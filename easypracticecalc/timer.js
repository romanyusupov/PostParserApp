(function () {
  'use strict';

  const Timer = window.EasyPracticeTimer;
  const storage = window.localStorage;
  const radius = 94;
  const circumference = 2 * Math.PI * radius;
  const warningMessage = 'Чтобы начать следующий отрезок, завершите текущий с теми же параметрами.';
  const allLayersMessage = 'Все 5 слоёв пройдены.';
  const mobileQuery = window.matchMedia('(max-width: 600px)');
  const elements = {
    parameters: document.getElementById('practiceParameters'),
    parameterToggle: document.getElementById('parameterToggle'),
    parameterSummary: document.getElementById('parameterSummary'),
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
  let parametersExpanded = !workoutSession || workoutSession.sessionStatus === 'configuring_next_segment';

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
        segmentLayers: Number(moveLayer.value),
        targetLayers: Number(moveLayer.value),
        parameters: {layer: moveLayer.value, speed: moveSpeed.value}
      };
    }
    const minutes = waterData[waterTemp.value][waterLayer.value];
    return {
      practiceType: 'water',
      durationMs: Math.round(minutes * 60) * 1000,
      segmentLayers: Number(waterLayer.value),
      targetLayers: Number(waterLayer.value),
      parameters: {layer: waterLayer.value, temperature: waterTemp.value}
    };
  }

  function draftOptions() {
    const options = practiceOptions(activePractice());
    return {
      practiceType: options.practiceType,
      segmentLayers: options.segmentLayers,
      targetLayers: options.targetLayers,
      parameters: options.parameters
    };
  }

  function canConfigure() {
    return !workoutSession || workoutSession.sessionStatus === 'configuring_next_segment';
  }

  function setParametersExpanded(expanded) {
    parametersExpanded = Boolean(expanded);
    const visuallyExpanded = !mobileQuery.matches || parametersExpanded;
    elements.parameters.classList.toggle('mobile-collapsed', !visuallyExpanded);
    elements.parameterToggle.setAttribute('aria-expanded', String(visuallyExpanded));
  }

  function limitLayerSelectors(maximum) {
    const safeMaximum = Math.max(1, Math.min(5, Number(maximum) || 1));
    [waterLayer, moveLayer].forEach(select => {
      Array.from(select.options).forEach(option => {
        const unavailable = Number(option.value) > safeMaximum;
        option.hidden = unavailable;
        option.disabled = unavailable;
      });
      if (Number(select.value) > safeMaximum) select.value = String(safeMaximum);
    });
  }

  function remainingLayerCapacity() {
    if (!workoutSession) return 5;
    return Timer.getWorkoutSnapshot(workoutSession, Date.now()).remainingLayers;
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
    const layerValue = String(parameters.layer || descriptor.segmentLayers || descriptor.targetLayers || 1);
    if (descriptor.practiceType === 'move') {
      if (moveLayer.querySelector(`option[value="${layerValue}"]`)) moveLayer.value = layerValue;
      if (parameters.speed && moveSpeed.querySelector(`option[value="${parameters.speed}"]`)) moveSpeed.value = parameters.speed;
      openTab('move', document.querySelector('.tab[data-practice="move"]'));
      updateMove();
    } else {
      if (waterLayer.querySelector(`option[value="${layerValue}"]`)) waterLayer.value = layerValue;
      if (parameters.temperature && waterTemp.querySelector(`option[value="${parameters.temperature}"]`)) waterTemp.value = parameters.temperature;
      openTab('water', document.querySelector('.tab[data-practice="water"]'));
      updateWater();
    }
  }

  function persistSession() {
    if (workoutSession) Timer.saveWorkoutSession(storage, workoutSession);
  }

  function showLockedWarning(message) {
    warningReturnFocus = document.activeElement;
    elements.warningText.textContent = message || warningMessage;
    elements.warning.hidden = false;
    elements.warningClose.focus();
  }

  function hideWarning() {
    elements.warning.hidden = true;
    if (warningReturnFocus && typeof warningReturnFocus.focus === 'function') warningReturnFocus.focus();
    warningReturnFocus = null;
  }

  function renderLayers(snapshot, targetCumulativeLayers) {
    elements.layers.replaceChildren();
    const completedLayers = snapshot ? snapshot.completedLayers : 0;
    const layerBarPercent = snapshot ? snapshot.layerBarPercent : 0;
    const targetLayers = Math.max(0, Math.min(5, Number(targetCumulativeLayers) || 0));
    elements.layers.setAttribute('aria-valuenow', completedLayers.toFixed(2));
    elements.layers.setAttribute('aria-valuetext', `Пройдено ${completedLayers.toFixed(2)} из 5 слоёв. Цель: ${targetLayers}.`);

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
      if (layer === targetLayers) item.classList.add('target');
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

  function compactPaceText(speed) {
    const paceSeconds = Math.round(3600 / Number(speed));
    return `${Math.floor(paceSeconds / 60)}:${String(paceSeconds % 60).padStart(2, '0')}/км`;
  }

  function updateParameterSummary(descriptor) {
    const source = descriptor || practiceOptions(activePractice());
    const parameters = source.parameters || {};
    const layers = Number(source.segmentLayers || source.targetLayers || parameters.layer || 1);
    if (source.practiceType === 'move') {
      const speed = parameters.speed || moveSpeed.value;
      elements.parameterSummary.textContent = `${layerText(layers)} · ${Number(speed)} км/ч · ${compactPaceText(speed)}`;
    } else {
      const temperature = parameters.temperature || waterTemp.value;
      elements.parameterSummary.textContent = `${layerText(layers)} · ${temperature} °C`;
    }
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
    const segments = workoutSession ? workoutSession.completedSegments.slice() : [];
    if (workoutSession && workoutSession.currentSegment && workoutSession.currentSegment.status === 'completed') {
      const snapshot = Timer.getWorkoutSnapshot(workoutSession, Date.now());
      const current = workoutSession.currentSegment;
      if (snapshot.totalLayerProgress >= 5 && !segments.some(segment => segment.id === current.id)) segments.push(current);
    }
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
    const sessionSnapshot = workoutSession ? Timer.getWorkoutSnapshot(workoutSession, Date.now()) : null;
    const completedLayers = sessionSnapshot ? sessionSnapshot.completedLayers : 0;
    const remainingLayers = sessionSnapshot ? sessionSnapshot.remainingLayers : 5;
    limitLayerSelectors(remainingLayers || 1);
    const options = practiceOptions(activePractice());
    const segmentNumber = workoutSession ? workoutSession.draftSegment.segmentNumber : 1;
    const cumulative = sessionSnapshot ? sessionSnapshot.cumulativeElapsedMs : 0;
    const targetCumulativeLayers = Math.min(5, completedLayers + options.segmentLayers);
    elements.practice.textContent = `Отрезок ${segmentNumber} · ${options.practiceType === 'water' ? 'Вода' : 'Ходьба/бег'}`;
    elements.status.textContent = remainingLayers > 0 ? 'Готово к запуску' : allLayersMessage;
    elements.time.textContent = Timer.formatRemaining(options.durationMs);
    elements.cumulative.textContent = Timer.formatElapsed(cumulative);
    elements.progress.style.strokeDashoffset = String(circumference);
    renderLayers({
      status: 'configuring',
      completedLayers,
      layerBarPercent: completedLayers / 5 * 100,
      currentLayer: completedLayers >= 5 ? 5 : Math.floor(completedLayers) + 1
    }, targetCumulativeLayers);
    elements.start.hidden = remainingLayers <= 0;
    elements.start.textContent = `Начать отрезок ${segmentNumber}`;
    elements.pause.hidden = true;
    elements.resume.hidden = true;
    elements.reset.hidden = !workoutSession;
    elements.next.hidden = true;
    elements.next.disabled = false;
    elements.next.textContent = '+ Следующий отрезок';
    setConfigurationEnabled(true);
    updateParameterSummary(options);
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
      ? `Идёт ${current.currentLayer}-й слой · цель ${current.targetCumulativeLayers} из 5`
      : snapshot.sessionStatus === 'paused'
        ? `Пауза · ${current.currentLayer}-й слой · цель ${current.targetCumulativeLayers} из 5`
        : 'Отрезок завершён';
    elements.time.textContent = Timer.formatRemaining(current.remainingMs);
    elements.cumulative.textContent = Timer.formatElapsed(snapshot.cumulativeElapsedMs);
    elements.progress.style.strokeDashoffset = String(circumference * (1 - current.progress));
    renderLayers(current, current.targetCumulativeLayers);
    elements.start.hidden = true;
    elements.pause.hidden = snapshot.sessionStatus !== 'running';
    elements.resume.hidden = snapshot.sessionStatus !== 'paused';
    elements.reset.hidden = false;
    const allLayersCompleted = snapshot.sessionStatus === 'segment_completed' && snapshot.totalLayerProgress >= 5;
    elements.next.hidden = false;
    elements.next.disabled = allLayersCompleted;
    elements.next.textContent = allLayersCompleted ? allLayersMessage : '+ Следующий отрезок';
    elements.next.classList.toggle('secondary', snapshot.sessionStatus !== 'segment_completed' || allLayersCompleted);
    elements.next.title = allLayersCompleted
      ? allLayersMessage
      : snapshot.sessionStatus === 'segment_completed' ? 'Настроить следующий отрезок' : warningMessage;
    setConfigurationEnabled(false);
    updateParameterSummary(segment);
    renderHistory();
  }

  function startSegment() {
    const options = Object.assign(practiceOptions(activePractice()), {segmentId: createSegmentId()});
    const result = Timer.startWorkoutSegment(workoutSession, options, Date.now());
    if (!result.started) {
      showLockedWarning(result.reason === 'layer_limit_exceeded' ? allLayersMessage : warningMessage);
      return;
    }
    workoutSession = result.session;
    setParametersExpanded(false);
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
      showLockedWarning(result.reason === 'all_layers_completed' ? allLayersMessage : warningMessage);
      return;
    }
    workoutSession = result.session;
    persistSession();
    stopVisualUpdates();
    setParametersExpanded(true);
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
    limitLayerSelectors(5);
    setParametersExpanded(true);
    setConfigurationEnabled(true);
    preview();
  }

  elements.start.addEventListener('click', startSegment);
  elements.pause.addEventListener('click', pause);
  elements.resume.addEventListener('click', resume);
  elements.reset.addEventListener('click', reset);
  elements.next.addEventListener('click', nextSegment);
  elements.parameterToggle.addEventListener('click', () => setParametersExpanded(!parametersExpanded));
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
  const handleViewportChange = () => setParametersExpanded(parametersExpanded);
  if (typeof mobileQuery.addEventListener === 'function') mobileQuery.addEventListener('change', handleViewportChange);
  else if (typeof mobileQuery.addListener === 'function') mobileQuery.addListener(handleViewportChange);

  const descriptor = workoutSession ? workoutSession.currentSegment || workoutSession.draftSegment : null;
  limitLayerSelectors(workoutSession && workoutSession.sessionStatus === 'configuring_next_segment'
    ? remainingLayerCapacity()
    : 5);
  restoreControls(descriptor);
  setParametersExpanded(parametersExpanded);
  if (workoutSession) persistSession();
  window.easyTimerController = {refresh, preview, canConfigure, showLockedWarning};
  refresh(Date.now());
  ensureVisualUpdates();
})();
