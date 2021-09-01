FROM python:3.9.7-buster

ENV PYTHONUNBUFFERED 1

RUN apt-get update \
  && apt -y upgrade \
  # postgres client psql for python manage.py dbshell
  && apt-get install -y postgresql-client \
  # gettexts for compilemessages + fluent comments
  && apt-get install -y gettext \
  # ffmpeg/ffprobe for audio length etc
  && apt-get install -y ffmpeg \
  && rm -rf /var/lib/apt/lists/*

# Add django user
RUN addgroup --system django \
    && adduser --system --ingroup django django

# Install Poetry
RUN curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python \
    && mkdir -p /etc/bash_completion.d \
    && /root/.poetry/bin/poetry completions bash > /etc/bash_completion.d/poetry.bash-completion

# Project Initialization
COPY poetry.lock pyproject.toml /app/
WORKDIR /app
RUN /root/.poetry/bin/poetry config virtualenvs.create false \
    && /root/.poetry/bin/poetry install --no-interaction --no-ansi --no-root --no-dev

# django-imagekit workaround (exception on save)
RUN python -m pip uninstall -y django-imagekit \
    && python -m pip install git+https://github.com/ephes/django-imagekit

COPY ./compose/production/django/entrypoint /entrypoint
RUN sed -i 's/\r//' /entrypoint
RUN chmod +x /entrypoint
RUN chown django /entrypoint

COPY ./compose/production/django/start /start
RUN sed -i 's/\r//' /start
RUN chmod +x /start
RUN chown django /start

COPY ./compose/production/django/bashrc /home/django/.bashrc

COPY . /app

RUN chown -R django /app

USER django

WORKDIR /app

ENTRYPOINT ["/entrypoint"]
