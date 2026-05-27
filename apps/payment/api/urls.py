from django.urls import path

from apps.payment.api import views
from apps.payment.api.stripe_webhook_view import StripeWebhookView

app_name = 'payment'

urlpatterns = [
    path('saved-cards/', views.SavedCardListCreateView.as_view(), name='saved-cards'),
    path('saved-cards/<int:pk>/', views.SavedCardDetailView.as_view(), name='saved-card-detail'),
    path('stripe/webhook/', StripeWebhookView.as_view(), name='stripe-webhook'),
]
