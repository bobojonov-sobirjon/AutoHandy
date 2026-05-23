"""Record master assignment failures for completion-rate metrics."""
from __future__ import annotations

from apps.order.models import MasterAssignmentFailure, MasterAssignmentFailureReason


def record_master_assignment_failure(*, master_id: int, order_id: int, reason: str) -> None:
    if not master_id or not order_id:
        return
    try:
        MasterAssignmentFailure.objects.get_or_create(
            master_id=int(master_id),
            order_id=int(order_id),
            reason=reason,
            defaults={},
        )
    except Exception:  # noqa: BLE001
        pass


def record_sos_no_departure_failure(*, master_id: int, order_id: int) -> None:
    record_master_assignment_failure(
        master_id=master_id,
        order_id=order_id,
        reason=MasterAssignmentFailureReason.SOS_NO_DEPARTURE,
    )


def record_standard_no_departure_failure(*, master_id: int, order_id: int) -> None:
    record_master_assignment_failure(
        master_id=master_id,
        order_id=order_id,
        reason=MasterAssignmentFailureReason.STANDARD_NO_DEPARTURE,
    )


def record_scheduled_no_start_failure(*, master_id: int, order_id: int) -> None:
    record_master_assignment_failure(
        master_id=master_id,
        order_id=order_id,
        reason=MasterAssignmentFailureReason.SCHEDULED_NO_START,
    )
