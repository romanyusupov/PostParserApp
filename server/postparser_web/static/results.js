"use strict";

(function () {
  const runsApiUrl = "/api/v1/results/runs";

  const statusMessage = document.getElementById("statusMessage");
  const runsTableBody = document.getElementById("runsTableBody");
  const runsEmptyState = document.getElementById("runsEmptyState");
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

  let selectedRunId = null;

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
    const metric = Number(value);
    return Number.isFinite(metric) ? String(metric) : "0";
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

  function renderRuns(runs) {
    runsTableBody.replaceChildren();
    runsEmptyState.hidden = runs.length !== 0;

    if (runs.length === 0) {
      selectedRunId = null;
      postsSection.hidden = true;
      exportGoogleSheetsButton.hidden = true;
    }

    runs.forEach(function (run) {
      const row = createElement("tr");
      appendCell(row, String(run.group_name || "—"));
      appendCell(row, networkLabel(run.network));
      appendCell(row, formatDate(run.finished_at || run.started_at));
      appendCell(row, statusLabel(run.status));
      appendCell(row, formatMetric(run.count), "metric-cell");

      const actionCell = appendCell(row, "", "action-cell");
      const selectButton = createElement(
        "button",
        "button button-secondary button-small",
        "Открыть"
      );
      selectButton.type = "button";
      selectButton.addEventListener("click", function () {
        loadPosts(run.id, run.group_name);
      });
      actionCell.appendChild(selectButton);
      runsTableBody.appendChild(row);
    });
  }

  function renderPosts(posts) {
    postsTableBody.replaceChildren();
    postsEmptyState.hidden = posts.length !== 0;

    posts.forEach(function (post) {
      const row = createElement("tr");
      appendCell(row, formatDate(post.published_at));
      appendCell(row, String(post.text || ""), "post-text");
      appendCell(row, String(post.post_type || "—"));
      appendCell(row, formatMetric(post.views), "metric-cell");
      appendCell(row, formatMetric(post.likes), "metric-cell");
      appendCell(row, formatMetric(post.comments), "metric-cell");
      postsTableBody.appendChild(row);
    });
  }

  async function loadPosts(runId, groupName) {
    selectedRunId = runId;
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
      setStatus("Публикации загружены.", "success");
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

  async function loadRuns() {
    setStatus("Загружаем запуски…", "info");

    try {
      const response = await fetch(runsApiUrl, {
        headers: { Accept: "application/json" },
      });
      const data = await readJson(response);

      if (!response.ok || !data || !data.success) {
        throw new Error(apiError(data, "Не удалось загрузить запуски."));
      }

      const runs = Array.isArray(data.runs) ? data.runs : [];
      renderRuns(runs);
      setStatus(
        runs.length === 0 ? "Запусков пока нет." : "Запуски загружены.",
        runs.length === 0 ? "info" : "success"
      );
    } catch (error) {
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
  loadRuns();
})();
