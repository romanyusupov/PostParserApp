(function () {
  'use strict';

  const Timer = window.EasyPracticeTimer;
  const storage = window.localStorage;
  const radius = 94;
  const circumference = 2 * Math.PI * radius;
  const warningMessage = 'Чтобы начать следующий отрезок, завершите текущий с теми же параметрами.';
  const allLayersMessage = 'Все 5 слоёв пройдены.';
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const elements = {
    parameterToggle: document.getElementById('parameterToggle'), parameterSummary: document.getElementById('parameterSummary'),
    modal: document.getElementById('parameterModal'), modalClose: document.getElementById('parameterModalClose'),
    modalTitle: document.getElementById('parameterModalTitle'), lockedNotice: document.getElementById('parameterLockedNotice'),
    sexFieldset: document.getElementById('sexFieldset'), sexButtons: Array.from(document.querySelectorAll('.sex-option')),
    practice: document.getElementById('timerPractice'), status: document.getElementById('timerStatus'),
    time: document.getElementById('timerTime'), cumulative: document.getElementById('timerCumulative'),
    progress: document.getElementById('timerProgress'), layers: document.getElementById('layerProgress'),
    start: document.getElementById('timerStart'), pause: document.getElementById('timerPause'),
    resume: document.getElementById('timerResume'), reset: document.getElementById('timerReset'),
    next: document.getElementById('timerNext'), nextLabel: document.querySelector('.next-segment-label'),
    history: document.getElementById('segmentHistory'), segmentList: document.getElementById('segmentList'),
    warning: document.getElementById('segmentWarning'), warningText: document.getElementById('segmentWarningText'),
    warningClose: document.getElementById('segmentWarningClose')
  };

  let workoutSession = Timer.loadWorkoutSession(storage, Date.now());
  let pendingSex = workoutSession ? workoutSession.sex : null;
  let renderInterval = null;
  let modalReturnFocus = null;
  let warningReturnFocus = null;
  elements.progress.style.strokeDasharray = String(circumference);

  function createSegmentId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
    return `segment-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function activePractice() { return document.querySelector('.panel.active').id; }

  function selectPractice(practiceType) {
    const type = practiceType === 'move' ? 'move' : 'water';
    document.querySelectorAll('.panel').forEach(panel => panel.classList.toggle('active', panel.id === type));
    document.querySelectorAll('.tab').forEach(tab => {
      const active = tab.dataset.practice === type;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', String(active));
    });
  }

  function practiceOptions(practiceType) {
    if (practiceType === 'move') {
      const minutes = moveData[moveSpeed.value][moveLayer.value];
      return {practiceType, durationMs: Math.round(minutes * 60) * 1000,
        segmentLayers: Number(moveLayer.value), targetLayers: Number(moveLayer.value),
        parameters: {layer: moveLayer.value, speed: moveSpeed.value}};
    }
    const minutes = waterData[waterTemp.value][waterLayer.value];
    return {practiceType: 'water', durationMs: Math.round(minutes * 60) * 1000,
      segmentLayers: Number(waterLayer.value), targetLayers: Number(waterLayer.value),
      parameters: {layer: waterLayer.value, temperature: waterTemp.value}};
  }

  function draftOptions() {
    const options = practiceOptions(activePractice());
    return {practiceType: options.practiceType, segmentLayers: options.segmentLayers,
      targetLayers: options.targetLayers, parameters: options.parameters};
  }

  function canConfigure() { return !workoutSession || workoutSession.sessionStatus === 'configuring_next_segment'; }
  function sessionSnapshot(now) { return workoutSession ? Timer.getWorkoutSnapshot(workoutSession, now || Date.now()) : null; }

  function limitLayerSelectors(maximum) {
    const safeMaximum = Math.max(1, Math.min(5, Number(maximum) || 1));
    [waterLayer, moveLayer].forEach(select => {
      Array.from(select.options).forEach(option => {
        const unavailable = Number(option.value) > safeMaximum;
        option.hidden = unavailable; option.disabled = unavailable;
      });
      if (Number(select.value) > safeMaximum) select.value = String(safeMaximum);
    });
  }

  function remainingLayerCapacity() {
    const snapshot = sessionSnapshot();
    return snapshot ? snapshot.remainingLayers : 5;
  }

  function setConfigurationEnabled(enabled) {
    [waterLayer, waterTemp, moveLayer, moveSpeed].forEach(select => { select.disabled = !enabled; });
    document.querySelectorAll('.tab').forEach(tab => {
      tab.disabled = !enabled; tab.classList.toggle('locked', !enabled);
      tab.setAttribute('aria-disabled', String(!enabled));
    });
  }

  function setSex(value) {
    pendingSex = value === 'female' || value === 'male' ? value : null;
    elements.sexButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.sex === pendingSex)));
    updateModalStartState();
  }

  function restoreControls(descriptor) {
    if (!descriptor) return;
    const parameters = descriptor.parameters || {};
    const layerValue = String(parameters.layer || descriptor.segmentLayers || descriptor.targetLayers || 1);
    selectPractice(descriptor.practiceType);
    if (descriptor.practiceType === 'move') {
      if (moveLayer.querySelector(`option[value="${layerValue}"]`)) moveLayer.value = layerValue;
      if (parameters.speed && moveSpeed.querySelector(`option[value="${parameters.speed}"]`)) moveSpeed.value = parameters.speed;
      updateMove();
    } else {
      if (waterLayer.querySelector(`option[value="${layerValue}"]`)) waterLayer.value = layerValue;
      if (parameters.temperature && waterTemp.querySelector(`option[value="${parameters.temperature}"]`)) waterTemp.value = parameters.temperature;
      updateWater();
    }
  }

  function persistSession() { if (workoutSession) Timer.saveWorkoutSession(storage, workoutSession); }

  function layerText(value) {
    if (value === 1) return '1 слой';
    if (value < 5) return `${value} слоя`;
    return '5 слоёв';
  }

  function formatSegmentDuration(milliseconds) {
    const totalSeconds = Math.round(milliseconds / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (hours > 0) return [hours, minutes, seconds].map(value => String(value).padStart(2, '0')).join(':');
    return `${minutes}:${String(seconds).padStart(2, '0')}`;
  }

  function descriptorSummary(descriptor) {
    if (!descriptor) return 'Параметры не заданы';
    const parameters = descriptor.parameters || {};
    const layers = Number(descriptor.segmentLayers || descriptor.targetLayers || parameters.layer || 1);
    if (descriptor.practiceType === 'move') {
      const speed = Number(parameters.speed || moveSpeed.value);
      return `${layerText(layers)} · ${speed} км/ч · ${Timer.formatPace(speed)}`;
    }
    return `${layerText(layers)} · ${parameters.temperature || waterTemp.value} °C`;
  }

  function updateParameterSummary(descriptor) { elements.parameterSummary.textContent = descriptorSummary(descriptor); }

  function renderLayers(snapshot, targetCumulativeLayers) {
    elements.layers.replaceChildren();
    const completedLayers = snapshot ? snapshot.completedLayers : 0;
    const layerBarPercent = snapshot ? snapshot.layerBarPercent : 0;
    const targetLayers = Math.max(0, Math.min(5, Number(targetCumulativeLayers) || 0));
    elements.layers.setAttribute('aria-valuenow', completedLayers.toFixed(2));
    elements.layers.setAttribute('aria-valuetext', `Пройдено ${completedLayers.toFixed(2)} из 5 слоёв. Цель: ${targetLayers}.`);
    const scale = document.createElement('div'); scale.className = 'layer-scale';
    const track = document.createElement('div'); track.className = 'layer-track';
    const fill = document.createElement('div'); fill.className = 'layer-fill'; fill.style.width = `${layerBarPercent}%`; track.appendChild(fill);
    const markers = document.createElement('div'); markers.className = 'layer-markers';
    for (let layer = 1; layer <= 5; layer += 1) {
      const item = document.createElement('div'); item.className = 'layer-step';
      if (completedLayers >= layer) item.classList.add('complete');
      if (snapshot && snapshot.status !== 'completed' && layer === snapshot.currentLayer) item.classList.add('current');
      if (layer === targetLayers) item.classList.add('target');
      const marker = document.createElement('span'); marker.className = 'layer-marker'; marker.textContent = String(layer);
      const label = document.createElement('span'); label.className = 'layer-label';
      const fullLabel = document.createElement('span'); fullLabel.className = 'layer-label-full';
      fullLabel.textContent = layer === 1 ? '1 слой' : layer < 5 ? `${layer} слоя` : '5 слоёв';
      const shortLabel = document.createElement('span'); shortLabel.className = 'layer-label-short'; shortLabel.textContent = String(layer);
      label.append(fullLabel, shortLabel); item.append(marker, label); markers.appendChild(item);
    }
    scale.append(track, markers); elements.layers.appendChild(scale);
  }

  function svgIcon(kind) {
    const svg = document.createElementNS(SVG_NS, 'svg'); svg.setAttribute('viewBox', '0 0 32 32');
    const paths = kind === 'water'
      ? ['M16 3C11 10 7 14 7 20a9 9 0 0 0 18 0c0-6-4-10-9-17Z', 'M11 21c1 3 3 4 6 4']
      : kind === 'running'
        ? ['M19 6a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z', 'm14 11 5 2 4-2', 'm14 11-3 7-5 5', 'm12 17 6 3 4 7', 'm14 11-5 2']
        : ['M18 6a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z', 'm14 11 4 5 5 2', 'm14 11-2 8-4 7', 'm12 19 6 2 3 6', 'm14 12-5 4'];
    paths.forEach(data => { const path = document.createElementNS(SVG_NS, 'path'); path.setAttribute('d', data); svg.appendChild(path); });
    return svg;
  }

  function renderHistory() {
    const segments = workoutSession ? workoutSession.completedSegments.slice() : [];
    if (workoutSession && workoutSession.currentSegment && workoutSession.currentSegment.status === 'completed') {
      const snapshot = sessionSnapshot(); const current = workoutSession.currentSegment;
      if (snapshot.totalLayerProgress >= 5 && !segments.some(segment => segment.id === current.id)) segments.push(current);
    }
    elements.segmentList.replaceChildren(); elements.history.hidden = segments.length === 0;
    segments.forEach(segment => {
      const item = document.createElement('li'); item.className = 'segment-item';
      const parameters = segment.parameters || {};
      const kind = segment.practiceType === 'water' ? 'water' : Timer.getMovementKind(parameters.speed, workoutSession && workoutSession.sex);
      const icon = document.createElement('span'); icon.className = `segment-type-icon ${kind}`;
      icon.setAttribute('aria-label', kind === 'water' ? 'Вода' : kind === 'running' ? 'Бег' : 'Ходьба'); icon.appendChild(svgIcon(kind));
      const copy = document.createElement('span'); copy.className = 'segment-copy';
      const primary = document.createElement('span'); primary.className = 'segment-primary';
      primary.textContent = `${segment.segmentNumber} отрезок · ${layerText(segment.segmentLayers || segment.targetLayers)} · ${formatSegmentDuration(segment.plannedDurationMs)}`;
      const secondary = document.createElement('span'); secondary.className = 'segment-secondary';
      secondary.textContent = segment.practiceType === 'move'
        ? `${Number(parameters.speed)} км/ч · ${Timer.formatPace(parameters.speed)}` : `${parameters.temperature} °C`;
      copy.append(primary, secondary);
      const check = document.createElement('span'); check.className = 'segment-check'; check.setAttribute('aria-label', 'Завершён'); check.textContent = '✓';
      item.append(icon, copy, check); elements.segmentList.appendChild(item);
    });
  }

  function renderIdle() {
    const snapshot = sessionSnapshot();
    const configuring = workoutSession && workoutSession.sessionStatus === 'configuring_next_segment';
    const descriptor = configuring ? workoutSession.draftSegment : null;
    const completedLayers = snapshot ? snapshot.completedLayers : 0;
    const target = descriptor ? Math.min(5, completedLayers + descriptor.segmentLayers) : 0;
    elements.practice.textContent = configuring ? `Отрезок ${descriptor.segmentNumber} · Настройка` : 'Новая тренировка';
    elements.status.textContent = configuring ? 'Настройте следующий участок' : 'Настройте первый участок';
    elements.time.textContent = '00:00:00';
    elements.cumulative.textContent = Timer.formatElapsed(snapshot ? snapshot.cumulativeElapsedMs : 0);
    elements.progress.style.strokeDashoffset = String(circumference);
    renderLayers({status: 'configuring', completedLayers, layerBarPercent: completedLayers / 5 * 100,
      currentLayer: completedLayers >= 5 ? 5 : Math.floor(completedLayers) + 1}, target);
    elements.pause.hidden = true; elements.resume.hidden = true; elements.reset.hidden = !workoutSession; elements.next.hidden = true;
    updateParameterSummary(descriptor); renderHistory();
  }

  function stopVisualUpdates() { if (renderInterval !== null) window.clearInterval(renderInterval); renderInterval = null; }
  function ensureVisualUpdates() {
    stopVisualUpdates();
    if (workoutSession && workoutSession.sessionStatus === 'running') renderInterval = window.setInterval(() => refresh(Date.now()), 250);
  }

  function refresh(now) {
    if (!workoutSession || workoutSession.sessionStatus === 'configuring_next_segment') { renderIdle(); return; }
    const previousStatus = workoutSession.sessionStatus;
    workoutSession = Timer.syncWorkoutSession(workoutSession, now);
    if (workoutSession.sessionStatus !== previousStatus) { persistSession(); stopVisualUpdates(); }
    const snapshot = Timer.getWorkoutSnapshot(workoutSession, now);
    const segment = workoutSession.currentSegment; const current = snapshot.currentSegment;
    elements.practice.textContent = `Отрезок ${segment.segmentNumber} · ${segment.practiceType === 'water' ? 'Вода' : 'Ходьба/бег'}`;
    elements.status.textContent = snapshot.sessionStatus === 'running'
      ? `Идёт ${current.currentLayer}-й слой · цель ${current.targetCumulativeLayers} из 5`
      : snapshot.sessionStatus === 'paused' ? `Пауза · ${current.currentLayer}-й слой · цель ${current.targetCumulativeLayers} из 5` : 'Отрезок завершён';
    elements.time.textContent = Timer.formatRemaining(current.remainingMs);
    elements.cumulative.textContent = Timer.formatElapsed(snapshot.cumulativeElapsedMs);
    elements.progress.style.strokeDashoffset = String(circumference * (1 - current.progress));
    renderLayers(current, current.targetCumulativeLayers);
    elements.pause.hidden = snapshot.sessionStatus !== 'running'; elements.resume.hidden = snapshot.sessionStatus !== 'paused'; elements.reset.hidden = false;
    const allLayersCompleted = snapshot.sessionStatus === 'segment_completed' && snapshot.totalLayerProgress >= 5;
    elements.next.hidden = false; elements.next.disabled = allLayersCompleted;
    elements.nextLabel.textContent = allLayersCompleted ? allLayersMessage : 'Следующий отрезок';
    elements.next.classList.toggle('secondary', snapshot.sessionStatus !== 'segment_completed' || allLayersCompleted);
    elements.next.title = allLayersCompleted ? allLayersMessage : snapshot.sessionStatus === 'segment_completed' ? 'Настроить следующий отрезок' : warningMessage;
    updateParameterSummary(segment); renderHistory();
  }

  function updateModalStartState() {
    if (elements.modal.hidden) return;
    elements.start.disabled = !canConfigure() || (!workoutSession && !pendingSex) || remainingLayerCapacity() <= 0;
  }

  function configureModal(mode) {
    const locked = mode === 'locked';
    const segmentNumber = workoutSession ? (workoutSession.currentSegment ? workoutSession.currentSegment.segmentNumber : workoutSession.draftSegment.segmentNumber) : 1;
    elements.modalTitle.textContent = locked ? `Параметры участка ${segmentNumber}`
      : segmentNumber === 1 ? 'Введите параметры первого участка тренировки' : `Параметры участка ${segmentNumber}`;
    elements.lockedNotice.hidden = !locked; elements.start.hidden = locked; elements.start.textContent = `Запустить участок ${segmentNumber}`;
    setConfigurationEnabled(!locked);
    elements.sexButtons.forEach(button => { button.disabled = Boolean(workoutSession) || locked; });
    elements.sexFieldset.disabled = Boolean(workoutSession) || locked;
    setSex(workoutSession ? workoutSession.sex : pendingSex); updateModalStartState();
  }

  function showModal(mode) {
    modalReturnFocus = document.activeElement; configureModal(mode); elements.modal.hidden = false; document.body.classList.add('modal-open');
    updateModalStartState();
    window.setTimeout(() => { const target = mode === 'locked' ? elements.modalClose : elements.modal.querySelector('button:not([disabled]),select:not([disabled])'); if (target) target.focus(); }, 0);
  }

  function closeModal() {
    elements.modal.hidden = true; document.body.classList.remove('modal-open');
    const target = modalReturnFocus && document.contains(modalReturnFocus) ? modalReturnFocus : elements.parameterToggle;
    modalReturnFocus = null; target.focus();
  }

  function prepareNextSegment() {
    const result = Timer.requestNextSegment(workoutSession, Date.now());
    if (!result.allowed) { showLockedWarning(result.reason === 'all_layers_completed' ? allLayersMessage : warningMessage); return false; }
    workoutSession = result.session; persistSession(); stopVisualUpdates(); limitLayerSelectors(remainingLayerCapacity());
    restoreControls(workoutSession.draftSegment); refresh(Date.now()); return true;
  }

  function openParameters() {
    if (!workoutSession) { limitLayerSelectors(5); updateWater(); updateMove(); showModal('editable'); return; }
    if (workoutSession.sessionStatus === 'running' || workoutSession.sessionStatus === 'paused') {
      restoreControls(workoutSession.currentSegment); showModal('locked'); return;
    }
    if (workoutSession.sessionStatus === 'segment_completed' && !prepareNextSegment()) return;
    limitLayerSelectors(remainingLayerCapacity()); restoreControls(workoutSession.draftSegment); showModal('editable');
  }

  function startSegment() {
    if (!workoutSession && !pendingSex) { updateModalStartState(); return; }
    const options = Object.assign(practiceOptions(activePractice()), {segmentId: createSegmentId(), sex: workoutSession ? workoutSession.sex : pendingSex});
    const result = Timer.startWorkoutSegment(workoutSession, options, Date.now());
    if (!result.started) { showLockedWarning(result.reason === 'layer_limit_exceeded' ? allLayersMessage : warningMessage); return; }
    workoutSession = result.session; persistSession(); closeModal(); refresh(Date.now()); ensureVisualUpdates();
  }

  function pause() { workoutSession = Timer.pauseWorkout(workoutSession, Date.now()); persistSession(); stopVisualUpdates(); refresh(Date.now()); }
  function resume() { workoutSession = Timer.resumeWorkout(workoutSession, Date.now()); persistSession(); refresh(Date.now()); ensureVisualUpdates(); }
  function nextSegment() { if (prepareNextSegment()) showModal('editable'); }

  function updateDraftFromControls() {
    if (workoutSession && workoutSession.sessionStatus === 'configuring_next_segment') {
      workoutSession = Timer.updateDraftSegment(workoutSession, draftOptions(), Date.now()); persistSession(); refresh(Date.now());
    }
    updateModalStartState();
  }

  function reset() {
    stopVisualUpdates(); workoutSession = null; pendingSex = null; Timer.clearWorkoutSession(storage);
    limitLayerSelectors(5); setConfigurationEnabled(true); setSex(null); refresh(Date.now()); openParameters();
  }

  function showLockedWarning(message) {
    warningReturnFocus = document.activeElement; elements.warningText.textContent = message || warningMessage;
    elements.warning.hidden = false; elements.warningClose.focus();
  }
  function hideWarning() {
    elements.warning.hidden = true;
    if (warningReturnFocus && typeof warningReturnFocus.focus === 'function') warningReturnFocus.focus();
    warningReturnFocus = null;
  }

  function trapModalFocus(event) {
    if (elements.modal.hidden || event.key !== 'Tab') return;
    const focusable = Array.from(elements.modal.querySelectorAll('button:not([disabled]),select:not([disabled])'));
    if (!focusable.length) return;
    const first = focusable[0]; const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  elements.start.addEventListener('click', startSegment); elements.pause.addEventListener('click', pause);
  elements.resume.addEventListener('click', resume); elements.reset.addEventListener('click', reset);
  elements.next.addEventListener('click', nextSegment); elements.parameterToggle.addEventListener('click', openParameters);
  elements.modalClose.addEventListener('click', closeModal);
  elements.modal.addEventListener('click', event => { if (event.target === elements.modal) closeModal(); });
  elements.sexButtons.forEach(button => button.addEventListener('click', () => setSex(button.dataset.sex)));
  elements.warningClose.addEventListener('click', hideWarning);
  elements.warning.addEventListener('click', event => { if (event.target === elements.warning) hideWarning(); });
  document.addEventListener('keydown', event => {
    trapModalFocus(event);
    if (event.key !== 'Escape') return;
    if (!elements.warning.hidden) hideWarning(); else if (!elements.modal.hidden) closeModal();
  });
  document.querySelectorAll('select').forEach(element => element.addEventListener('change', updateDraftFromControls));
  document.querySelectorAll('.tab').forEach(element => element.addEventListener('click', () => window.setTimeout(updateDraftFromControls, 0)));
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(Date.now()); });
  window.addEventListener('pageshow', () => refresh(Date.now())); window.addEventListener('focus', () => refresh(Date.now()));

  setSex(pendingSex);
  const descriptor = workoutSession ? workoutSession.currentSegment || workoutSession.draftSegment : null;
  limitLayerSelectors(workoutSession && workoutSession.sessionStatus === 'configuring_next_segment' ? remainingLayerCapacity() : 5);
  restoreControls(descriptor);
  if (workoutSession) persistSession();
  window.easyTimerController = {refresh, canConfigure, showLockedWarning, openParameters};
  refresh(Date.now()); ensureVisualUpdates();
  if (!workoutSession || workoutSession.sessionStatus === 'configuring_next_segment') window.setTimeout(openParameters, 0);
})();
