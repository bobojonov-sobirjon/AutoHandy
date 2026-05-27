"""Master: in-app bank account for Stripe Connect payouts (Instacart-style direct deposit)."""
from __future__ import annotations

from django.conf import settings
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.master.models import Master
from apps.master.permissions import IsMasterGroup
from apps.payment.services.stripe_connect_bank import (
    StripeConnectBankError,
    build_master_payout_profile,
    delete_connect_bank_account,
    ensure_master_connect_and_add_bank,
)
from apps.payment.services.stripe_connect_setup import StripeConnectSetupError, complete_connect_account_setup
from apps.payment.services.stripe_identity import StripeIdentityError

_CONNECT_SETUP_FIELDS_DESCRIPTION = """
### Bank (direct deposit)
| Field | Required | Description |
|-------|----------|-------------|
| `routing_number` | Yes | US bank **routing number** (9 digits, ACH). Test: `110000000`. |
| `account_number` | Yes | US **bank account number** (4–17 digits). Test: `000123456789`. |
| `account_holder_name` | No | Name on the bank account. Defaults to the logged-in user's full name. |
| `account_holder_type` | No | `individual` (default) or `company`. |

### Stripe Connect activation (sent to Stripe only — **not stored in our database**)
| Field | Required | Description |
|-------|----------|-------------|
| `accept_agreement` | Yes (`true`) | Master tapped **I agree** to the [Stripe Connected Account Agreement](https://stripe.com/legal/connect-account). Must be `true`. |
| `dob_year` | Test: no / Live: yes | Birth **year** (e.g. `1990`). Used for Stripe identity (representative). |
| `dob_month` | Test: no / Live: yes | Birth **month** `1`–`12` (e.g. `1` = January). |
| `dob_day` | Test: no / Live: yes | Birth **day** `1`–`31` (e.g. `15`). Together: date of birth `1990-01-15`. |
| `ssn_last4` | Test: no / Live: often yes | US tax ID: in **test** mode omit (server uses Stripe test value). In **live** mode send **9-digit SSN** (digits only). Never stored in AutoHandy DB. |

**Test mode** (`sk_test_…`): only `routing_number`, `account_number`, and `accept_agreement: true` are enough; DOB/SSN are auto-filled server-side.

**Live mode**: provide real DOB; SSN may be required by Stripe for payouts.
"""


class MasterBankAccountCreateSerializer(serializers.Serializer):
    routing_number = serializers.CharField(
        max_length=9,
        min_length=9,
        help_text='US ACH routing number (9 digits). Example test: 110000000.',
    )
    account_number = serializers.CharField(
        max_length=17,
        min_length=4,
        help_text='US bank account number (4–17 digits). Example test: 000123456789.',
    )
    account_holder_name = serializers.CharField(
        max_length=120,
        required=False,
        allow_blank=True,
        help_text='Name on the bank account. If omitted, uses the authenticated user full name.',
    )
    account_holder_type = serializers.ChoiceField(
        choices=['individual', 'company'],
        default='individual',
        required=False,
        help_text='Bank account holder type: individual (most masters) or company.',
    )
    accept_agreement = serializers.BooleanField(
        default=True,
        help_text=(
            'Must be true. Master confirmed Stripe Connected Account Agreement in the app '
            '(link: connected_account_agreement_url in GET response).'
        ),
    )
    dob_year = serializers.IntegerField(
        required=False,
        min_value=1900,
        max_value=2100,
        help_text='Representative date of birth — year (e.g. 1990). Optional in Stripe test mode.',
    )
    dob_month = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=12,
        help_text='Representative date of birth — month 1–12 (1 = January).',
    )
    dob_day = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=31,
        help_text='Representative date of birth — day 1–31.',
    )
    ssn_last4 = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=9,
        help_text=(
            'US SSN for Stripe identity verification. Test mode: leave empty. '
            'Live mode: 9 digits only (e.g. 123456789). Sent to Stripe only, not saved in DB.'
        ),
    )


class MasterConnectSetupSerializer(serializers.Serializer):
    accept_agreement = serializers.BooleanField(
        default=True,
        help_text='Must be true — user accepted Stripe Connected Account Agreement.',
    )
    dob_year = serializers.IntegerField(
        required=False,
        min_value=1900,
        max_value=2100,
        help_text='Birth year (e.g. 1990). Optional in test mode.',
    )
    dob_month = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=12,
        help_text='Birth month 1–12.',
    )
    dob_day = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=31,
        help_text='Birth day 1–31.',
    )
    ssn_last4 = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=9,
        help_text='9-digit US SSN (live). Empty in test mode. Not stored in DB.',
    )


class MasterBankAccountDeleteSerializer(serializers.Serializer):
    bank_account_id = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        help_text='Stripe bank account id (ba_…). If omitted, deletes the default bank account.',
    )


class MasterStripeConnectBankAccountView(APIView):
    """
    **GET** — payout profile: Connect status + linked bank mask (e.g. BANK OF AMERICA •••• 4141).

    **POST** — add/replace US bank account (routing + account) without Stripe-hosted onboarding page.
    Creates Connect Express account if needed. Data is passed to Stripe only (not stored in DB).

    **DELETE** — remove a linked bank account (``bank_account_id`` or default).
    """

    permission_classes = [IsAuthenticated, IsMasterGroup]

    def _master_or_404(self, request):
        master = request.user.master_profiles.first()
        if not master:
            return None, Response({'error': 'Master profile not found'}, status=status.HTTP_404_NOT_FOUND)
        return master, None

    @extend_schema(
        summary='Direct deposit — linked bank & Connect status',
        description=(
            'Returns masked bank account for the Payments / Direct deposit screen. '
            'Includes Stripe Connected Account Agreement URL for in-app disclosure.'
        ),
        tags=['Stripe — Master'],
        responses={200: {'type': 'object'}},
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
        return Response(build_master_payout_profile(master=master))

    @extend_schema(
        summary='Direct deposit — save bank account (routing + account)',
        description=(
            'Requires **Stripe Identity verified** first (POST/GET `stripe-identity/`). '
            'Then master enters routing and account number; backend attaches bank to Connect.\n'
            f'{_CONNECT_SETUP_FIELDS_DESCRIPTION}'
        ),
        tags=['Stripe — Master'],
        request=MasterBankAccountCreateSerializer,
        examples=[
            OpenApiExample(
                'US bank + auto-enable (test)',
                value={
                    'routing_number': '110000000',
                    'account_number': '000123456789',
                    'account_holder_name': 'Jane Doe',
                    'account_holder_type': 'individual',
                    'accept_agreement': True,
                },
                request_only=True,
            ),
        ],
        responses={200: {'type': 'object'}, 400: {'type': 'object'}},
    )
    def post(self, request):
        if not (getattr(settings, 'STRIPE_SECRET_KEY', '') or '').strip():
            return Response(
                {'error': 'Stripe is not configured on the server.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        master, err = self._master_or_404(request)
        if err is not None:
            return err

        ser = MasterBankAccountCreateSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        holder = (ser.validated_data.get('account_holder_name') or '').strip()
        if not holder:
            holder = (request.user.get_full_name() or '').strip() or None

        if not ser.validated_data.get('accept_agreement', True):
            return Response(
                {'error': 'accept_agreement must be true to link direct deposit.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            profile = ensure_master_connect_and_add_bank(
                master=master,
                routing_number=ser.validated_data['routing_number'],
                account_number=ser.validated_data['account_number'],
                account_holder_name=holder,
                account_holder_type=ser.validated_data.get('account_holder_type') or 'individual',
                user=request.user,
                request=request,
                accept_agreement=True,
                dob_year=ser.validated_data.get('dob_year'),
                dob_month=ser.validated_data.get('dob_month'),
                dob_day=ser.validated_data.get('dob_day'),
                ssn_last4=(ser.validated_data.get('ssn_last4') or '').strip() or None,
            )
        except StripeIdentityError as e:
            return Response({'error': e.message, 'code': 'identity_verification_required'}, status=status.HTTP_403_FORBIDDEN)
        except StripeConnectBankError as e:
            return Response({'error': e.message}, status=status.HTTP_400_BAD_REQUEST)

        msg = 'Bank account saved for weekly direct deposit.'
        if profile.get('onboarding_complete'):
            msg = 'Bank saved. Stripe Connect account is enabled for payouts.'
        elif profile.get('connect_setup_error'):
            msg = f'Bank saved. Additional Stripe verification may be required: {profile["connect_setup_error"]}'

        return Response(
            {
                'status': 'success',
                'message': msg,
                **profile,
            }
        )

    @extend_schema(
        summary='Direct deposit — remove bank account',
        tags=['Stripe — Master'],
        request=MasterBankAccountDeleteSerializer,
        responses={200: {'type': 'object'}, 400: {'type': 'object'}},
    )
    def delete(self, request):
        if not (getattr(settings, 'STRIPE_SECRET_KEY', '') or '').strip():
            return Response(
                {'error': 'Stripe is not configured on the server.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        master, err = self._master_or_404(request)
        if err is not None:
            return err

        acct = (master.stripe_connect_account_id or '').strip()
        if not acct:
            return Response({'error': 'No Stripe Connect account linked.'}, status=status.HTTP_400_BAD_REQUEST)

        ser = MasterBankAccountDeleteSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        ba_id = (ser.validated_data.get('bank_account_id') or '').strip()

        from apps.payment.services.stripe_connect_bank import get_default_connect_bank_account

        if not ba_id:
            default_ba = get_default_connect_bank_account(stripe_connect_account_id=acct)
            if not default_ba:
                return Response({'error': 'No bank account linked.'}, status=status.HTTP_400_BAD_REQUEST)
            ba_id = default_ba.get('id') or ''

        try:
            delete_connect_bank_account(stripe_connect_account_id=acct, bank_account_id=ba_id)
        except StripeConnectBankError as e:
            return Response({'error': e.message}, status=status.HTTP_400_BAD_REQUEST)

        profile = build_master_payout_profile(master=master)
        return Response(
            {
                'status': 'success',
                'message': 'Bank account removed.',
                **profile,
            }
        )


class MasterStripeConnectCompleteSetupView(APIView):
    """Submit platform + profile data to Stripe for an existing ``acct_…`` (no new bank)."""

    permission_classes = [IsAuthenticated, IsMasterGroup]

    @extend_schema(
        summary='Stripe Connect — complete setup (enable account)',
        description=(
            'Use when the bank is already linked but the Connect account is still **Restricted**. '
            'Sends agreement, date of birth, and SSN (if provided) to Stripe only — nothing stored in AutoHandy DB.\n'
            f'{_CONNECT_SETUP_FIELDS_DESCRIPTION}'
        ),
        tags=['Stripe — Master'],
        request=MasterConnectSetupSerializer,
        examples=[
            OpenApiExample(
                'Test mode (minimal)',
                value={'accept_agreement': True},
                request_only=True,
            ),
            OpenApiExample(
                'With date of birth',
                value={
                    'accept_agreement': True,
                    'dob_year': 1990,
                    'dob_month': 1,
                    'dob_day': 15,
                },
                request_only=True,
            ),
        ],
        responses={200: {'type': 'object'}, 400: {'type': 'object'}},
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

        ser = MasterConnectSetupSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        if not ser.validated_data.get('accept_agreement', True):
            return Response({'error': 'accept_agreement must be true.'}, status=status.HTTP_400_BAD_REQUEST)

        from apps.payment.services.stripe_identity import assert_identity_verified_for_payout

        try:
            assert_identity_verified_for_payout(master=master)
        except StripeIdentityError as e:
            return Response({'error': e.message, 'code': 'identity_verification_required'}, status=status.HTTP_403_FORBIDDEN)

        try:
            setup = complete_connect_account_setup(
                master=master,
                user=request.user,
                request=request,
                accept_agreement=True,
                dob_year=ser.validated_data.get('dob_year'),
                dob_month=ser.validated_data.get('dob_month'),
                dob_day=ser.validated_data.get('dob_day'),
                ssn_last4=(ser.validated_data.get('ssn_last4') or '').strip() or None,
            )
        except StripeConnectSetupError as e:
            return Response({'error': e.message}, status=status.HTTP_400_BAD_REQUEST)

        profile = build_master_payout_profile(master=master)
        profile['connect_setup'] = setup
        if setup.get('onboarding_complete'):
            profile['onboarding_complete'] = True
        if setup.get('account'):
            profile['account'] = setup['account']

        return Response(
            {
                'status': 'success',
                'message': (
                    'Stripe Connect account is enabled.'
                    if setup.get('onboarding_complete')
                    else 'Setup submitted; check requirements in response.'
                ),
                **profile,
            }
        )
