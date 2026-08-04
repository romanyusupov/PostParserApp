"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const settingsLogic = require(
  "../postparser_web/static/settings_logic.js"
);

test("date presets calculate local ranges from today", function () {
  const today = new Date(2026, 7, 4);

  assert.deepEqual(
    settingsLogic.calculateDateRange("today", today),
    { dateStart: "2026-08-04", dateEnd: "2026-08-04" }
  );
  assert.deepEqual(
    settingsLogic.calculateDateRange("week", today),
    { dateStart: "2026-07-28", dateEnd: "2026-08-04" }
  );
  assert.deepEqual(
    settingsLogic.calculateDateRange("month", today),
    { dateStart: "2026-07-04", dateEnd: "2026-08-04" }
  );
  assert.deepEqual(
    settingsLogic.calculateDateRange("three-months", today),
    { dateStart: "2026-05-04", dateEnd: "2026-08-04" }
  );
  assert.deepEqual(
    settingsLogic.calculateDateRange("six-months", today),
    { dateStart: "2026-02-04", dateEnd: "2026-08-04" }
  );
  assert.deepEqual(
    settingsLogic.calculateDateRange("year", today),
    { dateStart: "2025-08-04", dateEnd: "2026-08-04" }
  );
});

test("calendar month presets clamp the day at month end", function () {
  assert.deepEqual(
    settingsLogic.calculateDateRange("month", new Date(2026, 2, 31)),
    { dateStart: "2026-02-28", dateEnd: "2026-03-31" }
  );
});


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
