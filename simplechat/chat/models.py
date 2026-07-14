from django.conf import settings
from django.db import models
from django.utils import timezone

# A user counts as "online" if their last_seen is within this window.
# Kept close to the 3s poll interval in room.js plus some slack so a
# person doesn't flicker offline between polls.
ONLINE_WINDOW_SECONDS = 12


def voice_message_path(instance, filename):
    return f"voice_messages/{instance.sender}/{filename}"


class Message(models.Model):
    TEXT = "text"
    AUDIO = "audio"
    MESSAGE_TYPES = [
        (TEXT, "Text"),
        (AUDIO, "Audio"),
    ]

    sender = models.CharField(max_length=150)
    text = models.TextField(blank=True)
    audio = models.FileField(upload_to=voice_message_path, blank=True, null=True)
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPES, default=TEXT)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.message_type == self.AUDIO:
            return f"{self.sender}: [voice message]"
        return f"{self.sender}: {self.text[:30]}"


class UserPresence(models.Model):
    """
    One row per user, updated on every authenticated request (see
    chat/middleware.py). Whether someone shows as "online" is derived
    from how recently this timestamp was touched - there's no separate
    login/logout tracking, so closing the tab quietly just lets the
    timestamp go stale and they fall back to offline within
    ONLINE_WINDOW_SECONDS.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="presence")
    last_seen = models.DateTimeField(default=timezone.now)

    def is_online(self):
        return (timezone.now() - self.last_seen).total_seconds() < ONLINE_WINDOW_SECONDS

    def __str__(self):
        return f"{self.user.username} presence"