"use strict";

// Run with an already installed Playwright and Chrome; no packages are downloaded.
// NODE_PATH may point to the existing runtime's node_modules directory.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
let chromium;
try {
  ({ chromium } = require("playwright"));
} catch (error) {
  if (error.code !== 'MODULE_NOT_FOUND') throw error;
  require('node:test')('water browser checks', { skip: 'Set NODE_PATH to an already installed Playwright runtime.' }, () => {});
}

async function inspect(page) {
  return page.evaluate(() => {
    const screen = document.querySelector('.screen');
    const viewportHeight = visualViewport.height;
    const failures = [];
    const rect = node => node.getBoundingClientRect();
    const contains = (outer, inner, margin = 0) => inner.left >= outer.left + margin - .5 && inner.top >= outer.top + margin - .5 && inner.right <= outer.right - margin + .5 && inner.bottom <= outer.bottom - margin + .5;
    const viewport = { left: 0, top: 0, right: innerWidth, bottom: viewportHeight };
    const elements = document.querySelectorAll('.page-heading, .stage, .comparison, .practice-card, .practice-card__status, .temperature, .info-section, .info-content, .info-content *, .nav-control, .nav-control__circle, .nav-control__label');
    for (const node of elements) {
      const box = rect(node);
      if (!contains(viewport, box)) failures.push(`outside viewport: ${node.className}`);
      const section = node.closest('.info-section');
      if (section && section !== node && !contains(rect(section), box, 1)) failures.push(`outside section: ${node.className}`);
      // Detect text painted beyond its own box, not only element rectangles.
      for (const child of node.childNodes) {
        if (child.nodeType !== Node.TEXT_NODE || !child.textContent.trim()) continue;
        const range = document.createRange();
        range.selectNodeContents(child);
        const ink = range.getBoundingClientRect();
        // Glyph ink may exceed a line box vertically by a fraction of a pixel.
        // Check horizontal wrapping plus the containing card/viewport vertically.
        if (ink.left < box.left - .5 || ink.right > box.right + .5 || !contains(section ? rect(section) : viewport, ink)) failures.push(`text overflow: ${node.className}`);
      }
    }
    const sections = [...document.querySelectorAll('.info-section')];
    let portraitSpacing;
    if (screen.dataset.layout === 'portrait') {
      const padding = getComputedStyle(screen);
      const circles = [...document.querySelectorAll('.nav-control__circle')].map(rect);
      const upperGap = Math.min(...circles.map(box => box.top)) - rect(sections[2]).bottom;
      const lowerGap = viewportHeight - Math.max(...circles.map(box => box.bottom));
      const subtitle = document.querySelector('.page-heading p');
      const calculator = document.querySelector('.calculator-link');
      portraitSpacing = { upperGap, lowerGap, headingTop: rect(document.querySelector('.page-heading')).top, calculatorHeight: rect(calculator).height };
      if (upperGap < 10 || upperGap > 15) failures.push(`arrow upper gap: ${upperGap}`);
      if (Math.abs(lowerGap - parseFloat(padding.paddingBottom)) > .5 || lowerGap < 10) failures.push(`arrow lower gap: ${lowerGap}`);
      if (portraitSpacing.headingTop < 14) failures.push('heading too close to top');
      if (rect(subtitle).height > parseFloat(getComputedStyle(subtitle).lineHeight) + .5) failures.push('portrait subtitle wraps');
      if (rect(document.querySelector('.formula')).height > parseFloat(getComputedStyle(document.querySelector('.formula')).lineHeight) + .5) failures.push('portrait formula wraps');
      if (rect(calculator).height > 40 || rect(calculator).height < 36) failures.push('portrait calculator is not compact/tappable');
      if (parseFloat(getComputedStyle(calculator).fontSize) >= parseFloat(padding.fontSize)) failures.push('portrait calculator text not reduced');
    }
    for (let i = 1; i < sections.length; i++) {
      if (rect(sections[i - 1]).bottom > rect(sections[i]).top + .5) failures.push('overlapping sections');
    }
    if (screen.dataset.layout !== 'portrait') {
      const panel = rect(document.querySelector('.info-panel'));
      sections.forEach(node => { if (!contains(panel, rect(node), 1)) failures.push('section outside panel'); });
      if (rect(document.querySelector('.nav-control--next')).left < panel.right) failures.push('next navigation overlaps panel');
      if (rect(document.querySelector('.nav-control--back')).right > rect(document.querySelector('.comparison')).left) failures.push('back navigation overlaps photo');
    }
    const scrolling = document.scrollingElement;
    if (scrolling.scrollWidth > innerWidth || scrolling.scrollHeight > innerHeight) failures.push(`document scroll: ${scrolling.scrollWidth}x${scrolling.scrollHeight}`);
    if (document.querySelector('.level-marker, .wrong-x')) failures.push('HTML water annotations');
    for (const photo of document.querySelectorAll('.practice-card__photo')) {
      const frame = rect(photo.parentElement);
      const box = rect(photo);
      if (getComputedStyle(photo).objectFit !== 'cover') failures.push('photo letterboxing');
      if (Math.abs(box.height - photo.parentElement.clientHeight) > .5 || Math.abs(box.width - photo.parentElement.clientWidth) > .5) failures.push('photo does not fill frame');
      if (!photo.naturalWidth || !photo.naturalHeight) failures.push('photo not loaded');
      if (!contains(frame, box)) failures.push('photo outside frame');
      const coverScale = Math.max(box.width / photo.naturalWidth, box.height / photo.naturalHeight);
      // The baked captions and cross are kept inside the central 56% of the image.
      if (box.width / (photo.naturalWidth * coverScale) < .56) failures.push('crop cuts into annotation safe area');
    }
    return { failures, width: innerWidth, height: viewportHeight, layout: screen.dataset.layout, fit: screen.style.getPropertyValue('--fit'), stageHeight: rect(document.querySelector('.stage')).height, stageWidth: rect(document.querySelector('.stage')).width, portraitSpacing };
  });
}

if (chromium) (async () => {
  const html = fs.readFileSync(path.join(__dirname, 'water/index.html'));
  const server = http.createServer((request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
    response.end(html);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const output = process.env.WATER_SCREENSHOTS || fs.mkdtempSync(path.join(os.tmpdir(), 'water-layout-'));
  fs.mkdirSync(output, { recursive: true });
  let browser;
  try {
    browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
    const page = await browser.newPage({ viewport: { width: 440, height: 956 }, deviceScaleFactor: 1 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/easystart/water/`);
    await page.evaluate(() => Promise.all([...document.images].map(image => image.decode())));
    const sizes = [[440,956],[440,760],[430,740],[393,680],[390,650],[375,620],[320,480],[956,340],[844,300],[740,300],[568,260],[768,1024],[1024,768],[1920,1080],[1868,850],[1366,768],[1100,600],[2880,1440]];
    const results = [];
    for (const [width, height] of sizes) {
      await page.setViewportSize({ width, height });
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const result = await inspect(page);
      results.push(result);
      console.log(JSON.stringify(result));
      await page.screenshot({ path: path.join(output, `${width}x${height}.png`) });
      assert.deepEqual(result.failures, [], `${width}x${height}`);
      if (width >= 1100) assert.ok(result.stageHeight <= 720, 'desktop slide fits its enlarged limit');
      if (width >= 1920) {
        assert.equal(result.stageHeight, 720, 'desktop height enlarged 1.5x');
        assert.ok(result.stageWidth >= 1900 && result.stageWidth <= 1920, 'desktop width enlarged about 1.5x');
        assert.ok(Number(result.fit) >= 1.4, 'desktop type and controls enlarged too');
      }
    }
    // Browser chrome can change visualViewport without a layout viewport resize.
    await page.setViewportSize({ width: 440, height: 956 });
    await page.evaluate(() => {
      Object.defineProperty(visualViewport, 'height', { configurable: true, get: () => 720 });
      visualViewport.dispatchEvent(new Event('resize'));
    });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const chromeResult = await inspect(page);
    assert.deepEqual(chromeResult.failures, [], 'visible viewport with browser chrome');
    assert.equal(await page.locator('.screen').evaluate(node => node.clientHeight), 720);
    await page.getByRole('button', { name: 'Перейти к разделу «Статические позы»' }).click();
    assert.match(await page.locator('.notice').innerText(), /будет добавлен/);
    assert.equal(await page.locator('.calculator-link').getAttribute('href'), '/easypracticecalc/');
    assert.equal(await page.locator('.nav-control--back').getAttribute('href'), '/easystart/');
    // Also exercise the browser's actual mobile rendering mode and orientation.
    const phone = await browser.newPage({ isMobile: true, hasTouch: true, deviceScaleFactor: 3, viewport: { width: 440, height: 760 } });
    phone.on('pageerror', error => errors.push(error.message));
    await phone.goto(`http://127.0.0.1:${server.address().port}/easystart/water/`);
    for (const [width, height] of [[440,760], [956,340], [1366,768], [440,760]]) {
      await phone.setViewportSize({ width, height });
      await phone.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const result = await inspect(phone);
      console.log(JSON.stringify({ mobile: true, requested: [width, height], ...result }));
      assert.deepEqual(result.failures, [], 'mobile rendering and orientation');
      if (width === 1366) assert.ok(result.stageHeight <= 480, 'touch device keeps its existing size');
      results.push({ ...result, mobile: true });
    }
    const fitBeforeZoom = await phone.locator('.screen').evaluate(node => node.style.getPropertyValue('--fit'));
    const cdp = await phone.context().newCDPSession(phone);
    await cdp.send('Emulation.setPageScaleFactor', {pageScaleFactor: 2});
    await phone.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await phone.locator('.screen').evaluate(node => node.style.getPropertyValue('--fit')), fitBeforeZoom, 'pinch zoom must not shrink the UI');
    await cdp.detach();
    await phone.close();
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify([...results, chromeResult], null, 2));
    console.log(`23 viewport/mobile checks, navigation and pinch zoom: OK. Screenshots: ${output}`);
  } finally {
    if (browser) await browser.close();
    server.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
