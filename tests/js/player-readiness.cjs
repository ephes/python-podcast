// Exercise the shipped waiting owner with deterministic timers and stale delivery.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
const start = source.indexOf('function wireActiveAudio(');
const end = source.indexOf('function teardownActive(', start);
const listeners = new Set();
const timers = new Set();
const errors = [];
let audio = null;
let player = {};
let plays = 0;
const state = {dockDisposers: [], dockSeq: 1};
const context = {
  state, PLAYER_ID: 'player', PLAYER_READY_TIMEOUT_MS: 15000,
  getActiveAudio: () => audio, getPersistentPlayerEl: () => player,
  updateCards() {}, updateCardTime() {},
  showPlayerError: error => errors.push(error),
  document: {addEventListener: (event, fn) => listeners.add(fn), removeEventListener: (event, fn) => listeners.delete(fn)},
  window: {setTimeout: fn => { timers.add(fn); return fn; }, clearTimeout: fn => timers.delete(fn)}
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
const dispose = () => { state.dockDisposers.splice(0).forEach(fn => fn()); state.dockSeq++; };
const ready = () => [...listeners].forEach(fn => fn({detail: {playerId: 'player'}}));
context.wireActiveAudio();
assert.equal(timers.size, 1, 'missing finite readiness deadline');
const staleTimeout = [...timers][0];
const staleReady = [...listeners][0];
dispose();
assert.equal(timers.size, 0);
assert.equal(listeners.size, 0);
player = {};
context.wireActiveAudio();
staleTimeout(); staleReady({detail: {playerId: 'player'}});
assert.equal(errors.length, 0, 'retired activation changed current dock');
ready(); // A ready event without current audio must not restart the deadline.
assert.equal(timers.size, 1);
assert.equal(listeners.size, 1);
const audioListeners = new Map();
const mediaError = new Error('synthetic media failure');
audio = {
  error: mediaError,
  addEventListener: (event, fn) => audioListeners.set(event, fn),
  removeEventListener: event => audioListeners.delete(event)
};
player.controller = {play: () => plays++};
ready();
assert.equal(timers.size, 0);
assert.equal(listeners.size, 0);
assert.equal(plays, 1, 'asynchronously ready controller never started');
audioListeners.get('pause')();
assert.equal(errors.length, 0);
const reportError = audioListeners.get('error');
assert.ok(reportError, 'ready audio has no error listener');
state.closeCancel = () => {};
reportError();
assert.equal(errors.length, 0, 'closing dock showed a retry');
state.closeCancel = null;
reportError();
assert.deepEqual(errors, [mediaError]);
dispose();
assert.equal(audioListeners.size, 0);
reportError();
assert.deepEqual(errors, [mediaError], 'retired audio changed the dock');
errors.length = 0;
audio = null; player = {};
context.wireActiveAudio();
[...timers][0]();
assert.equal(errors.length, 1);
assert.equal(listeners.size, 0, 'expired owner retained ready listener');
dispose();
assert.equal(timers.size, 0);
