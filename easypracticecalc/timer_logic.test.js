'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const Timer = require('./timer_logic.js');

function memoryStorage() {
  const values = new Map();
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
    values
  };
}

function create(now = 1_000, practiceType = 'water', targetLayers = 5) {
  return Timer.createTimerState({
    practiceType,
    durationMs: 100_000,
    targetLayers,
    parameters: {layer: String(targetLayers)}
  }, now);
}

test('Start stores the calculated duration and absolute end timestamp', () => {
  const state = create();
  assert.equal(state.durationMs, 100_000);
  assert.equal(state.endAt, 101_000);
  assert.equal(state.status, 'running');
});

test('Countdown and skipped interval ticks use the current timestamp', () => {
  const state = create();
  assert.equal(Timer.getTimerSnapshot(state, 2_000).remainingMs, 99_000);
  assert.equal(Timer.getTimerSnapshot(state, 51_000).remainingMs, 50_000);
});

test('Running state survives reload and close/reopen simulation', () => {
  const storage = memoryStorage();
  Timer.saveTimerState(storage, create());
  const restored = Timer.loadTimerState(storage);
  assert.equal(Timer.getTimerSnapshot(restored, 61_000).remainingMs, 40_000);
});

test('Pause freezes remaining time across reload', () => {
  const storage = memoryStorage();
  const paused = Timer.pauseTimer(create(), 31_000);
  Timer.saveTimerState(storage, paused);
  const restored = Timer.loadTimerState(storage);
  assert.equal(Timer.getTimerSnapshot(restored, 9_999_000).remainingMs, 70_000);
});

test('Resume continues from the exact paused remainder', () => {
  const paused = Timer.pauseTimer(create(), 31_000);
  const resumed = Timer.resumeTimer(paused, 80_000);
  assert.equal(resumed.endAt, 150_000);
  assert.equal(Timer.getTimerSnapshot(resumed, 100_000).remainingMs, 50_000);
});

test('Multiple pause/resume cycles do not accumulate timing errors', () => {
  let state = Timer.pauseTimer(create(), 21_000);
  state = Timer.resumeTimer(state, 50_000);
  state = Timer.pauseTimer(state, 60_000);
  state = Timer.resumeTimer(state, 90_000);
  assert.equal(Timer.getTimerSnapshot(state, 100_000).remainingMs, 60_000);
});

test('A practice finished while closed restores as finished at 100 percent', () => {
  const snapshot = Timer.getTimerSnapshot(create(), 200_000);
  assert.equal(snapshot.status, 'finished');
  assert.equal(snapshot.remainingMs, 0);
  assert.equal(snapshot.progress, 1);
  assert.equal(snapshot.currentLayer, 5);
});

test('Reset removes persistent state', () => {
  const storage = memoryStorage();
  Timer.saveTimerState(storage, create());
  Timer.clearTimerState(storage);
  assert.equal(Timer.loadTimerState(storage), null);
});

test('Layer progress is derived from elapsed time for layers 1 through 5', () => {
  const state = create();
  assert.equal(Timer.getTimerSnapshot(state, 1_000).currentLayer, 1);
  assert.equal(Timer.getTimerSnapshot(state, 21_000).currentLayer, 2);
  assert.equal(Timer.getTimerSnapshot(state, 41_000).currentLayer, 3);
  assert.equal(Timer.getTimerSnapshot(state, 61_000).currentLayer, 4);
  assert.equal(Timer.getTimerSnapshot(state, 81_000).currentLayer, 5);
});

test('Layer progress adapts to fewer selected layers', () => {
  const state = create(1_000, 'move', 2);
  assert.equal(Timer.getTimerSnapshot(state, 50_000).currentLayer, 1);
  assert.equal(Timer.getTimerSnapshot(state, 51_000).currentLayer, 2);
});

test('Water and movement practices remain distinguishable after persistence', () => {
  const storage = memoryStorage();
  const move = create(1_000, 'move', 3);
  Timer.saveTimerState(storage, move);
  assert.equal(Timer.loadTimerState(storage).practiceType, 'move');
  Timer.saveTimerState(storage, create(1_000, 'water', 2));
  assert.equal(Timer.loadTimerState(storage).practiceType, 'water');
});

test('Invalid or unrelated persisted data is ignored safely', () => {
  const storage = memoryStorage();
  storage.setItem(Timer.STORAGE_KEY, '{broken');
  assert.equal(Timer.loadTimerState(storage), null);
  storage.setItem(Timer.STORAGE_KEY, JSON.stringify({version: 99}));
  assert.equal(Timer.loadTimerState(storage), null);
});
