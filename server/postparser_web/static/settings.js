"use strict";

(function () {
  const apiUrl = "/api/v1/settings";
  const parseApiUrl = "/api/v1/parse";
  const runsApiUrl = "/api/v1/runs/";
  const pollIntervalMilliseconds = 2000;
  const tabs = window.PostParserTabs;

  const revisionValue = document.getElementById("revisionValue");
  const addGroupButton = document.getElementById("addGroupButton");
  const reloadButton = document.getElementById("reloadButton");
  const saveButton = document.getElementById("saveButton");
  const statusMessage = document.getElementById("statusMessage");
  const emptyState = document.getElementById("emptyState");
  const groupsContainer = document.getElementById("groupsContainer");
  const groupTabs = document.getElementById("groupTabs");
  const parentTabList = document.getElementById("parentTabList");

  let revision = 0;
  let groups = [];
  let activeGroupId = "";
  let hasUnsavedChanges = false;
  let requestInProgress = false;
  const parseStates = new Map();

  tabs.setupParentTabs(parentTabList);

  function markDirty() {
    hasUnsavedChanges = true;
  }

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

  function createButton(text, className, handler) {
    const button = createElement("button", className, text);
    button.type = "button";
    button.addEventListener("click", handler);
    return button;
  }

  function createTemporaryId() {
    if (
      window.crypto &&
      typeof window.crypto.randomUUID === "function"
    ) {
      return "group_" + window.crypto.randomUUID();
    }

    return (
      "group_" +
      Date.now() +
      "_" +
      Math.random().toString(36).slice(2, 10)
    );
  }

  function setStatus(message, type) {
    statusMessage.textContent = message;
    statusMessage.className = "status";

    if (type) {
      statusMessage.classList.add("status-" + type);
    }
  }

  function setBusy(isBusy) {
    requestInProgress = isBusy;
    saveButton.disabled = isBusy;
    reloadButton.disabled = isBusy;
    addGroupButton.disabled = isBusy;

    saveButton.textContent = isBusy
      ? "Сохранение…"
      : "Сохранить настройки";
  }

  function normalizeLoadedGroup(group) {
    const source = group && typeof group === "object" ? group : {};

    return {
      id: String(source.id || ""),
      name: String(source.name || ""),
      network: ["vk", "telegram", "instagram"].includes(source.network)
        ? source.network
        : "vk",
      url: String(source.url || ""),
      dateStart: String(source.dateStart || ""),
      dateEnd: String(source.dateEnd || ""),
      advertisingTypes: Array.isArray(source.advertisingTypes)
        ? source.advertisingTypes.map(normalizeLoadedType)
        : [],
    };
  }

  function normalizeLoadedType(advertisingType) {
    const source =
      advertisingType && typeof advertisingType === "object"
        ? advertisingType
        : {};

    return {
      type: String(source.type || ""),
      postWords: Array.isArray(source.postWords)
        ? source.postWords.map(String)
        : [],
      videoWords: Array.isArray(source.videoWords)
        ? source.videoWords.map(String)
        : [],
    };
  }

  function createField(labelText, input, visuallyHiddenLabel) {
    const field = createElement("label", "field");
    const label = createElement("span", "field-label", labelText);
    if (visuallyHiddenLabel) {
      label.classList.add("visually-hidden");
    }
    field.appendChild(label);
    field.appendChild(input);
    return field;
  }

  function createTextInput(value, placeholder, onInput) {
    const input = createElement("input", "input");
    input.type = "text";
    input.value = value;
    input.placeholder = placeholder;
    input.addEventListener("input", function () {
      markDirty();
      onInput(input.value);
    });
    return input;
  }

  function createDateInput(value, onInput) {
    const input = createElement("input", "input");
    input.type = "date";
    input.value = value;
    input.addEventListener("input", function () {
      markDirty();
      onInput(input.value);
    });
    return input;
  }

  function createNetworkSelect(value, onInput) {
    const select = createElement("select", "input");
    const networks = [
      ["vk", "VK"],
      ["telegram", "Telegram"],
      ["instagram", "Instagram"],
    ];

    networks.forEach(function (network) {
      const option = createElement("option", "", network[1]);
      option.value = network[0];
      option.selected = network[0] === value;
      select.appendChild(option);
    });

    select.addEventListener("change", function () {
      markDirty();
      onInput(select.value);
    });

    return select;
  }

  function wordsToText(words) {
    return Array.isArray(words) ? words.join("\n") : "";
  }

  function textToWords(text) {
    return String(text || "")
      .split(/\r?\n/)
      .map(function (word) {
        return word.trim();
      })
      .filter(function (word) {
        return Boolean(word);
      });
  }

  function createWordsTextarea(words, placeholder, onInput) {
    const textarea = createElement("textarea", "textarea");
    textarea.rows = 2;
    textarea.value = wordsToText(words);
    textarea.placeholder = placeholder;
    textarea.addEventListener("input", function () {
      markDirty();
      onInput(textToWords(textarea.value));
    });
    return textarea;
  }

  function prepareGroupsForSave() {
    return groups.map(function (group) {
      return Object.assign({}, group, {
        advertisingTypes: group.advertisingTypes.map(
          function (advertisingType) {
            return Object.assign({}, advertisingType, {
              videoWords:
                group.network === "telegram"
                  ? []
                  : advertisingType.videoWords,
            });
          }
        ),
      });
    });
  }

  function renderAdvertisingType(group, groupIndex, typeIndex) {
    const advertisingType = group.advertisingTypes[typeIndex];
    const row = createElement("article", "type-row");
    const typeInput = createTextInput(
      advertisingType.type,
      "Например, прямая реклама",
      function (value) {
        groups[groupIndex].advertisingTypes[typeIndex].type = value;
      }
    );
    const postWords = createWordsTextarea(
      advertisingType.postWords,
      "Одно слово или фраза на строке",
      function (value) {
        groups[groupIndex].advertisingTypes[typeIndex].postWords = value;
      }
    );
    const showsVideoWords = ["vk", "instagram"].includes(group.network);
    const deleteButton = createButton(
      "×",
      "button button-danger type-row-delete",
      function () {
        group.advertisingTypes.splice(typeIndex, 1);
        markDirty();
        renderGroups();
      }
    );
    deleteButton.title = "Удалить тип рекламы " + (typeIndex + 1);
    deleteButton.setAttribute(
      "aria-label",
      "Удалить тип рекламы " + (typeIndex + 1)
    );
    typeInput.setAttribute("aria-label", "Название типа рекламы");
    postWords.setAttribute("aria-label", "Поиск в тексте поста");

    row.appendChild(
      createField("Название типа рекламы", typeInput, true)
    );
    row.appendChild(
      createField("Поиск в тексте поста", postWords, true)
    );

    if (showsVideoWords) {
      const videoWords = createWordsTextarea(
        advertisingType.videoWords,
        "Одно слово или фраза на строке",
        function (value) {
          groups[groupIndex].advertisingTypes[typeIndex].videoWords = value;
        }
      );
      videoWords.setAttribute(
        "aria-label",
        "Поиск в описании видео"
      );
      row.appendChild(
        createField(
          "Поиск в описании видео",
          videoWords,
          true
        )
      );
    } else {
      const unavailable = createElement(
        "div",
        "type-video-unavailable",
        "—"
      );
      unavailable.setAttribute(
        "aria-label",
        "Поиск в описании видео недоступен"
      );
      row.appendChild(unavailable);
    }

    row.appendChild(deleteButton);
    return row;
  }

  function renderGroup(group, groupIndex) {
    const card = createElement("article", "group-card");
    card.id = "groupPanel";
    card.setAttribute("role", "tabpanel");
    const activeTab = groupTabs.querySelector('[aria-selected="true"]');
    if (activeTab) {
      card.setAttribute("aria-labelledby", activeTab.id);
    }
    const header = createElement("div", "group-header");
    const title = createElement(
      "h2",
      "",
      group.name || "Группа " + (groupIndex + 1)
    );
    const headerActions = createElement("div", "toolbar-actions");
    const state = getParseState(group.id);
    const launchButton = createButton(
      state.busy ? "Запуск…" : "Запустить",
      "button button-primary",
      function () {
        launchParse(group.id);
      }
    );
    const deleteButton = createButton(
      "Удалить группу",
      "button button-danger",
      function () {
        const nextGroup = groups[groupIndex + 1] || groups[groupIndex - 1];
        groups.splice(groupIndex, 1);
        activeGroupId = nextGroup ? nextGroup.id : "";
        markDirty();
        tabs.updateUrl(
          window.location.pathname,
          activeGroupId,
          "",
          "replace"
        );
        renderGroups();
        setStatus("Группа удалена из формы. Сохраните изменения.", "info");
      }
    );
    launchButton.disabled = state.busy;

    header.appendChild(title);
    headerActions.appendChild(deleteButton);
    header.appendChild(headerActions);
    card.appendChild(header);

    const identityGrid = createElement(
      "div",
      "fields-grid identity-grid"
    );
    const idInput = createTextInput(group.id, "Уникальный ID", function () {});
    const idField = createField("ID", idInput);
    idInput.readOnly = true;
    idField.classList.add("id-field");
    identityGrid.appendChild(idField);
    identityGrid.appendChild(
      createField(
        "Название",
        createTextInput(group.name, "Название группы", function (value) {
          groups[groupIndex].name = value;
          title.textContent = value || "Группа " + (groupIndex + 1);
          renderGroupTabs();
        })
      )
    );
    identityGrid.appendChild(
      createField(
        "URL",
        createTextInput(group.url, "https://…", function (value) {
          groups[groupIndex].url = value;
        })
      )
    );
    card.appendChild(identityGrid);

    const scheduleGrid = createElement(
      "div",
      "fields-grid schedule-grid"
    );
    scheduleGrid.appendChild(
      createField(
        "Социальная сеть",
        createNetworkSelect(group.network, function (value) {
          groups[groupIndex].network = value;

          if (value === "telegram") {
            groups[groupIndex].advertisingTypes.forEach(
              function (advertisingType) {
                advertisingType.videoWords = [];
              }
            );
          }

          renderGroups();
        })
      )
    );
    scheduleGrid.appendChild(
      createField(
        "Дата начала",
        createDateInput(group.dateStart, function (value) {
          groups[groupIndex].dateStart = value;
        })
      )
    );
    scheduleGrid.appendChild(
      createField(
        "Дата окончания",
        createDateInput(group.dateEnd, function (value) {
          groups[groupIndex].dateEnd = value;
        })
      )
    );
    card.appendChild(scheduleGrid);

    const typesSection = createElement("section", "types-section");
    const typesHeader = createElement("div", "types-heading");
    typesHeader.appendChild(createElement("h3", "", "Типы рекламы"));
    typesHeader.appendChild(
      createButton(
        "+ Добавить тип",
        "button button-secondary button-small",
        function () {
          group.advertisingTypes.push({
            type: "",
            postWords: [],
            videoWords: [],
          });
          markDirty();
          renderGroups();
        }
      )
    );
    typesSection.appendChild(typesHeader);

    if (group.advertisingTypes.length === 0) {
      typesSection.appendChild(
        createElement(
          "p",
          "types-empty",
          "Типы рекламы пока не добавлены."
        )
      );
    } else {
      const columnsHeader = createElement(
        "div",
        "type-columns-header"
      );
      columnsHeader.appendChild(
        createElement("span", "", "Название типа рекламы")
      );
      columnsHeader.appendChild(
        createElement("span", "", "Поиск в тексте поста")
      );
      columnsHeader.appendChild(
        createElement("span", "", "Поиск в описании видео")
      );
      columnsHeader.appendChild(
        createElement("span", "visually-hidden", "Действия")
      );
      typesSection.appendChild(columnsHeader);
      group.advertisingTypes.forEach(function (_, typeIndex) {
        typesSection.appendChild(
          renderAdvertisingType(group, groupIndex, typeIndex)
        );
      });
    }

    card.appendChild(typesSection);

    const parsePanel = createElement("div", "parse-panel");
    const parseLabel = createElement(
      "strong",
      "",
      "Запуск парсинга выбранной группы"
    );
    parsePanel.appendChild(parseLabel);
    if (state.message) {
      const message = createElement("p", "status", state.message);
      message.classList.add("status-" + state.messageType);
      message.setAttribute("role", "status");
      parsePanel.appendChild(message);
    }
    parsePanel.appendChild(launchButton);
    card.appendChild(parsePanel);
    return card;
  }

  function getParseState(groupId) {
    if (!parseStates.has(groupId)) {
      parseStates.set(groupId, {
        busy: false,
        message: "",
        messageType: "info",
      });
    }

    return parseStates.get(groupId);
  }

  function getApiError(data, fallbackMessage) {
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

  function scheduleRunPoll(groupId, runId) {
    window.setTimeout(function () {
      pollRun(groupId, runId);
    }, pollIntervalMilliseconds);
  }

  async function pollRun(groupId, runId) {
    const state = getParseState(groupId);

    try {
      const response = await fetch(
        runsApiUrl + encodeURIComponent(String(runId)),
        { headers: { Accept: "application/json" } }
      );
      const data = await readJson(response);

      if (!response.ok || !data || !data.success || !data.run) {
        throw new Error(
          getApiError(data, "Не удалось получить статус запуска.")
        );
      }

      if (data.run.status === "running") {
        state.message = "Парсинг выполняется...";
        state.messageType = "info";
        renderGroups();
        scheduleRunPoll(groupId, runId);
        return;
      }

      state.busy = false;

      if (data.run.status === "completed") {
        state.message =
          "Готово. Найдено публикаций: " + Number(data.run.count || 0);
        state.messageType = "success";
      } else if (data.run.status === "failed") {
        state.message = "Ошибка запуска";
        state.messageType = "error";
      } else {
        throw new Error("Получен неизвестный статус запуска.");
      }
    } catch (error) {
      state.busy = false;
      state.message =
        error instanceof Error
          ? error.message
          : "Не удалось получить статус запуска.";
      state.messageType = "error";
    }

    renderGroups();
  }

  async function launchParse(groupId) {
    const state = getParseState(groupId);

    if (state.busy) {
      return;
    }

    state.busy = true;
    state.message = "Создаём запуск...";
    state.messageType = "info";
    renderGroups();

    try {
      const response = await fetch(parseApiUrl, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ groupId: groupId }),
      });
      const data = await readJson(response);

      if (!response.ok || !data || !data.success) {
        throw new Error(getApiError(data, "Не удалось создать запуск."));
      }

      state.message = "Запуск создан. runId: " + String(data.runId);
      state.messageType = "success";
      renderGroups();
      scheduleRunPoll(groupId, data.runId);
    } catch (error) {
      state.busy = false;
      state.message =
        error instanceof Error
          ? error.message
          : "Не удалось создать запуск.";
      state.messageType = "error";
      renderGroups();
    }
  }

  function renderGroupTabs() {
    activeGroupId = tabs.renderGroupTabs(
      groupTabs,
      groups,
      activeGroupId,
      function (groupId) {
        selectGroup(groupId, "push");
      }
    );
    tabs.updateParentLinks(activeGroupId, "");
  }

  function selectGroup(groupId, historyMode) {
    activeGroupId = tabs.selectedGroupId(groups, groupId);
    tabs.updateUrl(
      window.location.pathname,
      activeGroupId,
      "",
      historyMode || "replace"
    );
    renderGroups();
  }

  function renderGroups() {
    groupsContainer.replaceChildren();
    emptyState.hidden = groups.length !== 0;
    renderGroupTabs();

    const groupIndex = groups.findIndex(function (group) {
      return group.id === activeGroupId;
    });

    if (groupIndex >= 0) {
      groupsContainer.appendChild(
        renderGroup(groups[groupIndex], groupIndex)
      );
    }
  }

  async function loadSettings() {
    if (requestInProgress) {
      return;
    }

    setBusy(true);
    setStatus("Загружаем настройки…", "info");

    try {
      const response = await fetch(apiUrl, {
        headers: { Accept: "application/json" },
      });

      if (!response.ok) {
        throw new Error("load_failed");
      }

      const data = await response.json();
      revision = Number.isInteger(data.revision) ? data.revision : 0;
      groups =
        data.settings && Array.isArray(data.settings.groups)
          ? data.settings.groups.map(normalizeLoadedGroup)
          : [];
      activeGroupId = tabs.selectedGroupId(
        groups,
        tabs.readUrlState(window.location.search).groupId
      );
      hasUnsavedChanges = false;

      revisionValue.textContent = String(revision);
      renderGroups();
      tabs.updateUrl(
        window.location.pathname,
        activeGroupId,
        "",
        "replace"
      );
      setStatus("Настройки загружены.", "success");
    } catch (error) {
      setStatus(
        "Не удалось загрузить настройки. Попробуйте ещё раз.",
        "error"
      );
    } finally {
      setBusy(false);
    }
  }

  async function saveSettings() {
    if (requestInProgress) {
      return;
    }

    setBusy(true);
    setStatus("Сохраняем настройки…", "info");

    try {
      const response = await fetch(apiUrl, {
        method: "PUT",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          revision: revision,
          settings: {
            groups: prepareGroupsForSave(),
          },
        }),
      });

      let data = null;
      try {
        data = await response.json();
      } catch (error) {
        data = null;
      }

      if (response.status === 409) {
        setStatus(
          "Настройки были изменены в другом окне. Перезагрузите данные.",
          "error"
        );
        return;
      }

      if (response.status === 400) {
        setStatus(
          data && data.error
            ? data.error
            : "Проверьте заполнение настроек.",
          "error"
        );
        return;
      }

      if (!response.ok || !data) {
        throw new Error("save_failed");
      }

      revision = data.revision;
      groups = data.settings.groups.map(normalizeLoadedGroup);
      activeGroupId = tabs.selectedGroupId(groups, activeGroupId);
      hasUnsavedChanges = false;
      revisionValue.textContent = String(revision);
      renderGroups();
      setStatus("Настройки успешно сохранены.", "success");
    } catch (error) {
      setStatus(
        "Не удалось сохранить настройки. Попробуйте ещё раз.",
        "error"
      );
    } finally {
      setBusy(false);
    }
  }

  addGroupButton.addEventListener("click", function () {
    const newGroup = {
      id: createTemporaryId(),
      name: "",
      network: "vk",
      url: "",
      dateStart: "",
      dateEnd: "",
      advertisingTypes: [],
    };
    groups.push(newGroup);
    activeGroupId = newGroup.id;
    markDirty();
    tabs.updateUrl(
      window.location.pathname,
      activeGroupId,
      "",
      "push"
    );
    renderGroups();
    setStatus("Новая группа добавлена. Заполните поля.", "info");
  });

  reloadButton.addEventListener("click", function () {
    if (
      !hasUnsavedChanges ||
      window.confirm("Несохранённые изменения будут потеряны. Перезагрузить?")
    ) {
      loadSettings();
    }
  });
  saveButton.addEventListener("click", saveSettings);
  window.addEventListener("popstate", function () {
    activeGroupId = tabs.selectedGroupId(
      groups,
      tabs.readUrlState(window.location.search).groupId
    );
    renderGroups();
  });
  window.addEventListener("beforeunload", function (event) {
    if (!hasUnsavedChanges) {
      return;
    }
    event.preventDefault();
    event.returnValue = "";
  });
  loadSettings();
})();
