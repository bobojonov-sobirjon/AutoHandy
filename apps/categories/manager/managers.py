from django.db import models


class ByMasterManager(models.Manager):
    """Manager для фильтрации категорий по типу мастера"""
    
    def get_queryset(self):
        return super().get_queryset().filter(type_category='by_master')


class ByCarManager(models.Manager):
    """Manager для фильтрации категорий по типу машины"""
    
    def get_queryset(self):
        return super().get_queryset().filter(type_category='by_car')


class ByOrderManager(models.Manager):
    """Manager для фильтрации категорий по типу заказа"""
    
    def get_queryset(self):
        return super().get_queryset().filter(type_category='by_order')