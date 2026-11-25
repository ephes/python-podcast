// Drive close completion and reactivation without relying on CSS or real time.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');
const timers = new Set();
const animationListeners = new Set();
const inner = {
  addEventListener: (name, listener) => animationListeners.add(listener),
  removeEventListener: (name, listener) => animationListeners.delete(listener)
};
const attrs = new Set();
const region = {
  querySelector: () => inner, contains: () => true,
  setAttribute: name => attrs.add(name), removeAttribute: name => attrs.delete(name),
  classList: {remove() {}}
};
let unmounts = 0;
let restores = 0;
let reducedMotion = false;
const state = {closeSeq: 0, vtSeq: 0, activePayloadId: 'episode'};
const context = {
  state, getRegion: () => region, prefersReducedMotion: () => reducedMotion,
  clearMorphNames() {}, teardownActive: () => unmounts++,
  releaseDockSpace() {}, updateCards() {}, restoreDockFocus: () => restores++,
  window: {setTimeout: fn => { timers.add(fn); return fn; }, clearTimeout: fn => timers.delete(fn)},
  document: {body: {classList: {remove() {}}}}
};
vm.createContext(context);
for (const [first, next] of [['cancelPendingClose', 'prefersReducedMotion'], ['closeDock', 'wirePlayButtons']]) {
  const start = source.indexOf('function ' + first + '(');
  vm.runInContext(source.slice(start, source.indexOf('function ' + next + '(', start)), context);
}
const animate = (target, animationName) => [...animationListeners].forEach(fn => fn({target, animationName}));

context.closeDock();
animate({}, 'cast-dock-sink');
assert.equal(unmounts, 0, 'descendant animation retired the dock');
animate(inner, 'cast-dock-rise');
assert.equal(unmounts, 0, 'unrelated inner animation retired the dock');
assert.equal(restores, 0);
animate(inner, 'cast-dock-sink');
assert.deepEqual([unmounts, restores, timers.size, animationListeners.size], [1, 1, 0, 0]);

context.closeDock();
const staleTimer = [...timers][0];
const staleAnimation = [...animationListeners][0];
context.cancelPendingClose();
assert.deepEqual([timers.size, animationListeners.size], [0, 0]);
assert.equal(attrs.has('data-cast-closing'), false);
context.closeDock();
staleTimer();
staleAnimation({target: inner, animationName: 'cast-dock-sink'});
assert.deepEqual([unmounts, restores, timers.size, animationListeners.size], [1, 1, 1, 1]);
[...timers][0]();
assert.deepEqual([unmounts, restores, timers.size, animationListeners.size], [2, 2, 0, 0]);

reducedMotion = true;
context.closeDock();
assert.deepEqual([unmounts, restores, timers.size, animationListeners.size], [3, 3, 0, 0]);
