"""Query optimizations for order list APIs."""
from __future__ import annotations

from django.db.models import Count, Prefetch

from apps.order.models import CustomRequestOffer, Order, OrderService, OrderStatus


_ORDER_SERVICES_PREFETCH = Prefetch(
    'order_services',
    queryset=OrderService.objects.select_related(
        'master_service_item',
        'master_service_item__category',
        'master_service_item__category__parent',
    ).order_by('id'),
)

_CUSTOM_OFFERS_PREFETCH = Prefetch(
    'custom_request_offers',
    queryset=CustomRequestOffer.objects.only(
        'id',
        'order_id',
        'master_id',
        'price',
        'created_at',
        'updated_at',
    ),
)


def optimize_orders_list_queryset(qs):
    """
    Lightweight select/prefetch for list serializers (OrderListSerializer).
    Avoids heavy master schedule/services/ratings graphs used only by full OrderSerializer.
    """
    return qs.select_related(
        'user',
        'master',
        'master__user',
        'review',
        'review__reviewer',
    ).prefetch_related(
        'category',
        'category__parent',
        'car',
        'car__category',
        _ORDER_SERVICES_PREFETCH,
        _CUSTOM_OFFERS_PREFETCH,
    )


def prepare_orders_page_for_serialization(orders: list[Order]) -> None:
    """
    Attach completed_orders_count on distinct masters (one query for the page).
    """
    master_ids = {o.master_id for o in orders if o.master_id}
    if not master_ids:
        return
    counts = (
        Order.objects.filter(master_id__in=master_ids, status=OrderStatus.COMPLETED)
        .values('master_id')
        .annotate(completed_orders_count=Count('id'))
    )
    by_master = {row['master_id']: row['completed_orders_count'] for row in counts}
    for order in orders:
        if order.master_id and hasattr(order, 'master') and order.master is not None:
            order.master.completed_orders_count = by_master.get(order.master_id, 0)
