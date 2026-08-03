"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const tabs = require("../postparser_web/static/app_tabs.js");


test("network colors use stable social network tones", function () {
  assert.equal(tabs.networkTone("vk"), "vk");
  assert.equal(tabs.networkTone("telegram"), "telegram");
  assert.equal(tabs.networkTone("instagram"), "instagram");
  assert.equal(tabs.networkTone("unknown"), "other");
});

test("group tabs preserve settings order and append archived groups", function () {
  const groups = tabs.mergeGroups(
    [
      { id: "vk", name: "VK group", network: "vk" },
      { id: "tg", name: "TG group", network: "telegram" },
    ],
    [
      { id: 10, group_id: "vk", group_name: "Old VK", network: "vk" },
      { id: 11, group_id: "deleted", group_name: "Deleted", network: "instagram" },
    ]
  );

  assert.deepEqual(
    groups.map((group) => [group.id, group.name, group.archived]),
    [
      ["vk", "VK group", false],
      ["tg", "TG group", false],
      ["deleted", "Deleted", true],
    ]
  );
});

test("invalid group selection safely falls back to the first group", function () {
  const groups = [
    { id: "first" },
    { id: "second" },
  ];

  assert.equal(tabs.selectedGroupId(groups, "missing"), "first");
  assert.equal(tabs.selectedGroupId(groups, "second"), "second");
  assert.equal(tabs.selectedGroupId([], "missing"), "");
});

test("URL state preserves group and run identifiers", function () {
  const url = tabs.buildUrl("/results", "group id", 42);

  assert.equal(url, "/results?group=group+id&run=42");
  assert.deepEqual(tabs.readUrlState("?group=group+id&run=42"), {
    groupId: "group id",
    runId: "42",
  });
});

test("keyboard tab navigation wraps and supports boundaries", function () {
  assert.equal(tabs.nextTabIndex(0, 4, "ArrowLeft"), 3);
  assert.equal(tabs.nextTabIndex(3, 4, "ArrowRight"), 0);
  assert.equal(tabs.nextTabIndex(2, 4, "Home"), 0);
  assert.equal(tabs.nextTabIndex(1, 4, "End"), 3);
});
