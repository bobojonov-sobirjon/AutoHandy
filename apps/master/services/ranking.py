"""Master list ordering: completed orders → rating → distance (ETA proxy) + new-master boost (slots 3–10)."""
from __future__ import annotations

from django.db.models import Avg, Count

from apps.order.models import Order, OrderStatus, Rating


NEW_MASTER_MAX_COMPLETED = 10


def attach_master_list_metrics(masters: list) -> None:
    if not masters:
        return
    ids = [m.id for m in masters]
    comp = dict(
        Order.objects.filter(master_id__in=ids, status=OrderStatus.COMPLETED)
        .values('master_id')
        .annotate(c=Count('id'))
        .values_list('master_id', 'c')
    )
    avg_map = dict(
        Rating.objects.filter(master_id__in=ids)
        .values('master_id')
        .annotate(a=Avg('rating'))
        .values_list('master_id', 'a')
    )
    for m in masters:
        m.completed_orders_count = comp.get(m.id, 0)
        a = avg_map.get(m.id)
        m.avg_rating_sort = float(a) if a is not None else 0.0


def _sort_key(master) -> tuple:
    dist = getattr(master, 'distance', None)
    if dist is None:
        dist = 9999.0
    return (
        -getattr(master, 'completed_orders_count', 0),
        -getattr(master, 'avg_rating_sort', 0.0),
        dist,
    )


def sort_masters_with_new_boost(masters: list):
    """
    Positions 1–2: лучшие по (выполненные ↓, рейтинг ↓, расстояние ↑).
    Позиции 3–10: приоритет «новым» мастерам (<10 завершённых), затем добор из остальных.
    """
    if len(masters) <= 2:
        return sorted(masters, key=_sort_key)

    all_sorted = sorted(masters, key=_sort_key)
    top_two = all_sorted[:2]
    used = {id(m) for m in top_two}

    new_pool = [m for m in all_sorted if m.completed_orders_count < NEW_MASTER_MAX_COMPLETED]
    mid: list = []
    for m in new_pool:
        if id(m) in used:
            continue
        if len(mid) >= 8:
            break
        mid.append(m)
        used.add(id(m))

    if len(mid) < 8:
        for m in all_sorted:
            if len(mid) >= 8:
                break
            if id(m) in used:
                continue
            mid.append(m)
            used.add(id(m))

    tail = [m for m in all_sorted if id(m) not in used]
    return top_two + mid + tail
