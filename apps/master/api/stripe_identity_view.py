"""Master: Stripe Identity verification (document + ID number + selfie) before Connect payouts."""
from __future__ import annotations

from django.conf import settings
from drf_spectacular.utils import OpenApiExample, extend_schema, extend_schema_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.master.permissions import IsMasterGroup
from apps.payment.services.stripe_identity import (
    StripeIdentityAlreadyVerifiedError,
    StripeIdentityError,
    build_identity_status_payload,
    create_verification_session,
)

STAG_MASTER_STRIPE_IDENTITY = 'Master Stripe Identity'


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Start verification (default)',
            summary='First time or continue active session',
            value={'force_new_session': False},
            request_only=True,
        ),
        OpenApiExample(
            'Restart (only if not verified yet)',
            summary='Cancel previous session — blocked when identity_locked',
            value={'force_new_session': True},
            request_only=True,
        ),
    ],
)
class MasterIdentityStartSerializer(serializers.Serializer):
    force_new_session = serializers.BooleanField(
        default=False,
        required=False,
        help_text=(
            'false (default): reuse active session. true: new session — '
            'not allowed after identity is verified (identity_locked).'
        ),
    )


class IdentityVerificationChecksSerializer(serializers.Serializer):
    document = serializers.BooleanField()
    id_number = serializers.BooleanField()
    matching_selfie = serializers.BooleanField()
    live_capture = serializers.BooleanField()


class MasterIdentityStartDataSerializer(serializers.Serializer):
    stripe_identity_verification_session_id = serializers.CharField()
    client_secret = serializers.CharField(allow_null=True)
    expires_at = serializers.CharField(required=False, allow_null=True)
    identity_verification_status = serializers.CharField()
    stripe_publishable_key = serializers.CharField()
    is_verified = serializers.BooleanField(required=False)
    identity_verified_at = serializers.CharField(required=False, allow_null=True)
    can_start_verification = serializers.BooleanField(required=False)
    identity_locked = serializers.BooleanField(required=False)
    verification_checks = IdentityVerificationChecksSerializer(required=False)
    poll_status_after_sdk = serializers.BooleanField(required=False)


class MasterIdentityStartResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    message = serializers.CharField()
    data = MasterIdentityStartDataSerializer()


class MasterIdentityStatusDataSerializer(serializers.Serializer):
    identity_verification_status = serializers.CharField()
    stripe_identity_verification_session_id = serializers.CharField(required=False, allow_null=True)
    identity_verified_at = serializers.CharField(required=False, allow_null=True)
    identity_last_error_code = serializers.CharField(required=False, allow_null=True)
    stripe_publishable_key = serializers.CharField()
    next_step = serializers.CharField()
    can_start_verification = serializers.BooleanField()
    is_verified = serializers.BooleanField()
    identity_locked = serializers.BooleanField(required=False)
    verification_checks = IdentityVerificationChecksSerializer(required=False)
    poll_status_after_sdk = serializers.BooleanField(required=False)
    webhook_optional = serializers.BooleanField(required=False)


class MasterIdentityStatusResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    data = MasterIdentityStatusDataSerializer()


class MasterStripeIdentityStatusView(APIView):
    permission_classes = [IsAuthenticated, IsMasterGroup]

    def _master_or_404(self, request):
        master = request.user.master_profiles.first()
        if not master:
            return None, Response({'error': 'Master profile not found'}, status=status.HTTP_404_NOT_FOUND)
        return master, None

    @extend_schema(
        summary='Stripe Identity — verification status',
        description=(
            'Status for the authenticated master (`request.user`). '
            'When `identity_locked` is true, verification is finished forever — do not call POST start again. '
            'Poll only while pending and not locked.'
        ),
        tags=[STAG_MASTER_STRIPE_IDENTITY],
        responses={
            200: MasterIdentityStatusResponseSerializer,
            400: {'type': 'object'},
            404: {'type': 'object'},
            503: {'type': 'object'},
        },
    )
    def get(self, request):
        if not (getattr(settings, 'STRIPE_SECRET_KEY', '') or '').strip():
            return Response(
                {'error': 'Stripe is not configured on the server.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        master, err = self._master_or_404(request)
        if err is not None:
            return err
        try:
            data = build_identity_status_payload(master=master, sync_stripe=True)
        except StripeIdentityError as e:
            return Response({'error': e.message, 'code': getattr(e, 'code', 'stripe_identity_error')}, status=400)
        return Response({'status': 'success', 'data': data})


class MasterStripeIdentityStartView(APIView):
    permission_classes = [IsAuthenticated, IsMasterGroup]

    @extend_schema(
        summary='Stripe Identity — start verification session',
        description=(
            'Creates a verification session only if the master is **not** verified yet. '
            'After `identity_verification_status` is `verified`, returns **409** — re-verification is blocked.\n\n'
            'Mobile: if GET status shows `identity_locked: true`, skip this endpoint and go to bank/Connect.'
        ),
        tags=[STAG_MASTER_STRIPE_IDENTITY],
        request=MasterIdentityStartSerializer,
        responses={
            200: MasterIdentityStartResponseSerializer,
            400: {'type': 'object'},
            409: {'type': 'object'},
            404: {'type': 'object'},
            503: {'type': 'object'},
        },
    )
    def post(self, request):
        if not (getattr(settings, 'STRIPE_SECRET_KEY', '') or '').strip():
            return Response(
                {'error': 'Stripe is not configured on the server.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        master = request.user.master_profiles.first()
        if not master:
            return Response({'error': 'Master profile not found'}, status=status.HTTP_404_NOT_FOUND)

        ser = MasterIdentityStartSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        try:
            result = create_verification_session(
                master=master,
                user=request.user,
                force_new_session=bool(ser.validated_data.get('force_new_session')),
            )
        except StripeIdentityAlreadyVerifiedError as e:
            master.refresh_from_db()
            return Response(
                {
                    'error': e.message,
                    'code': e.code,
                    'data': build_identity_status_payload(master=master, sync_stripe=False),
                },
                status=status.HTTP_409_CONFLICT,
            )
        except StripeIdentityError as e:
            return Response(
                {'error': e.message, 'code': getattr(e, 'code', 'stripe_identity_error')},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({'status': 'success', **result})
