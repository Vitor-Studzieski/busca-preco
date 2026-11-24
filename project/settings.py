import os
import re
from pathlib import Path
from secrets import token_urlsafe
from urllib.parse import parse_qs, unquote, urlsplit

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
IS_VERCEL = os.getenv("VERCEL") == "1" or bool(os.getenv("VERCEL_ENV"))
DJANGO_TRUST_LOCAL_PROXY = os.getenv("DJANGO_TRUST_LOCAL_PROXY", "0") == "1"
DEBUG = os.getenv("DJANGO_DEBUG", "0" if IS_VERCEL else "1") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Defina DJANGO_SECRET_KEY fora do ambiente de desenvolvimento.")
    SECRET_KEY = token_urlsafe(64)
ALLOWED_HOSTS = [
    host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")
    if host.strip()
]
VERCEL_DOMAINS = []
for variable in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
    domain = os.getenv(variable, "").strip()
    if domain and domain not in VERCEL_DOMAINS:
        VERCEL_DOMAINS.append(domain)
ALLOWED_HOSTS.extend(domain for domain in VERCEL_DOMAINS if domain not in ALLOWED_HOSTS)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "pricing",
    "django_otp",
    "django_otp.plugins.otp_totp",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "pricing.access.PortalSecurityMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "project.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ]},
    },
]
WSGI_APPLICATION = "project.wsgi.application"

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
if DATABASE_URL:
    parsed_database_url = urlsplit(DATABASE_URL)
    if (parsed_database_url.scheme not in {"postgres", "postgresql"}
            or not parsed_database_url.hostname or not parsed_database_url.path.strip("/")):
        raise ImproperlyConfigured("DATABASE_URL deve ser uma URL PostgreSQL válida.")
    database_query = parse_qs(parsed_database_url.query)
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed_database_url.path.lstrip("/")),
        "USER": unquote(parsed_database_url.username or ""),
        "PASSWORD": unquote(parsed_database_url.password or ""),
        "HOST": parsed_database_url.hostname,
        "PORT": str(parsed_database_url.port or ""),
        "OPTIONS": {
            "sslmode": database_query.get("sslmode", [os.getenv("POSTGRES_SSLMODE", "require")])[0],
        },
    }}
elif os.getenv("POSTGRES_DB"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("PRICING_SQLITE_PATH", BASE_DIR / "db.sqlite3"),
    }}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
] + [
    {"NAME": f"django.contrib.auth.password_validation.{name}"}
    for name in (
        "UserAttributeSimilarityValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    )
]
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "pricing:search"
LOGOUT_REDIRECT_URL = "login"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
OFFER_MAX_AGE_HOURS = 36

# Independent capacity for search results and per-account request counters.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pompeia-default",
    },
    "pricing_search": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pompeia-price-search",
        "OPTIONS": {"MAX_ENTRIES": 750},
    },
    "pricing_limits": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pompeia-search-limits",
        "OPTIONS": {"MAX_ENTRIES": 2500},
    },
}
PRICING_SEARCH_TTL = 90
PRICING_SEARCH_EMPTY_TTL = 30
PRICING_SEARCH_FAILURE_TTL = 10
PRICING_SEARCH_TIMEOUT = 15
PRICING_SEARCH_RATE_LIMIT = 20
PRICING_SEARCH_RATE_WINDOW = 60

PRICING_COLLECTION_HOURS = tuple(
    int(value) for value in os.getenv("PRICING_COLLECTION_HOURS", "4,14").split(",")
)
if (len(PRICING_COLLECTION_HOURS) != 2 or len(set(PRICING_COLLECTION_HOURS)) != 2
        or any(hour not in range(24) for hour in PRICING_COLLECTION_HOURS)):
    raise ImproperlyConfigured("Defina dois horários distintos entre 0 e 23 para a coleta.")
PRICING_ALLOW_MANUAL_LINKS = os.getenv("PRICING_ALLOW_MANUAL_LINKS", "0") == "1"
PRICING_ENABLE_OWN_PRICES = os.getenv("PRICING_ENABLE_OWN_PRICES", "0") == "1"
PRICING_REDIS_URL = os.getenv("PRICING_REDIS_URL") or os.getenv("REDIS_URL", "")
if PRICING_REDIS_URL:
    for cache_alias in CACHES:
        CACHES[cache_alias] = {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": PRICING_REDIS_URL,
            "KEY_PREFIX": f"pompeia-{cache_alias}",
            "OPTIONS": {"socket_connect_timeout": 2, "socket_timeout": 2},
        }


PORTAL_ADMIN_PATH = os.getenv("PRICING_ADMIN_PATH", "admin/")
if re.fullmatch(r"[a-z0-9_-]+/", PORTAL_ADMIN_PATH) is None:
    raise ImproperlyConfigured("PRICING_ADMIN_PATH deve conter um segmento de caminho seguido de barra.")
SESSION_IDLE_DAYS = int(os.getenv("PRICING_SESSION_IDLE_DAYS", "30"))
if not 1 <= SESSION_IDLE_DAYS <= 90:
    raise ImproperlyConfigured("Defina a duração da sessão entre 1 e 90 dias.")
SESSION_COOKIE_AGE = SESSION_IDLE_DAYS * 24 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
CSRF_TRUSTED_ORIGINS = [
    value.strip() for value in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if value.strip()
]
CSRF_TRUSTED_ORIGINS.extend(
    origin for origin in (f"https://{domain}" for domain in VERCEL_DOMAINS)
    if origin not in CSRF_TRUSTED_ORIGINS
)
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
if not DEBUG:
    if len(SECRET_KEY) < 50 or "*" in ALLOWED_HOSTS:
        raise ImproperlyConfigured("Defina uma chave exclusiva forte e hosts restritos em produção.")
    if not (DATABASE_URL or os.getenv("POSTGRES_DB")) or not PRICING_REDIS_URL:
        raise ImproperlyConfigured("Produção requer PostgreSQL e Redis.")
    if PORTAL_ADMIN_PATH == "admin/":
        raise ImproperlyConfigured("Defina PRICING_ADMIN_PATH específico para produção.")
    if DJANGO_TRUST_LOCAL_PROXY or IS_VERCEL:
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    if not DATABASE_URL:
        DATABASES["default"]["OPTIONS"] = {"sslmode": os.getenv("POSTGRES_SSLMODE", "prefer")}
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
    INSTALLED_APPS[0] = "project.admin_apps.ProtectedAdminConfig"
OTP_TOTP_ISSUER = "Portal Pompeia"
OTP_ADMIN_HIDE_SENSITIVE_DATA = True
ALLOW_DEV_PROVISIONING = DEBUG
MIDDLEWARE.insert(0, "project.logging.RequestIdMiddleware")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "project.logging.JSONLogFormatter"}},
    "handlers": {"structured": {"class": "logging.StreamHandler", "formatter": "json"}},
    "loggers": {
        "pricing": {"handlers": ["structured"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["structured"], "level": "WARNING", "propagate": False},
    },
}
