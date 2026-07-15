"""Build absolute media URLs that stay on HTTPS in production."""
from __future__ import annotations

from django.conf import settings


def absolute_media_url(request, file_field) -> str | None:
    """
    Return a full URL for an ImageField/FileField.

    Prefers ``API_PUBLIC_BASE_URL`` when set (avoids http:// behind nginx TLS
    termination). In non-DEBUG, upgrades accidental ``http://`` to ``https://``.
    """
    if not file_field:
        return None
    try:
        path = file_field.url
    except ValueError:
        return None
    return absolute_media_path(request, path)


def absolute_media_path(request, relative_url: str | None) -> str | None:
    if not relative_url:
        return relative_url
    if relative_url.startswith('https://'):
        return relative_url
    if relative_url.startswith('http://'):
        if not settings.DEBUG:
            return 'https://' + relative_url[len('http://') :]
        return relative_url

    base = (getattr(settings, 'API_PUBLIC_BASE_URL', '') or '').strip().rstrip('/')
    path = relative_url if relative_url.startswith('/') else f'/{relative_url}'
    if base:
        return f'{base}{path}'

    if request is not None:
        url = request.build_absolute_uri(path)
        if url.startswith('http://') and not settings.DEBUG:
            return 'https://' + url[len('http://') :]
        return url
    return path
