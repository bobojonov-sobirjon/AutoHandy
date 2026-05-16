from django.contrib import admin

from apps.payment.models import SavedCard


@admin.register(SavedCard)
class SavedCardAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'holder_role', 'brand', 'last4', 'is_default', 'is_active', 'created_at')
    list_filter = ('holder_role', 'is_active', 'is_default')
    search_fields = ('user__email', 'user__phone_number', 'stripe_payment_method_id', 'stripe_customer_id')
