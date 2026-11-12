"""Public auth endpoints: Google Sign-In, email OTP signup, password login."""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.auth_services import (
    consume_password_reset_otp,
    consume_signup_otp,
    find_user_by_google,
    issue_password_reset_otp,
    issue_signup_otp,
    normalize_email,
    normalize_phone,
    provision_owner_account,
    verify_google_id_token,
)
from accounts.models import User, Workspace
from accounts.serializers import LoginSerializer, UserSerializer, WorkspaceSerializer
from accounts.views import tokens_for
from ops.models import ActivityLog


def _auth_response(user: User) -> Response:
    ActivityLog.objects.create(
        workspace=user.workspace,
        actor=user,
        action="login",
        target_type="session",
        summary=f"Signed in as {user.display_name}",
        is_platform=user.is_platform_admin,
    )
    if user.workspace_id:
        Workspace.objects.filter(pk=user.workspace_id).update(last_activity_at=timezone.now())
    return Response(
        {
            "user": UserSerializer(user).data,
            "workspace": WorkspaceSerializer(user.workspace).data if user.workspace_id else None,
            "tokens": tokens_for(user),
        }
    )


class AuthConfigView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        client_id = (settings.GOOGLE_CLIENT_ID or "").strip()
        return Response(
            {
                "googleClientId": client_id,
                "googleEnabled": bool(client_id),
                "googleRedirectUri": getattr(settings, "GOOGLE_REDIRECT_URI", "") or "",
                "otpExpiryMinutes": getattr(settings, "OTP_EXPIRY_MINUTES", 10),
            }
        )


class GoogleAuthView(APIView):
    """Exchange a Google Identity Services ID token for app JWTs.

    New owners must pass businessName (+ optional phone) on first sign-in.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        credential = request.data.get("credential") or request.data.get("idToken") or ""
        if not credential:
            return Response({"detail": "credential is required."}, status=400)
        info = verify_google_id_token(credential)
        user = find_user_by_google(info["sub"], info["email"])

        if user:
            if not user.is_active:
                return Response({"detail": "This account is disabled."}, status=403)
            if user.workspace_id and user.workspace.status == Workspace.Status.SUSPENDED:
                return Response({"detail": "Workspace is suspended."}, status=403)
            changed = False
            if not user.google_sub:
                user.google_sub = info["sub"]
                changed = True
            if not user.email_verified:
                user.email_verified = True
                changed = True
            if user.auth_provider == "password":
                user.auth_provider = "mixed"
                changed = True
            if changed:
                user.save(update_fields=["google_sub", "email_verified", "auth_provider"])
            if user.is_platform_admin:
                return Response(
                    {"detail": "Use the Super Admin portal for platform accounts."},
                    status=403,
                )
            return _auth_response(user)

        business_name = (request.data.get("businessName") or request.data.get("business_name") or "").strip()
        phone = (request.data.get("phone") or "").strip()
        if not business_name:
            return Response(
                {
                    "detail": "Complete signup with your business name.",
                    "code": "signup_required",
                    "email": info["email"],
                    "name": info["name"],
                },
                status=409,
            )

        user, _ws = provision_owner_account(
            email=info["email"],
            name=info["name"],
            phone=phone,
            business_name=business_name,
            google_sub=info["sub"],
            auth_provider="google",
            email_verified=True,
        )
        return _auth_response(user)


class SignupStartView(APIView):
    """Start email+password signup — sends OTP to email (phone is not used for OTP)."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = normalize_email(request.data.get("email") or "")
        password = request.data.get("password") or ""
        name = (request.data.get("name") or "").strip()
        phone = (request.data.get("phone") or "").strip()
        business_name = (request.data.get("businessName") or request.data.get("business_name") or "").strip()

        errors = {}
        if not email or "@" not in email:
            errors["email"] = "Enter a valid email address."
        if len(password) < 8:
            errors["password"] = "Password must be at least 8 characters."
        if len(name) < 2:
            errors["name"] = "Enter your full name."
        if len(business_name) < 2:
            errors["businessName"] = "Enter your business / company name."
        if phone and len(normalize_phone(phone)) < 10:
            errors["phone"] = "Enter a valid 10-digit phone number."
        if errors:
            return Response({"detail": "Validation failed.", "errors": errors}, status=400)

        if User.objects.filter(email__iexact=email).exists():
            return Response({"detail": "An account with this email already exists. Sign in instead."}, status=400)

        try:
            issue_signup_otp(
                email=email,
                payload={
                    "email": email,
                    "password_hash": make_password(password),
                    "name": name,
                    "phone": phone,
                    "business_name": business_name,
                },
            )
        except Exception as e:
            return Response(
                {"detail": f"Could not send verification email. {e}"},
                status=502,
            )
        return Response(
            {
                "ok": True,
                "email": email,
                "message": "We sent a 6-digit verification code to your email.",
                "expiresInMinutes": getattr(settings, "OTP_EXPIRY_MINUTES", 10),
            }
        )


class SignupVerifyView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = normalize_email(request.data.get("email") or "")
        code = (request.data.get("otp") or request.data.get("code") or "").strip()
        if not email or not code:
            return Response({"detail": "email and otp are required."}, status=400)
        payload = consume_signup_otp(email=email, code=code)
        if User.objects.filter(email__iexact=email).exists():
            return Response({"detail": "An account with this email already exists."}, status=400)

        user, _ws = provision_owner_account(
            email=payload["email"],
            name=payload.get("name") or "",
            phone=payload.get("phone") or "",
            business_name=payload.get("business_name") or "",
            auth_provider="password",
            email_verified=True,
        )
        # Apply the pre-hashed password from signup start.
        user.password = payload["password_hash"]
        user.save(update_fields=["password"])
        return _auth_response(user)


class SignupResendView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = normalize_email(request.data.get("email") or "")
        from accounts.models import EmailOTP

        prev = (
            EmailOTP.objects.filter(email=email, purpose=EmailOTP.Purpose.SIGNUP)
            .order_by("-created_at")
            .first()
        )
        if not prev:
            return Response({"detail": "No pending signup for this email. Start signup again."}, status=400)
        try:
            issue_signup_otp(email=email, payload=prev.payload)
        except Exception as e:
            return Response({"detail": f"Could not send verification email. {e}"}, status=502)
        return Response({"ok": True, "message": "A new verification code was sent."})


class LoginView(APIView):
    """Email or phone + password. OTP is not required at login time."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        ser = LoginSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        user = ser.validated_data["user"]
        # Password-registered owners must verify email before first login.
        if (
            user.auth_provider in ("password", "mixed")
            and user.role == User.Role.OWNER
            and not user.email_verified
            and not user.is_platform_admin
        ):
            return Response(
                {
                    "detail": "Verify your email before signing in.",
                    "code": "email_unverified",
                },
                status=403,
            )
        return _auth_response(user)


class PasswordForgotView(APIView):
    """Send a password-reset OTP to email. Always returns the same message (no email leak)."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = normalize_email(request.data.get("email") or "")
        if not email or "@" not in email:
            return Response({"detail": "Enter a valid email address.", "errors": {"email": "Enter a valid email address."}}, status=400)

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        # Only email OTP for accounts that can use password login (not platform portal).
        if user and not user.is_platform_admin:
            try:
                issue_password_reset_otp(email=email)
            except Exception as e:
                return Response({"detail": f"Could not send reset email. {e}"}, status=502)

        return Response(
            {
                "ok": True,
                "email": email,
                "message": "If an account exists for that email, we sent a 6-digit reset code.",
                "expiresInMinutes": getattr(settings, "OTP_EXPIRY_MINUTES", 10),
            }
        )


class PasswordResetView(APIView):
    """Verify OTP and set a new password."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = normalize_email(request.data.get("email") or "")
        code = (request.data.get("otp") or request.data.get("code") or "").strip()
        password = request.data.get("password") or request.data.get("newPassword") or ""

        errors = {}
        if not email or "@" not in email:
            errors["email"] = "Enter a valid email address."
        if not code:
            errors["otp"] = "Enter the 6-digit code from your email."
        if len(password) < 8:
            errors["password"] = "Password must be at least 8 characters."
        if errors:
            return Response({"detail": "Validation failed.", "errors": errors}, status=400)

        consume_password_reset_otp(email=email, code=code)

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if not user or user.is_platform_admin:
            return Response({"detail": "No account found for this email."}, status=400)

        user.set_password(password)
        fields = ["password"]
        if not user.email_verified:
            user.email_verified = True
            fields.append("email_verified")
        if user.auth_provider == "google":
            user.auth_provider = "mixed"
            fields.append("auth_provider")
        user.save(update_fields=fields)

        return Response(
            {
                "ok": True,
                "message": "Password updated. You can sign in with your email and new password.",
            }
        )


class PasswordResetResendView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = normalize_email(request.data.get("email") or "")
        if not email or "@" not in email:
            return Response({"detail": "Enter a valid email address."}, status=400)

        from accounts.models import EmailOTP

        prev = (
            EmailOTP.objects.filter(email=email, purpose=EmailOTP.Purpose.PASSWORD_RESET)
            .order_by("-created_at")
            .first()
        )
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if not prev and not (user and not user.is_platform_admin):
            return Response({"detail": "No pending password reset for this email. Start again."}, status=400)
        try:
            issue_password_reset_otp(email=email)
        except Exception as e:
            return Response({"detail": f"Could not send reset email. {e}"}, status=502)
        return Response({"ok": True, "message": "A new reset code was sent."})
