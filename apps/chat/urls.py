from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    # Chat rooms
    path('rooms/', views.ChatRoomListCreateView.as_view(), name='chat-rooms'),
    path('rooms/<int:room_id>/', views.ChatRoomDetailView.as_view(), name='chat-room-detail'),
    
    # Messages
    path('rooms/<int:room_id>/messages/', views.ChatMessagesView.as_view(), name='chat-messages'),
    path('rooms/<int:room_id>/mark-read/', views.MarkAsReadView.as_view(), name='mark-as-read'),
]
