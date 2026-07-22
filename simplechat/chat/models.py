from django.conf import settings
from django.db import models
from django.utils import timezone

ONLINE_WINDOW_SECONDS = 12


def voice_message_path(instance, filename):
    return f"voice_messages/{instance.sender}/{filename}"


def video_message_path(instance, filename):
    return f"video_messages/{instance.sender}/{filename}"


def photo_message_path(instance, filename):
    return f"photo_messages/{instance.sender}/{filename}"


def document_message_path(instance, filename):
    return f"document_messages/{instance.sender}/{filename}"


def custom_sticker_path(instance, filename):
    return f"custom_stickers/{instance.created_by}/{filename}"


class Message(models.Model):
    TEXT = "text"
    AUDIO = "audio"
    VIDEO = "video"
    PHOTO = "photo"
    DOCUMENT = "document"
    STICKER = "sticker"
    POLL = "poll"
    MESSAGE_TYPES = [
        (TEXT, "Text"),
        (AUDIO, "Audio"),
        (VIDEO, "Video"),
        (PHOTO, "Photo"),
        (DOCUMENT, "Document"),
        (STICKER, "Sticker"),
        (POLL, "Poll"),
    ]

    sender = models.CharField(max_length=150)
    text = models.TextField(blank=True)
    audio = models.FileField(upload_to=voice_message_path, blank=True, null=True)
    video = models.FileField(upload_to=video_message_path, blank=True, null=True)
    photo = models.FileField(upload_to=photo_message_path, blank=True, null=True)
    document = models.FileField(upload_to=document_message_path, blank=True, null=True)
    document_name = models.CharField(max_length=255, blank=True)
    sticker = models.CharField(max_length=64, blank=True)
    custom_sticker = models.ForeignKey("CustomSticker", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages")
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPES, default=TEXT)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.is_deleted:
            return f"{self.sender}: [deleted]"
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
        if self.message_type == self.POLL:
            return f"{self.sender}: [poll: {self.text[:30]}]"
        return f"{self.sender}: {self.text[:30]}"


class MessageReceipt(models.Model):

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="receipts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="message_receipts")
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    played_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("message", "user")

    def __str__(self):
        return f"receipt: msg {self.message_id} / {self.user.username}"


class PollOption(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="poll_options")
    text = models.CharField(max_length=100)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.text


class PollVote(models.Model):

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="poll_votes")
    option = models.ForeignKey(PollOption, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="poll_votes")
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user")


class CustomSticker(models.Model):

    created_by = models.CharField(max_length=150)
    image = models.FileField(upload_to=custom_sticker_path)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"custom sticker by {self.created_by}"


class UserPresence(models.Model):

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="presence")
    last_seen = models.DateTimeField(default=timezone.now)

    def is_online(self):
        return (timezone.now() - self.last_seen).total_seconds() < ONLINE_WINDOW_SECONDS

    def __str__(self):
        return f"{self.user.username} presence"


class UserProfile(models.Model):

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


class Country(models.Model):

    iso2 = models.CharField("ISO code", max_length=2, unique=True)
    name = models.CharField(max_length=100)
    dial_code = models.CharField("Dial code", max_length=4, help_text="Without the leading '+'.")

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "countries"

    def __str__(self):
        return f"{self.name} (+{self.dial_code})"


class PhoneNumber(models.Model):

    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="phone_numbers")
    country = models.ForeignKey(Country, on_delete=models.PROTECT, related_name="phone_numbers", null=True, blank=True)
    number = models.CharField(max_length=20)

    def __str__(self):
        if self.country:
            return f"+{self.country.dial_code} {self.number}"
        return self.number

    def formatted(self):
        if self.country:
            return f"+{self.country.dial_code} {self.number}"
        return self.number