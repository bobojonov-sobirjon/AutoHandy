"""Read Stripe Connect account balance + recent payouts (platform secret key)."""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from typing import Any

from django.conf import settings

from apps.payment.services.stripe_client import stripe_configured, stripe_sdk


class StripeConnectBalanceError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _cents_to_decimal_str(cents: int) -> str:
    return format(Decimal(cents) / Decimal('100'), 'f')


def _format_money_rows(rows: list) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        try:
            amt = int(getattr(row, 'amount', row.get('amount', 0) if isinstance(row, dict) else 0))
        except (TypeError, ValueError):
            amt = 0
        cur = str(getattr(row, 'currency', None) or (row.get('currency') if isinstance(row, dict) else '') or '')
        out.append(
            {
                'currency': cur.upper(),
                'amount_cents': amt,
                'amount': _cents_to_decimal_str(amt),
            }
        )
    return out


def _iso_from_unix(ts: int | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=dt_timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def fetch_connect_balance_and_payouts(
    *,
    stripe_connect_account_id: str,
    payout_limit: int = 20,
) -> dict[str, Any]:
    if not stripe_configured():
        raise StripeConnectBalanceError('Stripe is not configured on the server.')
    acct = (stripe_connect_account_id or '').strip()
    if not acct:
        raise StripeConnectBalanceError('No Stripe Connect account on file for this master.')

    stripe = stripe_sdk()
    try:
        bal = stripe.Balance.retrieve(stripe_account=acct)
    except Exception as exc:  # noqa: BLE001
        raise StripeConnectBalanceError(str(exc)) from exc

    available = _format_money_rows(getattr(bal, 'available', []) or [])
    pending = _format_money_rows(getattr(bal, 'pending', []) or [])
    instant = _format_money_rows(getattr(bal, 'instant_available', []) or [])

    recent: list[dict[str, Any]] = []
    try:
        plist = stripe.Payout.list(stripe_account=acct, limit=payout_limit)
        for po in getattr(plist, 'data', []) or []:
            recent.append(
                {
                    'id': str(getattr(po, 'id', '') or ''),
                    'amount_cents': int(getattr(po, 'amount', 0) or 0),
                    'amount': _cents_to_decimal_str(int(getattr(po, 'amount', 0) or 0)),
                    'currency': str(getattr(po, 'currency', '') or '').upper(),
                    'status': str(getattr(po, 'status', '') or ''),
                    'arrival_date': _iso_from_unix(getattr(po, 'arrival_date', None)),
                    'created': _iso_from_unix(getattr(po, 'created', None)),
                    'description': str(getattr(po, 'description', '') or '') or None,
                }
            )
    except Exception:  # noqa: BLE001
        pass

    note = getattr(settings, 'MASTER_PAYOUT_SCHEDULE_NOTE', None) or (
        'Earnings from card-paid orders appear on your Stripe Connect balance: first pending, then available. '
        'Automatic payouts to your bank follow Stripe’s schedule for this connected account (the platform may '
        'set a default such as weekly payouts; exact timing still depends on Stripe and your bank). '
        'This endpoint only reads Stripe; it does not change payout settings.'
    )

    return {
        'stripe_connect_account_id': acct,
        'livemode': bool(getattr(bal, 'livemode', False)),
        'available': available,
        'pending': pending,
        'instant_available': instant,
        'recent_payouts': recent,
        'payout_schedule_note': note,
    }


def try_fetch_connect_balance(stripe_connect_account_id: str) -> dict[str, Any] | None:
    """For serializers: never raises; returns None if unconfigured / no account / Stripe error."""
    acct = (stripe_connect_account_id or '').strip()
    if not acct or not stripe_configured():
        return None
    try:
        return fetch_connect_balance_and_payouts(stripe_connect_account_id=acct)
    except StripeConnectBalanceError:
        return None
    except Exception:  # noqa: BLE001
        return None


def list_connect_balance_transactions(
    stripe_connect_account_id: str,
    *,
    limit: int = 30,
    starting_after: str | None = None,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """
    Connected-account ledger lines (charges, payouts, fees, etc.).
    Returns (rows, has_more, last_id_for_next_page).
    """
    if not stripe_configured():
        return [], False, None
    acct = (stripe_connect_account_id or '').strip()
    if not acct:
        return [], False, None
    lim = max(1, min(int(limit), 100))
    stripe = stripe_sdk()
    params: dict[str, Any] = {'limit': lim, 'stripe_account': acct}
    if starting_after:
        params['starting_after'] = starting_after
    try:
        lst = stripe.BalanceTransaction.list(**params)
    except Exception:  # noqa: BLE001
        return [], False, None
    out: list[dict[str, Any]] = []
    for tx in getattr(lst, 'data', []) or []:
        amt = int(getattr(tx, 'amount', 0) or 0)
        fee = int(getattr(tx, 'fee', 0) or 0)
        net = int(getattr(tx, 'net', amt) or amt)
        out.append(
            {
                'id': str(getattr(tx, 'id', '') or ''),
                'type': str(getattr(tx, 'type', '') or ''),
                'amount_cents': amt,
                'amount': _cents_to_decimal_str(amt),
                'fee_cents': fee,
                'fee': _cents_to_decimal_str(fee),
                'net_cents': net,
                'net': _cents_to_decimal_str(net),
                'currency': str(getattr(tx, 'currency', '') or '').upper(),
                'description': str(getattr(tx, 'description', '') or '') or None,
                'created': _iso_from_unix(getattr(tx, 'created', None)),
            }
        )
    has_more = bool(getattr(lst, 'has_more', False))
    last_id = str(getattr(lst.data[-1], 'id', '') or '') if getattr(lst, 'data', None) else None
    return out, has_more, last_id
