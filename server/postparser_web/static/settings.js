"use strict";

(function () {
  const apiUrl = "/api/v1/settings";

  const revisionValue = document.getElementById("revisionValue");
  const addGroupButton = document.getElementById("addGroupButton");
  const reloadButton = document.getElementById("reloadButton");
  const saveButton = document.getElementById("saveButton");
  const statusMessage = document.getElementById("statusMessage");
  const emptyState = document.getElementById("emptyState");
  const groupsContainer = document.getElementById("groupsContainer");

  let revision = 0;
  let groups = [];
  let requestInProgress = false;

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

  function createField(labelText, input) {
    const field = createElement("label", "field");
    const label = createElement("span", "field-label", labelText);
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
      onInput(input.value);
    });
    return input;
  }

  function createDateInput(value, onInput) {
    const input = createElement("input", "input");
    input.type = "date";
    input.value = value;
    input.addEventListener("input", function () {
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
    textarea.rows = 5;
    textarea.value = wordsToText(words);
    textarea.placeholder = placeholder;
    textarea.addEventListener("input", function () {
      onInput(textToWords(textarea.value));
    });
    return textarea;
  }

  function renderAdvertisingType(group, groupIndex, typeIndex) {
    const advertisingType = group.advertisingTypes[typeIndex];
    const card = createElement("article", "type-card");
    const header = createElement("div", "type-header");
    const title = createElement(
      "h4",
      "",
      "Тип рекламы " + (typeIndex + 1)
    );
    const deleteButton = createButton(
      "Удалить тип",
      "button button-danger button-small",
      function () {
        group.advertisingTypes.splice(typeIndex, 1);
        renderGroups();
      }
    );

    header.appendChild(title);
    header.appendChild(deleteButton);
    card.appendChild(header);

    card.appendChild(
      createField(
        "Название типа",
        createTextInput(
          advertisingType.type,
          "Например, прямая реклама",
          function (value) {
            groups[groupIndex].advertisingTypes[typeIndex].type = value;
          }
        )
      )
    );

    const wordsGrid = createElement("div", "words-grid");
    wordsGrid.appendChild(
      createField(
        "Ключевые слова постов",
        createWordsTextarea(
          advertisingType.postWords,
          "Одно слово или фраза на строке",
          function (value) {
            groups[groupIndex].advertisingTypes[typeIndex].postWords =
              value;
          }
        )
      )
    );
    wordsGrid.appendChild(
      createField(
        "Ключевые слова видео",
        createWordsTextarea(
          advertisingType.videoWords,
          "Одно слово или фраза на строке",
          function (value) {
            groups[groupIndex].advertisingTypes[typeIndex].videoWords =
              value;
          }
        )
      )
    );
    card.appendChild(wordsGrid);

    return card;
  }

  function renderGroup(group, groupIndex) {
    const card = createElement("article", "group-card");
    const header = createElement("div", "group-header");
    const title = createElement(
      "h2",
      "",
      group.name || "Группа " + (groupIndex + 1)
    );
    const deleteButton = createButton(
      "Удалить группу",
      "button button-danger",
      function () {
        groups.splice(groupIndex, 1);
        renderGroups();
        setStatus("Группа удалена из формы. Сохраните изменения.", "info");
      }
    );

    header.appendChild(title);
    header.appendChild(deleteButton);
    card.appendChild(header);

    const fieldsGrid = createElement("div", "fields-grid");
    fieldsGrid.appendChild(
      createField(
        "ID",
        createTextInput(group.id, "Уникальный ID", function (value) {
          groups[groupIndex].id = value;
        })
      )
    );
    fieldsGrid.appendChild(
      createField(
        "Название",
        createTextInput(group.name, "Название группы", function (value) {
          groups[groupIndex].name = value;
          title.textContent = value || "Группа " + (groupIndex + 1);
        })
      )
    );
    fieldsGrid.appendChild(
      createField(
        "Социальная сеть",
        createNetworkSelect(group.network, function (value) {
          groups[groupIndex].network = value;
        })
      )
    );
    fieldsGrid.appendChild(
      createField(
        "URL",
        createTextInput(group.url, "https://…", function (value) {
          groups[groupIndex].url = value;
        })
      )
    );
    fieldsGrid.appendChild(
      createField(
        "Дата начала",
        createDateInput(group.dateStart, function (value) {
          groups[groupIndex].dateStart = value;
        })
      )
    );
    fieldsGrid.appendChild(
      createField(
        "Дата окончания",
        createDateInput(group.dateEnd, function (value) {
          groups[groupIndex].dateEnd = value;
        })
      )
    );
    card.appendChild(fieldsGrid);

    const typesSection = createElement("section", "types-section");
    const typesHeader = createElement("div", "types-heading");
    typesHeader.appendChild(createElement("h3", "", "Типы рекламы"));
    typesHeader.appendChild(
      createButton(
        "Добавить тип рекламы",
        "button button-secondary button-small",
        function () {
          group.advertisingTypes.push({
            type: "",
            postWords: [],
            videoWords: [],
          });
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
      group.advertisingTypes.forEach(function (_, typeIndex) {
        typesSection.appendChild(
          renderAdvertisingType(group, groupIndex, typeIndex)
        );
      });
    }

    card.appendChild(typesSection);
    return card;
  }

  function renderGroups() {
    groupsContainer.replaceChildren();
    emptyState.hidden = groups.length !== 0;

    groups.forEach(function (group, groupIndex) {
      groupsContainer.appendChild(renderGroup(group, groupIndex));
    });
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

      revisionValue.textContent = String(revision);
      renderGroups();
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
            groups: groups,
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
    groups.push({
      id: createTemporaryId(),
      name: "",
      network: "vk",
      url: "",
      dateStart: "",
      dateEnd: "",
      advertisingTypes: [],
    });
    renderGroups();
    setStatus("Новая группа добавлена. Заполните поля.", "info");
  });

  reloadButton.addEventListener("click", loadSettings);
  saveButton.addEventListener("click", saveSettings);
  loadSettings();
})();
