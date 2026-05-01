from channels.middleware import BaseMiddleware
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken, TokenError
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
import jwt
from urllib.parse import parse_qs
import re


@database_sync_to_async
def get_user_from_jwt(token_key):
    """
    Resolve user from JWT for WebSockets. Never raise: invalid/expired token or missing user
    in DB → AnonymousUser (consumer closes with 4001 / 4003 instead of HTTP 500 on handshake).
    """
    try:
        jwt_auth = JWTAuthentication()
        validated_token = jwt_auth.get_validated_token(token_key)
        user = jwt_auth.get_user(validated_token)
        return user
    except AuthenticationFailed:
        # e.g. user_id in token but CustomUser row deleted / wrong DB / stale export
        return AnonymousUser()
    except (InvalidToken, TokenError):
        return AnonymousUser()
    except jwt.ExpiredSignatureError:
        return AnonymousUser()
    except jwt.InvalidTokenError:
        return AnonymousUser()


class TokenAuthMiddleware(BaseMiddleware):
    def __init__(self, inner):
        super().__init__(inner)

    async def __call__(self, scope, receive, send):
        query_string = parse_qs(scope["query_string"].decode())
        token_key = query_string.get("token", [None])[0]
        if not token_key:
            # Support legacy clients that put token in the URL path (URLRouter kwargs are not
            # available here because this middleware wraps URLRouter).
            path = (scope.get("path") or "").strip()
            # /ws/sos/master/token=<jwt>
            m = re.search(r"/ws/sos/master/token=([^/]+)$", path)
            if m:
                token_key = m.group(1)
            else:
                # /ws/sos/master/<jwt>
                m2 = re.search(r"/ws/sos/master/([^/]+)$", path)
                if m2:
                    token_key = m2.group(1)
        scope["user"] = await get_user_from_jwt(token_key) if token_key else AnonymousUser()
        return await super().__call__(scope, receive, send)
