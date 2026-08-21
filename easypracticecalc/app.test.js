'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const directory = __dirname;
const html = fs.readFileSync(path.join(directory, 'index.html'), 'utf8');
const timerUi = fs.readFileSync(path.join(directory, 'timer.js'), 'utf8');
const timerLogic = fs.readFileSync(path.join(directory, 'timer_logic.js'), 'utf8');
const serviceWorker = fs.readFileSync(path.join(directory, 'sw.js'), 'utf8');

function dataConstant(name) {
  const match = html.match(new RegExp(`const ${name}=(\\{.*?\\});`));
  assert.ok(match, `${name} is present`);
  return JSON.parse(match[1]);
}

test('Production water and movement formula fixtures are unchanged', () => {
  const waterData = dataConstant('waterData');
  const moveData = dataConstant('moveData');
  assert.equal(Math.round(waterData['28']['1'] * 60), 876);
  assert.equal(Math.round(moveData['4.0']['1'] * 60), 3912);
  assert.equal((4 * moveData['4.0']['1'] / 60).toFixed(3), '4.347');
  assert.equal(Math.round(waterData['20']['5'] * 60), 1842);
  assert.equal(Math.round(moveData['10.0']['5'] * 60), 5568);
});

test('Timer, sequential segment controls and progress are rendered', () => {
  for (const id of [
    'timerStart', 'timerPause', 'timerResume', 'timerReset', 'timerNext', 'timerNextIcon',
    'timerCumulative', 'timerOvertime', 'timerProgress', 'layerProgress', 'segmentHistory',
    'segmentWarning', 'segmentWarningClose', 'parameterModal',
    'parameterModalClose', 'parameterModalTitle', 'parameterLockedNotice',
    'parameterToggle', 'parameterPanel', 'parameterSummary', 'sexFieldset',
    'timerBackdrop', 'resetConfirmation', 'resetConfirmationCancel',
    'resetConfirmationConfirm'
  ]) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /\.timer-circle/);
  assert.match(html, /\.layer-progress/);
  assert.match(html, /role="progressbar"/);
  assert.match(timerUi, /layer <= 5/);
  assert.match(timerUi, /className = 'layer-track'/);
  assert.match(timerUi, /className = 'layer-fill'/);
  assert.match(html, /Следующий отрезок/);
  assert.match(html, /Чтобы начать следующий отрезок, завершите текущий с теми же параметрами\./);
  assert.match(timerUi, /textContent = '✓'/);
  assert.doesNotMatch(timerUi, /interrupted|✕/);
  assert.match(html, /id="parameterModal" role="dialog" aria-modal="true"/);
  assert.match(html, /id="timerNext" type="button" hidden/);
  assert.match(timerUi, /window\.setTimeout\(openParameters, 0\)/);
  assert.match(timerUi, /showModal\('locked'\)/);
  assert.match(timerUi, /sessionStatus === 'segment_completed'/);
  assert.match(timerLogic, /completedLayersBeforeSegment/);
  assert.match(timerLogic, /targetCumulativeLayers/);
  assert.match(html, /⚠️Вы точно уверены, что хотите сбросить результаты\?/);
  assert.match(html, /Будут сброшены результаты всей тренировки\. Очищение начнётся снова с первого слоя\.🔄/);
  assert.match(timerUi, /elements\.reset\.addEventListener\('click', showResetConfirmation\)/);
  assert.match(timerUi, /function confirmReset\(\)/);
  assert.match(timerLogic, /function finalizeWorkoutOvertime\(session, now\)/);
  assert.match(timerUi, /Дополнительное очищение:/);
  assert.match(timerUi, /Сверх \$\{segment\.segmentNumber\} отрезка/);
});

test('Supplied compact WebP controls are used for timer actions', () => {
  for (const asset of ['button-play.webp', 'button-pause.webp', 'button-reset.webp', 'button-next.webp']) {
    assert.ok(fs.existsSync(path.join(directory, 'assets', asset)), `${asset} exists`);
    assert.match(html, new RegExp(`src="\\.\\/assets\\/${asset}"`));
    assert.match(serviceWorker, new RegExp(`'\\.\\/assets\\/${asset}'`));
  }
  assert.ok(fs.existsSync(path.join(directory, 'assets', 'button-next-active.webp')));
  assert.match(serviceWorker, /'\.\/assets\/button-next-active\.webp'/);
  assert.match(timerUi, /elements\.nextIcon\.src = overtimeRunning \? '\.\/assets\/button-next-active\.webp'/);
});

test('One reusable modal owns the only parameter controls and supports first-load flow', () => {
  for (const id of ['waterLayer', 'waterTemp', 'moveLayer', 'moveSpeed']) {
    assert.equal((html.match(new RegExp(`id="${id}"`, 'g')) || []).length, 1);
  }
  assert.match(timerUi, /function openParameters\(\)/);
  assert.match(timerUi, /function closeModal\(\)/);
  assert.match(timerUi, /document\.body\.classList\.add\('modal-open'\)/);
  assert.match(html, /Параметры текущего участка нельзя изменить до его завершения/);
  assert.match(timerUi, /elements\.modal\.hidden = true/);
  assert.match(timerUi, /elements\.next\.hidden = true/);
});

test('Movement presentation uses centralized compact pace and supplied history icons', () => {
  assert.match(html, /EasyPracticeTimer\.formatPace\(s\)/);
  assert.match(html, /EasyPracticeTimer\.formatPace\(moveSpeed\.value\)/);
  assert.match(timerUi, /Timer\.formatPace\(speed\)/);
  assert.match(timerUi, /Timer\.formatPace\(parameters\.speed\)/);
  assert.match(timerUi, /Timer\.getMovementKind\(parameters\.speed/);
  assert.match(timerUi, /HISTORY_ICON_SOURCES\[kind\]/);
  assert.match(timerUi, /document\.createElement\('img'\)/);
  assert.doesNotMatch(timerUi, /innerHTML/);
});

test('Timer backgrounds are selected by practice and session sex', () => {
  for (const asset of [
    'history-running.webp', 'history-walking.webp', 'history-water.webp',
    'timer-move-female.webp', 'timer-move-male.webp',
    'timer-water-female.webp', 'timer-water-male.webp'
  ]) {
    assert.ok(fs.existsSync(path.join(directory, 'assets', asset)), `${asset} exists`);
  }
  assert.match(timerUi, /'water:female': '\.\/assets\/timer-water-female\.webp'/);
  assert.match(timerUi, /'water:male': '\.\/assets\/timer-water-male\.webp'/);
  assert.match(timerUi, /'move:female': '\.\/assets\/timer-move-female\.webp'/);
  assert.match(timerUi, /'move:male': '\.\/assets\/timer-move-male\.webp'/);
  assert.match(timerUi, /elements\.backdrop\.hidden = true/);
});

test('Timer persistence is standalone and does not depend on a network API', () => {
  assert.match(timerLogic, /easypracticecalc\.timerState\.v1/);
  assert.match(timerLogic, /easypracticecalc\.workoutSession\.v2/);
  assert.doesNotMatch(timerLogic + timerUi, /\bfetch\s*\(|XMLHttpRequest|WebSocket/);
});

test('Service worker pre-caches timer assets within its existing safe scope logic', () => {
  assert.match(serviceWorker, /CACHE_PREFIX = 'easypracticecalc-'/);
  assert.match(serviceWorker, /2026-08-21-v12/);
  assert.match(serviceWorker, /'\.\/timer_logic\.js'/);
  assert.match(serviceWorker, /'\.\/timer\.js'/);
  assert.match(serviceWorker, /'\.\/assets\/history-running\.webp'/);
  assert.match(serviceWorker, /'\.\/assets\/timer-water-female\.webp'/);
  assert.match(serviceWorker, /requestUrl\.origin !== self\.location\.origin/);
  assert.match(serviceWorker, /requestUrl\.pathname\.startsWith\(scopeUrl\.pathname\)/);
});
