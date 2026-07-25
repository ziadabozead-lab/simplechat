import logging
from django.conf import settings
from django.http import HttpResponseForbidden
from chat.models import BlockedIP, UserPresence
from chat.utils import get_client_ip

logger = logging.getLogger(__name__)
_SKIP_PREFIXES = (settings.MEDIA_URL, settings.STATIC_URL)


class BlockBannedIPMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(_SKIP_PREFIXES):
            return self.get_response(request)

        ip = get_client_ip(request)
        if ip and BlockedIP.objects.filter(ip_address=ip).exists():
            return HttpResponseForbidden("Access denied.")

        return self.get_response(request)
