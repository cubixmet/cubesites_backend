"""Google ID-token verification, OTP email, and owner workspace provisioning."""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import EmailOTP, User, Workspace, default_permissions


def hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) >= 10:
        return digits[-10:]
    return digits


def verify_google_id_token(credential: str) -> dict:
    """Verify GIS ID token; returns {sub, email, email_verified, name, picture}."""
    client_id = settings.GOOGLE_CLIENT_ID
    if not client_id:
        raise ValidationError({"detail": "Google Sign-In is not configured."})
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError as e:
        raise ValidationError({"detail": "Google auth library is not installed."}) from e

    try:
        info = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            client_id,
            clock_skew_in_seconds=10,
        )
    except Exception as e:
        raise ValidationError({"detail": f"Invalid Google credential: {e}"}) from e

    if info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise ValidationError({"detail": "Invalid Google token issuer."})
    email = normalize_email(info.get("email") or "")
    if not email:
        raise ValidationError({"detail": "Google account has no email."})
    if not info.get("email_verified", False):
        raise ValidationError({"detail": "Google email is not verified."})
    return {
        "sub": str(info["sub"]),
        "email": email,
        "name": (info.get("name") or email.split("@")[0]).strip(),
        "picture": info.get("picture") or "",
    }


def send_otp_email(email: str, code: str, *, purpose: str = EmailOTP.Purpose.SIGNUP) -> None:
    minutes = getattr(settings, "OTP_EXPIRY_MINUTES", 10)
    if purpose == EmailOTP.Purpose.PASSWORD_RESET:
        subject = "Your CuboSites password reset code"
        intro = "Your CuboSites password reset code is"
    else:
        subject = "Your CuboSites verification code"
        intro = "Your CuboSites verification code is"
    body = (
        f"{intro}: {code}\n\n"
        f"It expires in {minutes} minutes. If you did not request this, ignore this email.\n"
    )
    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [email],
        fail_silently=False,
    )


def _issue_otp(*, email: str, purpose: str, payload: dict | None = None) -> EmailOTP:
    email = normalize_email(email)
    EmailOTP.objects.filter(email=email, purpose=purpose).delete()
    code = f"{secrets.randbelow(1_000_000):06d}"
    minutes = getattr(settings, "OTP_EXPIRY_MINUTES", 10)
    otp = EmailOTP.objects.create(
        email=email,
        code_hash=hash_otp(code),
        purpose=purpose,
        payload=payload or {},
        expires_at=timezone.now() + timedelta(minutes=minutes),
    )
    send_otp_email(email, code, purpose=purpose)
    return otp


def _consume_otp(*, email: str, code: str, purpose: str) -> dict:
    email = normalize_email(email)
    otp = (
        EmailOTP.objects.filter(email=email, purpose=purpose)
        .order_by("-created_at")
        .first()
    )
    if not otp:
        raise ValidationError({"detail": "No verification code found. Request a new one."})
    if otp.expires_at < timezone.now():
        otp.delete()
        raise ValidationError({"detail": "Verification code expired. Request a new one."})
    if otp.attempts >= 5:
        otp.delete()
        raise ValidationError({"detail": "Too many attempts. Request a new code."})
    otp.attempts += 1
    otp.save(update_fields=["attempts"])
    if otp.code_hash != hash_otp(code.strip()):
        raise ValidationError({"detail": "Incorrect verification code."})
    payload = dict(otp.payload or {})
    otp.delete()
    return payload


def issue_signup_otp(*, email: str, payload: dict) -> EmailOTP:
    return _issue_otp(email=email, purpose=EmailOTP.Purpose.SIGNUP, payload=payload)


def consume_signup_otp(*, email: str, code: str) -> dict:
    return _consume_otp(email=email, code=code, purpose=EmailOTP.Purpose.SIGNUP)


def issue_password_reset_otp(*, email: str) -> EmailOTP:
    return _issue_otp(
        email=email,
        purpose=EmailOTP.Purpose.PASSWORD_RESET,
        payload={"email": normalize_email(email)},
    )


def consume_password_reset_otp(*, email: str, code: str) -> dict:
    return _consume_otp(email=email, code=code, purpose=EmailOTP.Purpose.PASSWORD_RESET)


@transaction.atomic
def provision_owner_account(
    *,
    email: str,
    name: str,
    phone: str = "",
    business_name: str = "",
    password: str | None = None,
    google_sub: str = "",
    auth_provider: str = "password",
    email_verified: bool = False,
) -> tuple[User, Workspace]:
    email = normalize_email(email)
    if User.objects.filter(email__iexact=email).exists():
        raise ValidationError({"detail": "An account with this email already exists."})

    display = (name or email.split("@")[0]).strip()
    biz = (business_name or f"{display}'s Workspace").strip()
    first, *rest = display.split(" ", 1)

    ws = Workspace.objects.create(
        business_name=biz,
        owner_name=display,
        phone=phone or "",
        email=email,
    )
    user = User(
        username=email,
        email=email,
        workspace=ws,
        phone=phone or "",
        role=User.Role.OWNER,
        permissions=default_permissions("owner"),
        first_name=first,
        last_name=rest[0] if rest else "",
        email_verified=email_verified,
        google_sub=google_sub or "",
        auth_provider=auth_provider,
    )
    if password:
        user.set_password(password)
    else:
        user.set_unusable_password()
    user.save()
    return user, ws


def find_user_by_google(sub: str, email: str) -> User | None:
    if sub:
        u = User.objects.filter(google_sub=sub).first()
        if u:
            return u
    return User.objects.filter(email__iexact=email).first()
