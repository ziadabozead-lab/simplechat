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
    # The stored document filename is a random UUID (see views.send_document)
    # so it can't collide; this keeps the name the person actually gave the
    # file, so the chat can still show/download it as "report.pdf" etc.
    document_name = models.CharField(max_length=255, blank=True)
    # For stickers we either reference a file in static/chat/stickers/
    # (the fixed, pre-approved built-in set - e.g. "thumbs_up.svg") or,
    # if custom_sticker is set below, one a user created themselves.
    sticker = models.CharField(max_length=64, blank=True)
    custom_sticker = models.ForeignKey(
        "CustomSticker", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages"
    )
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPES, default=TEXT)
    # WhatsApp-style soft delete: the row (and its receipts/votes) stays,
    # but the actual content is wiped and the chat shows a tombstone
    # instead. See views.delete_message.
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
    """
    Per-(message, user) delivery/read/played tracking, powering the
    WhatsApp-style "info" panel on long-press. There's one group room
    here rather than 1-to-1 conversations, so "delivered"/"read" is
    tracked against every other active member, not a single recipient.

    - delivered_at: set the first time this message shows up in that
      user's /messages/ poll response (see views.get_messages).
    - read_at: set when the message actually scrolls into view in their
      chat box (IntersectionObserver in room.js calls /mark-read/).
    - played_at: audio messages only, set when they actually press play
      (room.js calls /mark-played/ on the <audio> 'play' event).
    """

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
    """
    One vote per user per poll (single-choice, like a basic WhatsApp
    poll). `message` is denormalized alongside `option` purely so
    unique_together can enforce "one vote per user per poll" directly,
    since Django can't express uniqueness across a FK's own FK.
    """

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="poll_votes")
    option = models.ForeignKey(PollOption, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="poll_votes")
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user")


class CustomSticker(models.Model):
    """
    A sticker someone made themselves by uploading an image (see
    views.create_sticker). Shared with the whole room, same as the
    built-in set - once created, anyone can pick it from the sticker
    picker, not just its creator.
    """

    created_by = models.CharField(max_length=150)
    image = models.FileField(upload_to=custom_sticker_path)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"custom sticker by {self.created_by}"


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


class Country(models.Model):
    """
    Country dial-code reference data for the signup phone number fields.
    Used to live as a hardcoded list in chat/countries.py; now a real
    table so it can be managed (added to / corrected / reordered) from
    the admin panel without a code deploy. Seeded with the same data the
    old countries.py shipped with - see the data migration that created
    this table.
    """

    iso2 = models.CharField("ISO code", max_length=2, unique=True)
    name = models.CharField(max_length=100)
    dial_code = models.CharField("Dial code", max_length=4, help_text="Without the leading '+'.")

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "countries"

    def __str__(self):
        return f"{self.name} (+{self.dial_code})"


class PhoneNumber(models.Model):
    """A user can register more than one phone number, from any country."""

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