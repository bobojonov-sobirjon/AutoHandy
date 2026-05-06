from django.urls import re_path

from apps.order.ws.consumers import (
    MasterSosConsumer,
    RiderCustomRequestConsumer,
    OrderUserEventsConsumer,
    OrderMasterEventsConsumer,
)

websocket_urlpatterns = [
    re_path(r'^ws/sos/master/$', MasterSosConsumer.as_asgi()),
    # Legacy clients may pass JWT token in the path instead of query string:
    # /ws/sos/master/token=<jwt>  (no trailing slash)
    re_path(r'^ws/sos/master/token=(?P<token>[^/]+)$', MasterSosConsumer.as_asgi()),
    # Also accept /ws/sos/master/<jwt> (no "token=" prefix).
    re_path(r'^ws/sos/master/(?P<token>[^/]+)$', MasterSosConsumer.as_asgi()),
    re_path(r'^ws/custom-request/rider/$', RiderCustomRequestConsumer.as_asgi()),
    re_path(r'^ws/order/user/$', OrderUserEventsConsumer.as_asgi()),
    re_path(r'^ws/order/master/$', OrderMasterEventsConsumer.as_asgi()),
]
