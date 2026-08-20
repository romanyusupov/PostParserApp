(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.EasyPracticeTimer = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const STATE_VERSION = 1;
  const STORAGE_KEY = 'easypracticecalc.timerState.v1';
  const SESSION_VERSION = 2;
  const SESSION_STORAGE_KEY = 'easypracticecalc.workoutSession.v2';
  const VALID_STATUSES = new Set(['running', 'paused', 'finished']);
  const VALID_PRACTICES = new Set(['water', 'move']);
  const VALID_SESSION_STATUSES = new Set([
    'running',
    'paused',
    'segment_completed',
    'configuring_next_segment'
  ]);

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function normalizeState(value) {
    if (!value || value.version !== STATE_VERSION) return null;
    if (!VALID_STATUSES.has(value.status) || !VALID_PRACTICES.has(value.practiceType)) return null;

    const durationMs = Number(value.durationMs);
    const targetLayers = Number(value.targetLayers);
    if (!Number.isFinite(durationMs) || durationMs <= 0) return null;
    if (!Number.isInteger(targetLayers) || targetLayers < 1 || targetLayers > 5) return null;

    const normalized = {
      version: STATE_VERSION,
      status: value.status,
      practiceType: value.practiceType,
      startedAt: Number(value.startedAt) || null,
      endAt: Number(value.endAt) || null,
      durationMs,
      remainingMsAtPause: value.remainingMsAtPause == null
        ? null
        : clamp(Number(value.remainingMsAtPause) || 0, 0, durationMs),
      targetLayers,
      parameters: value.parameters && typeof value.parameters === 'object'
        ? Object.assign({}, value.parameters)
        : {},
      createdAt: Number(value.createdAt) || null,
      updatedAt: Number(value.updatedAt) || null
    };

    if (normalized.status === 'running' && !normalized.endAt) return null;
    if (normalized.status === 'paused' && normalized.remainingMsAtPause == null) return null;
    return normalized;
  }

  function createTimerState(options, now) {
    const timestamp = Number(now);
    const durationMs = Number(options.durationMs);
    const targetLayers = Number(options.targetLayers);
    if (!Number.isFinite(timestamp) || !Number.isFinite(durationMs) || durationMs <= 0) {
      throw new Error('Некорректная длительность таймера.');
    }
    if (!VALID_PRACTICES.has(options.practiceType)) throw new Error('Неизвестный тип практики.');
    if (!Number.isInteger(targetLayers) || targetLayers < 1 || targetLayers > 5) {
      throw new Error('Некорректное количество слоёв.');
    }

    return {
      version: STATE_VERSION,
      status: 'running',
      practiceType: options.practiceType,
      startedAt: timestamp,
      endAt: timestamp + durationMs,
      durationMs,
      remainingMsAtPause: null,
      targetLayers,
      parameters: Object.assign({}, options.parameters || {}),
      createdAt: timestamp,
      updatedAt: timestamp
    };
  }

  function getTimerSnapshot(state, now) {
    const normalized = normalizeState(state);
    if (!normalized) return null;

    let remainingMs;
    if (normalized.status === 'running') {
      remainingMs = clamp(normalized.endAt - Number(now), 0, normalized.durationMs);
    } else if (normalized.status === 'paused') {
      remainingMs = normalized.remainingMsAtPause;
    } else {
      remainingMs = 0;
    }

    const elapsedMs = normalized.durationMs - remainingMs;
    const progress = clamp(elapsedMs / normalized.durationMs, 0, 1);
    const completedLayers = clamp(normalized.targetLayers * progress, 0, normalized.targetLayers);
    const layerBarPercent = completedLayers / 5 * 100;
    const currentLayer = progress >= 1
      ? normalized.targetLayers
      : Math.min(normalized.targetLayers, Math.floor(completedLayers) + 1);

    return {
      status: normalized.status === 'running' && remainingMs === 0 ? 'finished' : normalized.status,
      remainingMs,
      elapsedMs,
      progress,
      completedLayers,
      layerBarPercent,
      currentLayer,
      targetLayers: normalized.targetLayers
    };
  }

  function pauseTimer(state, now) {
    const normalized = normalizeState(state);
    if (!normalized || normalized.status !== 'running') return normalized;
    const snapshot = getTimerSnapshot(normalized, now);
    if (snapshot.status === 'finished') return finishTimer(normalized, now);
    return Object.assign({}, normalized, {
      status: 'paused',
      startedAt: null,
      endAt: null,
      remainingMsAtPause: snapshot.remainingMs,
      updatedAt: Number(now)
    });
  }

  function resumeTimer(state, now) {
    const normalized = normalizeState(state);
    if (!normalized || normalized.status !== 'paused') return normalized;
    if (normalized.remainingMsAtPause <= 0) return finishTimer(normalized, now);
    return Object.assign({}, normalized, {
      status: 'running',
      startedAt: Number(now),
      endAt: Number(now) + normalized.remainingMsAtPause,
      remainingMsAtPause: null,
      updatedAt: Number(now)
    });
  }

  function finishTimer(state, now) {
    const normalized = normalizeState(state);
    if (!normalized) return null;
    return Object.assign({}, normalized, {
      status: 'finished',
      startedAt: null,
      endAt: null,
      remainingMsAtPause: 0,
      updatedAt: Number(now)
    });
  }

  function loadTimerState(storage) {
    try {
      return normalizeState(JSON.parse(storage.getItem(STORAGE_KEY)));
    } catch (_) {
      return null;
    }
  }

  function saveTimerState(storage, state) {
    const normalized = normalizeState(state);
    if (!normalized) throw new Error('Некорректное состояние таймера.');
    storage.setItem(STORAGE_KEY, JSON.stringify(normalized));
    return normalized;
  }

  function clearTimerState(storage) {
    storage.removeItem(STORAGE_KEY);
  }

  function normalizeSegment(value) {
    if (!value || typeof value !== 'object' || !VALID_PRACTICES.has(value.practiceType)) return null;
    if (!['running', 'paused', 'completed'].includes(value.status)) return null;
    const plannedDurationMs = Number(value.plannedDurationMs);
    const targetLayers = Number(value.targetLayers);
    const segmentNumber = Number(value.segmentNumber);
    if (!Number.isFinite(plannedDurationMs) || plannedDurationMs <= 0) return null;
    if (!Number.isInteger(targetLayers) || targetLayers < 1 || targetLayers > 5) return null;
    if (!Number.isInteger(segmentNumber) || segmentNumber < 1) return null;

    const segment = {
      id: String(value.id || `segment-${segmentNumber}`),
      segmentNumber,
      practiceType: value.practiceType,
      targetLayers,
      parameters: value.parameters && typeof value.parameters === 'object'
        ? Object.assign({}, value.parameters)
        : {},
      plannedDurationMs,
      actualElapsedMs: value.status === 'completed' ? plannedDurationMs : null,
      status: value.status,
      startedAt: Number(value.startedAt) || null,
      endAt: Number(value.endAt) || null,
      remainingMsAtPause: value.remainingMsAtPause == null
        ? null
        : clamp(Number(value.remainingMsAtPause) || 0, 0, plannedDurationMs),
      completedAt: Number(value.completedAt) || null
    };
    if (segment.status === 'running' && !segment.endAt) return null;
    if (segment.status === 'paused' && segment.remainingMsAtPause == null) return null;
    return segment;
  }

  function normalizeDraft(value) {
    if (!value || !VALID_PRACTICES.has(value.practiceType)) return null;
    const segmentNumber = Number(value.segmentNumber);
    const targetLayers = Number(value.targetLayers);
    if (!Number.isInteger(segmentNumber) || segmentNumber < 1) return null;
    if (!Number.isInteger(targetLayers) || targetLayers < 1 || targetLayers > 5) return null;
    return {
      segmentNumber,
      practiceType: value.practiceType,
      targetLayers,
      parameters: value.parameters && typeof value.parameters === 'object'
        ? Object.assign({}, value.parameters)
        : {}
    };
  }

  function normalizeWorkoutSession(value) {
    if (!value || value.version !== SESSION_VERSION) return null;
    if (!VALID_SESSION_STATUSES.has(value.sessionStatus)) return null;
    const completedSegments = Array.isArray(value.completedSegments)
      ? value.completedSegments.map(normalizeSegment)
      : [];
    if (completedSegments.some(segment => !segment || segment.status !== 'completed')) return null;
    const currentSegment = value.currentSegment ? normalizeSegment(value.currentSegment) : null;
    const draftSegment = value.draftSegment ? normalizeDraft(value.draftSegment) : null;
    if (value.sessionStatus === 'configuring_next_segment') {
      if (currentSegment || !draftSegment) return null;
    } else if (!currentSegment) {
      return null;
    } else {
      const requiredSegmentStatus = {
        running: 'running',
        paused: 'paused',
        segment_completed: 'completed'
      }[value.sessionStatus];
      if (currentSegment.status !== requiredSegmentStatus || draftSegment) return null;
    }
    return {
      version: SESSION_VERSION,
      sessionStatus: value.sessionStatus,
      completedSegments,
      currentSegment,
      draftSegment,
      createdAt: Number(value.createdAt) || null,
      updatedAt: Number(value.updatedAt) || null
    };
  }

  function createSegment(options, now, segmentNumber) {
    const durationMs = Number(options.durationMs);
    const targetLayers = Number(options.targetLayers);
    if (!VALID_PRACTICES.has(options.practiceType)) throw new Error('Неизвестный тип практики.');
    if (!Number.isFinite(durationMs) || durationMs <= 0) throw new Error('Некорректная длительность отрезка.');
    if (!Number.isInteger(targetLayers) || targetLayers < 1 || targetLayers > 5) {
      throw new Error('Некорректное количество слоёв.');
    }
    return {
      id: String(options.segmentId || `segment-${segmentNumber}-${Number(now)}`),
      segmentNumber,
      practiceType: options.practiceType,
      targetLayers,
      parameters: Object.assign({}, options.parameters || {}),
      plannedDurationMs: durationMs,
      actualElapsedMs: null,
      status: 'running',
      startedAt: Number(now),
      endAt: Number(now) + durationMs,
      remainingMsAtPause: null,
      completedAt: null
    };
  }

  function getSegmentSnapshot(segment, now) {
    const normalized = normalizeSegment(segment);
    if (!normalized) return null;
    let remainingMs;
    if (normalized.status === 'running') {
      remainingMs = clamp(normalized.endAt - Number(now), 0, normalized.plannedDurationMs);
    } else if (normalized.status === 'paused') {
      remainingMs = normalized.remainingMsAtPause;
    } else {
      remainingMs = 0;
    }
    const elapsedMs = normalized.plannedDurationMs - remainingMs;
    const progress = clamp(elapsedMs / normalized.plannedDurationMs, 0, 1);
    const completedLayers = clamp(normalized.targetLayers * progress, 0, normalized.targetLayers);
    return {
      status: normalized.status === 'running' && remainingMs === 0 ? 'completed' : normalized.status,
      remainingMs,
      elapsedMs,
      progress,
      completedLayers,
      layerBarPercent: completedLayers / 5 * 100,
      currentLayer: progress >= 1
        ? normalized.targetLayers
        : Math.min(normalized.targetLayers, Math.floor(completedLayers) + 1),
      targetLayers: normalized.targetLayers
    };
  }

  function completedDuration(session) {
    return session.completedSegments.reduce(
      (total, segment) => total + segment.plannedDurationMs,
      0
    );
  }

  function getWorkoutSnapshot(session, now) {
    const normalized = normalizeWorkoutSession(session);
    if (!normalized) return null;
    const segment = normalized.currentSegment
      ? getSegmentSnapshot(normalized.currentSegment, now)
      : null;
    const completedElapsedMs = completedDuration(normalized);
    return {
      sessionStatus: segment && segment.status === 'completed'
        ? 'segment_completed'
        : normalized.sessionStatus,
      currentSegment: segment,
      completedElapsedMs,
      cumulativeElapsedMs: completedElapsedMs + (segment ? segment.elapsedMs : 0),
      nextSegmentNumber: normalized.currentSegment
        ? normalized.currentSegment.segmentNumber + (segment && segment.status === 'completed' ? 1 : 0)
        : normalized.draftSegment.segmentNumber
    };
  }

  function syncWorkoutSession(session, now) {
    const normalized = normalizeWorkoutSession(session);
    if (!normalized || !normalized.currentSegment) return normalized;
    const snapshot = getSegmentSnapshot(normalized.currentSegment, now);
    if (snapshot.status !== 'completed' || normalized.currentSegment.status === 'completed') return normalized;
    const completedAt = normalized.currentSegment.endAt || Number(now);
    return Object.assign({}, normalized, {
      sessionStatus: 'segment_completed',
      currentSegment: Object.assign({}, normalized.currentSegment, {
        status: 'completed',
        actualElapsedMs: normalized.currentSegment.plannedDurationMs,
        endAt: null,
        remainingMsAtPause: 0,
        completedAt
      }),
      updatedAt: Number(now)
    });
  }

  function startWorkoutSegment(session, options, now) {
    if (!session) {
      const currentSegment = createSegment(options, now, 1);
      return {
        started: true,
        session: {
          version: SESSION_VERSION,
          sessionStatus: 'running',
          completedSegments: [],
          currentSegment,
          draftSegment: null,
          createdAt: Number(now),
          updatedAt: Number(now)
        }
      };
    }
    const normalized = normalizeWorkoutSession(session);
    if (!normalized || normalized.sessionStatus !== 'configuring_next_segment') {
      return {started: false, reason: 'segment_already_active', session: normalized};
    }
    const segmentNumber = normalized.draftSegment.segmentNumber;
    return {
      started: true,
      session: Object.assign({}, normalized, {
        sessionStatus: 'running',
        currentSegment: createSegment(options, now, segmentNumber),
        draftSegment: null,
        updatedAt: Number(now)
      })
    };
  }

  function pauseWorkout(session, now) {
    const normalized = syncWorkoutSession(session, now);
    if (!normalized || normalized.sessionStatus !== 'running') return normalized;
    const snapshot = getSegmentSnapshot(normalized.currentSegment, now);
    if (snapshot.status === 'completed') return syncWorkoutSession(normalized, now);
    return Object.assign({}, normalized, {
      sessionStatus: 'paused',
      currentSegment: Object.assign({}, normalized.currentSegment, {
        status: 'paused',
        endAt: null,
        remainingMsAtPause: snapshot.remainingMs
      }),
      updatedAt: Number(now)
    });
  }

  function resumeWorkout(session, now) {
    const normalized = normalizeWorkoutSession(session);
    if (!normalized || normalized.sessionStatus !== 'paused') return normalized;
    const remainingMs = normalized.currentSegment.remainingMsAtPause;
    if (remainingMs <= 0) return syncWorkoutSession(normalized, now);
    return Object.assign({}, normalized, {
      sessionStatus: 'running',
      currentSegment: Object.assign({}, normalized.currentSegment, {
        status: 'running',
        endAt: Number(now) + remainingMs,
        remainingMsAtPause: null
      }),
      updatedAt: Number(now)
    });
  }

  function requestNextSegment(session, now) {
    const normalized = syncWorkoutSession(session, now);
    if (!normalized || normalized.sessionStatus !== 'segment_completed') {
      return {allowed: false, reason: 'next_segment_not_allowed', session: normalized};
    }
    const completed = normalized.currentSegment;
    const alreadyStored = normalized.completedSegments.some(segment => segment.id === completed.id);
    const completedSegments = alreadyStored
      ? normalized.completedSegments.slice()
      : normalized.completedSegments.concat(completed);
    return {
      allowed: true,
      session: Object.assign({}, normalized, {
        sessionStatus: 'configuring_next_segment',
        completedSegments,
        currentSegment: null,
        draftSegment: {
          segmentNumber: completed.segmentNumber + 1,
          practiceType: completed.practiceType,
          targetLayers: completed.targetLayers,
          parameters: Object.assign({}, completed.parameters)
        },
        updatedAt: Number(now)
      })
    };
  }

  function updateDraftSegment(session, draft, now) {
    const normalized = normalizeWorkoutSession(session);
    if (!normalized || normalized.sessionStatus !== 'configuring_next_segment') return normalized;
    const nextDraft = normalizeDraft(Object.assign({}, draft, {
      segmentNumber: normalized.draftSegment.segmentNumber
    }));
    if (!nextDraft) return normalized;
    return Object.assign({}, normalized, {draftSegment: nextDraft, updatedAt: Number(now)});
  }

  function migrateTimerState(timerState, now) {
    const legacy = normalizeState(timerState);
    if (!legacy) return null;
    const segmentStatus = legacy.status === 'finished' ? 'completed' : legacy.status;
    let session = {
      version: SESSION_VERSION,
      sessionStatus: segmentStatus === 'completed' ? 'segment_completed' : segmentStatus,
      completedSegments: [],
      currentSegment: {
        id: 'migrated-segment-1',
        segmentNumber: 1,
        practiceType: legacy.practiceType,
        targetLayers: legacy.targetLayers,
        parameters: Object.assign({}, legacy.parameters),
        plannedDurationMs: legacy.durationMs,
        actualElapsedMs: segmentStatus === 'completed' ? legacy.durationMs : null,
        status: segmentStatus,
        startedAt: legacy.startedAt,
        endAt: legacy.endAt,
        remainingMsAtPause: segmentStatus === 'completed' ? 0 : legacy.remainingMsAtPause,
        completedAt: segmentStatus === 'completed' ? (legacy.updatedAt || Number(now)) : null
      },
      draftSegment: null,
      createdAt: legacy.createdAt || Number(now),
      updatedAt: Number(now)
    };
    session = syncWorkoutSession(session, now);
    return session;
  }

  function loadWorkoutSession(storage, now) {
    try {
      const stored = normalizeWorkoutSession(JSON.parse(storage.getItem(SESSION_STORAGE_KEY)));
      if (stored) return syncWorkoutSession(stored, now);
      const legacy = loadTimerState(storage);
      if (!legacy) return null;
      const migrated = migrateTimerState(legacy, now);
      saveWorkoutSession(storage, migrated);
      clearTimerState(storage);
      return migrated;
    } catch (_) {
      return null;
    }
  }

  function saveWorkoutSession(storage, session) {
    const normalized = normalizeWorkoutSession(session);
    if (!normalized) throw new Error('Некорректное состояние тренировки.');
    storage.setItem(SESSION_STORAGE_KEY, JSON.stringify(normalized));
    return normalized;
  }

  function clearWorkoutSession(storage) {
    storage.removeItem(SESSION_STORAGE_KEY);
    storage.removeItem(STORAGE_KEY);
  }

  function formatRemaining(milliseconds) {
    const totalSeconds = Math.max(0, Math.ceil(Number(milliseconds) / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return [hours, minutes, seconds].map(value => String(value).padStart(2, '0')).join(':');
  }

  function formatElapsed(milliseconds) {
    const totalSeconds = Math.max(0, Math.floor(Number(milliseconds) / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return [hours, minutes, seconds].map(value => String(value).padStart(2, '0')).join(':');
  }

  return {
    STATE_VERSION,
    STORAGE_KEY,
    SESSION_VERSION,
    SESSION_STORAGE_KEY,
    normalizeState,
    createTimerState,
    getTimerSnapshot,
    pauseTimer,
    resumeTimer,
    finishTimer,
    loadTimerState,
    saveTimerState,
    clearTimerState,
    normalizeWorkoutSession,
    getSegmentSnapshot,
    getWorkoutSnapshot,
    syncWorkoutSession,
    startWorkoutSegment,
    pauseWorkout,
    resumeWorkout,
    requestNextSegment,
    updateDraftSegment,
    migrateTimerState,
    loadWorkoutSession,
    saveWorkoutSession,
    clearWorkoutSession,
    formatRemaining,
    formatElapsed
  };
});
