Changelog
=========

Unreleased
----------

* Establish the destination URL before connecting navigation content and retire
  old htmx node work before processing the replacement.

* Bound enhanced-navigation HTML to 2 MiB before parsing; cancel oversized
  streams and use one native-navigation fallback.
* Retire pending enhanced navigation on a newer native same-page fragment click.
* Serialize development/Git source switches through validation, atomic source
  publication and environment sync, retaining failed-sync recovery.
* Clear partially constructed docks after synchronous player/panel connection
  or initial play failures; retain the original error and allow explicit retry.
  Errors raised while tearing down the previous dock do not fail the new one.
