from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.order.models import Order, OrderType

from .models import MasterBusySlot


@receiver(post_save, sender=Order)
def sync_order_master_busy_slot(sender, instance, **kwargs):
    """Visit date/time were removed from Order; clear any busy-slot rows still pointing at this order."""
    if instance.order_type == OrderType.STANDARD:
        MasterBusySlot.objects.filter(order=instance).delete()


@receiver(post_delete, sender=Order)
def delete_order_busy_slot(sender, instance, **kwargs):
    MasterBusySlot.objects.filter(order_id=instance.pk).delete()
