"""Account-level API permissions."""
from django.conf import settings
from rest_framework.permissions import BasePermission


# (method, path) pairs that work without verified email (authenticated users).
_EMAIL_VERIFICATION_EXEMPT = {
    ('GET', '/api/auth/user/'),
    ('PUT', '/api/auth/user/'),
    ('PATCH', '/api/auth/user/'),
    ('POST', '/api/auth/user/register-profile/'),
    ('POST', '/api/auth/email-verification/'),
    ('POST', '/api/auth/email-verification/resend/'),
    ('DELETE', '/api/auth/user/'),
    ('DELETE', '/api/auth/account/delete/'),
    ('POST', '/api/auth/device/'),
    ('PATCH', '/api/auth/device/'),
    ('PUT', '/api/auth/device/'),
    ('POST', '/api/auth/device/test-push/'),
}


def _path_exempt_from_email_verification(request) -> bool:
    path = (request.path or '').rstrip('/') + '/'
    if not path.startswith('/'):
        path = '/' + path
    key = (request.method.upper(), path)
    return key in _EMAIL_VERIFICATION_EXEMPT


class EmailVerifiedRequired(BasePermission):
    """
    Blocks authenticated drivers and masters until ``is_email_verified`` is true.
    Login, profile registration, email confirm/resend, and read-own-profile stay available.
    """

    message = 'Please verify your email before using the app.'

    def has_permission(self, request, view):
        if not getattr(settings, 'REQUIRE_EMAIL_VERIFICATION', True):
            return True
        if getattr(view, 'allow_without_email_verification', False):
            return True
        if _path_exempt_from_email_verification(request):
            return True

        user = request.user
        if not user or not getattr(user, 'is_authenticated', False):
            return True

        if getattr(user, 'is_superuser', False) or getattr(user, 'is_staff', False):
            return True

        return bool(getattr(user, 'is_email_verified', False))
