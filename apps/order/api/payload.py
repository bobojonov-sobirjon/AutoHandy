"""Normalize driver order create payloads (JSON vs multipart/form-data)."""
from __future__ import annotations

import json

from django.http import QueryDict


def _flatten_request_data(data) -> dict:
    if isinstance(data, QueryDict):
        out = {}
        for key in data.keys():
            vals = data.getlist(key)
            out[key] = vals[0] if len(vals) == 1 else vals
        return out
    return dict(data)


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


def _flatten_int_ids(items):
    """Turn nested lists from bad clients into a flat list of ints."""
    out = []
    for x in items:
        if x is None or x == '':
            continue
        if isinstance(x, (list, tuple)):
            out.extend(_flatten_int_ids(x))
            continue
        if isinstance(x, bytes):
            x = x.decode('utf-8', errors='replace')
        out.append(int(x))
    return out


def _coerce_id_list(value):
    """
    Multipart / form fields send ``car_list`` / ``category_list`` as a single string like ``[1,2]``
    or repeated fields as ``['1','2']``. DRF ``ListField`` expects ``list[int]``.
    """
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode('utf-8', errors='replace')
    if isinstance(value, list):
        return _flatten_int_ids(value)
    if not isinstance(value, str):
        return value
    s = value.strip().lstrip('\ufeff').strip()
    if not s:
        return []
    if s.startswith('['):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return _flatten_int_ids(parsed)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    if ',' in s:
        parts = [p.strip() for p in s.split(',') if p.strip()]
        if parts and all(p.lstrip('-').isdigit() for p in parts):
            return [int(p) for p in parts]
    if s.lstrip('-').isdigit():
        return [int(s)]
    return value


def _strip_empty_optional_master_id(data: dict) -> None:
    """Multipart \"Send empty value\" sends ``master_id`` as ``''``; DRF IntegerField rejects that."""
    if 'master_id' not in data:
        return
    v = data['master_id']
    if isinstance(v, bytes):
        v = v.decode('utf-8', errors='replace')
        data['master_id'] = v
    if v is None:
        return
    if isinstance(v, str) and not v.strip():
        data.pop('master_id', None)


def normalize_order_create_request_data(request) -> dict:
    """
    - ``car_list`` / ``category_list``: JSON string or ``1,2`` or single id → ``list[int]``.
    - ``parts_purchase_required``: form truthy strings → bool.
    - ``master_id``: empty string (optional form field) → removed so SOS works without master.
    Drops stray ``images`` key from form text fields (files use ``request.FILES``).
    """
    data = _flatten_request_data(request.data)
    data.pop('images', None)

    _strip_empty_optional_master_id(data)

    for key in ('car_list', 'category_list'):
        if key in data:
            data[key] = _coerce_id_list(data.get(key))

    if 'parts_purchase_required' in data:
        data['parts_purchase_required'] = _coerce_bool(data['parts_purchase_required'])

    return data


def _coerce_tag_string_list(value):
    """Multipart / form: JSON array string, comma-separated, or repeated keys → list[str]."""
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode('utf-8', errors='replace')
    if isinstance(value, list):
        out = []
        for x in value:
            if x is None or x == '':
                continue
            if isinstance(x, bytes):
                x = x.decode('utf-8', errors='replace')
            s = str(x).strip()
            if s:
                out.append(s)
        return out
    if not isinstance(value, str):
        return value
    s = value.strip().lstrip('\ufeff').strip()
    if not s:
        return []
    if s.startswith('['):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    if ',' in s:
        return [p.strip() for p in s.split(',') if p.strip()]
    return [s]


def normalize_review_create_request_data(request) -> dict:
    """multipart/form-data: parse ``tags`` for review create (no file fields on review)."""
    data = _flatten_request_data(request.data)
    if 'tags' in data:
        data['tags'] = _coerce_tag_string_list(data['tags'])
    return data


def normalize_custom_request_create_data(request) -> dict:
    """Same list coercion as standard/SOS; no category_list (server assigns catalog row)."""
    data = _flatten_request_data(request.data)
    data.pop('images', None)
    if 'car_list' in data:
        data['car_list'] = _coerce_id_list(data.get('car_list'))
    if 'parts_purchase_required' in data:
        data['parts_purchase_required'] = _coerce_bool(data['parts_purchase_required'])
    from datetime import date as date_cls, datetime as datetime_cls

    req_alias = data.pop('request_date', None)
    crd = data.pop('custom_request_date', None)
    raw_date = crd if crd not in (None, '') else req_alias
    if raw_date is not None and raw_date != '':
        if isinstance(raw_date, datetime_cls):
            data['custom_request_date'] = raw_date.date()
        elif isinstance(raw_date, date_cls):
            data['custom_request_date'] = raw_date
        else:
            s = str(raw_date).strip()
            for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y'):
                try:
                    data['custom_request_date'] = datetime_cls.strptime(s, fmt).date()
                    break
                except ValueError:
                    continue
    return data


def attach_order_images_from_request(order, request, field_name: str = 'images') -> int:
    """Create ``OrderImage`` rows from ``request.FILES.getlist(field_name)``. Returns count added."""
    from apps.order.models import OrderImage

    n = 0
    for f in request.FILES.getlist(field_name):
        if f:
            OrderImage.objects.create(order=order, image=f)
            n += 1
    return n
