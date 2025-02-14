# syntax=docker/dockerfile:1
# https://github.com/moby/buildkit/blob/master/frontend/dockerfile/docs/reference.md

# Stage: compile-frontend
# Purpose: Compiles the frontend
# Notes:
#  - Does NPM stuff with Typescript and such
FROM --platform=$BUILDPLATFORM docker.io/node:20-bookworm-slim AS compile-frontend

COPY ./src-ui /src/src-ui

WORKDIR /src/src-ui
RUN set -eux \
  && npm update npm -g \
  && npm ci

ARG PNGX_TAG_VERSION=
# Add the tag to the environment file if its a tagged dev build
RUN set -eux && \
case "${PNGX_TAG_VERSION}" in \
  dev|beta|fix*|feature*) \
    sed -i -E "s/version: '([0-9\.]+)'/version: '\1 #${PNGX_TAG_VERSION}'/g" /src/src-ui/src/environments/environment.prod.ts \
    ;; \
esac

RUN set -eux \
  && ./node_modules/.bin/ng build --configuration production

# Stage: pipenv-base
# Purpose: Generates a requirements.txt file for building
# Comments:
#  - pipenv dependencies are not left in the final image
#  - pipenv can't touch the final image somehow
FROM --platform=$BUILDPLATFORM docker.io/python:3.12-alpine AS pipenv-base

WORKDIR /usr/src/pipenv

COPY Pipfile* ./

RUN set -eux \
  && echo "Installing pipenv" \
    && python3 -m pip install --no-cache-dir --upgrade pipenv==2024.4.1 \
  && echo "Generating requirement.txt" \
    && pipenv requirements > requirements.txt

# Stage: s6-overlay-base
# Purpose: Installs s6-overlay and rootfs
# Comments:
#  - Don't leave anything extra in here either
FROM docker.io/python:3.12-slim-bookworm AS s6-overlay-base

WORKDIR /usr/src/s6

# https://github.com/just-containers/s6-overlay#customizing-s6-overlay-behaviour
ENV \
    S6_BEHAVIOUR_IF_STAGE2_FAILS=2 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0 \
    S6_VERBOSITY=1 \
    PATH=/command:$PATH

# Buildx provided, must be defined to use though
ARG TARGETARCH
ARG TARGETVARIANT
# Lock this version
ARG S6_OVERLAY_VERSION=3.2.0.2

ARG S6_BUILD_TIME_PKGS="curl \
                        xz-utils"

RUN set -eux \
    && echo "Installing build time packages" \
      && apt-get update \
      && apt-get install --yes --quiet --no-install-recommends ${S6_BUILD_TIME_PKGS} \
    && echo "Determining arch" \
      && S6_ARCH="" \
      && if [ "${TARGETARCH}${TARGETVARIANT}" = "amd64" ]; then S6_ARCH="x86_64"; \
      elif [ "${TARGETARCH}${TARGETVARIANT}" = "arm64" ]; then S6_ARCH="aarch64"; fi\
      && if [ -z "${S6_ARCH}" ]; then { echo "Error: Not able to determine arch"; exit 1; }; fi \
    && echo "Installing s6-overlay for ${S6_ARCH}" \
      && curl --fail --silent --no-progress-meter --show-error --location --remote-name-all --parallel --parallel-max 4 \
        "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz" \
        "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz.sha256" \
        "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${S6_ARCH}.tar.xz" \
        "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${S6_ARCH}.tar.xz.sha256" \
      && echo "Validating s6-archive checksums" \
        && sha256sum --check ./*.sha256 \
      && echo "Unpacking archives" \
        && tar --directory / -Jxpf s6-overlay-noarch.tar.xz \
        && tar --directory / -Jxpf s6-overlay-${S6_ARCH}.tar.xz \
      && echo "Removing downloaded archives" \
        && rm ./*.tar.xz \
        && rm ./*.sha256 \
    && echo "Cleaning up image" \
      && apt-get --yes purge ${S6_BUILD_TIME_PKGS} \
      && apt-get --yes autoremove --purge \
      && rm -rf /var/lib/apt/lists/*

# Copy our service defs and filesystem
COPY ./docker/rootfs /

# Stage: main-app
# Purpose: The final image
# Comments:
#  - Don't leave anything extra in here
FROM s6-overlay-base AS main-app

LABEL org.opencontainers.image.authors="paperless-ngx team <hello@paperless-ngx.com>"
LABEL org.opencontainers.image.documentation="https://docs.paperless-ngx.com/"
LABEL org.opencontainers.image.source="https://github.com/paperless-ngx/paperless-ngx"
LABEL org.opencontainers.image.url="https://github.com/paperless-ngx/paperless-ngx"
LABEL org.opencontainers.image.licenses="GPL-3.0-only"

ARG DEBIAN_FRONTEND=noninteractive

# Buildx provided, must be defined to use though
ARG TARGETARCH

# Can be workflow provided, defaults set for manual building
ARG JBIG2ENC_VERSION=0.30
ARG QPDF_VERSION=11.9.0
ARG GS_VERSION=10.03.1

# Set Python environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Ignore warning from Whitenoise
    PYTHONWARNINGS="ignore:::django.http.response:517" \
    PNGX_CONTAINERIZED=1

#
# Begin installation and configuration
# Order the steps below from least often changed to most
#

# Packages need for running
ARG RUNTIME_PACKAGES="\
  # General utils
  curl \
  # Docker specific
  gosu \
  # Timezones support
  tzdata \
  # fonts for text file thumbnail generation
  fonts-liberation \
  gettext \
  ghostscript \
  gnupg \
  icc-profiles-free \
  imagemagick \
  # PostgreSQL
  postgresql-client \
  # MySQL / MariaDB
  mariadb-client \
  # OCRmyPDF dependencies
  tesseract-ocr \
  tesseract-ocr-eng \
  tesseract-ocr-deu \
  tesseract-ocr-fra \
  tesseract-ocr-ita \
  tesseract-ocr-spa \
  unpaper \
  pngquant \
  jbig2dec \
  # lxml
  libxml2 \
  libxslt1.1 \
  # itself
  qpdf \
  # Mime type detection
  file \
  libmagic1 \
  media-types \
  zlib1g \
  # Barcode splitter
  libzbar0 \
  poppler-utils"

# Install basic runtime packages.
# These change very infrequently
RUN set -eux \
  echo "Installing system packages" \
    && apt-get update \
    && apt-get install --yes --quiet --no-install-recommends ${RUNTIME_PACKAGES} \
    && echo "Installing pre-built updates" \
      && curl --fail --silent --no-progress-meter --show-error --location --remote-name-all --parallel --parallel-max 4 \
        https://github.com/paperless-ngx/builder/releases/download/qpdf-${QPDF_VERSION}/libqpdf29_${QPDF_VERSION}-1_${TARGETARCH}.deb \
        https://github.com/paperless-ngx/builder/releases/download/qpdf-${QPDF_VERSION}/qpdf_${QPDF_VERSION}-1_${TARGETARCH}.deb \
        https://github.com/paperless-ngx/builder/releases/download/ghostscript-${GS_VERSION}/libgs10_${GS_VERSION}.dfsg-1_${TARGETARCH}.deb \
        https://github.com/paperless-ngx/builder/releases/download/ghostscript-${GS_VERSION}/ghostscript_${GS_VERSION}.dfsg-1_${TARGETARCH}.deb \
        https://github.com/paperless-ngx/builder/releases/download/ghostscript-${GS_VERSION}/libgs10-common_${GS_VERSION}.dfsg-1_all.deb \
        https://github.com/paperless-ngx/builder/releases/download/jbig2enc-${JBIG2ENC_VERSION}/jbig2enc_${JBIG2ENC_VERSION}-1_${TARGETARCH}.deb \
      && echo "Installing qpdf ${QPDF_VERSION}" \
        && dpkg --install ./libqpdf29_${QPDF_VERSION}-1_${TARGETARCH}.deb \
        && dpkg --install ./qpdf_${QPDF_VERSION}-1_${TARGETARCH}.deb \
      && echo "Installing Ghostscript ${GS_VERSION}" \
        && dpkg --install ./libgs10-common_${GS_VERSION}.dfsg-1_all.deb \
        && dpkg --install ./libgs10_${GS_VERSION}.dfsg-1_${TARGETARCH}.deb \
        && dpkg --install ./ghostscript_${GS_VERSION}.dfsg-1_${TARGETARCH}.deb \
      && echo "Installing jbig2enc" \
        && dpkg --install ./jbig2enc_${JBIG2ENC_VERSION}-1_${TARGETARCH}.deb \
      && echo "Configuring imagemagick" \
        && cp /etc/ImageMagick-6/paperless-policy.xml /etc/ImageMagick-6/policy.xml \
      && echo "Cleaning up image layer" \
        && rm --force --verbose *.deb \
    && rm --recursive --force --verbose /var/lib/apt/lists/*

# Copy webserver config
# Changes very infrequently
WORKDIR /usr/src/paperless/
COPY --chown=1000:1000 webserver.py /usr/src/paperless/webserver.py

WORKDIR /usr/src/paperless/src/

# Python dependencies
# Change pretty frequently
COPY --chown=1000:1000 --from=pipenv-base /usr/src/pipenv/requirements.txt ./

# Packages needed only for building a few quick Python
# dependencies
ARG BUILD_PACKAGES="\
  build-essential \
  git \
  # https://www.psycopg.org/docs/install.html#prerequisites
  libpq-dev \
  # https://github.com/PyMySQL/mysqlclient#linux
  default-libmysqlclient-dev \
  pkg-config"

ARG ZXING_VERSION=2.3.0
ARG PSYCOPG_VERSION=3.2.4

# hadolint ignore=DL3042
RUN --mount=type=cache,target=/root/.cache/pip/,id=pip-cache \
  set -eux \
  && echo "Installing build system packages" \
    && apt-get update \
    && apt-get install --yes --quiet --no-install-recommends ${BUILD_PACKAGES} \
    && python3 -m pip install --upgrade wheel \
  && echo "Installing Python requirements" \
    && curl --fail --silent --no-progress-meter --show-error --location --remote-name-all --parallel --parallel-max 4 \
      https://github.com/paperless-ngx/builder/releases/download/psycopg-${PSYCOPG_VERSION}/psycopg_c-${PSYCOPG_VERSION}-cp312-cp312-linux_x86_64.whl \
      https://github.com/paperless-ngx/builder/releases/download/psycopg-${PSYCOPG_VERSION}/psycopg_c-${PSYCOPG_VERSION}-cp312-cp312-linux_aarch64.whl \
      https://github.com/paperless-ngx/builder/releases/download/zxing-${ZXING_VERSION}/zxing_cpp-${ZXING_VERSION}-cp312-cp312-linux_aarch64.whl \
      https://github.com/paperless-ngx/builder/releases/download/zxing-${ZXING_VERSION}/zxing_cpp-${ZXING_VERSION}-cp312-cp312-linux_x86_64.whl \
    && python3 -m pip install --default-timeout=1000 --find-links . --requirement requirements.txt \
  && echo "Installing NLTK data" \
    && python3 -W ignore::RuntimeWarning -m nltk.downloader -d "/usr/share/nltk_data" snowball_data \
    && python3 -W ignore::RuntimeWarning -m nltk.downloader -d "/usr/share/nltk_data" stopwords \
    && python3 -W ignore::RuntimeWarning -m nltk.downloader -d "/usr/share/nltk_data" punkt_tab \
  && echo "Cleaning up image" \
    && apt-get --yes purge ${BUILD_PACKAGES} \
    && apt-get --yes autoremove --purge \
    && apt-get clean --yes \
    && rm --recursive --force --verbose *.whl \
    && rm --recursive --force --verbose /var/lib/apt/lists/* \
    && rm --recursive --force --verbose /tmp/* \
    && rm --recursive --force --verbose /var/tmp/* \
    && rm --recursive --force --verbose /var/cache/apt/archives/* \
    && truncate --size 0 /var/log/*log

# copy backend
COPY --chown=1000:1000 ./src ./

# copy frontend
COPY --from=compile-frontend --chown=1000:1000 /src/src/documents/static/frontend/ ./documents/static/frontend/

# add users, setup scripts
# Mount the compiled frontend to expected location
RUN set -eux \
  && echo "Setting up user/group" \
    && addgroup --gid 1000 paperless \
    && useradd --uid 1000 --gid paperless --home-dir /usr/src/paperless paperless \
  && echo "Creating volume directories" \
    && mkdir --parents --verbose /usr/src/paperless/data \
    && mkdir --parents --verbose /usr/src/paperless/media \
    && mkdir --parents --verbose /usr/src/paperless/consume \
    && mkdir --parents --verbose /usr/src/paperless/export \
  && echo "Creating gnupg directory" \
    && mkdir -m700 --verbose /usr/src/paperless/.gnupg \
  && echo "Adjusting all permissions" \
    && chown --from root:root --changes --recursive paperless:paperless /usr/src/paperless \
  && echo "Collecting static files" \
    && s6-setuidgid paperless python3 manage.py collectstatic --clear --no-input --link \
    && s6-setuidgid paperless python3 manage.py compilemessages

VOLUME ["/usr/src/paperless/data", \
        "/usr/src/paperless/media", \
        "/usr/src/paperless/consume", \
        "/usr/src/paperless/export"]

ENTRYPOINT ["/init"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=5 CMD [ "curl", "-fs", "-S", "--max-time", "2", "http://localhost:8000" ]
