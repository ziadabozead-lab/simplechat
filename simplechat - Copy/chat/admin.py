from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils.html import format_html
from .models import Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("sender", "text", "created_at")
    list_filter = ("sender",)
    search_fields = ("sender", "text")
    ordering = ("-created_at",)


class BanFilter(admin.SimpleListFilter):
    title = "ban status"
    parameter_name = "banned"

    def lookups(self, request, model_admin):
        return (("yes", "Banned"), ("no", "Active"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(is_active=False)
        if self.value() == "no":
            return queryset.filter(is_active=True)
        return queryset


class CustomUserAdmin(UserAdmin):
    # NOTE on passwords:
    # Django never stores a user's real password anywhere, including here.
    # `User.password` only holds a one-way salted hash (e.g. "pbkdf2_sha256$...")
    # so there is no "original password" for the admin panel to reveal, for
    # any user. This isn't a Django limitation to work around — it's what
    # keeps every account safe if the database is ever leaked, and it's the
    # same reason "forgot password" flows everywhere make you *reset* your
    # password rather than emailing it back to you.
    #
    # What the admin panel CAN safely do (and already does via UserAdmin):
    # set a new password for any user. The "Change password" link below
    # takes you straight to that built-in page.
    list_display = ("username", "email", "is_active", "is_staff", "date_joined", "password_actions")
    list_filter = (BanFilter, "is_staff")
    actions = ["ban_users", "unban_users"]

    @admin.display(description="Password")
    def password_actions(self, obj):
        url = reverse("admin:auth_user_password_change", args=[obj.pk])
        return format_html('<a href="{}">Set new password</a>', url)

    @admin.action(description="Ban selected users")
    def ban_users(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description="Unban selected users")
    def unban_users(self, request, queryset):
        queryset.update(is_active=True)


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)