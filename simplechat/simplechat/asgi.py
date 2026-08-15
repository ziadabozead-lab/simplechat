"""
ASGI config for simplechat project.

Routes plain HTTP to Django as normal, and WebSocket connections
(used for live call signaling) to the Channels consumer.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'simplechat.settings')

# get_asgi_application() must be called before importing anything that
# touches models, so the Django app registry is populated first.
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

import chat.routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(chat.routing.websocket_urlpatterns)
    ),
})