"""Towing service types — each is a separate driver-selectable offering."""

from django.db import models


class TowingServiceType(models.TextChoices):
    LOCAL = 'local', 'Local towing'
    LONG_DISTANCE = 'long_distance', 'Long distance towing'
    ACCIDENT_RECOVERY = 'accident_recovery', 'Accident recovery'
    MOTORCYCLE = 'motorcycle', 'Motorcycle towing'


ALL_TOWING_SERVICE_TYPES: tuple[str, ...] = tuple(TowingServiceType.values)

TOWING_SERVICE_TYPE_LABELS: dict[str, str] = {
    TowingServiceType.LOCAL: 'Local towing',
    TowingServiceType.LONG_DISTANCE: 'Long distance towing',
    TowingServiceType.ACCIDENT_RECOVERY: 'Accident recovery',
    TowingServiceType.MOTORCYCLE: 'Motorcycle towing',
}
