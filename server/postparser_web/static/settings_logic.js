"use strict";

(function (root, factory) {
  const api = factory();

  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }

  if (root) {
    root.PostParserSettingsLogic = api;
  }
})(typeof window !== "undefined" ? window : globalThis, function () {
  function formatLocalDate(date) {
    const year = String(date.getFullYear()).padStart(4, "0");
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return year + "-" + month + "-" + day;
  }

  function subtractCalendarMonths(date, monthCount) {
    const result = new Date(
      date.getFullYear(),
      date.getMonth() - monthCount,
      1
    );
    const lastDay = new Date(
      result.getFullYear(),
      result.getMonth() + 1,
      0
    ).getDate();
    result.setDate(Math.min(date.getDate(), lastDay));
    return result;
  }

  function calculateDateRange(period, currentDate) {
    const today = currentDate instanceof Date
      ? new Date(
          currentDate.getFullYear(),
          currentDate.getMonth(),
          currentDate.getDate()
        )
      : new Date();
    let start = new Date(today.getTime());

    if (period === "week") {
      start.setDate(start.getDate() - 7);
    } else if (period === "month") {
      start = subtractCalendarMonths(start, 1);
    } else if (period === "three-months") {
      start = subtractCalendarMonths(start, 3);
    } else if (period === "six-months") {
      start = subtractCalendarMonths(start, 6);
    } else if (period === "year") {
      start = subtractCalendarMonths(start, 12);
    } else if (period !== "today") {
      throw new Error("Unknown date period");
    }

    return {
      dateStart: formatLocalDate(start),
      dateEnd: formatLocalDate(today),
    };
  }

  async function ensureSettingsSavedBeforeLaunch(
    hasUnsavedChanges,
    saveSettings
  ) {
    if (!hasUnsavedChanges) {
      return true;
    }

    return (await saveSettings()) === true;
  }

  return {
    calculateDateRange: calculateDateRange,
    ensureSettingsSavedBeforeLaunch: ensureSettingsSavedBeforeLaunch,
  };
});
