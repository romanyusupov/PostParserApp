"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const settingsLogic = require(
  "../postparser_web/static/settings_logic.js"
);


test("unsaved dates are saved before the parser run", async function () {
  const draft = {
    dateStart: "2026-01-01",
    dateEnd: "2026-08-04",
  };
  let saved = {
    dateStart: "2026-08-01",
    dateEnd: "2026-08-03",
  };
  const events = [];

  const ready = await settingsLogic.ensureSettingsSavedBeforeLaunch(
    true,
    async function () {
      events.push("save");
      saved = Object.assign({}, draft);
      return true;
    }
  );

  assert.equal(ready, true);
  events.push("launch");
  const run = {
    dateStart: saved.dateStart,
    dateEnd: saved.dateEnd,
  };
  assert.deepEqual(events, ["save", "launch"]);
  assert.deepEqual(run, draft);
});

test("failed automatic save prevents parser launch", async function () {
  let launchCount = 0;
  const ready = await settingsLogic.ensureSettingsSavedBeforeLaunch(
    true,
    async function () {
      return false;
    }
  );

  if (ready) {
    launchCount += 1;
  }

  assert.equal(ready, false);
  assert.equal(launchCount, 0);
});

test("saved settings do not trigger another save", async function () {
  let saveCount = 0;
  const ready = await settingsLogic.ensureSettingsSavedBeforeLaunch(
    false,
    async function () {
      saveCount += 1;
      return true;
    }
  );

  assert.equal(ready, true);
  assert.equal(saveCount, 0);
});
