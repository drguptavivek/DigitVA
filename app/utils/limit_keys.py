"""Rate-limit keys that never hold a raw identifier."""
import hashlib
import hmac

from flask import current_app


def keyed_digest(key_func):
    """``key_func``'s bucket under an HMAC of its key: limit keys are Redis
    keys and flask-limiter logs the key of every refused request, so emails,
    mobile numbers and usernames must not appear in them (digitva-mu7m)."""
    def key():
        secret = current_app.secret_key.encode("utf-8")
        return "digest:" + hmac.new(secret, key_func().encode("utf-8"), hashlib.sha256).hexdigest()
    return key
