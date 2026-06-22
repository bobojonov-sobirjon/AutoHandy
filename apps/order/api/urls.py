from django.urls import path
from apps.order.api import views
from apps.payment.api.views import OrderCheckoutPreviewView, OrderPaymentCardPatchView

app_name = 'order'

urlpatterns = [
    path('standard/', views.StandardOrderCreateView.as_view(), name='standard-order-create'),
    path('sos/', views.SOSOrderCreateView.as_view(), name='sos-order-create'),
    path('custom-request/', views.CustomRequestCreateView.as_view(), name='custom-request-create'),
    path('towing/estimate/', views.TowingEstimateView.as_view(), name='towing-estimate'),
    path('towing/', views.TowingCreateView.as_view(), name='towing-create'),
    path('truck/', views.TruckOrderCreateView.as_view(), name='truck-order-create'),
    path('truck/towing/', views.TruckTowingCreateView.as_view(), name='truck-towing-create'),
    path(
        'emergency/estimate-price/',
        views.EmergencyPriceEstimateView.as_view(),
        name='emergency-estimate-price',
    ),
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
    path(
        'order-service/<int:order_service_id>/count/',
        views.OrderServiceCountPatchView.as_view(),
        name='order-service-count',
    ),
    path(
        '<int:order_id>/extra-money/',
        views.OrderExtraMoneyPatchView.as_view(),
        name='order-extra-money',
    ),
    path(
        '<int:order_id>/extra-money/requests/',
        views.OrderExtraMoneyRequestCreateView.as_view(),
        name='order-extra-money-requests-create',
    ),
    path(
        'extra-money/requests/<int:request_id>/approve/',
        views.OrderExtraMoneyRequestApproveView.as_view(),
        name='order-extra-money-requests-approve',
    ),
    path(
        'extra-money/requests/<int:request_id>/reject/',
        views.OrderExtraMoneyRequestRejectView.as_view(),
        name='order-extra-money-requests-reject',
    ),
    path(
        'extra-money/requests/pending/',
        views.PendingExtraMoneyRequestsForClientView.as_view(),
        name='order-extra-money-requests-pending',
    ),
    path(
        '<int:order_id>/time-change/requests/',
        views.OrderTimeChangeRequestCreateView.as_view(),
        name='order-time-change-requests-create',
    ),
    path(
        'time-change/requests/<int:request_id>/approve/',
        views.OrderTimeChangeRequestApproveView.as_view(),
        name='order-time-change-requests-approve',
    ),
    path(
        'time-change/requests/<int:request_id>/reject/',
        views.OrderTimeChangeRequestRejectView.as_view(),
        name='order-time-change-requests-reject',
    ),
    path(
        'time-change/requests/pending/',
        views.PendingTimeChangeRequestsForClientView.as_view(),
        name='order-time-change-requests-pending',
    ),
    path(
        '<int:order_id>/service-add/requests/',
        views.OrderServiceAddRequestCreateView.as_view(),
        name='order-service-add-requests-create',
    ),
    path(
        'service-add/requests/<int:request_id>/approve/',
        views.OrderServiceAddRequestApproveView.as_view(),
        name='order-service-add-requests-approve',
    ),
    path(
        'service-add/requests/<int:request_id>/reject/',
        views.OrderServiceAddRequestRejectView.as_view(),
        name='order-service-add-requests-reject',
    ),
    path(
        'service-add/requests/pending/',
        views.PendingServiceAddRequestsForClientView.as_view(),
        name='order-service-add-requests-pending',
    ),
    path('services-list/', views.MasterServicesListView.as_view(), name='master-services-list'),
    path('add-master/', views.AddMasterToOrderView.as_view(), name='add-master-to-order'),
    path('', views.OrderListCreateView.as_view(), name='order-list-create'),
    path('<int:id>/', views.OrderDetailView.as_view(), name='order-detail'),
    path('by-user/', views.OrdersByUserView.as_view(), name='orders-by-user'),
    path('by-master/', views.OrdersByMasterView.as_view(), name='orders-by-master'),
    path(
        'master/incoming-sync/',
        views.MasterIncomingSyncView.as_view(),
        name='master-incoming-sync',
    ),
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
    path('<int:order_id>/payment-card/', OrderPaymentCardPatchView.as_view(), name='order-payment-card'),
    path('<int:order_id>/checkout-preview/', OrderCheckoutPreviewView.as_view(), name='order-checkout-preview'),
    path('<int:order_id>/complete/', views.CompleteOrderView.as_view(), name='complete-order'),
    path(
        '<int:order_id>/work-completion-image/',
        views.UploadOrderWorkCompletionImageView.as_view(),
        name='order-work-completion-image',
    ),
    path('reviews/create/', views.CreateReviewView.as_view(), name='create-review'),
]
