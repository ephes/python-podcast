FROM python:3.7.2-slim

ENV PYTHONUNBUFFERED 1

# being able to use apt
RUN apt update
RUN apt -y upgrade

# git
RUN apt -y install git gcc

# postgres client
RUN apt -y install libpq-dev

# use bash (pipefail option)
RUN apt -y install bash
RUN chsh -s /bin/bash

# Requirements are installed here to ensure they will be cached.
COPY ./requirements /requirements
RUN pip install --upgrade pip
RUN pip install -r /requirements/local.txt

COPY ./compose/production/django/entrypoint /entrypoint
RUN sed -i 's/\r//' /entrypoint
RUN chmod +x /entrypoint

COPY ./compose/local/django/start /start
RUN sed -i 's/\r//' /start
RUN chmod +x /start

WORKDIR /app

ENV DJANGO_READ_DOT_ENV_FILE=True

ENTRYPOINT ["/entrypoint"]
