from django.urls import path
from . import views

app_name = 'order'

urlpatterns = [
    # Order creation (NEW: separate endpoints for different order types)
    path('scheduled/', views.ScheduledOrderCreateView.as_view(), name='scheduled-order-create'),
    path('sos/', views.SOSOrderCreateView.as_view(), name='sos-order-create'),
    
    # Available time slots
    path('available-slots/', views.AvailableTimeSlotsView.as_view(), name='available-time-slots'),
    
    # Order services
    path('add-services/', views.AddServicesToOrderView.as_view(), name='add-services-to-order'),
    path('services-list/', views.MasterServicesListView.as_view(), name='master-services-list'),
    
    # Order masters management
    path('add-masters/', views.AddMastersToOrderView.as_view(), name='add-masters-to-order'),
    
    # Order CRUD operations
    path('', views.OrderListCreateView.as_view(), name='order-list-create'),
    path('<int:id>/', views.OrderDetailView.as_view(), name='order-detail'),
    
    # Order filtering
    path('by-user/', views.OrdersByUserView.as_view(), name='orders-by-user'),
    path('by-master/', views.OrdersByMasterView.as_view(), name='orders-by-master'),
    path('available/', views.AvailableOrdersForMasterView.as_view(), name='available-orders'),
    
    # Order status management
    path('<int:order_id>/status/', views.UpdateOrderStatusView.as_view(), name='update-status'),
    path('<int:order_id>/accept/', views.AcceptOrderView.as_view(), name='accept-order'),
    path('<int:order_id>/complete/', views.CompleteOrderView.as_view(), name='complete-order'),
    
    # Review endpoints (replaces old Rating API)
    path('reviews/create/', views.CreateReviewView.as_view(), name='create-review'),
]

