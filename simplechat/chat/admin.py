from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
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
    list_display = ("username", "email", "is_active", "is_staff", "date_joined")
    list_filter = (BanFilter, "is_staff")
    actions = ["ban_users", "unban_users"]

    @admin.action(description="Ban selected users")
    def ban_users(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description="Unban selected users")
    def unban_users(self, request, queryset):
        queryset.update(is_active=True)


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)