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
    ensureSettingsSavedBeforeLaunch: ensureSettingsSavedBeforeLaunch,
  };
});
