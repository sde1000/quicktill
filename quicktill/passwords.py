"""Till password hashing and checking logic.

This module provides functions to create 'password tuples' which take the format
`algorithm$iterations$salt$hash_hex`.
"""

import secrets
import hashlib


def compute_password_tuple(password):
    """Computes the password tuple for storage in the database.

    Returns a string in the format `algorithm$iterations$salt$hash_hex`.
    """
    iterations = 500_000
    salt = secrets.token_hex(16)
    hash = compute_pbkdf2(password, salt, iterations)
    return f"pbkdf2${iterations}${salt}${hash}"


def compute_pbkdf2(value, salt, iterations):
    """Computes t he PBKDF2 hash for a value given a salt and number of
    iterations.
    """
    hash = hashlib.pbkdf2_hmac("sha256", bytes(value, "utf-8"),
                               bytes(salt, "utf-8"), iterations)
    return hash.hex()


def check_password(password, tuple):
    """Checks a password against a tuple.

    The tuple must be in the format `algorithm$iterations$salt$hash_hex`.
    Malformed values will raise an exception.
    """
    elems = tuple.split("$")
    if len(elems) != 4:
        raise Exception("Invalid password tuple presented (len(elems) != 4).")

    algo = elems[0]
    iterations = int(elems[1])
    salt = elems[2]
    hash = elems[3]

    if algo == 'pbkdf2':
        return compute_pbkdf2(password, salt, iterations) == hash
    else:
        raise Exception("Unsupported password algorithm: " + algo)
