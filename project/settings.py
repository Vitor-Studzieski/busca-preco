import os
from pathlib import Path
from secrets import token_urlsafe

BASE_DIR = Path(__file__).resolve().parent.parent
IS_VERCEL = os.getenv("VERCEL") == "1" or bool(os.getenv("VERCEL_ENV"))
DEBUG = os.getenv("DJANGO_DEBUG", "0" if IS_VERCEL else "1") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or token_urlsafe(64)

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")
    if host.strip()
]
for variable in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
    domain = os.getenv(variable, "").strip()
    if domain and domain not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(domain)

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "pricing",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "project.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
    ]},
}]
WSGI_APPLICATION = "project.wsgi.application"

MARKETS_DATABASE = BASE_DIR / "pricing" / "markets.sqlite3"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": f"file:{MARKETS_DATABASE.as_posix()}?mode=ro",
    "OPTIONS": {"uri": True, "timeout": 2},
    "CONN_MAX_AGE": 0,
}}

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "busca-preco-default",
    },
    "pricing_search": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "busca-preco-search",
        "OPTIONS": {"MAX_ENTRIES": 300},
    },
}
PRICING_SEARCH_TTL = 90
PRICING_SEARCH_EMPTY_TTL = 30
PRICING_SEARCH_FAILURE_TTL = 10
PRICING_SEARCH_TIMEOUT = 18
PRICING_SEARCH_RATE_LIMIT = 20
PRICING_SEARCH_RATE_WINDOW = 60

if IS_VERCEL:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
