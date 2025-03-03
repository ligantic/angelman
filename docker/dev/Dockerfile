# FROM muccg/rdrf-builder
FROM python:3.9 as builder

ENV PYTHONUNBUFFERED 1

RUN apt-get update && apt-get install -y --no-install-recommends \
  # TODO check if requirements are needed
  # Base
  gettext \
  libpcre3 \
  libpq5 \
  mime-support \
  nodejs \
  unixodbc \

  # Builder
  build-essential \
  git \
  gzip \
  libpcre3-dev \
  libpq-dev \
  libssl-dev \
  libyaml-dev \
  unixodbc-dev \
  zlib1g-dev \
  && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN mkdir -p /requirements/rdrf
WORKDIR /requirements

# RUN env | sort

# Add our python deps in multiple docker layers
# hgvs was failing due to lack of nose, hence the order

COPY requirements/* ./
COPY rdrf/requirements/* ./rdrf/

COPY rdrf/clients ./clients

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools \
    && pip install -r rdrf/requirements.txt \
    && pip install -r rdrf/dev-requirements.txt \
    && pip install -r rdrf/test-requirements.txt \
    && pip install -r requirements.txt \
    && pip install -r dev-requirements.txt \
    && pip install -r test-requirements.txt

VOLUME ["/data"]

FROM python:3.9-slim

ENV PYTHONPATH="/app/rdrf/rdrf/:/app/angelman/"
ENV DJANGO_SETTINGS_MODULE angelman.settings
ENV STATIC_ROOT="/data/static"
ENV WRITABLE_DIRECTORY="/data/scratch"
ENV LOCALE_PATHS="/app/translations/locale"
ENV LOG_DIRECTORY="/data/log"
ENV MEDIA_ROOT="/data/static/media"

# RUN apt-get update && apt-get install -y --no-install-recommends \
#    libxml2 \
#   && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN apt-get update && apt-get install -y --no-install-recommends \
  # Base
  # TODO check if requirements are needed
  gettext \
  libpcre3 \
  libpq5 \
  mime-support \
  nodejs \
  postgresql-client \
  unixodbc \
  libmagic1 \
  git \
  && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN mkdir -p /requirements/rdrf/
WORKDIR /requirements

COPY --from=builder /requirements/ .

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r rdrf/requirements.txt \
    && pip install -r rdrf/dev-requirements.txt \
    && pip install -r rdrf/test-requirements.txt \
    && pip install -r requirements.txt \
    && pip install -r dev-requirements.txt \
    && pip install -r test-requirements.txt

RUN rm -Rf /root/.cache

COPY docker/dev/docker-entrypoint.sh /
RUN chmod +x /docker-entrypoint.sh

COPY docker/dev/lambda/aws-lambda-rie /
RUN chmod +x /aws-lambda-rie

VOLUME ["/app", "/data"]

ENV HOME /data
WORKDIR /data

EXPOSE 8000

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["runserver_plus"]
