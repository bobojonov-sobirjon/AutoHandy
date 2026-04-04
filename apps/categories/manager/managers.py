from django.db import models


class ByCarManager(models.Manager):
    """Manager для фильтрации категорий по типу машины"""
    
    def get_queryset(self):
        return super().get_queryset().filter(type_category='by_car')


class ByOrderManager(models.Manager):
    """Manager для фильтрации категорий по типу заказа"""
    
    def get_queryset(self):
        return super().get_queryset().filter(type_category='by_order')