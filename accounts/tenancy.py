"""Tenant scoping helpers."""
from django.db.models import QuerySet

from jobsites.models import Site, SiteAssignment


def visible_site_ids(user) -> list:
    if not user.workspace_id:
        return []
    if user.role == user.Role.OWNER:
        return list(Site.objects.filter(workspace_id=user.workspace_id).values_list("id", flat=True))
    return list(
        SiteAssignment.objects.filter(user=user, site__workspace_id=user.workspace_id).values_list(
            "site_id", flat=True
        )
    )


def filter_sites_for_user(qs: QuerySet, user) -> QuerySet:
    if user.role == user.Role.OWNER:
        return qs.filter(workspace_id=user.workspace_id)
    return qs.filter(workspace_id=user.workspace_id, id__in=visible_site_ids(user))


def assert_site_access(user, site) -> None:
    from rest_framework.exceptions import PermissionDenied

    if site.workspace_id != user.workspace_id:
        raise PermissionDenied("Site not found.")
    if user.role != user.Role.OWNER and site.id not in set(visible_site_ids(user)):
        raise PermissionDenied("You don't have access to this site.")
