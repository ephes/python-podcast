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

  var state = {
    activePayloadId: null,
    activeAudioId: null,
    switchCount: 0,
    pageDisposers: [],
  };

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

  function teardownActive() {
    var region = getRegion();
    if (!region) {
      return;
    }
    // Removing the children synchronously fires disconnectedCallback on the
    // <cast-audio-player> (controller.destroy + unregister) and the panels, so
    // no controller/listener leaks across a switch and the registry is clear
    // before the replacement registers under the same id (no duplicate-id
    // warning).
    region.replaceChildren();
  }

  // Build the single live persistent player from a published episode payload
  // and start playback. Called only on an explicit "play this episode" action.
  function activate(payloadId) {
    var payload = parsePayload(payloadId);
    var region = getRegion();
    if (!payload || !region) {
      return;
    }

    teardownActive();
    state.switchCount += 1;

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
    region.appendChild(dataScript);
    region.appendChild(player);
    region.appendChild(panels);
    region.hidden = false;
    region.setAttribute("data-cast-active", "true");

    state.activePayloadId = payloadId;
    state.activeAudioId = payload.data && typeof payload.data.audioId === "number" ? payload.data.audioId : null;

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
        activate(payloadId);
      };
      button.addEventListener("click", handler);
      state.pageDisposers.push(function () {
        button.removeEventListener("click", handler);
      });
    });
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
