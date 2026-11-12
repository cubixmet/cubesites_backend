from django.contrib import admin

from jobsites.models import Site, SiteAssignment, SiteStatusEvent


class StatusInline(admin.TabularInline):
    model = SiteStatusEvent
    extra = 0
    readonly_fields = ("status", "at", "by")


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "status", "primary_phone", "start_date")
    list_filter = ("status",)
    search_fields = ("name", "primary_phone", "address")
    inlines = [StatusInline]


@admin.register(SiteAssignment)
class SiteAssignmentAdmin(admin.ModelAdmin):
    list_display = ("site", "user", "created_at")
