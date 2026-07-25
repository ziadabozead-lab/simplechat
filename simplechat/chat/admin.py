from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from .models import BlockedIP, Country, Message, PhoneNumber, UserProfile


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


class ProfileBanFilter(admin.SimpleListFilter):
    """
    Ban status as seen from the UserProfile table. A "banned" profile is
    one that was approved at signup but has since had access revoked
    directly (via ban_users below) - as opposed to a profile that's
    simply still pending or was rejected at signup time.
    """
    title = "ban status"
    parameter_name = "banned"

    def lookups(self, request, model_admin):
        return (("yes", "Banned"), ("no", "Not banned"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(approval_status=UserProfile.APPROVED, user__is_active=False)
        if self.value() == "no":
            return queryset.exclude(approval_status=UserProfile.APPROVED, user__is_active=False)
        return queryset


class CustomUserAdmin(UserAdmin):

    list_display = ("username", "email", "is_active", "is_staff", "date_joined", "password_actions")
    list_filter = (BanFilter, "is_staff")

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

    list_display = ("user", "account_status", "signup_ip", "requested_at", "decided_at", "phone_summary")
    list_filter = ("approval_status", ProfileBanFilter)
    search_fields = ("user__username", "signup_ip")
    ordering = ("-requested_at",)
    inlines = [PhoneNumberInline]
    actions = ["approve_signups", "reject_signups", "ban_users", "unban_users", "block_signup_ip"]

    readonly_fields = ("signup_ip",)

    @admin.display(description="Phone numbers")
    def phone_summary(self, obj):
        numbers = [p.formatted() for p in obj.phone_numbers.all()]
        return ", ".join(numbers) if numbers else "-"

    @admin.display(description="Status")
    def account_status(self, obj):
        # approval_status alone can't distinguish "approved and fine" from
        # "was approved, later banned" - both keep approval_status set to
        # APPROVED, since ban_users never touches that field. This column
        # folds in user.is_active so the ban is actually visible in the list.
        if obj.approval_status == UserProfile.APPROVED and not obj.user.is_active:
            return "Banned"
        return dict(UserProfile.APPROVAL_STATUSES).get(obj.approval_status, obj.approval_status)

    def _apply_decision(self, profile):
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

    @admin.action(description="Ban selected users (revokes access, does not touch shared IPs)")
    def ban_users(self, request, queryset):
        banned, skipped = 0, 0
        for profile in queryset:
            if profile.approval_status != UserProfile.APPROVED or not profile.user.is_active:
                # Only approved-and-active accounts can be banned this way.
                # Pending/rejected profiles already have is_active=False
                # for other reasons - use Reject for those instead.
                skipped += 1
                continue
            profile.user.is_active = False
            profile.user.save()
            banned += 1
        if banned:
            self.message_user(request, f"Banned {banned} user(s).")
        if skipped:
            self.message_user(request, f"{skipped} profile(s) skipped (not an approved/active account).")

    @admin.action(description="Unban selected users (restores access)")
    def unban_users(self, request, queryset):
        restored, skipped = 0, 0
        for profile in queryset:
            if profile.approval_status != UserProfile.APPROVED or profile.user.is_active:
                skipped += 1
                continue
            profile.user.is_active = True
            profile.user.save()
            restored += 1
        if restored:
            self.message_user(request, f"Unbanned {restored} user(s).")
        if skipped:
            self.message_user(request, f"{skipped} profile(s) skipped (not currently banned).")

    @admin.action(description="Block signup IP (prevents future signups/logins from it)")
    def block_signup_ip(self, request, queryset):
        blocked, skipped = 0, 0
        for profile in queryset:
            if not profile.signup_ip:
                skipped += 1
                continue
            BlockedIP.objects.get_or_create(
                ip_address=profile.signup_ip,
                defaults={"reason": f"Blocked from signup by {profile.user.username}"},
            )
            blocked += 1
        if blocked:
            self.message_user(request, f"Blocked {blocked} IP address(es).")
        if skipped:
            self.message_user(request, f"{skipped} profile(s) had no recorded signup IP.")


@admin.register(BlockedIP)
class BlockedIPAdmin(admin.ModelAdmin):
    list_display = ("ip_address", "reason", "blocked_at")
    search_fields = ("ip_address", "reason")
    ordering = ("-blocked_at",)


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)