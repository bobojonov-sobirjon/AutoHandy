"""Master-proposed schedule changes with client approval."""
from __future__ import annotations

from datetime import date, time

from apps.order.models import Order, OrderStatus, OrderTimeChangeRequest, OrderType, TimeChangeRequestStatus
from apps.order.services.order_scheduled_start import scheduled_slot_is_in_future
from apps.order.services.standard_booking_availability import preferred_slot_blocked_message

TIME_CHANGE_ALLOWED_STATUSES = {
    OrderStatus.ACCEPTED,
    OrderStatus.ON_THE_WAY,
    OrderStatus.ARRIVED,
}


def order_allows_time_change_proposal(order: Order) -> str | None:
    if order.order_type not in (OrderType.STANDARD, OrderType.CUSTOM_REQUEST):
        return 'Time change is only available for standard and custom-request orders.'
    if order.status not in TIME_CHANGE_ALLOWED_STATUSES:
        return 'Time can be changed only while the order is accepted, on the way, or arrived.'
    if not order.master_id:
        return 'Order has no assigned master.'
    if order.preferred_date is None or order.preferred_time_start is None:
        return 'Order has no scheduled date/time to change.'
    return None


def validate_proposed_time_change(
    *,
    order: Order,
    proposed_date: date,
    proposed_time_start: time,
    proposed_time_end: time | None,
) -> dict[str, str]:
    errors: dict[str, str] = {}

    if order.order_type == OrderType.STANDARD and proposed_time_end is None:
        errors['proposed_preferred_time_end'] = 'Required for standard orders.'

    if proposed_time_end is not None and proposed_time_end <= proposed_time_start:
        errors['proposed_preferred_time_end'] = 'Must be after proposed_preferred_time_start.'

    unchanged = (
        order.preferred_date == proposed_date
        and order.preferred_time_start == proposed_time_start
        and (order.order_type != OrderType.STANDARD or order.preferred_time_end == proposed_time_end)
    )
    if unchanged:
        errors['proposed_preferred_date'] = 'Proposed time must differ from the current schedule.'

    if not scheduled_slot_is_in_future(preferred_date=proposed_date, preferred_time_start=proposed_time_start):
        errors['proposed_preferred_time_start'] = 'Proposed time must be in the future.'

    blocked = preferred_slot_blocked_message(
        master_id=order.master_id,
        preferred_date=proposed_date,
        preferred_time_start=proposed_time_start,
        exclude_order_id=order.pk,
    )
    if blocked:
        errors['proposed_preferred_time_start'] = blocked

    return errors


def apply_approved_time_change(order: Order, req: OrderTimeChangeRequest) -> list[str]:
    """Apply approved proposal to the order; returns updated field names."""
    fields = ['preferred_date', 'preferred_time_start', 'updated_at']
    order.preferred_date = req.proposed_preferred_date
    order.preferred_time_start = req.proposed_preferred_time_start

    if req.proposed_preferred_time_end is not None:
        order.preferred_time_end = req.proposed_preferred_time_end
        fields.append('preferred_time_end')

    if order.order_type == OrderType.CUSTOM_REQUEST:
        order.custom_request_date = req.proposed_preferred_date
        order.custom_request_time = req.proposed_preferred_time_start
        fields.extend(['custom_request_date', 'custom_request_time'])

    order.save(update_fields=fields)
    return fields


def has_pending_time_change(order_id: int) -> bool:
    return OrderTimeChangeRequest.objects.filter(
        order_id=order_id,
        status=TimeChangeRequestStatus.PENDING,
    ).exists()
