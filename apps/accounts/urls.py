from django.urls import path
from .views import (
    LoginView, CheckSMSCodeView, SMSServiceStatusView, 
    UserDetailsView, UserDetailsByIdView, FAQListView, UpdateTelegramChatIdView,
    HealthCheckView
)

urlpatterns = [
    
    # Login (SMS kod yuborish)
    path('login/', LoginView.as_view(), name='login'),
    
    # SMS kod tekshirish va token berish
    path('check-sms-code/', CheckSMSCodeView.as_view(), name='check_sms_code'),
    
    # SMS servis statusini tekshirish
    path('sms-status/', SMSServiceStatusView.as_view(), name='sms_status'),
    
    # User details endpoints
    path('user/', UserDetailsView.as_view(), name='user_details'),
    path('user/<int:user_id>/', UserDetailsByIdView.as_view(), name='user_details_by_id'),
    
    # Telegram Chat ID update endpoint
    path('update-telegram-chat-id/', UpdateTelegramChatIdView.as_view(), name='update_telegram_chat_id'),
    
    # FAQ endpoints
    path('faq/', FAQListView.as_view(), name='faq_list'),
]