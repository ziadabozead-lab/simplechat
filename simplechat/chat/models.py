from django.db import models


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
