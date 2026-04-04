from django.urls import re_path

from apps.order.ws.consumers import MasterSosConsumer

websocket_urlpatterns = [
    re_path(r'^ws/sos/master/$', MasterSosConsumer.as_asgi()),
]
