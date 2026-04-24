from django.urls import path
from .views import (
    LoginView,
    CheckSMSCodeView,
    SMSServiceStatusView,
    UserDetailsView,
    UserLocationUpdateView,
    UserDetailsByIdView,
    UserProfileRegistrationView,
    EmailVerificationConfirmView,
    FAQListView,
    HealthCheckView,
    AppVersionView,
    AppVersionDetailView,
    UserDeviceMeView,
)

urlpatterns = [
    # App version endpoints
    path('app-version/', AppVersionView.as_view(), name='app_version'),
    path('app-version/<int:app_version_id>/', AppVersionDetailView.as_view(), name='app_version_detail'),
    # Login (SMS kod yuborish)
    path('login/', LoginView.as_view(), name='login'),
    
    # SMS kod tekshirish va token berish
    path('check-sms-code/', CheckSMSCodeView.as_view(), name='check_sms_code'),

    # Device registration (push notifications)
    path('device/', UserDeviceMeView.as_view(), name='user_device_me'),
    
    # SMS servis statusini tekshirish
    path('sms-status/', SMSServiceStatusView.as_view(), name='sms_status'),
    
    # User details endpoints
    path('user/', UserDetailsView.as_view(), name='user_details'),
    path('user/location/', UserLocationUpdateView.as_view(), name='user_location'),
    path('user/<int:user_id>/', UserDetailsByIdView.as_view(), name='user_details_by_id'),
    path(
        'user/register-profile/',
        UserProfileRegistrationView.as_view(),
        name='user_register_profile',
    ),
    path(
        'email-verification/',
        EmailVerificationConfirmView.as_view(),
        name='email_verification_confirm',
    ),
    
    
    # FAQ endpoints
    path('faq/', FAQListView.as_view(), name='faq_list'),
]