from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from apps.accounts.models import CustomUser
from apps.accounts.services import SMSService


@method_decorator(csrf_exempt, name='dispatch')
class SwaggerTokenView(APIView):
    """
    Swagger OAuth2 token endpoint - email-only authentication (SMS-based)
    """
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="OAuth2 Token Endpoint",
        description="OAuth2 password flow for Swagger - email only authentication",
        request={
            'application/x-www-form-urlencoded': {
                'type': 'object',
                'properties': {
                    'grant_type': {'type': 'string', 'example': 'password'},
                    'username': {'type': 'string', 'format': 'email', 'example': 'user@example.com'},
                    'password': {'type': 'string', 'example': 'password'},
                },
                'required': ['grant_type', 'username']
            }
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'access_token': {'type': 'string'},
                    'refresh_token': {'type': 'string'},
                    'token_type': {'type': 'string', 'example': 'Bearer'},
                    'expires_in': {'type': 'integer', 'example': 604800},
                    'scope': {'type': 'string', 'example': 'read write'}
                }
            },
            400: {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'},
                    'error_description': {'type': 'string'}
                }
            }
        },
        tags=['Authentication']
    )
    def post(self, request):
        """OAuth2 password flow for Swagger - email only"""
        username = request.data.get('username')  # This will be the email
        password = request.data.get('password', '')  # Not used, but kept for compatibility
        grant_type = request.data.get('grant_type', 'password')
        
        if grant_type != 'password':
            return JsonResponse({
                'error': 'unsupported_grant_type',
                'error_description': 'Only password grant type is supported'
            }, status=400)
        
        if not username:
            return JsonResponse({
                'error': 'invalid_request',
                'error_description': 'Email is required'
            }, status=400)
        
        # Try to find user by email
        try:
            user = CustomUser.objects.get(email=username)
        except CustomUser.DoesNotExist:
            # If user doesn't exist, create a new one (similar to your login flow)
            user = CustomUser.objects.create_user(
                username=username,  # Use email as username
                email=username,
                phone_number='',  # Will be set later if needed
                first_name='',
                last_name=''
            )
        
        # Generate tokens directly (no password check needed)
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)
        
        return JsonResponse({
            'access_token': access_token,
            'refresh_token': refresh_token,
            'token_type': 'Bearer',
            'expires_in': 604800,  # 7 days in seconds
            'scope': 'read write'
        })