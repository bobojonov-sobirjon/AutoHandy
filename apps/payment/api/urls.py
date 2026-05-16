from django.urls import path

from apps.payment.api import views

app_name = 'payment'

urlpatterns = [
    path('saved-cards/', views.SavedCardListCreateView.as_view(), name='saved-cards'),
    path('saved-cards/<int:pk>/', views.SavedCardDetailView.as_view(), name='saved-card-detail'),
]
