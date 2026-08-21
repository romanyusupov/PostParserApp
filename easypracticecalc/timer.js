(function () {
  'use strict';

  const Timer = window.EasyPracticeTimer;
  const storage = window.localStorage;
  const radius = 94;
  const circumference = 2 * Math.PI * radius;
  const warningMessage = 'Чтобы начать следующий отрезок, завершите текущий с теми же параметрами.';
  const allLayersMessage = 'Все 5 слоёв пройдены.';
  const HISTORY_ICON_SOURCES = Object.freeze({
    water: './assets/history-water.webp',
    walking: './assets/history-walking.webp',
    running: './assets/history-running.webp'
  });
  const TIMER_BACKDROP_SOURCES = Object.freeze({
    'water:female': './assets/timer-water-female.webp',
    'water:male': './assets/timer-water-male.webp',
    'move:female': './assets/timer-move-female.webp',
    'move:male': './assets/timer-move-male.webp'
  });
  const elements = {
    parameterToggle: document.getElementById('parameterToggle'), parameterSummary: document.getElementById('parameterSummary'),
    modal: document.getElementById('parameterModal'), modalClose: document.getElementById('parameterModalClose'),
    modalTitle: document.getElementById('parameterModalTitle'), lockedNotice: document.getElementById('parameterLockedNotice'),
    sexFieldset: document.getElementById('sexFieldset'), sexButtons: Array.from(document.querySelectorAll('.sex-option')),
    practice: document.getElementById('timerPractice'), status: document.getElementById('timerStatus'),
    backdrop: document.getElementById('timerBackdrop'),
    time: document.getElementById('timerTime'), cumulative: document.getElementById('timerCumulative'),
    overtime: document.getElementById('timerOvertime'),
    progress: document.getElementById('timerProgress'), progressGlow: document.getElementById('timerProgressGlow'),
    progressHighlight: document.getElementById('timerProgressHighlight'), progressLead: document.getElementById('timerProgressLead'),
    layers: document.getElementById('layerProgress'),
    start: document.getElementById('timerStart'), pause: document.getElementById('timerPause'),
    resume: document.getElementById('timerResume'), reset: document.getElementById('timerReset'),
    next: document.getElementById('timerNext'), nextIcon: document.getElementById('timerNextIcon'),
    nextLabel: document.querySelector('.next-segment-label'),
    history: document.getElementById('segmentHistory'), segmentList: document.getElementById('segmentList'),
    warning: document.getElementById('segmentWarning'), warningText: document.getElementById('segmentWarningText'),
    warningClose: document.getElementById('segmentWarningClose'),
    resetConfirmation: document.getElementById('resetConfirmation'),
    resetConfirmationCancel: document.getElementById('resetConfirmationCancel'),
    resetConfirmationConfirm: document.getElementById('resetConfirmationConfirm')
  };

  let workoutSession = Timer.loadWorkoutSession(storage, Date.now());
  let pendingSex = workoutSession ? workoutSession.sex : null;
  let renderInterval = null;
  let modalReturnFocus = null;
  let warningReturnFocus = null;
  let resetReturnFocus = null;
  [elements.progress, elements.progressGlow, elements.progressHighlight].forEach(element => {
    element.style.strokeDasharray = String(circumference);
  });
  elements.progressLead.style.strokeDasharray = `1 ${circumference - 1}`;

  function setTimerProgress(progress) {
    const safeProgress = Math.max(0, Math.min(1, Number(progress) || 0));
    const offset = circumference * (1 - safeProgress);
    elements.progress.style.strokeDashoffset = String(offset);
    elements.progressGlow.style.strokeDashoffset = String(offset);
    elements.progressHighlight.style.strokeDashoffset = String(offset);
    elements.progressLead.style.strokeDashoffset = String(-circumference * safeProgress);
    elements.progressLead.style.opacity = safeProgress > 0 ? '1' : '0';
  }

  function createSegmentId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
    return `segment-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function activePractice() { return document.querySelector('.panel.active').id; }

  function setTimerBackdrop(descriptor) {
    const sex = workoutSession ? workoutSession.sex : pendingSex;
    const key = descriptor && sex ? `${descriptor.practiceType}:${sex}` : '';
    const source = TIMER_BACKDROP_SOURCES[key];
    if (!source) {
      elements.backdrop.hidden = true;
      elements.backdrop.removeAttribute('src');
      elements.backdrop.dataset.source = '';
      return;
    }
    if (elements.backdrop.dataset.source !== source) {
      elements.backdrop.src = source;
      elements.backdrop.dataset.source = source;
    }
    elements.backdrop.hidden = false;
  }

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
    const safeMaximum = Math.max(1, Math.min(5, Math.ceil(Number(maximum) || 1)));
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
    if (!workoutSession || workoutSession.sessionStatus === 'configuring_next_segment') {
      setTimerBackdrop(workoutSession ? workoutSession.draftSegment : pendingSex ? practiceOptions(activePractice()) : null);
    }
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

  function formatLayerAmount(value) {
    return Number(value || 0).toFixed(2).replace(/0+$/, '').replace(/\.$/, '').replace('.', ',');
  }

  function descriptorSummary(descriptor) {
    if (!descriptor) return 'Параметры не заданы';
    const parameters = descriptor.parameters || {};
    const layers = Number(descriptor.segmentLayers || descriptor.targetLayers || parameters.layer || 1);
    if (descriptor.practiceType === 'move') {
      const speed = Number(parameters.speed || moveSpeed.value);
      const compactPace = Timer.formatPace(speed).replace(' мин/км', '/км');
      return `${layerText(layers)} · ${speed} км/ч · ${compactPace}`;
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
      if (snapshot && completedLayers < 5 && layer === snapshot.currentLayer) item.classList.add('current');
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

  function renderHistory() {
    const segments = workoutSession ? workoutSession.completedSegments.slice() : [];
    if (workoutSession && workoutSession.currentSegment && workoutSession.currentSegment.status === 'completed') {
      const current = workoutSession.currentSegment;
      if (!segments.some(segment => segment.id === current.id)) segments.push(current);
    }
    elements.segmentList.replaceChildren(); elements.history.hidden = segments.length === 0;
    segments.forEach(segment => {
      const item = document.createElement('li'); item.className = 'segment-item';
      const parameters = segment.parameters || {};
      const kind = segment.practiceType === 'water' ? 'water' : Timer.getMovementKind(parameters.speed, workoutSession && workoutSession.sex);
      const icon = document.createElement('span'); icon.className = `segment-type-icon ${kind}`;
      icon.setAttribute('aria-label', kind === 'water' ? 'Вода' : kind === 'running' ? 'Бег' : 'Ходьба');
      const iconImage = document.createElement('img');
      iconImage.src = HISTORY_ICON_SOURCES[kind]; iconImage.alt = ''; iconImage.decoding = 'async';
      iconImage.width = 64; iconImage.height = 64; icon.appendChild(iconImage);
      const copy = document.createElement('span'); copy.className = 'segment-copy';
      const primary = document.createElement('span'); primary.className = 'segment-primary';
      primary.textContent = `${segment.segmentNumber} отрезок · ${layerText(segment.segmentLayers || segment.targetLayers)} · ${formatSegmentDuration(segment.plannedDurationMs)}`;
      const secondary = document.createElement('span'); secondary.className = 'segment-secondary';
      secondary.textContent = segment.practiceType === 'move'
        ? `${Number(parameters.speed)} км/ч · ${Timer.formatPace(parameters.speed)}` : `${parameters.temperature} °C`;
      copy.append(primary, secondary);
      if (segment.overtimeDurationMs > 0) {
        const overtime = document.createElement('span'); overtime.className = 'segment-overtime';
        overtime.textContent = `Сверх ${segment.segmentNumber} отрезка · +${formatLayerAmount(segment.overtimeLayers)} слоя · ${formatSegmentDuration(segment.overtimeDurationMs)}`;
        copy.appendChild(overtime);
      }
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
    elements.overtime.hidden = true; elements.overtime.textContent = '';
    setTimerProgress(0);
    setTimerBackdrop(descriptor || (pendingSex ? practiceOptions(activePractice()) : null));
    renderLayers({status: 'configuring', completedLayers, layerBarPercent: completedLayers / 5 * 100,
      currentLayer: completedLayers >= 5 ? 5 : Math.floor(completedLayers) + 1}, target);
    elements.pause.hidden = true; elements.resume.hidden = true; elements.reset.hidden = !workoutSession; elements.next.hidden = true;
    updateParameterSummary(descriptor); renderHistory();
  }

  function stopVisualUpdates() { if (renderInterval !== null) window.clearInterval(renderInterval); renderInterval = null; }
  function ensureVisualUpdates() {
    stopVisualUpdates();
    if (workoutSession && ['running', 'overtime_running'].includes(workoutSession.sessionStatus)) {
      renderInterval = window.setInterval(() => refresh(Date.now()), 250);
    }
  }

  function refresh(now) {
    if (!workoutSession || workoutSession.sessionStatus === 'configuring_next_segment') { renderIdle(); return; }
    const previousStatus = workoutSession.sessionStatus;
    workoutSession = Timer.syncWorkoutSession(workoutSession, now);
    if (workoutSession.sessionStatus !== previousStatus) {
      persistSession();
      if (!['running', 'overtime_running'].includes(workoutSession.sessionStatus)) stopVisualUpdates();
    }
    const snapshot = Timer.getWorkoutSnapshot(workoutSession, now);
    const segment = workoutSession.currentSegment; const current = snapshot.currentSegment;
    elements.practice.textContent = `Отрезок ${segment.segmentNumber} · ${segment.practiceType === 'water' ? 'Вода' : 'Ходьба/бег'}`;
    elements.status.textContent = snapshot.sessionStatus === 'running'
      ? `Идёт ${current.currentLayer}-й слой · цель ${current.targetCumulativeLayers} из 5`
      : snapshot.sessionStatus === 'paused'
        ? `Пауза · ${current.currentLayer}-й слой · цель ${current.targetCumulativeLayers} из 5`
        : snapshot.sessionStatus === 'overtime_running' ? 'Идёт дополнительное очищение' : 'Отрезок завершён';
    elements.time.textContent = Timer.formatRemaining(current.remainingMs);
    elements.cumulative.textContent = Timer.formatElapsed(snapshot.cumulativeElapsedMs);
    const overtimeDurationMs = current.overtimeDurationMs || 0;
    elements.overtime.hidden = overtimeDurationMs <= 0;
    elements.overtime.textContent = overtimeDurationMs > 0
      ? `Дополнительное очищение: +${formatLayerAmount(current.overtimeLayers)} слоя · ${formatSegmentDuration(overtimeDurationMs)}`
      : '';
    setTimerProgress(current.progress);
    setTimerBackdrop(segment);
    renderLayers(current, current.targetCumulativeLayers);
    elements.pause.hidden = snapshot.sessionStatus !== 'running'; elements.resume.hidden = snapshot.sessionStatus !== 'paused'; elements.reset.hidden = false;
    const overtimeRunning = snapshot.sessionStatus === 'overtime_running';
    const allLayersCompleted = snapshot.sessionStatus === 'segment_completed' && snapshot.totalLayerProgress >= 5;
    elements.next.hidden = false; elements.next.disabled = allLayersCompleted;
    elements.nextLabel.textContent = allLayersCompleted ? allLayersMessage : 'Следующий отрезок';
    elements.next.classList.toggle('secondary', !overtimeRunning || allLayersCompleted);
    elements.nextIcon.src = overtimeRunning ? './assets/button-next-active.webp' : './assets/button-next.webp';
    elements.next.title = allLayersCompleted ? allLayersMessage : overtimeRunning ? 'Зафиксировать отрезок и настроить следующий' : warningMessage;
    updateParameterSummary(segment); renderHistory();
  }

  function updateModalStartState() {
    if (elements.modal.hidden) return;
    elements.start.disabled = !canConfigure() || (!workoutSession && !pendingSex) || remainingLayerCapacity() <= 0;
  }

  function handleReturn() {
    refresh(Date.now());
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
    const now = Date.now();
    const result = Timer.requestNextSegment(workoutSession, now);
    if (!result.allowed) {
      if (result.reason === 'all_layers_completed') {
        workoutSession = result.session; persistSession(); stopVisualUpdates(); refresh(now);
      }
      showLockedWarning(result.reason === 'all_layers_completed' ? allLayersMessage : warningMessage); return false;
    }
    workoutSession = result.session; persistSession(); stopVisualUpdates(); limitLayerSelectors(remainingLayerCapacity());
    restoreControls(workoutSession.draftSegment); refresh(Date.now()); return true;
  }

  function openParameters() {
    if (!workoutSession) { limitLayerSelectors(5); updateWater(); updateMove(); showModal('editable'); return; }
    if (['running', 'paused', 'overtime_running'].includes(workoutSession.sessionStatus)) {
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
    setTimerBackdrop(workoutSession ? workoutSession.draftSegment : pendingSex ? practiceOptions(activePractice()) : null);
    updateModalStartState();
  }

  function reset() {
    stopVisualUpdates(); workoutSession = null; pendingSex = null; Timer.clearWorkoutSession(storage);
    limitLayerSelectors(5); setConfigurationEnabled(true); setSex(null); refresh(Date.now()); openParameters();
  }

  function showResetConfirmation() {
    resetReturnFocus = document.activeElement;
    elements.resetConfirmation.hidden = false;
    document.body.classList.add('modal-open');
    elements.resetConfirmationCancel.focus();
  }

  function hideResetConfirmation(restoreFocus) {
    elements.resetConfirmation.hidden = true;
    document.body.classList.remove('modal-open');
    if (restoreFocus !== false && resetReturnFocus && typeof resetReturnFocus.focus === 'function') resetReturnFocus.focus();
    resetReturnFocus = null;
  }

  function confirmReset() {
    hideResetConfirmation(false);
    reset();
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
    if (event.key !== 'Tab') return;
    const activeDialog = !elements.resetConfirmation.hidden ? elements.resetConfirmation : !elements.modal.hidden ? elements.modal : null;
    if (!activeDialog) return;
    const focusable = Array.from(activeDialog.querySelectorAll('button:not([disabled]),select:not([disabled])'));
    if (!focusable.length) return;
    const first = focusable[0]; const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  elements.start.addEventListener('click', startSegment); elements.pause.addEventListener('click', pause);
  elements.resume.addEventListener('click', resume); elements.reset.addEventListener('click', showResetConfirmation);
  elements.next.addEventListener('click', nextSegment); elements.parameterToggle.addEventListener('click', openParameters);
  elements.modalClose.addEventListener('click', closeModal);
  elements.modal.addEventListener('click', event => { if (event.target === elements.modal) closeModal(); });
  elements.sexButtons.forEach(button => button.addEventListener('click', () => setSex(button.dataset.sex)));
  elements.warningClose.addEventListener('click', hideWarning);
  elements.warning.addEventListener('click', event => { if (event.target === elements.warning) hideWarning(); });
  elements.resetConfirmationCancel.addEventListener('click', () => hideResetConfirmation(true));
  elements.resetConfirmationConfirm.addEventListener('click', confirmReset);
  elements.resetConfirmation.addEventListener('click', event => {
    if (event.target === elements.resetConfirmation) hideResetConfirmation(true);
  });
  document.addEventListener('keydown', event => {
    trapModalFocus(event);
    if (event.key !== 'Escape') return;
    if (!elements.resetConfirmation.hidden) hideResetConfirmation(true);
    else if (!elements.warning.hidden) hideWarning(); else if (!elements.modal.hidden) closeModal();
  });
  document.querySelectorAll('select').forEach(element => element.addEventListener('change', updateDraftFromControls));
  document.querySelectorAll('.tab').forEach(element => element.addEventListener('click', () => window.setTimeout(updateDraftFromControls, 0)));
  document.addEventListener('visibilitychange', () => { if (!document.hidden) handleReturn(); });
  window.addEventListener('pageshow', handleReturn); window.addEventListener('focus', handleReturn);

  setSex(pendingSex);
  const descriptor = workoutSession ? workoutSession.currentSegment || workoutSession.draftSegment : null;
  limitLayerSelectors(workoutSession && workoutSession.sessionStatus === 'configuring_next_segment' ? remainingLayerCapacity() : 5);
  restoreControls(descriptor);
  if (workoutSession) persistSession();
  window.easyTimerController = {refresh, canConfigure, showLockedWarning, openParameters};
  refresh(Date.now()); ensureVisualUpdates();
  if (!workoutSession || workoutSession.sessionStatus === 'configuring_next_segment') window.setTimeout(openParameters, 0);
})();
