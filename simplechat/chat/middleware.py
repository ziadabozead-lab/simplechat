from django.utils import timezone

from .models import UserPresence


class UpdatePresenceMiddleware:
    """
    Touches UserPresence.last_seen for the logged-in user on every request.
    Since the room page polls /messages/ every 3s while it's open, this is
    enough to keep someone's presence "fresh" without any extra heartbeat
    endpoint - the existing polling IS the heartbeat.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated:
            UserPresence.objects.update_or_create(
                user=request.user, defaults={"last_seen": timezone.now()}
            )
        return response