import datetime
import json
import math
import multiprocessing
import os
import tempfile
from os import PathLike
from pathlib import Path
from platform import machine
from typing import Final
from urllib.parse import urlparse

from celery.schedules import crontab
from concurrent_log_handler.queue import setup_logging_queues
from django.utils.translation import gettext_lazy as _
from dotenv import load_dotenv

# Tap paperless.conf if it's available
configuration_path = os.getenv("PAPERLESS_CONFIGURATION_PATH")
if configuration_path and os.path.exists(configuration_path):
    load_dotenv(configuration_path)
elif os.path.exists("../paperless.conf"):
    load_dotenv("../paperless.conf")
elif os.path.exists("/etc/paperless.conf"):
    load_dotenv("/etc/paperless.conf")
elif os.path.exists("/usr/local/etc/paperless.conf"):
    load_dotenv("/usr/local/etc/paperless.conf")

# There are multiple levels of concurrency in paperless:
#  - Multiple consumers may be run in parallel.
#  - Each consumer may process multiple pages in parallel.
#  - Each Tesseract OCR run may spawn multiple threads to process a single page
#    slightly faster.
# The performance gains from having tesseract use multiple threads are minimal.
# However, when multiple pages are processed in parallel, the total number of
# OCR threads may exceed the number of available cpu cores, which will
# dramatically slow down the consumption process. This settings limits each
# Tesseract process to one thread.
os.environ["OMP_THREAD_LIMIT"] = "1"


def __get_boolean(key: str, default: str = "NO") -> bool:
    """
    Return a boolean value based on whatever the user has supplied in the
    environment based on whether the value "looks like" it's True or not.
    """
    return bool(os.getenv(key, default).lower() in ("yes", "y", "1", "t", "true"))


def __get_int(key: str, default: int) -> int:
    """
    Return an integer value based on the environment variable or a default
    """
    return int(os.getenv(key, default))


def __get_optional_int(key: str) -> int | None:
    """
    Returns None if the environment key is not present, otherwise an integer
    """
    if key in os.environ:
        return __get_int(key, -1)  # pragma: no cover
    return None


def __get_float(key: str, default: float) -> float:
    """
    Return an integer value based on the environment variable or a default
    """
    return float(os.getenv(key, default))


def __get_path(
    key: str,
    default: PathLike | str,
) -> Path:
    """
    Return a normalized, absolute path based on the environment variable or a default,
    if provided
    """
    if key in os.environ:
        return Path(os.environ[key]).resolve()
    return Path(default).resolve()


def __get_optional_path(key: str) -> Path | None:
    """
    Returns None if the environment key is not present, otherwise a fully resolved Path
    """
    if key in os.environ:
        return __get_path(key, "")
    return None


def __get_list(
    key: str,
    default: list[str] | None = None,
    sep: str = ",",
) -> list[str]:
    """
    Return a list of elements from the environment, as separated by the given
    string, or the default if the key does not exist
    """
    if key in os.environ:
        return list(filter(None, os.environ[key].split(sep)))
    elif default is not None:
        return default
    else:
        return []


def _parse_redis_url(env_redis: str | None) -> tuple[str, str]:
    """
    Gets the Redis information from the environment or a default and handles
    converting from incompatible django_channels and celery formats.

    Returns a tuple of (celery_url, channels_url)
    """

    # Not set, return a compatible default
    if env_redis is None:
        return ("redis://localhost:6379", "redis://localhost:6379")

    if "unix" in env_redis.lower():
        # channels_redis socket format, looks like:
        # "unix:///path/to/redis.sock"
        _, path = env_redis.split(":")
        # Optionally setting a db number
        if "?db=" in env_redis:
            path, number = path.split("?db=")
            return (f"redis+socket:{path}?virtual_host={number}", env_redis)
        else:
            return (f"redis+socket:{path}", env_redis)

    elif "+socket" in env_redis.lower():
        # celery socket style, looks like:
        # "redis+socket:///path/to/redis.sock"
        _, path = env_redis.split(":")
        if "?virtual_host=" in env_redis:
            # Virtual host (aka db number)
            path, number = path.split("?virtual_host=")
            return (env_redis, f"unix:{path}?db={number}")
        else:
            return (env_redis, f"unix:{path}")

    # Not a socket
    return (env_redis, env_redis)


def _parse_beat_schedule() -> dict:
    """
    Configures the scheduled tasks, according to default or
    environment variables.  Task expiration is configured so the task will
    expire (and not run), shortly before the default frequency will put another
    of the same task into the queue


    https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html#beat-entries
    https://docs.celeryq.dev/en/latest/userguide/calling.html#expiration
    """
    schedule = {}
    tasks = [
        {
            "name": "Check all e-mail accounts",
            "env_key": "PAPERLESS_EMAIL_TASK_CRON",
            # Default every ten minutes
            "env_default": "*/10 * * * *",
            "task": "paperless_mail.tasks.process_mail_accounts",
            "options": {
                # 1 minute before default schedule sends again
                "expires": 9.0 * 60.0,
            },
        },
        {
            "name": "Train the classifier",
            "env_key": "PAPERLESS_TRAIN_TASK_CRON",
            # Default hourly at 5 minutes past the hour
            "env_default": "5 */1 * * *",
            "task": "documents.tasks.train_classifier",
            "options": {
                # 1 minute before default schedule sends again
                "expires": 59.0 * 60.0,
            },
        },
        {
            "name": "Optimize the index",
            "env_key": "PAPERLESS_INDEX_TASK_CRON",
            # Default daily at midnight
            "env_default": "0 0 * * *",
            "task": "documents.tasks.index_optimize",
            "options": {
                # 1 hour before default schedule sends again
                "expires": 23.0 * 60.0 * 60.0,
            },
        },
        {
            "name": "Perform sanity check",
            "env_key": "PAPERLESS_SANITY_TASK_CRON",
            # Default Sunday at 00:30
            "env_default": "30 0 * * sun",
            "task": "documents.tasks.sanity_check",
            "options": {
                # 1 hour before default schedule sends again
                "expires": ((7.0 * 24.0) - 1.0) * 60.0 * 60.0,
            },
        },
        {
            "name": "Empty trash",
            "env_key": "PAPERLESS_EMPTY_TRASH_TASK_CRON",
            # Default daily at 01:00
            "env_default": "0 1 * * *",
            "task": "documents.tasks.empty_trash",
            "options": {
                # 1 hour before default schedule sends again
                "expires": 23.0 * 60.0 * 60.0,
            },
        },
        {
            "name": "Check and run scheduled workflows",
            "env_key": "PAPERLESS_WORKFLOW_SCHEDULED_TASK_CRON",
            # Default hourly at 5 minutes past the hour
            "env_default": "5 */1 * * *",
            "task": "documents.tasks.check_scheduled_workflows",
            "options": {
                # 1 minute before default schedule sends again
                "expires": 59.0 * 60.0,
            },
        },
    ]
    for task in tasks:
        # Either get the environment setting or use the default
        value = os.getenv(task["env_key"], task["env_default"])
        # Don't add disabled tasks to the schedule
        if value == "disable":
            continue
        # I find https://crontab.guru/ super helpful
        # crontab(5) format
        #   - five time-and-date fields
        #   - separated by at least one blank
        minute, hour, day_month, month, day_week = value.split(" ")

        schedule[task["name"]] = {
            "task": task["task"],
            "schedule": crontab(minute, hour, day_week, day_month, month),
            "options": task["options"],
        }

    return schedule


# NEVER RUN WITH DEBUG IN PRODUCTION.
DEBUG = __get_boolean("PAPERLESS_DEBUG", "NO")


###############################################################################
# Directories                                                                 #
###############################################################################

BASE_DIR: Path = Path(__file__).resolve().parent.parent

STATIC_ROOT = __get_path("PAPERLESS_STATICDIR", BASE_DIR.parent / "static")

MEDIA_ROOT = __get_path("PAPERLESS_MEDIA_ROOT", BASE_DIR.parent / "media")
ORIGINALS_DIR = MEDIA_ROOT / "documents" / "originals"
ARCHIVE_DIR = MEDIA_ROOT / "documents" / "archive"
THUMBNAIL_DIR = MEDIA_ROOT / "documents" / "thumbnails"

DATA_DIR = __get_path("PAPERLESS_DATA_DIR", BASE_DIR.parent / "data")

NLTK_DIR = __get_path("PAPERLESS_NLTK_DIR", "/usr/share/nltk_data")

# Check deprecated setting first
EMPTY_TRASH_DIR = os.getenv(
    "PAPERLESS_TRASH_DIR",
    os.getenv("PAPERLESS_EMPTY_TRASH_DIR"),
)

# Lock file for synchronizing changes to the MEDIA directory across multiple
# threads.
MEDIA_LOCK = MEDIA_ROOT / "media.lock"
INDEX_DIR = DATA_DIR / "index"
MODEL_FILE = __get_path(
    "PAPERLESS_MODEL_FILE",
    DATA_DIR / "classification_model.pickle",
)

LOGGING_DIR = __get_path("PAPERLESS_LOGGING_DIR", DATA_DIR / "log")

CONSUMPTION_DIR = __get_path(
    "PAPERLESS_CONSUMPTION_DIR",
    BASE_DIR.parent / "consume",
)

# This will be created if it doesn't exist
SCRATCH_DIR = __get_path(
    "PAPERLESS_SCRATCH_DIR",
    Path(tempfile.gettempdir()) / "paperless",
)

###############################################################################
# Application Definition                                                      #
###############################################################################

env_apps = __get_list("PAPERLESS_APPS")

INSTALLED_APPS = [
    "whitenoise.runserver_nostatic",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "django_extensions",
    "paperless",
    "documents.apps.DocumentsConfig",
    "paperless_tesseract.apps.PaperlessTesseractConfig",
    "paperless_text.apps.PaperlessTextConfig",
    "paperless_mail.apps.PaperlessMailConfig",
    "django.contrib.admin",
    "rest_framework",
    "rest_framework.authtoken",
    "django_filters",
    "django_celery_results",
    "guardian",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.mfa",
    *env_apps,
]

if DEBUG:
    INSTALLED_APPS.append("channels")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "paperless.auth.PaperlessBasicAuthentication",
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.AcceptHeaderVersioning",
    "DEFAULT_VERSION": "1",
    # Make sure these are ordered and that the most recent version appears
    # last
    "ALLOWED_VERSIONS": ["1", "2", "3", "4", "5", "6"],
}

if DEBUG:
    REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"].append(
        "paperless.auth.AngularApiAuthenticationOverride",
    )

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "paperless.middleware.ApiVersionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

# Optional to enable compression
if __get_boolean("PAPERLESS_ENABLE_COMPRESSION", "yes"):  # pragma: no cover
    MIDDLEWARE.insert(0, "compression_middleware.middleware.CompressionMiddleware")

ROOT_URLCONF = "paperless.urls"


def _parse_base_paths() -> tuple[str, str, str, str, str]:
    script_name = os.getenv("PAPERLESS_FORCE_SCRIPT_NAME")
    base_url = (script_name or "") + "/"
    login_url = base_url + "accounts/login/"
    login_redirect_url = base_url + "dashboard"
    logout_redirect_url = os.getenv(
        "PAPERLESS_LOGOUT_REDIRECT_URL",
        login_url + "?loggedout=1",
    )
    return script_name, base_url, login_url, login_redirect_url, logout_redirect_url


FORCE_SCRIPT_NAME, BASE_URL, LOGIN_URL, LOGIN_REDIRECT_URL, LOGOUT_REDIRECT_URL = (
    _parse_base_paths()
)

WSGI_APPLICATION = "paperless.wsgi.application"
ASGI_APPLICATION = "paperless.asgi.application"

STATIC_URL = os.getenv("PAPERLESS_STATIC_URL", BASE_URL + "static/")
WHITENOISE_STATIC_PREFIX = "/static/"

if machine().lower() == "aarch64":  # pragma: no cover
    _static_backend = "django.contrib.staticfiles.storage.StaticFilesStorage"
else:
    _static_backend = "whitenoise.storage.CompressedStaticFilesStorage"

STORAGES = {
    "staticfiles": {
        "BACKEND": _static_backend,
    },
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
}

_CELERY_REDIS_URL, _CHANNELS_REDIS_URL = _parse_redis_url(
    os.getenv("PAPERLESS_REDIS", None),
)

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "documents.context_processors.settings",
            ],
        },
    },
]

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.pubsub.RedisPubSubChannelLayer",
        "CONFIG": {
            "hosts": [_CHANNELS_REDIS_URL],
            "capacity": 2000,  # default 100
            "expiry": 15,  # default 60
            "prefix": os.getenv("PAPERLESS_REDIS_PREFIX", ""),
        },
    },
}

###############################################################################
# Security                                                                    #
###############################################################################

AUTHENTICATION_BACKENDS = [
    "guardian.backends.ObjectPermissionBackend",
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

ACCOUNT_LOGOUT_ON_GET = True
ACCOUNT_DEFAULT_HTTP_PROTOCOL = os.getenv(
    "PAPERLESS_ACCOUNT_DEFAULT_HTTP_PROTOCOL",
    "https",
)

ACCOUNT_ADAPTER = "paperless.adapter.CustomAccountAdapter"
ACCOUNT_ALLOW_SIGNUPS = __get_boolean("PAPERLESS_ACCOUNT_ALLOW_SIGNUPS")

SOCIALACCOUNT_ADAPTER = "paperless.adapter.CustomSocialAccountAdapter"
SOCIALACCOUNT_ALLOW_SIGNUPS = __get_boolean(
    "PAPERLESS_SOCIALACCOUNT_ALLOW_SIGNUPS",
    "yes",
)
SOCIALACCOUNT_AUTO_SIGNUP = __get_boolean("PAPERLESS_SOCIAL_AUTO_SIGNUP")
SOCIALACCOUNT_PROVIDERS = json.loads(
    os.getenv("PAPERLESS_SOCIALACCOUNT_PROVIDERS", "{}"),
)

MFA_TOTP_ISSUER = "Paperless-ngx"

ACCOUNT_EMAIL_SUBJECT_PREFIX = "[Paperless-ngx] "

DISABLE_REGULAR_LOGIN = __get_boolean("PAPERLESS_DISABLE_REGULAR_LOGIN")
REDIRECT_LOGIN_TO_SSO = __get_boolean("PAPERLESS_REDIRECT_LOGIN_TO_SSO")

AUTO_LOGIN_USERNAME = os.getenv("PAPERLESS_AUTO_LOGIN_USERNAME")

ACCOUNT_EMAIL_VERIFICATION = os.getenv(
    "PAPERLESS_ACCOUNT_EMAIL_VERIFICATION",
    "optional",
)

ACCOUNT_SESSION_REMEMBER = __get_boolean("PAPERLESS_ACCOUNT_SESSION_REMEMBER", "True")
SESSION_EXPIRE_AT_BROWSER_CLOSE = not ACCOUNT_SESSION_REMEMBER
SESSION_COOKIE_AGE = int(
    os.getenv("PAPERLESS_SESSION_COOKIE_AGE", 60 * 60 * 24 * 7 * 3),
)

if AUTO_LOGIN_USERNAME:
    _index = MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware")
    # This overrides everything the auth middleware is doing but still allows
    # regular login in case the provided user does not exist.
    MIDDLEWARE.insert(_index + 1, "paperless.auth.AutoLoginMiddleware")


def _parse_remote_user_settings() -> str:
    global MIDDLEWARE, AUTHENTICATION_BACKENDS, REST_FRAMEWORK
    enable = __get_boolean("PAPERLESS_ENABLE_HTTP_REMOTE_USER")
    enable_api = __get_boolean("PAPERLESS_ENABLE_HTTP_REMOTE_USER_API")
    if enable or enable_api:
        MIDDLEWARE.append("paperless.auth.HttpRemoteUserMiddleware")
        AUTHENTICATION_BACKENDS.insert(
            0,
            "django.contrib.auth.backends.RemoteUserBackend",
        )

    if enable_api:
        REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"].insert(
            0,
            "paperless.auth.PaperlessRemoteUserAuthentication",
        )

    header_name = os.getenv(
        "PAPERLESS_HTTP_REMOTE_USER_HEADER_NAME",
        "HTTP_REMOTE_USER",
    )

    return header_name


HTTP_REMOTE_USER_HEADER_NAME = _parse_remote_user_settings()

# X-Frame options for embedded PDF display:
X_FRAME_OPTIONS = "ANY" if DEBUG else "SAMEORIGIN"


# The next 3 settings can also be set using just PAPERLESS_URL
CSRF_TRUSTED_ORIGINS = __get_list("PAPERLESS_CSRF_TRUSTED_ORIGINS")

# We allow CORS from localhost:8000
CORS_ALLOWED_ORIGINS = __get_list(
    "PAPERLESS_CORS_ALLOWED_HOSTS",
    ["http://localhost:8000"],
)

if DEBUG:
    # Allow access from the angular development server during debugging
    CORS_ALLOWED_ORIGINS.append("http://localhost:4200")

ALLOWED_HOSTS = __get_list("PAPERLESS_ALLOWED_HOSTS", ["*"])
if ALLOWED_HOSTS != ["*"]:
    # always allow localhost. Necessary e.g. for healthcheck in docker.
    ALLOWED_HOSTS.append("localhost")


def _parse_paperless_url():
    global CSRF_TRUSTED_ORIGINS, CORS_ALLOWED_ORIGINS, ALLOWED_HOSTS
    url = os.getenv("PAPERLESS_URL")
    if url:
        CSRF_TRUSTED_ORIGINS.append(url)
        CORS_ALLOWED_ORIGINS.append(url)
        ALLOWED_HOSTS.append(urlparse(url).hostname)

    return url


PAPERLESS_URL = _parse_paperless_url()

# For use with trusted proxies
TRUSTED_PROXIES = __get_list("PAPERLESS_TRUSTED_PROXIES")

USE_X_FORWARDED_HOST = __get_boolean("PAPERLESS_USE_X_FORWARD_HOST", "false")
USE_X_FORWARDED_PORT = __get_boolean("PAPERLESS_USE_X_FORWARD_PORT", "false")
SECURE_PROXY_SSL_HEADER = (
    tuple(json.loads(os.environ["PAPERLESS_PROXY_SSL_HEADER"]))
    if "PAPERLESS_PROXY_SSL_HEADER" in os.environ
    else None
)

# The secret key has a default that should be fine so long as you're hosting
# Paperless on a closed network.  However, if you're putting this anywhere
# public, you should change the key to something unique and verbose.
SECRET_KEY = os.getenv(
    "PAPERLESS_SECRET_KEY",
    "e11fl1oa-*ytql8p)(06fbj4ukrlo+n7k&q5+$1md7i+mge=ee",
)

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Disable Django's artificial limit on the number of form fields to submit at
# once. This is a protection against overloading the server, but since this is
# a self-hosted sort of gig, the benefits of being able to mass-delete a ton
# of log entries outweigh the benefits of such a safeguard.

DATA_UPLOAD_MAX_NUMBER_FIELDS = None

COOKIE_PREFIX = os.getenv("PAPERLESS_COOKIE_PREFIX", "")

CSRF_COOKIE_NAME = f"{COOKIE_PREFIX}csrftoken"
SESSION_COOKIE_NAME = f"{COOKIE_PREFIX}sessionid"
LANGUAGE_COOKIE_NAME = f"{COOKIE_PREFIX}django_language"

EMAIL_CERTIFICATE_FILE = __get_optional_path("PAPERLESS_EMAIL_CERTIFICATE_LOCATION")


###############################################################################
# Database                                                                    #
###############################################################################
def _parse_db_settings() -> dict:
    databases = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.path.join(DATA_DIR, "db.sqlite3"),
            "OPTIONS": {},
        },
    }
    if os.getenv("PAPERLESS_DBHOST"):
        # Have sqlite available as a second option for management commands
        # This is important when migrating to/from sqlite
        databases["sqlite"] = databases["default"].copy()

        databases["default"] = {
            "HOST": os.getenv("PAPERLESS_DBHOST"),
            "NAME": os.getenv("PAPERLESS_DBNAME", "paperless"),
            "USER": os.getenv("PAPERLESS_DBUSER", "paperless"),
            "PASSWORD": os.getenv("PAPERLESS_DBPASS", "paperless"),
            "OPTIONS": {},
        }
        if os.getenv("PAPERLESS_DBPORT"):
            databases["default"]["PORT"] = os.getenv("PAPERLESS_DBPORT")

        # Leave room for future extensibility
        if os.getenv("PAPERLESS_DBENGINE") == "mariadb":
            engine = "django.db.backends.mysql"
            options = {
                "read_default_file": "/etc/mysql/my.cnf",
                "charset": "utf8mb4",
                "ssl_mode": os.getenv("PAPERLESS_DBSSLMODE", "PREFERRED"),
                "ssl": {
                    "ca": os.getenv("PAPERLESS_DBSSLROOTCERT", None),
                    "cert": os.getenv("PAPERLESS_DBSSLCERT", None),
                    "key": os.getenv("PAPERLESS_DBSSLKEY", None),
                },
            }

        else:  # Default to PostgresDB
            engine = "django.db.backends.postgresql"
            options = {
                "sslmode": os.getenv("PAPERLESS_DBSSLMODE", "prefer"),
                "sslrootcert": os.getenv("PAPERLESS_DBSSLROOTCERT", None),
                "sslcert": os.getenv("PAPERLESS_DBSSLCERT", None),
                "sslkey": os.getenv("PAPERLESS_DBSSLKEY", None),
            }

        databases["default"]["ENGINE"] = engine
        databases["default"]["OPTIONS"].update(options)

    if os.getenv("PAPERLESS_DB_TIMEOUT") is not None:
        if databases["default"]["ENGINE"] == "django.db.backends.sqlite3":
            databases["default"]["OPTIONS"].update(
                {"timeout": int(os.getenv("PAPERLESS_DB_TIMEOUT"))},
            )
        else:
            databases["default"]["OPTIONS"].update(
                {"connect_timeout": int(os.getenv("PAPERLESS_DB_TIMEOUT"))},
            )
            databases["sqlite"]["OPTIONS"].update(
                {"timeout": int(os.getenv("PAPERLESS_DB_TIMEOUT"))},
            )
    return databases


DATABASES = _parse_db_settings()

if os.getenv("PAPERLESS_DBENGINE") == "mariadb":
    # Silence Django error on old MariaDB versions.
    # VARCHAR can support > 255 in modern versions
    # https://docs.djangoproject.com/en/4.1/ref/checks/#database
    # https://mariadb.com/kb/en/innodb-system-variables/#innodb_large_prefix
    SILENCED_SYSTEM_CHECKS = ["mysql.W003"]

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

###############################################################################
# Internationalization                                                        #
###############################################################################

LANGUAGE_CODE = "en-us"

LANGUAGES = [
    ("en-us", _("English (US)")),  # needs to be first to act as fallback language
    ("ar-ar", _("Arabic")),
    ("af-za", _("Afrikaans")),
    ("be-by", _("Belarusian")),
    ("bg-bg", _("Bulgarian")),
    ("ca-es", _("Catalan")),
    ("cs-cz", _("Czech")),
    ("da-dk", _("Danish")),
    ("de-de", _("German")),
    ("el-gr", _("Greek")),
    ("en-gb", _("English (GB)")),
    ("es-es", _("Spanish")),
    ("fi-fi", _("Finnish")),
    ("fr-fr", _("French")),
    ("hu-hu", _("Hungarian")),
    ("it-it", _("Italian")),
    ("ja-jp", _("Japanese")),
    ("ko-kr", _("Korean")),
    ("lb-lu", _("Luxembourgish")),
    ("no-no", _("Norwegian")),
    ("nl-nl", _("Dutch")),
    ("pl-pl", _("Polish")),
    ("pt-br", _("Portuguese (Brazil)")),
    ("pt-pt", _("Portuguese")),
    ("ro-ro", _("Romanian")),
    ("ru-ru", _("Russian")),
    ("sk-sk", _("Slovak")),
    ("sl-si", _("Slovenian")),
    ("sr-cs", _("Serbian")),
    ("sv-se", _("Swedish")),
    ("tr-tr", _("Turkish")),
    ("uk-ua", _("Ukrainian")),
    ("zh-cn", _("Chinese Simplified")),
]

LOCALE_PATHS = [os.path.join(BASE_DIR, "locale")]

TIME_ZONE = os.getenv("PAPERLESS_TIME_ZONE", "UTC")

USE_I18N = True

USE_L10N = True

USE_TZ = True

###############################################################################
# Logging                                                                     #
###############################################################################

setup_logging_queues()

LOGGING_DIR.mkdir(parents=True, exist_ok=True)

LOGROTATE_MAX_SIZE = os.getenv("PAPERLESS_LOGROTATE_MAX_SIZE", 1024 * 1024)
LOGROTATE_MAX_BACKUPS = os.getenv("PAPERLESS_LOGROTATE_MAX_BACKUPS", 20)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] [{levelname}] [{name}] {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG" if DEBUG else "INFO",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file_paperless": {
            "class": "concurrent_log_handler.ConcurrentRotatingFileHandler",
            "formatter": "verbose",
            "filename": os.path.join(LOGGING_DIR, "paperless.log"),
            "maxBytes": LOGROTATE_MAX_SIZE,
            "backupCount": LOGROTATE_MAX_BACKUPS,
        },
        "file_mail": {
            "class": "concurrent_log_handler.ConcurrentRotatingFileHandler",
            "formatter": "verbose",
            "filename": os.path.join(LOGGING_DIR, "mail.log"),
            "maxBytes": LOGROTATE_MAX_SIZE,
            "backupCount": LOGROTATE_MAX_BACKUPS,
        },
        "file_celery": {
            "class": "concurrent_log_handler.ConcurrentRotatingFileHandler",
            "formatter": "verbose",
            "filename": os.path.join(LOGGING_DIR, "celery.log"),
            "maxBytes": LOGROTATE_MAX_SIZE,
            "backupCount": LOGROTATE_MAX_BACKUPS,
        },
    },
    "root": {"handlers": ["console"]},
    "loggers": {
        "paperless": {"handlers": ["file_paperless"], "level": "DEBUG"},
        "paperless_mail": {"handlers": ["file_mail"], "level": "DEBUG"},
        "ocrmypdf": {"handlers": ["file_paperless"], "level": "INFO"},
        "celery": {"handlers": ["file_celery"], "level": "DEBUG"},
        "kombu": {"handlers": ["file_celery"], "level": "DEBUG"},
    },
}

###############################################################################
# Task queue                                                                  #
###############################################################################

# https://docs.celeryq.dev/en/stable/userguide/configuration.html

CELERY_BROKER_URL = _CELERY_REDIS_URL
CELERY_TIMEZONE = TIME_ZONE

CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_WORKER_CONCURRENCY: Final[int] = __get_int("PAPERLESS_TASK_WORKERS", 1)
TASK_WORKERS = CELERY_WORKER_CONCURRENCY
CELERY_WORKER_MAX_TASKS_PER_CHILD = 1
CELERY_WORKER_SEND_TASK_EVENTS = True
CELERY_TASK_SEND_SENT_EVENT = True
CELERY_SEND_TASK_SENT_EVENT = True
CELERY_BROKER_CONNECTION_RETRY = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "global_keyprefix": os.getenv("PAPERLESS_REDIS_PREFIX", ""),
}

CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT: Final[int] = __get_int("PAPERLESS_WORKER_TIMEOUT", 1800)

CELERY_RESULT_EXTENDED = True
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "default"

# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-serializer
CELERY_TASK_SERIALIZER = "pickle"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std-setting-accept_content
CELERY_ACCEPT_CONTENT = ["application/json", "application/x-python-serialize"]

# https://docs.celeryq.dev/en/stable/userguide/configuration.html#beat-schedule
CELERY_BEAT_SCHEDULE = _parse_beat_schedule()

# https://docs.celeryq.dev/en/stable/userguide/configuration.html#beat-schedule-filename
CELERY_BEAT_SCHEDULE_FILENAME = os.path.join(DATA_DIR, "celerybeat-schedule.db")

# django setting.
CACHES = {
    "default": {
        "BACKEND": os.environ.get(
            "PAPERLESS_CACHE_BACKEND",
            "django.core.cache.backends.redis.RedisCache",
        ),
        "LOCATION": _CHANNELS_REDIS_URL,
        "KEY_PREFIX": os.getenv("PAPERLESS_REDIS_PREFIX", ""),
    },
}

if DEBUG and os.getenv("PAPERLESS_CACHE_BACKEND") is None:
    CACHES["default"]["BACKEND"] = (
        "django.core.cache.backends.locmem.LocMemCache"  # pragma: no cover
    )


def default_threads_per_worker(task_workers) -> int:
    # always leave one core open
    available_cores = max(multiprocessing.cpu_count(), 1)
    try:
        return max(math.floor(available_cores / task_workers), 1)
    except NotImplementedError:
        return 1


THREADS_PER_WORKER = os.getenv(
    "PAPERLESS_THREADS_PER_WORKER",
    default_threads_per_worker(CELERY_WORKER_CONCURRENCY),
)

###############################################################################
# Paperless Specific Settings                                                 #
###############################################################################

CONSUMER_POLLING = int(os.getenv("PAPERLESS_CONSUMER_POLLING", 0))

CONSUMER_POLLING_DELAY = int(os.getenv("PAPERLESS_CONSUMER_POLLING_DELAY", 5))

CONSUMER_POLLING_RETRY_COUNT = int(
    os.getenv("PAPERLESS_CONSUMER_POLLING_RETRY_COUNT", 5),
)

CONSUMER_INOTIFY_DELAY: Final[float] = __get_float(
    "PAPERLESS_CONSUMER_INOTIFY_DELAY",
    0.5,
)

CONSUMER_DELETE_DUPLICATES = __get_boolean("PAPERLESS_CONSUMER_DELETE_DUPLICATES")

CONSUMER_RECURSIVE = __get_boolean("PAPERLESS_CONSUMER_RECURSIVE")

# Ignore glob patterns, relative to PAPERLESS_CONSUMPTION_DIR
CONSUMER_IGNORE_PATTERNS = list(
    json.loads(
        os.getenv(
            "PAPERLESS_CONSUMER_IGNORE_PATTERNS",
            '[".DS_Store", ".DS_STORE", "._*", ".stfolder/*", ".stversions/*", ".localized/*", "desktop.ini", "@eaDir/*", "Thumbs.db"]',
        ),
    ),
)

CONSUMER_SUBDIRS_AS_TAGS = __get_boolean("PAPERLESS_CONSUMER_SUBDIRS_AS_TAGS")

CONSUMER_ENABLE_BARCODES: Final[bool] = __get_boolean(
    "PAPERLESS_CONSUMER_ENABLE_BARCODES",
)

CONSUMER_BARCODE_TIFF_SUPPORT: Final[bool] = __get_boolean(
    "PAPERLESS_CONSUMER_BARCODE_TIFF_SUPPORT",
)

CONSUMER_BARCODE_STRING: Final[str] = os.getenv(
    "PAPERLESS_CONSUMER_BARCODE_STRING",
    "PATCHT",
)

CONSUMER_BARCODE_SCANNER: Final[str] = os.getenv(
    "PAPERLESS_CONSUMER_BARCODE_SCANNER",
    "PYZBAR",
).upper()

CONSUMER_ENABLE_ASN_BARCODE: Final[bool] = __get_boolean(
    "PAPERLESS_CONSUMER_ENABLE_ASN_BARCODE",
)

CONSUMER_ASN_BARCODE_PREFIX: Final[str] = os.getenv(
    "PAPERLESS_CONSUMER_ASN_BARCODE_PREFIX",
    "ASN",
)

CONSUMER_BARCODE_UPSCALE: Final[float] = __get_float(
    "PAPERLESS_CONSUMER_BARCODE_UPSCALE",
    0.0,
)

CONSUMER_BARCODE_DPI: Final[int] = __get_int("PAPERLESS_CONSUMER_BARCODE_DPI", 300)

CONSUMER_BARCODE_MAX_PAGES: Final[int] = __get_int(
    "PAPERLESS_CONSUMER_BARCODE_MAX_PAGES",
    0,
)

CONSUMER_BARCODE_RETAIN_SPLIT_PAGES = __get_boolean(
    "PAPERLESS_CONSUMER_BARCODE_RETAIN_SPLIT_PAGES",
)

CONSUMER_ENABLE_TAG_BARCODE: Final[bool] = __get_boolean(
    "PAPERLESS_CONSUMER_ENABLE_TAG_BARCODE",
)

CONSUMER_TAG_BARCODE_MAPPING = dict(
    json.loads(
        os.getenv(
            "PAPERLESS_CONSUMER_TAG_BARCODE_MAPPING",
            '{"TAG:(.*)": "\\\\g<1>"}',
        ),
    ),
)

CONSUMER_ENABLE_COLLATE_DOUBLE_SIDED: Final[bool] = __get_boolean(
    "PAPERLESS_CONSUMER_ENABLE_COLLATE_DOUBLE_SIDED",
)

CONSUMER_COLLATE_DOUBLE_SIDED_SUBDIR_NAME: Final[str] = os.getenv(
    "PAPERLESS_CONSUMER_COLLATE_DOUBLE_SIDED_SUBDIR_NAME",
    "double-sided",
)

CONSUMER_COLLATE_DOUBLE_SIDED_TIFF_SUPPORT: Final[bool] = __get_boolean(
    "PAPERLESS_CONSUMER_COLLATE_DOUBLE_SIDED_TIFF_SUPPORT",
)

CONSUMER_PDF_RECOVERABLE_MIME_TYPES = ("application/octet-stream",)

OCR_PAGES = __get_optional_int("PAPERLESS_OCR_PAGES")

# The default language that tesseract will attempt to use when parsing
# documents.  It should be a 3-letter language code consistent with ISO 639.
OCR_LANGUAGE = os.getenv("PAPERLESS_OCR_LANGUAGE", "eng")

# OCRmyPDF --output-type options are available.
OCR_OUTPUT_TYPE = os.getenv("PAPERLESS_OCR_OUTPUT_TYPE", "pdfa")

# skip. redo, force
OCR_MODE = os.getenv("PAPERLESS_OCR_MODE", "skip")

OCR_SKIP_ARCHIVE_FILE = os.getenv("PAPERLESS_OCR_SKIP_ARCHIVE_FILE", "never")

OCR_IMAGE_DPI = __get_optional_int("PAPERLESS_OCR_IMAGE_DPI")

OCR_CLEAN = os.getenv("PAPERLESS_OCR_CLEAN", "clean")

OCR_DESKEW: Final[bool] = __get_boolean("PAPERLESS_OCR_DESKEW", "true")

OCR_ROTATE_PAGES: Final[bool] = __get_boolean("PAPERLESS_OCR_ROTATE_PAGES", "true")

OCR_ROTATE_PAGES_THRESHOLD: Final[float] = __get_float(
    "PAPERLESS_OCR_ROTATE_PAGES_THRESHOLD",
    12.0,
)

OCR_MAX_IMAGE_PIXELS: Final[int | None] = __get_optional_int(
    "PAPERLESS_OCR_MAX_IMAGE_PIXELS",
)

OCR_COLOR_CONVERSION_STRATEGY = os.getenv(
    "PAPERLESS_OCR_COLOR_CONVERSION_STRATEGY",
    "RGB",
)

OCR_USER_ARGS = os.getenv("PAPERLESS_OCR_USER_ARGS")

MAX_IMAGE_PIXELS: Final[int | None] = __get_optional_int(
    "PAPERLESS_MAX_IMAGE_PIXELS",
)

# GNUPG needs a home directory for some reason
GNUPG_HOME = os.getenv("HOME", "/tmp")

# Convert is part of the ImageMagick package
CONVERT_BINARY = os.getenv("PAPERLESS_CONVERT_BINARY", "convert")
CONVERT_TMPDIR = os.getenv("PAPERLESS_CONVERT_TMPDIR")
CONVERT_MEMORY_LIMIT = os.getenv("PAPERLESS_CONVERT_MEMORY_LIMIT")

GS_BINARY = os.getenv("PAPERLESS_GS_BINARY", "gs")


# Pre-2.x versions of Paperless stored your documents locally with GPG
# encryption, but that is no longer the default.  This behaviour is still
# available, but it must be explicitly enabled by setting
# `PAPERLESS_PASSPHRASE` in your environment or config file.  The default is to
# store these files unencrypted.
#
# Translation:
# * If you're a new user, you can safely ignore this setting.
# * If you're upgrading from 1.x, this must be set, OR you can run
#   `./manage.py change_storage_type gpg unencrypted` to decrypt your files,
#   after which you can unset this value.
PASSPHRASE = os.getenv("PAPERLESS_PASSPHRASE")

# Trigger a script after every successful document consumption?
PRE_CONSUME_SCRIPT = os.getenv("PAPERLESS_PRE_CONSUME_SCRIPT")
POST_CONSUME_SCRIPT = os.getenv("PAPERLESS_POST_CONSUME_SCRIPT")

# Specify the default date order (for autodetected dates)
DATE_ORDER = os.getenv("PAPERLESS_DATE_ORDER", "DMY")
FILENAME_DATE_ORDER = os.getenv("PAPERLESS_FILENAME_DATE_ORDER")

# Maximum number of dates taken from document start to end to show as suggestions for
# `created` date in the frontend. Duplicates are removed, which can result in
# fewer dates shown.
NUMBER_OF_SUGGESTED_DATES = __get_int("PAPERLESS_NUMBER_OF_SUGGESTED_DATES", 3)

# Specify the filename format for out files
FILENAME_FORMAT = os.getenv("PAPERLESS_FILENAME_FORMAT")

# If this is enabled, variables in filename format will resolve to
# empty-string instead of 'none'.
# Directories with 'empty names' are omitted, too.
FILENAME_FORMAT_REMOVE_NONE = __get_boolean(
    "PAPERLESS_FILENAME_FORMAT_REMOVE_NONE",
    "NO",
)

THUMBNAIL_FONT_NAME = os.getenv(
    "PAPERLESS_THUMBNAIL_FONT_NAME",
    "/usr/share/fonts/liberation/LiberationSerif-Regular.ttf",
)

# Tika settings
TIKA_ENABLED = __get_boolean("PAPERLESS_TIKA_ENABLED", "NO")
TIKA_ENDPOINT = os.getenv("PAPERLESS_TIKA_ENDPOINT", "http://localhost:9998")
TIKA_GOTENBERG_ENDPOINT = os.getenv(
    "PAPERLESS_TIKA_GOTENBERG_ENDPOINT",
    "http://localhost:3000",
)

if TIKA_ENABLED:
    INSTALLED_APPS.append("paperless_tika.apps.PaperlessTikaConfig")

AUDIT_LOG_ENABLED = __get_boolean("PAPERLESS_AUDIT_LOG_ENABLED", "true")
if AUDIT_LOG_ENABLED:
    INSTALLED_APPS.append("auditlog")
    MIDDLEWARE.append("auditlog.middleware.AuditlogMiddleware")


def _parse_ignore_dates(
    env_ignore: str,
    date_order: str = DATE_ORDER,
) -> set[datetime.datetime]:
    """
    If the PAPERLESS_IGNORE_DATES environment variable is set, parse the
    user provided string(s) into dates

    Args:
        env_ignore (str): The value of the environment variable, comma separated dates
        date_order (str, optional): The format of the date strings.
                                    Defaults to DATE_ORDER.

    Returns:
        Set[datetime.datetime]: The set of parsed date objects
    """
    import dateparser

    ignored_dates = set()
    for s in env_ignore.split(","):
        d = dateparser.parse(
            s,
            settings={
                "DATE_ORDER": date_order,
            },
        )
        if d:
            ignored_dates.add(d.date())
    return ignored_dates


# List dates that should be ignored when trying to parse date from document text
IGNORE_DATES: set[datetime.date] = set()

if os.getenv("PAPERLESS_IGNORE_DATES") is not None:
    IGNORE_DATES = _parse_ignore_dates(os.getenv("PAPERLESS_IGNORE_DATES"))

ENABLE_UPDATE_CHECK = os.getenv("PAPERLESS_ENABLE_UPDATE_CHECK", "default")
if ENABLE_UPDATE_CHECK != "default":
    ENABLE_UPDATE_CHECK = __get_boolean("PAPERLESS_ENABLE_UPDATE_CHECK")

APP_TITLE = os.getenv("PAPERLESS_APP_TITLE", None)
APP_LOGO = os.getenv("PAPERLESS_APP_LOGO", None)

###############################################################################
# Machine Learning                                                            #
###############################################################################


def _get_nltk_language_setting(ocr_lang: str) -> str | None:
    """
    Maps an ISO-639-1 language code supported by Tesseract into
    an optional NLTK language name.  This is the set of common supported
    languages for all the NLTK data used.

    Assumption: The primary language is first

    NLTK Languages:
      - https://www.nltk.org/api/nltk.stem.snowball.html#nltk.stem.snowball.SnowballStemmer
      - https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/tokenizers/punkt.zip
      - https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/stopwords.zip

    The common intersection between all languages in those 3 is handled here

    """
    ocr_lang = ocr_lang.split("+")[0]
    iso_code_to_nltk = {
        "dan": "danish",
        "nld": "dutch",
        "eng": "english",
        "fin": "finnish",
        "fra": "french",
        "deu": "german",
        "ita": "italian",
        "nor": "norwegian",
        "por": "portuguese",
        "rus": "russian",
        "spa": "spanish",
        "swe": "swedish",
    }

    return iso_code_to_nltk.get(ocr_lang)


NLTK_ENABLED: Final[bool] = __get_boolean("PAPERLESS_ENABLE_NLTK", "yes")

NLTK_LANGUAGE: str | None = _get_nltk_language_setting(OCR_LANGUAGE)

###############################################################################
# Email (SMTP) Backend                                                        #
###############################################################################

EMAIL_HOST: Final[str] = os.getenv("PAPERLESS_EMAIL_HOST", "localhost")
EMAIL_PORT: Final[int] = int(os.getenv("PAPERLESS_EMAIL_PORT", 25))
EMAIL_HOST_USER: Final[str] = os.getenv("PAPERLESS_EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD: Final[str] = os.getenv("PAPERLESS_EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL: Final[str] = os.getenv("PAPERLESS_EMAIL_FROM", EMAIL_HOST_USER)
EMAIL_USE_TLS: Final[bool] = __get_boolean("PAPERLESS_EMAIL_USE_TLS")
EMAIL_USE_SSL: Final[bool] = __get_boolean("PAPERLESS_EMAIL_USE_SSL")
EMAIL_SUBJECT_PREFIX: Final[str] = "[Paperless-ngx] "
EMAIL_TIMEOUT = 30.0
EMAIL_ENABLED = EMAIL_HOST != "localhost" or EMAIL_HOST_USER != ""
if DEBUG:  # pragma: no cover
    EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
    EMAIL_FILE_PATH = BASE_DIR / "sent_emails"

###############################################################################
# Email Preprocessors                                                         #
###############################################################################

EMAIL_GNUPG_HOME: Final[str | None] = os.getenv("PAPERLESS_EMAIL_GNUPG_HOME")
EMAIL_ENABLE_GPG_DECRYPTOR: Final[bool] = __get_boolean(
    "PAPERLESS_ENABLE_GPG_DECRYPTOR",
)


###############################################################################
# Soft Delete                                                                 #
###############################################################################
EMPTY_TRASH_DELAY = max(__get_int("PAPERLESS_EMPTY_TRASH_DELAY", 30), 1)


###############################################################################
# Oauth Email                                                                 #
###############################################################################
OAUTH_CALLBACK_BASE_URL = os.getenv("PAPERLESS_OAUTH_CALLBACK_BASE_URL")
GMAIL_OAUTH_CLIENT_ID = os.getenv("PAPERLESS_GMAIL_OAUTH_CLIENT_ID")
GMAIL_OAUTH_CLIENT_SECRET = os.getenv("PAPERLESS_GMAIL_OAUTH_CLIENT_SECRET")
GMAIL_OAUTH_ENABLED = bool(
    (OAUTH_CALLBACK_BASE_URL or PAPERLESS_URL)
    and GMAIL_OAUTH_CLIENT_ID
    and GMAIL_OAUTH_CLIENT_SECRET,
)
OUTLOOK_OAUTH_CLIENT_ID = os.getenv("PAPERLESS_OUTLOOK_OAUTH_CLIENT_ID")
OUTLOOK_OAUTH_CLIENT_SECRET = os.getenv("PAPERLESS_OUTLOOK_OAUTH_CLIENT_SECRET")
OUTLOOK_OAUTH_ENABLED = bool(
    (OAUTH_CALLBACK_BASE_URL or PAPERLESS_URL)
    and OUTLOOK_OAUTH_CLIENT_ID
    and OUTLOOK_OAUTH_CLIENT_SECRET,
)
