'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const Timer = require('./timer_logic.js');

const DURATION = 21 * 60_000 + 48_000;

function options(overrides = {}) {
  return Object.assign({
    segmentId: 'segment-1',
    practiceType: 'move',
    durationMs: DURATION,
    targetLayers: 1,
    parameters: {layer: '1', speed: '9.0'}
  }, overrides);
}

function start(now = 1_000, overrides = {}) {
  return Timer.startWorkoutSegment(null, options(overrides), now).session;
}

function finish(session, now) {
  return Timer.syncWorkoutSession(session, now);
}

function next(session, now) {
  return Timer.requestNextSegment(session, now);
}

function storage() {
  const values = new Map();
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
    values
  };
}

test('Next is blocked while current segment is running', () => {
  const session = start();
  const before = Timer.getWorkoutSnapshot(session, 601_000);
  const result = next(session, 601_000);
  assert.equal(result.allowed, false);
  assert.equal(result.reason, 'next_segment_not_allowed');
  assert.equal(result.session.currentSegment.id, 'segment-1');
  assert.equal(result.session.completedSegments.length, 0);
  assert.equal(Timer.getWorkoutSnapshot(result.session, 601_000).currentSegment.remainingMs, before.currentSegment.remainingMs);
});

test('Repeated Start cannot replace an active segment or its frozen parameters', () => {
  const session = start();
  const result = Timer.startWorkoutSegment(session, options({
    segmentId: 'replacement', parameters: {layer: '1', speed: '6.0'}
  }), 601_000);
  assert.equal(result.started, false);
  assert.equal(result.session.currentSegment.id, 'segment-1');
  assert.equal(result.session.currentSegment.parameters.speed, '9.0');
});

test('Next is blocked while an incomplete segment is paused', () => {
  const paused = Timer.pauseWorkout(start(), 601_000);
  const result = next(paused, 9_000_000);
  assert.equal(result.allowed, false);
  assert.equal(result.session.sessionStatus, 'paused');
  assert.equal(result.session.completedSegments.length, 0);
});

test('Resume after blocked Next continues with the exact remaining time', () => {
  const paused = Timer.pauseWorkout(start(), 601_000);
  const blocked = next(paused, 2_000_000).session;
  const resumed = Timer.resumeWorkout(blocked, 3_000_000);
  assert.equal(
    Timer.getWorkoutSnapshot(resumed, 3_010_000).currentSegment.remainingMs,
    DURATION - 610_000
  );
});

test('Next after completion moves one completed segment to history and opens segment 2 config', () => {
  const completed = finish(start(), 1_000 + DURATION);
  const result = next(completed, 1_000 + DURATION);
  assert.equal(result.allowed, true);
  assert.equal(result.session.completedSegments.length, 1);
  assert.equal(result.session.completedSegments[0].status, 'completed');
  assert.equal(result.session.currentSegment, null);
  assert.equal(result.session.sessionStatus, 'configuring_next_segment');
  assert.equal(result.session.draftSegment.segmentNumber, 2);
});

test('Completion while closed is detected from absolute end timestamp', () => {
  const restored = Timer.syncWorkoutSession(start(), 1_000 + DURATION + 3_600_000);
  assert.equal(restored.sessionStatus, 'segment_completed');
  assert.equal(restored.currentSegment.actualElapsedMs, DURATION);
  assert.equal(next(restored, 1_000 + DURATION + 3_600_000).allowed, true);
});

test('Waiting after 00:00 is excluded from history and cumulative time', () => {
  const completed = finish(start(), 1_000 + DURATION + 600_000);
  const configured = next(completed, 1_000 + DURATION + 600_000).session;
  assert.equal(configured.completedSegments[0].actualElapsedMs, DURATION);
  assert.equal(Timer.getWorkoutSnapshot(configured, 99_000_000).cumulativeElapsedMs, DURATION);
});

test('Cumulative time is completed durations plus current active elapsed', () => {
  let session = next(finish(start(), 1_000 + DURATION), 1_000 + DURATION).session;
  session = Timer.startWorkoutSegment(session, options({segmentId: 'segment-2'}), 2_000_000).session;
  assert.equal(Timer.getWorkoutSnapshot(session, 2_900_000).cumulativeElapsedMs, DURATION + 900_000);
});

test('Cumulative display rounds elapsed time down instead of counting an early second', () => {
  assert.equal(Timer.formatElapsed(999), '00:00:00');
  assert.equal(Timer.formatElapsed(1_000), '00:00:01');
});

test('Configuration time between segments is excluded from cumulative time', () => {
  const configuring = next(finish(start(), 1_000 + DURATION), 1_000 + DURATION).session;
  assert.equal(Timer.getWorkoutSnapshot(configuring, 1_000 + DURATION + 900_000).cumulativeElapsedMs, DURATION);
});

test('Paused time is excluded from cumulative time', () => {
  const paused = Timer.pauseWorkout(start(), 601_000);
  assert.equal(Timer.getWorkoutSnapshot(paused, 2_401_000).cumulativeElapsedMs, 600_000);
});

test('New segment resets layer progress and applies its own target', () => {
  let first = start(1_000, {targetLayers: 3, parameters: {layer: '3', speed: '9.0'}});
  first = next(finish(first, 1_000 + DURATION), 1_000 + DURATION).session;
  const second = Timer.startWorkoutSegment(first, options({
    segmentId: 'segment-2',
    targetLayers: 1,
    parameters: {layer: '1', speed: '6.0'}
  }), 2_000_000).session;
  const snapshot = Timer.getWorkoutSnapshot(second, 2_000_000).currentSegment;
  assert.equal(snapshot.completedLayers, 0);
  assert.equal(snapshot.targetLayers, 1);
});

test('Double Next cannot duplicate a completed segment', () => {
  const completed = finish(start(), 1_000 + DURATION);
  const first = next(completed, 1_000 + DURATION);
  const second = next(first.session, 1_000 + DURATION + 1);
  assert.equal(second.allowed, false);
  assert.equal(second.session.completedSegments.length, 1);
});

test('Reload preserves running segment and keeps Next blocked', () => {
  const store = storage();
  Timer.saveWorkoutSession(store, start());
  const loaded = Timer.loadWorkoutSession(store, 601_000);
  assert.equal(loaded.sessionStatus, 'running');
  assert.equal(next(loaded, 601_000).allowed, false);
});

test('Reload preserves paused segment and keeps Next blocked', () => {
  const store = storage();
  Timer.saveWorkoutSession(store, Timer.pauseWorkout(start(), 601_000));
  const loaded = Timer.loadWorkoutSession(store, 9_000_000);
  assert.equal(loaded.sessionStatus, 'paused');
  assert.equal(next(loaded, 9_000_000).allowed, false);
});

test('Reload converts elapsed running segment to completed and allows Next', () => {
  const store = storage();
  Timer.saveWorkoutSession(store, start());
  const loaded = Timer.loadWorkoutSession(store, 1_000 + DURATION + 1);
  assert.equal(loaded.sessionStatus, 'segment_completed');
  assert.equal(next(loaded, 1_000 + DURATION + 1).allowed, true);
});

test('Reload during next segment configuration preserves history and draft', () => {
  const store = storage();
  let configuring = next(finish(start(), 1_000 + DURATION), 1_000 + DURATION).session;
  configuring = Timer.updateDraftSegment(configuring, {
    practiceType: 'water', targetLayers: 2, parameters: {layer: '2', temperature: '25'}
  }, 2_000_000);
  Timer.saveWorkoutSession(store, configuring);
  const loaded = Timer.loadWorkoutSession(store, 9_000_000);
  assert.equal(loaded.completedSegments.length, 1);
  assert.equal(loaded.draftSegment.segmentNumber, 2);
  assert.equal(loaded.draftSegment.practiceType, 'water');
  assert.equal(Timer.getWorkoutSnapshot(loaded, 9_000_000).cumulativeElapsedMs, DURATION);
});

for (const legacyStatus of ['running', 'paused', 'finished']) {
  test(`Migration preserves legacy ${legacyStatus} timer as segment 1`, () => {
    const store = storage();
    let legacy = Timer.createTimerState({
      practiceType: 'water', durationMs: DURATION, targetLayers: 2,
      parameters: {layer: '2', temperature: '25'}
    }, 1_000);
    if (legacyStatus === 'paused') legacy = Timer.pauseTimer(legacy, 601_000);
    if (legacyStatus === 'finished') legacy = Timer.finishTimer(legacy, 1_000 + DURATION);
    Timer.saveTimerState(store, legacy);
    const migrated = Timer.loadWorkoutSession(store, legacyStatus === 'running' ? 601_000 : 9_000_000);
    assert.equal(migrated.version, 2);
    assert.equal(migrated.currentSegment.segmentNumber, 1);
    assert.equal(migrated.sessionStatus, legacyStatus === 'finished' ? 'segment_completed' : legacyStatus);
    assert.equal(store.getItem(Timer.STORAGE_KEY), null);
  });
}

test('Reset clears the entire incomplete workout session', () => {
  const store = storage();
  Timer.saveWorkoutSession(store, start());
  Timer.clearWorkoutSession(store);
  assert.equal(Timer.loadWorkoutSession(store, 601_000), null);
});

test('Ten sequential segments keep unique numbering and exact cumulative duration', () => {
  let now = 1_000;
  let session = start(now);
  for (let number = 1; number <= 10; number += 1) {
    now += DURATION;
    session = finish(session, now);
    if (number < 10) {
      session = next(session, now).session;
      session = Timer.startWorkoutSegment(session, options({segmentId: `segment-${number + 1}`}), now + 1).session;
      now += 1;
    }
  }
  const finalHistory = next(session, now).session;
  assert.deepEqual(finalHistory.completedSegments.map(segment => segment.segmentNumber), [1,2,3,4,5,6,7,8,9,10]);
  assert.equal(Timer.getWorkoutSnapshot(finalHistory, now + 1_000_000).cumulativeElapsedMs, DURATION * 10);
});

test('Water segment keeps its temperature in completed history', () => {
  const water = start(1_000, {
    segmentId: 'water-1', practiceType: 'water', targetLayers: 1,
    parameters: {layer: '1', temperature: '25'}
  });
  const history = next(finish(water, 1_000 + DURATION), 1_000 + DURATION).session.completedSegments;
  assert.equal(history[0].practiceType, 'water');
  assert.equal(history[0].parameters.temperature, '25');
});
