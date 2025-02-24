# Configuration

Paperless provides a wide range of customizations. Depending on how you
run paperless, these settings have to be defined in different places.

Certain configuration options may be set via the UI. This currently includes
common [OCR](#ocr) related settings and some frontend settings. If set, these will take
preference over the settings via environment variables. If not set, the environment setting
or applicable default will be utilized instead.

-   If you run paperless on docker, `paperless.conf` is not used.
    Rather, configure paperless by copying necessary options to
    `docker-compose.env`.

-   If you are running paperless on anything else, paperless will search
    for the configuration file in these locations and use the first one
    it finds:
    -   The environment variable `PAPERLESS_CONFIGURATION_PATH`
    -   `/path/to/paperless/paperless.conf`
    -   `/etc/paperless.conf`
    -   `/usr/local/etc/paperless.conf`

## Required services

### Redis Broker

#### [`PAPERLESS_REDIS=<url>`](#PAPERLESS_REDIS) {#PAPERLESS_REDIS}

: This is required for processing scheduled tasks such as email
fetching, index optimization and for training the automatic document
matcher.

    -   If your Redis server needs login credentials PAPERLESS_REDIS =
        `redis://<username>:<password>@<host>:<port>`
    -   With the requirepass option PAPERLESS_REDIS =
        `redis://:<password>@<host>:<port>`
    -   To include the redis database index PAPERLESS_REDIS =
        `redis://<username>:<password>@<host>:<port>/<DBIndex>`

    [More information on securing your Redis
    Instance](https://redis.io/docs/latest/operate/oss_and_stack/management/security).

    Defaults to `redis://localhost:6379`.

#### [`PAPERLESS_REDIS_PREFIX=<prefix>`](#PAPERLESS_REDIS_PREFIX) {#PAPERLESS_REDIS_PREFIX}

: Prefix to be used in Redis for keys and channels. Useful for sharing one Redis server among multiple Paperless instances.

    Defaults to no prefix.

### Database

#### [`PAPERLESS_DBENGINE=<engine_name>`](#PAPERLESS_DBENGINE) {#PAPERLESS_DBENGINE}

: Optional, gives the ability to choose Postgres or MariaDB for
database engine. Available options are `postgresql` and
`mariadb`.

    Default is `postgresql`.

    !!! warning

        Using MariaDB comes with some caveats. See [MySQL Caveats](advanced_usage.md#mysql-caveats).

#### [`PAPERLESS_DBHOST=<hostname>`](#PAPERLESS_DBHOST) {#PAPERLESS_DBHOST}

: By default, sqlite is used as the database backend. This can be
changed here.

    Set PAPERLESS_DBHOST and another database will be used instead of
    sqlite.

#### [`PAPERLESS_DBPORT=<port>`](#PAPERLESS_DBPORT) {#PAPERLESS_DBPORT}

: Adjust port if necessary.

    Default is 5432.

#### [`PAPERLESS_DBNAME=<name>`](#PAPERLESS_DBNAME) {#PAPERLESS_DBNAME}

: Database name in PostgreSQL or MariaDB.

    Defaults to "paperless".

#### [`PAPERLESS_DBUSER=<name>`](#PAPERLESS_DBUSER) {#PAPERLESS_DBUSER}

: Database user in PostgreSQL or MariaDB.

    Defaults to "paperless".

#### [`PAPERLESS_DBPASS=<password>`](#PAPERLESS_DBPASS) {#PAPERLESS_DBPASS}

: Database password for PostgreSQL or MariaDB.

    Defaults to "paperless".

#### [`PAPERLESS_DBSSLMODE=<mode>`](#PAPERLESS_DBSSLMODE) {#PAPERLESS_DBSSLMODE}

: SSL mode to use when connecting to PostgreSQL or MariaDB.

    See [the official documentation about
    sslmode for PostgreSQL](https://www.postgresql.org/docs/current/libpq-ssl.html).

    See [the official documentation about
    sslmode for MySQL and MariaDB](https://dev.mysql.com/doc/refman/8.0/en/connection-options.html#option_general_ssl-mode).

    *Note*: SSL mode values differ between PostgreSQL and MariaDB.

    Default is `prefer` for PostgreSQL and `PREFERRED` for MariaDB.

#### [`PAPERLESS_DBSSLROOTCERT=<ca-path>`](#PAPERLESS_DBSSLROOTCERT) {#PAPERLESS_DBSSLROOTCERT}

: SSL root certificate path

    See [the official documentation about
    sslmode for PostgreSQL](https://www.postgresql.org/docs/current/libpq-ssl.html).
    Changes path of `root.crt`.

    See [the official documentation about
    sslmode for MySQL and MariaDB](https://dev.mysql.com/doc/refman/8.0/en/connection-options.html#option_general_ssl-ca).

    Defaults to unset, using the documented path in the home directory.

#### [`PAPERLESS_DBSSLCERT=<client-cert-path>`](#PAPERLESS_DBSSLCERT) {#PAPERLESS_DBSSLCERT}

: SSL client certificate path

    See [the official documentation about
    sslmode for PostgreSQL](https://www.postgresql.org/docs/current/libpq-ssl.html).

    See [the official documentation about
    sslmode for MySQL and MariaDB](https://dev.mysql.com/doc/refman/8.0/en/connection-options.html#option_general_ssl-cert).

    Changes path of `postgresql.crt`.

    Defaults to unset, using the documented path in the home directory.

#### [`PAPERLESS_DBSSLKEY=<client-cert-key>`](#PAPERLESS_DBSSLKEY) {#PAPERLESS_DBSSLKEY}

: SSL client key path

    See [the official documentation about
    sslmode for PostgreSQL](https://www.postgresql.org/docs/current/libpq-ssl.html).

    See [the official documentation about
    sslmode for MySQL and MariaDB](https://dev.mysql.com/doc/refman/8.0/en/connection-options.html#option_general_ssl-key).

    Changes path of `postgresql.key`.

    Defaults to unset, using the documented path in the home directory.

#### [`PAPERLESS_DB_TIMEOUT=<int>`](#PAPERLESS_DB_TIMEOUT) {#PAPERLESS_DB_TIMEOUT}

: Amount of time for a database connection to wait for the database to
unlock. Mostly applicable for sqlite based installation. Consider changing
to postgresql if you are having concurrency problems with sqlite.

    Defaults to unset, keeping the Django defaults.

## Optional Services

### Tika {#tika}

Paperless can make use of [Tika](https://tika.apache.org/) and
[Gotenberg](https://gotenberg.dev/) for parsing and converting
"Office" documents (such as ".doc", ".xlsx" and ".odt").
Tika and Gotenberg are also needed to allow parsing of E-Mails (.eml).

If you wish to use this, you must provide a Tika server and a Gotenberg server,
configure their endpoints, and enable the feature.

#### [`PAPERLESS_TIKA_ENABLED=<bool>`](#PAPERLESS_TIKA_ENABLED) {#PAPERLESS_TIKA_ENABLED}

: Enable (or disable) the Tika parser.

    Defaults to false.

#### [`PAPERLESS_TIKA_ENDPOINT=<url>`](#PAPERLESS_TIKA_ENDPOINT) {#PAPERLESS_TIKA_ENDPOINT}

: Set the endpoint URL where Paperless can reach your Tika server.

    Defaults to "<http://localhost:9998>".

#### [`PAPERLESS_TIKA_GOTENBERG_ENDPOINT=<url>`](#PAPERLESS_TIKA_GOTENBERG_ENDPOINT) {#PAPERLESS_TIKA_GOTENBERG_ENDPOINT}

: Set the endpoint URL where Paperless can reach your Gotenberg server.

    Defaults to "<http://localhost:3000>".

If you run paperless on docker, you can add those services to the
Docker Compose file (see the provided
[`docker-compose.sqlite-tika.yml`](https://github.com/paperless-ngx/paperless-ngx/blob/main/docker/compose/docker-compose.sqlite-tika.yml)
file for reference).

Add all three configuration parameters to your configuration. If using
Docker, this may be the `environment` key of the webserver or a
`docker-compose.env` file. Bare metal installations may have a `.conf` file
containing the configuration parameters. Be sure to use the correct format
and watch out for indentation if editing the YAML file.

### Email Parsing

#### [`PAPERLESS_EMAIL_PARSE_DEFAULT_LAYOUT=<int>`(#PAPERLESS_EMAIL_PARSE_DEFAULT_LAYOUT) {#PAPERLESS_EMAIL_PARSE_DEFAULT_LAYOUT}

: The default layout to use for emails that are consumed as documents. Must be one of the integer choices below. Note that mail
rules can specify this setting, thus this fallback is used for the default selection and for .eml files consumed by other means.

    - `1` = Text, then HTML
    - `2` = HTML, then text
    - `3` = HTML only
    - `4` = Text only

## Paths and folders

#### [`PAPERLESS_CONSUMPTION_DIR=<path>`](#PAPERLESS_CONSUMPTION_DIR) {#PAPERLESS_CONSUMPTION_DIR}

: This is where your documents should go to be consumed. Make sure that
it exists and that the user running the paperless service can
read/write its contents before you start Paperless.

    Don't change this when using docker, as it only changes the path
    within the container. Change the local consumption directory in the
    docker-compose.yml file instead.

    Defaults to "../consume/", relative to the "src" directory.

#### [`PAPERLESS_DATA_DIR=<path>`](#PAPERLESS_DATA_DIR) {#PAPERLESS_DATA_DIR}

: This is where paperless stores all its data (search index, SQLite
database, classification model, etc).

    Defaults to "../data/", relative to the "src" directory.

#### [`PAPERLESS_EMPTY_TRASH_DIR=<path>`](#PAPERLESS_EMPTY_TRASH_DIR) {#PAPERLESS_EMPTY_TRASH_DIR}

: When documents are deleted (e.g. after emptying the trash) the original files will be moved here
instead of being removed from the filesystem. Only the original version is kept.

    This must be writeable by the user running paperless. When running
    inside docker, ensure that this path is within a permanent volume
    (such as "../media/trash") so it won't get lost on upgrades.

    Note that the directory must exist prior to using this setting.

    Defaults to empty (i.e. really delete files).

    This setting was previously named PAPERLESS_TRASH_DIR.

#### [`PAPERLESS_MEDIA_ROOT=<path>`](#PAPERLESS_MEDIA_ROOT) {#PAPERLESS_MEDIA_ROOT}

: This is where your documents and thumbnails are stored.

    You can set this and PAPERLESS_DATA_DIR to the same folder to have
    paperless store all its data within the same volume.

    Defaults to "../media/", relative to the "src" directory.

#### [`PAPERLESS_STATICDIR=<path>`](#PAPERLESS_STATICDIR) {#PAPERLESS_STATICDIR}

: Override the default STATIC_ROOT here. This is where all static
files created using "collectstatic" manager command are stored.

    Unless you're doing something fancy, there is no need to override
    this.  If this is changed, you may need to run
    `collectstatic` again.

    Defaults to "../static/", relative to the "src" directory.

#### [`PAPERLESS_FILENAME_FORMAT=<format>`](#PAPERLESS_FILENAME_FORMAT) {#PAPERLESS_FILENAME_FORMAT}

: Changes the filenames paperless uses to store documents in the media
directory. See [File name handling](advanced_usage.md#file-name-handling) for details.

    Default is none, which disables this feature.

#### [`PAPERLESS_FILENAME_FORMAT_REMOVE_NONE=<bool>`](#PAPERLESS_FILENAME_FORMAT_REMOVE_NONE) {#PAPERLESS_FILENAME_FORMAT_REMOVE_NONE}

: Tells paperless to replace placeholders in
`PAPERLESS_FILENAME_FORMAT` that would resolve to
'none' to be omitted from the resulting filename. This also holds
true for directory names. See [File name handling](advanced_usage.md#empty-placeholders) for
details.

    Defaults to `false` which disables this feature.

#### [`PAPERLESS_LOGGING_DIR=<path>`](#PAPERLESS_LOGGING_DIR) {#PAPERLESS_LOGGING_DIR}

: This is where paperless will store log files.

    Defaults to `PAPERLESS_DATA_DIR/log/`.

#### [`PAPERLESS_NLTK_DIR=<path>`](#PAPERLESS_NLTK_DIR) {#PAPERLESS_NLTK_DIR}

: This is where paperless will search for the data required for NLTK
processing, if you are using it. If you are using the Docker image,
this should not be changed, as the data is included in the image
already.

Previously, the location defaulted to `PAPERLESS_DATA_DIR/nltk`.
Unless you are using this in a bare metal install or other setup,
this folder is no longer needed and can be removed manually.

Defaults to `/usr/share/nltk_data`

#### [`PAPERLESS_MODEL_FILE=<path>`](#PAPERLESS_MODEL_FILE) {#PAPERLESS_MODEL_FILE}

: This is where paperless will store the classification model.

    Defaults to `PAPERLESS_DATA_DIR/classification_model.pickle`.

## Logging

#### [`PAPERLESS_LOGROTATE_MAX_SIZE=<num>`](#PAPERLESS_LOGROTATE_MAX_SIZE) {#PAPERLESS_LOGROTATE_MAX_SIZE}

: Maximum file size for log files before they are rotated, in bytes.

    Defaults to 1 MiB.

#### [`PAPERLESS_LOGROTATE_MAX_BACKUPS=<num>`](#PAPERLESS_LOGROTATE_MAX_BACKUPS) {#PAPERLESS_LOGROTATE_MAX_BACKUPS}

: Number of rotated log files to keep.

    Defaults to 20.

## Hosting & Security {#hosting-and-security}

#### [`PAPERLESS_SECRET_KEY=<key>`](#PAPERLESS_SECRET_KEY) {#PAPERLESS_SECRET_KEY}

: Paperless uses this to make session tokens. If you expose paperless
on the internet, you need to change this, since the default secret
is well known.

    Use any sequence of characters. The more, the better. You don't
    need to remember this. Just face-roll your keyboard.

    Default is listed in the file `src/paperless/settings.py`.

#### [`PAPERLESS_URL=<url>`](#PAPERLESS_URL) {#PAPERLESS_URL}

: This setting can be used to set the three options below
(ALLOWED_HOSTS, CORS_ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS). If the
other options are set the values will be combined with this one. Do
not include a trailing slash. E.g. <https://paperless.domain.com>

    Defaults to empty string, leaving the other settings unaffected.

    !!! note

        This value cannot contain a path (e.g. domain.com/path), even if
        you are installing paperless-ngx at a subpath.

#### [`PAPERLESS_CSRF_TRUSTED_ORIGINS=<comma-separated-list>`](#PAPERLESS_CSRF_TRUSTED_ORIGINS) {#PAPERLESS_CSRF_TRUSTED_ORIGINS}

: A list of trusted origins for unsafe requests (e.g. POST). As of
Django 4.0 this is required to access the Django admin via the web.
See the [Django project documentation on the settings](https://docs.djangoproject.com/en/4.1/ref/settings/#csrf-trusted-origins)

    Can also be set using PAPERLESS_URL (see above).

    Defaults to empty string, which does not add any origins to the
    trusted list.

#### [`PAPERLESS_ALLOWED_HOSTS=<comma-separated-list>`](#PAPERLESS_ALLOWED_HOSTS) {#PAPERLESS_ALLOWED_HOSTS}

: If you're planning on putting Paperless on the open internet, then
you really should set this value to the domain name you're using.
Failing to do so leaves you open to HTTP host header attacks.
You can read more about this in [the Django project's documentation](https://docs.djangoproject.com/en/4.1/topics/security/#host-header-validation)

    Just remember that this is a comma-separated list, so
    "example.com" is fine, as is "example.com,www.example.com", but
    NOT " example.com" or "example.com,"

    Can also be set using PAPERLESS_URL (see above).

    "localhost" is always allowed for docker healthcheck

    Defaults to "\*", which is all hosts.

#### [`PAPERLESS_CORS_ALLOWED_HOSTS=<comma-separated-list>`](#PAPERLESS_CORS_ALLOWED_HOSTS) {#PAPERLESS_CORS_ALLOWED_HOSTS}

: You need to add your servers to the list of allowed hosts that can
do CORS calls. Set this to your public domain name.

    Can also be set using PAPERLESS_URL (see above).

    Defaults to "<http://localhost:8000>".

#### [`PAPERLESS_TRUSTED_PROXIES=<comma-separated-list>`](#PAPERLESS_TRUSTED_PROXIES) {#PAPERLESS_TRUSTED_PROXIES}

: This may be needed to prevent IP address spoofing if you are using e.g.
fail2ban with log entries for failed authorization attempts. Value should be
IP address(es).

    Defaults to empty string.

#### [`PAPERLESS_FORCE_SCRIPT_NAME=<path>`](#PAPERLESS_FORCE_SCRIPT_NAME) {#PAPERLESS_FORCE_SCRIPT_NAME}

: To host paperless under a subpath url like example.com/paperless you
set this value to /paperless. No trailing slash!

    Defaults to none, which hosts paperless at "/".

#### [`PAPERLESS_STATIC_URL=<path>`](#PAPERLESS_STATIC_URL) {#PAPERLESS_STATIC_URL}

: Override the STATIC_URL here. Unless you're hosting Paperless off a
subdomain like /paperless/, you probably don't need to change this.
If you do change it, be sure to include the trailing slash.

    Defaults to "/static/".

    !!! note

        When hosting paperless behind a reverse proxy like Traefik or Nginx
        at a subpath e.g. example.com/paperlessngx you will also need to set
        `PAPERLESS_FORCE_SCRIPT_NAME` (see above).

#### [`PAPERLESS_AUTO_LOGIN_USERNAME=<username>`](#PAPERLESS_AUTO_LOGIN_USERNAME) {#PAPERLESS_AUTO_LOGIN_USERNAME}

: Specify a username here so that paperless will automatically perform
login with the selected user.

    !!! danger

        Do not use this when exposing paperless on the internet. There are
        no checks in place that would prevent you from doing this.

    Defaults to none, which disables this feature.

#### [`PAPERLESS_ADMIN_USER=<username>`](#PAPERLESS_ADMIN_USER) {#PAPERLESS_ADMIN_USER}

: If this environment variable is specified, Paperless automatically
creates a superuser with the provided username at start. This is
useful in cases where you can not run the
`createsuperuser` command separately, such as Kubernetes
or AWS ECS.

    Requires PAPERLESS_ADMIN_PASSWORD be set.

    !!! note

        This will not change an existing \[super\]user's password, nor will
        it recreate a user that already exists. You can leave this
        throughout the lifecycle of the containers.

#### [`PAPERLESS_ADMIN_MAIL=<email>`](#PAPERLESS_ADMIN_MAIL) {#PAPERLESS_ADMIN_MAIL}

: (Optional) Specify superuser email address. Only used when
PAPERLESS_ADMIN_USER is set.

    Defaults to `root@localhost`.

#### [`PAPERLESS_ADMIN_PASSWORD=<password>`](#PAPERLESS_ADMIN_PASSWORD) {#PAPERLESS_ADMIN_PASSWORD}

: Only used when PAPERLESS_ADMIN_USER is set. This will
be the password of the automatically created superuser.

#### [`PAPERLESS_COOKIE_PREFIX=<str>`](#PAPERLESS_COOKIE_PREFIX) {#PAPERLESS_COOKIE_PREFIX}

: Specify a prefix that is added to the cookies used by paperless to
identify the currently logged in user. This is useful for when
you're running two instances of paperless on the same host.

    After changing this, you will have to login again.

    Defaults to `""`, which does not alter the cookie names.

#### [`PAPERLESS_ENABLE_HTTP_REMOTE_USER=<bool>`](#PAPERLESS_ENABLE_HTTP_REMOTE_USER) {#PAPERLESS_ENABLE_HTTP_REMOTE_USER}

: Allows authentication via HTTP_REMOTE_USER which is used by some SSO
applications.

    !!! warning

        This will allow authentication by simply adding a
        `Remote-User: <username>` header to a request. Use with care! You
        especially *must* ensure that any such header is not passed from
        external requests to your reverse-proxy to paperless (that would
        effectively bypass all authentication).

        If you're exposing paperless to the internet directly (i.e.
        without a reverse proxy), do not use this.

        Also see the warning [in the official documentation](https://docs.djangoproject.com/en/4.1/howto/auth-remote-user/#configuration).

    Defaults to "false" which disables this feature.

#### [`PAPERLESS_ENABLE_HTTP_REMOTE_USER_API=<bool>`](#PAPERLESS_ENABLE_HTTP_REMOTE_USER_API) {#PAPERLESS_ENABLE_HTTP_REMOTE_USER_API}

: Allows authentication via HTTP_REMOTE_USER directly against the API

    !!! warning

        See the warning above about securing your installation when using remote user header authentication. This setting is separate from
        `PAPERLESS_ENABLE_HTTP_REMOTE_USER` to avoid introducing a security vulnerability to existing reverse proxy setups. As above,
        ensure that your reverse proxy does not simply pass the `Remote-User` header from the internet to paperless.

    Defaults to "false" which disables this feature.

#### [`PAPERLESS_HTTP_REMOTE_USER_HEADER_NAME=<str>`](#PAPERLESS_HTTP_REMOTE_USER_HEADER_NAME) {#PAPERLESS_HTTP_REMOTE_USER_HEADER_NAME}

: If "PAPERLESS_ENABLE_HTTP_REMOTE_USER" or `PAPERLESS_ENABLE_HTTP_REMOTE_USER_API` are enabled, this
property allows to customize the name of the HTTP header from which
the authenticated username is extracted. Values are in terms of
[HttpRequest.META](https://docs.djangoproject.com/en/4.1/ref/request-response/#django.http.HttpRequest.META).
Thus, the configured value must start with `HTTP*`
followed by the normalized actual header name.

    Defaults to "HTTP_REMOTE_USER".

#### [`PAPERLESS_LOGOUT_REDIRECT_URL=<str>`](#PAPERLESS_LOGOUT_REDIRECT_URL) {#PAPERLESS_LOGOUT_REDIRECT_URL}

: URL to redirect the user to after a logout. This can be used
together with PAPERLESS_ENABLE_HTTP_REMOTE_USER and SSO to
redirect the user back to the SSO application's logout page to
complete the logout process.

    Defaults to None, which disables this feature.

#### [`PAPERLESS_USE_X_FORWARD_HOST=<bool>`](#PAPERLESS_USE_X_FORWARD_HOST) {#PAPERLESS_USE_X_FORWARD_HOST}

: Configures the Django setting [USE_X_FORWARDED_HOST](https://docs.djangoproject.com/en/4.2/ref/settings/#use-x-forwarded-host)
which may be needed for hosting behind a proxy.

    Defaults to False

#### [`PAPERLESS_USE_X_FORWARD_PORT=<bool>`](#PAPERLESS_USE_X_FORWARD_PORT) {#PAPERLESS_USE_X_FORWARD_PORT}

: Configures the Django setting [USE_X_FORWARDED_PORT](https://docs.djangoproject.com/en/4.2/ref/settings/#use-x-forwarded-port)
which may be needed for hosting behind a proxy.

    Defaults to False

#### [`PAPERLESS_PROXY_SSL_HEADER=<json-list>`](#PAPERLESS_PROXY_SSL_HEADER) {#PAPERLESS_PROXY_SSL_HEADER}

: Configures the Django setting [SECURE_PROXY_SSL_HEADER](https://docs.djangoproject.com/en/4.2/ref/settings/#secure-proxy-ssl-header)
which may be needed for hosting behind a proxy. The two values in the list will form the tuple of
HTTP header/value expected by Django, eg `'["HTTP_X_FORWARDED_PROTO", "https"]'`.

    Defaults to None

!!! warning

    Settings this value has security implications.  Read the Django documentation
    and be sure you understand its usage before setting it.

#### [`PAPERLESS_EMAIL_CERTIFICATE_LOCATION=<path>`](#PAPERLESS_EMAIL_CERTIFICATE_LOCATION) {#PAPERLESS_EMAIL_CERTIFICATE_LOCATION}

: Configures an additional SSL certificate file containing a [certificate](https://docs.python.org/3/library/ssl.html#certificates)
or certificate chain which should be trusted for validating SSL connections against mail providers.
This is for use with self-signed certificates against local IMAP servers.

    Defaults to None.

!!! warning

    Settings this value has security implications for the security of your email.
    Understand what it does and be sure you need to before setting.

### Authentication & SSO {#authentication}

#### [`PAPERLESS_ACCOUNT_ALLOW_SIGNUPS=<bool>`](#PAPERLESS_ACCOUNT_ALLOW_SIGNUPS) {#PAPERLESS_ACCOUNT_ALLOW_SIGNUPS}

: Allow users to signup for a new Paperless-ngx account.

    Defaults to False

#### [`PAPERLESS_ACCOUNT_DEFAULT_GROUPS=<comma-separated-list>`](#PAPERLESS_ACCOUNT_DEFAULT_GROUPS) {#PAPERLESS_ACCOUNT_DEFAULT_GROUPS}

: A list of group names that users will be added to when they sign up for a new account. Groups listed here must already exist.

    Defaults to None

#### [`PAPERLESS_SOCIALACCOUNT_PROVIDERS=<json>`](#PAPERLESS_SOCIALACCOUNT_PROVIDERS) {#PAPERLESS_SOCIALACCOUNT_PROVIDERS}

: This variable is used to setup login and signup via social account providers which are compatible with django-allauth.
See the corresponding [django-allauth documentation](https://docs.allauth.org/en/latest/socialaccount/providers/index.html)
for a list of provider configurations. You will also need to include the relevant Django 'application' inside the
[PAPERLESS_APPS](#PAPERLESS_APPS) setting to activate that specific authentication provider (e.g. `allauth.socialaccount.providers.openid_connect` for the [OIDC Connect provider](https://docs.allauth.org/en/latest/socialaccount/providers/openid_connect.html)).

    Defaults to None, which does not enable any third party authentication systems.

#### [`PAPERLESS_SOCIAL_AUTO_SIGNUP=<bool>`](#PAPERLESS_SOCIAL_AUTO_SIGNUP) {#PAPERLESS_SOCIAL_AUTO_SIGNUP}

: Attempt to signup the user using retrieved email, username etc from the third party authentication
system. See the corresponding
[django-allauth documentation](https://docs.allauth.org/en/latest/socialaccount/configuration.html)

    Defaults to False

#### [`PAPERLESS_SOCIALACCOUNT_ALLOW_SIGNUPS=<bool>`](#PAPERLESS_SOCIALACCOUNT_ALLOW_SIGNUPS) {#PAPERLESS_SOCIALACCOUNT_ALLOW_SIGNUPS}

: Allow users to signup for a new Paperless-ngx account using any setup third party authentication systems.

    Defaults to True

#### [`PAPERLESS_SOCIAL_ACCOUNT_SYNC_GROUPS=<bool>`](#PAPERLESS_SOCIAL_ACCOUNT_SYNC_GROUPS) {#PAPERLESS_SOCIAL_ACCOUNT_SYNC_GROUPS}

: Sync groups from the third party authentication system (e.g. OIDC) to Paperless-ngx. When enabled, users will be added or removed from groups based on their group membership in the third party authentication system. Groups must already exist in Paperless-ngx and have the same name as in the third party authentication system. Groups are updated upon logging in via the third party authentication system, see the corresponding [django-allauth documentation](https://docs.allauth.org/en/dev/socialaccount/signals.html).

: In order to pass groups from the authentication system you will need to update your [PAPERLESS_SOCIALACCOUNT_PROVIDERS](#PAPERLESS_SOCIALACCOUNT_PROVIDERS) setting by adding a top-level "SCOPES" setting which includes "groups", e.g.:

    ```json
    {"openid_connect":{"SCOPE": ["openid","profile","email","groups"]...
    ```

    Defaults to False

#### [`PAPERLESS_SOCIAL_ACCOUNT_DEFAULT_GROUPS=<comma-separated-list>`](#PAPERLESS_SOCIAL_ACCOUNT_DEFAULT_GROUPS) {#PAPERLESS_SOCIAL_ACCOUNT_DEFAULT_GROUPS}

: A list of group names that users who signup via social accounts will be added to upon signup. Groups listed here must already exist.
If both the [PAPERLESS_ACCOUNT_DEFAULT_GROUPS](#PAPERLESS_ACCOUNT_DEFAULT_GROUPS) setting and this setting are used, the user will be added to both sets of groups.

    Defaults to None

#### [`PAPERLESS_ACCOUNT_DEFAULT_HTTP_PROTOCOL=<string>`](#PAPERLESS_ACCOUNT_DEFAULT_HTTP_PROTOCOL) {#PAPERLESS_ACCOUNT_DEFAULT_HTTP_PROTOCOL}

: The protocol used when generating URLs, e.g. login callback URLs. See the corresponding
[django-allauth documentation](https://docs.allauth.org/en/latest/account/configuration.html)

    Defaults to 'https'

#### [`PAPERLESS_ACCOUNT_EMAIL_VERIFICATION=<string>`](#PAPERLESS_ACCOUNT_EMAIL_VERIFICATION) {#PAPERLESS_ACCOUNT_EMAIL_VERIFICATION}

: Determines whether email addresses are verified during signup (as performed by Django allauth). See the relevant
[paperless settings](#PAPERLESS_EMAIL_HOST) and [the allauth docs](https://docs.allauth.org/en/latest/account/configuration.html)

    Defaults to 'optional'

!!! note

    If you do not have a working email server set up you should set this to 'none'.

#### [`PAPERLESS_DISABLE_REGULAR_LOGIN=<bool>`](#PAPERLESS_DISABLE_REGULAR_LOGIN) {#PAPERLESS_DISABLE_REGULAR_LOGIN}

: Disables the regular frontend username / password login, i.e. once you have setup SSO. Note that this setting does not disable the Django admin login nor logging in with local credentials via the API. To prevent access to the Django admin, consider blocking `/admin/` in your [web server or reverse proxy configuration](https://github.com/paperless-ngx/paperless-ngx/wiki/Using-a-Reverse-Proxy-with-Paperless-ngx).

    You can optionally also automatically redirect users to the SSO login with [PAPERLESS_REDIRECT_LOGIN_TO_SSO](#PAPERLESS_REDIRECT_LOGIN_TO_SSO)

    Defaults to False

#### [`PAPERLESS_REDIRECT_LOGIN_TO_SSO=<bool>`](#PAPERLESS_REDIRECT_LOGIN_TO_SSO) {#PAPERLESS_REDIRECT_LOGIN_TO_SSO}

: When this setting is enabled users will automatically be redirected (using javascript) to the first SSO provider login. You may still want to disable the frontend login form for clarity.

    Defaults to False

#### [`PAPERLESS_ACCOUNT_SESSION_REMEMBER=<bool>`](#PAPERLESS_ACCOUNT_SESSION_REMEMBER) {#PAPERLESS_ACCOUNT_SESSION_REMEMBER}

: If false, sessions will expire at browser close, if true will use `PAPERLESS_SESSION_COOKIE_AGE` for expiration. See the corresponding
[django-allauth documentation](https://docs.allauth.org/en/latest/account/configuration.html)

    Defaults to True

#### [`PAPERLESS_SESSION_COOKIE_AGE=<int>`](#PAPERLESS_SESSION_COOKIE_AGE) {#PAPERLESS_SESSION_COOKIE_AGE}

: Login session cookie expiration. Applies if `PAPERLESS_ACCOUNT_SESSION_REMEMBER` is enabled. See the corresponding
[django documentation](https://docs.djangoproject.com/en/5.1/ref/settings/#std-setting-SESSION_COOKIE_AGE)

    Defaults to 1209600 (2 weeks)

## OCR settings {#ocr}

Paperless uses [OCRmyPDF](https://ocrmypdf.readthedocs.io/en/latest/)
for performing OCR on documents and images. Paperless uses sensible
defaults for most settings, but all of them can be configured to your
needs.

#### [`PAPERLESS_OCR_LANGUAGE=<lang>`](#PAPERLESS_OCR_LANGUAGE) {#PAPERLESS_OCR_LANGUAGE}

: Customize the language that paperless will attempt to use when
parsing documents.

    It should be a 3-letter code, see the list of [languages Tesseract supports](https://tesseract-ocr.github.io/tessdoc/Data-Files-in-different-versions.html).

    Set this to the language most of your documents are written in.

    This can be a combination of multiple languages such as `deu+eng`,
    in which case Tesseract will use whatever language matches best.
    Keep in mind that Tesseract uses much more CPU time with multiple
    languages enabled.

    If you are including languages that are not installed by default, you will need to also set [`PAPERLESS_OCR_LANGUAGES`](configuration.md#PAPERLESS_OCR_LANGUAGES) for docker deployments or install the tesseract language packages manually for bare metal installations.

    Defaults to "eng".

    !!! note

        If your language contains a '-' such as chi-sim, you must use `chi_sim`.

#### [`PAPERLESS_OCR_MODE=<mode>`](#PAPERLESS_OCR_MODE) {#PAPERLESS_OCR_MODE}

: Tell paperless when and how to perform ocr on your documents. Three
modes are available:

    -   `skip`: Paperless skips all pages and will perform ocr only on
        pages where no text is present. This is the safest option.

    -   `redo`: Paperless will OCR all pages of your documents and
        attempt to replace any existing text layers with new text. This
        will be useful for documents from scanners that already
        performed OCR with insufficient results. It will also perform
        OCR on purely digital documents.

        This option may fail on some documents that have features that
        cannot be removed, such as forms. In this case, the text from
        the document is used instead.

    -   `force`: Paperless rasterizes your documents, converting any
        text into images and puts the OCRed text on top. This works for
        all documents, however, the resulting document may be
        significantly larger and text won't appear as sharp when zoomed
        in.

    The default is `skip`, which only performs OCR when necessary and
    always creates archived documents.

    Read more about this in the [OCRmyPDF
    documentation](https://ocrmypdf.readthedocs.io/en/latest/advanced.html#when-ocr-is-skipped).

#### [`PAPERLESS_OCR_SKIP_ARCHIVE_FILE=<mode>`](#PAPERLESS_OCR_SKIP_ARCHIVE_FILE) {#PAPERLESS_OCR_SKIP_ARCHIVE_FILE}

: Specify when you would like paperless to skip creating an archived
version of your documents. This is useful if you don't want to have two
almost-identical versions of your documents in the media folder.

    -   `never`: Never skip creating an archived version.
    -   `with_text`: Skip creating an archived version for documents
    that already have embedded text.
    -   `always`: Always skip creating an archived version.

    The default is `never`.

#### [`PAPERLESS_OCR_CLEAN=<mode>`](#PAPERLESS_OCR_CLEAN) {#PAPERLESS_OCR_CLEAN}

: Tells paperless to use `unpaper` to clean any input document before
sending it to tesseract. This uses more resources, but generally
results in better OCR results. The following modes are available:

    -   `clean`: Apply unpaper.
    -   `clean-final`: Apply unpaper, and use the cleaned images to
        build the output file instead of the original images.
    -   `none`: Do not apply unpaper.

    Defaults to `clean`.

    !!! note

        `clean-final` is incompatible with ocr mode `redo`. When both
        `clean-final` and the ocr mode `redo` is configured, `clean` is used
        instead.

#### [`PAPERLESS_OCR_DESKEW=<bool>`](#PAPERLESS_OCR_DESKEW) {#PAPERLESS_OCR_DESKEW}

: Tells paperless to correct skewing (slight rotation of input images
mainly due to improper scanning)

    Defaults to `true`, which enables this feature.

    !!! note

        Deskewing is incompatible with ocr mode `redo`. Deskewing will get
        disabled automatically if `redo` is used as the ocr mode.

#### [`PAPERLESS_OCR_ROTATE_PAGES=<bool>`](#PAPERLESS_OCR_ROTATE_PAGES) {#PAPERLESS_OCR_ROTATE_PAGES}

: Tells paperless to correct page rotation (90°, 180° and 270°
rotation).

    If you notice that paperless is not rotating incorrectly rotated
    pages (or vice versa), try adjusting the threshold up or down (see
    below).

    Defaults to `true`, which enables this feature.

#### [`PAPERLESS_OCR_ROTATE_PAGES_THRESHOLD=<num>`](#PAPERLESS_OCR_ROTATE_PAGES_THRESHOLD) {#PAPERLESS_OCR_ROTATE_PAGES_THRESHOLD}

: Adjust the threshold for automatic page rotation by
`PAPERLESS_OCR_ROTATE_PAGES`. This is an arbitrary value reported by
tesseract. "15" is a very conservative value, whereas "2" is a
very aggressive option and will often result in correctly rotated
pages being rotated as well.

    Defaults to "12".

#### [`PAPERLESS_OCR_OUTPUT_TYPE=<type>`](#PAPERLESS_OCR_OUTPUT_TYPE) {#PAPERLESS_OCR_OUTPUT_TYPE}

: Specify the the type of PDF documents that paperless should produce.

    -   `pdf`: Modify the PDF document as little as possible.
    -   `pdfa`: Convert PDF documents into PDF/A-2b documents, which is
        a subset of the entire PDF specification and meant for storing
        documents long term.
    -   `pdfa-1`, `pdfa-2`, `pdfa-3` to specify the exact version of
        PDF/A you wish to use.

    If not specified, `pdfa` is used. Remember that paperless also keeps
    the original input file as well as the archived version.

#### [`PAPERLESS_OCR_PAGES=<num>`](#PAPERLESS_OCR_PAGES) {#PAPERLESS_OCR_PAGES}

: Tells paperless to use only the specified amount of pages for OCR.
Documents with less than the specified amount of pages get OCR'ed
completely.

    Specifying 1 here will only use the first page.

    The value must be greater than or equal to 1 to be used.

    When combined with `PAPERLESS_OCR_MODE=redo` or
    `PAPERLESS_OCR_MODE=force`, paperless will not modify any text it
    finds on excluded pages and copy it verbatim.

    Defaults to unset, which disables this feature and always uses all
    pages.

#### [`PAPERLESS_OCR_IMAGE_DPI=<num>`](#PAPERLESS_OCR_IMAGE_DPI) {#PAPERLESS_OCR_IMAGE_DPI}

: Paperless will OCR any images you put into the system and convert
them into PDF documents. This is useful if your scanner produces
images. In order to do so, paperless needs to know the DPI of the
image. Most images from scanners will have this information embedded
and paperless will detect and use that information. In case this
fails, it uses this value as a fallback.

    Set this to the DPI your scanner produces images at.

    Defaults to unset, which will automatically calculate image DPI so
    that the produced PDF documents are A4 sized.

#### [`PAPERLESS_OCR_MAX_IMAGE_PIXELS=<num>`](#PAPERLESS_OCR_MAX_IMAGE_PIXELS) {#PAPERLESS_OCR_MAX_IMAGE_PIXELS}

: Paperless will raise a warning when OCRing images which are over
this limit and will not OCR images which are more than twice this
limit. Note this does not prevent the document from being consumed,
but could result in missing text content.

    If unset, will default to the value determined by
    [Pillow](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.MAX_IMAGE_PIXELS).

    Setting this value to 0 will entirely disable the limit.  See the below warning.

    !!! note

        Increasing this limit could cause Paperless to consume additional
        resources when consuming a file. Be sure you have sufficient system
        resources.

    !!! warning

        The limit is intended to prevent malicious files from consuming
        system resources and causing crashes and other errors. Only change
        this value if you are certain your documents are not malicious and
        you need the text which was not OCRed

#### [`PAPERLESS_OCR_COLOR_CONVERSION_STRATEGY=<RGB>`](#PAPERLESS_OCR_COLOR_CONVERSION_STRATEGY) {#PAPERLESS_OCR_COLOR_CONVERSION_STRATEGY}

: Controls the Ghostscript color conversion strategy when creating the archive file. This setting
will only be utilized if the output is a version of PDF/A.

    Valid options are CMYK, Gray, LeaveColorUnchanged, RGB or UseDeviceIndependentColor.

    You can find more on the settings [here](https://ghostscript.readthedocs.io/en/latest/VectorDevices.html#color-conversion-and-management) in the Ghostscript documentation.

    !!! warning

        Utilizing some of the options may result in errors when creating archive
        files from PDFs.

#### [`PAPERLESS_OCR_USER_ARGS=<json>`](#PAPERLESS_OCR_USER_ARGS) {#PAPERLESS_OCR_USER_ARGS}

: OCRmyPDF offers many more options. Use this parameter to specify any
additional arguments you wish to pass to OCRmyPDF. Since Paperless
uses the API of OCRmyPDF, you have to specify these in a format that
can be passed to the API. See [the API reference of
OCRmyPDF](https://ocrmypdf.readthedocs.io/en/latest/api.html#reference)
for valid parameters. All command line options are supported, but
they use underscores instead of dashes.

    !!! warning

        Paperless has been tested to work with the OCR options provided
        above. There are many options that are incompatible with each other,
        so specifying invalid options may prevent paperless from consuming
        any documents.  Use with caution!

    Specify arguments as a JSON dictionary. Keep note of lower case
    booleans and double quoted parameter names and strings. Examples:

    ``` json
    {"deskew": true, "optimize": 3, "unpaper_args": "--pre-rotate 90"}
    ```

## Software tweaks {#software_tweaks}

#### [`PAPERLESS_TASK_WORKERS=<num>`](#PAPERLESS_TASK_WORKERS) {#PAPERLESS_TASK_WORKERS}

: Paperless does multiple things in the background: Maintain the
search index, maintain the automatic matching algorithm, check
emails, consume documents, etc. This variable specifies how many
things it will do in parallel.

    Defaults to 1

#### [`PAPERLESS_THREADS_PER_WORKER=<num>`](#PAPERLESS_THREADS_PER_WORKER) {#PAPERLESS_THREADS_PER_WORKER}

: Furthermore, paperless uses multiple threads when consuming
documents to speed up OCR. This variable specifies how many pages
paperless will process in parallel on a single document.

    !!! warning

        Ensure that the product

        `PAPERLESS_TASK_WORKERS * PAPERLESS_THREADS_PER_WORKER`

        does not exceed your CPU core count or else paperless will be
        extremely slow. If you want paperless to process many documents in
        parallel, choose a high worker count. If you want paperless to
        process very large documents faster, use a higher thread per worker
        count.

    The default is a balance between the two, according to your CPU core
    count, with a slight favor towards threads per worker:

    | CPU core count | Workers | Threads |
    | -------------- | ------- | ------- |
    | > 1            | > 1     | > 1     |
    | > 2            | > 2     | > 1     |
    | > 4            | > 2     | > 2     |
    | > 6            | > 2     | > 3     |
    | > 8            | > 2     | > 4     |
    | > 12           | > 3     | > 4     |
    | > 16           | > 4     | > 4     |

    If you only specify PAPERLESS_TASK_WORKERS, paperless will adjust
    PAPERLESS_THREADS_PER_WORKER automatically.

#### [`PAPERLESS_WORKER_TIMEOUT=<num>`](#PAPERLESS_WORKER_TIMEOUT) {#PAPERLESS_WORKER_TIMEOUT}

: Machines with few cores or weak ones might not be able to finish OCR
on large documents within the default 1800 seconds. So extending
this timeout may prove to be useful on weak hardware setups.

#### [`PAPERLESS_TIME_ZONE=<timezone>`](#PAPERLESS_TIME_ZONE) {#PAPERLESS_TIME_ZONE}

: Set the time zone here. See more details on
why and how to set it [in the Django project documentation](https://docs.djangoproject.com/en/4.1/ref/settings/#std:setting-TIME_ZONE)
for details on how to set it.

    Defaults to UTC.

#### [`PAPERLESS_ENABLE_NLTK=<bool>`](#PAPERLESS_ENABLE_NLTK) {#PAPERLESS_ENABLE_NLTK}

: Enables or disables the advanced natural language processing
used during automatic classification. If disabled, paperless will
still perform some basic text pre-processing before matching.

: See also `PAPERLESS_NLTK_DIR`.

    Defaults to 1.

#### [`PAPERLESS_EMAIL_TASK_CRON=<cron expression>`](#PAPERLESS_EMAIL_TASK_CRON) {#PAPERLESS_EMAIL_TASK_CRON}

: Configures the scheduled email fetching frequency. The value
should be a valid crontab(5) expression describing when to run.

: If set to the string "disable", no emails will be fetched automatically.

    Defaults to `*/10 * * * *` or every ten minutes.

#### [`PAPERLESS_TRAIN_TASK_CRON=<cron expression>`](#PAPERLESS_TRAIN_TASK_CRON) {#PAPERLESS_TRAIN_TASK_CRON}

: Configures the scheduled automatic classifier training frequency. The value
should be a valid crontab(5) expression describing when to run.

: If set to the string "disable", the classifier will not be trained automatically.

    Defaults to `5 */1 * * *` or every hour at 5 minutes past the hour.

#### [`PAPERLESS_INDEX_TASK_CRON=<cron expression>`](#PAPERLESS_INDEX_TASK_CRON) {#PAPERLESS_INDEX_TASK_CRON}

: Configures the scheduled search index update frequency. The value
should be a valid crontab(5) expression describing when to run.

: If set to the string "disable", the search index will not be automatically updated.

    Defaults to `0 0 * * *` or daily at midnight.

#### [`PAPERLESS_SANITY_TASK_CRON=<cron expression>`](#PAPERLESS_SANITY_TASK_CRON) {#PAPERLESS_SANITY_TASK_CRON}

: Configures the scheduled sanity checker frequency.

: If set to the string "disable", the sanity checker will not run automatically.

    Defaults to `30 0 * * sun` or Sunday at 30 minutes past midnight.

#### [`PAPERLESS_ENABLE_COMPRESSION=<bool>`](#PAPERLESS_ENABLE_COMPRESSION) {#PAPERLESS_ENABLE_COMPRESSION}

: Enables compression of the responses from the webserver.

: Defaults to 1, enabling compression.

    !!! note

        If you are using a proxy such as nginx, it is likely more efficient
        to enable compression in your proxy configuration rather than
        the webserver

#### [`PAPERLESS_CONVERT_MEMORY_LIMIT=<num>`](#PAPERLESS_CONVERT_MEMORY_LIMIT) {#PAPERLESS_CONVERT_MEMORY_LIMIT}

: On smaller systems, or even in the case of Very Large Documents, the
consumer may explode, complaining about how it's "unable to extend
pixel cache". In such cases, try setting this to a reasonably low
value, like 32. The default is to use whatever is necessary to do
everything without writing to disk, and units are in megabytes.

    For more information on how to use this value, you should search the
    web for "MAGICK_MEMORY_LIMIT".

    Defaults to 0, which disables the limit.

#### [`PAPERLESS_CONVERT_TMPDIR=<path>`](#PAPERLESS_CONVERT_TMPDIR) {#PAPERLESS_CONVERT_TMPDIR}

: Similar to the memory limit, if you've got a small system and your
OS mounts /tmp as tmpfs, you should set this to a path that's on a
physical disk, like /home/your_user/tmp or something. ImageMagick
will use this as scratch space when crunching through very large
documents.

    For more information on how to use this value, you should search the
    web for "MAGICK_TMPDIR".

    Default is none, which disables the temporary directory.

#### [`PAPERLESS_APPS=<string>`](#PAPERLESS_APPS) {#PAPERLESS_APPS}

: A comma-separated list of Django apps to be included in Django's
[`INSTALLED_APPS`](https://docs.djangoproject.com/en/5.0/ref/applications/). This setting should
be used with caution!

    Defaults to None, which does not add any additional apps.

#### [`PAPERLESS_MAX_IMAGE_PIXELS=<number>`](#PAPERLESS_MAX_IMAGE_PIXELS) {#PAPERLESS_MAX_IMAGE_PIXELS}

: Configures the maximum size of an image PIL will allow to load without warning or error.

: If unset, will default to the value determined by
[Pillow](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.MAX_IMAGE_PIXELS).

    Defaults to None, which does change the limit

    !!! warning

        This limit is designed to prevent denial of service from malicious files.
        It should only be raised or disabled in certain circumstances and with great care.

## Document Consumption {#consume_config}

#### [`PAPERLESS_CONSUMER_DISABLE=<bool>`](#PAPERLESS_CONSUMER_DISABLE) {#PAPERLESS_CONSUMER_DISABLE}

: Completely disable the directory-based consumer in docker. If you don't plan to consume documents
via the consumption directory, you can disable the consumer to save resources.

#### [`PAPERLESS_CONSUMER_DELETE_DUPLICATES=<bool>`](#PAPERLESS_CONSUMER_DELETE_DUPLICATES) {#PAPERLESS_CONSUMER_DELETE_DUPLICATES}

: When the consumer detects a duplicate document, it will not touch
the original document. This default behavior can be changed here.

    Defaults to false.

#### [`PAPERLESS_CONSUMER_RECURSIVE=<bool>`](#PAPERLESS_CONSUMER_RECURSIVE) {#PAPERLESS_CONSUMER_RECURSIVE}

: Enable recursive watching of the consumption directory. Paperless
will then pickup files from files in subdirectories within your
consumption directory as well.

    Defaults to false.

#### [`PAPERLESS_CONSUMER_SUBDIRS_AS_TAGS=<bool>`](#PAPERLESS_CONSUMER_SUBDIRS_AS_TAGS) {#PAPERLESS_CONSUMER_SUBDIRS_AS_TAGS}

: Set the names of subdirectories as tags for consumed files. E.g.
`<CONSUMPTION_DIR>/foo/bar/file.pdf` will add the tags "foo" and
"bar" to the consumed file. Paperless will create any tags that
don't exist yet.

    This is useful for sorting documents with certain tags such as `car`
    or `todo` prior to consumption. These folders won't be deleted.

    PAPERLESS_CONSUMER_RECURSIVE must be enabled for this to work.

    Defaults to false.

#### [`PAPERLESS_CONSUMER_IGNORE_PATTERNS=<json>`](#PAPERLESS_CONSUMER_IGNORE_PATTERNS) {#PAPERLESS_CONSUMER_IGNORE_PATTERNS}

: By default, paperless ignores certain files and folders in the
consumption directory, such as system files created by the Mac OS
or hidden folders some tools use to store data.

    This can be adjusted by configuring a custom json array with
    patterns to exclude.

    For example, `.DS_STORE/*` will ignore any files found in a folder
    named `.DS_STORE`, including `.DS_STORE/bar.pdf` and `foo/.DS_STORE/bar.pdf`

    A pattern like `._*` will ignore anything starting with `._`, including:
    `._foo.pdf` and `._bar/foo.pdf`

    Defaults to
    `[".DS_Store", ".DS_STORE", "._*", ".stfolder/*", ".stversions/*", ".localized/*", "desktop.ini", "@eaDir/*", "Thumbs.db"]`.

#### [`PAPERLESS_CONSUMER_BARCODE_SCANNER=<string>`](#PAPERLESS_CONSUMER_BARCODE_SCANNER) {#PAPERLESS_CONSUMER_BARCODE_SCANNER}

: Sets the barcode scanner used for barcode functionality.

    Currently, "PYZBAR" (the default) or "ZXING" might be selected.
    If you have problems that your Barcodes/QR-Codes are not detected
    (especially with bad scan quality and/or small codes), try the other one.

#### [`PAPERLESS_PRE_CONSUME_SCRIPT=<filename>`](#PAPERLESS_PRE_CONSUME_SCRIPT) {#PAPERLESS_PRE_CONSUME_SCRIPT}

: After some initial validation, Paperless can trigger an arbitrary
script if you like before beginning consumption. This script will be provided
data for it to work with via the environment.

    For more information, take a look at [pre-consumption script](advanced_usage.md#pre-consume-script).

    The default is blank, which means nothing will be executed.

#### [`PAPERLESS_POST_CONSUME_SCRIPT=<filename>`](#PAPERLESS_POST_CONSUME_SCRIPT) {#PAPERLESS_POST_CONSUME_SCRIPT}

: After a document is consumed, Paperless can trigger an arbitrary
script if you like. This script will be provided
data for it to work with via the environment.

    For more information, take a look at [Post-consumption script](advanced_usage.md#post-consume-script).

    The default is blank, which means nothing will be executed.

#### [`PAPERLESS_FILENAME_DATE_ORDER=<format>`](#PAPERLESS_FILENAME_DATE_ORDER) {#PAPERLESS_FILENAME_DATE_ORDER}

: Paperless will check the document text for document date
information. Use this setting to enable checking the document
filename for date information. The date order can be set to any
option as specified in
<https://dateparser.readthedocs.io/en/latest/settings.html#date-order>.
The filename will be checked first, and if nothing is found, the
document text will be checked as normal.

    A date in a filename must have some separators (`.`, `,`, `-`, `/`, etc) for it to be parsed.

    Defaults to none, which disables this feature.

#### [`PAPERLESS_NUMBER_OF_SUGGESTED_DATES=<num>`](#PAPERLESS_NUMBER_OF_SUGGESTED_DATES) {#PAPERLESS_NUMBER_OF_SUGGESTED_DATES}

: Paperless searches an entire document for dates. The first date
found will be used as the initial value for the created date. When
this variable is greater than 0 (or left to its default value),
paperless will also suggest other dates found in the document, up to
a maximum of this setting. Note that duplicates will be removed,
which can result in fewer dates displayed in the frontend than this
setting value.

    The task to find all dates can be time-consuming and increases with
    a higher (maximum) number of suggested dates and slower hardware.

    Defaults to 3. Set to 0 to disable this feature.

#### [`PAPERLESS_THUMBNAIL_FONT_NAME=<filename>`](#PAPERLESS_THUMBNAIL_FONT_NAME) {#PAPERLESS_THUMBNAIL_FONT_NAME}

: Paperless creates thumbnails for plain text files by rendering the
content of the file on an image and uses a predefined font for that.
This font can be changed here.

    Note that this won't have any effect on already generated
    thumbnails.

    Defaults to
    `/usr/share/fonts/liberation/LiberationSerif-Regular.ttf`.

#### [`PAPERLESS_IGNORE_DATES=<string>`](#PAPERLESS_IGNORE_DATES) {#PAPERLESS_IGNORE_DATES}

: Paperless parses a document's creation date from filename and file
content. You may specify a comma separated list of dates that should
be ignored during this process. This is useful for special dates
(like date of birth) that appear in documents regularly but are very
unlikely to be the document's creation date.

    The date is parsed using the order specified in PAPERLESS_DATE_ORDER

    Defaults to an empty string to not ignore any dates.

#### [`PAPERLESS_DATE_ORDER=<format>`](#PAPERLESS_DATE_ORDER) {#PAPERLESS_DATE_ORDER}

: Paperless will try to determine the document creation date from its
contents. Specify the date format Paperless should expect to see
within your documents.

    This option defaults to DMY which translates to day first, month
    second, and year last order. Characters D, M, or Y can be shuffled
    to meet the required order.

#### [`PAPERLESS_ENABLE_GPG_DECRYPTOR=<bool>`](#PAPERLESS_ENABLE_GPG_DECRYPTOR) {#PAPERLESS_ENABLE_GPG_DECRYPTOR}

: Enable or disable the GPG decryptor for encrypted emails. See [GPG Decryptor](advanced_usage.md#gpg-decryptor) for more information.

    Defaults to false.

### Polling {#polling}

#### [`PAPERLESS_CONSUMER_POLLING=<num>`](#PAPERLESS_CONSUMER_POLLING) {#PAPERLESS_CONSUMER_POLLING}

: If paperless won't find documents added to your consume folder, it
might not be able to automatically detect filesystem changes. In
that case, specify a polling interval in seconds here, which will
then cause paperless to periodically check your consumption
directory for changes. This will also disable listening for file
system changes with `inotify`.

    Defaults to 0, which disables polling and uses filesystem
    notifications.

#### [`PAPERLESS_CONSUMER_POLLING_RETRY_COUNT=<num>`](#PAPERLESS_CONSUMER_POLLING_RETRY_COUNT) {#PAPERLESS_CONSUMER_POLLING_RETRY_COUNT}

: If consumer polling is enabled, sets the maximum number of times
paperless will check for a file to remain unmodified. If a file's
modification time and size are identical for two consecutive checks, it
will be consumed.

    Defaults to 5.

#### [`PAPERLESS_CONSUMER_POLLING_DELAY=<num>`](#PAPERLESS_CONSUMER_POLLING_DELAY) {#PAPERLESS_CONSUMER_POLLING_DELAY}

: If consumer polling is enabled, sets the delay in seconds between
each check (above) paperless will do while waiting for a file to
remain unmodified.

    Defaults to 5.

### iNotify {#inotify}

#### [`PAPERLESS_CONSUMER_INOTIFY_DELAY=<num>`](#PAPERLESS_CONSUMER_INOTIFY_DELAY) {#PAPERLESS_CONSUMER_INOTIFY_DELAY}

: Sets the time in seconds the consumer will wait for additional
events from inotify before the consumer will consider a file ready
and begin consumption. Certain scanners or network setups may
generate multiple events for a single file, leading to multiple
consumers working on the same file. Configure this to prevent that.

    Defaults to 0.5 seconds.

## Incoming Mail {#incoming_mail}

### Email OAuth {#email_oauth}

#### [`PAPERLESS_OAUTH_CALLBACK_BASE_URL=<str>`](#PAPERLESS_OAUTH_CALLBACK_BASE_URL) {#PAPERLESS_OAUTH_CALLBACK_BASE_URL}

: The base URL for the OAuth callback. This is used to construct the full URL for the OAuth callback. This should be the URL that the Paperless instance is accessible at. If not set, defaults to the `PAPERLESS_URL` setting. At least one of these settings must be set to enable OAuth Email setup.

    Defaults to none (thus will use [PAPERLESS_URL](#PAPERLESS_URL)).

!!! note

    This setting only applies to OAuth Email setup (not to the SSO setup).

#### [`PAPERLESS_GMAIL_OAUTH_CLIENT_ID=<str>`](#PAPERLESS_GMAIL_OAUTH_CLIENT_ID) {#PAPERLESS_GMAIL_OAUTH_CLIENT_ID}

: The OAuth client ID for Gmail. This is required for Gmail OAuth Email setup. See [OAuth Email Setup](usage.md#oauth-email-setup) for more information.

    Defaults to none.

#### [`PAPERLESS_GMAIL_OAUTH_CLIENT_SECRET=<str>`](#PAPERLESS_GMAIL_OAUTH_CLIENT_SECRET) {#PAPERLESS_GMAIL_OAUTH_CLIENT_SECRET}

: The OAuth client secret for Gmail. This is required for Gmail OAuth Email setup. See [OAuth Email Setup](usage.md#oauth-email-setup) for more information.

    Defaults to none.

#### [`PAPERLESS_OUTLOOK_OAUTH_CLIENT_ID=<str>`](#PAPERLESS_OUTLOOK_OAUTH_CLIENT_ID) {#PAPERLESS_OUTLOOK_OAUTH_CLIENT_ID}

: The OAuth client ID for Outlook. This is required for Outlook OAuth Email setup. See [OAuth Email Setup](usage.md#oauth-email-setup) for more information.

    Defaults to none.

#### [`PAPERLESS_OUTLOOK_OAUTH_CLIENT_SECRET=<str>`](#PAPERLESS_OUTLOOK_OAUTH_CLIENT_SECRET) {#PAPERLESS_OUTLOOK_OAUTH_CLIENT_SECRET}

: The OAuth client secret for Outlook. This is required for Outlook OAuth Email setup. See [OAuth Email Setup](usage.md#oauth-email-setup) for more information.

    Defaults to none.

### Encrypted Emails {#encrypted_emails}

#### [`PAPERLESS_EMAIL_GNUPG_HOME=<str>`](#PAPERLESS_EMAIL_GNUPG_HOME) {#PAPERLESS_EMAIL_GNUPG_HOME}

: Optional, sets the `GNUPG_HOME` path to use with GPG decryptor for encrypted emails. See [GPG Decryptor](advanced_usage.md#gpg-decryptor) for more information. If not set, defaults to the default `GNUPG_HOME` path.

    Defaults to <not set>.

## Barcodes {#barcodes}

#### [`PAPERLESS_CONSUMER_ENABLE_BARCODES=<bool>`](#PAPERLESS_CONSUMER_ENABLE_BARCODES) {#PAPERLESS_CONSUMER_ENABLE_BARCODES}

: Enables the scanning and page separation based on detected barcodes.
This allows for scanning and adding multiple documents per uploaded
file, which are separated by one or multiple barcode pages.

    For ease of use, it is suggested to use a standardized separation
    page, e.g. [here](https://www.alliancegroup.co.uk/patch-codes.htm).

    If no barcodes are detected in the uploaded file, no page separation
    will happen.

    The original document will be removed and the separated pages will
    be saved as pdf.

    See additional information in the [advanced usage documentation](advanced_usage.md#barcodes)

    Defaults to false.

#### [`PAPERLESS_CONSUMER_BARCODE_TIFF_SUPPORT=<bool>`](#PAPERLESS_CONSUMER_BARCODE_TIFF_SUPPORT) {#PAPERLESS_CONSUMER_BARCODE_TIFF_SUPPORT}

: Whether TIFF image files should be scanned for barcodes. This will
automatically convert any TIFF image(s) to pdfs for later
processing. This only has an effect, if
PAPERLESS_CONSUMER_ENABLE_BARCODES has been enabled.

    Defaults to false.

#### [`PAPERLESS_CONSUMER_BARCODE_STRING=<string>`](#PAPERLESS_CONSUMER_BARCODE_STRING) {#PAPERLESS_CONSUMER_BARCODE_STRING}

: Defines the string to be detected as a separator barcode. If
paperless is used with the PATCH-T separator pages, users shouldn't
change this.

    Defaults to "PATCHT"

#### [`PAPERLESS_CONSUMER_BARCODE_RETAIN_SPLIT_PAGES=<bool>`](#PAPERLESS_CONSUMER_BARCODE_RETAIN_SPLIT_PAGES) {#PAPERLESS_CONSUMER_BARCODE_RETAIN_SPLIT_PAGES}

: If set to true, all pages that are split by a barcode (such as PATCHT) will be kept.

    Defaults to false.

#### [`PAPERLESS_CONSUMER_ENABLE_ASN_BARCODE=<bool>`](#PAPERLESS_CONSUMER_ENABLE_ASN_BARCODE) {#PAPERLESS_CONSUMER_ENABLE_ASN_BARCODE}

: Enables the detection of barcodes in the scanned document and
setting the ASN (archive serial number) if a properly formatted
barcode is detected.

    The barcode must consist of a (configurable) prefix and the ASN
    to be set, for instance `ASN00123`. The content after the prefix
    is cleaned of non-numeric characters.

    This option is compatible with barcode page separation, since
    pages will be split up before reading the ASN.

    If no ASN barcodes are detected in the uploaded file, no ASN will
    be set. If a barcode with an existing ASN is detected, the
    document will not be consumed and an error logged.

    Defaults to false.

#### [`PAPERLESS_CONSUMER_ASN_BARCODE_PREFIX=<string>`](#PAPERLESS_CONSUMER_ASN_BARCODE_PREFIX) {#PAPERLESS_CONSUMER_ASN_BARCODE_PREFIX}

: Defines the prefix that is used to identify a barcode as an ASN
barcode.

    Defaults to "ASN"

#### [`PAPERLESS_CONSUMER_BARCODE_UPSCALE=<float>`](#PAPERLESS_CONSUMER_BARCODE_UPSCALE) {#PAPERLESS_CONSUMER_BARCODE_UPSCALE}

: Defines the upscale factor used in barcode detection.
Improves the detection of small barcodes, i.e. with a value of 1.5 by
upscaling the document before the detection process. Upscaling will
only take place if value is bigger than 1.0. Otherwise upscaling will
not be performed to save resources. Try using in combination with
PAPERLESS_CONSUMER_BARCODE_DPI set to a value higher than default.

    Defaults to 0.0

#### [`PAPERLESS_CONSUMER_BARCODE_DPI=<int>`](#PAPERLESS_CONSUMER_BARCODE_DPI) {#PAPERLESS_CONSUMER_BARCODE_DPI}

: During barcode detection every page from a PDF document needs
to be converted to an image. A dpi value can be specified in the
conversion process. Default is 300. If the detection of small barcodes
fails a bigger dpi value i.e. 600 can fix the issue. Try using in
combination with PAPERLESS_CONSUMER_BARCODE_UPSCALE bigger than 1.0.

    Defaults to "300"

#### [`PAPERLESS_CONSUMER_BARCODE_MAX_PAGES=<int>`](#PAPERLESS_CONSUMER_BARCODE_MAX_PAGES) {#PAPERLESS_CONSUMER_BARCODE_MAX_PAGES}

: Because barcode detection is a computationally-intensive operation, this setting
limits the detection of barcodes to a number of first pages. If your scanner has
a limit for the number of pages that can be scanned it would be sensible to set this
as the limit here.

    Defaults to "0", allowing all pages to be checked for barcodes.

#### [`PAPERLESS_CONSUMER_ENABLE_TAG_BARCODE=<bool>`](#PAPERLESS_CONSUMER_ENABLE_TAG_BARCODE) {#PAPERLESS_CONSUMER_ENABLE_TAG_BARCODE}

: Enables the detection of barcodes in the scanned document and
assigns or creates tags if a properly formatted barcode is detected.

    The barcode must match one of the (configurable) regular expressions.
    If the barcode text contains ',' (comma), it is split into multiple
    barcodes which are individually processed for tagging.

    Matching is case insensitive.

    Defaults to false.

#### [`PAPERLESS_CONSUMER_TAG_BARCODE_MAPPING=<json dict>`](#PAPERLESS_CONSUMER_TAG_BARCODE_MAPPING) {#PAPERLESS_CONSUMER_TAG_BARCODE_MAPPING}

: Defines a dictionary of filter regex and substitute expressions.

    Syntax: `{"<regex>": "<substitute>" [,...]]}`

    A barcode is considered for tagging if the barcode text matches
    at least one of the provided <regex> pattern.

    If a match is found, the <substitute> rule is applied. This allows very
    versatile reformatting and mapping of barcode pattern to tag values.

    If a tag is not found it will be created.

    Defaults to:

    `{"TAG:(.*)": "\\g<1>"}` which defines
    - a regex TAG:(.*) which includes barcodes beginning with TAG:
      followed by any text that gets stored into match group #1 and
    - a substitute `\\g<1>` that replaces the original barcode text
      by the content in match group #1.
    Consequently, the tag is the barcode text without its TAG: prefix.

    More examples:

    `{"ASN12.*": "JOHN", "ASN13.*": "SMITH"}` for example maps
    - ASN12nnnn barcodes to the tag JOHN and
    - ASN13nnnn barcodes to the tag SMITH.

    `{"T-J": "JOHN", "T-S": "SMITH", "T-D": "DOE"}` directly maps
    - T-J barcodes to the tag JOHN,
    - T-S barcodes to the tag SMITH and
    - T-D barcodes to the tag DOE.

    Please refer to the Python regex documentation for more information.

## Audit Trail

#### [`PAPERLESS_AUDIT_LOG_ENABLED=<bool>`](#PAPERLESS_AUDIT_LOG_ENABLED) {#PAPERLESS_AUDIT_LOG_ENABLED}

: Enables the audit trail for documents, document types, correspondents, and tags.

    Defaults to true.

## Collate Double-Sided Documents {#collate}

#### [`PAPERLESS_CONSUMER_ENABLE_COLLATE_DOUBLE_SIDED=<bool>`](#PAPERLESS_CONSUMER_ENABLE_COLLATE_DOUBLE_SIDED) {#PAPERLESS_CONSUMER_ENABLE_COLLATE_DOUBLE_SIDED}

: Enables automatic collation of two single-sided scans into a double-sided
document.

    This is useful if you have an automatic document feeder that only supports
    single-sided scans, but you need to scan a double-sided document. If your
    ADF supports double-sided scans natively, you do not need this feature.

    `PAPERLESS_CONSUMER_RECURSIVE` must be enabled for this to work.

    For more information, read the [corresponding section in the advanced
    documentation](advanced_usage.md#collate).

    Defaults to false.

#### [`PAPERLESS_CONSUMER_COLLATE_DOUBLE_SIDED_SUBDIR_NAME=<str>`](#PAPERLESS_CONSUMER_COLLATE_DOUBLE_SIDED_SUBDIR_NAME) {#PAPERLESS_CONSUMER_COLLATE_DOUBLE_SIDED_SUBDIR_NAME}

: The name of the subdirectory that the collate feature expects documents to
arrive.

    This only has an effect if `PAPERLESS_CONSUMER_ENABLE_COLLATE_DOUBLE_SIDED`
    has been enabled. Note that Paperless will not automatically create the
    directory.

    Defaults to "double-sided".

#### [`PAPERLESS_CONSUMER_COLLATE_DOUBLE_SIDED_TIFF_SUPPORT=<bool>`](#PAPERLESS_CONSUMER_COLLATE_DOUBLE_SIDED_TIFF_SUPPORT) {#PAPERLESS_CONSUMER_COLLATE_DOUBLE_SIDED_TIFF_SUPPORT}

: Whether TIFF image files should be supported when collating documents.
This will automatically convert any TIFF image(s) to pdfs for later
processing. This only has an effect if
`PAPERLESS_CONSUMER_ENABLE_COLLATE_DOUBLE_SIDED` has been enabled.

    Defaults to false.

## Trash

#### [`PAPERLESS_EMPTY_TRASH_DELAY=<num>`](#PAPERLESS_EMPTY_TRASH_DELAY) {#PAPERLESS_EMPTY_TRASH_DELAY}

: Sets how long in days documents remain in the 'trash' before they are permanently deleted.

    Defaults to 30 days, minimum of 1 day.

#### [`PAPERLESS_EMPTY_TRASH_TASK_CRON=<cron expression>`](#PAPERLESS_EMPTY_TRASH_TASK_CRON) {#PAPERLESS_EMPTY_TRASH_TASK_CRON}

: Configures the schedule to empty the trash of expired deleted documents.

    Defaults to `0 1 * * *`, once per day.

## Binaries

There are a few external software packages that Paperless expects to
find on your system when it starts up. Unless you've done something
creative with their installation, you probably won't need to edit any
of these. However, if you've installed these programs somewhere where
simply typing the name of the program doesn't automatically execute it
(ie. the program isn't in your $PATH), then you'll need to specify
the literal path for that program.

#### [`PAPERLESS_CONVERT_BINARY=<path>`](#PAPERLESS_CONVERT_BINARY) {#PAPERLESS_CONVERT_BINARY}

: Defaults to "convert".

#### [`PAPERLESS_GS_BINARY=<path>`](#PAPERLESS_GS_BINARY) {#PAPERLESS_GS_BINARY}

: Defaults to "gs".

## Docker-specific options {#docker}

These options don't have any effect in `paperless.conf`. These options
adjust the behavior of the docker container. Configure these in
`docker-compose.env`.

#### [`PAPERLESS_WEBSERVER_WORKERS=<num>`](#PAPERLESS_WEBSERVER_WORKERS) {#PAPERLESS_WEBSERVER_WORKERS}

: The number of worker processes the webserver should spawn. More
worker processes usually result in the front end to load data much
quicker. However, each worker process also loads the entire
application into memory separately, so increasing this value will
increase RAM usage.

    Defaults to 1.

    !!! note

         This option may also be set with `GRANIAN_WORKERS` and
         this option may be removed in the future

#### [`PAPERLESS_BIND_ADDR=<ip address>`](#PAPERLESS_BIND_ADDR) {#PAPERLESS_BIND_ADDR}

: The IP address the webserver will listen on inside the container.
There are special setups where you may need to configure this value
to restrict the Ip address or interface the webserver listens on.

    Defaults to `::`, meaning all interfaces, including IPv6.

    !!! note

         This option may also be set with `GRANIAN_HOST` and
         this option may be removed in the future

#### [`PAPERLESS_PORT=<port>`](#PAPERLESS_PORT) {#PAPERLESS_PORT}

: The port number the webserver will listen on inside the container.
There are special setups where you may need this to avoid collisions
with other services (like using podman with multiple containers in
one pod).

    Don't change this when using Docker. To change the port the
    webserver is reachable outside of the container, instead refer to
    the "ports" key in `docker-compose.yml`.

    Defaults to 8000.

    !!! note

         This option may also be set with `GRANIAN_PORT` and
         this option may be removed in the future

#### [`USERMAP_UID=<uid>`](#USERMAP_UID) {#USERMAP_UID}

: The ID of the paperless user in the container. Set this to your
actual user ID on the host system, which you can get by executing

    ``` shell-session
    id -u
    ```

    Paperless will change ownership on its folders to this user, so you
    need to get this right in order to be able to write to the
    consumption directory.

    Defaults to 1000.

#### [`USERMAP_GID=<gid>`](#USERMAP_GID) {#USERMAP_GID}

: The ID of the paperless Group in the container. Set this to your
actual group ID on the host system, which you can get by executing

    ``` shell-session
    id -g
    ```

    Paperless will change ownership on its folders to this group, so you
    need to get this right in order to be able to write to the
    consumption directory.

    Defaults to 1000.

#### [`PAPERLESS_OCR_LANGUAGES=<list>`](#PAPERLESS_OCR_LANGUAGES) {#PAPERLESS_OCR_LANGUAGES}

: Additional OCR languages to install. By default, paperless comes
with English, German, Italian, Spanish and French. If your language
is not in this list, install additional languages with this
configuration option. You will need to [find the right LangCodes](https://tesseract-ocr.github.io/tessdoc/Data-Files-in-different-versions.html)
but note that [tesseract-ocr-\* package names](https://packages.debian.org/bullseye/graphics/)
do not always correspond with the language codes e.g. "chi_tra" should be
specified as "chi-tra".

    ``` bash
    PAPERLESS_OCR_LANGUAGES=tur ces chi-tra
    ```

    Make sure it's a space-separated list when using several values.

    To actually use these languages, also set the default OCR language
    of paperless:

    ``` bash
    PAPERLESS_OCR_LANGUAGE=tur
    ```

    Defaults to none, which does not install any additional languages.

    !!! warning

         This option must not be used in rootless containers.

#### [`PAPERLESS_ENABLE_FLOWER=<defined>`](#PAPERLESS_ENABLE_FLOWER) {#PAPERLESS_ENABLE_FLOWER}

: If this environment variable is defined, the Celery monitoring tool
[Flower](https://flower.readthedocs.io/en/latest/index.html) will be
started by the container.

    You can read more about this in the [advanced documentation](advanced_usage.md#celery-monitoring).

#### [`PAPERLESS_SUPERVISORD_WORKING_DIR=<defined>`](#PAPERLESS_SUPERVISORD_WORKING_DIR) {#PAPERLESS_SUPERVISORD_WORKING_DIR}

!!! warning

        This option is deprecated and has no effect.  For read only file system support,
        see [S6_READ_ONLY_ROOT](https://github.com/just-containers/s6-overlay#customizing-s6-overlay-behaviour)
        from s6-overlay.

## Frontend Settings

#### [`PAPERLESS_APP_TITLE=<str>`](#PAPERLESS_APP_TITLE) {#PAPERLESS_APP_TITLE}

: If set, overrides the default name "Paperless-ngx"

#### [`PAPERLESS_APP_LOGO=<path>`](#PAPERLESS_APP_LOGO) {#PAPERLESS_APP_LOGO}

: Path to an image file in the /media/logo directory, must include 'logo', e.g. `/logo/Atari_logo.svg`

#### [`PAPERLESS_ENABLE_UPDATE_CHECK=<bool>`](#PAPERLESS_ENABLE_UPDATE_CHECK) {#PAPERLESS_ENABLE_UPDATE_CHECK}

!!! note

    This setting was deprecated in favor of a frontend setting after
    v1.9.2. A one-time migration is performed for users who have this
    setting set. This setting is always ignored if the corresponding
    frontend setting has been set.

## Email sending

Setting an SMTP server for the backend will allow you to reset your
password. All of these options come from their similarly-named [Django settings](https://docs.djangoproject.com/en/4.2/ref/settings/#email-host)

#### [`PAPERLESS_EMAIL_HOST=<str>`](#PAPERLESS_EMAIL_HOST) {#PAPERLESS_EMAIL_HOST}

: Defaults to 'localhost'.

#### [`PAPERLESS_EMAIL_PORT=<int>`](#PAPERLESS_EMAIL_PORT) {#PAPERLESS_EMAIL_PORT}

: Defaults to port 25.

#### [`PAPERLESS_EMAIL_HOST_USER=<str>`](#PAPERLESS_EMAIL_HOST_USER) {#PAPERLESS_EMAIL_HOST_USER}

: Defaults to ''.

#### [`PAPERLESS_EMAIL_FROM=<str>`](#PAPERLESS_EMAIL_FROM) {#PAPERLESS_EMAIL_FROM}

: Defaults to PAPERLESS_EMAIL_HOST_USER if not set.

#### [`PAPERLESS_EMAIL_HOST_PASSWORD=<str>`](#PAPERLESS_EMAIL_HOST_PASSWORD) {#PAPERLESS_EMAIL_HOST_PASSWORD}

: Defaults to ''.

#### [`PAPERLESS_EMAIL_USE_TLS=<bool>`](#PAPERLESS_EMAIL_USE_TLS) {#PAPERLESS_EMAIL_USE_TLS}

: Defaults to false.

#### [`PAPERLESS_EMAIL_USE_SSL=<bool>`](#PAPERLESS_EMAIL_USE_SSL) {#PAPERLESS_EMAIL_USE_SSL}

: Defaults to false.
