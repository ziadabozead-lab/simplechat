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
from .models import Message, PhoneNumber, UserPresence, UserProfile, ONLINE_WINDOW_SECONDS

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
    messages = Message.objects.all().order_by("created_at")
    members = list(User.objects.filter(is_active=True).order_by("username"))
    _attach_online_status(members)
    return render(request, "chat/room.html", {"messages": messages, "members": members})


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
    }
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
    elif m.message_type == Message.STICKER and m.sticker:
        data["sticker_url"] = static(f"chat/stickers/{m.sticker}")
    else:
        data["text"] = m.text
    return data


@login_required
def get_messages(request):
    after_id = request.GET.get("after", 0)
    messages = Message.objects.filter(id__gt=after_id).order_by("created_at")
    data = [_serialize_message(m, request) for m in messages]
    return JsonResponse({"messages": data})


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