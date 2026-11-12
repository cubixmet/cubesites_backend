from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from accounts.models import User, Workspace


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("business_name", "email", "status", "district", "created_at")
    search_fields = ("business_name", "email", "phone", "owner_name")
    list_filter = ("status",)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("email", "display_name", "role", "workspace", "is_platform_admin", "is_active")
    list_filter = ("role", "is_platform_admin", "is_active")
    search_fields = ("email", "username", "first_name", "last_name", "phone")
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "CuboSites",
            {"fields": ("workspace", "phone", "role", "permissions", "is_platform_admin", "last_site")},
        ),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (None, {"fields": ("workspace", "phone", "role", "is_platform_admin")}),
    )
