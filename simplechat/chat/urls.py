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
    path("create-sticker/", views.create_sticker, name="create_sticker"),
    path("messages/<int:message_id>/delete/", views.delete_message, name="delete_message"),
    path("messages/mark-read-bulk/", views.mark_read_bulk, name="mark_read_bulk"),
    path("messages/<int:message_id>/mark-read/", views.mark_read, name="mark_read"),
    path("messages/<int:message_id>/mark-played/", views.mark_played, name="mark_played"),
    path("messages/<int:message_id>/info/", views.message_info, name="message_info"),
    path("send-poll/", views.send_poll, name="send_poll"),
    path("messages/<int:message_id>/vote/", views.vote_poll, name="vote_poll"),
    path("call/status/", views.call_status, name="call_status"),
    path("call/", views.call_room, name="call_room"),
]