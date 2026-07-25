from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect

_SKIP_PREFIXES = (settings.MEDIA_URL, settings.STATIC_URL)


class EnforceActiveSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        if (request.user.is_authenticated and not request.user.is_active and not request.path.startswith(_SKIP_PREFIXES)):
            logout(request)
            return redirect("login")
        return self.get_response(request)