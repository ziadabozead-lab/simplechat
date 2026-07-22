from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from .models import Country, Message, PhoneNumber, UserProfile


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("name", "iso2", "dial_code")
    search_fields = ("name", "iso2", "dial_code")
    ordering = ("name",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("sender", "message_type", "text", "created_at")
    list_filter = ("sender", "message_type")
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

    list_display = ("username", "email", "is_active", "is_staff", "date_joined", "password_actions")
    list_filter = (BanFilter, "is_staff")

    # is_active is controlled exclusively through UserProfile.approval_status
    # (see UserProfileAdmin._apply_decision below). Editing it here directly
    # would desync the two: is_active would flip but approval_status would
    # stay "pending" forever. Read-only display only; use the UserProfile
    # admin's Approve/Reject actions to change it.
    readonly_fields = UserAdmin.readonly_fields + ("is_active",)

    @admin.display(description="Password")
    def password_actions(self, obj):
        url = reverse("admin:auth_user_password_change", args=[obj.pk])
        return format_html('<a href="{}">Set new password</a>', url)


class PhoneNumberInline(admin.TabularInline):
    model = PhoneNumber
    extra = 0
    can_delete = False
    readonly_fields = ("country", "number")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):

    list_display = ("user", "approval_status", "requested_at", "decided_at", "phone_summary")
    list_filter = ("approval_status",)
    search_fields = ("user__username",)
    ordering = ("-requested_at",)
    inlines = [PhoneNumberInline]
    actions = ["approve_signups", "reject_signups"]

    @admin.display(description="Phone numbers")
    def phone_summary(self, obj):
        numbers = [p.formatted() for p in obj.phone_numbers.all()]
        return ", ".join(numbers) if numbers else "-"

    def _apply_decision(self, profile):
        """Sync User.is_active + decided_at to match profile.approval_status."""
        profile.decided_at = timezone.now()
        profile.user.is_active = (profile.approval_status == UserProfile.APPROVED)
        profile.user.save()

    def save_model(self, request, obj, form, change):
        status_changed = "approval_status" in form.changed_data
        super().save_model(request, obj, form, change)
        if status_changed and obj.approval_status in (UserProfile.APPROVED, UserProfile.REJECTED):
            self._apply_decision(obj)
            obj.save()

    @admin.action(description="Approve selected signups (agree)")
    def approve_signups(self, request, queryset):
        for profile in queryset:
            profile.approval_status = UserProfile.APPROVED
            self._apply_decision(profile)
            profile.save()

    @admin.action(description="Reject selected signups (disagree)")
    def reject_signups(self, request, queryset):
        for profile in queryset:
            profile.approval_status = UserProfile.REJECTED
            self._apply_decision(profile)
            profile.save()


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)