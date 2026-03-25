from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve
from django.conf import settings
from django.conf.urls.static import static

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from config.swagger_auth import SwaggerTokenView

urlpatterns = [
    path('admin/', admin.site.urls),
]

urlpatterns += [
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

urlpatterns += [
    path('api/auth/', include('apps.accounts.urls')),
    path('api/auth/oauth/token/', SwaggerTokenView.as_view(), name='swagger-oauth-token'),
    path('api/car/', include('apps.car.urls')),
    path('api/master/', include('apps.master.urls')),
    # path('api/order/', include('apps.order.urls')),
    path('api/categories/', include('apps.categories.urls')),
    # path('api/chat/', include('apps.chat.urls')),
]

urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += [re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT, }, ), ]