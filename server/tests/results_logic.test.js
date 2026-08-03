"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const resultsLogic = require("../postparser_web/static/results_logic.js");


test("a new metric starts descending and repeated clicks toggle", function () {
  const first = resultsLogic.nextSortState(null, "views");
  const second = resultsLogic.nextSortState(first, "views");
  const third = resultsLogic.nextSortState(second, "views");

  assert.deepEqual(first, { field: "views", direction: "descending" });
  assert.deepEqual(second, { field: "views", direction: "ascending" });
  assert.deepEqual(third, { field: "views", direction: "descending" });
});

test("a different metric starts descending", function () {
  const state = resultsLogic.nextSortState(
    { field: "views", direction: "ascending" },
    "likes"
  );

  assert.deepEqual(state, { field: "likes", direction: "descending" });
});

test("metrics are sorted numerically", function () {
  const posts = [
    { id: "twenty", views: "20" },
    { id: "hundred", views: "100" },
    { id: "three", views: 3 },
  ];

  assert.deepEqual(
    resultsLogic.sortPosts(posts, "views", "descending").map((post) => post.id),
    ["hundred", "twenty", "three"]
  );
  assert.deepEqual(
    resultsLogic.sortPosts(posts, "views", "ascending").map((post) => post.id),
    ["three", "twenty", "hundred"]
  );
});

test("missing and invalid metrics remain last in both directions", function () {
  const posts = [
    { id: "missing", views: null },
    { id: "ten", views: 10 },
    { id: "empty", views: "" },
    { id: "broken", views: "not-a-number" },
    { id: "two", views: 2 },
  ];

  assert.deepEqual(
    resultsLogic.sortPosts(posts, "views", "descending").map((post) => post.id),
    ["ten", "two", "missing", "empty", "broken"]
  );
  assert.deepEqual(
    resultsLogic.sortPosts(posts, "views", "ascending").map((post) => post.id),
    ["two", "ten", "missing", "empty", "broken"]
  );
});

test("sorting keeps every post object and its linked data together", function () {
  const posts = [
    { id: "a", likes: 1, url: "https://example.test/a", text: "A" },
    { id: "b", likes: 9, url: "https://example.test/b", text: "B" },
  ];
  const sorted = resultsLogic.sortPosts(posts, "likes", "descending");

  assert.equal(sorted[0], posts[1]);
  assert.equal(sorted[0].url, "https://example.test/b");
  assert.equal(sorted[0].text, "B");
});

test("collapsed text is limited and preserves literal HTML and emoji", function () {
  const source = "<img src=x onerror=alert(1)>😀\n" + "Текст ".repeat(80);
  const result = resultsLogic.collapsedText(source, 300, 6);

  assert.equal(result.shortened, true);
  assert.match(result.text, /^<img src=x onerror=alert\(1\)>😀/);
  assert.ok(Array.from(result.text).length <= 301);
});

test("video description collapse preserves literal HTML and emoji", function () {
  const description = "<b>Не HTML</b> 🎬\n" + "Описание ".repeat(50);
  const result = resultsLogic.collapsedText(description, 300, 6);

  assert.equal(result.shortened, true);
  assert.match(result.text, /^<b>Не HTML<\/b> 🎬/);
  assert.ok(Array.from(result.text).length <= 301);
});

test("text with more than six lines is collapsed", function () {
  const result = resultsLogic.collapsedText(
    "one\ntwo\nthree\nfour\nfive\nsix\nseven",
    300,
    6
  );

  assert.equal(result.shortened, true);
  assert.equal(result.text, "one\ntwo\nthree\nfour\nfive\nsix…");
});

test("safe URLs accept HTTP links and reject executable schemes", function () {
  assert.equal(
    resultsLogic.safeHttpUrl("https://example.test/post"),
    "https://example.test/post"
  );
  assert.equal(resultsLogic.safeHttpUrl("javascript:alert(1)"), "");
  assert.equal(resultsLogic.safeHttpUrl(""), "");
});

test("metric normalization does not turn missing values into zero", function () {
  assert.equal(resultsLogic.metricValue(null), null);
  assert.equal(resultsLogic.metricValue(undefined), null);
  assert.equal(resultsLogic.metricValue(""), null);
  assert.equal(resultsLogic.metricValue("broken"), null);
  assert.equal(resultsLogic.metricValue(0), 0);
});
