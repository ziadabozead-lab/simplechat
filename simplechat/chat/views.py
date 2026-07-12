from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from .models import Message


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
    return render(request, "chat/room.html", {"messages": messages})


@login_required
def get_messages(request):
    after_id = request.GET.get("after", 0)
    messages = Message.objects.filter(id__gt=after_id).order_by("created_at")
    data = [
        {
            "id": m.id,
            "sender": m.sender,
            "text": m.text,
            "time": m.created_at.strftime("%H:%M"),
            "is_me": m.sender == request.user.username,
        }
        for m in messages
    ]
    return JsonResponse({"messages": data})


@login_required
@require_POST
def send_message(request):
    text = request.POST.get("text", "").strip()
    if text:
        Message.objects.create(sender=request.user.username, text=text)
    return JsonResponse({"ok": True})
