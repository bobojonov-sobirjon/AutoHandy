"""Query optimizations for order list APIs (same OrderSerializer output, fewer queries)."""
from __future__ import annotations

from django.db.models import Count, Prefetch

from apps.master.models import MasterImage, MasterScheduleDay, MasterService, MasterServiceItems
from apps.order.models import CustomRequestOffer, Order, OrderService, OrderStatus, Rating


_ORDER_SERVICES_PREFETCH = Prefetch(
    'order_services',
    queryset=OrderService.objects.select_related(
        'master_service_item',
        'master_service_item__category',
        'master_service_item__category__parent',
    ).order_by(
        'master_service_item__category__parent_id',
        'master_service_item__category__name',
    ),
)

_MASTER_SERVICE_ITEMS_PREFETCH = Prefetch(
    'master_service_items',
    queryset=MasterServiceItems.objects.select_related('category', 'category__parent'),
)

_MASTER_SERVICES_PREFETCH = Prefetch(
    'master_services',
    queryset=MasterService.objects.prefetch_related(_MASTER_SERVICE_ITEMS_PREFETCH),
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

_MASTER_RATINGS_PREFETCH = Prefetch(
    'master__ratings',
    queryset=Rating.objects.select_related('user').order_by('-created_at'),
)


def optimize_orders_list_queryset(qs):
    """
    select_related / prefetch_related for GET by-user and by-master list serialization.
    Response JSON unchanged; DB round-trips reduced.
    """
    return qs.select_related(
        'user',
        'master',
        'master__user',
        'saved_card',
        'review',
        'review__reviewer',
    ).prefetch_related(
        'images',
        'work_completion_images',
        'category',
        'category__parent',
        'car',
        'car__category',
        _ORDER_SERVICES_PREFETCH,
        _CUSTOM_OFFERS_PREFETCH,
        Prefetch('master__master_images', queryset=MasterImage.objects.all()),
        Prefetch('master__master_services', queryset=_MASTER_SERVICES_PREFETCH.queryset),
        _MASTER_RATINGS_PREFETCH,
        Prefetch(
            'master__schedule_days',
            queryset=MasterScheduleDay.objects.all().order_by('date', 'start_time'),
        ),
    )


def prepare_orders_page_for_serialization(orders: list[Order]) -> None:
    """
    Attach counts used by MasterSerializer so list views avoid per-order COUNT queries.
    Mutates master instances in memory only.
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
        if order.master_id and order.master_id in by_master:
            order.master.completed_orders_count = by_master[order.master_id]
