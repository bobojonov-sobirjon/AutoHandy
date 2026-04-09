from django.urls import path
from apps.order.api import views

app_name = 'order'

urlpatterns = [
    path('standard/', views.StandardOrderCreateView.as_view(), name='standard-order-create'),
    path('sos/', views.SOSOrderCreateView.as_view(), name='sos-order-create'),
    path('custom-request/', views.CustomRequestCreateView.as_view(), name='custom-request-create'),
    path(
        'custom-request/<int:order_id>/offers/',
        views.CustomRequestOfferListCreateView.as_view(),
        name='custom-request-offers',
    ),
    path(
        'nearby-masters/',
        views.NearbyMasterCandidatesView.as_view(),
        name='nearby-master-candidates',
    ),
    path('available-slots/', views.AvailableTimeSlotsView.as_view(), name='available-time-slots'),
    path('add-services/', views.AddServicesToOrderView.as_view(), name='add-services-to-order'),
    path('services-list/', views.MasterServicesListView.as_view(), name='master-services-list'),
    path('add-master/', views.AddMasterToOrderView.as_view(), name='add-master-to-order'),
    path('', views.OrderListCreateView.as_view(), name='order-list-create'),
    path('<int:id>/', views.OrderDetailView.as_view(), name='order-detail'),
    path('by-user/', views.OrdersByUserView.as_view(), name='orders-by-user'),
    path('by-master/', views.OrdersByMasterView.as_view(), name='orders-by-master'),
    path('available/', views.AvailableOrdersForMasterView.as_view(), name='available-orders'),
    path('<int:order_id>/cancel/', views.CancelOrderView.as_view(), name='cancel-order'),
    path('<int:order_id>/status/', views.UpdateOrderStatusView.as_view(), name='update-status'),
    path('<int:order_id>/accept/', views.AcceptOrderView.as_view(), name='accept-order'),
    path(
        '<int:order_id>/preferred-time/',
        views.OrderMasterPreferredTimePatchView.as_view(),
        name='order-master-preferred-time',
    ),
    path('<int:order_id>/decline/', views.DeclineOrderView.as_view(), name='decline-order'),
    path('<int:order_id>/complete/', views.CompleteOrderView.as_view(), name='complete-order'),
    path(
        '<int:order_id>/work-completion-image/',
        views.UploadOrderWorkCompletionImageView.as_view(),
        name='order-work-completion-image',
    ),
    path('reviews/create/', views.CreateReviewView.as_view(), name='create-review'),
]
