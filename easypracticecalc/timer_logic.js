(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.EasyPracticeTimer = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const STATE_VERSION = 1;
  const STORAGE_KEY = 'easypracticecalc.timerState.v1';
  const VALID_STATUSES = new Set(['running', 'paused', 'finished']);
  const VALID_PRACTICES = new Set(['water', 'move']);

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

  function formatRemaining(milliseconds) {
    const totalSeconds = Math.max(0, Math.ceil(Number(milliseconds) / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return [hours, minutes, seconds].map(value => String(value).padStart(2, '0')).join(':');
  }

  return {
    STATE_VERSION,
    STORAGE_KEY,
    normalizeState,
    createTimerState,
    getTimerSnapshot,
    pauseTimer,
    resumeTimer,
    finishTimer,
    loadTimerState,
    saveTimerState,
    clearTimerState,
    formatRemaining
  };
});
