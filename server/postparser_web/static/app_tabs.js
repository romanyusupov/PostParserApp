"use strict";

(function (root, factory) {
  const api = factory();

  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.PostParserTabs = api;
  }
})(typeof globalThis === "object" ? globalThis : this, function () {
  const knownNetworks = new Set(["vk", "telegram", "instagram"]);

  function cleanText(value) {
    return value === null || value === undefined
      ? ""
      : String(value).trim();
  }

  function networkTone(network) {
    const normalized = cleanText(network).toLowerCase();
    return knownNetworks.has(normalized) ? normalized : "other";
  }

  function readUrlState(search) {
    const parameters = new URLSearchParams(String(search || ""));
    return {
      groupId: cleanText(parameters.get("group")),
      runId: cleanText(parameters.get("run")),
    };
  }

  function buildUrl(pathname, groupId, runId) {
    const parameters = new URLSearchParams();
    const normalizedGroupId = cleanText(groupId);
    const normalizedRunId = cleanText(runId);

    if (normalizedGroupId) {
      parameters.set("group", normalizedGroupId);
    }
    if (normalizedRunId) {
      parameters.set("run", normalizedRunId);
    }

    const query = parameters.toString();
    return String(pathname || "") + (query ? "?" + query : "");
  }

  function updateUrl(pathname, groupId, runId, mode) {
    if (typeof window !== "object" || !window.history) {
      return;
    }

    const url = buildUrl(pathname, groupId, runId);
    const method = mode === "push" ? "pushState" : "replaceState";
    window.history[method]({}, "", url);
  }

  function updateParentLinks(groupId, runId) {
    if (typeof document !== "object") {
      return;
    }

    const settingsTab = document.getElementById("settingsParentTab");
    const resultsTab = document.getElementById("resultsParentTab");
    if (settingsTab) {
      settingsTab.href = buildUrl("/shadow/settings", groupId, "");
    }
    if (resultsTab) {
      resultsTab.href = buildUrl("/results", groupId, runId);
    }
  }

  function normalizeGroup(group, archived) {
    const source = group && typeof group === "object" ? group : {};
    return {
      id: cleanText(source.id || source.group_id),
      name: cleanText(source.name || source.group_name) || "Без названия",
      network: networkTone(source.network),
      archived: Boolean(archived),
    };
  }

  function mergeGroups(settingsGroups, runs) {
    const result = [];
    const knownIds = new Set();

    (Array.isArray(settingsGroups) ? settingsGroups : []).forEach(
      function (group) {
        const normalized = normalizeGroup(group, false);
        if (!normalized.id || knownIds.has(normalized.id)) {
          return;
        }
        knownIds.add(normalized.id);
        result.push(normalized);
      }
    );

    (Array.isArray(runs) ? runs : []).forEach(function (run) {
      const source = run && typeof run === "object" ? run : {};
      const normalized = normalizeGroup(
        {
          id: source.group_id,
          name: source.group_name,
          network: source.network,
        },
        true
      );
      if (!normalized.id || knownIds.has(normalized.id)) {
        return;
      }
      knownIds.add(normalized.id);
      result.push(normalized);
    });

    return result;
  }

  function selectedGroupId(groups, requestedGroupId) {
    const normalizedRequestedId = cleanText(requestedGroupId);
    const availableGroups = Array.isArray(groups) ? groups : [];
    const requestedExists = availableGroups.some(function (group) {
      return cleanText(group.id) === normalizedRequestedId;
    });

    if (requestedExists) {
      return normalizedRequestedId;
    }

    return availableGroups.length ? cleanText(availableGroups[0].id) : "";
  }

  function nextTabIndex(currentIndex, length, key) {
    if (length <= 0) {
      return -1;
    }
    if (key === "Home") {
      return 0;
    }
    if (key === "End") {
      return length - 1;
    }
    if (key === "ArrowRight") {
      return (currentIndex + 1) % length;
    }
    if (key === "ArrowLeft") {
      return (currentIndex - 1 + length) % length;
    }
    return currentIndex;
  }

  function bindKeyboard(tablist, onActivate) {
    tablist.addEventListener("keydown", function (event) {
      const tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));
      const currentIndex = tabs.indexOf(event.target);

      if (currentIndex < 0) {
        return;
      }

      if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        tabs[nextTabIndex(currentIndex, tabs.length, event.key)].focus();
        return;
      }

      if (["Enter", " "].includes(event.key)) {
        event.preventDefault();
        onActivate(event.target);
      }
    });
  }

  function setupParentTabs(tablist) {
    if (!tablist || tablist.dataset.keyboardReady === "true") {
      return;
    }

    bindKeyboard(tablist, function (tab) {
      tab.click();
    });
    tablist.dataset.keyboardReady = "true";
  }

  function renderGroupTabs(container, groups, activeGroupId, onActivate) {
    const availableGroups = Array.isArray(groups) ? groups : [];
    const selectedId = selectedGroupId(availableGroups, activeGroupId);
    container.replaceChildren();

    availableGroups.forEach(function (group, index) {
      const normalized = normalizeGroup(group, group.archived);
      const selected = normalized.id === selectedId;
      const tab = document.createElement("button");
      const dot = document.createElement("span");
      const label = document.createElement("span");

      tab.type = "button";
      tab.id = "groupTab" + String(index);
      tab.className = "group-tab";
      if (normalized.archived) {
        tab.classList.add("is-archived");
      }
      if (selected) {
        tab.classList.add("is-active");
      }
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", selected ? "true" : "false");
      tab.setAttribute("aria-controls", "groupPanel");
      tab.setAttribute("tabindex", selected ? "0" : "-1");
      tab.dataset.groupId = normalized.id;
      tab.title = normalized.name;

      dot.className = "network-dot network-" + normalized.network;
      dot.setAttribute("aria-hidden", "true");
      label.className = "group-tab-label";
      label.textContent = normalized.archived
        ? "Архив · " + normalized.name
        : normalized.name;

      tab.appendChild(dot);
      tab.appendChild(label);
      tab.addEventListener("click", function () {
        onActivate(normalized.id);
      });
      container.appendChild(tab);
    });

    const activeTab = container.querySelector('[aria-selected="true"]');
    const panel =
      typeof document === "object"
        ? document.getElementById("groupPanel")
        : null;
    if (panel && activeTab) {
      panel.setAttribute("aria-labelledby", activeTab.id);
    }

    if (
      availableGroups.length &&
      container.dataset.keyboardReady !== "true"
    ) {
      bindKeyboard(container, function (tab) {
        tab.click();
      });
      container.dataset.keyboardReady = "true";
    }

    return selectedId;
  }

  return {
    buildUrl: buildUrl,
    mergeGroups: mergeGroups,
    networkTone: networkTone,
    nextTabIndex: nextTabIndex,
    readUrlState: readUrlState,
    renderGroupTabs: renderGroupTabs,
    selectedGroupId: selectedGroupId,
    setupParentTabs: setupParentTabs,
    updateUrl: updateUrl,
    updateParentLinks: updateParentLinks,
  };
});
