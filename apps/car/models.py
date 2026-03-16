from django.db import models
from apps.accounts.models import CustomUser
from django.core.exceptions import ValidationError
from apps.categories.models import Category


class Car(models.Model):
    """Car model"""

    category = models.ForeignKey(Category, on_delete=models.CASCADE, null=True, blank=True, verbose_name='Category', related_name='cars')

    brand = models.CharField(max_length=255, null=True, blank=True, verbose_name='Car brand')
    model = models.CharField(max_length=255, null=True, blank=True, verbose_name='Car model')
    year = models.IntegerField(null=True, blank=True, verbose_name='Manufacturing year')

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True, blank=True, verbose_name='User')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created at')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated at')

    class Meta:
        verbose_name = 'Car'
        verbose_name_plural = 'Cars'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.brand} {self.model} ({self.year})" if self.brand and self.model else f"Car {self.id}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
