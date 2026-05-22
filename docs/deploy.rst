Deploy
========

Staging and production deployments run through ops-control (SOPS-backed). The local ``deploy/``
directory is kept as a legacy reference.

Deployment Commands
-------------------

Deploy to staging via ops-control::

    just deploy-staging

Deploy to production via ops-control::

    just deploy-production

The deploy recipes first install/update Ansible collections and the local ``ops-library``
collection via ``uvx ansible-galaxy``. They also install ``community.postgresql`` explicitly
because current ops-control roles require it. The recipes support overriding the launcher
commands when needed::

    ANSIBLE_PLAYBOOK_CMD="uvx --from ansible-core ansible-playbook" just deploy-staging

    ANSIBLE_GALAXY_CMD="uvx --from ansible-core ansible-galaxy" just deploy-staging

Ops-control Prerequisites
-------------------------

* An ops-control clone (set ``OPS_CONTROL`` if not located at ``../ops-control``)
* An ops-library clone (set ``OPS_LIBRARY_PATH`` if not located at ``$PROJECTS_ROOT/ops-library``)
* SOPS age key configured (``SOPS_AGE_KEY_FILE`` defaults to ``~/.config/sops/age/keys.txt``)
* ``PROJECTS_ROOT`` pointing at the parent directory that contains this repo
* ``uv`` installed locally; the just recipes run ``uvx --from ansible-core ansible-playbook``

Transcript Worker
-----------------

Voxhelm transcript generation from Wagtail admin queues completion work on the
``cast_transcripts`` Django Tasks database backend. The ops-control
``deploy-python-podcast.yml`` playbook enables a managed systemd worker in
addition to Gunicorn::

    uv run python manage.py db_worker --backend cast_transcripts --worker-id python-podcast-transcripts

The worker service uses the ``cast_transcripts`` backend alias and the stable
``python-podcast-transcripts`` worker id. The worker requires the
``django_tasks_db`` migrations to have been applied before it starts processing
jobs. Full-episode Voxhelm diarization can exceed django-cast's default polling
window, so this project sets ``CAST_VOXHELM_POLL_TIMEOUT`` to six hours by
default.

Voxhelm credentials should be supplied through deployment-managed environment
variables rather than relying on the Wagtail database token field. Configure
``CAST_VOXHELM_API_BASE`` and ``CAST_VOXHELM_API_KEY`` in the shared
environment used by both Gunicorn and the transcript worker; the Wagtail
``Voxhelm settings`` token field may stay blank when the token comes from
deployment secrets.
