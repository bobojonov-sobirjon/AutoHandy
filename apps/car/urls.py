from django.urls import path
from .views import CarListCreateView, CarDetailView, CarStatsView

urlpatterns = [
    # Car API endpoints
    path('', CarListCreateView.as_view(), name='car-list-create'),
    path('<int:pk>/', CarDetailView.as_view(), name='car-detail'),
    path('stats/', CarStatsView.as_view(), name='car-stats'),
]
