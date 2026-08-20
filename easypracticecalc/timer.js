(function () {
  'use strict';

  const Timer = window.EasyPracticeTimer;
  const storage = window.localStorage;
  const radius = 94;
  const circumference = 2 * Math.PI * radius;
  const elements = {
    card: document.getElementById('timerCard'),
    practice: document.getElementById('timerPractice'),
    status: document.getElementById('timerStatus'),
    time: document.getElementById('timerTime'),
    progress: document.getElementById('timerProgress'),
    layers: document.getElementById('layerProgress'),
    start: document.getElementById('timerStart'),
    pause: document.getElementById('timerPause'),
    resume: document.getElementById('timerResume'),
    reset: document.getElementById('timerReset')
  };

  let timerState = Timer.loadTimerState(storage);
  let renderInterval = null;

  elements.progress.style.strokeDasharray = String(circumference);

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

  function restoreControls(state) {
    if (!state) return;
    const parameters = state.parameters || {};
    if (state.practiceType === 'move') {
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

  function renderLayers(snapshot, selectedLayers) {
    elements.layers.replaceChildren();
    for (let layer = 1; layer <= selectedLayers; layer += 1) {
      const item = document.createElement('div');
      item.className = 'layer-step';
      if (snapshot && layer < snapshot.currentLayer) item.classList.add('complete');
      if (snapshot && layer === snapshot.currentLayer) item.classList.add(snapshot.status === 'finished' ? 'complete' : 'current');
      const marker = document.createElement('span');
      marker.className = 'layer-marker';
      marker.textContent = String(layer);
      const label = document.createElement('span');
      label.textContent = `${layer} слой`;
      item.append(marker, label);
      elements.layers.appendChild(item);
    }
  }

  function stopVisualUpdates() {
    if (renderInterval !== null) window.clearInterval(renderInterval);
    renderInterval = null;
  }

  function ensureVisualUpdates() {
    stopVisualUpdates();
    if (timerState && timerState.status === 'running') {
      renderInterval = window.setInterval(() => refresh(Date.now()), 250);
    }
  }

  function preview() {
    if (timerState) return;
    const options = practiceOptions(activePractice());
    elements.practice.textContent = options.practiceType === 'water' ? 'Вода' : 'Ходьба/бег';
    elements.status.textContent = 'Готово к запуску';
    elements.time.textContent = Timer.formatRemaining(options.durationMs);
    elements.progress.style.strokeDashoffset = String(circumference);
    renderLayers(null, options.targetLayers);
    elements.start.hidden = false;
    elements.pause.hidden = true;
    elements.resume.hidden = true;
    elements.reset.hidden = true;
  }

  function refresh(now) {
    if (!timerState) {
      preview();
      return;
    }

    let snapshot = Timer.getTimerSnapshot(timerState, now);
    if (snapshot.status === 'finished' && timerState.status !== 'finished') {
      timerState = Timer.finishTimer(timerState, now);
      Timer.saveTimerState(storage, timerState);
      stopVisualUpdates();
      snapshot = Timer.getTimerSnapshot(timerState, now);
    }

    elements.practice.textContent = timerState.practiceType === 'water' ? 'Вода' : 'Ходьба/бег';
    elements.status.textContent = snapshot.status === 'running'
      ? `Идёт ${snapshot.currentLayer} слой из ${snapshot.targetLayers}`
      : snapshot.status === 'paused'
        ? `Пауза · ${snapshot.currentLayer} слой из ${snapshot.targetLayers}`
        : 'Практика завершена';
    elements.time.textContent = Timer.formatRemaining(snapshot.remainingMs);
    elements.progress.style.strokeDashoffset = String(circumference * (1 - snapshot.progress));
    renderLayers(snapshot, snapshot.targetLayers);
    elements.start.hidden = snapshot.status !== 'finished';
    elements.start.textContent = snapshot.status === 'finished' ? 'Начать снова' : 'Начать';
    elements.pause.hidden = snapshot.status !== 'running';
    elements.resume.hidden = snapshot.status !== 'paused';
    elements.reset.hidden = false;
  }

  function startTimer() {
    if (timerState && timerState.status !== 'finished') {
      const confirmed = window.confirm('Текущая практика будет заменена новой. Продолжить?');
      if (!confirmed) return;
    }
    timerState = Timer.createTimerState(practiceOptions(activePractice()), Date.now());
    Timer.saveTimerState(storage, timerState);
    refresh(Date.now());
    ensureVisualUpdates();
  }

  function pause() {
    timerState = Timer.pauseTimer(timerState, Date.now());
    Timer.saveTimerState(storage, timerState);
    stopVisualUpdates();
    refresh(Date.now());
  }

  function resume() {
    timerState = Timer.resumeTimer(timerState, Date.now());
    Timer.saveTimerState(storage, timerState);
    refresh(Date.now());
    ensureVisualUpdates();
  }

  function reset() {
    stopVisualUpdates();
    timerState = null;
    Timer.clearTimerState(storage);
    preview();
  }

  elements.start.addEventListener('click', startTimer);
  elements.pause.addEventListener('click', pause);
  elements.resume.addEventListener('click', resume);
  elements.reset.addEventListener('click', reset);
  document.querySelectorAll('select, .tab').forEach(element => element.addEventListener('change', preview));
  document.querySelectorAll('.tab').forEach(element => element.addEventListener('click', () => window.setTimeout(preview, 0)));
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refresh(Date.now());
  });
  window.addEventListener('pageshow', () => refresh(Date.now()));
  window.addEventListener('focus', () => refresh(Date.now()));

  restoreControls(timerState);
  refresh(Date.now());
  ensureVisualUpdates();

  window.easyTimerController = {refresh, preview};
})();
