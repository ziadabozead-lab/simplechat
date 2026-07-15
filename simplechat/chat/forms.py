from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError

from .models import UserProfile


class SignupForm(UserCreationForm):
    """
    Same fields as Django's default UserCreationForm (username + two
    password fields). Phone numbers are handled separately in the signup
    view, since the person can add any number of them dynamically in the
    template - a fixed set of form fields wouldn't fit that.
    """

    class Meta(UserCreationForm.Meta):
        fields = ("username",)


class PendingAwareAuthenticationForm(AuthenticationForm):
    """
    Same as Django's default login form, but gives a specific message
    when the account exists and is simply awaiting (or was denied)
    admin approval, instead of the generic "invalid credentials" text.
    """

    def confirm_login_allowed(self, user):
        if not user.is_active:
            status = getattr(getattr(user, "profile", None), "approval_status", None)
            if status == UserProfile.REJECTED:
                raise ValidationError(
                    "This account's signup request was not approved.", code="rejected"
                )
            if status == UserProfile.PENDING or status is None:
                raise ValidationError(
                    "This account is still waiting for admin approval.", code="pending"
                )
            raise ValidationError("This account is inactive.", code="inactive")