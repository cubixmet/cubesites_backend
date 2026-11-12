"""Contractor permission enforcement.

UI toggles are not security. Every sensitive read/write must go through these helpers.
Related rules (when saving staff permissions):
  - viewFinancials / reports / manageItems / uploadMedia / createEntries / editEntries /
    manageStaffSites all require viewSite
  - editEntries requires createEntries
  - reports requires viewFinancials (exporting money without viewing it is blocked)
  - manageStaffSites requires viewFinancials
"""
from __future__ import annotations

from typing import Iterable

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import PERMISSION_KEYS

# Child → required parents (all must be true when child is true).
PERMISSION_REQUIRES: dict[str, tuple[str, ...]] = {
    "viewFinancials": ("viewSite",),
    "createEntries": ("viewSite",),
    "editEntries": ("viewSite", "createEntries"),
    "manageItems": ("viewSite",),
    "uploadMedia": ("viewSite",),
    "reports": ("viewSite", "viewFinancials"),
    "manageStaffSites": ("viewSite", "viewFinancials"),
}


def sanitize_permissions(raw: dict | None) -> dict:
    """Keep only known keys; force related parents on when a child is enabled."""
    perms = {k: False for k in PERMISSION_KEYS}
    if isinstance(raw, dict):
        for k in PERMISSION_KEYS:
            perms[k] = bool(raw.get(k))
    # Apply dependencies until stable (editEntries → createEntries → viewSite, etc.)
    changed = True
    while changed:
        changed = False
        for child, parents in PERMISSION_REQUIRES.items():
            if not perms.get(child):
                continue
            for p in parents:
                if not perms.get(p):
                    perms[p] = True
                    changed = True
    return perms


def deny(detail: str = "Permission denied.") -> None:
    raise PermissionDenied(detail)


def require_user_perm(user, key: str, detail: str | None = None) -> None:
    if not user or not getattr(user, "is_authenticated", False):
        deny(detail or "Authentication required.")
    if not user.has_perm_key(key):
        deny(detail or f"Missing permission: {key}.")


def require_any_user_perm(user, keys: Iterable[str], detail: str | None = None) -> None:
    if not user or not getattr(user, "is_authenticated", False):
        deny(detail or "Authentication required.")
    if any(user.has_perm_key(k) for k in keys):
        return
    deny(detail or f"Missing one of: {', '.join(keys)}.")


def can_view_financials(user) -> bool:
    return bool(user and user.has_perm_key("viewFinancials"))


def redact_money_fields(payload: dict) -> dict:
    """Null out paise / amount fields for users without viewFinancials."""
    out = dict(payload)
    for k in (
        "unit_price_paise",
        "unitPricePaise",
        "total_paise",
        "totalPaise",
        "amount",
        "amountPaise",
        "subtotalPaise",
        "taxPaise",
    ):
        if k in out:
            out[k] = None
    before = out.get("before")
    after = out.get("after")
    if isinstance(before, dict):
        out["before"] = {bk: (None if "amount" in bk.lower() or bk == "amount" else bv) for bk, bv in before.items()}
        if "amount" in before:
            out["before"]["amount"] = None
    if isinstance(after, dict):
        out["after"] = {ak: (None if "amount" in ak.lower() or ak == "amount" else av) for ak, av in after.items()}
        if "amount" in after:
            out["after"]["amount"] = None
    return out


class IsPlatformAdmin(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_platform_admin)


class IsWorkspaceUser(BasePermission):
    """Authenticated contractor user with an active workspace (not platform admin)."""

    message = "Workspace access required."

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated and u.workspace_id and not u.is_platform_admin):
            return False
        if not u.is_active:
            self.message = "This account is disabled."
            return False
        ws = u.workspace
        if ws is None:
            return False
        if ws.status == ws.Status.SUSPENDED:
            self.message = "Workspace is suspended."
            return False
        return True


class HasPerm(BasePermission):
    """Require a contractor permission key (owner always passes via has_perm_key)."""

    key = ""
    message = "Permission denied."

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated and u.workspace_id):
            return False
        key = getattr(view, "permission_key", None) or self.key
        if not key:
            return True
        if request.method in SAFE_METHODS and key.startswith("manage"):
            pass
        if not u.has_perm_key(key):
            self.message = f"Missing permission: {key}."
            return False
        return True


def require_perm(key: str):
    class _P(HasPerm):
        pass

    _P.key = key
    return _P


class HasAnyPerm(BasePermission):
    keys: tuple[str, ...] = ()
    message = "Permission denied."

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated and u.workspace_id):
            return False
        keys = getattr(view, "permission_keys", None) or self.keys
        if not keys:
            return True
        if any(u.has_perm_key(k) for k in keys):
            return True
        self.message = f"Missing one of: {', '.join(keys)}."
        return False


def require_any_perm(*keys: str):
    class _P(HasAnyPerm):
        pass

    _P.keys = keys
    return _P
