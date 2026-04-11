"""Parse time strings from mobile / JSON (ISO, trailing Z)."""
from datetime import datetime, time

from rest_framework import serializers as drf_serializers


def parse_flexible_time(value):
    if isinstance(value, time):
        return value.replace(microsecond=0)
    s = str(value).strip()
    if not s:
        raise drf_serializers.ValidationError('Invalid time.')
    if s.endswith('Z') or s.endswith('z'):
        s = s[:-1]
    if 'T' in s:
        try:
            dt = datetime.fromisoformat(s)
            return dt.time().replace(microsecond=0)
        except ValueError:
            pass
    for fmt in ('%H:%M:%S.%f', '%H:%M:%S', '%H:%M'):
        try:
            return datetime.strptime(s, fmt).time().replace(microsecond=0)
        except ValueError:
            continue
    raise drf_serializers.ValidationError('Invalid time format.')
