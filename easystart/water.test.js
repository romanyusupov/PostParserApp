"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = __dirname;
const landing = fs.readFileSync(path.join(root, "index.html"), "utf8");
const page = fs.readFileSync(path.join(root, "water", "index.html"), "utf8");

assert.match(landing, /href="\/easystart\/water\/"/);
assert.equal((page.match(/data:image\/jpeg;base64,/g) || []).length, 3);
assert.doesNotMatch(page, /(?:src|url)=["']https?:\/\//);
assert.doesNotMatch(page, /@import\s+url/);
assert.match(page, /Правильно/);
assert.match(page, /Ошибка/);
assert.match(page, /25°C и ниже/);
assert.match(page, /<p>Правильный уровень и согрев после холодной воды\.<\/p>/);
assert.match(page, /<p class="formula"><strong>T℃ воды<\/strong> х кол-во слоев = время практики<\/p>/);
assert.doesNotMatch(page, /Температура воды \+ количество слоев/);
assert.match(page, /Прогрев \(горячая ванна, парная\)\./);
assert.doesNotMatch(page, /Целевой ориентир/);
assert.match(page, /href="\/easypracticecalc\/"/);
assert.match(page, /href="\/easystart\/"/);
assert.match(page, /data-layout="portrait"/);
assert.match(page, /data-layout="compact"/);
assert.match(page, /@media \(orientation: landscape\)/);
assert.doesNotMatch(page, /level-marker|wrong-x/);
assert.doesNotMatch(page, />\s*(?:по подмышки|По пояс — неправильно)\s*</);
assert.match(page, /object-fit: cover; object-position: center/);
assert.doesNotMatch(page, /object-fit: contain/);
assert.match(page, /height: 100dvh/);
assert.match(page, /max\(7px, env\(safe-area-inset/);
assert.match(page, /-webkit-text-size-adjust: 100%/);
assert.match(page, /height: min\(100%, var\(--stage-max-height\)\)/);
assert.match(page, /--desktop-scale: 1\.5; --stage-max-width: 1920px; --stage-max-height: 720px/);
assert.match(page, /\(hover: hover\) and \(pointer: fine\)/);
assert.match(page, /flex: 0 0 auto/);
assert.match(page, /window\.visualViewport\?\.addEventListener\('resize', scheduleFit\)/);
assert.match(page, /Math\.abs\(viewport\.scale - 1\)/);
assert.doesNotMatch(page, /overflow:\s*hidden[\s\S]{0,30}grid-template-columns: 24px/);

const scripts = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((match) => match[1]);
assert.equal(scripts.length, 1);
new vm.Script(scripts[0], { filename: "water/index.inline.js" });

// All images remain embedded in the deployed HTML, with no filesystem dependency.
for (const match of page.matchAll(/data:image\/jpeg;base64,([A-Za-z0-9+/=]+)/g)) {
  const jpeg = Buffer.from(match[1], 'base64');
  assert.equal(jpeg.readUInt16BE(0), 0xffd8);
  assert.equal(jpeg.readUInt16BE(jpeg.length - 2), 0xffd9);
}

console.log("water quiz checks: ok");
