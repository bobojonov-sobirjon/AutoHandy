from rest_framework.views import exception_handler

from apps.accounts.permissions import EmailVerifiedRequired


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    if response.status_code == 403:
        detail = response.data.get('detail') if isinstance(response.data, dict) else None
        if detail == EmailVerifiedRequired.message:
            request = context.get('request')
            user = getattr(request, 'user', None) if request else None
            response.data = {
                'success': False,
                'error': 'email_verification_required',
                'message': EmailVerifiedRequired.message,
                'is_email_verified': bool(getattr(user, 'is_email_verified', False)),
            }

    return response
