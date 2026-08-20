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
    'timerStart', 'timerPause', 'timerResume', 'timerReset', 'timerNext',
    'timerCumulative', 'timerProgress', 'layerProgress', 'segmentHistory',
    'segmentWarning', 'segmentWarningClose', 'practiceParameters',
    'parameterToggle', 'parameterPanel', 'parameterSummary'
  ]) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /\.timer-circle/);
  assert.match(html, /\.layer-progress/);
  assert.match(html, /role="progressbar"/);
  assert.match(timerUi, /layer <= 5/);
  assert.match(timerUi, /className = 'layer-track'/);
  assert.match(timerUi, /className = 'layer-fill'/);
  assert.match(html, /\+ Следующий отрезок/);
  assert.match(html, /Чтобы начать следующий отрезок, завершите текущий с теми же параметрами\./);
  assert.match(timerUi, /textContent = '✓'/);
  assert.doesNotMatch(timerUi, /interrupted|✕/);
  assert.match(html, /aria-expanded="true" aria-controls="parameterPanel"/);
  assert.match(html, /\.parameters\.mobile-collapsed \.parameter-panel\{display:none\}/);
  assert.match(timerUi, /setParametersExpanded\(false\)/);
  assert.match(timerUi, /setParametersExpanded\(true\)/);
  assert.match(timerLogic, /completedLayersBeforeSegment/);
  assert.match(timerLogic, /targetCumulativeLayers/);
});

test('Timer persistence is standalone and does not depend on a network API', () => {
  assert.match(timerLogic, /easypracticecalc\.timerState\.v1/);
  assert.match(timerLogic, /easypracticecalc\.workoutSession\.v2/);
  assert.doesNotMatch(timerLogic + timerUi, /\bfetch\s*\(|XMLHttpRequest|WebSocket/);
});

test('Service worker pre-caches timer assets within its existing safe scope logic', () => {
  assert.match(serviceWorker, /CACHE_PREFIX = 'easypracticecalc-'/);
  assert.match(serviceWorker, /2026-08-20-v6/);
  assert.match(serviceWorker, /'\.\/timer_logic\.js'/);
  assert.match(serviceWorker, /'\.\/timer\.js'/);
  assert.match(serviceWorker, /requestUrl\.origin !== self\.location\.origin/);
  assert.match(serviceWorker, /requestUrl\.pathname\.startsWith\(scopeUrl\.pathname\)/);
});
