from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from accounts.views import (
    StaffActiveView,
    StaffDetailView,
    StaffListCreateView,
    WorkspaceDetailView,
)
from billing.views import BillingCurrentView, InvoiceListView, IssueInvoiceView, ManualPaymentView, WalletView
from jobsites.views import (
    SiteAssignView,
    SiteDetailView,
    SiteListCreateView,
    SiteStatusView,
    SiteTotalsView,
)
from ledger.views import (
    EntryDetailView,
    EntryListCreateView,
    ItemListCreateView,
    ItemRenameView,
    MediaDeleteView,
    MediaListUploadView,
)
from ops import admin_api
from ops.drive_views import (
    DriveBackupListView,
    DriveBackupRunView,
    DriveCallbackView,
    DriveConnectView,
    DriveDisconnectView,
    DriveStatusView,
)
from ops.notes_views import (
    NoteDetailView,
    NoteListCreateView,
    ReminderDetailView,
    ReminderListCreateView,
    ReminderNotifyView,
)
from ops.views import (
    ActivityListView,
    NotificationListView,
    NotificationReadAllView,
    NotificationReadView,
)

contractor_patterns = [
    path("workspace/", WorkspaceDetailView.as_view()),
    path("staff/", StaffListCreateView.as_view()),
    path("staff/<uuid:pk>/", StaffDetailView.as_view()),
    path("staff/<uuid:pk>/active/", StaffActiveView.as_view()),
    path("sites/", SiteListCreateView.as_view()),
    path("sites/<uuid:pk>/", SiteDetailView.as_view()),
    path("sites/<uuid:pk>/totals/", SiteTotalsView.as_view()),
    path("sites/<uuid:pk>/status/", SiteStatusView.as_view()),
    path("sites/<uuid:pk>/assignments/", SiteAssignView.as_view()),
    path("items/", ItemListCreateView.as_view()),
    path("items/<uuid:pk>/", ItemRenameView.as_view()),
    path("entries/", EntryListCreateView.as_view()),
    path("entries/<uuid:pk>/", EntryDetailView.as_view()),
    path("media/", MediaListUploadView.as_view()),
    path("media/<uuid:pk>/", MediaDeleteView.as_view()),
    path("billing/current/", BillingCurrentView.as_view()),
    path("wallet/", WalletView.as_view()),
    path("invoices/", InvoiceListView.as_view()),
    path("invoices/current/", IssueInvoiceView.as_view()),
    path("invoices/<uuid:pk>/payments/", ManualPaymentView.as_view()),
    path("activity/", ActivityListView.as_view()),
    path("notifications/", NotificationListView.as_view()),
    path("notifications/read-all/", NotificationReadAllView.as_view()),
    path("notifications/<uuid:pk>/read/", NotificationReadView.as_view()),
    path("notes/", NoteListCreateView.as_view()),
    path("notes/<uuid:pk>/", NoteDetailView.as_view()),
    path("reminders/", ReminderListCreateView.as_view()),
    path("reminders/<uuid:pk>/", ReminderDetailView.as_view()),
    path("reminders/<uuid:pk>/notify/", ReminderNotifyView.as_view()),
    path("drive/", DriveStatusView.as_view()),
    path("drive/connect/", DriveConnectView.as_view()),
    path("drive/callback/", DriveCallbackView.as_view()),
    path("drive/disconnect/", DriveDisconnectView.as_view()),
    path("drive/backup/", DriveBackupRunView.as_view()),
    path("drive/backups/", DriveBackupListView.as_view()),
]

admin_patterns = [
    path("overview/", admin_api.AdminOverviewView.as_view()),
    path("contractors/", admin_api.AdminContractorListView.as_view()),
    path("contractors/<uuid:pk>/", admin_api.AdminContractorDetailView.as_view()),
    path("contractors/<uuid:pk>/status/", admin_api.AdminContractorStatusView.as_view()),
    path("sites/", admin_api.AdminSitesView.as_view()),
    path("staff/", admin_api.AdminStaffView.as_view()),
    path("payments/", admin_api.AdminPaymentListView.as_view()),
    path("payments/<uuid:pk>/review/", admin_api.AdminPaymentReviewView.as_view()),
    path("wallets/", admin_api.AdminWalletListView.as_view()),
    path("wallets/transactions/", admin_api.AdminWalletTransactionListView.as_view()),
    path("contractors/<uuid:pk>/wallet/", admin_api.AdminContractorWalletView.as_view()),
    path("pricing-versions/", admin_api.AdminPricingListCreateView.as_view()),
    path("tax-rules/", admin_api.AdminTaxListCreateView.as_view()),
    path("subscriptions/", admin_api.AdminSubscriptionListView.as_view()),
    path("invoices/", admin_api.AdminInvoiceListView.as_view()),
    path("storage/snapshots/", admin_api.AdminStorageSnapshotListView.as_view()),
    path("storage/snapshots/<uuid:pk>/corrections/", admin_api.AdminStorageCorrectView.as_view()),
    path("backups/", admin_api.AdminBackupListView.as_view()),
    path("backups/<uuid:pk>/retry/", admin_api.AdminBackupRetryView.as_view()),
    path("support/cases/", admin_api.AdminSupportListView.as_view()),
    path("support/cases/<uuid:pk>/", admin_api.AdminSupportDetailView.as_view()),
    path("support/cases/<uuid:pk>/notes/", admin_api.AdminSupportNoteView.as_view()),
    path("notifications/", admin_api.AdminNotificationListView.as_view()),
    path("activity/", admin_api.AdminActivityView.as_view()),
    path("settings/", admin_api.AdminSettingsView.as_view()),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/v1/", include((contractor_patterns, "v1"))),
    path("api/admin/", include((admin_patterns, "admin-api"))),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
