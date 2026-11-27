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

Legacy transfer helper
----------------------

Prefer ``commands.py production-db-to-local`` for current installations. The
independent ``python -m scripts.prod_to_local`` helper is retained for the legacy
``site/scripts/prod_backup.py`` producer. Importing it performs no work. It reads
``PRODUCTION_HOST``, ``PRODUCTION_USERNAME``, ``DATABASE_NAME`` and ``POSTGRES_USER``
from the environment (or ``.env`` when explicitly run). Database names follow the
maintained restore allowance: lowercase letters/digits/underscores, starting with
a letter or underscore, at most 46 characters; role names allow 63 characters.

Start local PostgreSQL yourself and provision the connection role beforehand.
The helper no longer starts/stops Docker, creates roles or attempts a second SQL
restore. ``POSTGRES_USER`` becomes ``PGUSER`` only in the restore child process;
connection, permission and database-creation errors stop the operation. An existing
role is used as-is, never inferred from a failed ``createuser`` command. The helper
calls ``commands.py restore-local-dump`` with a literal absolute file argument;
that command owns gzip/SQL validation, staging and recovery described above.
An existing database is refused unless ``--replace-existing`` is explicitly passed.
Before contacting production, the helper runs ``commands.py check-local-restore``
with the same database name, role and confirmation. It changes nothing; an
unconfirmed existing database, a leftover staging/recovery database or a running
honcho stops the run before any remote backup is produced or downloaded.
Downloaded dumps are retained when the local restore fails.

Transfer admission and recovery
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The legacy helper uses Paramiko from the locked development dependencies and
requires a POSIX main thread without an already active real-time alarm. It uses
system SSH known-host keys and refuses unknown keys. The fixed remote producer
command must exit successfully and emit exactly one standalone line of this form::

    scp python-podcast:site/backups/backup_NAME.sql.gz backups

Only a basename starting with a letter, digit or underscore, followed by letters,
digits, underscores, dots or hyphens and ending in ``.sql.gz``, is admitted (at most
188 characters). Both output streams together are limited to 64 KiB. Other paths,
host aliases, shell syntax and ambiguous announcements are refused.

Connection/authentication has a 30-second overall deadline, producer/channel work
60 seconds, SFTP acquisition/download 300 seconds and gzip validation another
300 seconds. Every transport close has its own 5-second deadline; all finalizers
are attempted, and any close failure prevents publication and restore. These
POSIX alarms bound whole phases even when a peer keeps sending small chunks.

The remote file must be regular, nonempty and at most 1 GiB compressed. Its size,
mode and modification time must agree before and after the read. SFTP bytes go
into an exclusive 0600 file within a private 0700 staging directory. The received
byte count and flushed staging file size must match the remote size. A short
write aborts the download. Gzip integrity, at most 4 GiB of expanded SQL and the final
``pg_dump`` completion marker are checked before atomic publication in
``backups/``. The authenticated producer and these completeness checks establish
admission; there is no independent remote content digest or immutable snapshot.

A final filename is never overwritten, including when it is a symlink. A collision
refuses the run and preserves the old bytes; request a newly named remote backup
for a later attempt. Failure removes only the private stage and causes no local
Docker/database work. A complete published backup remains available if the later
maintained SQL restore fails. Do not run the helper in tests: its regression suite
uses only fake SSH/SFTP/process boundaries and synthetic gzip data.

Work on local package checkouts
-------------------------------

``django-cast``, ``cast-bootstrap5``, ``cast-vue`` (pinned to the redesign
commit ``f71c75d``), ``cast-react`` (from a version tag) and
``django-indieweb`` are installed from Git by default. Two commands rewrite
their entries in ``[tool.uv.sources]`` of ``pyproject.toml`` and then run
``uv sync``:

.. code-block:: console

   $ uv run commands.py switch-to-dev-environment   # editable ../<package> checkouts
   $ uv run commands.py switch-to-git-sources       # back to the Git sources

``switch-to-dev-environment`` only switches packages whose checkout exists next
to this repository.

Concurrent switches
~~~~~~~~~~~~~~~~~~~

Both commands hold the same project-local ``.source-switch.lock`` from before
reading ``pyproject.toml`` through atomic replacement, ``uv sync`` and the
success report. A second switch waits, so each sync sees the sources selected
by its own operation. The stable sidecar is ignored by Git; do not remove it
while a switch is running. A failed sync releases the lock and retains the
new sources for the recovery procedure below. Independent invocations of
``uv sync`` and manual edits do not participate in this lock.

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

``uv run`` syncs the environment from ``pyproject.toml`` before it starts
``commands.py``. With sources that cannot be installed it fails in the same way
and the command never starts. Recover with ``--no-sync``, which runs the
command in the environment as it is:

.. code-block:: console

   $ uv run --no-sync commands.py switch-to-git-sources


Unreleased
----------

* Serialize development/Git source switches across source admission, publication
  and environment sync, retaining explicit failed-sync recovery.
