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

test('Pace formatter uses one compact M:SS min/km format', () => {
  assert.equal(Timer.formatPace(8), '7:30 мин/км');
  assert.equal(Timer.formatPace(7), '8:34 мин/км');
  assert.equal(Timer.formatPace(6), '10:00 мин/км');
  assert.equal(Timer.formatPace(5), '12:00 мин/км');
});

test('Female walk-to-run threshold classifies 6.4 as walking and 6.5 as running', () => {
  assert.equal(Timer.getMovementKind(6.4, 'female'), 'walking');
  assert.equal(Timer.getMovementKind(6.5, 'female'), 'running');
});

test('Male walk-to-run threshold classifies 6.5 as walking and 7 as running', () => {
  assert.equal(Timer.getMovementKind(6.5, 'male'), 'walking');
  assert.equal(Timer.getMovementKind(7, 'male'), 'running');
});

test('Legacy sessions use neutral 7.2 km/h walk-to-run fallback', () => {
  assert.equal(Timer.getMovementKind(7), 'walking');
  assert.equal(Timer.getMovementKind(7.5), 'running');
});

test('Sex is stored once at Workout Session level and survives persistence', () => {
  const store = storage();
  const session = Timer.startWorkoutSegment(null, options({sex: 'female'}), 1_000).session;
  Timer.saveWorkoutSession(store, session);
  const loaded = Timer.loadWorkoutSession(store, 2_000);
  assert.equal(loaded.sex, 'female');
  assert.equal(loaded.currentSegment.sex, undefined);
});

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

test('Completion while closed finalizes overtime from the absolute planned end timestamp', () => {
  const restored = Timer.finalizeWorkoutOvertime(start(), 1_000 + DURATION + 3_600_000);
  assert.equal(restored.sessionStatus, 'segment_completed');
  assert.equal(restored.currentSegment.actualElapsedMs, DURATION + 3_600_000);
  assert.equal(restored.currentSegment.overtimeDurationMs, 3_600_000);
  assert.equal(next(restored, 1_000 + DURATION + 3_600_000).allowed, true);
});

test('Waiting after 00:00 is included once in history and cumulative time', () => {
  const completed = finish(start(), 1_000 + DURATION + 600_000);
  const configured = next(completed, 1_000 + DURATION + 600_000).session;
  assert.equal(configured.completedSegments[0].actualElapsedMs, DURATION + 600_000);
  assert.equal(Timer.getWorkoutSnapshot(configured, 99_000_000).cumulativeElapsedMs, DURATION + 600_000);
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

test('New segment continues cumulative layer progress and applies a cumulative target', () => {
  let first = start(1_000, {targetLayers: 1, parameters: {layer: '1', speed: '9.0'}});
  first = next(finish(first, 1_000 + DURATION), 1_000 + DURATION).session;
  const second = Timer.startWorkoutSegment(first, options({
    segmentId: 'segment-2',
    targetLayers: 1,
    parameters: {layer: '1', speed: '6.0'}
  }), 2_000_000).session;
  const snapshot = Timer.getWorkoutSnapshot(second, 2_000_000).currentSegment;
  assert.equal(snapshot.completedLayersBeforeSegment, 1);
  assert.equal(snapshot.totalLayerProgress, 1);
  assert.equal(snapshot.currentLayer, 2);
  assert.equal(snapshot.targetCumulativeLayers, 2);
});

test('One completed layer plus one new layer progresses from 1 through 1.5 to 2', () => {
  let session = next(finish(start(1_000), 1_000 + DURATION), 1_000 + DURATION).session;
  session = Timer.startWorkoutSegment(session, options({segmentId: 'segment-2'}), 2_000_000).session;
  assert.equal(Timer.getWorkoutSnapshot(session, 2_000_000).totalLayerProgress, 1);
  assert.equal(Timer.getWorkoutSnapshot(session, 2_000_000 + DURATION / 2).totalLayerProgress, 1.5);
  assert.equal(Timer.getWorkoutSnapshot(session, 2_000_000 + DURATION).totalLayerProgress, 2);
});

test('One completed layer plus two new layers progresses from 1 through 2 to target 3', () => {
  let session = next(finish(start(1_000), 1_000 + DURATION), 1_000 + DURATION).session;
  const secondDuration = DURATION * 2;
  session = Timer.startWorkoutSegment(session, options({
    segmentId: 'segment-2', targetLayers: 2, durationMs: secondDuration,
    parameters: {layer: '2', speed: '9.0'}
  }), 2_000_000).session;
  const atStart = Timer.getWorkoutSnapshot(session, 2_000_000).currentSegment;
  const atMiddle = Timer.getWorkoutSnapshot(session, 2_000_000 + secondDuration / 2).currentSegment;
  const atFinish = Timer.getWorkoutSnapshot(session, 2_000_000 + secondDuration).currentSegment;
  assert.equal(atStart.totalLayerProgress, 1);
  assert.equal(atMiddle.totalLayerProgress, 2);
  assert.equal(atFinish.totalLayerProgress, 3);
  assert.equal(atStart.targetCumulativeLayers, 3);
});

test('Two plus one plus two layers form one continuous zero-to-five sequence', () => {
  let now = 1_000;
  let session = start(now, {targetLayers: 2, durationMs: DURATION * 2, parameters: {layer: '2', speed: '9.0'}});
  now += DURATION * 2;
  assert.equal(Timer.getWorkoutSnapshot(session, now).totalLayerProgress, 2);
  session = next(finish(session, now), now).session;
  session = Timer.startWorkoutSegment(session, options({segmentId: 'segment-2'}), now + 1).session;
  now += 1 + DURATION;
  assert.equal(Timer.getWorkoutSnapshot(session, now).totalLayerProgress, 3);
  session = next(finish(session, now), now).session;
  session = Timer.startWorkoutSegment(session, options({
    segmentId: 'segment-3', targetLayers: 2, durationMs: DURATION * 2,
    parameters: {layer: '2', speed: '6.0'}
  }), now + 1).session;
  now += 1 + DURATION * 2;
  assert.equal(Timer.getWorkoutSnapshot(session, now).totalLayerProgress, 5);
});

test('Speed change affects only the new segment duration while layers continue from 1 to 2', () => {
  const slowerDuration = (38 * 60 + 42) * 1000;
  let session = next(finish(start(1_000), 1_000 + DURATION), 1_000 + DURATION).session;
  session = Timer.startWorkoutSegment(session, options({
    segmentId: 'segment-2', durationMs: slowerDuration,
    parameters: {layer: '1', speed: '6.0'}
  }), 2_000_000).session;
  const middle = Timer.getWorkoutSnapshot(session, 2_000_000 + slowerDuration / 2);
  assert.equal(session.completedSegments[0].plannedDurationMs, DURATION);
  assert.equal(session.currentSegment.plannedDurationMs, slowerDuration);
  assert.equal(middle.totalLayerProgress, 1.5);
  assert.equal(middle.cumulativeElapsedMs, DURATION + slowerDuration / 2);
});

test('Water temperature change affects only the new segment and continues cumulative layers', () => {
  const warmDuration = (14 * 60 + 36) * 1000;
  const coldDuration = (6 * 60 + 12) * 1000;
  let session = start(1_000, {
    practiceType: 'water', durationMs: warmDuration, targetLayers: 1,
    parameters: {layer: '1', temperature: '28'}
  });
  session = next(finish(session, 1_000 + warmDuration), 1_000 + warmDuration).session;
  session = Timer.startWorkoutSegment(session, options({
    segmentId: 'water-2', practiceType: 'water', durationMs: coldDuration,
    parameters: {layer: '1', temperature: '20'}
  }), 2_000_000).session;
  assert.equal(Timer.getWorkoutSnapshot(session, 2_000_000).totalLayerProgress, 1);
  assert.equal(Timer.getWorkoutSnapshot(session, 2_000_000 + coldDuration).totalLayerProgress, 2);
  assert.equal(session.currentSegment.plannedDurationMs, coldDuration);
});

test('Pause freezes cumulative progress of a later segment and Resume continues it', () => {
  let session = next(finish(start(1_000), 1_000 + DURATION), 1_000 + DURATION).session;
  session = Timer.startWorkoutSegment(session, options({segmentId: 'segment-2'}), 2_000_000).session;
  session = Timer.pauseWorkout(session, 2_000_000 + DURATION * 0.37);
  assert.equal(Timer.getWorkoutSnapshot(session, 9_000_000).totalLayerProgress, 1.37);
  session = Timer.resumeWorkout(session, 10_000_000);
  assert.equal(Timer.getWorkoutSnapshot(session, 10_000_000 + DURATION * 0.13).totalLayerProgress, 1.5);
});

test('Reload restores a running second segment at cumulative depth 1.4', () => {
  const store = storage();
  let session = next(finish(start(1_000), 1_000 + DURATION), 1_000 + DURATION).session;
  session = Timer.startWorkoutSegment(session, options({segmentId: 'segment-2'}), 2_000_000).session;
  Timer.saveWorkoutSession(store, session);
  const loaded = Timer.loadWorkoutSession(store, 2_000_000 + DURATION * 0.4);
  assert.equal(Timer.getWorkoutSnapshot(loaded, 2_000_000 + DURATION * 0.4).totalLayerProgress, 1.4);
});

test('A second segment reaching zero while PWA is closed restores with live overtime', () => {
  const store = storage();
  let session = next(finish(start(1_000), 1_000 + DURATION), 1_000 + DURATION).session;
  session = Timer.startWorkoutSegment(session, options({segmentId: 'segment-2'}), 2_000_000).session;
  Timer.saveWorkoutSession(store, session);
  const reopened = Timer.loadWorkoutSession(store, 2_000_000 + DURATION + 3_600_000);
  const snapshot = Timer.getWorkoutSnapshot(reopened, 2_000_000 + DURATION + 3_600_000);
  assert.equal(reopened.sessionStatus, 'overtime_running');
  assert.equal(snapshot.totalLayerProgress, 2 + 3_600_000 / DURATION);
  assert.equal(snapshot.cumulativeElapsedMs, DURATION * 2 + 3_600_000);
});

test('Existing v2 sessions without segmentLayers migrate cumulatively without timer loss', () => {
  const store = storage();
  const now = 5_000_000;
  const existing = {
    version: 2, sessionStatus: 'running', createdAt: 1_000, updatedAt: now,
    completedSegments: [{
      id: 'old-1', segmentNumber: 1, practiceType: 'move', targetLayers: 1,
      parameters: {layer: '1', speed: '9.0'}, plannedDurationMs: DURATION,
      actualElapsedMs: DURATION, status: 'completed', startedAt: 1_000,
      endAt: null, remainingMsAtPause: 0, completedAt: 1_000 + DURATION
    }],
    currentSegment: {
      id: 'old-2', segmentNumber: 2, practiceType: 'move', targetLayers: 1,
      parameters: {layer: '1', speed: '6.0'}, plannedDurationMs: DURATION,
      actualElapsedMs: null, status: 'running', startedAt: now - DURATION * 0.4,
      endAt: now + DURATION * 0.6, remainingMsAtPause: null, completedAt: null
    },
    draftSegment: null
  };
  store.setItem(Timer.SESSION_STORAGE_KEY, JSON.stringify(existing));
  const migrated = Timer.loadWorkoutSession(store, now);
  const snapshot = Timer.getWorkoutSnapshot(migrated, now);
  assert.equal(snapshot.totalLayerProgress, 1.4);
  assert.equal(migrated.currentSegment.endAt, existing.currentSegment.endAt);
  assert.equal(migrated.completedSegments[0].segmentLayers, 1);
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

test('Reload converts elapsed running segment to live overtime and allows Next', () => {
  const store = storage();
  Timer.saveWorkoutSession(store, start());
  const loaded = Timer.loadWorkoutSession(store, 1_000 + DURATION + 1);
  assert.equal(loaded.sessionStatus, 'overtime_running');
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

test('Five-layer limit rejects additional layers and preserves the completed workout', () => {
  let now = 1_000;
  let session = start(now);
  for (let number = 1; number <= 5; number += 1) {
    now += DURATION;
    session = finish(session, now);
    if (number < 5) {
      session = next(session, now).session;
      session = Timer.startWorkoutSegment(session, options({segmentId: `segment-${number + 1}`}), now + 1).session;
      now += 1;
    }
  }
  const finalSnapshot = Timer.getWorkoutSnapshot(session, now);
  const blocked = next(session, now);
  assert.equal(finalSnapshot.totalLayerProgress, 5);
  assert.equal(finalSnapshot.remainingLayers, 0);
  assert.equal(blocked.allowed, false);
  assert.equal(blocked.reason, 'all_layers_completed');
  assert.deepEqual(session.completedSegments.map(segment => segment.segmentNumber), [1,2,3,4]);
  assert.equal(finalSnapshot.cumulativeElapsedMs, DURATION * 5);
});

test('After four completed layers only one additional layer can be started', () => {
  let session = start(1_000, {
    targetLayers: 4, durationMs: DURATION * 4,
    parameters: {layer: '4', speed: '9.0'}
  });
  const finishedAt = 1_000 + DURATION * 4;
  session = next(finish(session, finishedAt), finishedAt).session;
  assert.equal(Timer.getWorkoutSnapshot(session, finishedAt).remainingLayers, 1);
  const tooMany = Timer.startWorkoutSegment(session, options({
    segmentId: 'invalid-2', targetLayers: 2, durationMs: DURATION * 2,
    parameters: {layer: '2', speed: '6.0'}
  }), finishedAt + 1);
  assert.equal(tooMany.started, false);
  assert.equal(tooMany.reason, 'layer_limit_exceeded');
  const valid = Timer.startWorkoutSegment(session, options({segmentId: 'valid-2'}), finishedAt + 1);
  assert.equal(valid.started, true);
  assert.equal(Timer.getWorkoutSnapshot(valid.session, finishedAt + 1).currentSegment.targetCumulativeLayers, 5);
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

test('Fifteen planned minutes plus seven and a half overtime minutes equal one and a half layers', () => {
  const duration = 15 * 60_000;
  const beganAt = 10_000;
  const session = start(beganAt, {durationMs: duration});
  const finalized = Timer.finalizeWorkoutOvertime(session, beganAt + duration + 7.5 * 60_000);
  const snapshot = Timer.getWorkoutSnapshot(finalized, beganAt + duration + 7.5 * 60_000);
  assert.equal(finalized.currentSegment.overtimeDurationMs, 7.5 * 60_000);
  assert.equal(finalized.currentSegment.overtimeLayers, 0.5);
  assert.equal(snapshot.totalLayerProgress, 1.5);
  assert.equal(snapshot.cumulativeElapsedMs, duration + 7.5 * 60_000);
});

test('The next segment starts from fractional layer progress left by overtime', () => {
  const duration = 15 * 60_000;
  const beganAt = 10_000;
  const finalized = Timer.finalizeWorkoutOvertime(start(beganAt, {durationMs: duration}), beganAt + duration * 1.5);
  let session = next(finalized, beganAt + duration * 1.5).session;
  session = Timer.startWorkoutSegment(session, options({segmentId: 'segment-2', durationMs: duration}), 2_000_000).session;
  const snapshot = Timer.getWorkoutSnapshot(session, 2_000_000);
  assert.equal(snapshot.completedLayers, 1.5);
  assert.equal(snapshot.currentSegment.currentLayer, 2);
  assert.equal(snapshot.currentSegment.layerBarPercent, 30);
});

test('New segment parameters cannot recalculate a previous segment overtime', () => {
  const duration = 15 * 60_000;
  const beganAt = 10_000;
  const finalized = Timer.finalizeWorkoutOvertime(start(beganAt, {durationMs: duration}), beganAt + duration * 1.5);
  let session = next(finalized, beganAt + duration * 1.5).session;
  session = Timer.startWorkoutSegment(session, options({
    segmentId: 'segment-2', durationMs: 40 * 60_000,
    parameters: {layer: '1', speed: '4.0'}
  }), 2_000_000).session;
  assert.equal(session.completedSegments[0].plannedDurationMs, duration);
  assert.equal(session.completedSegments[0].overtimeDurationMs, duration / 2);
  assert.equal(session.completedSegments[0].overtimeLayers, 0.5);
});

test('Returning after hidden wall-clock time finalizes overtime from timestamps', () => {
  const duration = 15 * 60_000;
  const beganAt = 10_000;
  const returnedAt = beganAt + duration + 123_456;
  const finalized = Timer.finalizeWorkoutOvertime(start(beganAt, {durationMs: duration}), returnedAt);
  assert.equal(finalized.currentSegment.plannedEndAt, beganAt + duration);
  assert.equal(finalized.currentSegment.overtimeDurationMs, 123_456);
  assert.equal(finalized.currentSegment.overtimeFinalizedAt, returnedAt);
});

test('Reload restores live overtime without finalizing it', () => {
  const store = storage();
  const duration = 15 * 60_000;
  const beganAt = 10_000;
  Timer.saveWorkoutSession(store, start(beganAt, {durationMs: duration}));
  const returnedAt = beganAt + duration + 90_000;
  const loaded = Timer.loadWorkoutSession(store, returnedAt);
  const persisted = JSON.parse(store.getItem(Timer.SESSION_STORAGE_KEY));
  const snapshot = Timer.getWorkoutSnapshot(loaded, returnedAt);
  assert.equal(loaded.sessionStatus, 'overtime_running');
  assert.equal(snapshot.currentSegment.overtimeDurationMs, 90_000);
  assert.equal(persisted.sessionStatus, 'overtime_running');
  assert.equal(persisted.currentSegment.overtimeFinalizedAt, null);
});

test('Repeated return synchronization never counts overtime twice', () => {
  const duration = 15 * 60_000;
  const beganAt = 10_000;
  const returnedAt = beganAt + duration + 90_000;
  const first = Timer.finalizeWorkoutOvertime(start(beganAt, {durationMs: duration}), returnedAt);
  const second = Timer.finalizeWorkoutOvertime(first, returnedAt + 600_000);
  assert.equal(second.currentSegment.overtimeDurationMs, 90_000);
  assert.equal(second.currentSegment.actualElapsedMs, duration + 90_000);
  assert.equal(second.currentSegment.overtimeFinalizedAt, returnedAt);
});

test('Pause shifts the planned end and paused time does not become overtime', () => {
  const duration = 15 * 60_000;
  const beganAt = 10_000;
  const pausedAt = beganAt + 5 * 60_000;
  const resumedAt = pausedAt + 20 * 60_000;
  let session = Timer.pauseWorkout(start(beganAt, {durationMs: duration}), pausedAt);
  session = Timer.resumeWorkout(session, resumedAt);
  const correctedEnd = resumedAt + 10 * 60_000;
  const finalized = Timer.finalizeWorkoutOvertime(session, correctedEnd + 60_000);
  assert.equal(finalized.currentSegment.plannedEndAt, correctedEnd);
  assert.equal(finalized.currentSegment.overtimeDurationMs, 60_000);
});

test('Overtime may contribute more than one full layer', () => {
  const duration = 15 * 60_000;
  const beganAt = 10_000;
  const finalized = Timer.finalizeWorkoutOvertime(start(beganAt, {durationMs: duration}), beganAt + duration + 20 * 60_000);
  assert.ok(Math.abs(finalized.currentSegment.overtimeLayers - 4 / 3) < 1e-12);
  assert.ok(Math.abs(finalized.currentSegment.actualLayers - 7 / 3) < 1e-12);
});

test('Reset storage clears a session that contains finalized overtime', () => {
  const store = storage();
  const duration = 15 * 60_000;
  const session = Timer.finalizeWorkoutOvertime(start(10_000, {durationMs: duration}), 10_000 + duration + 60_000);
  Timer.saveWorkoutSession(store, session);
  Timer.clearWorkoutSession(store);
  assert.equal(store.getItem(Timer.SESSION_STORAGE_KEY), null);
  assert.equal(Timer.loadWorkoutSession(store, 99_000_000), null);
});

test('Finalized overtime contributes to cumulative time exactly once across the next segment', () => {
  const duration = 15 * 60_000;
  const beganAt = 10_000;
  const returnedAt = beganAt + duration + 90_000;
  let session = next(Timer.finalizeWorkoutOvertime(start(beganAt, {durationMs: duration}), returnedAt), returnedAt).session;
  session = Timer.startWorkoutSegment(session, options({segmentId: 'segment-2', durationMs: duration}), 2_000_000).session;
  const snapshot = Timer.getWorkoutSnapshot(session, 2_000_000 + 60_000);
  assert.equal(snapshot.cumulativeElapsedMs, duration + 90_000 + 60_000);
  assert.equal(session.completedSegments[0].actualElapsedMs, duration + 90_000);
});

test('Live overtime keeps growing after repeated return and focus-style synchronization', () => {
  const duration = 15 * 60_000;
  const beganAt = 10_000;
  let session = Timer.syncWorkoutSession(start(beganAt, {durationMs: duration}), beganAt + duration + 21_000);
  const first = Timer.getWorkoutSnapshot(session, beganAt + duration + 21_000);
  session = Timer.syncWorkoutSession(session, beganAt + duration + 60_000);
  const second = Timer.getWorkoutSnapshot(session, beganAt + duration + 60_000);
  assert.equal(session.sessionStatus, 'overtime_running');
  assert.equal(first.currentSegment.overtimeDurationMs, 21_000);
  assert.equal(second.currentSegment.overtimeDurationMs, 60_000);
  assert.equal(session.currentSegment.overtimeFinalizedAt, null);
});

test('A later visibility return derives all overtime from plannedEndAt', () => {
  const duration = 15 * 60_000;
  const beganAt = 10_000;
  let session = Timer.syncWorkoutSession(start(beganAt, {durationMs: duration}), beganAt + duration + 60_000);
  session = Timer.syncWorkoutSession(session, beganAt + duration + 5 * 60_000);
  const snapshot = Timer.getWorkoutSnapshot(session, beganAt + duration + 5 * 60_000);
  assert.equal(snapshot.currentSegment.overtimeDurationMs, 5 * 60_000);
});

test('Next is the only boundary that freezes live overtime', () => {
  const duration = 15 * 60_000;
  const beganAt = 10_000;
  const pressedAt = beganAt + duration + 7.5 * 60_000;
  const live = Timer.syncWorkoutSession(start(beganAt, {durationMs: duration}), beganAt + duration + 21_000);
  const configured = next(live, pressedAt).session;
  const completed = configured.completedSegments[0];
  assert.equal(completed.overtimeDurationMs, 7.5 * 60_000);
  assert.equal(completed.overtimeLayers, 0.5);
  assert.equal(completed.overtimeFinalizedAt, pressedAt);
  assert.equal(Timer.getWorkoutSnapshot(configured, pressedAt + 60 * 60_000).completedElapsedMs, duration * 1.5);
});

test('Live overtime advances fractional layer progress before Next', () => {
  const duration = 15 * 60_000;
  const beganAt = 10_000;
  const session = Timer.syncWorkoutSession(start(beganAt, {durationMs: duration}), beganAt + duration);
  const snapshot = Timer.getWorkoutSnapshot(session, beganAt + duration + 7.5 * 60_000);
  assert.equal(snapshot.currentSegment.overtimeLayers, 0.5);
  assert.equal(snapshot.totalLayerProgress, 1.5);
  assert.equal(snapshot.currentSegment.currentLayer, 2);
  assert.equal(snapshot.layerBarPercent, 30);
});

test('Reloaded overtime continues growing and cumulative time includes it once', () => {
  const store = storage();
  const duration = 15 * 60_000;
  const beganAt = 10_000;
  const firstReturn = beganAt + duration + 3 * 60_000;
  const live = Timer.syncWorkoutSession(start(beganAt, {durationMs: duration}), firstReturn);
  Timer.saveWorkoutSession(store, live);
  const secondReturn = firstReturn + 5 * 60_000;
  const reloaded = Timer.loadWorkoutSession(store, secondReturn);
  const snapshot = Timer.getWorkoutSnapshot(reloaded, secondReturn);
  assert.equal(reloaded.sessionStatus, 'overtime_running');
  assert.equal(snapshot.currentSegment.overtimeDurationMs, 8 * 60_000);
  assert.equal(snapshot.cumulativeElapsedMs, duration + 8 * 60_000);
  assert.equal(reloaded.currentSegment.overtimeFinalizedAt, null);
});

test('A session frozen by the previous focus behavior resumes as live overtime', () => {
  const store = storage();
  const duration = 15 * 60_000;
  const beganAt = 10_000;
  const oldReturn = beganAt + duration + 60_000;
  const previouslyFrozen = Timer.finalizeWorkoutOvertime(start(beganAt, {durationMs: duration}), oldReturn);
  previouslyFrozen.currentSegment.completedAt = beganAt + duration;
  Timer.saveWorkoutSession(store, previouslyFrozen);
  const newReturn = oldReturn + 4 * 60_000;
  const restored = Timer.loadWorkoutSession(store, newReturn);
  const snapshot = Timer.getWorkoutSnapshot(restored, newReturn);
  assert.equal(restored.sessionStatus, 'overtime_running');
  assert.equal(snapshot.currentSegment.overtimeDurationMs, 5 * 60_000);
  assert.equal(restored.currentSegment.overtimeFinalizedAt, null);
});
