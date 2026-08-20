(function () {
  'use strict';

  const Timer = window.EasyPracticeTimer;
  const storage = window.localStorage;
  const radius = 94;
  const circumference = 2 * Math.PI * radius;
  const warningMessage = 'Чтобы начать следующий отрезок, завершите текущий с теми же параметрами.';
  const elements = {
    practice: document.getElementById('timerPractice'),
    status: document.getElementById('timerStatus'),
    time: document.getElementById('timerTime'),
    cumulative: document.getElementById('timerCumulative'),
    progress: document.getElementById('timerProgress'),
    layers: document.getElementById('layerProgress'),
    start: document.getElementById('timerStart'),
    pause: document.getElementById('timerPause'),
    resume: document.getElementById('timerResume'),
    reset: document.getElementById('timerReset'),
    next: document.getElementById('timerNext'),
    history: document.getElementById('segmentHistory'),
    segmentList: document.getElementById('segmentList'),
    warning: document.getElementById('segmentWarning'),
    warningText: document.getElementById('segmentWarningText'),
    warningClose: document.getElementById('segmentWarningClose')
  };

  let workoutSession = Timer.loadWorkoutSession(storage, Date.now());
  let renderInterval = null;
  let warningReturnFocus = null;

  elements.progress.style.strokeDasharray = String(circumference);

  function createSegmentId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
    return `segment-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function activePractice() {
    return document.querySelector('.panel.active').id;
  }

  function practiceOptions(practiceType) {
    if (practiceType === 'move') {
      const minutes = moveData[moveSpeed.value][moveLayer.value];
      return {
        practiceType,
        durationMs: Math.round(minutes * 60) * 1000,
        targetLayers: Number(moveLayer.value),
        parameters: {layer: moveLayer.value, speed: moveSpeed.value}
      };
    }
    const minutes = waterData[waterTemp.value][waterLayer.value];
    return {
      practiceType: 'water',
      durationMs: Math.round(minutes * 60) * 1000,
      targetLayers: Number(waterLayer.value),
      parameters: {layer: waterLayer.value, temperature: waterTemp.value}
    };
  }

  function draftOptions() {
    const options = practiceOptions(activePractice());
    return {
      practiceType: options.practiceType,
      targetLayers: options.targetLayers,
      parameters: options.parameters
    };
  }

  function canConfigure() {
    return !workoutSession || workoutSession.sessionStatus === 'configuring_next_segment';
  }

  function setConfigurationEnabled(enabled) {
    [waterLayer, waterTemp, moveLayer, moveSpeed].forEach(select => { select.disabled = !enabled; });
    document.querySelectorAll('.tab').forEach(tab => {
      tab.classList.toggle('locked', !enabled);
      tab.setAttribute('aria-disabled', String(!enabled));
    });
  }

  function restoreControls(descriptor) {
    if (!descriptor) return;
    const parameters = descriptor.parameters || {};
    if (descriptor.practiceType === 'move') {
      if (parameters.layer && moveLayer.querySelector(`option[value="${parameters.layer}"]`)) moveLayer.value = parameters.layer;
      if (parameters.speed && moveSpeed.querySelector(`option[value="${parameters.speed}"]`)) moveSpeed.value = parameters.speed;
      openTab('move', document.querySelector('.tab[data-practice="move"]'));
      updateMove();
    } else {
      if (parameters.layer && waterLayer.querySelector(`option[value="${parameters.layer}"]`)) waterLayer.value = parameters.layer;
      if (parameters.temperature && waterTemp.querySelector(`option[value="${parameters.temperature}"]`)) waterTemp.value = parameters.temperature;
      openTab('water', document.querySelector('.tab[data-practice="water"]'));
      updateWater();
    }
  }

  function persistSession() {
    if (workoutSession) Timer.saveWorkoutSession(storage, workoutSession);
  }

  function showLockedWarning() {
    warningReturnFocus = document.activeElement;
    elements.warningText.textContent = warningMessage;
    elements.warning.hidden = false;
    elements.warningClose.focus();
  }

  function hideWarning() {
    elements.warning.hidden = true;
    if (warningReturnFocus && typeof warningReturnFocus.focus === 'function') warningReturnFocus.focus();
    warningReturnFocus = null;
  }

  function renderLayers(snapshot, selectedLayers) {
    elements.layers.replaceChildren();
    const completedLayers = snapshot ? snapshot.completedLayers : 0;
    const layerBarPercent = snapshot ? snapshot.layerBarPercent : 0;
    elements.layers.setAttribute('aria-valuenow', completedLayers.toFixed(2));
    elements.layers.setAttribute('aria-valuetext', `Пройдено ${completedLayers.toFixed(2)} из 5 слоёв. Цель: ${selectedLayers}.`);

    const scale = document.createElement('div');
    scale.className = 'layer-scale';
    const track = document.createElement('div');
    track.className = 'layer-track';
    const fill = document.createElement('div');
    fill.className = 'layer-fill';
    fill.style.width = `${layerBarPercent}%`;
    track.appendChild(fill);
    const markers = document.createElement('div');
    markers.className = 'layer-markers';

    for (let layer = 1; layer <= 5; layer += 1) {
      const item = document.createElement('div');
      item.className = 'layer-step';
      if (completedLayers >= layer) item.classList.add('complete');
      if (snapshot && snapshot.status !== 'completed' && layer === snapshot.currentLayer) item.classList.add('current');
      if (layer === selectedLayers) item.classList.add('target');
      const marker = document.createElement('span');
      marker.className = 'layer-marker';
      marker.textContent = String(layer);
      const label = document.createElement('span');
      label.className = 'layer-label';
      const fullLabel = document.createElement('span');
      fullLabel.className = 'layer-label-full';
      fullLabel.textContent = layer === 1 ? '1 слой' : layer < 5 ? `${layer} слоя` : '5 слоёв';
      const shortLabel = document.createElement('span');
      shortLabel.className = 'layer-label-short';
      shortLabel.textContent = String(layer);
      label.append(fullLabel, shortLabel);
      item.append(marker, label);
      markers.appendChild(item);
    }
    scale.append(track, markers);
    elements.layers.appendChild(scale);
  }

  function formatSegmentDuration(milliseconds) {
    const totalSeconds = Math.round(milliseconds / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (hours > 0) return [hours, minutes, seconds].map(value => String(value).padStart(2, '0')).join(':');
    return `${minutes}:${String(seconds).padStart(2, '0')}`;
  }

  function layerText(value) {
    if (value === 1) return '1 слой';
    if (value < 5) return `${value} слоя`;
    return '5 слоёв';
  }

  function paceText(speed) {
    const paceSeconds = Math.round(3600 / Number(speed));
    const minutes = Math.floor(paceSeconds / 60);
    const seconds = paceSeconds % 60;
    return seconds ? `${minutes} мин ${seconds} сек/км` : `${minutes} мин/км`;
  }

  function segmentDescription(segment) {
    const parts = [
      `${segment.segmentNumber} отрезок`,
      layerText(segment.targetLayers),
      formatSegmentDuration(segment.plannedDurationMs)
    ];
    if (segment.practiceType === 'move') {
      const speed = Number(segment.parameters.speed);
      parts.push(`${speed} км/ч (${paceText(speed)})`);
    } else {
      parts.push(`${segment.parameters.temperature} °C`);
    }
    return parts.join(' · ');
  }

  function renderHistory() {
    const segments = workoutSession ? workoutSession.completedSegments : [];
    elements.segmentList.replaceChildren();
    elements.history.hidden = segments.length === 0;
    segments.forEach(segment => {
      const item = document.createElement('li');
      item.className = 'segment-item';
      const text = document.createElement('span');
      text.textContent = segmentDescription(segment);
      const check = document.createElement('span');
      check.className = 'segment-check';
      check.textContent = '✓';
      check.setAttribute('aria-label', 'Завершён');
      item.append(text, check);
      elements.segmentList.appendChild(item);
    });
  }

  function stopVisualUpdates() {
    if (renderInterval !== null) window.clearInterval(renderInterval);
    renderInterval = null;
  }

  function ensureVisualUpdates() {
    stopVisualUpdates();
    if (workoutSession && workoutSession.sessionStatus === 'running') {
      renderInterval = window.setInterval(() => refresh(Date.now()), 250);
    }
  }

  function preview() {
    if (workoutSession && workoutSession.sessionStatus !== 'configuring_next_segment') return;
    const options = practiceOptions(activePractice());
    const segmentNumber = workoutSession ? workoutSession.draftSegment.segmentNumber : 1;
    const cumulative = workoutSession ? Timer.getWorkoutSnapshot(workoutSession, Date.now()).cumulativeElapsedMs : 0;
    elements.practice.textContent = `Отрезок ${segmentNumber} · ${options.practiceType === 'water' ? 'Вода' : 'Ходьба/бег'}`;
    elements.status.textContent = 'Готово к запуску';
    elements.time.textContent = Timer.formatRemaining(options.durationMs);
    elements.cumulative.textContent = Timer.formatElapsed(cumulative);
    elements.progress.style.strokeDashoffset = String(circumference);
    renderLayers(null, options.targetLayers);
    elements.start.hidden = false;
    elements.start.textContent = `Начать отрезок ${segmentNumber}`;
    elements.pause.hidden = true;
    elements.resume.hidden = true;
    elements.reset.hidden = !workoutSession;
    elements.next.hidden = true;
    setConfigurationEnabled(true);
    renderHistory();
  }

  function refresh(now) {
    if (!workoutSession || workoutSession.sessionStatus === 'configuring_next_segment') {
      preview();
      return;
    }
    const previousStatus = workoutSession.sessionStatus;
    workoutSession = Timer.syncWorkoutSession(workoutSession, now);
    if (workoutSession.sessionStatus !== previousStatus) {
      persistSession();
      stopVisualUpdates();
    }
    const snapshot = Timer.getWorkoutSnapshot(workoutSession, now);
    const segment = workoutSession.currentSegment;
    const current = snapshot.currentSegment;
    elements.practice.textContent = `Отрезок ${segment.segmentNumber} · ${segment.practiceType === 'water' ? 'Вода' : 'Ходьба/бег'}`;
    elements.status.textContent = snapshot.sessionStatus === 'running'
      ? `Идёт ${current.currentLayer} слой из ${current.targetLayers}`
      : snapshot.sessionStatus === 'paused'
        ? `Пауза · ${current.currentLayer} слой из ${current.targetLayers}`
        : 'Отрезок завершён';
    elements.time.textContent = Timer.formatRemaining(current.remainingMs);
    elements.cumulative.textContent = Timer.formatElapsed(snapshot.cumulativeElapsedMs);
    elements.progress.style.strokeDashoffset = String(circumference * (1 - current.progress));
    renderLayers(current, current.targetLayers);
    elements.start.hidden = true;
    elements.pause.hidden = snapshot.sessionStatus !== 'running';
    elements.resume.hidden = snapshot.sessionStatus !== 'paused';
    elements.reset.hidden = false;
    elements.next.hidden = false;
    elements.next.classList.toggle('secondary', snapshot.sessionStatus !== 'segment_completed');
    elements.next.title = snapshot.sessionStatus === 'segment_completed' ? 'Настроить следующий отрезок' : warningMessage;
    setConfigurationEnabled(false);
    renderHistory();
  }

  function startSegment() {
    const options = Object.assign(practiceOptions(activePractice()), {segmentId: createSegmentId()});
    const result = Timer.startWorkoutSegment(workoutSession, options, Date.now());
    if (!result.started) {
      showLockedWarning();
      return;
    }
    workoutSession = result.session;
    persistSession();
    refresh(Date.now());
    ensureVisualUpdates();
  }

  function pause() {
    workoutSession = Timer.pauseWorkout(workoutSession, Date.now());
    persistSession();
    stopVisualUpdates();
    refresh(Date.now());
  }

  function resume() {
    workoutSession = Timer.resumeWorkout(workoutSession, Date.now());
    persistSession();
    refresh(Date.now());
    ensureVisualUpdates();
  }

  function nextSegment() {
    const result = Timer.requestNextSegment(workoutSession, Date.now());
    if (!result.allowed) {
      showLockedWarning();
      return;
    }
    workoutSession = result.session;
    persistSession();
    stopVisualUpdates();
    restoreControls(workoutSession.draftSegment);
    preview();
  }

  function updateDraftFromControls() {
    if (!canConfigure()) return;
    if (workoutSession) {
      workoutSession = Timer.updateDraftSegment(workoutSession, draftOptions(), Date.now());
      persistSession();
    }
    preview();
  }

  function reset() {
    stopVisualUpdates();
    workoutSession = null;
    Timer.clearWorkoutSession(storage);
    setConfigurationEnabled(true);
    preview();
  }

  elements.start.addEventListener('click', startSegment);
  elements.pause.addEventListener('click', pause);
  elements.resume.addEventListener('click', resume);
  elements.reset.addEventListener('click', reset);
  elements.next.addEventListener('click', nextSegment);
  elements.warningClose.addEventListener('click', hideWarning);
  elements.warning.addEventListener('click', event => {
    if (event.target === elements.warning) hideWarning();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !elements.warning.hidden) hideWarning();
  });
  document.querySelectorAll('select').forEach(element => element.addEventListener('change', updateDraftFromControls));
  document.querySelectorAll('.tab').forEach(element => element.addEventListener('click', () => window.setTimeout(updateDraftFromControls, 0)));
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refresh(Date.now());
  });
  window.addEventListener('pageshow', () => refresh(Date.now()));
  window.addEventListener('focus', () => refresh(Date.now()));

  const descriptor = workoutSession ? workoutSession.currentSegment || workoutSession.draftSegment : null;
  restoreControls(descriptor);
  if (workoutSession) persistSession();
  window.easyTimerController = {refresh, preview, canConfigure, showLockedWarning};
  refresh(Date.now());
  ensureVisualUpdates();
})();
