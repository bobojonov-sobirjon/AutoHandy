"""Push + WebSocket notifications for towing orders."""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.order.models import Order


def _towing_extra(order: 'Order') -> dict[str, str]:
    extra: dict[str, str] = {'order_type': 'towing'}
    if order.towing_total is not None:
        extra['total_price'] = format(Decimal(str(order.towing_total)), 'f')
    if order.towing_distance_miles is not None:
        extra['distance_miles'] = format(Decimal(str(order.towing_distance_miles)), 'f')
    return extra


def _order_ws_payload(order: 'Order', request=None) -> dict:
    from apps.order.api.serializers import OrderSerializer

    return OrderSerializer(order, context={'request': request}).data


def notify_towing_order_created(order: 'Order', *, request=None) -> None:
    """
    After towing order create: confirm to driver, reinforce master alert + real-time WS.
    Master FCM is also sent via ``activate_pending_master_offer`` → ``notify_master_new_order``.
    """
    from apps.order.services.notifications import (
        notify_user_order_kind,
        push_order_event_to_master_websocket,
        push_order_event_to_user_websocket,
    )

    extra = _towing_extra(order)
    try:
        notify_user_order_kind(order, kind='towing_created', extra_data=extra)
    except Exception:  # noqa: BLE001
        pass

    payload = {
        'order_id': order.id,
        'order_type': 'towing',
        'order': _order_ws_payload(order, request),
    }
    try:
        push_order_event_to_user_websocket(
            user_id=order.user_id,
            event_type='towing_created',
            payload=payload,
        )
    except Exception:  # noqa: BLE001
        pass

    if order.master_id:
        try:
            from apps.master.models import Master

            mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=order.master_id)
            push_order_event_to_master_websocket(
                master_user_id=mu.user_id,
                event_type='towing_new',
                payload=payload,
            )
        except Exception:  # noqa: BLE001
            pass
