"""Per-request caches shared across nested serializers (survives context dict copies)."""
from __future__ import annotations

from typing import Any


def request_serializer_cache(context: dict | None, bucket: str) -> dict[str, Any]:
    """
    Mutable dict keyed by bucket, stored on ``request`` for the lifetime of one HTTP call.
    Use for Stripe balance, min-price lookups, etc.
    """
    if not context:
        return {}
    request = context.get('request')
    if request is None:
        return context.setdefault(f'_local_{bucket}', {})
    attr = f'_autohandy_ser_cache_{bucket}'
    cache = getattr(request, attr, None)
    if cache is None:
        cache = {}
        setattr(request, attr, cache)
    return cache
