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
