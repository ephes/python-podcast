// Small transport/event oracle; browser fixtures cover real DOM and native focus.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function main() {
  let click;
  let parsed = 0;
  let swapped = 0;
  let cancelled = 0;
  const assigned = [];
  const region = {getAttribute: () => null, querySelector: () => null};
  const paging = {replaceWith: () => { swapped++; }, querySelectorAll: () => [],
    setAttribute() {}, focus() {}};
  const window = {
    location: {href: 'https://podcast.invalid/page/a', origin: 'https://podcast.invalid',
      assign: url => assigned.push(url)},
    history: {state: {}, pushState() {}},
    setTimeout, clearTimeout, addEventListener() {}, scrollTo() {}
  };
  const document = {
    readyState: 'complete', body: {addEventListener() {}},
    getElementById: id => id === 'cast-persistent-player' ? region : paging,
    querySelectorAll: () => [], importNode: node => node,
    addEventListener: (name, handler) => { if (name === 'click') click = handler; }
  };
  let release;
  let signal;
  let responseBody;
  const mode = process.argv[3];
  const deferred = mode !== 'oversize';
  const retired = mode === 'fragment';
  const context = {window, document, URL, AbortController, TextDecoder,
    DOMParser: class {parseFromString() { parsed++; return {getElementById: () => paging}; }},
    fetch: (url, options) => {
      signal = options.signal;
      if (deferred) return new Promise(resolve => { release = () => resolve(
        new Response('<div id="paging-area">B</div>', {headers: {'content-type': 'text/html'}})); });
      let chunks = 0;
      const body = new ReadableStream({
        pull(controller) {
          if (chunks++ === 4) controller.close();
          else controller.enqueue(new Uint8Array(1024 * 1024).fill(32));
        },
        cancel() { cancelled++; }
      });
      responseBody = body;
      return Promise.resolve(new Response(body, {headers: {'content-type': 'text/html'}}));
    }};
  vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), context);
  const dispatch = (href, options = {}) => {
    const anchor = {tagName: 'A', attributes: [], href: new URL(href, window.location.href).href,
      getAttribute: key => key === 'href' ? href : null, hasAttribute: () => false,
      closest: () => options.owned ? {} : null};
    const event = {button: 0, ctrlKey: options.modified, target: {closest: () => anchor}, preventDefault() { this.defaultPrevented = true; }};
    click(event);
    return event;
  };
  dispatch('/page/b');
  if (deferred) {
    assert.equal(dispatch('#comments', {modified: mode === 'modified', owned: mode === 'owned'}).defaultPrevented, undefined);
    release();
  }
  // Drain promise and stream continuations, including fallback/cancellation.
  await new Promise(resolve => setTimeout(resolve, 100));
  const admitted = deferred && !retired ? 1 : 0;
  assert.equal(parsed, admitted, 'unadmitted or retired HTML reached DOMParser');
  assert.equal(swapped, admitted);
  assert.equal(assigned.length, deferred ? 0 : 1);
  assert.equal(signal.aborted, !deferred || retired);
  if (!deferred) {
    assert.equal(cancelled, 1);
    assert.equal(responseBody.locked, false);
  }
}
main().catch(error => { console.error(error); process.exit(1); });
