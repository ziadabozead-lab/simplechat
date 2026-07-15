from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .forms import PendingAwareAuthenticationForm

urlpatterns = [
    path("", views.room, name="room"),
    path("signup/", views.signup, name="signup"),
    path("signup/pending/", views.signup_pending, name="signup_pending"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="chat/login.html",
            authentication_form=PendingAwareAuthenticationForm,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("messages/", views.get_messages, name="get_messages"),
    path("members/", views.get_members, name="get_members"),
    path("send/", views.send_message, name="send_message"),
    path("send-voice/", views.send_voice, name="send_voice"),
    path("send-video/", views.send_video, name="send_video"),
    path("send-photo/", views.send_photo, name="send_photo"),
    path("send-document/", views.send_document, name="send_document"),
    path("send-sticker/", views.send_sticker, name="send_sticker"),
]