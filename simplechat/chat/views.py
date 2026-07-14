from datetime import timedelta
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from uuid import uuid4
from .models import Message, UserPresence, ONLINE_WINDOW_SECONDS

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


def signup(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("room")
    else:
        form = UserCreationForm()
    return render(request, "chat/signup.html", {"form": form})


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