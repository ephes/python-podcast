Deploy
========

Staging and production deployments run through ops-control (SOPS-backed). The local ``deploy/``
directory is kept as a legacy reference.

Deployment Commands
-------------------

Deploy to staging (ops-control)::

    uv run python commands.py deploy_staging

Deploy to production (ops-control)::

    OPS_CONTROL=/path/to/ops-control \
    SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
    uv run python commands.py deploy_production

From Justfile::

    just deploy-staging
    just deploy-production

Ops-control Prerequisites
-------------------------

* An ops-control clone (set ``OPS_CONTROL`` if not located at ``../ops-control``)
* SOPS age key configured (``SOPS_AGE_KEY_FILE`` defaults to ``~/.config/sops/age/keys.txt``)
* ``PROJECTS_ROOT`` pointing at the parent directory that contains this repo
