"use strict";

(function () {
  const runsApiUrl = "/api/v1/results/runs";
  const resultsLogic = window.PostParserResults;
  const collapsedTextCharacters = 300;
  const collapsedTextLines = 6;

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
  const sortButtons = Array.from(
    document.querySelectorAll("[data-sort-field]")
  );

  let selectedRunId = null;
  let loadedPosts = [];
  let sortState = { field: null, direction: null };

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
      const link = createElement("a", "", "Открыть пост");
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

  function appendPostTextCell(row, value) {
    const cell = appendCell(row, "", "post-text");
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
            : "";
      button.setAttribute("aria-label", actionLabel);
      button.title = actionLabel;
    });
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
      appendPostTextCell(row, post.text);
      appendCell(row, String(post.post_type || "—"));
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

  async function loadPosts(runId, groupName) {
    selectedRunId = runId;
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
  loadRuns();
})();
