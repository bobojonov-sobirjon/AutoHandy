"""Push / outbound notifications for orders (extend with FCM/APNs)."""
from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone as django_timezone
if TYPE_CHECKING:
    from django.http import HttpRequest

    from apps.order.models import Order

logger = logging.getLogger(__name__)

_FIREBASE_APPS: dict[str, Any] = {}


def _env(key: str, default: str = '') -> str:
    return (os.getenv(key, default) or '').strip()


def _fcm_debug_enabled() -> bool:
    return _env('FCM_DEBUG', '').lower() in ('1', 'true', 'yes', 'on')


def _fcm_dbg(msg: str) -> None:
    if _fcm_debug_enabled():
        try:
            print(f'[FCM_DEBUG] {msg}')
        except Exception:  # noqa: BLE001
            return


def _fcm_error_means_invalid_token(err: Any) -> bool:
    """True when FCM says this registration token must be dropped (stale app, reinstall, wrong project)."""
    if err is None:
        return False
    try:
        import firebase_admin.exceptions as fb_exc

        if isinstance(err, fb_exc.NotFoundError):
            return True
        if isinstance(err, fb_exc.InvalidArgumentError):
            return True
    except Exception:  # noqa: BLE001
        pass
    code = str(getattr(err, 'code', '') or '')
    msg = str(err).lower()
    code_l = code.lower()
    if 'not_found' in code_l or code_l == 'not_found':
        return True
    if 'registration-token-not-registered' in code_l:
        return True
    if 'invalid-argument' in code_l:
        return True
    if 'notregistered' in msg or 'not registered' in msg or 'requested entity was not found' in msg:
        return True
    if 'invalid registration' in msg:
        return True
    return False


def _firebase_service_account_from_env(prefix: str) -> dict[str, str]:
    pk = _env(f'{prefix}PRIVATE_KEY')
    if '\\n' in pk:
        pk = pk.replace('\\n', '\n')
    return {
        'type': _env(f'{prefix}TYPE', 'service_account'),
        'project_id': _env(f'{prefix}PROJECT_ID'),
        'private_key_id': _env(f'{prefix}PRIVATE_KEY_ID'),
        'private_key': pk,
        'client_email': _env(f'{prefix}CLIENT_EMAIL'),
        'client_id': _env(f'{prefix}CLIENT_ID'),
        'auth_uri': _env(f'{prefix}AUTH_URI', 'https://accounts.google.com/o/oauth2/auth'),
        'token_uri': _env(f'{prefix}TOKEN_URI', 'https://oauth2.googleapis.com/token'),
        'auth_provider_x509_cert_url': _env(
            f'{prefix}AUTH_PROVIDER_X509_CERT_URL',
            'https://www.googleapis.com/oauth2/v1/certs',
        ),
        'client_x509_cert_url': _env(f'{prefix}CLIENT_X509_CERT_URL'),
    }


def _get_firebase_app(_kind: str):
    """
    Firebase Admin app init.

    This backend is configured to use a single Firebase project/credential for *all* pushes
    (both customer + provider apps). Therefore we keep a single cached app instance.
    """
    cache_key = 'default'
    if cache_key in _FIREBASE_APPS:
        return _FIREBASE_APPS[cache_key]

    try:
        import firebase_admin
        from firebase_admin import credentials
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError('firebase-admin is not installed') from exc

    # Project selection:
    # - Use FIREBASE_MASTER_* for all pushes (single Firebase project).
    prefix = 'FIREBASE_MASTER_'
    sa = _firebase_service_account_from_env(prefix)
    if not sa.get('project_id') or not sa.get('private_key') or not sa.get('client_email'):
        raise RuntimeError(f'Firebase env missing (prefix {prefix})')

    cred = credentials.Certificate(sa)
    logger.warning(
        'FCM init app (project_id=%s client_email=%s)',
        sa.get('project_id'),
        (sa.get('client_email') or '').split('@')[0] + '@…',
    )
    _fcm_dbg(f'init app project_id={sa.get("project_id")}')
    app = firebase_admin.initialize_app(cred, name='autohandy_default')
    _FIREBASE_APPS[cache_key] = app
    return app


def _device_tokens_for_user(user_id: int) -> list[str]:
    from apps.accounts.models import UserDevice

    tokens = list(
        UserDevice.objects.filter(user_id=user_id, is_active=True)
        .order_by('-updated_at')
        .values_list('device_token', flat=True)
    )
    _fcm_dbg(f'devices_lookup user_id={user_id} rows={len(tokens)}')
    seen = set()
    out: list[str] = []
    empty = 0
    for t in tokens:
        t = (t or '').strip()
        if not t:
            empty += 1
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    if empty:
        _fcm_dbg(f'devices_lookup user_id={user_id} empty_tokens={empty}')
    if out:
        sample = out[0]
        _fcm_dbg(f'devices_lookup user_id={user_id} unique_tokens={len(out)} sample_prefix={sample[:12]}…')
    return out


def send_fcm_to_user_devices(
    *,
    user_id: int,
    firebase_kind: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> None:
    """
    Best-effort FCM send. Does not raise.
    firebase_kind: "user" or "master"
    """
    try:
        from firebase_admin import messaging
    except Exception as exc:  # noqa: BLE001
        logger.warning('FCM skipped (firebase-admin not available): %s', exc)
        _fcm_dbg(f'skipped: firebase-admin not available: {exc}')
        return

    tokens = _device_tokens_for_user(user_id)
    if not tokens:
        logger.warning('FCM no_tokens (kind=%s user_id=%s)', firebase_kind, user_id)
        _fcm_dbg(f'no_tokens kind={firebase_kind} user_id={user_id}')
        return

    try:
        app = _get_firebase_app(firebase_kind)
    except Exception as exc:  # noqa: BLE001
        logger.warning('FCM init failed (kind=%s): %s', firebase_kind, exc)
        _fcm_dbg(f'init_failed kind={firebase_kind} user_id={user_id}: {exc}')
        return

    logger.warning(
        'FCM send attempt (kind=%s user_id=%s tokens=%s title=%s)',
        firebase_kind,
        user_id,
        len(tokens),
        (title or '')[:60],
    )
    _fcm_dbg(
        f'send_attempt kind={firebase_kind} user_id={user_id} tokens={len(tokens)} title={(title or "")[:60]}'
    )

    payload_data = {str(k): str(v) for k, v in (data or {}).items()}
    # Ensure devices wake promptly and play sound consistently (iOS + Android).
    channel_id = str(getattr(settings, 'PUSH_ANDROID_CHANNEL_ID', '') or '').strip() or 'high_importance_channel'
    msg = messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(title=title, body=body),
        data=payload_data,
        android=messaging.AndroidConfig(
            priority='high',
            notification=messaging.AndroidNotification(
                sound='default',
                channel_id=channel_id,
            ),
        ),
        apns=messaging.APNSConfig(
            headers={'apns-priority': '10'},
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    sound='default',
                )
            ),
        ),
    )
    try:
        # firebase-admin 7.x removed send_multicast in favor of send_each_for_multicast.
        if hasattr(messaging, 'send_each_for_multicast'):
            resp = messaging.send_each_for_multicast(msg, app=app)
        elif hasattr(messaging, 'send_multicast'):
            resp = messaging.send_multicast(msg, app=app)
        else:
            # Very old fallback (should not happen in this project): expand into per-token messages.
            messages = [
                messaging.Message(
                    token=t,
                    notification=messaging.Notification(title=title, body=body),
                    data=payload_data,
                )
                for t in tokens
            ]
            resp = messaging.send_all(messages, app=app)
    except Exception as exc:  # noqa: BLE001
        logger.warning('FCM send failed (kind=%s user_id=%s): %s', firebase_kind, user_id, exc)
        _fcm_dbg(f'send_failed kind={firebase_kind} user_id={user_id}: {exc}')
        return

    logger.warning(
        'FCM send result (kind=%s user_id=%s success=%s failure=%s)',
        firebase_kind,
        user_id,
        getattr(resp, 'success_count', None),
        getattr(resp, 'failure_count', None),
    )
    _fcm_dbg(
        f'send_result kind={firebase_kind} user_id={user_id} success={getattr(resp,"success_count",None)} '
        f'failure={getattr(resp,"failure_count",None)}'
    )

    invalid_tokens: list[str] = []
    for i, r in enumerate(resp.responses):
        if r.success:
            continue
        err = getattr(r, 'exception', None)
        code = getattr(err, 'code', '') if err else ''
        msg_txt = str(err) if err else ''
        # Log first few failures for diagnostics.
        if i < 3:
            logger.warning(
                'FCM send failure detail (kind=%s user_id=%s token_idx=%s code=%s err=%s)',
                firebase_kind,
                user_id,
                i,
                code,
                (msg_txt or '')[:200],
            )
        _fcm_dbg(
            f'failure_detail kind={firebase_kind} user_id={user_id} token_idx={i} '
            f'code={code} err={(msg_txt or "")[:200]} invalid_token={_fcm_error_means_invalid_token(err)}'
        )
        if _fcm_error_means_invalid_token(err):
            invalid_tokens.append(tokens[i])
    if invalid_tokens:
        try:
            from apps.accounts.models import UserDevice

            deleted, _ = UserDevice.objects.filter(device_token__in=invalid_tokens).delete()
            logger.warning(
                'FCM cleaned invalid tokens (kind=%s user_id=%s removed_rows=%s)',
                firebase_kind,
                user_id,
                deleted,
            )
            _fcm_dbg(
                f'token_cleanup kind={firebase_kind} user_id={user_id} removed_rows={deleted} '
                f'(client must re-register via POST /api/auth/device/)'
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning('FCM token cleanup failed: %s', exc)


def format_money_for_push(
    *,
    amount_cents: int | None = None,
    amount_str: str | None = None,
    currency: str | None = None,
) -> str:
    """Human-readable amount for push body (e.g. ``$10.00``)."""
    from decimal import Decimal

    cur = (currency or getattr(settings, 'STRIPE_CHARGE_CURRENCY', 'usd') or 'usd').strip().lower()
    if amount_str not in (None, ''):
        try:
            val = Decimal(str(amount_str).replace(',', '').strip())
        except Exception:  # noqa: BLE001
            val = None
        if val is not None:
            sym = '$' if cur in ('usd', 'cad') else ''
            return f'{sym}{val:.2f}'
    if amount_cents is not None and int(amount_cents) > 0:
        sym = '$' if cur in ('usd', 'cad') else ''
        return f'{sym}{Decimal(int(amount_cents)) / Decimal(100):.2f}'
    return ''


def _pro_push_copy(
    *,
    kind: str,
    order_id: int | None,
    audience: str,
    extra_data: dict[str, str] | None,
    fallback_title: str,
    fallback_body: str,
) -> tuple[str, str]:
    """
    Central place for polished push copy.
    audience: "user" (customer/driver app) or "master" (provider app)
    """
    k = (kind or '').strip()
    by = (extra_data or {}).get('by') if extra_data else None
    order_type = (extra_data or {}).get('order_type') if extra_data else None
    push_source = (extra_data or {}).get('push_source') if extra_data else None
    oid = f'#{order_id}' if order_id else ''

    if k == 'order_new' and audience == 'master':
        if (order_type or '').lower() == 'sos':
            return (
                'Emergency request',
                f'Urgent SOS order received. Tap to respond now — {oid}'.strip(),
            )
        return 'New order received', f'A new order is waiting for you. Tap to view — {oid}'.strip()

    if k == 'offer_expiring_soon':
        mins = (extra_data or {}).get('minutes_left') if extra_data else None
        if audience == 'user':
            if mins:
                return 'Order update', f'Order {oid}: waiting for master response. About {mins} min left.'.strip()
            return 'Order update', f'Order {oid}: waiting for master response. The timer ends soon.'.strip()
        if mins:
            return 'Response needed', f'Order {oid}: about {mins} min left to accept or decline.'.strip()
        return 'Response needed', f'Order {oid}: please accept or decline before the timer ends.'.strip()

    if k == 'offer_expired':
        if audience == 'user':
            return 'Order expired', f'Order {oid}: no master accepted in time. Please choose another master.'.strip()
        return 'Offer expired', f'Order {oid}: the response window ended.'.strip()

    if k == 'sos_expiring_soon' and audience == 'user':
        mins = (extra_data or {}).get('minutes_left') if extra_data else None
        if mins:
            return 'SOS update', f'SOS order {oid}: about {mins} min left for a response.'.strip()
        return 'SOS update', f'SOS order {oid}: the response window ends very soon.'.strip()

    if k == 'sos_expired' and audience == 'user':
        return 'SOS request expired', f'SOS order {oid}: no master responded in time. Please try again.'.strip()

    if k == 'penalty_free_unlock_soon':
        if audience == 'user':
            return 'Cancellation update', f'Order {oid}: penalty-free cancellation will unlock soon.'.strip()
        return 'Cancellation update', f'Order {oid}: the customer will be able to cancel without penalty soon.'.strip()

    if k == 'penalty_free_unlocked':
        if audience == 'user':
            return 'Cancellation unlocked', f'Order {oid}: you can now cancel without a penalty (while the master is on the way).'.strip()
        return 'Cancellation unlocked', f'Order {oid}: the customer can now cancel without a penalty (while you are on the way).'.strip()

    if k == 'arrival_deadline_soon':
        if audience == 'user':
            return 'Arrival reminder', f'Order {oid}: the arrival deadline is approaching.'.strip()
        return 'Arrival deadline approaching', f'Order {oid}: please arrive before the deadline to avoid auto-cancel.'.strip()

    if k == 'auto_cancel_no_show':
        if audience == 'user':
            return 'Order cancelled', f'Order {oid} was cancelled because the master did not arrive in time.'.strip()
        return 'Order cancelled', f'Order {oid} was auto-cancelled because the arrival deadline passed.'.strip()

    if k == 'order_selected' and audience == 'master':
        return (
            'You were selected',
            f'A customer selected you for order {oid}. Tap to review and accept.'.strip(),
        )

    if k == 'custom_request_new' and audience == 'master':
        return (
            'New custom request nearby',
            f'A customer posted a custom request near you. Tap to view and send your price — {oid}'.strip(),
        )

    if k == 'custom_request_offer' and audience == 'user':
        price = (extra_data or {}).get('price') if extra_data else None
        master_name = (extra_data or {}).get('master_name') if extra_data else None
        if price and master_name:
            return (
                'New offer received',
                f'{master_name} offered {price} for your request {oid}. Tap to view.'.strip(),
            )
        if price:
            return (
                'New offer received',
                f'You received an offer of {price} for your request {oid}. Tap to view.'.strip(),
            )
        return 'New offer received', f'You received a new offer for your request {oid}. Tap to view.'.strip()

    if k == 'order_accepted' and audience == 'user':
        return 'Order accepted', f'Good news — a master accepted your order {oid}. Tap to view details.'.strip()

    if k == 'order_declined' and audience == 'user':
        return 'Order declined', f'Your order {oid} was declined. You can try again or choose another master.'.strip()

    if k == 'order_cancelled':
        if audience == 'user' and by == 'master':
            return 'Order cancelled', f'The master cancelled your order {oid}. Tap to see details.'.strip()
        if audience == 'master' and by == 'user':
            return 'Order cancelled', f'The customer cancelled order {oid}.'.strip()
        return 'Order cancelled', f'Order {oid} was cancelled.'.strip()

    if k == 'cancellation_penalty_charged' and audience == 'user':
        cents_raw = (extra_data or {}).get('amount_cents')
        try:
            cents_val = int(cents_raw) if cents_raw not in (None, '') else None
        except (TypeError, ValueError):
            cents_val = None
        amt = format_money_for_push(
            amount_cents=cents_val,
            amount_str=(extra_data or {}).get('amount_display'),
            currency=(extra_data or {}).get('currency'),
        )
        pct = (extra_data or {}).get('penalty_percent') if extra_data else None
        pct_s = str(pct).strip() if pct not in (None, '') else ''
        if amt and pct_s and pct_s != '0':
            return (
                'Cancellation fee charged',
                f'{amt} was charged to your saved card for cancelling order {oid} ({pct_s}% fee). '
                f'Tap to view details.',
            )
        if amt:
            return (
                'Cancellation fee charged',
                f'{amt} was charged to your saved card because you cancelled order {oid}. Tap to view details.',
            )
        return (
            'Cancellation fee charged',
            f'A cancellation fee was charged to your saved card for order {oid}. Tap to view details.',
        )

    if k == 'order_payment_charged' and audience == 'user':
        cents_raw = (extra_data or {}).get('amount_cents')
        try:
            cents_val = int(cents_raw) if cents_raw not in (None, '') else None
        except (TypeError, ValueError):
            cents_val = None
        amt = format_money_for_push(
            amount_cents=cents_val,
            amount_str=(extra_data or {}).get('amount_display'),
            currency=(extra_data or {}).get('currency'),
        )
        if amt:
            return (
                'Payment processed',
                f'Your order {oid} is complete. {amt} was charged to your saved card. Tap to view the receipt.',
            )
        return (
            'Payment processed',
            f'Your order {oid} is complete. Your saved card was charged. Tap to view details.',
        )

    if k == 'order_completed' and audience == 'user':
        amt = ''
        if extra_data:
            try:
                cents = int(extra_data.get('amount_cents') or 0)
            except (TypeError, ValueError):
                cents = 0
            if cents > 0:
                amt = format_money_for_push(
                    amount_cents=cents,
                    currency=extra_data.get('currency'),
                )
        if amt:
            return (
                'Order completed',
                f'Your order {oid} is complete. {amt} was charged to your saved card. Thank you!',
            )
        return 'Order completed', f'Your order {oid} has been marked as completed. Tap to review the details.'.strip()

    if k == 'completion_pin_invalid' and audience == 'user':
        return 'PIN incorrect', f'Order {oid}: the master entered an incorrect completion PIN. Please double-check and try again.'.strip()

    if k == 'order_services_added' and audience == 'user':
        cnt_raw = (extra_data or {}).get('service_count') if extra_data else None
        try:
            cnt = int(cnt_raw) if cnt_raw is not None else 0
        except (TypeError, ValueError):
            cnt = 0
        if cnt > 0:
            return (
                'Services updated',
                f'The master added {cnt} service{"s" if cnt != 1 else ""} to your order {oid}. Tap to review.'.strip(),
            )
        return 'Services updated', f'The master updated the services for your order {oid}. Tap to review.'.strip()

    if k == 'review_created' and audience == 'master':
        stars = (extra_data or {}).get('rating') if extra_data else None
        who = (extra_data or {}).get('reviewer_name') if extra_data else None
        if stars and who:
            return 'New review received', f'{who} left a {stars}-star review for order {oid}. Tap to view.'.strip()
        if stars:
            return 'New review received', f'You received a {stars}-star review for order {oid}. Tap to view.'.strip()
        return 'New review received', f'You received a new review for order {oid}. Tap to view.'.strip()

    if k == 'payout_scheduled_today' and audience == 'master':
        day = ((extra_data or {}).get('anchor_day') or 'today').strip().capitalize()
        interval = ((extra_data or {}).get('interval') or 'weekly').strip().lower()
        if interval == 'weekly':
            return (
                'Bank payout today',
                f'Today is your scheduled payout day ({day}). Stripe will transfer your available '
                f'balance to your linked bank. Funds usually arrive within 1–2 business days. '
                f'Check Payouts in the app for details.',
            )
        return (
            'Payout scheduled',
            f'Your Stripe payout schedule runs on {interval} payouts. Check your balance and '
            f'Payouts in the app for transfer status.',
        )

    if k == 'order_status_changed':
        if audience == 'user':
            return fallback_title or 'Order update', fallback_body or f'Your order {oid} has an update.'.strip()
        return fallback_title or 'Order update', fallback_body or f'Order {oid} has an update.'.strip()

    return fallback_title, fallback_body


def _ws_json_safe(value: Any) -> Any:
    """Make nested dicts safe for Channels (Redis JSON) and ``json.dumps`` on the consumer."""
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _absolute_media_path(request: 'HttpRequest | None', relative_url: str) -> str:
    """Turn /media/... into full URL. Prefer API_PUBLIC_BASE_URL (SOS rotation has no request)."""
    if not relative_url:
        return relative_url
    if relative_url.startswith('http://') or relative_url.startswith('https://'):
        return relative_url
    base = (getattr(settings, 'API_PUBLIC_BASE_URL', '') or '').strip().rstrip('/')
    if base:
        path = relative_url if relative_url.startswith('/') else f'/{relative_url}'
        return f'{base}{path}'
    if request:
        return request.build_absolute_uri(relative_url)
    return relative_url


def _media_url(request: 'HttpRequest | None', file_field) -> str | None:
    if not file_field:
        return None
    try:
        url = file_field.url
    except ValueError:
        return None
    return _absolute_media_path(request, url)


def build_sos_order_websocket_payload(
    order: 'Order',
    *,
    request: 'HttpRequest | None' = None,
    offered_master_id: int | None = None,
) -> dict[str, Any]:
    """
    Rich SOS offer payload for WebSocket (exact location for emergency).
    """
    from apps.order.models import Order as OrderModel
    from decimal import Decimal
    from apps.order.services.order_pricing import compute_order_price_breakdown

    oid = order.pk
    order = (
        OrderModel.objects.filter(pk=oid)
        .select_related('user')
        .prefetch_related(
            'car__category',
            'category',
            'order_services__master_service_item__category',
            'order_services__master_service_item__category__parent',
            'images',
        )
        .get(pk=oid)
    )

    u = order.user
    full_name = (u.get_full_name() or '').strip() or None

    user_out: dict[str, Any] = {
        'id': u.id,
        'private_id': u.private_id,
        'first_name': u.first_name or '',
        'last_name': u.last_name or '',
        'full_name': full_name,
        'phone_number': getattr(u, 'phone_number', None) or None,
        'email': getattr(u, 'email', None) or None,
        'avatar': _media_url(request, getattr(u, 'avatar', None)),
    }

    car_data: list[dict[str, Any]] = []
    for car in order.car.all():
        cat = car.category
        car_data.append(
            {
                'id': car.id,
                'brand': car.brand,
                'model': car.model,
                'year': car.year,
                'image': _media_url(request, car.image),
                'category': (
                    {
                        'id': cat.id,
                        'name': cat.name,
                        'type_category': cat.type_category,
                        'parent_id': cat.parent_id,
                    }
                    if cat
                    else None
                ),
            }
        )

    category_data = [
        {
            'id': c.id,
            'name': c.name,
            'type_category': c.type_category,
            'parent_id': c.parent_id,
        }
        for c in order.category.all()
    ]

    bd = compute_order_price_breakdown(order)
    em = bd.get('emergency') or {}
    coef = em.get('coefficient', Decimal('1.0'))
    coef_s = format(Decimal(str(coef)), 'f')

    services_out: list[dict[str, Any]] = []
    # SOS broadcast offers do not assign a master on the order. Prices must be shown per-target master:
    # use MasterServiceItems (base price set by that master) for the order categories.
    if offered_master_id and not order.order_services.exists():
        try:
            from apps.master.models import MasterServiceItems
            from apps.categories.models import Category

            car_count = max(1, order.car.count())
            cat_ids = list(order.category.values_list('id', flat=True))
            items = (
                MasterServiceItems.objects.filter(
                    master_service__master_id=int(offered_master_id),
                    category_id__in=cat_ids,
                )
                .select_related('category')
            )
            subtotal = Decimal('0')
            for it in items:
                cat = it.category
                base = Decimal(str(it.price or 0))
                final = (base * Decimal(str(coef))).quantize(Decimal('0.01'))
                line_total = (final * Decimal(str(car_count))).quantize(Decimal('0.01'))
                subtotal += line_total
                services_out.append(
                    {
                        'id': it.id,
                        'service_name': cat.name if cat else None,
                        'category_id': cat.id if cat else None,
                        'type_category': cat.type_category if cat else None,
                        'base_price': format(base, 'f'),
                        'emergency_coefficient': coef_s,
                        'final_price': format(final, 'f'),
                        'line_total': format(line_total, 'f'),
                    }
                )
            # Replace pricing totals for WS (discount not applied in SOS offer list).
            pen = Decimal(str(bd.get('penalty_total', 0)))
            if pen < 0:
                pen = Decimal('0')
            bd = {
                **bd,
                'subtotal': subtotal,
                'discount_applied': Decimal('0'),
                'work_total': subtotal,
                'penalty_total': pen,
                'total': (subtotal + pen).quantize(Decimal('0.01')),
            }
        except Exception:  # noqa: BLE001
            pass
    else:
        for os_row in order.order_services.all():
            msi = os_row.master_service_item
            if not msi:
                continue
            cat = msi.category
            meta = (bd.get('lines_by_order_service_id') or {}).get(os_row.id) or {}
            final_unit = meta.get('unit_price')
            services_out.append(
                {
                    'id': msi.id,
                    'service_name': cat.name if cat else None,
                    'category_id': cat.id if cat else None,
                    'type_category': cat.type_category if cat else None,
                    'base_price': str(msi.price) if msi.price is not None else None,
                    'emergency_coefficient': format(Decimal(str(meta.get('emergency_coefficient', coef_s))), 'f'),
                    'final_price': (
                        format(Decimal(str(final_unit)), 'f')
                        if final_unit is not None
                        else (str(msi.price) if msi.price is not None else None)
                    ),
                    'line_total': (
                        format(Decimal(str(meta.get('line_total'))), 'f')
                        if meta.get('line_total') is not None
                        else None
                    ),
                }
            )

    order_images = [
        {
            'id': im.id,
            'image': _media_url(request, im.image),
            'created_at': im.created_at.isoformat() if im.created_at else None,
        }
        for im in order.images.all()
    ]

    queue = order.sos_offer_queue or []
    sos_broadcast = bool(queue)
    seconds = int(
        getattr(settings, 'SOS_BROADCAST_RESPONSE_SECONDS', 120)
        if sos_broadcast
        else getattr(settings, 'SOS_OFFER_SECONDS_PER_MASTER', 30)
    )

    return {
        'order_id': order.id,
        'status': order.status,
        'text': (order.text or '')[:4000],
        'location': order.location or '',
        'latitude': str(order.latitude) if order.latitude is not None else None,
        'longitude': str(order.longitude) if order.longitude is not None else None,
        'location_source': order.location_source,
        'priority': order.priority,
        'order_type': order.order_type,
        'discount': str(order.discount) if order.discount is not None else None,
        'parts_purchase_required': order.parts_purchase_required,
        'parts_purchase_required_json': getattr(order, 'parts_purchase_required_json', None) or [],
        'preferred_date': (
            order.preferred_date.isoformat() if order.preferred_date else None
        ),
        'preferred_time_start': (
            order.preferred_time_start.isoformat()
            if order.preferred_time_start
            else None
        ),
        'preferred_time_end': (
            order.preferred_time_end.isoformat()
            if order.preferred_time_end
            else None
        ),
        'created_at': order.created_at.isoformat() if order.created_at else None,
        'updated_at': order.updated_at.isoformat() if order.updated_at else None,
        'user': user_out,
        'car_data': car_data,
        'category_data': category_data,
        'services': services_out,
        'pricing': {
            'subtotal': format(Decimal(str(bd.get('subtotal', 0))), 'f'),
            'discount_applied': format(Decimal(str(bd.get('discount_applied', 0))), 'f'),
            'work_total': format(Decimal(str(bd.get('work_total', bd.get('total', 0)))), 'f'),
            'penalty_total': format(Decimal(str(bd.get('penalty_total', 0))), 'f'),
            'total': format(Decimal(str(bd.get('total', 0))), 'f'),
            'emergency_pricing': {
                **em,
                'coefficient': coef_s,
            },
        },
        'order_images': order_images,
        'master_response_deadline': (
            order.master_response_deadline.isoformat() if order.master_response_deadline else None
        ),
        'seconds': seconds,
        'sos_offer_index': order.sos_offer_index,
        'sos_queue_length': len(queue),
        'sos_broadcast': sos_broadcast,
        'offered_master_id': offered_master_id,
    }


def build_custom_request_websocket_payload(
    order: 'Order',
    *,
    request: 'HttpRequest | None' = None,
) -> dict[str, Any]:
    """Payload for masters on ``custom_request_push`` — category labels are neutral (no catalog leakage)."""
    from apps.order.models import Order as OrderModel

    oid = order.pk
    order = (
        OrderModel.objects.filter(pk=oid)
        .select_related('user')
        .prefetch_related('car__category', 'category', 'images')
        .get(pk=oid)
    )
    u = order.user
    full_name = (u.get_full_name() or '').strip() or None
    user_out: dict[str, Any] = {
        'id': u.id,
        'private_id': u.private_id,
        'first_name': u.first_name or '',
        'last_name': u.last_name or '',
        'full_name': full_name,
        'phone_number': getattr(u, 'phone_number', None) or None,
        'email': getattr(u, 'email', None) or None,
        'avatar': _media_url(request, getattr(u, 'avatar', None)),
    }
    car_data: list[dict[str, Any]] = []
    for car in order.car.all():
        cat = car.category
        car_data.append(
            {
                'id': car.id,
                'brand': car.brand,
                'model': car.model,
                'year': car.year,
                'image': _media_url(request, car.image),
                'category': (
                    {
                        'id': cat.id,
                        'name': cat.name,
                        'type_category': cat.type_category,
                        'parent_id': cat.parent_id,
                    }
                    if cat
                    else None
                ),
            }
        )
    mask = 'Incoming request'
    category_data = [
        {
            'id': c.id,
            'name': mask,
            'type_category': c.type_category,
            'parent_id': c.parent_id,
        }
        for c in order.category.all()
    ]
    order_images = [
        {
            'id': im.id,
            'image': _media_url(request, im.image),
            'created_at': im.created_at.isoformat() if im.created_at else None,
        }
        for im in order.images.all()
    ]
    return {
        'order_id': order.id,
        'kind': 'custom_request',
        'status': order.status,
        'text': (order.text or '')[:4000],
        'location': order.location or '',
        'latitude': str(order.latitude) if order.latitude is not None else None,
        'longitude': str(order.longitude) if order.longitude is not None else None,
        'location_source': order.location_source,
        'priority': order.priority,
        'order_type': order.order_type,
        'preferred_date': (
            order.preferred_date.isoformat() if getattr(order, 'preferred_date', None) else None
        ),
        'created_at': order.created_at.isoformat() if order.created_at else None,
        'updated_at': order.updated_at.isoformat() if order.updated_at else None,
        'user': user_out,
        'car_data': car_data,
        'category_data': category_data,
        'order_images': order_images,
    }


def notify_masters_broadcast_order_closed_websocket(
    *,
    order_id: int,
    order_type_value: str,
    recipient_master_ids: list[int],
    accepted_by_master_pk: int,
) -> None:
    """
    SOS / custom_request: tell other masters (same ``ws/sos/master/`` group) that the job is taken.
    Clients should drop ``order_id`` from local incoming-job lists without waiting for deadline.
    """
    layer = get_channel_layer()
    if not layer:
        return
    seen: set[int] = set()
    payload = _ws_json_safe(
        {
            'order_id': int(order_id),
            'order_type': str(order_type_value),
            'reason': 'accepted_elsewhere',
            'accepted_by_master_id': int(accepted_by_master_pk),
            'closed_at': django_timezone.now().isoformat(),
        }
    )
    message = {'type': 'incoming_job_closed', 'payload': payload}
    try:
        from apps.master.models import Master

        for raw_mid in recipient_master_ids:
            try:
                mid = int(raw_mid)
            except (TypeError, ValueError):
                continue
            if mid == int(accepted_by_master_pk):
                continue
            if mid in seen:
                continue
            seen.add(mid)
            try:
                mu = Master.objects.only('user_id').get(pk=mid)
            except Master.DoesNotExist:
                continue
            uid = int(mu.user_id)
            group = f'master_sos_{uid}'
            try:
                async_to_sync(layer.group_send)(group, message)
            except Exception as exc:  # noqa: BLE001
                logger.warning('incoming_job_closed group_send failed user_id=%s order_id=%s: %s', uid, order_id, exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning('notify_masters_broadcast_order_closed_websocket failed order_id=%s: %s', order_id, exc)


def push_custom_request_to_master_websocket(
    order: 'Order',
    *,
    request: 'HttpRequest | None' = None,
    target_master_id: int,
) -> None:
    """Real-time custom-request job to one master (same WS connection as SOS: ``ws/sos/master/``)."""
    try:
        from apps.master.models import Master

        master = Master.objects.select_related('user').get(pk=target_master_id)
        group = f'master_sos_{master.user_id}'
        layer = get_channel_layer()
        if not layer:
            return
        payload = build_custom_request_websocket_payload(order, request=request)
        async_to_sync(layer.group_send)(
            group,
            {'type': 'custom_request_push', 'payload': payload},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('push_custom_request_to_master_websocket failed: %s', exc)


def push_custom_request_offer_to_rider_websocket(
    order: 'Order',
    *,
    offer_id: int,
    master_id: int,
    price: str,
    created_at_iso: str | None,
    request: 'HttpRequest | None' = None,
) -> None:
    """Notify the client (driver) over ``ws/custom-request/rider/`` when a master submits a price."""
    try:
        from apps.master.api.serializers import MasterSerializer
        from apps.master.models import Master
        from apps.master.services.geo import haversine_distance_km

        master = (
            Master.objects.select_related('user')
            .prefetch_related(
                'master_images',
                'master_services',
                'master_services__master_service_items',
                'master_services__master_service_items__category',
                'master_services__master_service_items__category__parent',
            )
            .get(pk=master_id)
        )

        wlat, wlon = master.get_work_location_for_distance()
        if (
            order.latitude is not None
            and order.longitude is not None
            and wlat is not None
            and wlon is not None
        ):
            master.distance = float(
                haversine_distance_km(
                    float(order.latitude),
                    float(order.longitude),
                    float(wlat),
                    float(wlon),
                )
            )
        else:
            master.distance = None

        layer = get_channel_layer()
        if not layer:
            return

        ctx: dict[str, Any] = {
            'request': request,
            'hide_master_exact_location': False,
            'embed_order_min_price': True,
        }
        first_cat = order.category.first()
        if first_cat is not None and not getattr(first_cat, 'is_custom_request_entry', False):
            ctx['filter_service_category_id'] = first_cat.id

        payload = _ws_json_safe(
            {
                'offer_id': offer_id,
                'order_id': order.id,
                'price': price,
                'created_at': created_at_iso,
                'master': MasterSerializer(master, context=ctx).data,
            }
        )
        group = f'rider_custom_request_{order.user_id}'
        async_to_sync(layer.group_send)(
            group,
            {'type': 'rider_custom_request_offer', 'payload': payload},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('push_custom_request_offer_to_rider_websocket failed: %s', exc)


def push_sos_order_to_master_websocket(
    order: 'Order',
    *,
    request: 'HttpRequest | None' = None,
    target_master_id: int | None = None,
) -> None:
    """
    Real-time SOS offer to master's WebSocket group.
    Connect: ws://.../ws/sos/master/?token=<JWT>

    Use Redis channel layer if HTTP and WS (or Celery) run in different processes.
    """
    from apps.order.models import OrderType
    from apps.order.services.master_service_zone import order_within_master_acceptance_zone

    mid = target_master_id if target_master_id is not None else order.master_id
    if not mid:
        return
    _fcm_dbg(f'push_sos_order_to_master_websocket order_id={getattr(order,"id",None)} target_master_id={mid}')
    if order.order_type == OrderType.SOS and not order_within_master_acceptance_zone(order, mid):
        logger.warning(
            'push_sos_order_to_master_websocket skipped: order %s not in master %s acceptance zone',
            order.id,
            mid,
        )
        return
    try:
        from apps.master.models import Master

        master = Master.objects.select_related('user').get(pk=mid)
        group = f'master_sos_{master.user_id}'
        layer = get_channel_layer()
        if not layer:
            return
        payload = build_sos_order_websocket_payload(
            order, request=request, offered_master_id=mid
        )
        async_to_sync(layer.group_send)(
            group,
            {'type': 'sos_order_push', 'payload': payload},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('push_sos_order_to_master_websocket failed: %s', exc)


def notify_master_new_order(order: 'Order', *, target_master_id: int | None = None) -> None:
    """
    Loud alert for new assignment (integrate mobile push + vibration on client).
    Hook: send FCM to order.master.user_id devices.
    """
    mid = target_master_id if target_master_id is not None else order.master_id
    if not mid:
        return
    try:
        from apps.master.models import Master

        master = Master.objects.select_related('user').only('id', 'user_id').get(pk=mid)
    except Exception as exc:  # noqa: BLE001
        logger.warning('notify_master_new_order: master lookup failed: %s', exc)
        return

    title, body = _pro_push_copy(
        kind='order_new',
        order_id=order.id,
        audience='master',
        extra_data={'order_type': str(getattr(order, 'order_type', '') or '')},
        fallback_title='New order received',
        fallback_body=f'A new order is waiting for you. Tap to view — #{order.id}',
    )
    logger.warning(
        'notify_master_new_order order_id=%s master_id=%s master_user_id=%s (FCM target user_id=%s)',
        order.id,
        mid,
        master.user_id,
        master.user_id,
    )
    _fcm_dbg(
        f'notify_master_new_order order_id={order.id} master_id={mid} master_user_id={master.user_id}'
    )
    send_fcm_to_user_devices(
        user_id=master.user_id,
        firebase_kind='master',
        title=title,
        body=body,
        data={
            'kind': 'order_new',
            'order_id': str(order.id),
            'order_type': str(getattr(order, 'order_type', '') or ''),
        },
    )


def notify_user_cancellation_penalty_charged(
    order: 'Order',
    *,
    amount_cents: int,
    penalty_percent: int,
    currency: str | None = None,
) -> None:
    """Push after a cancellation penalty is successfully captured on the driver's card."""
    cur = (currency or getattr(order, 'stripe_payment_currency', None) or '').strip()
    notify_user_order_event(
        order,
        title='Cancellation fee charged',
        body=f'Order #{order.id}: cancellation fee charged.',
        kind='cancellation_penalty_charged',
        extra_data={
            'amount_cents': str(int(amount_cents)),
            'penalty_percent': str(int(penalty_percent)),
            'currency': cur or getattr(settings, 'STRIPE_CHARGE_CURRENCY', 'usd'),
        },
    )


def notify_user_order_payment_charged(
    order: 'Order',
    *,
    amount_cents: int,
    currency: str | None = None,
) -> None:
    """Push after the full order total is charged on complete."""
    cur = (currency or getattr(order, 'stripe_payment_currency', None) or '').strip()
    notify_user_order_event(
        order,
        title='Payment processed',
        body=f'Order #{order.id}: payment charged.',
        kind='order_payment_charged',
        extra_data={
            'amount_cents': str(int(amount_cents)),
            'currency': cur or getattr(settings, 'STRIPE_CHARGE_CURRENCY', 'usd'),
        },
    )


def notify_user_order_event(
    order: 'Order',
    *,
    title: str,
    body: str,
    kind: str,
    extra_data: dict[str, str] | None = None,
) -> None:
    if not getattr(order, 'user_id', None):
        return
    _fcm_dbg(
        'notify_user_order_event '
        f'order_id={getattr(order,"id",None)} user_id={getattr(order,"user_id",None)} kind={kind} '
        f'title={(title or "")[:60]} extra_keys={list((extra_data or {}).keys())}'
    )
    title_out, body_out = _pro_push_copy(
        kind=kind,
        order_id=order.id,
        audience='user',
        extra_data=extra_data,
        fallback_title=title,
        fallback_body=body,
    )
    data = {'kind': kind, 'order_id': str(order.id)}
    if extra_data:
        data.update({str(k): str(v) for k, v in extra_data.items()})
    send_fcm_to_user_devices(
        user_id=order.user_id,
        firebase_kind='user',
        title=title_out,
        body=body_out,
        data=data,
    )


def notify_master_payout_day(
    *,
    master_user_id: int,
    anchor_day: str,
    interval: str = 'weekly',
) -> None:
    """Push on the configured weekly payout anchor (all Connect-linked masters)."""
    title_out, body_out = _pro_push_copy(
        kind='payout_scheduled_today',
        order_id=None,
        audience='master',
        extra_data={
            'anchor_day': anchor_day,
            'interval': interval,
        },
        fallback_title='Bank payout today',
        fallback_body='Your scheduled Stripe payout to your bank is processing today.',
    )
    send_fcm_to_user_devices(
        user_id=int(master_user_id),
        firebase_kind='master',
        title=title_out,
        body=body_out,
        data={
            'kind': 'payout_scheduled_today',
            'anchor_day': anchor_day,
            'interval': interval,
        },
    )


def notify_master_order_event(
    *,
    master_user_id: int,
    order_id: int,
    title: str,
    body: str,
    kind: str,
    extra_data: dict[str, str] | None = None,
) -> None:
    _fcm_dbg(
        'notify_master_order_event '
        f'order_id={order_id} master_user_id={master_user_id} kind={kind} '
        f'title={(title or "")[:60]} extra_keys={list((extra_data or {}).keys())}'
    )
    title_out, body_out = _pro_push_copy(
        kind=kind,
        order_id=order_id,
        audience='master',
        extra_data=extra_data,
        fallback_title=title,
        fallback_body=body,
    )
    data = {'kind': kind, 'order_id': str(order_id)}
    if extra_data:
        data.update({str(k): str(v) for k, v in extra_data.items()})
    send_fcm_to_user_devices(
        user_id=master_user_id,
        firebase_kind='master',
        title=title_out,
        body=body_out,
        data=data,
    )


def push_order_event_to_user_websocket(*, user_id: int, event_type: str, payload: dict) -> None:
    """
    Generic order-related real-time event to the order owner's websocket group.
    WS connect: ws://.../ws/order/user/?token=<JWT>
    """
    try:
        layer = get_channel_layer()
        if not layer:
            return
        group = f'order_user_{int(user_id)}'
        async_to_sync(layer.group_send)(
            group,
            {'type': 'order_user_event', 'event_type': str(event_type), 'payload': _ws_json_safe(payload)},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('push_order_event_to_user_websocket failed: %s', exc)


def push_order_event_to_master_websocket(*, master_user_id: int, event_type: str, payload: dict) -> None:
    """
    Generic order-related real-time event to the assigned master's websocket group.
    WS connect: ws://.../ws/order/master/?token=<JWT>
    """
    try:
        layer = get_channel_layer()
        if not layer:
            return
        group = f'order_master_{int(master_user_id)}'
        async_to_sync(layer.group_send)(
            group,
            {'type': 'order_master_event', 'event_type': str(event_type), 'payload': _ws_json_safe(payload)},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('push_order_event_to_master_websocket failed: %s', exc)
