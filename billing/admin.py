from django.contrib import admin

from billing.models import (
    BillingPayment,
    Invoice,
    PricingVersion,
    StorageSnapshot,
    Subscription,
    TaxRule,
    Wallet,
    WalletTransaction,
)

admin.site.register(PricingVersion)
admin.site.register(TaxRule)
admin.site.register(Subscription)
admin.site.register(Invoice)
admin.site.register(BillingPayment)
admin.site.register(StorageSnapshot)
admin.site.register(Wallet)
admin.site.register(WalletTransaction)
