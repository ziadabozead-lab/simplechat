import logging

from django.conf import settings
from django.db import OperationalError
from django.utils import timezone

from .models import UserPresence

logger = logging.getLogger(__name__)

# Don't burn a DB write on every single asset request. Loading one page
# with a few voice/video messages fires many concurrent /media/ range
# requests, and static assets (CSS/JS/stickers) fire even more - none of
# that needs to touch presence, and doing it anyway is what was causing
# SQLite "database is locked" errors under concurrent load.
_SKIP_PREFIXES = (settings.MEDIA_URL, settings.STATIC_URL)


class UpdatePresenceMiddleware:
    """
    Touches UserPresence.last_seen for the logged-in user on requests that
    actually represent activity (page loads, polling, sending messages) -
    not on every asset request. Since the room page polls /messages/
    every 3s while it's open, that alone is enough to keep someone's
    presence "fresh" without a dedicated heartbeat endpoint.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.user.is_authenticated and not request.path.startswith(_SKIP_PREFIXES):
            try:
                UserPresence.objects.update_or_create(
                    user=request.user, defaults={"last_seen": timezone.now()}
                )
            except OperationalError:
                # SQLite under concurrent writes can still occasionally
                # raise "database is locked" even after cutting out most
                # of the request volume above. Presence being a few
                # seconds stale is harmless, so don't turn that into a
                # 500 for the person's actual request.
                logger.warning("UserPresence update skipped: database was locked.")

        return response