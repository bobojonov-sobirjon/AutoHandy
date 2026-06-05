"""Block API usage for authenticated users until email is verified."""
from django.conf import settings
from django.http import JsonResponse
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.accounts.permissions import _path_exempt_from_email_verification


class EmailVerificationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_block(request):
            return JsonResponse(
                {
                    'success': False,
                    'error': 'email_verification_required',
                    'message': 'Please verify your email before using the app.',
                    'is_email_verified': False,
                },
                status=403,
            )
        return self.get_response(request)

    def _should_block(self, request) -> bool:
        if not getattr(settings, 'REQUIRE_EMAIL_VERIFICATION', True):
            return False
        path = request.path or ''
        if not path.startswith('/api/'):
            return False
        if _path_exempt_from_email_verification(request):
            return False

        user = getattr(request, 'user', None)
        if user is not None and getattr(user, 'is_authenticated', False):
            authenticated_user = user
        else:
            authenticated_user = self._jwt_user(request)

        if not authenticated_user or not getattr(authenticated_user, 'is_authenticated', False):
            return False
        if getattr(authenticated_user, 'is_superuser', False) or getattr(authenticated_user, 'is_staff', False):
            return False
        return not bool(getattr(authenticated_user, 'is_email_verified', False))

    @staticmethod
    def _jwt_user(request):
        try:
            auth = JWTAuthentication().authenticate(request)
        except Exception:
            return None
        if not auth:
            return None
        return auth[0]
