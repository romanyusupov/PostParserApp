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
assert.match(page, /Прогрев \(горячая ванна, парная\)\./);
assert.doesNotMatch(page, /Целевой ориентир/);
assert.match(page, /href="\/easypracticecalc\/"/);
assert.match(page, /href="\/easystart\/"/);
assert.match(page, /@media \(orientation: portrait\)/);
assert.match(page, /@media \(orientation: landscape\)/);
assert.doesNotMatch(page, /level-marker__line/);
assert.match(page, /height: 100dvh/);
assert.match(page, /padding: 7px/);

const scripts = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((match) => match[1]);
assert.equal(scripts.length, 1);
new vm.Script(scripts[0], { filename: "water/index.inline.js" });

console.log("water quiz checks: ok");
