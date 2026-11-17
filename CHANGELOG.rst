Changelog
=========

Unreleased
----------

* Make the legacy production-transfer helper inert on import, validate local
  identities and pass downloaded paths as literal process arguments. Remove its
  independent Docker/SQL restore and automatic role creation; delegate to the
  maintained staging/cutover restore with explicit existing-database confirmation.

* Log Fediverse upstream failures with fixed categories and discovery paths;
  omit raw exception, query, status, header and redirect text while preserving
  generic 502/504 responses and timeout/capacity/protocol distinctions.

* Vary every Fediverse discovery proxy response on ``Accept`` to separate
  cached representations; preserve supported upstream variation and wildcard
  no-reuse semantics, and keep gateway ``HEAD`` responses bodyless.

* Settle the delayed-transcript browser-test gate after rejected JSON reads too:
  switching episodes correctly aborts the retired player's response body. Keep
  both response orders, exact fetch counts and current-episode cue assertions;
  add a browser-free regression for successful, aborted and invalid JSON bodies.
* Load the comments stylesheet on every pp page (navigation asset set
  ``pp-v2``) instead of giving comment-enabled posts their own ``pp-v1+comments``
  set: that marker forced a full page load when navigating from such a post,
  which stopped the persistent player in the pp theme.
* Stage and recover the generated asset set on handled publication failures.
* Bound asynchronous player readiness and retire stale waits on switch/close;
  expose an explicit playback retry after expiry.
* Select forced shownote sources deterministically with revision/digest receipts
  (SHA-256 over UTF-8 JSON); per-episode reports keep block counts and order;
  emit committed progress immediately and continue independent episode failures
  with a nonzero summary.
* Require matching navigation asset markers before partial swaps, and iterate
  shownote archives without retaining every full episode body.
* Establish the destination URL before connecting navigation content and retire
  old htmx node work before processing the replacement through a cleanup-running
  ``htmx.swap`` delete; comment-enabled pp posts advertise their own navigation
  asset marker.

* Bound enhanced-navigation HTML to 2 MiB before parsing; cancel oversized
  streams and use one native-navigation fallback.
* Retire pending enhanced navigation on a newer native same-page fragment click.
* Serialize development/Git source switches through validation, atomic source
  publication and environment sync, retaining failed-sync recovery.
* Clear partially constructed docks after synchronous player/panel connection
  or initial play failures; retain the original error and allow explicit retry.
  Errors raised while tearing down the previous dock do not fail the new one.
