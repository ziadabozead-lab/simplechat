from django.contrib.auth.backends import ModelBackend


class AllowInactiveAuthBackend(ModelBackend):
    """
    Identical to Django's default ModelBackend, except it doesn't reject
    inactive users during authenticate() itself. That rejection is instead
    left to AuthenticationForm.confirm_login_allowed() (see
    PendingAwareAuthenticationForm in forms.py), which can then give a
    specific "still pending approval" / "was rejected" message instead of
    the generic "invalid credentials" one Django would otherwise show.
    """

    def user_can_authenticate(self, user):
        return True