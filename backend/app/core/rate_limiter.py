"""
Rate limiting configuration using SlowAPI (backed by Redis).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _get_identifier(request):
    """Use user ID if authenticated, fall back to IP."""
    user = getattr(request.state, "user", None)
    if user:
        return f"user:{user.id}"
    return get_remote_address(request)


limiter = Limiter(key_func=_get_identifier)

# Shorthand rate limit strings
AUTH_RATE = f"{settings.RATE_LIMIT_AUTH}/minute"
ANON_RATE = f"{settings.RATE_LIMIT_ANON}/minute"
UPLOAD_RATE = "10/minute"
