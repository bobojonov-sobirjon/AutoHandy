from django.urls import path
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
