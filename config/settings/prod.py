from .base import *  # noqa: F403

DEBUG = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31_536_000

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": env("EMAIL_HOST", default="localhost"),  # noqa: F405
            "port": env.int("EMAIL_PORT", default=587),  # noqa: F405
            "username": env("EMAIL_HOST_USER", default=""),  # noqa: F405
            "password": env("EMAIL_HOST_PASSWORD", default=""),  # noqa: F405
            "use_tls": True,
        },
    },
}

SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]