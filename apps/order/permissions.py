from rest_framework import permissions


class IsOrderOwner(permissions.BasePermission):
    """Разрешение для владельца заказа"""
    
    def has_object_permission(self, request, view, obj):
        # Разрешаем доступ только владельцу заказа
        return obj.user == request.user


class IsMaster(permissions.BasePermission):
    """Разрешение для мастера"""
    
    def has_permission(self, request, view):
        # Проверяем, что пользователь аутентифицирован и является мастером
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.master_profiles.exists()
        )


class IsOrderOwnerOrMaster(permissions.BasePermission):
    """Разрешение для владельца заказа или назначенного мастера"""
    
    def has_object_permission(self, request, view, obj):
        # Разрешаем доступ владельцу заказа
        if obj.user == request.user:
            return True
        
        # Разрешаем доступ назначенному мастеру
        master = request.user.master_profiles.first()
        if master and obj.master == master:
            return True
        
        return False


class IsOrderOwnerOrReadOnly(permissions.BasePermission):
    """Разрешение для владельца заказа или только чтение"""
    
    def has_object_permission(self, request, view, obj):
        # Разрешаем чтение всем аутентифицированным пользователям
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Разрешаем изменение только владельцу заказа
        return obj.user == request.user

