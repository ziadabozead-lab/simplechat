from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError
from .models import UserProfile


class SignupForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        fields = ("username",)

class PendingAwareAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        if not user.is_active:
            status = getattr(getattr(user, "profile", None), "approval_status", None)
            
            if status == UserProfile.REJECTED:
                raise ValidationError("This account's signup request was not approved (rejected).", code="rejected")
            
            if status == UserProfile.PENDING or status is None:
                raise ValidationError("This account is still waiting for admin approval.", code="pending")

            raise ValidationError("This account is inactive or banned.", code="inactive")