from rest_framework import permissions


class IsDriverGroup(permissions.BasePermission):
    """Разрешение только для группы Driver"""
    
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.groups.filter(name='Driver').exists()
        )


class IsMasterGroup(permissions.BasePermission):
    """Разрешение только для группы Master"""
    
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.groups.filter(name='Master').exists()
        )
