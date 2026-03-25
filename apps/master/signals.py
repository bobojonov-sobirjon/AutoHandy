from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.order.models import Order, OrderStatus, OrderType

from .models import MasterBusySlot


@receiver(post_save, sender=Order)
def sync_order_master_busy_slot(sender, instance, **kwargs):
    if not instance.master_id:
        MasterBusySlot.objects.filter(order=instance).delete()
        return
    if instance.order_type != OrderType.SCHEDULED:
        MasterBusySlot.objects.filter(order=instance).delete()
        return
    if not instance.scheduled_date or not instance.scheduled_time_start or not instance.scheduled_time_end:
        MasterBusySlot.objects.filter(order=instance).delete()
        return
    if instance.status in (OrderStatus.CANCELLED, OrderStatus.REJECTED):
        MasterBusySlot.objects.filter(order=instance).delete()
        return

    MasterBusySlot.objects.update_or_create(
        order=instance,
        defaults={
            'master_id': instance.master_id,
            'date': instance.scheduled_date,
            'start_time': instance.scheduled_time_start,
            'end_time': instance.scheduled_time_end,
            'reason': '',
        },
    )


@receiver(post_delete, sender=Order)
def delete_order_busy_slot(sender, instance, **kwargs):
    MasterBusySlot.objects.filter(order_id=instance.pk).delete()
