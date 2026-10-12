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

If the local database already exists, the command refuses to run before it contacts
the server. Replacing existing local data has to be confirmed explicitly:

.. code-block:: console

   $ uv run commands.py production-db-to-local --replace-existing

To keep the development database untouched, restore into a separate database
instead, for example to inspect production data:

.. code-block:: console

   $ uv run commands.py production-db-to-local --local-db-name python_podcast_prod
   $ psql python_podcast_prod

How the restore protects local data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The existing database is never dropped before its replacement is complete:

1. The dump is saved to ``backups/`` and checked: it has to be a complete gzip file
   that ends with the ``pg_dump`` completion marker.
2. It is loaded into the staging database ``<name>_restore_staging`` with
   ``psql -v ON_ERROR_STOP=1``, so the first SQL error aborts the load. A failed
   load drops the staging database and leaves ``<name>`` untouched.
3. Only after a complete load the existing database is renamed to
   ``<name>_restore_previous``, the staging database is renamed to ``<name>`` and
   the previous copy is dropped last. The renames need all connections to the
   database to be closed; if one fails, the old database is put back under its name.

Database names have to be lowercase letters, digits and underscores.

If a restore is interrupted (for example the machine goes to sleep or the process is
killed), the next run refuses to start and names the leftover database:

* ``<name>_restore_staging`` only holds restored dump data. Remove it with
  ``dropdb <name>_restore_staging`` and rerun.
* ``<name>_restore_previous`` holds the previous local data. If ``<name>`` is
  missing, bring it back with
  ``psql -d postgres -c "ALTER DATABASE <name>_restore_previous RENAME TO <name>"``.
  If ``<name>`` is fine, remove the copy with ``dropdb <name>_restore_previous``.

The downloaded dump stays in ``backups/`` in every case.

Do not use ``uvx honcho start postgres`` for this restore flow; the restore
command intentionally exits when it sees a running ``honcho`` process.

To override the SSH host or database names, see:

.. code-block:: console

   $ uv run commands.py production-db-to-local --help

Work on local package checkouts
-------------------------------

``django-cast``, ``cast-bootstrap5``, ``cast-vue`` and ``django-indieweb`` are
installed from Git by default. Two commands rewrite their entries in
``[tool.uv.sources]`` of ``pyproject.toml`` and then run ``uv sync``:

.. code-block:: console

   $ uv run commands.py switch-to-dev-environment   # editable ../<package> checkouts
   $ uv run commands.py switch-to-git-sources       # back to the Git sources

``switch-to-dev-environment`` only switches packages whose checkout exists next
to this repository.

What happens to ``pyproject.toml``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* A replaced entry is removed completely, also when its value spans several
  lines (an array of sources with markers, for example) or its key is quoted.
  Other tables, other source entries and comments are kept byte for byte.
* The new document is parsed before the file is replaced. It has to be valid
  TOML, contain the requested sources and differ from the old document in
  nothing else. Otherwise the command exits with status 1 and
  ``pyproject.toml`` keeps its original bytes. This also applies to a
  ``pyproject.toml`` that is already invalid, and to sources written as dotted
  keys (``django-cast.git = ...``) or sub-tables
  (``[tool.uv.sources.django-cast]``); convert those to ``name = { ... }``
  entries first.
* The check uses Python's ``tomllib`` (TOML 1.0). An inline table that is spread
  over several lines is TOML 1.1 and is refused in the same way.
* The file is replaced atomically, so an interrupted run leaves either the old
  or the new file.

When ``uv sync`` fails
~~~~~~~~~~~~~~~~~~~~~~

If ``uv sync`` exits with an error or cannot be started, the command exits with
status 1 and does not report success. ``pyproject.toml`` is **not** rolled
back: it keeps the new source entries while the installed environment is still
the old one. Fix the cause (a missing checkout, an unreachable Git remote, an
incompatible dependency) and run the same command again, or run the opposite
switch command to go back.
