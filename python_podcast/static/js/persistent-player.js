/*
 * Persistent audio player + enhanced navigation (python-podcast staging proof).
 *
 * Keeps a single live <cast-audio-player> (registered by django-cast's
 * custom-player bundle) alive OUTSIDE the #paging-area swap boundary, so audio
 * started on one page keeps playing while internal public navigation only
 * replaces #paging-area. Episode pages publish a sanitized payload (json_script)
 * plus an inert "play this episode" action; clicking it loads that episode into
 * the persistent player. Merely navigating to an episode never interrupts
 * playback — only an explicit play action switches the source.
 *
 * Dependency-free vanilla JS. It composes the same public HTML contract the
 * django-cast custom player already consumes (a json_script payload + a
 * <cast-audio-player data-payload>), so it needs no django-cast internals. htmx
 * is used only, optionally, to re-process swapped-in content (pagination).
 *
 * Diagnostics for tests live on window.__castPersistentAudioDebug.
 */
(function () {
  "use strict";

  var REGION_ID = "cast-persistent-player";
  var PLAYER_ID = "cast-persistent-audio";
  var DATA_ID = "cast-persistent-data";
  // Id of the per-page content element swapped by enhanced navigation. Themes
  // declare it on the region via data-cast-swap-target (pp: "paging-area";
  // bootstrap5: "main-content"). Resolved in init().
  var PAGING_ID = "paging-area";

  // Path prefixes that must always use a full document load (never enhanced).
  var EXCLUDED_PREFIXES = [
    "/admin",
    "/django-admin",
    "/cms",
    "/accounts",
    "/account",
    "/auth",
    "/login",
    "/logout",
    "/media",
    "/static",
    "/api",
    "/comments",
  ];
  // Path suffixes (feed / download / media files) that must use a full load.
  var EXCLUDED_SUFFIXES = [".mp3", ".m4a", ".oga", ".opus", ".xml", ".rss", ".json", ".zip", ".pdf"];

  var CLOSE_ICON =
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  // Chevron-down; CSS rotates it 180° while the dock is minimized.
  var MINIFY_ICON =
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';

  var state = {
    activePayloadId: null,
    activeAudioId: null,
    switchCount: 0,
    pageDisposers: [],
    // Guards the async close animation against a re-activation racing it: each
    // close takes a sequence number; activating (or a newer close) bumps it so a
    // stale finish() no-ops instead of tearing down the freshly built dock.
    closeSeq: 0,
    closeTimer: null,
    // Same idea for the View Transition: a rapid second activate supersedes the
    // first. vtSeq generation-scopes cleanup so a stale transition can't strip the
    // current dock's names/class; vtSourcePoster/vtSourceCard track the morph
    // sources so their names are cleared before the next snapshot (two elements
    // sharing a view-transition-name in one snapshot aborts the transition).
    vtSeq: 0,
    vtSourcePoster: null,
    vtSourceCard: null,
    // Listeners scoped to the lifetime of the current dock (audio events that
    // mirror playback state onto the page's play cards). Disposed on teardown.
    dockDisposers: [],
    dockResizeObserver: null,
    lastCardTimeText: "",
  };

  // Clear the morph view-transition-names currently held by the dock (poster +
  // inner) and the tracked source poster/card, so the next snapshot has unique
  // names even if a prior transition has not run its cleanup yet.
  function clearMorphNames() {
    if (state.vtSourcePoster) {
      state.vtSourcePoster.style.viewTransitionName = "";
      state.vtSourcePoster = null;
    }
    if (state.vtSourceCard) {
      state.vtSourceCard.style.viewTransitionName = "";
      state.vtSourceCard = null;
    }
    var region = getRegion();
    if (!region) {
      return;
    }
    var dockPoster = region.querySelector(".cast-dock__poster");
    if (dockPoster) {
      dockPoster.style.viewTransitionName = "";
    }
    var inner = region.querySelector(".cast-dock__inner");
    if (inner) {
      inner.style.viewTransitionName = "";
    }
  }

  // Cancel an in-flight close animation/teardown (called before (re)activating),
  // so a pending finish() can't dismiss the new dock and the closing animation
  // never leaks onto it.
  function cancelPendingClose() {
    state.closeSeq += 1;
    if (state.closeTimer) {
      window.clearTimeout(state.closeTimer);
      state.closeTimer = null;
    }
    var region = getRegion();
    if (region) {
      region.removeAttribute("data-cast-closing");
    }
  }

  function prefersReducedMotion() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  // The play card a "play this episode" button belongs to — the View Transition
  // morph source that grows into the dock.
  function cardFor(button) {
    if (!button || !button.closest) {
      return null;
    }
    return button.closest(".cast-play-card");
  }

  // The card's poster: a nested morph pair that glides into the dock poster.
  function cardPosterFor(button) {
    var card = cardFor(button);
    return card ? card.querySelector(".cast-play-card__poster") : null;
  }

  // ---- persistent player lifecycle -----------------------------------------

  function getRegion() {
    return document.getElementById(REGION_ID);
  }

  function getPersistentPlayerEl() {
    var region = getRegion();
    return region ? region.querySelector("cast-audio-player") : null;
  }

  function getActiveAudio() {
    var player = getPersistentPlayerEl();
    return player ? player.querySelector("audio") : null;
  }

  function parsePayload(payloadId) {
    var script = document.getElementById(payloadId);
    if (!script || !script.textContent) {
      return null;
    }
    try {
      return { raw: script.textContent, data: JSON.parse(script.textContent) };
    } catch (err) {
      return null;
    }
  }

  // ---- dock space reservation ----------------------------------------------
  // The dock is fixed to the bottom edge and grows when the transcript/chapters
  // panels open (up to ~42vh), so a static body padding cannot keep the page
  // content reachable. --cast-dock-height tracks the dock's real height; the CSS
  // reserves padding-bottom/scroll-padding-bottom from it, so the footer and the
  // pagination controls always scroll clear of the dock.

  function releaseDockSpace() {
    if (state.dockResizeObserver) {
      state.dockResizeObserver.disconnect();
      state.dockResizeObserver = null;
    }
    document.documentElement.style.removeProperty("--cast-dock-height");
  }

  function reserveDockSpace() {
    releaseDockSpace();
    var region = getRegion();
    var inner = region ? region.querySelector(".cast-dock__inner") : null;
    if (!inner) {
      return;
    }
    var apply = function () {
      var height = Math.ceil(inner.getBoundingClientRect().height);
      document.documentElement.style.setProperty("--cast-dock-height", height + "px");
    };
    if (window.ResizeObserver) {
      state.dockResizeObserver = new ResizeObserver(apply);
      state.dockResizeObserver.observe(inner);
    }
    apply();
  }

  // ---- play-card state mirror ------------------------------------------------
  // The page's play cards mirror the dock's playback state for their own episode:
  // data-cast-state="playing"|"paused" drives the pause glyph, equalizer badge and
  // accent styling; the static duration yields to a live elapsed/total readout.
  // Cards stay plain DOM the manager writes to — they never hold a controller.

  function formatTime(totalSeconds) {
    if (typeof totalSeconds !== "number" || !isFinite(totalSeconds) || totalSeconds < 0) {
      return "";
    }
    var s = Math.floor(totalSeconds);
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var two = function (n) {
      return n < 10 ? "0" + n : "" + n;
    };
    return h > 0 ? h + ":" + two(m) + ":" + two(s % 60) : m + ":" + two(s % 60);
  }

  function updateCardTime() {
    var audio = state.activePayloadId ? getActiveAudio() : null;
    var text = "";
    if (audio) {
      var current = formatTime(audio.currentTime);
      var total = formatTime(audio.duration);
      text = current && total ? current + " / " + total : current;
    }
    if (text === state.lastCardTimeText) {
      return; // timeupdate fires ~4x/s; only touch the DOM on a visible change
    }
    state.lastCardTimeText = text;
    var times = document.querySelectorAll(".cast-play-card[data-cast-state] .cast-play-card__time");
    Array.prototype.forEach.call(times, function (el) {
      el.textContent = text;
      el.hidden = !text;
    });
  }

  function updateCards() {
    var audio = getActiveAudio();
    var playing = !!(audio && !audio.paused && !audio.ended);
    var cards = document.querySelectorAll(".cast-play-card[data-cast-episode-payload]");
    Array.prototype.forEach.call(cards, function (card) {
      var isActive =
        !!state.activePayloadId && card.getAttribute("data-cast-episode-payload") === state.activePayloadId;
      var label = card.querySelector(".cast-play-card__label");
      var time = card.querySelector(".cast-play-card__time");
      var button = card.querySelector(".cast-play-card__btn");
      if (!isActive) {
        card.removeAttribute("data-cast-state");
        if (label && label.getAttribute("data-cast-idle-label")) {
          label.textContent = label.getAttribute("data-cast-idle-label");
        }
        if (time) {
          time.hidden = true;
          time.textContent = "";
        }
        if (button) {
          button.removeAttribute("aria-label");
        }
        return;
      }
      card.setAttribute("data-cast-state", playing ? "playing" : "paused");
      if (label) {
        label.textContent = playing ? "Now playing" : "Paused";
      }
      if (button) {
        // The visible label states the status; the accessible name keeps that
        // text (label-in-name) and adds the action the click performs.
        button.setAttribute("aria-label", playing ? "Now playing — pause" : "Paused — resume");
      }
    });
    state.lastCardTimeText = null; // force the next readout to render
    updateCardTime();
  }

  // ---- dock minimize / expand -----------------------------------------------

  function syncMinifyButton(region, button) {
    var minimized = region.hasAttribute("data-cast-min");
    button.setAttribute("aria-label", minimized ? "Expand player" : "Minimize player");
    button.setAttribute("aria-expanded", minimized ? "false" : "true");
  }

  function toggleMinimized() {
    var region = getRegion();
    if (!region) {
      return;
    }
    if (region.hasAttribute("data-cast-min")) {
      region.removeAttribute("data-cast-min");
    } else {
      region.setAttribute("data-cast-min", "");
    }
    var button = region.querySelector(".cast-dock__minify");
    if (button) {
      syncMinifyButton(region, button);
    }
    // The ResizeObserver follows the height change and shrinks/grows the
    // body's reserved space automatically.
  }

  // The active episode's card is a thin proxy for the dock: clicking it again
  // toggles pause/resume on the single live controller instead of restarting.
  function toggleActive() {
    var player = getPersistentPlayerEl();
    if (player && player.controller && typeof player.controller.toggle === "function") {
      player.controller.toggle();
      return;
    }
    var audio = getActiveAudio();
    if (audio) {
      if (audio.paused) {
        var p = audio.play();
        if (p && typeof p.catch === "function") {
          p.catch(function () {});
        }
      } else {
        audio.pause();
      }
    }
  }

  function disposeDockListeners() {
    for (var i = 0; i < state.dockDisposers.length; i++) {
      state.dockDisposers[i]();
    }
    state.dockDisposers = [];
  }

  // Mirror the dock's audio events onto the page's play cards. Scoped to the
  // current dock: disposed in teardownActive(), re-attached per build.
  function wireActiveAudio() {
    var audio = getActiveAudio();
    if (!audio) {
      // The custom element upgrades synchronously when the bundle is loaded, but
      // be defensive: resolve through the registry's document-level ready event.
      var onReady = function (event) {
        if (!event.detail || event.detail.playerId !== PLAYER_ID) {
          return;
        }
        document.removeEventListener("cast:player-ready", onReady);
        wireActiveAudio();
        updateCards();
      };
      document.addEventListener("cast:player-ready", onReady);
      state.dockDisposers.push(function () {
        document.removeEventListener("cast:player-ready", onReady);
      });
      return;
    }
    var onState = function () {
      updateCards();
    };
    var onTime = function () {
      updateCardTime();
    };
    audio.addEventListener("play", onState);
    audio.addEventListener("pause", onState);
    audio.addEventListener("ended", onState);
    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("durationchange", onTime);
    state.dockDisposers.push(function () {
      audio.removeEventListener("play", onState);
      audio.removeEventListener("pause", onState);
      audio.removeEventListener("ended", onState);
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("durationchange", onTime);
    });
  }

  function teardownActive() {
    var region = getRegion();
    if (!region) {
      return;
    }
    disposeDockListeners();
    // Removing the children synchronously fires disconnectedCallback on the
    // <cast-audio-player> (controller.destroy + unregister) and the panels, so
    // no controller/listener leaks across a switch and the registry is clear
    // before the replacement registers under the same id (no duplicate-id
    // warning).
    region.replaceChildren();
  }

  // Build the dock chrome (poster + title + close) and the single live player
  // from a published episode payload, reveal the dock, and start playback.
  // Returns whether the dock was already active (an in-place episode switch),
  // so the caller can avoid re-animating the dock entrance on a switch.
  function buildActiveDock(payloadId, payload, opts) {
    var region = getRegion();
    if (!region) {
      return false;
    }
    var wasActive = region.getAttribute("data-cast-active") === "true";
    var data = payload.data || {};

    teardownActive();
    state.switchCount += 1;

    // Centred floating card; the region itself is the full-width fixed positioner.
    var inner = document.createElement("div");
    inner.className = "cast-dock__inner";

    var header = document.createElement("div");
    header.className = "cast-dock__header";
    if (data.poster) {
      var poster = document.createElement("img");
      poster.className = "cast-dock__poster";
      poster.src = data.poster;
      poster.alt = "";
      header.appendChild(poster);
    }
    var meta = document.createElement("div");
    meta.className = "cast-dock__meta";
    var title = document.createElement("span");
    title.className = "cast-dock__title";
    title.textContent = data.title || "";
    meta.appendChild(title);
    if (data.subtitle) {
      var subtitle = document.createElement("span");
      subtitle.className = "cast-dock__subtitle";
      subtitle.textContent = data.subtitle;
      meta.appendChild(subtitle);
    }
    header.appendChild(meta);
    // Minimize/expand: collapses the dock to a one-row strip (poster, title,
    // play, elapsed) and back. The attribute lives on the REGION, so the choice
    // survives episode switches (the inner is rebuilt, the region is not).
    var minify = document.createElement("button");
    minify.type = "button";
    minify.className = "cast-dock__minify";
    minify.innerHTML = MINIFY_ICON;
    minify.addEventListener("click", toggleMinimized);
    header.appendChild(minify);
    var close = document.createElement("button");
    close.type = "button";
    close.className = "cast-dock__close";
    close.setAttribute("aria-label", "Close player");
    close.innerHTML = CLOSE_ICON;
    close.addEventListener("click", closeDock);
    header.appendChild(close);
    syncMinifyButton(region, minify);

    var dataScript = document.createElement("script");
    dataScript.type = "application/json";
    dataScript.id = DATA_ID;
    dataScript.textContent = payload.raw;

    var player = document.createElement("cast-audio-player");
    player.id = PLAYER_ID;
    player.setAttribute("data-payload", DATA_ID);

    var panels = document.createElement("div");
    panels.className = "cast-player__panels";
    var transcript = document.createElement("cast-transcript");
    transcript.setAttribute("for", PLAYER_ID);
    var chapters = document.createElement("cast-chapters");
    chapters.setAttribute("for", PLAYER_ID);
    chapters.setAttribute("data-mode", "list");
    panels.appendChild(transcript);
    panels.appendChild(chapters);

    // Append the payload + player first (upgrades synchronously: connectedCallback
    // builds the controller and dispatches cast:player-ready), then the panels so
    // they resolve the freshly-registered controller.
    inner.appendChild(header);
    inner.appendChild(dataScript);
    inner.appendChild(player);
    inner.appendChild(panels);
    // Plain CSS entrance for the non-VT path only (first open, not a switch); the
    // View Transition path passes rise:false and animates the entrance itself.
    if (opts && opts.rise && !wasActive) {
      inner.className += " cast-rise";
    }
    region.appendChild(inner);
    region.hidden = false;
    region.setAttribute("data-cast-active", "true");
    document.body.classList.add("cast-dock-open");

    // Set manager state HERE (not in activate()), so in the deferred View
    // Transition path it is written together with the dock that actually exists.
    state.activePayloadId = payloadId;
    state.activeAudioId = typeof data.audioId === "number" ? data.audioId : null;

    // Start playback through the controller the element exposed on connect.
    // applyStartAt() inside the element already honours ?t=<seconds>.
    if (player.controller && typeof player.controller.play === "function") {
      player.controller.play();
    } else {
      var btn = player.querySelector(".cast-player__play");
      if (btn) {
        btn.click();
      }
    }
    // Track the dock's real height for the body's space reservation, and mirror
    // the new playback state onto the page's play cards.
    reserveDockSpace();
    wireActiveAudio();
    updateCards();
    return wasActive;
  }

  // Activate an episode. Called only on an explicit "play this episode" action.
  // When the View Transitions API is available (and motion is allowed) the play
  // card's poster glides into the dock; otherwise the dock just builds/reveals.
  function activate(payloadId, sourceButton) {
    var payload = parsePayload(payloadId);
    var region = getRegion();
    if (!payload || !region) {
      return;
    }

    // Neutralise any in-flight close synchronously — before the (deferred) View
    // Transition callback — so its finish() can't null manager state or tear down
    // the dock we are about to build.
    cancelPendingClose();

    if (!document.startViewTransition || prefersReducedMotion()) {
      // No View Transition: the dock gets a plain CSS rise on first open (the
      // media query suppresses it under reduced motion anyway).
      buildActiveDock(payloadId, payload, { rise: !prefersReducedMotion() });
      return;
    }

    // Morph the clicked card into the dock (and its poster into the dock poster
    // as a nested pair). A view-transition-name is unique per snapshot, so it
    // lives on the card in the OLD snapshot and is moved onto the dock in the
    // NEW snapshot, then cleared when finished. A second activate supersedes the
    // first: bump the generation and clear any names a still-in-flight prior
    // transition holds, so this snapshot is unique.
    var myVt = (state.vtSeq += 1);
    clearMorphNames();
    var sourcePoster = cardPosterFor(sourceButton);
    var sourceCard = cardFor(sourceButton);
    if (sourcePoster) {
      sourcePoster.style.viewTransitionName = "cast-vt-poster";
      state.vtSourcePoster = sourcePoster;
    }
    if (sourceCard) {
      sourceCard.style.viewTransitionName = "cast-vt-card";
      state.vtSourceCard = sourceCard;
    }
    region.classList.add("cast-vt-active");

    var transition = document.startViewTransition(function () {
      if (sourcePoster) {
        sourcePoster.style.viewTransitionName = "";
      }
      if (state.vtSourcePoster === sourcePoster) {
        state.vtSourcePoster = null;
      }
      if (sourceCard) {
        sourceCard.style.viewTransitionName = "";
      }
      if (state.vtSourceCard === sourceCard) {
        state.vtSourceCard = null;
      }
      // The VT animates the entrance; never also run the CSS rise.
      var wasActive = buildActiveDock(payloadId, payload, { rise: false });
      var dockPoster = region.querySelector(".cast-dock__poster");
      if (dockPoster) {
        dockPoster.style.viewTransitionName = "cast-vt-poster";
      }
      // First open: the dock inner is the card's morph target (the card grows
      // into the player); without a card source it falls back to the rise
      // entrance. An in-place switch only crossfades.
      if (!wasActive) {
        var inner = region.querySelector(".cast-dock__inner");
        if (inner) {
          inner.style.viewTransitionName = sourceCard ? "cast-vt-card" : "cast-vt-dock";
        }
      }
    });

    var cleanup = function () {
      // A newer transition (or its clearMorphNames) now owns the dock; do not
      // strip its names/class.
      if (myVt !== state.vtSeq) {
        return;
      }
      region.classList.remove("cast-vt-active");
      clearMorphNames();
    };
    transition.finished.then(cleanup).catch(cleanup);
  }

  // Dismiss the dock entirely: stop + unmount the single live player (zero live
  // players), distinct from pause (which keeps the player alive). Animates out
  // unless reduced motion is preferred.
  function closeDock() {
    var region = getRegion();
    if (!region) {
      return;
    }
    var myClose = (state.closeSeq += 1);
    var finish = function () {
      // No-op if a re-activation (or a newer close) has superseded this one.
      if (myClose !== state.closeSeq) {
        return;
      }
      if (state.closeTimer) {
        window.clearTimeout(state.closeTimer);
        state.closeTimer = null;
      }
      teardownActive();
      region.hidden = true;
      region.removeAttribute("data-cast-active");
      region.removeAttribute("data-cast-closing");
      region.removeAttribute("data-cast-min"); // a future dock starts expanded
      document.body.classList.remove("cast-dock-open");
      state.activePayloadId = null;
      state.activeAudioId = null;
      releaseDockSpace();
      updateCards();
    };
    var inner = region.querySelector(".cast-dock__inner");
    if (prefersReducedMotion() || !inner) {
      finish();
      return;
    }
    region.setAttribute("data-cast-closing", "");
    var onEnd = function () {
      inner.removeEventListener("animationend", onEnd);
      finish();
    };
    inner.addEventListener("animationend", onEnd);
    state.closeTimer = window.setTimeout(onEnd, 400); // fallback if animationend never fires
  }

  // Wire every page-published "play this episode" action to the manager. Old
  // handlers are disposed first so navigations never leak listeners.
  function wirePlayButtons() {
    for (var i = 0; i < state.pageDisposers.length; i++) {
      state.pageDisposers[i]();
    }
    state.pageDisposers = [];

    var buttons = document.querySelectorAll("[data-cast-play]");
    Array.prototype.forEach.call(buttons, function (button) {
      var payloadId = button.getAttribute("data-cast-play");
      var handler = function (event) {
        event.preventDefault();
        var region = getRegion();
        var dockActive = !!region && region.getAttribute("data-cast-active") === "true";
        if (dockActive && payloadId === state.activePayloadId) {
          // This episode is already in the dock: the card acts as a pause/resume
          // proxy instead of restarting playback.
          toggleActive();
          return;
        }
        activate(payloadId, button);
      };
      button.addEventListener("click", handler);
      state.pageDisposers.push(function () {
        button.removeEventListener("click", handler);
      });
    });
    // Fresh cards (initial load, enhanced nav, htmx pagination) must immediately
    // reflect the dock's current episode/state.
    updateCards();
  }

  // ---- enhanced navigation --------------------------------------------------

  function isEnhanceable(anchor) {
    if (!anchor || anchor.tagName !== "A") {
      return false;
    }
    var href = anchor.getAttribute("href");
    if (!href || href.charAt(0) === "#") {
      return false; // hash-only -> browser native
    }
    if (anchor.hasAttribute("download")) {
      return false;
    }
    var target = anchor.getAttribute("target");
    if (target && target !== "_self") {
      return false;
    }
    // Already an htmx-driven control (e.g. pagination) -> leave to htmx.
    var attrs = anchor.attributes;
    for (var i = 0; i < attrs.length; i++) {
      var name = attrs[i].name;
      if (name.indexOf("hx-") === 0 || name.indexOf("data-hx-") === 0) {
        return false;
      }
    }
    if (anchor.closest("[data-no-boost], [data-hx-get], [hx-get], form")) {
      return false;
    }
    var url;
    try {
      url = new URL(anchor.href, window.location.href);
    } catch (err) {
      return false;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return false;
    }
    if (url.origin !== window.location.origin) {
      return false; // external
    }
    if (url.hash) {
      return false; // any fragment link (same- or cross-page) -> let the
      // browser handle native fragment scrolling; enhanced nav would otherwise
      // scroll to top and drop the #fragment.
    }
    var path = url.pathname.toLowerCase();
    for (var p = 0; p < EXCLUDED_PREFIXES.length; p++) {
      if (path === EXCLUDED_PREFIXES[p] || path.indexOf(EXCLUDED_PREFIXES[p] + "/") === 0) {
        return false;
      }
    }
    for (var s = 0; s < EXCLUDED_SUFFIXES.length; s++) {
      if (path.endsWith(EXCLUDED_SUFFIXES[s])) {
        return false;
      }
    }
    if (path.indexOf("/feed") !== -1) {
      return false;
    }
    return true;
  }

  function isVisible(el) {
    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  }

  function focusHeading(container) {
    var headings = container.querySelectorAll("h1");
    var visibleH1 = null;
    for (var i = 0; i < headings.length; i++) {
      if (isVisible(headings[i])) {
        visibleH1 = headings[i];
        break;
      }
    }
    if (visibleH1) {
      if (!visibleH1.hasAttribute("tabindex")) {
        visibleH1.setAttribute("tabindex", "-1");
      }
      visibleH1.focus({ preventScroll: true });
    } else {
      container.setAttribute("tabindex", "-1");
      container.focus({ preventScroll: true });
    }
  }

  // After #paging-area content changes (initial load or enhanced nav), re-wire
  // the new page's play actions and re-process htmx-driven controls in it.
  function onContentReady() {
    wirePlayButtons();
    var paging = document.getElementById(PAGING_ID);
    if (paging && window.htmx && typeof window.htmx.process === "function") {
      window.htmx.process(paging);
    }
  }

  var navToken = 0;

  function navigateTo(url, options) {
    var push = !options || options.push !== false;
    var token = ++navToken;
    fetch(url, { headers: { "X-Cast-Enhanced-Nav": "1" }, credentials: "same-origin" })
      .then(function (response) {
        if (token !== navToken) {
          return null; // superseded by a newer navigation
        }
        var contentType = response.headers.get("content-type") || "";
        if (!response.ok || contentType.indexOf("text/html") === -1) {
          window.location.assign(url);
          return null;
        }
        return response.text();
      })
      .then(function (text) {
        if (text === null || token !== navToken) {
          return;
        }
        var doc = new DOMParser().parseFromString(text, "text/html");
        var incoming = doc.getElementById(PAGING_ID);
        var current = document.getElementById(PAGING_ID);
        if (!incoming || !current) {
          window.location.assign(url); // no enhanced target -> full load fallback
          return;
        }
        var adopted = document.importNode(incoming, true);
        current.replaceWith(adopted);
        if (doc.title) {
          document.title = doc.title;
        }
        if (push) {
          window.history.pushState({ castNav: true }, "", url);
        }
        window.scrollTo(0, 0);
        onContentReady();
        focusHeading(adopted);
      })
      .catch(function () {
        if (token === navToken) {
          window.location.assign(url);
        }
      });
  }

  function onClick(event) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    var anchor = event.target.closest ? event.target.closest("a") : null;
    if (!anchor || !isEnhanceable(anchor)) {
      return;
    }
    event.preventDefault();
    navigateTo(anchor.href, { push: true });
  }

  function onPopState(event) {
    // Only handle history entries WE created (enhanced navigation marks them
    // with {castNav: true}, including the initial replaceState). Entries created
    // by htmx (e.g. list pagination) or by a normal full load are left to their
    // own handler, so we never compete with htmx's history restoration. The
    // persistent player region is never touched, so audio keeps advancing.
    if (!event.state || event.state.castNav !== true) {
      return;
    }
    navigateTo(window.location.href, { push: false });
  }

  // ---- diagnostics (tests) --------------------------------------------------

  function installDiagnostics() {
    window.__castPersistentAudioDebug = {
      get activePayloadId() {
        return state.activePayloadId;
      },
      get activeAudioId() {
        return state.activeAudioId;
      },
      get switchCount() {
        return state.switchCount;
      },
      get listenerDisposerCount() {
        return state.pageDisposers.length;
      },
      hostCount: function () {
        return document.querySelectorAll("cast-audio-player").length;
      },
      audioCount: function () {
        return document.querySelectorAll("cast-audio-player audio").length;
      },
      getActiveAudio: getActiveAudio,
      getActivePlayer: getPersistentPlayerEl,
      // Map of payload id -> data-cast-state (null when idle) for every play
      // card on the page; lets tests assert the now-playing mirror.
      cardStates: function () {
        var out = {};
        var cards = document.querySelectorAll(".cast-play-card[data-cast-episode-payload]");
        Array.prototype.forEach.call(cards, function (card) {
          out[card.getAttribute("data-cast-episode-payload")] = card.getAttribute("data-cast-state");
        });
        return out;
      },
      // The reserved dock height custom property ("" when no dock is open).
      dockHeight: function () {
        return document.documentElement.style.getPropertyValue("--cast-dock-height");
      },
      isMinimized: function () {
        var region = getRegion();
        return !!region && region.hasAttribute("data-cast-min");
      },
    };
  }

  // ---- init -----------------------------------------------------------------

  function init() {
    var region = getRegion();
    if (!region) {
      return; // persistent flag disabled / region absent
    }
    // Theme-declared content swap target (pp: paging-area, bootstrap5: main-content).
    PAGING_ID = region.getAttribute("data-cast-swap-target") || PAGING_ID;
    installDiagnostics();
    document.addEventListener("click", onClick);
    window.addEventListener("popstate", onPopState);
    // Re-wire play actions after any htmx swap (e.g. list pagination) that may
    // bring new [data-cast-play] buttons into #paging-area. Enhanced navigation
    // calls onContentReady() itself; this covers htmx-driven swaps too.
    document.body.addEventListener("htmx:afterSettle", wirePlayButtons);
    // Seed the initial history entry so the first back lands here cleanly.
    if (window.history.state == null) {
      window.history.replaceState({ castNav: true }, "", window.location.href);
    }
    onContentReady();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
