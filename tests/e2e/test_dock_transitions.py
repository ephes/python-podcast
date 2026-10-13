"""Isolated browser regressions for deferred dock updates; no database or Vite."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e
STATIC_JS = Path(__file__).resolve().parents[2] / "python_podcast/static/js"


@pytest.fixture(params=["persistent-player.js", "persistent-player.min.js"])
def dock(page, request):
    page.emulate_media(reduced_motion="no-preference")
    page.set_content("""
        <div id="cast-persistent-player" hidden></div>
        <div id="paging-area">
          <div class="cast-play-card" data-cast-episode-payload="a">
            <img class="cast-play-card__poster"><button id="play-a" data-cast-play="a">A</button>
          </div>
          <div class="cast-play-card" data-cast-episode-payload="b">
            <img class="cast-play-card__poster"><button id="play-b" data-cast-play="b">B</button>
          </div>
        </div>
        <script type="application/json" id="a">{"audioId":1,"title":"A","poster":"a.png"}</script>
        <script type="application/json" id="b">{"audioId":2,"title":"B","poster":"b.png"}</script>
    """)
    page.evaluate("""() => {
        window.plays = [];
        customElements.define('cast-audio-player', class extends HTMLElement {
            connectedCallback() {
                const payload = JSON.parse(document.getElementById(this.dataset.payload).textContent);
                this.controller = {play: () => window.plays.push(payload.audioId)};
            }
        });
        window.transitions = [];
        document.startViewTransition = update => {
            let finish;
            const finished = new Promise(resolve => { finish = resolve; });
            window.transitions.push({update, finish});
            return {finished};
        };
    }""")
    page.add_script_tag(path=str(STATIC_JS / request.param))
    return page


def _complete(page, index):
    page.evaluate(
        """async index => {
        window.transitions[index].update();
        window.transitions[index].finish();
        await Promise.resolve();
    }""",
        index,
    )


def _assert_active(page, audio_id, plays):
    assert page.evaluate("window.__castPersistentAudioDebug.activeAudioId") == audio_id
    assert page.evaluate("window.plays") == plays
    assert page.locator("cast-audio-player").count() == 1


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_latest_activation_owns_update_and_cleanup(dock, order):
    dock.locator("#play-a").click()
    dock.locator("#play-b").click()
    assert dock.evaluate("window.transitions.length") == 2
    _complete(dock, order[0])
    if order[0] == 0:
        assert dock.locator("cast-audio-player").count() == 0
        assert dock.evaluate("window.plays") == []
        assert (
            dock.locator("#play-b").evaluate("button => button.closest('.cast-play-card').style.viewTransitionName")
            == "cast-vt-card"
        )
        assert dock.locator("#cast-persistent-player").evaluate(
            "region => region.classList.contains('cast-vt-active')"
        )
    _complete(dock, order[1])
    _assert_active(dock, 2, [2])
    assert not dock.locator("#cast-persistent-player").evaluate(
        "region => region.classList.contains('cast-vt-active')"
    )


@pytest.mark.parametrize("fallback", ["reduced-motion", "no-api"])
def test_non_transition_activation_supersedes_pending_update(dock, fallback):
    dock.locator("#play-a").click()
    if fallback == "reduced-motion":
        dock.emulate_media(reduced_motion="reduce")
    else:
        dock.evaluate("document.startViewTransition = undefined")
    dock.locator("#play-b").click()
    assert dock.evaluate("window.transitions.length") == 1
    _assert_active(dock, 2, [2])
    _complete(dock, 0)
    _assert_active(dock, 2, [2])
    assert not dock.locator("#cast-persistent-player").evaluate(
        "region => region.classList.contains('cast-vt-active')"
    )


@pytest.mark.parametrize("reduced_motion", ["reduce", "no-preference"])
def test_close_invalidates_pending_switch_and_allows_reactivation(dock, reduced_motion):
    dock.locator("#play-a").click()
    _complete(dock, 0)
    dock.locator("#play-b").click()
    dock.emulate_media(reduced_motion=reduced_motion)
    # Keep the close fallback from racing assertions on a slow runner. Animation
    # completion below is explicit; no real time needs to pass.
    dock.evaluate("""() => {
        const setTimeout = window.setTimeout.bind(window);
        window.closeTimeoutHits = 0;
        window.setTimeout = (callback, delay) => {
            if (delay === 400) {
                window.closeTimeoutHits += 1;
                return setTimeout(() => {}, 0);
            }
            return setTimeout(callback, delay);
        };
    }""")
    dock.locator(".cast-dock__close").click()
    assert dock.evaluate("window.closeTimeoutHits") == (1 if reduced_motion == "no-preference" else 0)
    _complete(dock, 1)
    if reduced_motion == "no-preference":
        # Drive the animation end explicitly instead of depending on a timer/CSS.
        dock.locator(".cast-dock__inner").dispatch_event("animationend")
    assert dock.locator("cast-audio-player").count() == 0
    assert dock.evaluate("window.__castPersistentAudioDebug.activeAudioId") is None
    assert dock.evaluate("window.plays") == [1]
    assert dock.locator("#cast-persistent-player").evaluate("region => region.hidden")
    dock.emulate_media(reduced_motion="reduce")
    dock.locator("#play-b").click()
    _assert_active(dock, 2, [1, 2])
