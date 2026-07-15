"""Stripe Identity verification sessions for Master profiles (no local PII storage)."""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.master.models import Master, MasterIdentityVerificationStatus
from apps.payment.services.stripe_client import stripe_configured, stripe_sdk


class StripeIdentityError(Exception):
    def __init__(self, message: str, *, code: str = 'stripe_identity_error'):
        self.message = message
        self.code = code
        super().__init__(message)


class StripeIdentityAlreadyVerifiedError(StripeIdentityError):
    def __init__(self, message: str = 'Identity is already verified. Re-verification is not allowed.'):
        super().__init__(message, code='identity_already_verified')


_STRIPE_STATUS_TO_DB = {
    'verified': MasterIdentityVerificationStatus.VERIFIED,
    'processing': MasterIdentityVerificationStatus.PENDING,
    'requires_input': MasterIdentityVerificationStatus.REQUIRES_INPUT,
    'canceled': MasterIdentityVerificationStatus.CANCELED,
    'redacted': MasterIdentityVerificationStatus.CANCELED,
}

_ACTIVE_SESSION_STATUSES = frozenset(
    {
        MasterIdentityVerificationStatus.PENDING,
        MasterIdentityVerificationStatus.REQUIRES_INPUT,
    }
)


def _publishable_key() -> str:
    return (getattr(settings, 'STRIPE_PUBLISHABLE_KEY', '') or '').strip()


def _session_id(master: Master) -> str:
    return (getattr(master, 'stripe_identity_verification_session_id', '') or '').strip()


def _db_status(master: Master) -> str:
    raw = getattr(master, 'identity_verification_status', '') or MasterIdentityVerificationStatus.NOT_STARTED
    return str(raw)


def is_identity_verified(master: Master) -> bool:
    return _db_status(master) == MasterIdentityVerificationStatus.VERIFIED


def is_identity_verification_locked(master: Master) -> bool:
    """Once verified, identity status stays verified (no restart, no downgrade)."""
    return is_identity_verified(master)


def _env_bool(name: str, default: bool = True) -> bool:
    raw = getattr(settings, name, default)
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in ('1', 'true', 'yes')


def verification_checks_config() -> dict[str, bool]:
    """Checks requested on each VerificationSession (matches Stripe Dashboard flow)."""
    return {
        'document': True,
        'id_number': _env_bool('STRIPE_IDENTITY_REQUIRE_ID_NUMBER', True),
        'matching_selfie': _env_bool('STRIPE_IDENTITY_REQUIRE_MATCHING_SELFIE', True),
        'live_capture': _env_bool('STRIPE_IDENTITY_REQUIRE_LIVE_CAPTURE', True),
    }


def _document_session_options() -> dict[str, Any]:
    checks = verification_checks_config()
    doc: dict[str, Any] = {
        'allowed_types': ['driving_license', 'id_card', 'passport'],
    }
    if checks['id_number']:
        doc['require_id_number'] = True
    if checks['matching_selfie']:
        doc['require_matching_selfie'] = True
    if checks['live_capture']:
        doc['require_live_capture'] = True
    return doc


def assert_identity_verified_for_payout(*, master: Master) -> None:
    """Block Connect bank / payout setup until Stripe Identity is verified."""
    if not _env_bool('STRIPE_IDENTITY_ENFORCE_BEFORE_PAYOUT', True):
        return
    if is_identity_verified(master):
        return
    status = _db_status(master)
    sid = _session_id(master)
    raise StripeIdentityError(
        'Complete Stripe Identity verification (government ID, ID number, and selfie) '
        'before adding a bank account. '
        f'Current status: {status}. '
        'Use POST /api/master/stripe-identity/start/ then GET .../stripe-identity/status/ after the SDK finishes.'
        + (f' Active session: {sid}.' if sid else '')
    )


def _iso_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, dt_timezone.utc)
    return value.isoformat()


def _stripe_unix_to_dt(value: Any) -> datetime | None:
    if value in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _extract_error_code(session: Any) -> str:
    err = getattr(session, 'last_error', None)
    if err is None and isinstance(session, dict):
        err = session.get('last_error')
    if not err:
        return ''
    code = getattr(err, 'code', None) or (err.get('code') if isinstance(err, dict) else None)
    return str(code or '').strip()[:64]


def _map_stripe_status(stripe_status: str) -> str:
    key = (stripe_status or '').strip().lower()
    return _STRIPE_STATUS_TO_DB.get(key, MasterIdentityVerificationStatus.PENDING)


def compute_next_step(*, status: str, has_active_session: bool, last_error_code: str = '') -> str:
    if status == MasterIdentityVerificationStatus.VERIFIED:
        return 'proceed_to_connect'
    if status == MasterIdentityVerificationStatus.PENDING:
        return 'continue_verification' if has_active_session else 'wait_for_result'
    if status == MasterIdentityVerificationStatus.REQUIRES_INPUT:
        if has_active_session and not (last_error_code or '').strip():
            return 'continue_verification'
        return 'retry_verification'
    if status in (MasterIdentityVerificationStatus.CANCELED, MasterIdentityVerificationStatus.FAILED):
        return 'retry_verification'
    return 'start_verification'


def apply_verification_session_to_master(*, master: Master, session: Any) -> Master:
    """Persist Stripe VerificationSession status on Master (metadata only)."""
    session_id = str(getattr(session, 'id', None) or (session.get('id') if isinstance(session, dict) else '') or '')
    stripe_status = str(
        getattr(session, 'status', None) or (session.get('status') if isinstance(session, dict) else '') or ''
    )
    mapped = _map_stripe_status(stripe_status)
    if is_identity_verification_locked(master) and mapped != MasterIdentityVerificationStatus.VERIFIED:
        return master

    error_code = _extract_error_code(session)

    updates: dict[str, Any] = {
        'stripe_identity_verification_session_id': session_id or _session_id(master),
        'identity_verification_status': mapped,
        'identity_last_error_code': error_code,
    }

    if mapped == MasterIdentityVerificationStatus.VERIFIED:
        verified_at = _stripe_unix_to_dt(getattr(session, 'created', None) or getattr(session, 'verified_at', None))
        if verified_at is None and isinstance(session, dict):
            verified_at = _stripe_unix_to_dt(session.get('verified_at') or session.get('created'))
        updates['identity_verified_at'] = verified_at or timezone.now()
    elif mapped != MasterIdentityVerificationStatus.VERIFIED and not is_identity_verification_locked(master):
        updates['identity_verified_at'] = None

    for field, value in updates.items():
        setattr(master, field, value)
    master.save(update_fields=list(updates.keys()) + ['updated_at'])
    return master


def sync_master_identity_from_stripe(*, master: Master) -> Master:
    if is_identity_verification_locked(master):
        return master
    sid = _session_id(master)
    if not sid or not stripe_configured():
        return master
    stripe = stripe_sdk()
    try:
        session = stripe.identity.VerificationSession.retrieve(sid)
    except Exception as exc:  # noqa: BLE001
        msg = str(getattr(exc, 'user_message', None) or getattr(exc, 'message', None) or exc)
        raise StripeIdentityError(msg) from exc
    return apply_verification_session_to_master(master=master, session=session)


def build_identity_verification_block(*, master: Master, sync_stripe: bool = True) -> dict[str, Any]:
    if sync_stripe and _session_id(master) and _db_status(master) != MasterIdentityVerificationStatus.VERIFIED:
        try:
            master = sync_master_identity_from_stripe(master=master)
        except StripeIdentityError:
            pass

    status = _db_status(master)
    sid = _session_id(master) or None
    error_code = (getattr(master, 'identity_last_error_code', '') or '').strip()
    checks = verification_checks_config()
    verified = status == MasterIdentityVerificationStatus.VERIFIED
    return {
        'status': status,
        'verified_at': _iso_dt(getattr(master, 'identity_verified_at', None)),
        'session_id': sid,
        'is_verified': verified,
        'last_error_code': error_code or None,
        'next_step': compute_next_step(status=status, has_active_session=bool(sid), last_error_code=error_code),
        'verification_checks': checks,
        'poll_status_after_sdk': not verified,
        'identity_locked': verified,
        'can_start_verification': not verified,
        'webhook_optional': not bool((getattr(settings, 'STRIPE_WEBHOOK_SECRET', '') or '').strip()),
    }


def build_identity_status_payload(*, master: Master, sync_stripe: bool = True) -> dict[str, Any]:
    if sync_stripe and _session_id(master) and _db_status(master) != MasterIdentityVerificationStatus.VERIFIED:
        try:
            master = sync_master_identity_from_stripe(master=master)
        except StripeIdentityError:
            pass

    status = _db_status(master)
    sid = _session_id(master) or None
    verified = status == MasterIdentityVerificationStatus.VERIFIED
    error_code = (getattr(master, 'identity_last_error_code', '') or '').strip()
    can_start = status in (
        MasterIdentityVerificationStatus.NOT_STARTED,
        MasterIdentityVerificationStatus.CANCELED,
        MasterIdentityVerificationStatus.FAILED,
        MasterIdentityVerificationStatus.REQUIRES_INPUT,
    ) or (status == MasterIdentityVerificationStatus.PENDING and not sid)

    checks = verification_checks_config()
    return {
        'identity_verification_status': status,
        'stripe_identity_verification_session_id': sid,
        'identity_verified_at': _iso_dt(getattr(master, 'identity_verified_at', None)),
        'identity_last_error_code': error_code or None,
        'stripe_publishable_key': _publishable_key(),
        'next_step': compute_next_step(status=status, has_active_session=bool(sid), last_error_code=error_code),
        'can_start_verification': can_start and not verified,
        'is_verified': verified,
        'identity_locked': verified,
        'verification_checks': checks,
        'poll_status_after_sdk': not verified,
        'webhook_optional': not bool((getattr(settings, 'STRIPE_WEBHOOK_SECRET', '') or '').strip()),
    }


def _stripe_ephemeral_api_version(stripe_mod) -> str:
    """
    Android Identity SDK requires an ephemeral key bound to the VerificationSession.
    Prefer configured version, then the SDK default.
    """
    configured = (getattr(settings, 'STRIPE_IDENTITY_EPHEMERAL_API_VERSION', '') or '').strip()
    if configured:
        return configured
    return str(getattr(stripe_mod, 'api_version', None) or '2024-11-20.acacia')


def _create_identity_ephemeral_key_secret(*, session_id: str) -> str | None:
    if not session_id or not stripe_configured():
        return None
    stripe = stripe_sdk()
    try:
        ephemeral_key = stripe.EphemeralKey.create(
            verification_session=session_id,
            stripe_version=_stripe_ephemeral_api_version(stripe),
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(getattr(exc, 'user_message', None) or getattr(exc, 'message', None) or exc)
        raise StripeIdentityError(f'Failed to create Identity ephemeral key: {msg}') from exc
    secret = getattr(ephemeral_key, 'secret', None)
    return str(secret) if secret else None


def _session_public_data(session: Any) -> dict[str, Any]:
    """
    Client payload for mobile SDKs.

    - iOS often uses ``client_secret``
    - Android native IdentityVerificationSheet needs ``verification_session_id`` +
      ``ephemeral_key_secret``
    - ``url`` supports the web/redirect fallback
    """
    session_id = str(getattr(session, 'id', None) or (session.get('id') if isinstance(session, dict) else '') or '')
    client_secret = getattr(session, 'client_secret', None)
    if client_secret is None and isinstance(session, dict):
        client_secret = session.get('client_secret')
    url = getattr(session, 'url', None)
    if url is None and isinstance(session, dict):
        url = session.get('url')
    expires_at = _stripe_unix_to_dt(
        getattr(session, 'expires_at', None)
        if not isinstance(session, dict)
        else session.get('expires_at')
    )
    ephemeral_key_secret = _create_identity_ephemeral_key_secret(session_id=session_id)
    return {
        'stripe_identity_verification_session_id': session_id,
        'verification_session_id': session_id,
        'client_secret': client_secret or None,
        'ephemeral_key_secret': ephemeral_key_secret,
        'url': url or None,
        'expires_at': _iso_dt(expires_at),
    }


def create_verification_session(
    *,
    master: Master,
    user,
    force_new_session: bool = False,
) -> dict[str, Any]:
    if not stripe_configured():
        raise StripeIdentityError('Stripe is not configured on the server.')

    status = _db_status(master)
    sid = _session_id(master)

    if is_identity_verification_locked(master):
        raise StripeIdentityAlreadyVerifiedError()

    stripe = stripe_sdk()

    if sid and not force_new_session and status in _ACTIVE_SESSION_STATUSES:
        try:
            existing = stripe.identity.VerificationSession.retrieve(sid)
            existing_status = _map_stripe_status(str(getattr(existing, 'status', '') or ''))
            if existing_status == MasterIdentityVerificationStatus.VERIFIED:
                apply_verification_session_to_master(master=master, session=existing)
                raise StripeIdentityAlreadyVerifiedError()
            if existing_status in _ACTIVE_SESSION_STATUSES:
                apply_verification_session_to_master(master=master, session=existing)
                return {
                    'message': 'Existing verification session is still active.',
                    'data': {
                        **_session_public_data(existing),
                        'identity_verification_status': _db_status(master),
                        'stripe_publishable_key': _publishable_key(),
                        'verification_checks': verification_checks_config(),
                        'poll_status_after_sdk': True,
                    },
                }
        except StripeIdentityAlreadyVerifiedError:
            raise
        except Exception:
            pass

    if sid and force_new_session:
        try:
            stripe.identity.VerificationSession.cancel(sid)
        except Exception:
            pass

    metadata = {
        'master_id': str(master.pk),
        'user_id': str(getattr(user, 'pk', '') or ''),
    }
    email = (getattr(user, 'email', None) or '').strip()
    if email:
        metadata['user_email'] = email[:255]

    try:
        session = stripe.identity.VerificationSession.create(
            type='document',
            metadata=metadata,
            options={'document': _document_session_options()},
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(getattr(exc, 'user_message', None) or getattr(exc, 'message', None) or exc)
        raise StripeIdentityError(msg) from exc

    master.stripe_identity_verification_session_id = str(session.id)
    master.identity_verification_status = MasterIdentityVerificationStatus.PENDING
    master.identity_verified_at = None
    master.identity_last_error_code = ''
    master.save(
        update_fields=[
            'stripe_identity_verification_session_id',
            'identity_verification_status',
            'identity_verified_at',
            'identity_last_error_code',
            'updated_at',
        ]
    )

    return {
        'message': 'Identity verification session created.',
        'data': {
            **_session_public_data(session),
            'identity_verification_status': MasterIdentityVerificationStatus.PENDING,
            'stripe_publishable_key': _publishable_key(),
            'verification_checks': verification_checks_config(),
            'poll_status_after_sdk': True,
        },
    }


def handle_stripe_identity_webhook_event(*, event: dict[str, Any]) -> bool:
    """
    Apply Identity verification session events to Master.
    Returns True if the event was handled.
    """
    event_type = str(event.get('type') or '')
    if not event_type.startswith('identity.verification_session.'):
        return False

    obj = event.get('data', {}).get('object') or {}
    session_id = str(obj.get('id') or '').strip()
    if not session_id:
        return False

    master = None
    meta = obj.get('metadata') or {}
    master_id = meta.get('master_id')
    if master_id:
        try:
            master = Master.objects.filter(pk=int(master_id)).first()
        except (TypeError, ValueError):
            master = None
    if master is None:
        master = Master.objects.filter(stripe_identity_verification_session_id=session_id).first()
    if master is None:
        return False

    if is_identity_verification_locked(master):
        return True

    apply_verification_session_to_master(master=master, session=obj)
    return True
