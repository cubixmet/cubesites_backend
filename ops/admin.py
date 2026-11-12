from django.contrib import admin

from ops.models import (
    ActivityLog,
    AppNotification,
    BackupJob,
    Note,
    PlatformSettings,
    Reminder,
    RetentionNotice,
    SupportCase,
    SupportNote,
)

admin.site.register(ActivityLog)
admin.site.register(AppNotification)
admin.site.register(BackupJob)
admin.site.register(SupportCase)
admin.site.register(SupportNote)
admin.site.register(RetentionNotice)
admin.site.register(PlatformSettings)
admin.site.register(Note)
admin.site.register(Reminder)
