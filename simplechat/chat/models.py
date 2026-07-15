from django.conf import settings
from django.db import models
from django.utils import timezone

# A user counts as "online" if their last_seen is within this window.
# Kept close to the 3s poll interval in room.js plus some slack so a
# person doesn't flicker offline between polls.
ONLINE_WINDOW_SECONDS = 12


def voice_message_path(instance, filename):
    return f"voice_messages/{instance.sender}/{filename}"


def video_message_path(instance, filename):
    return f"video_messages/{instance.sender}/{filename}"


def photo_message_path(instance, filename):
    return f"photo_messages/{instance.sender}/{filename}"


def document_message_path(instance, filename):
    return f"document_messages/{instance.sender}/{filename}"


class Message(models.Model):
    TEXT = "text"
    AUDIO = "audio"
    VIDEO = "video"
    PHOTO = "photo"
    DOCUMENT = "document"
    STICKER = "sticker"
    MESSAGE_TYPES = [
        (TEXT, "Text"),
        (AUDIO, "Audio"),
        (VIDEO, "Video"),
        (PHOTO, "Photo"),
        (DOCUMENT, "Document"),
        (STICKER, "Sticker"),
    ]

    sender = models.CharField(max_length=150)
    text = models.TextField(blank=True)
    audio = models.FileField(upload_to=voice_message_path, blank=True, null=True)
    video = models.FileField(upload_to=video_message_path, blank=True, null=True)
    photo = models.FileField(upload_to=photo_message_path, blank=True, null=True)
    document = models.FileField(upload_to=document_message_path, blank=True, null=True)
    # The stored document filename is a random UUID (see views.send_document)
    # so it can't collide; this keeps the name the person actually gave the
    # file, so the chat can still show/download it as "report.pdf" etc.
    document_name = models.CharField(max_length=255, blank=True)
    # For stickers we just store which file in static/chat/stickers/ was
    # sent (e.g. "thumbs_up.svg") - stickers are a fixed, pre-approved set
    # bundled with the app, not user uploads, so there's nothing to store
    # except which one was picked.
    sticker = models.CharField(max_length=64, blank=True)
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPES, default=TEXT)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.message_type == self.AUDIO:
            return f"{self.sender}: [voice message]"
        if self.message_type == self.VIDEO:
            return f"{self.sender}: [video message]"
        if self.message_type == self.PHOTO:
            return f"{self.sender}: [photo]"
        if self.message_type == self.DOCUMENT:
            return f"{self.sender}: [document: {self.document_name}]"
        if self.message_type == self.STICKER:
            return f"{self.sender}: [sticker: {self.sticker}]"
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


class UserProfile(models.Model):
    """
    Created for every new signup. Holds the admin approval status, since
    User.is_active is already used for banning (see BanFilter in admin.py)
    and we don't want a rejected/pending signup to look identical to a
    banned account in the admin UI.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPROVAL_STATUSES = [
        (PENDING, "Pending"),
        (APPROVED, "Approved"),
        (REJECTED, "Rejected"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    approval_status = models.CharField(max_length=10, choices=APPROVAL_STATUSES, default=PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} ({self.approval_status})"


class PhoneNumber(models.Model):
    """A user can register more than one phone number, from any country."""

    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="phone_numbers")
    country_iso2 = models.CharField(max_length=2)
    dial_code = models.CharField(max_length=4)
    number = models.CharField(max_length=20)

    def __str__(self):
        return f"+{self.dial_code} {self.number}"

    def formatted(self):
        return f"+{self.dial_code} {self.number}"