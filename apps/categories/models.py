from django.db import models
from apps.categories.manager.managers import ByMasterManager, ByCarManager, ByOrderManager


class Category(models.Model):
    """Category model"""

    class TypeCategory(models.TextChoices):
        BY_MASTER = 'by_master', 'By master category'
        BY_CAR = 'by_car', 'By car category'
        BY_ORDER = 'by_order', 'By order category'

    name = models.CharField(max_length=255, verbose_name='Category name')
    type_category = models.CharField(max_length=255, verbose_name='Category type', choices=TypeCategory.choices)
    service_type = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='Service type',
        help_text='Common service type for linking by_order and by_master categories. Examples: Repair, Diagnostics, Replacement, Maintenance, Tire fitting, Painting, Body repair, Electrical, Air conditioning, Tuning, etc.'
    )
    icon = models.FileField(upload_to='categories/icons/', verbose_name='Category icon', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created at')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated at')

    objects = models.Manager()
    by_master = ByMasterManager()
    by_car = ByCarManager()
    by_order = ByOrderManager()

    class Meta:
        verbose_name = 'Category'
        verbose_name_plural = 'Categories'
        ordering = ['-created_at']

    def __str__(self):
        return self.name
