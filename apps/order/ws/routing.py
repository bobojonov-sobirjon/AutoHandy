from django.urls import re_path

from apps.order.ws.consumers import MasterSosConsumer, RiderCustomRequestConsumer

websocket_urlpatterns = [
    re_path(r'^ws/sos/master/$', MasterSosConsumer.as_asgi()),
    re_path(r'^ws/custom-request/rider/$', RiderCustomRequestConsumer.as_asgi()),
]
