from django.db import models
from apps.categories.manager.managers import ByCarManager, ByOrderManager


class Category(models.Model):
    """Category model"""

    class TypeCategory(models.TextChoices):
        BY_CAR = 'by_car', 'By car category'
        BY_ORDER = 'by_order', 'By order category'

    name = models.CharField(max_length=255, verbose_name='Category name')
    type_category = models.CharField(max_length=255, verbose_name='Category type', choices=TypeCategory.choices)
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children',
        verbose_name='Parent category',
        help_text='Optional parent to group related categories (e.g. by_order service tree).',
    )
    icon = models.FileField(upload_to='categories/icons/', verbose_name='Category icon', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created at')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated at')

    objects = models.Manager()
    by_car = ByCarManager()
    by_order = ByOrderManager()

    class Meta:
        verbose_name = 'Category'
        verbose_name_plural = 'Categories'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class MainCategory(Category):
    """Top-level category (no parent); use Main categories in admin."""

    class Meta:
        proxy = True
        verbose_name = 'Main category'
        verbose_name_plural = 'Main categories'


class SubCategory(Category):
    """Child category with a main category as parent; use Sub categories in admin."""

    class Meta:
        proxy = True
        verbose_name = 'Sub category'
        verbose_name_plural = 'Sub categories'
