FROM python:3.8-buster

ENV PYTHONUNBUFFERED 1

RUN apt update \
  && apt -y upgrade \
  # postgres client psql for python manage.py dbshell
  && apt-get install -y postgresql-client \
  # gettexts for compilemessages + fluent comments
  && apt-get install -y gettext \
  # ffmpeg/ffprobe for audio length etc
  && apt-get install -y ffmpeg \
  # bash for pipefail option
  && apt -y install bash \
  && chsh -s /bin/bash

# Install Poetry
RUN curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python \
  && mkdir -p /etc/bash_completion.d \
  && /root/.poetry/bin/poetry completions bash > /etc/bash_completion.d/poetry.bash-completion

# Project Initialization
COPY poetry.lock pyproject.toml /app/
WORKDIR /app
RUN /root/.poetry/bin/poetry config virtualenvs.create false \
    && /root/.poetry/bin/poetry install --no-interaction --no-ansi --no-root

COPY ./compose/production/django/entrypoint /entrypoint
RUN sed -i 's/\r//' /entrypoint
RUN chmod +x /entrypoint

COPY ./compose/local/django/start /start
RUN sed -i 's/\r//' /start
RUN chmod +x /start

COPY ./compose/local/django/bashrc /root/.bashrc

WORKDIR /app

ENV DJANGO_READ_DOT_ENV_FILE=True

ENTRYPOINT ["/entrypoint"]
