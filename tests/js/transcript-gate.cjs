// Exercise the browser gate with native Response bodies, without a browser/DB.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync(process.argv[2], 'utf8');

async function check(outcome) {
  const abort = new AbortController();
  let body;
  let fetches = 0;
  const context = {
    URL, setTimeout,
    location: {href: 'https://example.test/'},
    window: {fetch: async (url, {signal}) => {
      fetches++;
      const response = new Response(new ReadableStream({start(controller) {
        body = controller;
        controller.enqueue(new TextEncoder().encode(outcome === 'invalid' ? '{' : '{"cues":[]}'));
        signal.addEventListener('abort', () => controller.error(signal.reason), {once: true});
      }}));
      Object.defineProperty(response, 'url', {value: url});
      return response;
    }}
  };
  vm.runInNewContext(script, context);
  const gate = context.window.__transcriptGate;
  const url = 'https://example.test/player-transcript/1/';
  let continued = false;
  const result = context.window.fetch(url, {signal: abort.signal}).then(response => response.json()).then(
    data => { continued = true; return {data}; },
    error => { continued = true; return {error}; }
  );
  // The transport promise has resolved; the gate must still hold the response.
  await new Promise(setImmediate);
  assert.equal(gate.waiting[url].length, 1);
  assert.equal(continued, false);
  assert.equal(gate.settled[url], undefined);
  if (outcome === 'aborted') abort.abort();
  else body.close();
  gate.release(url);
  const actual = await result;
  if (outcome === 'aborted') assert.equal(actual.error.name, 'AbortError');
  else if (outcome === 'invalid') assert.equal(actual.error.name, 'SyntaxError');
  else assert.deepEqual(actual.data, {cues: []});
  // Drain the task scheduled by the gate, after the consumer's continuation.
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(gate.settled[url], true, `${outcome}: missing terminal signal`);
  assert.equal(continued, true);
  assert.deepEqual(Object.keys(gate.waiting), []);
  assert.equal(gate.started[url], 1);
  assert.equal(fetches, 1);
}

(async () => {
  for (const outcome of ['success', 'aborted', 'invalid']) await check(outcome);
})().catch(error => { console.error(error); process.exitCode = 1; });
