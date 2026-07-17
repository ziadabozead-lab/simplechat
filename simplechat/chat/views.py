from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.templatetags.static import static
from django.utils import timezone
from django.views.decorators.http import require_POST

from .countries import COUNTRY_CHOICES, DIAL_CODE_BY_ISO2
from .forms import SignupForm
from .models import (
    CustomSticker,
    Message,
    MessageReceipt,
    PhoneNumber,
    PollOption,
    PollVote,
    UserPresence,
    UserProfile,
    ONLINE_WINDOW_SECONDS,
)

# Only these audio container types are accepted from the recorder.
# (MediaRecorder in browsers produces webm/ogg containers with an
# opus-encoded stream; mp4/m4a covers Safari.)
ALLOWED_AUDIO_TYPES = {
    "audio/webm": "webm",
    "video/webm": "webm",  # some browsers label audio-only webm blobs this way
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
}
AUDIO_TYPE_BY_EXT = {"webm": "audio/webm", "ogg": "audio/ogg", "m4a": "audio/mp4", "mp3": "audio/mpeg"}

# Video messages are sent as a regular file (camera-capture or existing
# clip), not recorded in-browser, so the container list is simpler.
ALLOWED_VIDEO_TYPES = {
    "video/webm": "webm",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
}
VIDEO_TYPE_BY_EXT = {"webm": "video/webm", "mp4": "video/mp4", "mov": "video/quicktime"}

# Fixed, pre-approved sticker set bundled with the app at
# chat/static/chat/stickers/. Only these filenames may ever be sent -
# stickers aren't user uploads, so anything not in this list is rejected.
ALLOWED_STICKERS = {
    "thumbs_up.svg",
    "heart.svg",
    "laugh.svg",
    "fire.svg",
    "clap.svg",
    "ok_hand.svg",
}

# Images people upload to create their own stickers.
ALLOWED_STICKER_IMAGE_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}

ALLOWED_PHOTO_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
PHOTO_TYPE_BY_EXT = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}

# Documents are validated by extension rather than content-type, since
# browsers often send a generic "application/octet-stream" for these and
# a content-type whitelist would reject perfectly normal files.
ALLOWED_DOCUMENT_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv", "zip", "rar"}


def signup(request):
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            # New accounts wait for an admin to approve/reject them in the
            # admin panel before they can log in at all.
            user.is_active = False
            user.save()

            profile = UserProfile.objects.create(user=user, approval_status=UserProfile.PENDING)

            countries = request.POST.getlist("phone_country")
            numbers = request.POST.getlist("phone_number")
            for iso2, number in zip(countries, numbers):
                number = number.strip()
                if not number:
                    continue
                PhoneNumber.objects.create(
                    profile=profile,
                    country_iso2=iso2,
                    dial_code=DIAL_CODE_BY_ISO2.get(iso2, ""),
                    number=number,
                )

            return redirect("signup_pending")
    else:
        form = SignupForm()
    return render(request, "chat/signup.html", {"form": form, "countries": COUNTRY_CHOICES})


def signup_pending(request):
    return render(request, "chat/signup_pending.html")


@login_required
def room(request):
    messages = list(Message.objects.all().order_by("created_at"))
    _mark_delivered(messages, request.user)
    _attach_poll_data(messages, request.user)
    members = list(User.objects.filter(is_active=True).order_by("username"))
    _attach_online_status(members)
    last_id = messages[-1].id if messages else 0
    custom_stickers = list(CustomSticker.objects.all().order_by("-created_at")[:60])
    return render(request, "chat/room.html", {
        "messages": messages,
        "members": members,
        "last_id": last_id,
        "custom_stickers": custom_stickers,
    })


def _attach_poll_data(messages, user):
    """Mutates each poll Message in `messages`, attaching total_votes,
    my_vote_option_id, and per-option vote_count/pct - so the template
    can render current results without a separate JS fetch on load."""
    for m in messages:
        if m.message_type != Message.POLL:
            continue
        options = list(m.poll_options.all())
        total = sum(o.votes.count() for o in options)
        m.total_votes = total
        m.my_vote_option_id = (
            PollVote.objects.filter(message=m, user=user).values_list("option_id", flat=True).first()
        )
        for o in options:
            o.vote_count = o.votes.count()
            o.pct = round(100 * o.vote_count / total) if total else 0
        # So the template's `{% for opt in m.poll_options.all %}` reuses
        # these same (mutated) objects instead of silently re-querying
        # fresh ones without vote_count/pct set.
        m._prefetched_objects_cache = {"poll_options": options}


def _attach_online_status(members):
    """Mutates each User in `members`, setting .is_online from UserPresence."""
    cutoff = timezone.now() - timedelta(seconds=ONLINE_WINDOW_SECONDS)
    online_user_ids = set(
        UserPresence.objects.filter(user__in=members, last_seen__gte=cutoff).values_list("user_id", flat=True)
    )
    for m in members:
        m.is_online = m.id in online_user_ids


@login_required
def get_members(request):
    members = list(User.objects.filter(is_active=True).order_by("username"))
    _attach_online_status(members)
    data = [{"username": m.username, "is_online": m.is_online} for m in members]
    return JsonResponse({"members": data})


def _serialize_message(m, request):
    data = {
        "id": m.id,
        "sender": m.sender,
        "type": m.message_type,
        "time": m.created_at.strftime("%H:%M"),
        "is_me": m.sender == request.user.username,
        "is_deleted": m.is_deleted,
        # Own messages can always be deleted by their sender; staff can
        # delete anyone's, matching "the admin can delete all of that".
        "can_delete": (not m.is_deleted) and (m.sender == request.user.username or request.user.is_staff),
        # Only the sender (or staff, for moderation) can see the
        # delivered/read/played breakdown for a message - other members
        # get can_view_info=false and the frontend just won't offer it.
        "can_view_info": m.sender == request.user.username or request.user.is_staff,
    }

    if m.is_deleted:
        # WhatsApp-style tombstone: no media/text survives, just the fact
        # that something was deleted.
        data["text"] = "This message was deleted"
        return data

    if m.message_type == Message.AUDIO and m.audio:
        data["audio_url"] = m.audio.url
        data["audio_type"] = AUDIO_TYPE_BY_EXT.get(m.audio.name.rsplit(".", 1)[-1].lower(), "audio/webm")
    elif m.message_type == Message.VIDEO and m.video:
        data["video_url"] = m.video.url
        data["video_type"] = VIDEO_TYPE_BY_EXT.get(m.video.name.rsplit(".", 1)[-1].lower(), "video/mp4")
    elif m.message_type == Message.PHOTO and m.photo:
        data["photo_url"] = m.photo.url
    elif m.message_type == Message.DOCUMENT and m.document:
        data["document_url"] = m.document.url
        data["document_name"] = m.document_name or m.document.name.rsplit("/", 1)[-1]
    elif m.message_type == Message.STICKER and m.custom_sticker_id:
        data["sticker_url"] = m.custom_sticker.image.url
    elif m.message_type == Message.STICKER and m.sticker:
        data["sticker_url"] = static(f"chat/stickers/{m.sticker}")
    elif m.message_type == Message.POLL:
        data["question"] = m.text
        options = list(m.poll_options.all())
        total_votes = sum(o.votes.count() for o in options)
        my_vote = PollVote.objects.filter(message=m, user=request.user).values_list("option_id", flat=True).first()
        data["poll"] = {
            "total_votes": total_votes,
            "voted_option_id": my_vote,
            "options": [
                {
                    "id": o.id,
                    "text": o.text,
                    "votes": o.votes.count(),
                    "percent": round(100 * o.votes.count() / total_votes) if total_votes else 0,
                }
                for o in options
            ],
        }
    else:
        data["text"] = m.text
    return data


@login_required
def get_messages(request):
    after_id = request.GET.get("after", 0)
    messages = list(Message.objects.filter(id__gt=after_id).order_by("created_at"))
    _mark_delivered(messages, request.user)
    data = [_serialize_message(m, request) for m in messages]
    return JsonResponse({"messages": data})


def _mark_delivered(messages, user):
    """First time any of these messages (not sent by `user`) reaches
    their client, stamp delivered_at - this is the "got the message
    sent" half of the read-receipt picture."""
    others_msgs = [m for m in messages if m.sender != user.username]
    if not others_msgs:
        return
    existing = set(
        MessageReceipt.objects.filter(message__in=others_msgs, user=user, delivered_at__isnull=False)
        .values_list("message_id", flat=True)
    )
    now = timezone.now()
    for m in others_msgs:
        if m.id in existing:
            continue
        MessageReceipt.objects.update_or_create(
            message=m, user=user, defaults={"delivered_at": now}
        )


@login_required
@require_POST
def send_message(request):
    text = request.POST.get("text", "").strip()
    if text:
        Message.objects.create(sender=request.user.username, text=text, message_type=Message.TEXT)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def send_voice(request):
    audio_file = request.FILES.get("audio")
    if not audio_file:
        return JsonResponse({"ok": False, "error": "No audio file received."}, status=400)

    if audio_file.size > settings.MAX_VOICE_MESSAGE_BYTES:
        return JsonResponse({"ok": False, "error": "Voice message is too long."}, status=400)

    content_type = (audio_file.content_type or "").split(";")[0].strip()
    ext = ALLOWED_AUDIO_TYPES.get(content_type)
    if not ext:
        return JsonResponse({"ok": False, "error": "Unsupported audio format."}, status=400)

    audio_file.name = f"{request.user.username}_{uuid4().hex}.{ext}"
    message = Message.objects.create(
        sender=request.user.username,
        message_type=Message.AUDIO,
        audio=audio_file,
    )
    return JsonResponse({"ok": True, "message": _serialize_message(message, request)})


@login_required
@require_POST
def send_video(request):
    video_file = request.FILES.get("video")
    if not video_file:
        return JsonResponse({"ok": False, "error": "No video file received."}, status=400)

    if video_file.size > settings.MAX_VIDEO_MESSAGE_BYTES:
        return JsonResponse({"ok": False, "error": "Video is too large."}, status=400)

    content_type = (video_file.content_type or "").split(";")[0].strip()
    ext = ALLOWED_VIDEO_TYPES.get(content_type)
    if not ext:
        return JsonResponse({"ok": False, "error": "Unsupported video format."}, status=400)

    video_file.name = f"{request.user.username}_{uuid4().hex}.{ext}"
    message = Message.objects.create(
        sender=request.user.username,
        message_type=Message.VIDEO,
        video=video_file,
    )
    return JsonResponse({"ok": True, "message": _serialize_message(message, request)})


@login_required
@require_POST
def send_sticker(request):
    sticker = request.POST.get("sticker", "").strip()
    custom_sticker_id = request.POST.get("custom_sticker_id", "").strip()

    if custom_sticker_id:
        try:
            custom_sticker = CustomSticker.objects.get(id=custom_sticker_id)
        except (CustomSticker.DoesNotExist, ValueError):
            return JsonResponse({"ok": False, "error": "Unknown sticker."}, status=400)
        message = Message.objects.create(
            sender=request.user.username,
            message_type=Message.STICKER,
            custom_sticker=custom_sticker,
        )
    else:
        if sticker not in ALLOWED_STICKERS:
            return JsonResponse({"ok": False, "error": "Unknown sticker."}, status=400)
        message = Message.objects.create(
            sender=request.user.username,
            message_type=Message.STICKER,
            sticker=sticker,
        )
    return JsonResponse({"ok": True, "message": _serialize_message(message, request)})


@login_required
@require_POST
def create_sticker(request):
    """
    Turn an uploaded image into a new sticker anyone in the room can
    then pick from the sticker picker - not a message by itself, just
    adds to the shared sticker set (see send_sticker for actually
    sending one).
    """
    image_file = request.FILES.get("image")
    if not image_file:
        return JsonResponse({"ok": False, "error": "No image received."}, status=400)

    if image_file.size > settings.MAX_STICKER_IMAGE_BYTES:
        return JsonResponse({"ok": False, "error": "Image is too large."}, status=400)

    content_type = (image_file.content_type or "").split(";")[0].strip()
    ext = ALLOWED_STICKER_IMAGE_TYPES.get(content_type)
    if not ext:
        return JsonResponse({"ok": False, "error": "Please use a PNG, JPG, or WEBP image."}, status=400)

    image_file.name = f"{request.user.username}_{uuid4().hex}.{ext}"
    sticker = CustomSticker.objects.create(created_by=request.user.username, image=image_file)
    return JsonResponse({"ok": True, "sticker": {"id": sticker.id, "url": sticker.image.url}})


@login_required
@require_POST
def send_photo(request):
    photo_file = request.FILES.get("photo")
    if not photo_file:
        return JsonResponse({"ok": False, "error": "No photo received."}, status=400)

    if photo_file.size > settings.MAX_PHOTO_MESSAGE_BYTES:
        return JsonResponse({"ok": False, "error": "Photo is too large."}, status=400)

    content_type = (photo_file.content_type or "").split(";")[0].strip()
    ext = ALLOWED_PHOTO_TYPES.get(content_type)
    if not ext:
        return JsonResponse({"ok": False, "error": "Unsupported photo format."}, status=400)

    photo_file.name = f"{request.user.username}_{uuid4().hex}.{ext}"
    message = Message.objects.create(
        sender=request.user.username,
        message_type=Message.PHOTO,
        photo=photo_file,
    )
    return JsonResponse({"ok": True, "message": _serialize_message(message, request)})


@login_required
@require_POST
def send_document(request):
    doc_file = request.FILES.get("document")
    if not doc_file:
        return JsonResponse({"ok": False, "error": "No file received."}, status=400)

    if doc_file.size > settings.MAX_DOCUMENT_MESSAGE_BYTES:
        return JsonResponse({"ok": False, "error": "File is too large."}, status=400)

    original_name = doc_file.name
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
        return JsonResponse({"ok": False, "error": "That file type isn't allowed."}, status=400)

    doc_file.name = f"{request.user.username}_{uuid4().hex}.{ext}"
    message = Message.objects.create(
        sender=request.user.username,
        message_type=Message.DOCUMENT,
        document=doc_file,
        document_name=original_name[:255],
    )
    return JsonResponse({"ok": True, "message": _serialize_message(message, request)})


@login_required
@require_POST
def delete_message(request, message_id):
    """
    Soft-deletes a message: senders can delete their own, staff/admins
    can delete anyone's (matches "the admin can delete all of that").
    The row stays (so receipts/votes aren't orphaned) but the actual
    content is wiped and every client will show a tombstone instead.
    """
    try:
        message = Message.objects.get(id=message_id)
    except Message.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Message not found."}, status=404)

    if message.sender != request.user.username and not request.user.is_staff:
        return JsonResponse({"ok": False, "error": "You can't delete this message."}, status=403)

    if message.is_deleted:
        return JsonResponse({"ok": True})  # already gone, nothing to do

    # Actually remove the stored files so a "deleted" message doesn't
    # keep the media sitting in MEDIA_ROOT forever.
    for field_name in ("audio", "video", "photo", "document"):
        field_file = getattr(message, field_name)
        if field_file:
            field_file.delete(save=False)

    message.is_deleted = True
    message.text = ""
    message.sticker = ""
    message.document_name = ""
    message.save()
    return JsonResponse({"ok": True, "id": message.id})


@login_required
@require_POST
def mark_read(request, message_id):
    """Called by room.js (IntersectionObserver) when a message someone
    else sent actually scrolls into view in this user's chat box."""
    try:
        message = Message.objects.get(id=message_id)
    except Message.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Message not found."}, status=404)

    if message.sender == request.user.username:
        return JsonResponse({"ok": True})  # no self-receipts

    MessageReceipt.objects.update_or_create(
        message=message, user=request.user,
        defaults={"read_at": timezone.now(), "delivered_at": timezone.now()},
    )
    return JsonResponse({"ok": True})


@login_required
@require_POST
def mark_played(request, message_id):
    """Called on the <audio>/<video> element's 'play' event."""
    try:
        message = Message.objects.get(id=message_id, message_type__in=[Message.AUDIO, Message.VIDEO])
    except Message.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Message not found."}, status=404)

    if message.sender == request.user.username:
        return JsonResponse({"ok": True})

    MessageReceipt.objects.update_or_create(
        message=message, user=request.user,
        defaults={"played_at": timezone.now(), "read_at": timezone.now(), "delivered_at": timezone.now()},
    )
    return JsonResponse({"ok": True})


@login_required
def message_info(request, message_id):
    """
    WhatsApp-style "message info" panel: for every other active member,
    whether the message was delivered / read / (if audio or video)
    played. Only the sender or an admin gets to see this - matches "who
    got the message sent and who didn't... just like the whatsapp style".
    """
    try:
        message = Message.objects.get(id=message_id)
    except Message.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Message not found."}, status=404)

    if message.sender != request.user.username and not request.user.is_staff:
        return JsonResponse({"ok": False, "error": "Not allowed."}, status=403)

    show_played = message.message_type in (Message.AUDIO, Message.VIDEO)

    others = User.objects.filter(is_active=True).exclude(username=message.sender).order_by("username")
    receipts_by_user = {r.user_id: r for r in MessageReceipt.objects.filter(message=message, user__in=others)}

    members_data = []
    for u in others:
        r = receipts_by_user.get(u.id)
        members_data.append({
            "username": u.username,
            "delivered": bool(r and r.delivered_at),
            "read": bool(r and r.read_at),
            "played": bool(r and r.played_at) if show_played else None,
        })

    return JsonResponse({
        "ok": True,
        "show_played": show_played,
        "members": members_data,
    })


@login_required
@require_POST
def send_poll(request):
    question = request.POST.get("question", "").strip()
    options = [o.strip() for o in request.POST.getlist("options") if o.strip()]

    if not question:
        return JsonResponse({"ok": False, "error": "A poll needs a question."}, status=400)
    if len(options) < 2:
        return JsonResponse({"ok": False, "error": "A poll needs at least 2 options."}, status=400)
    if len(options) > 10:
        return JsonResponse({"ok": False, "error": "A poll can have at most 10 options."}, status=400)

    message = Message.objects.create(sender=request.user.username, text=question, message_type=Message.POLL)
    for i, option_text in enumerate(options):
        PollOption.objects.create(message=message, text=option_text[:100], order=i)

    return JsonResponse({"ok": True, "message": _serialize_message(message, request)})


@login_required
@require_POST
def vote_poll(request, message_id):
    try:
        message = Message.objects.get(id=message_id, message_type=Message.POLL)
    except Message.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Poll not found."}, status=404)

    try:
        option = PollOption.objects.get(id=request.POST.get("option_id"), message=message)
    except (PollOption.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "Invalid option."}, status=400)

    # One vote per user per poll; voting again just moves your vote.
    PollVote.objects.update_or_create(
        message=message, user=request.user, defaults={"option": option}
    )
    return JsonResponse({"ok": True, "message": _serialize_message(message, request)})