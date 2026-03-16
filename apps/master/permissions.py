from rest_framework import permissions


class IsMasterGroup(permissions.BasePermission):
    """Разрешение только для группы Master"""
    
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.groups.filter(name='Master').exists()
        )


class IsOwnerGroup(permissions.BasePermission):
    """Разрешение только для группы Owner"""
    
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.groups.filter(name='Owner').exists()
        )
