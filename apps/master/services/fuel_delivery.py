"""Fuel Delivery master skill validation."""
from __future__ import annotations

from rest_framework import serializers

from apps.categories.models import Category
from apps.categories.services.fuel_delivery_catalog import is_fuel_delivery_category
from apps.master.models import MasterServiceItems


FUEL_DELIVERY_EQUIPMENT_ERROR = (
    'Fuel Delivery requires confirming both containers: '
    'a separate 2-gallon gas container and a separate 2-gallon diesel container.'
)


def validate_fuel_delivery_equipment(
    *,
    category: Category,
    has_gas_container_2gal: bool,
    has_diesel_container_2gal: bool,
) -> None:
    if not is_fuel_delivery_category(category):
        return
    if not (has_gas_container_2gal and has_diesel_container_2gal):
        raise serializers.ValidationError({
            'has_gas_container_2gal': FUEL_DELIVERY_EQUIPMENT_ERROR,
            'has_diesel_container_2gal': FUEL_DELIVERY_EQUIPMENT_ERROR,
        })


def master_has_active_fuel_delivery(master_id: int, category_id: int) -> bool:
    return MasterServiceItems.objects.filter(
        master_service__master_id=master_id,
        category_id=category_id,
        has_gas_container_2gal=True,
        has_diesel_container_2gal=True,
    ).exists()
