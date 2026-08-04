FROM mcr.microsoft.com/devcontainers/python:3.13

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gettext \
        git \
        libmagic1 \
        libpq-dev \
        libssl-dev \
        libyaml-dev \
        nodejs \
        unixodbc-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY rdrf/requirements/ /tmp/requirements/
COPY rdrf/clients/ /tmp/requirements/clients/

WORKDIR /tmp/requirements

RUN python -m pip install --no-cache-dir --upgrade pip setuptools \
    && python -m pip install --no-cache-dir \
        -r /tmp/requirements/requirements.txt \
        -r /tmp/requirements/dev-requirements.txt \
        -r /tmp/requirements/test-requirements.txt \
    && rm -rf /tmp/requirements

USER vscode