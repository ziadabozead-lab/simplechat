from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("", views.room, name="room"),
    path("signup/", views.signup, name="signup"),
    path("login/", auth_views.LoginView.as_view(template_name="chat/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("messages/", views.get_messages, name="get_messages"),
    path("members/", views.get_members, name="get_members"),
    path("send/", views.send_message, name="send_message"),
    path("send-voice/", views.send_voice, name="send_voice"),
]