Install
=========

Prerequisites
-------------

Install the command line tools used by the development workflow:

* ``uv``
* ``just``
* PostgreSQL server/client binaries such as ``postgres``, ``initdb``,
  ``createdb``, ``dropdb``, ``createuser``, and ``psql``
* Real S3 media credentials in ``.env``:
  ``DJANGO_AWS_ACCESS_KEY_ID``, ``DJANGO_AWS_SECRET_ACCESS_KEY``,
  ``DJANGO_AWS_STORAGE_BUCKET_NAME``, and ``CLOUDFRONT_DOMAIN``

Local database
--------------

The project uses a repository-local PostgreSQL data directory at
``databases/postgres``. It is created automatically the first time you start
PostgreSQL through ``just``:

.. code-block:: console

   $ just postgres

The same bootstrap is used by the Procfile, so normal development startup also
works on a fresh machine:

.. code-block:: console

   $ just dev

Restore production data locally
-------------------------------

The production restore command fetches a fresh PostgreSQL dump over SSH from
``root@wersdoerfer.de`` and restores it into the local ``python_podcast``
database. It expects only PostgreSQL to be running locally. Start PostgreSQL
directly with ``just postgres`` in one terminal, then restore from another:

.. code-block:: console

   $ just postgres
   $ uv run commands.py production-db-to-local

Do not use ``uvx honcho start postgres`` for this restore flow; the restore
command intentionally exits when it sees a running ``honcho`` process.

The command no longer uses the legacy Ansible Vault files in ``deploy/``. To
override the SSH host or database names, see:

.. code-block:: console

   $ uv run commands.py production-db-to-local --help
