"""Till password hashing and checking

Passwords are stored as strings of the form
`algorithm$iterations$salt$hash_hex`

This format is compatible with Django, and the default pbkdf2_sha256
algorithm implemented in this module is compatible with
`django.contrib.auth.hashers.PBKDF2PasswordHasher`
"""

import secrets
import hashlib
import math
import base64
from . import plugins


_RSC = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_utf8 = "utf-8"


def identify_hasher(encoded):
    algorithm = encoded.split("$", 1)[0]
    return get_hasher(algorithm)


def get_hasher(algorithm):
    for h in PasswordHasher.plugins:
        if h.algorithm == algorithm or algorithm is None:
            return h()
    raise ValueError(f"Unknown password hashing algorithm {algorithm}")


def encode_password(password, algorithm=None):
    """Computes the password hash for storage in the database.

    Returns a string in the format `algorithm$iterations$salt$hash`.
    """
    hasher = get_hasher(algorithm)
    return hasher.encode(password, hasher.salt())


def check_password(password, encoded):
    """Checks a password against an encoded password
    """
    hasher = identify_hasher(encoded)
    return hasher.verify(password, encoded)


class PasswordHasher(metaclass=plugins.ClassPluginMount):
    algorithm = None
    salt_entropy = 128

    def salt(self):
        return "".join(secrets.choice(_RSC) for _ in range(
            math.ceil(self.salt_entropy / math.log2(len(_RSC)))))

    def verify(self, password, encoded):
        raise NotImplementedError("provide a verify() method")

    def encode(self, password, salt):
        raise NotImplementedError("provide an encode() method")


class PBKDF2Hasher(PasswordHasher):
    algorithm = "pbkdf2_sha256"
    iterations = 100000

    def encode(self, password, salt, iterations=None):
        iterations = iterations or self.iterations
        hash = base64.b64encode(
            hashlib.pbkdf2_hmac("sha256", bytes(password, _utf8),
                                bytes(salt, _utf8), iterations))\
                     .decode("ascii").strip()
        return f"{self.algorithm}${iterations}${salt}${hash}"

    def verify(self, password, encoded):
        algorithm, iterations_str, salt, hash = encoded.split("$", 3)
        iterations = int(iterations_str)
        assert algorithm == self.algorithm
        reencoded = self.encode(password, salt, iterations)
        return encoded == reencoded
