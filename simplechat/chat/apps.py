from django.apps import AppConfig
from .signals import set_sqlite_pragma


class ChatConfig(AppConfig):
    name = 'chat'
