"use strict";

(function () {
  const runsApiUrl = "/api/v1/results/runs";
  const settingsApiUrl = "/api/v1/settings";
  const resultsLogic = window.PostParserResults;
  const tabs = window.PostParserTabs;
  const collapsedTextCharacters = 300;
  const collapsedTextLines = 6;
  const collapsedRunsLimit = 3;

  const statusMessage = document.getElementById("statusMessage");
  const runsTableBody = document.getElementById("runsTableBody");
  const runsEmptyState = document.getElementById("runsEmptyState");
  const runsToggleButton = document.getElementById("runsToggleButton");
  const postsSection = document.getElementById("postsSection");
  const postsTableBody = document.getElementById("postsTableBody");
  const postsEmptyState = document.getElementById("postsEmptyState");
  const selectedRunDescription = document.getElementById(
    "selectedRunDescription"
  );
  const exportGoogleSheetsButton = document.getElementById(
    "exportGoogleSheetsButton"
  );
  const exportResult = document.getElementById("exportResult");
  const sortButtons = Array.from(
    document.querySelectorAll("[data-sort-field]")
  );
  const groupTabs = document.getElementById("groupTabs");
  const parentTabList = document.getElementById("parentTabList");

  let selectedRunId = null;
  let activeGroupId = "";
  let allGroups = [];
  let allRuns = [];
  let visibleRuns = [];
  let runsExpanded = false;
  let pendingSelectionNotice = "";
  let loadedPosts = [];
  let sortState = { field: null, direction: null };

  tabs.setupParentTabs(parentTabList);

  function createElement(tagName, className, text) {
    const element = document.createElement(tagName);

    if (className) {
      element.className = className;
    }

    if (text !== undefined) {
      element.textContent = text;
    }

    return element;
  }

  function setStatus(message, type) {
    statusMessage.textContent = message;
    statusMessage.className = "status status-" + type;
  }

  function apiError(data, fallbackMessage) {
    const message =
      data && typeof data.error === "string" ? data.error.trim() : "";

    return message && !message.includes("Traceback")
      ? message
      : fallbackMessage;
  }

  async function readJson(response) {
    try {
      return await response.json();
    } catch (error) {
      return null;
    }
  }

  function formatDate(value) {
    if (!value) {
      return "—";
    }

    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? String(value)
      : date.toLocaleString("ru-RU");
  }

  function formatMetric(value) {
    if (value === null || value === undefined || value === "") {
      return "—";
    }

    const metric = Number(value);
    return Number.isFinite(metric) ? String(metric) : "—";
  }

  function statusLabel(status) {
    const labels = {
      running: "Выполняется",
      completed: "Завершён",
      failed: "Ошибка",
    };
    return labels[status] || String(status || "—");
  }

  function networkLabel(network) {
    const labels = {
      vk: "VK",
      instagram: "Instagram",
      telegram: "Telegram",
    };
    return labels[network] || String(network || "—");
  }

  function appendCell(row, text, className) {
    const cell = createElement("td", className, text);
    row.appendChild(cell);
    return cell;
  }

  function emptyValue() {
    return createElement("span", "empty-value", "—");
  }

  function appendPublicationCell(row, post) {
    const cell = appendCell(row, "", "publication-cell");
    const preview = createElement("div", "publication-preview");
    const imageUrl = resultsLogic.safeHttpUrl(post.image_url);

    if (imageUrl) {
      const image = createElement("img", "publication-image");
      image.src = imageUrl;
      image.alt = "";
      image.loading = "lazy";
      image.addEventListener("error", function () {
        preview.replaceChildren(emptyValue());
      });
      preview.appendChild(image);
    } else {
      preview.appendChild(emptyValue());
    }

    const linkContainer = createElement("div", "publication-link");
    const permalink = resultsLogic.safeHttpUrl(post.url);

    if (permalink) {
      const link = createElement("a", "", "Открыть");
      link.href = permalink;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      linkContainer.appendChild(link);
    } else {
      linkContainer.appendChild(emptyValue());
    }

    cell.appendChild(preview);
    cell.appendChild(linkContainer);
  }

  function appendExpandableTextCell(row, value, className) {
    const cell = appendCell(row, "", className);
    const text = value === null || value === undefined ? "" : String(value);

    if (!text.trim()) {
      cell.appendChild(emptyValue());
      return;
    }

    const collapsed = resultsLogic.collapsedText(
      text,
      collapsedTextCharacters,
      collapsedTextLines
    );
    const content = createElement(
      "div",
      "post-text-content",
      collapsed.text
    );
    cell.appendChild(content);

    if (!collapsed.shortened) {
      return;
    }

    const toggle = createElement(
      "button",
      "text-toggle",
      "Показать полностью"
    );
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", "false");
    toggle.addEventListener("click", function () {
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      content.textContent = expanded ? collapsed.text : text;
      toggle.textContent = expanded ? "Показать полностью" : "Свернуть";
      toggle.setAttribute("aria-expanded", expanded ? "false" : "true");
    });
    cell.appendChild(toggle);
  }

  const sortLabels = {
    views: "просмотрам",
    likes: "лайкам",
    comments: "комментариям",
  };

  function updateSortHeaders() {
    sortButtons.forEach(function (button) {
      const field = button.dataset.sortField;
      const header = button.closest("th");
      const indicator = button.querySelector(".sort-indicator");
      const active = sortState.field === field;
      const direction = active ? sortState.direction : "none";
      const nextDirection =
        active && direction === "descending" ? "ascending" : "descending";
      const directionLabel =
        nextDirection === "descending" ? "по убыванию" : "по возрастанию";
      const actionLabel =
        "Сортировать по " + sortLabels[field] + " " + directionLabel;

      header.setAttribute("aria-sort", direction);
      indicator.textContent =
        direction === "descending"
          ? "↓"
          : direction === "ascending"
            ? "↑"
            : "↓↑";
      button.setAttribute("aria-label", actionLabel);
      button.title = actionLabel;
    });
  }

  function renderRuns(runs) {
    runsTableBody.replaceChildren();
    runsEmptyState.hidden = runs.length !== 0;
    const displayedRuns = resultsLogic.limitedRuns(
      runs,
      runsExpanded,
      collapsedRunsLimit
    );
    const hasHiddenRuns = runs.length > collapsedRunsLimit;

    runsToggleButton.hidden = !hasHiddenRuns;
    runsToggleButton.textContent = resultsLogic.runsToggleLabel(
      runs.length,
      runsExpanded,
      collapsedRunsLimit
    );
    runsToggleButton.setAttribute(
      "aria-expanded",
      runsExpanded ? "true" : "false"
    );

    if (runs.length === 0) {
      selectedRunId = null;
      postsSection.hidden = true;
      exportGoogleSheetsButton.hidden = true;
    }

    displayedRuns.forEach(function (run) {
      const row = createElement("tr");
      const currentGroup = allGroups.find(function (group) {
        return group.id === String(run.group_id || "");
      });
      appendCell(
        row,
        String(currentGroup ? currentGroup.name : run.group_name || "—")
      );
      appendCell(row, networkLabel(run.network));
      appendCell(row, formatDate(run.finished_at || run.started_at));
      appendCell(row, statusLabel(run.status));
      appendCell(row, formatMetric(run.count), "metric-cell");
      appendCell(row, String(run.warning || "—"), "run-warning-cell");

      if (Number(run.id) === Number(selectedRunId)) {
        row.classList.add("is-selected");
      }

      const actionCell = appendCell(row, "", "action-cell");
      const selectButton = createElement(
        "button",
        "button button-secondary button-small",
        "Открыть"
      );
      selectButton.type = "button";
      selectButton.addEventListener("click", function () {
        loadPosts(run, "push");
      });
      actionCell.appendChild(selectButton);
      runsTableBody.appendChild(row);
    });
  }

  function renderPosts(posts) {
    if (Array.isArray(posts)) {
      loadedPosts = posts.slice();
    }

    const displayedPosts = sortState.field
      ? resultsLogic.sortPosts(
          loadedPosts,
          sortState.field,
          sortState.direction
        )
      : loadedPosts.slice();

    postsTableBody.replaceChildren();
    postsEmptyState.hidden = displayedPosts.length !== 0;

    displayedPosts.forEach(function (post) {
      const row = createElement("tr");
      appendCell(row, formatDate(post.published_at));
      appendPublicationCell(row, post);
      appendExpandableTextCell(row, post.text, "post-text");
      appendCell(
        row,
        String(post.post_type || "—"),
        "post-type-cell"
      );
      appendExpandableTextCell(
        row,
        post.video_description,
        "video-description-cell"
      );
      appendCell(
        row,
        String(post.advertising_type || "—"),
        "advertising-type-cell"
      );
      appendCell(row, formatMetric(post.views), "metric-cell");
      appendCell(row, formatMetric(post.likes), "metric-cell");
      appendCell(row, formatMetric(post.comments), "metric-cell");
      postsTableBody.appendChild(row);
    });
  }

  async function loadPosts(run, historyMode) {
    const runId = run.id;
    const currentGroup = allGroups.find(function (group) {
      return group.id === String(run.group_id || "");
    });
    const groupName = currentGroup ? currentGroup.name : run.group_name;
    selectedRunId = runId;
    renderRuns(visibleRuns);
    if (historyMode) {
      tabs.updateUrl(
        window.location.pathname,
        activeGroupId,
        runId,
        historyMode
      );
    }
    tabs.updateParentLinks(activeGroupId, runId);
    loadedPosts = [];
    sortState = { field: null, direction: null };
    updateSortHeaders();
    postsSection.hidden = false;
    exportGoogleSheetsButton.hidden = false;
    exportGoogleSheetsButton.disabled = false;
    exportGoogleSheetsButton.textContent =
      "Экспортировать в Google Sheets";
    exportResult.hidden = true;
    exportResult.replaceChildren();
    selectedRunDescription.textContent =
      "Запуск " + String(runId) + " · " + String(groupName || "Без названия");
    postsTableBody.replaceChildren();
    postsEmptyState.hidden = true;
    setStatus("Загружаем публикации…", "info");

    try {
      const response = await fetch(
        runsApiUrl + "/" + encodeURIComponent(String(runId)) + "/posts",
        { headers: { Accept: "application/json" } }
      );
      const data = await readJson(response);

      if (!response.ok || !data || !data.success) {
        throw new Error(
          apiError(data, "Не удалось загрузить публикации.")
        );
      }

      const posts = Array.isArray(data.posts) ? data.posts : [];
      renderPosts(posts);
      setStatus(
        pendingSelectionNotice || "Публикации загружены.",
        pendingSelectionNotice ? "info" : "success"
      );
      pendingSelectionNotice = "";
    } catch (error) {
      renderPosts([]);
      setStatus(
        error instanceof Error
          ? error.message
          : "Не удалось загрузить публикации.",
        "error"
      );
    }
  }

  function googleSheetsUrl(value) {
    try {
      const url = new URL(String(value));
      return url.protocol === "https:" && url.hostname === "docs.google.com"
        ? url.href
        : "";
    } catch (error) {
      return "";
    }
  }

  function showExportSuccess(url) {
    const link = createElement("a", "", "Открыть Google Sheets");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";

    exportResult.className = "status status-success";
    exportResult.replaceChildren(
      document.createTextNode("Готово. "),
      link
    );
    exportResult.hidden = false;
  }

  function showExportError(message) {
    exportResult.className = "status status-error";
    exportResult.textContent = message;
    exportResult.hidden = false;
  }

  async function exportSelectedRun() {
    if (selectedRunId === null || exportGoogleSheetsButton.disabled) {
      return;
    }

    const runId = selectedRunId;
    exportGoogleSheetsButton.disabled = true;
    exportGoogleSheetsButton.textContent = "Экспортируем…";
    exportResult.hidden = true;
    exportResult.replaceChildren();

    try {
      const response = await fetch(
        runsApiUrl +
          "/" +
          encodeURIComponent(String(runId)) +
          "/export/google-sheets",
        {
          method: "POST",
          headers: { Accept: "application/json" },
        }
      );
      const data = await readJson(response);

      if (!response.ok || !data || !data.success) {
        throw new Error(
          apiError(data, "Не удалось экспортировать результаты.")
        );
      }

      const url = googleSheetsUrl(data.url);
      if (!url) {
        throw new Error("Сервис экспорта не вернул корректную ссылку.");
      }

      showExportSuccess(url);
    } catch (error) {
      showExportError(
        error instanceof Error
          ? error.message
          : "Не удалось экспортировать результаты."
      );
    } finally {
      exportGoogleSheetsButton.disabled = false;
      exportGoogleSheetsButton.textContent =
        "Экспортировать в Google Sheets";
    }
  }

  function renderGroupTabs() {
    activeGroupId = tabs.renderGroupTabs(
      groupTabs,
      allGroups,
      activeGroupId,
      function (groupId) {
        activateGroup(groupId, "", "push");
      }
    );
    tabs.updateParentLinks(activeGroupId, selectedRunId);
  }

  function activateGroup(groupId, requestedRunId, historyMode) {
    activeGroupId = tabs.selectedGroupId(allGroups, groupId);
    visibleRuns = allRuns.filter(function (run) {
      return String(run.group_id || "") === activeGroupId;
    });

    const requestedRun = visibleRuns.find(function (run) {
      return String(run.id) === String(requestedRunId || "");
    });
    const requestedRunIndex = requestedRun
      ? visibleRuns.indexOf(requestedRun)
      : -1;
    runsExpanded = requestedRunIndex >= collapsedRunsLimit;
    const selectedRun = requestedRun || visibleRuns[0] || null;
    selectedRunId = selectedRun ? selectedRun.id : null;
    renderGroupTabs();
    renderRuns(visibleRuns);

    tabs.updateUrl(
      window.location.pathname,
      activeGroupId,
      selectedRun ? selectedRun.id : "",
      historyMode || "replace"
    );

    if (selectedRun) {
      loadPosts(selectedRun, "");
    } else {
      loadedPosts = [];
      postsSection.hidden = true;
      exportGoogleSheetsButton.hidden = true;
      setStatus("У выбранной группы пока нет запусков.", "info");
    }
  }

  async function fetchJson(url) {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
    });
    const data = await readJson(response);

    if (!response.ok || !data || !data.success) {
      throw new Error(apiError(data, "Не удалось загрузить данные."));
    }

    return data;
  }

  async function loadInterface() {
    setStatus("Загружаем запуски…", "info");

    try {
      const responses = await Promise.all([
        fetchJson(settingsApiUrl),
        fetchJson(runsApiUrl),
      ]);
      const settingsData = responses[0];
      const runsData = responses[1];
      const settingsGroups =
        settingsData.settings &&
        Array.isArray(settingsData.settings.groups)
          ? settingsData.settings.groups
          : [];
      allRuns = Array.isArray(runsData.runs) ? runsData.runs : [];
      allGroups = tabs.mergeGroups(settingsGroups, allRuns);

      const urlState = tabs.readUrlState(window.location.search);
      const requestedGroupExists = allGroups.some(function (group) {
        return group.id === urlState.groupId;
      });
      pendingSelectionNotice =
        urlState.groupId && !requestedGroupExists
          ? "Указанная группа не найдена. Выбрана первая доступная группа."
          : "";
      activateGroup(urlState.groupId, urlState.runId, "replace");

      if (!allGroups.length) {
        setStatus("Групп и запусков пока нет.", "info");
      }
    } catch (error) {
      allGroups = [];
      allRuns = [];
      visibleRuns = [];
      renderGroupTabs();
      renderRuns([]);
      setStatus(
        error instanceof Error
          ? error.message
          : "Не удалось загрузить запуски.",
        "error"
      );
    }
  }

  exportGoogleSheetsButton.addEventListener("click", exportSelectedRun);
  runsToggleButton.addEventListener("click", function () {
    runsExpanded = !runsExpanded;
    renderRuns(visibleRuns);
  });
  sortButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      sortState = resultsLogic.nextSortState(
        sortState,
        button.dataset.sortField
      );
      updateSortHeaders();
      renderPosts();
    });
  });
  updateSortHeaders();
  window.addEventListener("popstate", function () {
    const urlState = tabs.readUrlState(window.location.search);
    activateGroup(urlState.groupId, urlState.runId, "replace");
  });
  loadInterface();
})();
