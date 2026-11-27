Deploy
========

Staging and production deployments run through ops-control (SOPS-backed).

Registration
------------

Registration is closed by default in all environments. Set
``DJANGO_ACCOUNT_ALLOW_REGISTRATION=true`` in the deployment environment only
when public signup is intended. An unset value or ``false`` keeps signup closed.

Deployment Commands
-------------------

Deploy to staging via ops-control::

    just deploy-staging

Deploy to production via ops-control::

    just deploy-production

The recipes invoke ``just deploy-one python_podcast staging`` or
``just deploy-one python_podcast production`` inside ``OPS_CONTROL``. Current
ops-control metadata routes both hosts through pyinfra; do not bypass its guards
with direct Ansible commands. Update the controller before deploying.

``PROJECTS_ROOT`` defaults to this checkout's parent. The dispatcher selects
``$PROJECTS_ROOT/python-podcast``: keep that checkout name or explicitly select
the parent of the intended ``python-podcast`` source. Inspect the source status
and diff first: uncommitted local changes are included in deployment.
``OPS_LIBRARY_PATH`` and ``SOPS_AGE_KEY_FILE`` are forwarded, with spaces supported.
The legacy Ansible dispatcher branch selects its default SOPS key internally;
a custom forwarded key is effective on the pyinfra path.

For a legacy Ansible target, run ``just deploy-bootstrap`` when collections need
setup. Pyinfra does not require this bootstrap. The bootstrap launcher remains
configurable with ``ANSIBLE_GALAXY_CMD``; its default uses Python 3.14 because
ansible-core 2.21 does not start on Python 3.15.

Ops-control Prerequisites
-------------------------

* An updated ops-control clone (``OPS_CONTROL``, default ``~/projects/ops-control``)
* An ops-library clone (``OPS_LIBRARY_PATH``, default ``$PROJECTS_ROOT/ops-library``)
* SOPS age key configured (``SOPS_AGE_KEY_FILE``, default ``~/.config/sops/age/keys.txt``)
* ``PROJECTS_ROOT`` selecting the parent of the intended ``python-podcast`` source
* ``just`` and ``uv`` installed locally

Dependency Updates
------------------

``uv.lock`` pins exact versions and Git commits. django-cast tracks ``develop``
and can therefore include unreleased changes. Refresh within the constraints in
``pyproject.toml`` with ``uv lock --upgrade`` and ``uv sync --locked``; use
``uv lock --upgrade-package django-cast`` for a focused Cast update.

Run isolated application and migration checks in Bash or Zsh::

    (
        export DATABASE_URL=sqlite:///:memory:
        export LEGACY_DATABASE_URL=sqlite:///:memory:
        export DJANGO_SETTINGS_MODULE=config.settings.test
        uv run --locked pytest --create-db
        uv run --locked python manage.py makemigrations --check --dry-run
        uv run --locked python manage.py migrate --noinput
    )

Default pytest discovery includes both ``python_podcast`` and ``tests`` and
excludes browser tests through the existing marker setting. Add future test
roots to ``testpaths``. Browser tests need ffmpeg and the browser matching the
locked Playwright version; install it with ``uv run --locked playwright install
chromium`` and run ``just test-e2e``. Before deploying, also check the new frozen
environment with production settings and ``migrate --plan`` against PostgreSQL,
and retain a fresh database backup and the previous commit/lock for rollback.

2026-11-27 cast-vue f71c75d
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves cast-vue from ``caa13867`` to ``f71c75d5`` (Git commit, not
on PyPI; the version stays ``0.0.28``). Nothing else in the lock changed. No
migration and no settings change. The Vue.js router uses the path of an
absolute blog URL as its base; python-podcast delivers a path already, so its
pages behave as before. Static bundle only.

Rollback: as under "2026-11-18" below with the commit before this change,
including the clean static rebuild.

Deployed ``8f80cef`` on 2026-11-27 at 19:15 with ``just pyinfra-check
python_podcast production`` first, from an isolated clean ``PROJECTS_ROOT``
and ops-control ``14aae132`` (``caa1386`` itself went live at 18:43 as ``8ac3444``).
Verified after it in a browser with Vue.js chosen (phone and desktop, light and
dark): pages load ``cast_vue/main-BB-OyYTZ.js`` and ``main-DaiSgm8b.css``; the
footer sits on the page background with a hairline in the content column;
episode links are ``/show/<slug>/``; no console errors and no horizontal
overflow.

2026-11-27 cast-vue caa1386
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves cast-vue from ``7684476d`` to ``caa13867`` (Git commit, not
on PyPI; the version stays ``0.0.28``). Nothing else in the lock changed. No
migration and no settings change. The Vue.js footer no longer paints its own
band and full-width rule; it sits on the page background with a hairline in
the content column. CSS and the rebuilt static bundle only.

Rollback: as under "2026-11-18" below with the commit before this change,
including the clean static rebuild; a reader who chose Vue.js then sees the
``7684476`` footer again.

2026-11-27 cast-vue 7684476
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves cast-vue from ``062fa8e7`` to ``7684476d`` (Git commit, not
on PyPI; the version stays ``0.0.28``). Nothing else in the lock changed. No
migration and no settings change. The Vue.js theme gets a "Subscribe" link in
the header, a row of podcast app links on the archive and below the episode
player, follow links in the footer, and ``/show/feed/`` becomes a subscribe
page with app buttons and copyable feed URLs. Templates, a template tag and
static assets only.

Rollback: as under "2026-11-18" below with the commit before this change,
including the clean static rebuild; a reader who chose Vue.js then sees the
``062fa8e`` look again.

Deployed ``21c7320`` on 2026-11-27 at 18:22 with ``just pyinfra-check
python_podcast production`` first, from an isolated clean ``PROJECTS_ROOT``
and ops-control ``14aae132``. Verified after it in a browser with Vue.js chosen
(phone and desktop, light and dark): the header shows "Subscribe" and leads to
``/show/feed/``; the archive shows the app row (Apple Podcasts, Overcast,
Pocket Casts, Spotify, YouTube, RSS; phones show three plus "More options");
episodes show the subscribe line below the player; the footer lists Feeds,
Mastodon, LinkedIn and E-Mail; the feed page's Copy button puts the MP3 RSS
URL on the clipboard; no horizontal overflow and no console errors. The feed
page answers 200 in all themes.

2026-11-27 cast-vue 062fa8e
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves cast-vue from ``cdc53e40`` to ``062fa8e7`` (Git commit, not
on PyPI; the version stays ``0.0.28``). Nothing else in the lock changed. No
migration and no settings change. The Vue.js theme's sort and site theme
selects, footer, theme chooser page and filter controls are restyled; the
footer theme select shows the theme that renders the page and offers "Keep
this theme" from a ``?theme=vue`` preview. Static assets and templates only.

Rollback: as under "2026-11-18" below with the commit before this change,
including the clean static rebuild; a reader who chose Vue.js then sees the
``cdc53e4`` look again.

Deployed ``cd5ca3d`` on 2026-11-27 at 17:26 with ``just pyinfra-check
python_podcast production`` first (ops-control ``8ff629a4``). Verified after
it: pages under ``?theme=vue`` load ``cast_vue/main-CowE9Zwe.js``; in a browser
(phone and desktop, light and dark) the sort and footer theme selects show
the inset chevron, Oldest first and back reorders the list and survives a
reload, the footer select shows Vue.js under ``?theme=vue``, and the theme
chooser marks Vue.js as current, without console errors. The other themes
answer 200 unchanged.

2026-11-27 cast-react v0.0.9
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves cast-react from ``v0.0.8`` (``14dd4f6d``) to ``v0.0.9``
(``6eee93f4``, from its Git tag). Nothing else in the lock changed. No
migration and no settings change. In browsers with customizable selects
(current Chrome and Safari) the Month, Order and Site theme menus open on a
solid surface in the theme's light or dark colours instead of the translucent
system menu; older browsers keep their built-in menus. Static assets only.

Rollback: as under "2026-11-27 React theme (cast-react v0.0.3)" below, with the
commit before this change; a reader who chose React then sees the system
menus again.

Deployed ``bd11951`` on 2026-11-27 at 19:04 with ``just pyinfra-check python_podcast
production`` first, from an isolated clean ``PROJECTS_ROOT`` and a current
ops-control checkout. Verified after it in Chrome and Safari with React chosen
(phone and desktop, light and dark): the live page loads the 0.0.9 bundle, and
the Month and Site theme menus open on a solid surface in the page colours,
without console errors.

2026-11-27 cast-react v0.0.8
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves cast-react from ``v0.0.7`` (``78ecc24a``) to ``v0.0.8``
(``14dd4f6d``, from its Git tag). Nothing else in the lock changed. No
migration and no settings change. The header shows a labelled Subscribe link
(Feeds for written blogs), podcast blogs get app links (from
``CAST_FOLLOW_LINKS``; Overcast, Pocket Casts and Castro derived from the Apple
Podcasts id) on lists and episodes, the footer lists follow links, and the feed
page becomes a subscribe page. Static assets and templates only.

Rollback: as under "2026-11-27 React theme (cast-react v0.0.3)" below, with the
commit before this change; a reader who chose React then sees the 0.0.7
feed icon and plain feed page again.

Deployed ``628f7f3`` on 2026-11-27 at 18:35 with ``just pyinfra-check python_podcast
production`` first, from an isolated clean ``PROJECTS_ROOT`` and a current
ops-control checkout. Verified after it in a browser with React chosen (phone
and desktop, light and dark): the header shows the labelled Subscribe (podcast)
or Feeds (blog) link, podcast lists and episodes show the app links, the feed
page shows the copyable feed address, and the footer lists the follow links.
The other themes answer 200 unchanged.

2026-11-27 cast-react v0.0.7
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves cast-react from ``v0.0.6`` (``e9beabd0``) to ``v0.0.7``
(``78ecc24a``, from its Git tag). Nothing else in the lock changed. No
migration and no settings change. Dropdowns draw their own arrow with room
to the right edge; the footer Site theme menu aligns with the header, stacks
on phones and also appears on Django-rendered pages (feed, transcript, plain
pages), except on the full theme chooser. Static assets and templates only.

Rollback: as under "2026-11-27 React theme (cast-react v0.0.3)" below, with the
commit before this change; a reader who chose React then sees the 0.0.6
controls again.

Deployed ``1af22e4`` on 2026-11-27 at 17:57 with ``just pyinfra-check python_podcast
production`` first, from an isolated clean ``PROJECTS_ROOT`` and a current
ops-control checkout. Verified after it in a browser with React chosen (phone
and desktop, light and dark): on the episode list the month and order dropdowns and the
footer Site theme menu show the inset arrow; the footer lines up with the
header and stacks on phones; choosing another theme there reloads the same page
in that theme. The theme chooser page shows no duplicate footer menu.

2026-11-27 cast-react v0.0.6
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves cast-react from ``v0.0.5`` (``b82b43cb``) to ``v0.0.6``
(``e9beabd0``, from its Git tag). Nothing else in the lock changed. No
migration and no settings change. List rows show only the post's overview
with a "Read more" link to the post page; the post page shows overview and
detail. Static assets only.

Rollback: as under "2026-11-27 React theme (cast-react v0.0.3)" below, with the
commit before this change; a reader who chose React then sees the 0.0.5 list
again.

Deployed ``15918ae`` on 2026-11-27 at 17:17 with ``just pyinfra-check python_podcast
production`` first, from an isolated clean ``PROJECTS_ROOT``. Verified after
it: the host's ``uv.lock`` names cast-react ``v0.0.6``; the units are active
with ``NRestarts=0`` and their journal since the deploy holds no warning or
error. In a browser with React chosen (phone and desktop): the episode lists (first page, page 3, tag, month and search filters) and an episode
show only the overview with a Read more link, no detail part; the post page
shows overview and detail. The other themes answer 200 unchanged.

2026-11-27 cast-vue cdc53e4
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves cast-vue from ``785a147d`` to ``cdc53e40`` (Git commit, not
on PyPI; the version stays ``0.0.28``). Nothing else in the lock changed. No
migration and no settings change. The Vue.js theme's tag filter shows the
most-used tags with a tag search and an alphabetical index, the archive is a
year list that opens a year's months, and pages rendered by Django (feed page,
transcripts, theme chooser, error, flat and account pages) get the theme's
header, footer and styles. The blog list and post pages now extend the
theme's ``spa.html``; site templates that extend ``cast/vue/base.html`` with
``{% block content %}`` get the server-rendered layout. Static assets and
templates only.

Rollback: as under "2026-11-18" below with the commit before this change,
including the clean static rebuild; a reader who chose Vue.js then sees the
``785a147`` look again.

Deployed ``38505b7`` on 2026-11-27 at 14:26 with ``just pyinfra-check
python_podcast production`` first (ops-control ``6717d7a0``). Verified after
it: pages under ``?theme=vue`` load ``cast_vue/main-BV9bxGCU.js``; in a
browser with Vue.js chosen (phone and desktop, light and dark) the theme
chooser, the episode list with tag search and year filter, an episode, its
transcript, the feed page and Über uns/Impressum render in the theme's look
without console errors. The other themes answer 200 unchanged.

2026-11-27 cast-react v0.0.5
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves cast-react from ``v0.0.4`` (``8030bdad``) to ``v0.0.5``
(``b82b43cb``, from its Git tag). Nothing else in the lock changed. No
migration and no settings change. Tags and categories show the ten most-used
choices as pills; the rest open as a compact alphabetical index with counts
and a filter field. The custom date range folds below the month menu, list
rows show a cover only once, the phone header keeps navigation on one
scrolling line, and server pages use a centered column. Static assets only.

Rollback: as under "2026-11-27 React theme (cast-react v0.0.3)" below, with
the commit before this change; a reader who chose React then sees the 0.0.4
look again.

Deployed ``1d93174`` on 2026-11-27 at 14:00 with ``just pyinfra-check python_podcast
production`` first. Verified after it: the host's ``uv.lock`` names cast-react
``v0.0.5``; the units are active with ``NRestarts=0`` and their journal since
the deploy holds no warning or error. In a browser with React chosen (phone
and desktop, light and dark): the episode list with the tag filter, the feed page, a transcript, Über uns and the theme chooser render in the theme's look. The other
themes answer 200 unchanged.

2026-11-27 cast-react v0.0.4
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves cast-react from ``v0.0.3`` (``6a949de5``) to ``v0.0.4``
(``8030bdad``, from its Git tag). Nothing else in the lock changed. No
migration and no settings change. The release orders the tag and category
filters by post count (12 shown, the rest behind "Show all"), shows months as
one select grouped by year, and renders the feed page (``/show/feed/``),
transcript pages, the theme chooser and pages without a blog (Impressum,
Über uns, Datenschutz, account pages) with the theme's header and styles.
These pages load a small ``page`` entry from the same Vite manifest instead of
the React app; ``collectstatic`` picks it up. ``test_cast_react_theme.py``
checks for the new page layout instead of the old plain page.

Rollback: as under "2026-11-27 React theme (cast-react v0.0.3)" below, with
the commit before this change; a reader who chose React then sees the 0.0.3
look again.

Deployed ``e3f5502`` on 2026-11-27 at 13:13 with ``just pyinfra-check
python_podcast production`` first. Verified after it in a browser with React
chosen: the episode list with the filter panel, the feed page, a transcript,
Über uns and the theme chooser render in the theme's look.

2026-11-27 cast-vue redesign (785a147)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves cast-vue from ``b82a2e62`` to ``785a147d``. It stays at
``0.0.28`` and comes from the pinned Git commit (not on PyPI). The lockfile
changes are limited to the cast-vue source and its project dependency entry.
The package ships its built Vite bundle and
``cast_vue/static/cast_vue/manifest.json``. ``collectstatic`` picks them up and
production ``DJANGO_VITE`` reads ``staticfiles/cast_vue/manifest.json``. No
migration. The redesign uses the site's existing settings, URLs and template
configuration. cast-vue now requires django-cast ``>=0.2.55`` and Python
``>=3.11``. The lock has django-cast ``0.2.70`` and the project requires
Python ``>=3.12``.

Rollback: the sequence under "2026-11-18" below with the commit before this
change, including the clean static rebuild. Otherwise the Vite manifest
from the redesign can survive the rollback.

Deployed ``9390c20`` over ``d08c9f7`` on 2026-11-27 at 12:29. No task result
was ``READY`` or ``RUNNING`` before it; ``just pyinfra-check python_podcast
production`` showed the source sync and its dependent steps; ops-control ran
at ``6717d7a0``. Verified after it: the host's ``uv.lock`` names cast-vue
``785a147d``; ``staticfiles/cast_vue/manifest.json`` points at
``main-Col8ctVI.js``; both units are active with ``NRestarts=0``. In a
browser, choosing Vue.js on ``/select-theme/`` shows the new episode list
(search and filters in the side column) and an episode with the new player,
chapters and transcript; the player plays the episode and keeps playing in
the bottom bar after going back to the list. Choosing Python Podcast again
restores the previous look; the other themes answer 200 (``?theme=`` for pp,
bootstrap5, react, bootstrap4 and plain). The journal since the deploy holds
only known notices (old-URL 404s, the HEAD body notice, the worker's
graceful shutdown and the allauth deprecation warnings at worker start).
The largest live audio API response is 0.46 MB, below the 2 MiB limit of
the new player's JSON reader.

2026-11-27 React theme (cast-react v0.0.3)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` adds cast-react ``v0.0.3`` (``6a949de5``, from its Git tag; it is
not on PyPI). Nothing else in the lock changed. ``cast_react`` joins
``INSTALLED_APPS``, ``CAST_CUSTOM_THEMES`` offers it as "React" and the
production ``DJANGO_VITE`` reads its manifest from
``staticfiles/cast_react/manifest.json``. The package ships its built bundle,
so ``collectstatic`` picks it up and no Node.js build runs on the host. No
migration. No blog changes its theme: React is only used where a reader picks
it in the theme chooser (stored in the session) or an editor sets it.

Deployed ``951697b`` over ``f920736`` on 2026-11-27 at 11:47. No task result
was ``READY`` or ``RUNNING`` before it; ``just pyinfra-check python_podcast
production`` showed the source sync and its dependent steps; ops-control ran
at ``9c555d76``. Verified after it: the host's ``uv.lock`` names cast-react
``v0.0.3`` (``6a949de5``); both units are active with ``NRestarts=0``;
``/show/``, ``/about/`` and ``robots.txt`` answered 200. In a browser the
theme chooser offers React; choosing it shows the episode list and an episode
with its player, chapters and hosts, and the player plays the episode;
``/about/``, ``/impressum/``, ``/datenschutzerklaerung/``, the chooser page
and the login page still render; choosing Python Podcast again restores the
previous look. The other themes answer 200 unchanged (``?theme=`` for pp,
bootstrap5, vue, bootstrap4 and plain). The journal since the deploy holds
only known notices (``/favicon.ico`` 404, the HEAD body notice, the two
allauth deprecation warnings at worker start).

Rollback: the sequence under "2026-11-18" below with the commit before this
change, including the clean static rebuild. No database step is needed,
unless an editor has since saved React as a theme: first check ``manage.py
shell`` for ``Blog.objects.filter(template_base_dir="react")`` and
``TemplateBaseDirectory.objects.filter(name="react")`` (both in
``cast.models``) and set any match back to its previous theme in the Wagtail
admin and publish it (a draft leaves the live theme on React), then rerun the
queries; django-cast keeps using a stored ``react`` after the package is
gone. A reader whose session still names ``react`` falls back to the site's
theme on its own.

2026-11-27 django-cast 766c225f, cast-bootstrap5 44aece3, django-indieweb 47a983a
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves django-cast ``develop`` from ``d4f29f33`` to ``766c225f``
(still 0.2.70 development state; release notes ``docs/releases/0.2.70.rst``),
cast-bootstrap5 from ``8a11f2b`` to ``44aece3`` and django-indieweb
``develop`` from ``3faf52a`` to ``47a983a``. Nothing else in the lock changed.
No package adds a migration in these ranges; django-cast and cast-bootstrap5
ship new Vite bundles and manifests.

Visible effects: a podcast feed cache miss no longer issues one storage
request per enclosure (sizes read from storage are stored with their file
name after the request commits), the "Cache file sizes" admin action no
longer overwrites concurrent editor changes, chapter saves no longer reuse
rolled-back IDs, several transcript editor fixes, replaced theme-switcher
controls show the current colour mode, and django-indieweb drops only an
out-of-range Webmention date instead of failing and ignores an ``#author``
link to another page. The upgrade actions in django-cast 0.2.70 concern the
editor API, Voxhelm settings clients and primary/replica routers; this site
uses none of them (no ``DATABASE_ROUTERS``).

Local gates on PostgreSQL 17: prek, the Webmention tests with migrations (62
passed), the full suite on Python 3.15.2 and 3.14 (807 passed each, the known
hanging ``test_stalled_phase_is_interrupted_and_resources_close``
deselected), the dock/navigation browser tests (152 passed), Sphinx ``-W``
and the core media gate (7 passed).

Deployed ``bacf947`` over ``88ee7f0`` on 2026-11-27 at 08:41 (owner approval
in chat the same day). It also shipped the show-note converter changes
``1f873f5`` and ``fae75db`` of the manually run ``convert_show_notes``
command. No task result was ``READY`` or ``RUNNING`` before it; ``just
pyinfra-check python_podcast production`` showed only the source sync;
ops-control ran at ``49b3ab74``. Verified after it: the host's ``uv.lock``
names the three new revisions; both units are active with new PIDs and
``NRestarts=0``; ``/``, ``/show/``, an episode, its transcript page, the M4A
and MP3 feeds, ``/cms/login/`` and ``robots.txt`` answered 200 and the
static CSS/JS of the episode page answered 200; the journal of both units
held no error for the first ten minutes and no warning that was not already
logged before the deploy (the two allauth deprecation warnings at worker
start, the HEAD body notice, a 403 on ``/api/audios/`` and 404s for unknown
URLs).

Uncached feeds (cache-busting query, five runs, time to first byte): M4A
0.44-0.55 s, MP3 0.43-0.53 s, the same as before the deploy (0.44-0.60 s).
All audio sizes were already bound by the "Cache file sizes" admin action on
2026-11-26, so this release only keeps them bound; the remaining time is the
feed rendering itself.

Rollback: the sequence under "2026-11-18" below with ``88ee7f0``, including
the clean static rebuild (the older Vite manifests would otherwise stay
behind). No database step is needed.

2026-11-26 robots.txt for the episode index filter URLs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Deployed ``88ee7f0`` over ``c03be33`` on 2026-11-26 at 16:40 as a routine
code-only deploy. ``robots.txt`` now disallows the episode index filter
parameters ``date_facets``, ``tag_facets`` and ``category_facets``, as first
(``/*?tag_facets=``) or later (``/*?*&tag_facets=``) query parameter; crawlers
walked every filter combination (about a quarter of all requests). The deploy
also shipped every change merged since ``c03be33``: the show-note converter
fixes of the manually run ``convert_show_notes`` command, the Fediverse proxy
trying another address when socket creation fails, and script/test-only
changes (legacy backup staging checks, core media gate). No migration, settings,
dependency or unit change; ``just pyinfra-check python_podcast production``
showed only the source sync; ops-control ran at ``8ff629a4``. No task result was
``READY`` or ``RUNNING`` before it. The command was not run.

Verified after the deploy: ``https://python-podcast.de/robots.txt`` serves the
new rules; ``/show/``, its second page, an episode, the MP3 feed and
``/cms/login/`` answered 200 (``/`` redirects to ``/show/`` as before); both
units are active with ``NRestarts=0``; their journal since the deploy holds no
warning or error.

Rollback: the sequence under "2026-11-18" below with ``c03be33``. No database
step is needed.

2026-11-25 django-cast d4f29f33, cast-bootstrap5 8a11f2b, django-indieweb 3faf52a
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves django-cast ``develop`` from ``e0c632ad`` to ``d4f29f33``
(0.2.70 development state; release notes ``docs/releases/0.2.70.rst``),
cast-bootstrap5 from ``b7f16729`` to ``8a11f2b`` (gallery opening fixes) and
django-indieweb ``develop`` from ``7ab7a8ef`` (before 0.7.0) to ``3faf52a``
(0.7.1 plus the unreleased 0.7.2 changes). Nothing else in the lock changed.
django-cast adds no migration in this range. django-indieweb adds
``indieweb.0032`` (two nullable columns) and ``indieweb.0033``
(``failure_attempts``, a JSON column with default ``{}``) on
``WebmentionOutboundTarget``; the deploy's ``migrate`` applies them.

Upgrade actions, checked for this site: the upgrade actions listed in
django-cast 0.2.70 concern programmatic editor API and Voxhelm settings
clients, which this site does not use. Other changes in this range are
visible to readers, for example a single stable podcast RSS
``lastBuildDate`` taken from stored publication dates and the gallery
opening fixes of cast-bootstrap5. django-indieweb's system checks change in
this range: ``indieweb.E004`` (malformed endpoint rate limits; at runtime an
invalid limit is logged and not applied) and ``indieweb.E005`` (a
non-boolean WebSub signature policy) are new after 0.7.1, and the existing
``indieweb.E001`` for Micropub canonical origins now also rejects empty query
and fragment delimiters. This site sets only ``INDIEWEB_RATE_LIMITS`` of the
affected settings, and ``manage.py check`` reports no ``indieweb`` issue.

Local gates on Python 3.15.2 with PostgreSQL 17: prek, the Webmention tests
with migrations (62 passed), the full suite (720 passed, the known hanging
``test_stalled_phase_is_interrupted_and_resources_close`` deselected), the
dock/navigation browser tests (152 passed), Sphinx ``-W``, the full suite on
Python 3.14 (720 passed) and the core media gate (7 passed).

Deployed ``c03be33`` on 2026-11-25 at 17:10 (owner approval in chat the same
day; it also shipped every python-podcast change merged since the previous
deploy). No task result was queued before it. The deploy also applied the
pending unit drift (``RuntimeDirectory=django-site/python-podcast`` and
``XDG_RUNTIME_DIR``). Verified after it: the host's ``uv.lock`` names the three
new revisions; ``indieweb.0032``/``0033`` are applied; ``manage.py check``
reports only the two known allauth deprecation warnings; both units run with
``NRestarts=0``; ``/show/``, an episode, the MP3 feed, the episode's transcript
page and ``/cms/login/`` answered 200 and the static CSS/JS they reference
answered 200; the journal of both units held no warning or error for the
first ten minutes.

Rollback: the sequence under "2026-11-18" below with the previous commit.
The old code does not know ``failure_attempts`` (a non-null column without a
database default). If ``indieweb.0033`` was applied, then after both units
have stopped (step 1, under the deploy lock) and before redeploying the old
commit, reverse it with the new code that is still installed, as the
``python-podcast`` user with the site ``.env``: ``manage.py migrate indieweb
0032``. This drops the per-attempt failure history and keeps the aggregate
failure count, so the old code can insert outbound targets again and a later
upgrade does not count stale attempts.

2026-11-18 Wagtail 8.1 and django-cast e0c632ad
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves Wagtail from 8.0.1 to 8.1 (``pyproject.toml`` now allows
``>=8.1,<8.2``), django-cast ``develop`` from ``c290ec1a`` to ``e0c632ad``
(release 0.2.68 plus the 0.2.69 version bump, the revision the homepage runs)
and draftjs-exporter from 7.1.0 to 7.3.1 (Wagtail 8.1 requires
``>=7.3.0,<8.0``).
django-cast no longer depends on ``python-dateutil`` directly; nothing else in
the lock changed. Neither package adds migrations in this range: the 196
numbered migration files of the Wagtail apps this site installs are
byte-identical between the 8.0.1 and 8.1 wheels, and django-cast stays at
``cast.0094``.

Wagtail 8.1 upgrade considerations, checked for this site:

* Python 3.10 support is dropped; the site runs on Python 3.15.2.
* The internal admin API ``/cms/api/main/`` and the ``construct_admin_api``
  hook are replaced by ``/cms/api/explorer/<id>/``. The site has no
  ``wagtail_hooks.py`` and does not call the old API.
* Pages with an ``ajax_template`` now send ``Vary: X-Requested-With``. No page
  model of this site or django-cast defines one.
* Sitemaps include all locales with ``WAGTAIL_I18N_ENABLED``, which is off;
  the site serves no Wagtail sitemap.
* Redirects are only auto-created when live pages move or are renamed, not
  drafts (``WAGTAILREDIRECTS_AUTO_CREATE = "always"`` restores the old
  behaviour). The default is kept.
* On Django 6.1 Wagtail sends admin mail through ``mailers.default``. Without
  ``MAILERS`` Django builds it from ``EMAIL_BACKEND``, so production keeps the
  Mailgun backend (checked under production settings). Moving to ``MAILERS``
  is separate work.

django-cast upgrade actions between ``c290ec1a`` and ``e0c632ad``, checked for
this site:

* Configured ``cast_public_transcripts`` and ``cast_voice_references`` storages
  now fail loudly instead of falling back to other storages. Both are
  configured here; on production both initialize (the S3 transcript storage
  with its bucket, the voice references on the local filesystem).
* Theme discovery only looks at ``<template-root>/cast/<theme>/``. The offered
  themes (bootstrap4, plain, vue, bootstrap5, pp) are the same before and after.
* Comment posting only accepts Wagtail page targets unless
  ``CAST_COMMENTS_ALLOWED_TARGET_MODELS`` opts in others. Comments here are on
  episodes and posts, so the setting stays unset.
* The modal facet counts need SQLite or PostgreSQL and a search backend that
  returns a database queryset; production runs PostgreSQL with Wagtail's
  default database search backend.
* Galleries are limited to 500 images; the largest gallery here has one.
* No ``cast/audio``, ``cast/video`` or ``cast/transcript`` ``confirm_delete.html``
  overrides exist, so the new delete confirmation field needs no template
  change. New transcript uploads need ``.json`` or ``.vtt`` extensions.
* The development styleguide (``config/settings/local.py``) now admits remote
  media only from allowed origins; extra CDN origins go into
  ``CAST_STYLEGUIDE_REMOTE_ALLOWED_ORIGINS``. Production does not enable it.

Local gates on Python 3.15.2 with PostgreSQL 17: 610 tests passed (one skipped
test needs ``--migrations`` and passed in that mode), the 167 browser tests
(``just test-e2e``) and the core media gate passed, as did
``makemigrations --check``, prek and ``pip-audit`` of the exported lock. Under
production settings ``check`` reports the same issues as before, ``migrate
--plan`` plans nothing and ``collectstatic --clear`` post-processes all files.
A database migrated and seeded with synthetic blog, podcast, image, gallery,
audio and transcript content under the old lock migrated with "No migrations to
apply" under the new one, with an identical ``showmigrations`` and the same
responses for pages, feeds and the admin. In a browser, the admin page explorer
loaded its pages from the new endpoint without JavaScript errors or missing
static files.

Deploy with the usual ``just deploy-one python_podcast production`` from
ops-control. Before it, check that no task result is ``READY`` or ``RUNNING``
(transcripts, incoming Webmentions): the deploy restarts
``python-podcast-db-worker.service``, and a task that runs longer than the
unit's 90-second stop timeout is killed and its row stays ``RUNNING``. If a
task is pending, deploy later.

Rollback: redeploy the previous commit with a clean static rebuild; no
database step is needed. Hold the shared deploy lock on the host for the whole
sequence (``python -m pyinfra_support.deploy_lock acquire production`` in
ops-control, export ``OPS_CONTROL_DEPLOY_LOCK=production=<token>`` so the
nested ``just deploy-one`` accepts it, release afterwards):

1. As root stop ``python-podcast.service`` and
   ``python-podcast-db-worker.service``, then look at the task results. A
   rollback does not wait for an empty queue: ``READY`` rows stay queued and
   the restarted worker runs them. A task still running when the worker
   stopped finishes within the 90-second stop timeout or is killed. A row
   still ``RUNNING`` after both units stopped is not picked up again: report
   it with its id, task path and start time to the site owner and edit
   nothing. Whether its work completed and needs redoing (a transcript
   generation, a Webmention) is a separate decision; this rollback does not
   retry anything.
2. As the ``python-podcast`` user empty
   ``/home/python-podcast/site/staticfiles`` (what ``collectstatic --clear``
   does; it only holds collected files).
3. In ops-control run ``just deploy-one python_podcast production`` with
   ``PROJECTS_ROOT`` set to a directory whose ``python-podcast`` subdirectory
   is a clean checkout of the previous commit. Its ``collectstatic`` fills the
   empty directory from the old packages, and the deploy starts both units
   again. Check each unit with its own ``systemctl is-active``.

The deploy's plain ``collectstatic`` skips a source file that is not newer
than the collected copy. The site's virtualenv hardlinks files from the uv
cache, so the older packages carry the cache's older timestamps. Without the
clean rebuild a rollback would keep the Wagtail 8.1 and django-cast static
files, including ``cast/vite/manifest.json``, next to a ``staticfiles.json``
for the old lock. The units stay stopped until the deploy starts them, because
WhiteNoise indexes the static files at startup and fails on a file removed
under it.

The first forward deploy is not affected: Wagtail 8.1 and django-cast
``e0c632ad`` were never installed for this user, so they are unpacked into
the cache freshly and are newer than the collected files. A forward deploy
after a rollback, or a retry after a deploy that stopped during
``collectstatic``, is affected the same way, so it needs the same sequence
with the intended commit.

2026-10-29 Python 3.15.2
~~~~~~~~~~~~~~~~~~~~~~~~

ops-control now deploys this site on Python 3.15.2 (previously 3.15.1) with uv
0.13.6, the first uv release that can install 3.15.2. The lock and application
code are unchanged, and CI tests 3.15.2 instead of 3.15.1. The interpreter is
installed by ops-control's runtime step before the normal deploy. The deploy
restarts the web and worker processes only when it syncs changed files or
dependencies; the new interpreter alone does not trigger a restart, so check
afterwards that both processes run 3.15.2 and restart them if not. Django and
Wagtail upstream support for Python 3.15 is unchanged from the 2026-10-24 note.

2026-10-21 certifi security update
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` advances certifi from ``2026.7.22`` to ``2026.10.19`` and pip from
``26.2.1`` to ``26.2.2`` for the eMudhra/emSign CA compromise
(`GHSA-6q48-6c7w-9gw2
<https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2>`_).
``pyproject.toml`` now requires ``certifi>=2026.10.19`` so a later relock cannot
resolve an affected bundle. No other package changed. Deploying an earlier
commit or lock reinstalls the affected certifi and pip versions; restart the
application after syncing so running processes load the new bundle.

2026-10-24 framework security patches
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The lock updates only Django 6.1.1 to 6.1.2 and Wagtail 8.0 to 8.0.1. All other
locked packages and Git revisions remain unchanged, including django-cast
``ddcc44d9`` (0.2.68), certifi 2026.10.19 and pip 26.2.2. Do not deploy an older
lock that lowers those certificate trust fixes.

Python 3.15.1 is configured separately by ops-control; this application lock
alone does not upgrade a host interpreter. Testing this maintenance stack does
not extend official runtime support: Django's Python 3.15 support is expected in
6.1.3, and Wagtail's published support matrix currently stops at Python 3.14.
Use the exact qualified source/controller and stage the rollout before production.
Keep fresh database and host-local private-media recovery evidence before any
migration; a code rollback does not reverse schema or stored transcript changes.

2026-10-24 image, API and notebook security follow-up
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

On top of the framework patch, the lock advances only Pillow 12.3.0 to 13.0.0,
Django REST framework 3.18.1 to 3.18.3 and development-only nbconvert 7.17.1 to
7.17.2. Cast's Git revision and the certifi/pip trust fixes remain unchanged.
Pillow 13.0.0 addresses the image-decoder advisories affecting 12.3.0, including
`FPX JPEG decoding <https://github.com/python-pillow/Pillow/security/advisories/GHSA-5x8w-8jj5-q52h>`_.
DRF first fixes the `JSON charset issue
<https://github.com/encode/django-rest-framework/security/advisories/GHSA-3547-9m27-7rxg>`_
in 3.18.2; 3.18.3 also restores the compatibility of ``order_by_precedence``.
nbconvert 7.17.2 fixes `export filename traversal
<https://github.com/jupyter/nbconvert/security/advisories/GHSA-pjvx-prjx-h659>`_;
it is a developer notebook tool, not installed in the production app venv.

Black stays at locked 26.5.1: its reported GitHub Action advisory names only
26.9.0 and 26.10.0, and this repository does not use that Action. Dependency
alert counts and maintainer severity/ranges can differ; these updates are not
a claim that every open alert describes an exposed production code path.

Qualification must exercise actual Python 3.15.1, supported image round trips,
EXIF orientation, Wagtail/Willow renditions, rejected compressed JSON charsets,
valid JSON and malformed input, notebook export containment and the full app
suite. Keep staging-before-production deployment and the recovery prerequisites
above; tests do not broaden upstream Python support claims.

2026-10-17 django-cast develop refresh
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` advances only django-cast from ``704a60aa`` to ``ddcc44d9``
(0.2.68 development). It adds transcript glossary snippets, private correction
sidecars and editor review, preserves approved speaker mappings when transcript
text changes, and omits the speaker-count hint for known-speaker Voxhelm jobs.

Deploy with migrations ``cast.0084`` through ``0086``. Migration ``0084`` reads
existing stored transcript files to backfill source fingerprints; retain a fresh
database backup before deployment. The corrections sidecar uses the private
voice-reference storage backend. Existing transcripts are not automatically
glossary-corrected by the migrations; corrections run on future Voxhelm imports
or through ``apply_transcript_glossary``. Rolling code back does not undo
transcript edits or remove the added schema.

Validation: 360 application tests passed on PostgreSQL 17 with ``--migrations``
(49 browser tests deselected), all prek hooks passed, and
``makemigrations --check --dry-run`` found no changes. An isolated Python 3.15
production environment passed system checks with the existing allauth
deprecation warnings and showed only the three expected pending Cast migrations.

The refresh was deployed on 2026-10-17 from a working tree without committing
the lock. The production deploy of ``8aaa4dd`` on 2026-10-19 therefore
installed ``704a60aa`` again. The migrations stayed applied, the code did not
match them, and transcript corrections and source fingerprints were missing.
This commit records the lock and was deployed the same day. **Deploy only from
a commit that contains the lock you mean to ship.**

2026-10-15 Python 3.15
~~~~~~~~~~~~~~~~~~~~~~

Production moves from Python 3.14.8 to 3.15.0. The interpreter is set in
ops-control (``wagtail_python_version`` in
``playbooks/deploy-python-podcast.yml``); the ops-library ``wagtail_deploy``
role installs it with uv, rebuilds the virtualenv when the version differs and
runs ``uv sync --frozen``. Expect a short outage while the virtualenv is
rebuilt.

* ``uv.lock`` moves pydantic to 2.14.1, pydantic-core to 2.50.1, markupsafe to
  3.0.4, rcssmin and rjsmin to 1.3.0, which ship Python 3.15 wheels, and
  django-indieweb ``develop`` from ``dc6365af`` to ``c1918dc6``. No migration.
* The django-indieweb update limits request bodies on the IndieAuth
  authorization and token endpoints. This site routes only the Webmention
  endpoint and its status URL, so nothing changes here.
* PyYAML (a development dependency through Jupyter) has no 3.15 wheel yet and
  is built from source during ``uv sync`` on the host; the host has a C
  compiler.
* CI tests on Python 3.14 and 3.15 with uv 0.13.1 (3.15.0 needs uv 0.13.0 or
  later); lint and the dock transition browser tests run on 3.15.
* Django 6.1 and Wagtail 8.0 do not list Python 3.15 as supported yet. The
  tests pass on 3.14.8 and 3.15.0 against PostgreSQL 17 (38 with
  ``--migrations``, then 355 passed and 1 skipped), as do the 12 dock
  transition browser tests on 3.15.0.

Rollback: set ``wagtail_python_version`` back to ``"3.14.8"`` in ops-control
and deploy again; the role rebuilds the virtualenv on 3.14. The lock works on
both versions.

2026-10-14 library refresh
~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves django-cast ``develop`` from ``5ac84fbd`` to ``704a60aa``,
django-indieweb ``develop`` from ``9726be2d`` to ``dc6365af`` and
cast-bootstrap5 ``main`` from ``88134d96`` to ``9fba4b2d``. No other locked
package changed. None of the updates has a migration or needs a settings change.

* django-cast writes internal page links in feed item descriptions as absolute
  URLs, so they resolve in podcast apps and feed readers. Voxhelm status polls
  retry lost connections until the job deadline instead of failing the job.
  Applying speaker suggestions names a guest without a voice reference from the
  leftover diarization label when the assignment is unambiguous.
  ``media_stale`` now skips files younger than 7 days
  (``CAST_MEDIA_STALE_MIN_AGE_DAYS``) or of unknown age and re-checks age and
  references before each deletion. Nothing here runs it on a schedule.
* django-indieweb falls back to ``GET`` when outbound Webmention discovery gets
  an error answer to ``HEAD``. Its other behaviour changes (``create`` scope
  for multipart Micropub, ``404`` for rejected WebSub callbacks, fail-closed
  ``INDIEWEB_LOG_REDACTION``) concern views this site does not route and a
  setting it does not set.
* cast-bootstrap5 ships a compiled German catalog, so its theme strings appear
  in German here (``LANGUAGE_CODE`` is ``de-DE``), and sets ``<html lang>`` from
  the active language. This site's ``cast/bootstrap5/base.html`` extends the
  theme's template, so its pages now declare German instead of ``en``.

2026-10-13 library refresh
~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves django-indieweb ``develop`` from ``c7b8da62`` to ``4022366f``,
django-cast ``develop`` from ``8205bc48`` to ``5ac84fbd`` (0.2.68 development),
cast-bootstrap5 ``main`` from ``d0ea6879`` to ``88134d96``.
No other locked package changed. None of the updates has a migration.

One setting is new: ``config.settings.production`` sets
``INDIEWEB_RATE_LIMIT_TRUSTED_PROXY_HOPS`` from ``DJANGO_NUM_PROXIES`` (default
``1``), so django-indieweb rate limits count the client address that Traefik
appends to ``X-Forwarded-For`` and not Traefik's own address. Local and test
settings keep the library default ``0`` (``REMOTE_ADDR``).

**Check before deploying:** django-cast now takes the Voxhelm API base and
token as a pair from one level: the Wagtail ``Voxhelm settings`` of the site
if either field is filled, otherwise the Django settings, otherwise the
environment. A site that has only one of the two Wagtail fields filled no
longer inherits the other from the environment, and transcript generation is
disabled for it. Before the deploy, open ``Settings -> Voxhelm settings`` for
every site and make sure that either both fields are blank (deployment
credentials are used) or both are filled. Changing the API base in Wagtail now
requires re-entering the token; saving with both fields blank removes the
stored token.

* django-indieweb analyses at most two received Webmention documents at a
  time per lock directory (``INDIEWEB_WEBMENTION_PARSE_MAX_CONCURRENT``). A
  further one waits up to 1 s for a slot; after that a synchronous receive
  answers ``503`` with ``Retry-After: 1``. An already verified mention keeps
  its state; a new submission is left as a ``pending`` row. Fetching a
  source or Vouch document has a total budget of 15 s
  (``INDIEWEB_WEBMENTION_FETCH_TOTAL_TIMEOUT_SECONDS``); a source that sends
  its body too slowly is marked ``failed``. Relative links in a source are
  resolved against the fetched source URL, so posts on this site can mention
  each other with relative links; documents containing ``<base`` still match
  on absolute links only. All new settings stay at their defaults.
  When this was written the project did not route any django-indieweb URL.
  The receiving endpoint is routed since; see `Receiving webmentions`_.
* django-indieweb keeps the complete ``next`` URL, including the
  authorization parameters, when IndieAuth or token management redirects to
  the login page.
* A follow-up on the same day moves django-indieweb ``develop`` from
  ``4022366f`` to ``9726be2d``; no other locked package changed and there is
  no migration or settings change. Its endpoint rate limit now stores the
  count and the window deadline together, so the configured window is fixed
  from a client's first request and no longer extends while the client keeps
  sending on a file-based cache; ``Retry-After`` is the time left to that
  deadline. Counting stays best-effort under simultaneous requests. The
  counters use a new cache key namespace, so every client starts with a
  fresh allowance after the upgrade. When this was written no
  ``INDIEWEB_RATE_LIMITS`` were configured and no django-indieweb URL was
  routed; both changed with `Receiving webmentions`_.
* django-cast leaves view-restricted pages, and pages below them, out of the
  navigation links of blog, post and feed pages, for signed-in visitors too.
  Feed descriptions are rendered with the default theme of the blog or site
  and ignore a visitor's session, query or preview theme.
* django-cast answers HTMX theme-selector requests with the plain fragment
  when a theme has no ``select_theme.html``, and ``manage.py check`` reports
  missing optional theme templates as ``cast.W002`` warnings.
  ``Transcript.rewrite_speaker_labels`` also renames generic ``Speaker N:``
  cue prefixes.
* cast-bootstrap5 ships rebuilt bundles, so ``collectstatic`` picks up new
  hashed assets. A Podlove player that fails to load shows a message and a
  ``Retry loading player`` button instead of loading forever. The color mode
  choice applies for the rest of the page session when the browser refuses to
  store it. Search suggestions give up after 5 s and say so; submitting the
  search still works. Consecutive plain blockquotes merge only when nothing
  but whitespace separates them and they carry no attributes such as ``cite``
  or ``id``.

2026-10-12 security library refresh
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves django-indieweb ``develop`` from ``289ea25a`` to ``c7b8da62``,
django-cast ``develop`` from ``95965b91`` to ``8205bc48`` (0.2.68 development),
cast-bootstrap5 ``main`` from ``4ed370aa`` to ``d0ea6879`` and cast-vue ``main``
from ``a0db14fb`` to ``0e1d408b``. No other locked package changed. None of the
updates has a migration, and no settings change is needed.

* django-indieweb parses fetched Webmention source and Vouch documents in a
  short-lived child process, ``python -m indieweb.webmention_parse_worker``,
  one per fetched document. The child limits itself to 512 MiB of address
  space and 20 s of CPU time; the receiving process ends it after 30 s. Over a
  limit the Webmention is marked ``failed`` and nothing from the document is
  stored. The ``INDIEWEB_WEBMENTION_PARSE_*`` settings stay at these defaults.
  When this was written no Webmention endpoint was exposed. It is now (see
  `Receiving webmentions`_), and the child process is started by the
  ``cast_transcripts`` database worker, not by gunicorn. The ``wagtail_deploy`` units
  (``NoNewPrivileges``, ``PrivateTmp``, ``ProtectSystem=strict``) have no
  system call filter, memory limit or task limit that would stop the child or
  its ``setrlimit`` calls, and gunicorn runs from the same virtualenv.
* django-cast limits comment posting to ``CAST_COMMENTS_POST_RATE_LIMIT`` posts
  (default 20) per ``CAST_COMMENTS_POST_RATE_WINDOW`` seconds (default 600) per
  logged-in user or anonymous client address and answers further posts with
  ``429`` and ``Retry-After``. Both settings stay at their defaults. The
  client address comes from ``REST_FRAMEWORK["NUM_PROXIES"]``
  (``DJANGO_NUM_PROXIES``, default ``1``), which matches Traefik as the only
  reverse proxy; see :doc:`login_rate_limits`. The counters live in the
  ``default`` cache.
  The production ``default`` cache is a file cache with Django's default
  ``MAX_ENTRIES`` of 300. When it is full, culling removes entries at random,
  which can drop a counter and reset that client's budget early.
* django-cast ``media_replace --yes`` and ``recalc_video_posters`` now exit
  non-zero when at least one item failed, and ``media_backup`` has a new
  ``--refresh-changed`` option. No deploy step or scheduled job here runs these
  commands.
* cast-bootstrap5 and cast-vue ship rebuilt bundles (gallery metadata and modal
  focus fixes; comment drafts and list state fixes), so ``collectstatic`` picks
  up new hashed assets.

The 269 application tests passed on Python 3.14.8 against PostgreSQL; browser
tests were not run. ``makemigrations
--check`` reported no changes.

2026-10-12 cast-bootstrap5 refresh
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves cast-bootstrap5 ``main`` from ``bcd0b513`` to ``4ed370aa``. No
other locked package changed. The source conflict that kept it at ``bcd0b513``
(see the refresh note below) is resolved: cast-bootstrap5 ``main`` now takes
django-cast from the ``develop`` branch, as this project does.

The update brings the search suggestion input fixes (text composition and
modified clicks are respected) with a rebuilt search modal bundle, so
``collectstatic`` picks up a new hashed asset. It has no migrations and needs no
settings change.

2026-10-12 django-cast and django-indieweb refresh
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv.lock`` moves django-cast ``develop`` from ``0e55a47b`` to ``95965b91`` and
django-indieweb ``develop`` from ``5187311d`` to ``289ea25a``. No other locked
package changed. cast-bootstrap5 stays at ``bcd0b513``: its ``main`` now pins
django-cast to a fixed commit in ``tool.uv.sources``, which conflicts with
tracking ``develop`` here.

* django-indieweb migration ``0029_reconcile_no_scope_grants`` deletes duplicate
  no-scope tokens and auth codes before ``0030_scope_not_null`` makes the scope
  column non-null. Take a database backup before deploying.
  The ops-control deploy migrates while the previous release is still serving
  and restarts the service afterwards. The previous pin stores a no-scope grant
  as ``NULL``, so an IndieAuth authorization issued without a scope during that
  window can recreate a duplicate and make ``0030`` fail, or fail itself once
  ``0030`` has run. Do not authorize IndieAuth clients while deploying. If
  ``0030`` fails, ``0029`` is already recorded and a plain rerun skips it:
  run ``migrate indieweb 0028`` (reversing ``0029`` is a no-op), then deploy
  again so ``0029`` reconciles the new rows before ``0030``.
* django-cast strips EXIF GPS from new image uploads. Existing originals are not
  rewritten; ``python manage.py report_image_gps`` lists them read-only.
* django-cast restricts the Wagtail images API to staff unless
  ``CAST_PUBLIC_IMAGES_API`` is ``True``. The setting stays unset here.

The 153 application tests passed on Python 3.14.7 against PostgreSQL; browser
tests were not run. ``makemigrations --check`` reported no changes.

2026-09-16 django-cast release pin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The focused django-cast refresh advances the intentionally retained Git pin
from ``b36ddd4b`` to the released 0.2.65 commit ``1021142d``. PyPI now also
publishes 0.2.65. No other locked dependency changed. See the
`final release notes <https://github.com/ephes/django-cast/blob/0.2.65/docs/releases/0.2.65.rst>`_.
The 82 application tests and all 11 Chromium browser tests passed on Python
3.14.5. The migration graph applied to empty SQLite, and the settings,
model-change, changed-file hook, and documentation checks also completed.

2026-09-08 refresh
~~~~~~~~~~~~~~~~~~

* django-cast: 0.2.64 at ``c4a9e97a`` to unreleased 0.2.65 at ``b36ddd4b``.
  The latest published PyPI release at upgrade time remains 0.2.64.
* Django: 6.1 to 6.1.1; Wagtail remains 8.0. Both Cast theme pins are unchanged.
* django-indieweb: 0.6.1 to 0.6.2; Gunicorn: 26.0.0 to 26.2.0;
  django-debug-toolbar: 7.0.0 to 8.0.0; Playwright: 1.61.0 to 1.62.0.
* Refreshed 77 packages in total within the existing dependency constraints.
  Removed the now-unused ``setuptools`` and ``decorator`` dependencies;
  ``pkg_resources`` is no longer available in the frozen production environment.

Cast includes permission, feed-isolation, comment, and editor rich-text fixes.
Legacy audio/video collection POST endpoints now reject uploads; clients must
use the editor media API. No project application, configuration, script, or test
references to those legacy upload paths were found. A scan of the shared
production Traefik access log during the companion homepage upgrade found no
such POSTs across 27,632,499 entries; this covers observed usage, not unknown
clients outside the available history. Editor rich-text writes are normalized
against configured Wagtail features. See the
`upstream release notes <https://github.com/ephes/django-cast/blob/b36ddd4b3b3e31b73dd822b749304957c4b3ffe0/docs/releases/0.2.65.rst>`_.

The 82 application tests and all 11 Chromium browser tests passed on Python
3.14.7 using in-memory SQLite. Browser tests used ``config.settings.e2e``,
``DJANGO_ALLOW_ASYNC_UNSAFE=1``, and ``--migrations --create-db`` after installing
the matching Chromium browser. The full migration chain applied to empty SQLite,
and ``makemigrations --check --dry-run`` found no changes. Local settings checks,
including debug-toolbar 8.0, completed with existing allauth deprecation warnings.
The test settings also report a missing Vite manifest.

The new production dependencies, including the pillow-heif wheel, installed in
an isolated environment on the production Linux host with Python 3.14.7.
Against the production PostgreSQL database, that environment's migration plan
was empty and its settings check reported only the allauth deprecations. A fresh
custom-format database dump was saved and its catalog checked with
``pg_restore --list``; the previous dependency files were also retained. No
schema rollback is needed when redeploying the previous commit for this refresh.
PostgreSQL's pre-existing collation-version mismatch was resolved on 2026-09-16
by rebuilding all 114 indexes that use the database default collation
concurrently, then refreshing the database metadata from glibc 2.35 to 2.39.
The post-maintenance check found no invalid user indexes; system catalog indexes
were outside the targeted rebuild. A cluster-wide check found that the
unrelated ``lead`` and ``template1`` databases still carry the old version and
are outside this application release follow-up.

.. _sentry-privacy:

Sentry Privacy
--------------

Error reports sent to Sentry do not identify visitors or users:
``config.settings.production`` calls ``sentry_sdk.init`` with
``send_default_pii=False`` and ``max_request_body_size="never"``. Events keep
the stack trace (including local variables) and the request URL, method and
non-sensitive headers, but not client IP addresses, the logged-in user,
cookies or request bodies (form posts, JSON payloads, uploads).

These are fixed defaults, not ``.env`` settings; change them in the settings
module only after an owner decision. ``tests/test_production_sentry.py``
guards them.

.. _hsts:

HSTS
----

Two layers send ``Strict-Transport-Security``:

* Traefik, through the ``wagtail_deploy`` headers middleware in ops-library:
  ``stsSeconds: 15552000`` (180 days), ``stsIncludeSubdomains`` and
  ``stsPreload``. This is the header visitors see while that middleware is in
  place.
* Django's ``SecurityMiddleware`` (``config.settings.production``), as the
  fallback when the site is served without that middleware.

Django defaults to the same 180 days with ``includeSubDomains`` and **without**
``preload``. The old cookiecutter value (``max-age=60`` plus ``preload``) is
gone. ``preload`` asks browsers to hard-code the domain and its subdomains as
HTTPS-only; removal from the preload list takes months, and hstspreload.org
requires ``max-age`` of at least one year anyway, so the token does nothing
useful at 180 days. ``manage.py check --deploy`` reports ``security.W021``
for this on purpose.

The settings can be overridden from ``.env``:

* ``DJANGO_SECURE_HSTS_SECONDS`` (default ``15552000``)
* ``DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS`` (default ``True``)
* ``DJANGO_SECURE_HSTS_PRELOAD`` (default ``False``)

Upgrade path to preload (owner decision): confirm every subdomain of the domain
serves HTTPS, set ``DJANGO_SECURE_HSTS_SECONDS=31536000`` and
``DJANGO_SECURE_HSTS_PRELOAD=True``, raise ``stsSeconds`` in the Traefik
middleware to match, then submit the domain at https://hstspreload.org/.
Until then the ``stsPreload`` flag in the Traefik middleware should be dropped
in ops-library so both layers agree.

2026-10-09 database connection recovery
----------------------------------------

Production and staging enable ``CONN_HEALTH_CHECKS`` on the default database.
Django checks persistent connections before reuse during a request and replaces
connections closed by a PostgreSQL restart. The existing 60-second
``CONN_MAX_AGE`` remains unchanged. Requests made while PostgreSQL is unavailable
can still fail; this setting does not retry interrupted transactions.

The verified recovery path is persistent connection reuse by web requests;
this is not a retry mechanism for interrupted transcript tasks. The transcript
worker retains systemd's automatic restart on unexpected database connection
failures. For planned PostgreSQL maintenance, pause task producers, drain both
``READY`` and ``RUNNING`` tasks, and gracefully stop active database task workers.
Verify clean shutdown and re-check queue state before restarting PostgreSQL;
restore workers and producers after database readiness. The current worker stop
timeout is 90 seconds, so a long task must finish before maintenance. PostgreSQL
is shared with other applications; coordinate their workers and maintenance
window too.
The operator procedure and staging verification are recorded in ops-control's
``runbooks/python-podcast-database-maintenance.md``.

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

Public transcript artifacts
---------------------------

Published transcript artifacts (Podlove/WebVTT/DOTe) are public for this
podcast: podcast feeds link to transcript endpoints and the transcript text is
intended to be available to listeners. django-cast reads and writes these public
artifacts through the ``cast_public_transcripts`` storage alias, which this
project points at the same public S3 media storage as ``default``. This lets
django-cast read the existing ``cast_transcript/`` S3 objects by their stored
names while the public transcript HTML, player cues, PodcastIndex JSON, and
WebVTT remain served through Django.

Private known-speaker suggestion sidecars and contributor voice references are a
separate concern and use the ``cast_voice_references`` filesystem storage under
``private_media/``. ``cast_private_media`` is not used as the public transcript
workaround anymore.

Voxhelm credentials should be supplied through deployment-managed environment
variables rather than relying on the Wagtail database token field. Configure
``CAST_VOXHELM_API_BASE`` and ``CAST_VOXHELM_API_KEY`` in the shared
environment used by both Gunicorn and the transcript worker, and leave both
the API base and the token field of the Wagtail ``Voxhelm settings`` blank.
django-cast takes the two values as a pair from one level: a site with only
one of the two Wagtail fields filled does not inherit the other from the
environment, and transcript generation is disabled for it.

Known-speaker recognition
-------------------------

Anonymous diarization clusters voices but cannot reliably recover a known
recurring speaker on this podcast's mono live-room recordings. To use
contributor voice references for known-speaker recognition:

* Enable diarization (``CAST_VOXHELM_DIARIZATION_ENABLED=true`` or the
  site-level Voxhelm setting).
* Enable known-speaker recognition with ``CAST_VOXHELM_KNOWN_SPEAKER_ENABLED=true``
  (or the site-level Voxhelm setting) in the shared environment used by both
  Gunicorn and the transcript worker.
* Ensure Voxhelm's ``VOXHELM_ALLOWED_URL_HOSTS`` includes the host that serves
  reference audio. References are sent as source ranges into already-uploaded
  mastered audio (the CloudFront media host), so that host must be allowlisted
  on the Voxhelm side.
* Configure the Voxhelm known-speaker backend: ``VOXHELM_DIARIZATION_BACKEND=pyannote``
  with a Hugging Face token (``VOXHELM_HUGGINGFACE_TOKEN``) that has accepted the
  ``pyannote/wespeaker-voxceleb-resnet34-LM`` model terms.

When enabled, diarized transcript jobs send the approved voice references of an
episode's expected contributors to Voxhelm. Voxhelm returns per-segment speaker
suggestions (candidates, confidence, margin, uncertainty, raw diarization
labels) which django-cast stores privately on the transcript. Known-speaker
results are suggestions: public transcript output stays unlabeled until an
editor reviews and approves them.

Applying the django-cast version with these features runs one new migration
(``cast.0071``) adding the private known-speaker suggestion field and the
site-level known-speaker setting. Bump the pinned ``django-cast`` commit, run
``uv lock --upgrade-package django-cast``, apply migrations, and redeploy.

Receiving webmentions
---------------------

Only two django-indieweb views are routed (pinned at develop ``dc6365a``),
both without authentication:

* ``/indieweb/webmention/`` accepts ``POST`` (submit a mention), ``GET`` and
  ``HEAD`` (a plain-text discovery response with the ``Link`` header) and
  ``OPTIONS`` (CORS preflight). Other methods get ``405``.
* ``/indieweb/webmention/<status_token>/`` accepts ``GET``, ``HEAD`` and
  ``OPTIONS``. GET and HEAD use the status polling rate limit described below.
  A status token is an unguessable random value known only from the
  ``Location`` header of the submission.

IndieAuth, authorization metadata, token issuance,
introspection, token management/revocation, Micropub, media and WebSub callbacks
remain unrouted (404). The status URL returns verification state and, when
available, its timestamp; it does not disclose submitted URLs or content.

Live, public cast blog, post and episode pages advertise the endpoint through
an HTTP ``Link: <…/indieweb/webmention/>; rel="webmention"`` header, across all
themes. The middleware preserves existing Link values in order and appends
the discovery link when the page has no Webmention relation for that endpoint.
It resolves relative Link targets and ``anchor`` parameters against the request
URI for this comparison. A link anchored to another page or fragment is
preserved alongside the page's discovery link. Newly added discovery links use
an absolute endpoint URI. The scan stops at the first match. If the existing
Link header exceeds 8,192 characters, the middleware leaves it as supplied to
avoid adding a potentially duplicate advertisement. See `RFC 8288 <https://www.rfc-editor.org/rfc/rfc8288.html#section-3>`_.

Discovery reads page metadata from mapping template contexts. Custom template
responses with other context types keep their supplied Link headers as they
render.

Drafts, previews, restricted pages (including ancestor restrictions),
account/admin pages and error responses do not advertise it. The receiver
accepts HTTP(S) targets on the current Django Sites domain; discovery is limited
to public cast content. No custom target resolver or comment adapter is enabled.

A submission stores a ``pending`` Webmention, enqueues
``python_podcast.core.webmention_tasks.process_webmention`` on the
``cast_transcripts`` Django Tasks database backend and returns ``202 Accepted``
with its status URL in ``Location``. The request does not fetch remote pages.
The existing ``python-podcast-db-worker`` verifies the source backlink and
stores parsed data. It shares the transcript queue: long transcript jobs can
delay verification for hours. With no worker, mentions stay pending. Locally,
run ``uv run python manage.py db_worker --backend cast_transcripts``; test
settings use ImmediateBackend and intentionally execute tasks immediately.

The synthetic integration tests run the public bounded ``db_worker`` command
(``--batch --max-tasks 10 --no-startup-delay --no-reload``). They verify backend
and queue selection, the claim and terminal task states, failed-source and
failed-task isolation, and execution exactly once. Discovery tests render real
inherited login/group restrictions as an authorized reader: even a successful
private response has no discovery header or mention content. Run both with the
dependency migrations against a disposable PostgreSQL database::

    uv run --locked pytest --create-db --migrations -p no:sugar tests/test_webmention_queue.py tests/test_webmention_discovery.py

A missing backlink or failed fetch marks the mention ``failed``. A failed task
appears under Tasks Database Backend in Django admin, can leave the mention
``pending``, and is not retried automatically. Re-submitting the source/target
pair queues it again.

``INDIEWEB_RATE_LIMITS`` permits 60 receiving requests per client address and
HTTP method in a fixed 300-second window; excess requests get ``429`` with
``Retry-After`` and enqueue nothing. Production's existing
``INDIEWEB_RATE_LIMIT_TRUSTED_PROXY_HOPS`` selects the address appended by
Traefik. Counters use the shared default file cache: increments are not atomic
and cache eviction can reset them early. A cache write failure rejects requests.

Status polling at ``/indieweb/webmention/<status_token>/`` uses the
``webmention_status`` limit: 120 requests per client address and HTTP method
(GET and HEAD separately) per 300 seconds; excess requests get ``429`` with
``Retry-After``. The same shared file cache and counter caveats described
above apply to status polling.

Owner inspection and publication
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Received mentions are visible to authorized staff in Django admin under
**Indieweb → Webmentions**, with source/target, author, content and status.
The library stores ``pending``, ``verified``, ``failed`` and ``spam``: these
are processing states, not owner approval. Homepage renders verified mentions
using its template tags; it has no separate approval status. Python Podcast
renders none of them on public pages, including verified mentions, and does
not convert them into public comments. Owner inspection is required before
any future publication workflow; changing status in admin does not publish.

No project migration is needed: ``indieweb`` is already installed and its
packaged migrations own these tables. Normal deployment must run ``uv run
python manage.py migrate`` before starting web/worker processes; verify with
``uv run python manage.py showmigrations indieweb``. CI additionally runs the
Webmention tests with real migrations and checks their applied history and
Webmention table, since the regular suite uses ``--no-migrations``.
