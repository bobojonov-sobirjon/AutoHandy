from django.urls import path
from .views import (
    MasterProfileView, MasterDetailsView, MasterListView,
    MasterEmployeeView, MasterFilterChoicesView, MastersByUserView,
    AddServiceItemsView, UpdateServiceItemView, DeleteServiceItemView,
    AddMasterImagesView, UpdateMasterImageView, DeleteMasterImageView,
    MasterEmployeeListView
)

urlpatterns = [
    # Masters endpoints
    path('masters/', MasterProfileView.as_view(), name='master-profile'),
    path('masters/list/', MasterListView.as_view(), name='master-list'),
    path('masters/by-user/', MastersByUserView.as_view(), name='masters-by-user'),
    path('masters/filter-choices/', MasterFilterChoicesView.as_view(), name='master-filter-choices'),
    path('masters/<int:master_id>/', MasterDetailsView.as_view(), name='master-details'),
    
    # Master Employees endpoints
    path('masters/employees/', MasterEmployeeView.as_view(), name='master-employees'),
    path('employees/', MasterEmployeeListView.as_view(), name='master-employee-list'),
    
    # Master Service Items endpoints
    path('service-items/', AddServiceItemsView.as_view(), name='add-service-items'),
    path('service-items/<int:item_id>/', UpdateServiceItemView.as_view(), name='update-service-item'),
    path('service-items/<int:item_id>/delete/', DeleteServiceItemView.as_view(), name='delete-service-item'),
    
    # Master Images endpoints
    path('images/', AddMasterImagesView.as_view(), name='add-master-images'),
    path('images/<int:image_id>/', UpdateMasterImageView.as_view(), name='update-master-image'),
    path('images/<int:image_id>/delete/', DeleteMasterImageView.as_view(), name='delete-master-image'),
]
