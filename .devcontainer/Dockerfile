# syntax=docker/dockerfile:1

FROM --platform=$BUILDPLATFORM docker.io/node:20-bookworm-slim as main-app

ARG DEBIAN_FRONTEND=noninteractive

# Buildx provided, must be defined to use though
ARG TARGETARCH

# Can be workflow provided, defaults set for manual building
ARG JBIG2ENC_VERSION=0.29
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
  poppler-utils \
  htop \
  sudo"

# Install basic runtime packages.
# These change very infrequently
RUN set -eux \
  echo "Installing system packages" \
    && apt-get update \
    && apt-get install --yes --quiet --no-install-recommends ${RUNTIME_PACKAGES}

ARG PYTHON_PACKAGES="ca-certificates"

RUN set -eux \
  echo "Installing python packages" \
    && apt-get update \
    && apt-get install --yes --quiet ${PYTHON_PACKAGES}

COPY --from=ghcr.io/astral-sh/uv:0.4 /uv /bin/uv

RUN set -eux \
  && echo "Installing pre-built updates" \
    && echo "Installing qpdf ${QPDF_VERSION}" \
      && curl --fail --silent --show-error --location \
        --output libqpdf29_${QPDF_VERSION}-1_${TARGETARCH}.deb \
        https://github.com/paperless-ngx/builder/releases/download/qpdf-${QPDF_VERSION}/libqpdf29_${QPDF_VERSION}-1_${TARGETARCH}.deb \
      && curl --fail --silent --show-error --location \
        --output qpdf_${QPDF_VERSION}-1_${TARGETARCH}.deb \
        https://github.com/paperless-ngx/builder/releases/download/qpdf-${QPDF_VERSION}/qpdf_${QPDF_VERSION}-1_${TARGETARCH}.deb \
      && dpkg --install ./libqpdf29_${QPDF_VERSION}-1_${TARGETARCH}.deb \
      && dpkg --install ./qpdf_${QPDF_VERSION}-1_${TARGETARCH}.deb \
    && echo "Installing Ghostscript ${GS_VERSION}" \
      && curl --fail --silent --show-error --location \
          --output libgs10_${GS_VERSION}.dfsg-1_${TARGETARCH}.deb \
          https://github.com/paperless-ngx/builder/releases/download/ghostscript-${GS_VERSION}/libgs10_${GS_VERSION}.dfsg-1_${TARGETARCH}.deb \
      && curl --fail --silent --show-error --location \
          --output ghostscript_${GS_VERSION}.dfsg-1_${TARGETARCH}.deb \
          https://github.com/paperless-ngx/builder/releases/download/ghostscript-${GS_VERSION}/ghostscript_${GS_VERSION}.dfsg-1_${TARGETARCH}.deb \
      && curl --fail --silent --show-error --location \
          --output libgs10-common_${GS_VERSION}.dfsg-1_all.deb \
          https://github.com/paperless-ngx/builder/releases/download/ghostscript-${GS_VERSION}/libgs10-common_${GS_VERSION}.dfsg-1_all.deb \
        && dpkg --install ./libgs10-common_${GS_VERSION}.dfsg-1_all.deb \
        && dpkg --install ./libgs10_${GS_VERSION}.dfsg-1_${TARGETARCH}.deb \
        && dpkg --install ./ghostscript_${GS_VERSION}.dfsg-1_${TARGETARCH}.deb \
    && echo "Installing jbig2enc" \
      && curl --fail --silent --show-error --location \
        --output jbig2enc_${JBIG2ENC_VERSION}-1_${TARGETARCH}.deb \
        https://github.com/paperless-ngx/builder/releases/download/jbig2enc-${JBIG2ENC_VERSION}/jbig2enc_${JBIG2ENC_VERSION}-1_${TARGETARCH}.deb \
      && dpkg --install ./jbig2enc_${JBIG2ENC_VERSION}-1_${TARGETARCH}.deb

# setup docker-specific things
# These change sometimes, but rarely
WORKDIR /usr/src/paperless/src/docker/

COPY --chown=root:root [ \
  "docker/imagemagick-policy.xml", \
  "/etc/ImageMagick-6/policy.xml" \
]

COPY --from=ghcr.io/astral-sh/uv:0.4 /uv /bin/uv

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

# hadolint ignore=DL3042
RUN --mount=type=cache,target=/root/.cache/uv,id=pip-cache \
  set -eux \
  && echo "Installing build system packages" \
    && apt-get update \
    && apt-get install --yes --quiet ${BUILD_PACKAGES}

RUN set -eux \
  && npm update npm -g

# add users, setup scripts
# Mount the compiled frontend to expected location
RUN set -eux \
  && echo "Setting up user/group" \
    && groupmod --new-name paperless node \
    && usermod --login paperless --home /usr/src/paperless node \
    && usermod -s /bin/bash paperless \
    && echo "paperless ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers \
  && echo "Creating volume directories" \
    && mkdir --parents --verbose /usr/src/paperless/paperless-ngx/data \
    && mkdir --parents --verbose /usr/src/paperless/paperless-ngx/media \
    && mkdir --parents --verbose /usr/src/paperless/paperless-ngx/consume \
    && mkdir --parents --verbose /usr/src/paperless/paperless-ngx/export \
    && mkdir --parents --verbose /usr/src/paperless/paperless-ngx/.venv \
  && echo "Adjusting all permissions" \
    && chown --from root:root --changes --recursive paperless:paperless /usr/src/paperless

VOLUME ["/usr/src/paperless/paperless-ngx/data", \
        "/usr/src/paperless/paperless-ngx/media", \
        "/usr/src/paperless/paperless-ngx/consume", \
        "/usr/src/paperless/paperless-ngx/export", \
        "/usr/src/paperless/paperless-ngx/.venv"]
