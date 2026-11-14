Changelog
=========

Unreleased
----------

* Settle the delayed-transcript browser-test gate after rejected JSON reads too:
  switching episodes correctly aborts the retired player's response body. Keep
  both response orders, exact fetch counts and current-episode cue assertions;
  add a browser-free regression for successful, aborted and invalid JSON bodies.
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
