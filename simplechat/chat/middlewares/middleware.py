import logging
from django.conf import settings
from django.db import OperationalError
from django.utils import timezone
from chat.models import UserPresence

logger = logging.getLogger(__name__)
_SKIP_PREFIXES = (settings.MEDIA_URL, settings.STATIC_URL)

class UpdatePresenceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated and not request.path.startswith(_SKIP_PREFIXES):
            try:
                UserPresence.objects.update_or_create(user=request.user, defaults={"last_seen": timezone.now()})
            except OperationalError:
                logger.warning("UserPresence update skipped: database was locked.")
        return response