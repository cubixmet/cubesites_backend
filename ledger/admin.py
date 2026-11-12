from django.contrib import admin

from ledger.models import Attachment, Entry, Item


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "workspace")
    list_filter = ("type",)


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ("description", "type", "site", "total_paise", "date")
    list_filter = ("type",)


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "site", "size_bytes", "date")
    list_filter = ("kind",)
