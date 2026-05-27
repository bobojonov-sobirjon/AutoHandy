from django.urls import path
from apps.master.api.checkout_history_view import MasterCheckoutHistoryView
from apps.master.api.stripe_balance_view import MasterStripeBalanceView
# Legacy hosted onboarding / manual acct_ link (replaced by bank-account API):
# from apps.master.api.stripe_connect_link_view import MasterStripeConnectLinkView
# from apps.master.api.stripe_connect_onboarding_view import MasterStripeConnectOnboardingView
from apps.master.api.stripe_connect_bank_view import (
    MasterStripeConnectBankAccountView,
    MasterStripeConnectCompleteSetupView,
)
from apps.master.api.stripe_identity_view import (
    MasterStripeIdentityStartView,
    MasterStripeIdentityStatusView,
)
from apps.master.api.views import (
    MasterProfileView, MasterDetailsView, MasterListView,
    MasterFilterChoicesView, MastersByUserView,
    AddServiceItemsView, UpdateServiceItemView, DeleteServiceItemView,
    AddMasterImagesView, UpdateMasterImageView, DeleteMasterImageView,
    MasterScheduleListBulkView, MasterScheduleDayDetailView,
    MasterBusySlotListCreateView, MasterBusySlotDetailView,
    MasterServiceCardsView,
    MasterServiceCategorySuggestionsView,
)

urlpatterns = [
    # --- Stripe Master: Identity verification ---
    path(
        'stripe-identity/status/',
        MasterStripeIdentityStatusView.as_view(),
        name='master-stripe-identity-status',
    ),
    path(
        'stripe-identity/start/',
        MasterStripeIdentityStartView.as_view(),
        name='master-stripe-identity-start',
    ),
    # --- Stripe Master: primary (Instacart-style direct deposit) ---
    path(
        'stripe-connect/bank-account/',
        MasterStripeConnectBankAccountView.as_view(),
        name='master-stripe-connect-bank-account',
    ),
    path(
        'stripe-connect/complete-setup/',
        MasterStripeConnectCompleteSetupView.as_view(),
        name='master-stripe-connect-complete-setup',
    ),
    path('stripe-balance/', MasterStripeBalanceView.as_view(), name='master-stripe-balance'),
    path('checkout-history/', MasterCheckoutHistoryView.as_view(), name='master-checkout-history'),
    # --- Legacy (Stripe-hosted onboarding / manual acct_ link) — uncomment if needed ---
    # path(
    #     'stripe-connect/onboarding/',
    #     MasterStripeConnectOnboardingView.as_view(),
    #     name='master-stripe-connect-onboarding',
    # ),
    # path('stripe-connect/', MasterStripeConnectLinkView.as_view(), name='master-stripe-connect'),
    path('masters/', MasterProfileView.as_view(), name='master-profile'),
    path('masters/list/', MasterListView.as_view(), name='master-list'),
    # path('masters/by-user/', MastersByUserView.as_view(), name='masters-by-user'),
    # path('masters/filter-choices/', MasterFilterChoicesView.as_view(), name='master-filter-choices'),
    path(
        'masters/<int:master_id>/service-category-suggestions/',
        MasterServiceCategorySuggestionsView.as_view(),
        name='master-service-category-suggestions',
    ),
    path('masters/<int:master_id>/', MasterDetailsView.as_view(), name='master-details'),
    path('service-items/', AddServiceItemsView.as_view(), name='add-service-items'),
    path('service-items/<int:item_id>/', UpdateServiceItemView.as_view(), name='update-service-item'),
    path('service-items/<int:item_id>/delete/', DeleteServiceItemView.as_view(), name='delete-service-item'),
    path('images/', AddMasterImagesView.as_view(), name='add-master-images'),
    path('images/<int:image_id>/', UpdateMasterImageView.as_view(), name='update-master-image'),
    path('images/<int:image_id>/delete/', DeleteMasterImageView.as_view(), name='delete-master-image'),
    path('schedule/', MasterScheduleListBulkView.as_view(), name='master-schedule'),
    path('schedule/<int:pk>/', MasterScheduleDayDetailView.as_view(), name='master-schedule-day'),
    path('busy-slots/', MasterBusySlotListCreateView.as_view(), name='master-busy-slots'),
    path('busy-slots/<int:pk>/', MasterBusySlotDetailView.as_view(), name='master-busy-slot-detail'),
    path('service-cards/', MasterServiceCardsView.as_view(), name='master-service-cards'),
]
