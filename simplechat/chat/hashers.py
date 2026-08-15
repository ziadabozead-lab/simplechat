"""
Custom password "hasher" that encrypts passwords instead of hashing them.

READ THIS FIRST:
Encryption is reversible - anyone holding PASSWORD_ENCRYPTION_KEY (you,
or an attacker who steals it from your server/env) can decrypt every
user's password back to plaintext. Normal hashing (PBKDF2/Argon2) is
one-way and can't be reversed even by you, even if the database leaks.
This file trades that safety away on purpose because that's what was
asked for. Keep PASSWORD_ENCRYPTION_KEY out of git and treat it like
any other secret credential (env var / secrets manager, not settings.py).

How it plugs in:
PASSWORD_HASHERS in settings.py lists this hasher first, so
set_password() (used by signup, password change, etc.) encrypts new
passwords with it. The stock Django PBKDF2 hasher stays second in the
list purely so any accounts created *before* this change still log in
correctly - Django picks the verifier by reading the algorithm prefix
stored with each password, not by trying hashers in order.
"""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.hashers import BasePasswordHasher, mask_hash
from django.core.exceptions import ImproperlyConfigured
from django.utils.crypto import constant_time_compare
from django.utils.translation import gettext_noop as _


class EncryptedPasswordHasher(BasePasswordHasher):
    algorithm = "fernetenc"

    def _fernet(self):
        key = getattr(settings, "PASSWORD_ENCRYPTION_KEY", None)
        if not key:
            raise ImproperlyConfigured(
                "PASSWORD_ENCRYPTION_KEY is not set. Generate one with:\n"
                "  python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"\n"
                "and set it as an env var - see settings.py."
            )
        if isinstance(key, str):
            key = key.encode("utf-8")
        return Fernet(key)

    def salt(self):
        # Fernet embeds its own random IV/timestamp per encryption, so a
        # separate salt isn't needed - but BasePasswordHasher expects
        # this method to exist.
        return ""

    def encode(self, password, salt=None):
        token = self._fernet().encrypt(password.encode("utf-8"))
        return "%s$%s" % (self.algorithm, token.decode("utf-8"))

    def decode(self, encoded):
        algorithm, token = encoded.split("$", 1)
        assert algorithm == self.algorithm
        return {"algorithm": algorithm, "token": token}

    def verify(self, password, encoded):
        decoded = self.decode(encoded)
        try:
            plaintext = self._fernet().decrypt(
                decoded["token"].encode("utf-8")
            ).decode("utf-8")
        except InvalidToken:
            return False
        return constant_time_compare(password, plaintext)

    def safe_summary(self, encoded):
        decoded = self.decode(encoded)
        return {
            _("algorithm"): decoded["algorithm"],
            _("token"): mask_hash(decoded["token"]),
        }

    def must_update(self, encoded):
        return False

    def harden_runtime(self, password, encoded):
        # No separate "harden" step needed for encryption - verify()
        # already does the real work.
        pass
