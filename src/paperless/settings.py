import json
import math
import multiprocessing
import os
import re

from dotenv import load_dotenv

# Tap paperless.conf if it's available
if os.path.exists("../paperless.conf"):
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
os.environ['OMP_THREAD_LIMIT'] = "1"


def __get_boolean(key, default="NO"):
    """
    Return a boolean value based on whatever the user has supplied in the
    environment based on whether the value "looks like" it's True or not.
    """
    return bool(os.getenv(key, default).lower() in ("yes", "y", "1", "t", "true"))


# NEVER RUN WITH DEBUG IN PRODUCTION.
DEBUG = __get_boolean("PAPERLESS_DEBUG", "NO")


###############################################################################
# Directories                                                                 #
###############################################################################

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STATIC_ROOT = os.getenv("PAPERLESS_STATICDIR", os.path.join(BASE_DIR, "..", "static"))

MEDIA_ROOT = os.getenv('PAPERLESS_MEDIA_ROOT', os.path.join(BASE_DIR, "..", "media"))
ORIGINALS_DIR = os.path.join(MEDIA_ROOT, "documents", "originals")
THUMBNAIL_DIR = os.path.join(MEDIA_ROOT, "documents", "thumbnails")

DATA_DIR = os.getenv('PAPERLESS_DATA_DIR', os.path.join(BASE_DIR, "..", "data"))
INDEX_DIR = os.path.join(DATA_DIR, "index")
MODEL_FILE = os.path.join(DATA_DIR, "classification_model.pickle")

CONSUMPTION_DIR = os.getenv("PAPERLESS_CONSUMPTION_DIR", os.path.join(BASE_DIR, "..", "consume"))

# This will be created if it doesn't exist
SCRATCH_DIR = os.getenv("PAPERLESS_SCRATCH_DIR", "/tmp/paperless")

###############################################################################
# Application Definition                                                      #
###############################################################################

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
    "django_filters",

    "django_q",

]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.BasicAuthentication',
        'rest_framework.authentication.SessionAuthentication'
    ]
}

if DEBUG:
    REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'].append(
        'paperless.auth.AngularApiAuthenticationOverride'
    )

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'paperless.urls'

FORCE_SCRIPT_NAME = os.getenv("PAPERLESS_FORCE_SCRIPT_NAME")

WSGI_APPLICATION = 'paperless.wsgi.application'

STATIC_URL = os.getenv("PAPERLESS_STATIC_URL", "/static/")

# what is this used for?
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

###############################################################################
# Security                                                                    #
###############################################################################

AUTO_LOGIN_USERNAME = os.getenv("PAPERLESS_AUTO_LOGIN_USERNAME")

if AUTO_LOGIN_USERNAME:
    _index = MIDDLEWARE.index('django.contrib.auth.middleware.AuthenticationMiddleware')
    # This overrides everything the auth middleware is doing but still allows
    # regular login in case the provided user does not exist.
    MIDDLEWARE.insert(_index+1, 'paperless.auth.AutoLoginMiddleware')


if DEBUG:
    X_FRAME_OPTIONS = ''
    # this should really be 'allow-from uri' but its not supported in any mayor
    # browser.
else:
    X_FRAME_OPTIONS = 'SAMEORIGIN'

# We allow CORS from localhost:8080
CORS_ALLOWED_ORIGINS = tuple(os.getenv("PAPERLESS_CORS_ALLOWED_HOSTS", "http://localhost:8000").split(","))

if DEBUG:
    # Allow access from the angular development server during debugging
    CORS_ALLOWED_ORIGINS += ('http://localhost:4200',)

# The secret key has a default that should be fine so long as you're hosting
# Paperless on a closed network.  However, if you're putting this anywhere
# public, you should change the key to something unique and verbose.
SECRET_KEY = os.getenv(
    "PAPERLESS_SECRET_KEY",
    "e11fl1oa-*ytql8p)(06fbj4ukrlo+n7k&q5+$1md7i+mge=ee"
)

_allowed_hosts = os.getenv("PAPERLESS_ALLOWED_HOSTS")
if _allowed_hosts:
    ALLOWED_HOSTS = _allowed_hosts.split(",")
else:
    ALLOWED_HOSTS = ["*"]

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Disable Django's artificial limit on the number of form fields to submit at
# once. This is a protection against overloading the server, but since this is
# a self-hosted sort of gig, the benefits of being able to mass-delete a tonne
# of log entries outweight the benefits of such a safeguard.

DATA_UPLOAD_MAX_NUMBER_FIELDS = None

###############################################################################
# Database                                                                    #
###############################################################################

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(
            DATA_DIR,
            "db.sqlite3"
        )
    }
}

if os.getenv("PAPERLESS_DBHOST"):
    # Have sqlite available as a second option for management commands
    # This is important when migrating to/from sqlite
    DATABASES['sqlite'] = DATABASES['default'].copy()

    DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "HOST": os.getenv("PAPERLESS_DBHOST"),
        "NAME": os.getenv("PAPERLESS_DBNAME", "paperless"),
        "USER": os.getenv("PAPERLESS_DBUSER", "paperless"),
        "PASSWORD": os.getenv("PAPERLESS_DBPASS", "paperless"),
    }
    if os.getenv("PAPERLESS_DBPORT"):
        DATABASES["default"]["PORT"] = os.getenv("PAPERLESS_DBPORT")

###############################################################################
# Internationalization                                                        #
###############################################################################

LANGUAGE_CODE = 'en-us'

TIME_ZONE = os.getenv("PAPERLESS_TIME_ZONE", "UTC")

USE_I18N = True

USE_L10N = True

USE_TZ = True

###############################################################################
# Logging                                                                     #
###############################################################################

DISABLE_DBHANDLER = __get_boolean("PAPERLESS_DISABLE_DBHANDLER")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "dbhandler": {
            "class": "documents.loggers.PaperlessHandler",
        },
        "streamhandler": {
            "class": "logging.StreamHandler"
        }
    },
    "loggers": {
        "documents": {
            "handlers": ["dbhandler", "streamhandler"],
            "level": "DEBUG"
        },
        "paperless_mail": {
            "handlers": ["dbhandler", "streamhandler"],
            "level": "DEBUG"
        },
        "paperless_tesseract": {
            "handlers": ["dbhandler", "streamhandler"],
            "level": "DEBUG"
        },
    },
}

###############################################################################
# Task queue                                                                  #
###############################################################################


# Sensible defaults for multitasking:
# use a fair balance between worker processes and threads epr worker so that
# both consuming many documents in parallel and consuming large documents is
# reasonably fast.
# Favors threads per worker on smaller systems and never exceeds cpu_count()
# in total.

def default_task_workers():
    try:
        return max(
            math.floor(math.sqrt(multiprocessing.cpu_count())),
            1
        )
    except NotImplementedError:
        return 1


TASK_WORKERS = int(os.getenv("PAPERLESS_TASK_WORKERS", default_task_workers()))

Q_CLUSTER = {
    'name': 'paperless',
    'catch_up': False,
    'workers': TASK_WORKERS,
    'redis': os.getenv("PAPERLESS_REDIS", "redis://localhost:6379")
}


def default_threads_per_worker():
    try:
        return max(
            math.floor(multiprocessing.cpu_count() / TASK_WORKERS),
            1
        )
    except NotImplementedError:
        return 1


THREADS_PER_WORKER = os.getenv("PAPERLESS_THREADS_PER_WORKER", default_threads_per_worker())

###############################################################################
# Paperless Specific Settings                                                 #
###############################################################################

CONSUMER_POLLING = int(os.getenv("PAPERLESS_CONSUMER_POLLING", 0))

CONSUMER_DELETE_DUPLICATES = __get_boolean("PAPERLESS_CONSUMER_DELETE_DUPLICATES")

# Consume from subdirectories of CONSUMPTION_DIR as well
CONSUMER_RECURSIVE = __get_boolean("PAPERLESS_CONSUMER_RECURSIVE")

# Set the names of subdirectories as tags for consumed files.
# E.g. $CONSUMPTION_DIR/foo/bar/file.pdf will add the tags "foo" and "bar" to
# the consumed file.
# PAPERLESS_CONSUMER_RECURSIVE must be enabled for this to work.
CONSUMER_SUBDIRS_AS_TAGS = __get_boolean("PAPERLESS_CONSUMER_SUBDIRS_AS_TAGS")

OPTIMIZE_THUMBNAILS = __get_boolean("PAPERLESS_OPTIMIZE_THUMBNAILS", "true")

OCR_PAGES = int(os.getenv('PAPERLESS_OCR_PAGES', 0))

# The default language that tesseract will attempt to use when parsing
# documents.  It should be a 3-letter language code consistent with ISO 639.
OCR_LANGUAGE = os.getenv("PAPERLESS_OCR_LANGUAGE", "eng")


# OCR all documents?
OCR_ALWAYS = __get_boolean("PAPERLESS_OCR_ALWAYS", "false")

# GNUPG needs a home directory for some reason
GNUPG_HOME = os.getenv("HOME", "/tmp")

# Convert is part of the ImageMagick package
CONVERT_BINARY = os.getenv("PAPERLESS_CONVERT_BINARY", "convert")
CONVERT_TMPDIR = os.getenv("PAPERLESS_CONVERT_TMPDIR")
CONVERT_MEMORY_LIMIT = os.getenv("PAPERLESS_CONVERT_MEMORY_LIMIT")
CONVERT_DENSITY = int(os.getenv("PAPERLESS_CONVERT_DENSITY", 300))

GS_BINARY = os.getenv("PAPERLESS_GS_BINARY", "gs")
OPTIPNG_BINARY = os.getenv("PAPERLESS_OPTIPNG_BINARY", "optipng")
UNPAPER_BINARY = os.getenv("PAPERLESS_UNPAPER_BINARY", "unpaper")


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

# Transformations applied before filename parsing
FILENAME_PARSE_TRANSFORMS = []
for t in json.loads(os.getenv("PAPERLESS_FILENAME_PARSE_TRANSFORMS", "[]")):
    FILENAME_PARSE_TRANSFORMS.append((re.compile(t["pattern"]), t["repl"]))

# TODO: this should not have a prefix.
# Specify the filename format for out files
PAPERLESS_FILENAME_FORMAT = os.getenv("PAPERLESS_FILENAME_FORMAT")
