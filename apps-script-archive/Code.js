const VK_API_VERSION = '5.199';

const SETTINGS_PROPERTY = 'VK_TG_MULTI_GROUP_PARSER_SETTINGS';

const OLD_MULTI_SETTINGS_PROPERTY = 'VK_MULTI_GROUP_PARSER_SETTINGS';

const LEGACY_SETTINGS_PROPERTY = 'VK_PARSER_SETTINGS';

const WALL_PAGE_SIZE = 100;
const VIDEO_BATCH_SIZE = 200;
const MAX_POSTS_TO_SCAN = 50000;

/* =========================================================
 * ВЕБ-ПРИЛОЖЕНИЕ
 * ========================================================= */

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Settings').setTitle('Настройки анализа публикаций');
}

/**
 * Возвращает сохранённые настройки
 * и ссылку на Google Таблицу.
 */
function getParserSettings() {
  return addRuntimeInformation(getStoredParserSettings());
}

/**
 * Добавляет данные для интерфейса.
 */
function addRuntimeInformation(settings) {
  const result = JSON.parse(JSON.stringify(settings));

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();

  result.spreadsheetUrl = spreadsheet ? spreadsheet.getUrl() : '';

  result.spreadsheetName = spreadsheet ? spreadsheet.getName() : '';

  return result;
}

/**
 * Сохраняет настройки всех групп.
 */
function saveParserSettings(settings) {
  validateParserSettings(settings);

  const prepared = prepareParserSettings(settings);

  prepared.savedAt = new Date().toISOString();

  PropertiesService.getScriptProperties().setProperty(SETTINGS_PROPERTY, JSON.stringify(prepared));

  return {
    success: true,
    settings: addRuntimeInformation(prepared),
  };
}

/**
 * Читает сохранённые настройки.
 */
function getStoredParserSettings() {
  const properties = PropertiesService.getScriptProperties();

  const currentJson = properties.getProperty(SETTINGS_PROPERTY);

  if (currentJson) {
    try {
      return prepareParserSettings(JSON.parse(currentJson));
    } catch (error) {
      Logger.log('Ошибка чтения настроек: ' + error.message);
    }
  }

  const migrated = migratePreviousSettings();

  if (migrated) {
    return migrated;
  }

  return getDefaultParserSettings();
}

/**
 * Переносит настройки из предыдущих версий.
 */
function migratePreviousSettings() {
  const properties = PropertiesService.getScriptProperties();

  const multiJson = properties.getProperty(OLD_MULTI_SETTINGS_PROPERTY);

  if (multiJson) {
    try {
      const source = JSON.parse(multiJson);

      const prepared = prepareParserSettings({
        groups: (source.groups || []).map(function (group) {
          return Object.assign({}, group, {
            network: group.network || 'vk',
          });
        }),
      });

      properties.setProperty(SETTINGS_PROPERTY, JSON.stringify(prepared));

      return prepared;
    } catch (error) {
      Logger.log('Ошибка переноса многогрупповых настроек: ' + error.message);
    }
  }

  const legacyJson = properties.getProperty(LEGACY_SETTINGS_PROPERTY);

  if (!legacyJson) {
    return null;
  }

  try {
    const legacy = JSON.parse(legacyJson);

    const prepared = prepareParserSettings({
      groups: [
        {
          id: 'group_1',
          name: 'Олег Торсунов VK',
          network: 'vk',
          url: 'https://vk.ru/og_torsunov',

          dateStart: legacy.dateStart || '',

          dateEnd: legacy.dateEnd || '',

          advertisingTypes: Array.isArray(legacy.advertisingTypes)
            ? legacy.advertisingTypes
            : getDefaultAdvertisingTypes(),
        },
      ],
    });

    properties.setProperty(SETTINGS_PROPERTY, JSON.stringify(prepared));

    return prepared;
  } catch (error) {
    Logger.log('Ошибка переноса старых настроек: ' + error.message);

    return null;
  }
}

/**
 * Подготавливает настройки к работе.
 */
function prepareParserSettings(settings) {
  const source = settings || {};

  const sourceGroups = Array.isArray(source.groups) ? source.groups : [];

  return {
    groups: sourceGroups.map(function (group, index) {
      return prepareGroupSettings(group, index);
    }),

    savedAt: String(source.savedAt || ''),
  };
}

/**
 * Подготавливает настройки одной группы.
 */
function prepareGroupSettings(group, index) {
  const source = group || {};

  const sourceTypes = Array.isArray(source.advertisingTypes) ? source.advertisingTypes : [];

  return {
    id: normalizeGroupInternalId(source.id, index),

    name: String(source.name || 'Группа ' + (index + 1))
      .trim()
      .slice(0, 100),

    network: normalizeNetwork(source.network),

    url: String(source.url || '').trim(),

    dateStart: normalizeDateValue(source.dateStart),

    dateEnd: normalizeDateValue(source.dateEnd),

    advertisingTypes: sourceTypes.map(function (item) {
      return {
        type: String(item && item.type ? item.type : '').trim(),

        postWords: normalizeWordsArray(item ? item.postWords : []),

        videoWords: normalizeWordsArray(item ? item.videoWords : []),
      };
    }),
  };
}

/**
 * Приводит название социальной сети
 * к внутреннему значению.
 */
function normalizeNetwork(value) {
  const network = String(value || '')
    .trim()
    .toLowerCase();

  if (network === 'telegram' || network === 'tg') {
    return 'telegram';
  }

  if (network === 'instagram' || network === 'insta' || network === 'ig') {
    return 'instagram';
  }

  return 'vk';
}

/**
 * Создаёт внутренний ID группы.
 */
function normalizeGroupInternalId(value, index) {
  const cleaned = String(value || '')
    .trim()
    .replace(/[^a-zA-Z0-9_-]/g, '');

  if (cleaned) {
    return cleaned;
  }

  return 'group_' + Date.now() + '_' + index + '_' + Math.random().toString(36).slice(2, 9);
}

/**
 * Настройки по умолчанию.
 */
function getDefaultParserSettings() {
  return {
    groups: [
      {
        id: 'group_1',
        name: 'Олег Торсунов VK',
        network: 'vk',

        url: 'https://vk.ru/og_torsunov',

        dateStart: '',
        dateEnd: '',

        advertisingTypes: getDefaultAdvertisingTypes(),
      },

      {
        id: 'group_2',
        name: 'Олег Торсунов Telegram',
        network: 'telegram',

        url: 'https://t.me/olegtorsunovofficial',

        dateStart: '',
        dateEnd: '',

        advertisingTypes: getDefaultAdvertisingTypes(),
      },

      {
        id: 'group_3',
        name: 'Проактивум Instagram',
        network: 'instagram',

        url: 'https://www.instagram.com/proactivum/',

        dateStart: '',
        dateEnd: '',

        advertisingTypes: getDefaultAdvertisingTypes(),
      },
    ],

    savedAt: '',
  };
}

/**
 * Начальные типы рекламы.
 */
function getDefaultAdvertisingTypes() {
  return [
    {
      type: 'Стройность.Гайд',

      postWords: ['слово стройность'],

      videoWords: ['стройность'],
    },

    {
      type: 'Деталь.Уважение к М',

      postWords: ['слово деталь'],

      videoWords: ['деталь'],
    },

    {
      type: 'Шаг.Нежность к Ж',

      postWords: ['слово шаг'],

      videoWords: ['шаг'],
    },

    {
      type: 'Тест.Тест нехваток',

      postWords: ['слово тест'],

      videoWords: ['тест'],
    },

    {
      type: 'Любовь.Истории',

      postWords: ['слово любовь'],

      videoWords: ['любовь'],
    },

    {
      type: 'Видео',

      postWords: ['слово видео'],

      videoWords: ['видео'],
    },

    {
      type: 'Прямая реклама',

      postWords: ['clck'],

      videoWords: [],
    },
  ];
}

/* =========================================================
 * ПРОВЕРКА НАСТРОЕК
 * ========================================================= */

function validateParserSettings(settings) {
  if (!settings || typeof settings !== 'object') {
    throw new Error('Настройки имеют неправильный формат.');
  }

  if (!Array.isArray(settings.groups)) {
    throw new Error('Не найден список групп.');
  }

  if (settings.groups.length === 0) {
    throw new Error('Добавьте хотя бы одну группу.');
  }

  const usedGroupNames = {};

  settings.groups.forEach(function (group, index) {
    validateGroupSettings(group, index, usedGroupNames);
  });
}

function validateGroupSettings(group, groupIndex, usedGroupNames) {
  if (!group) {
    throw new Error('Не найдены настройки группы №' + (groupIndex + 1) + '.');
  }

  const name = String(group.name || '').trim();

  if (!name) {
    throw new Error('Введите название группы №' + (groupIndex + 1) + '.');
  }

  const normalizedName = normalizeForSearch(name);

  if (usedGroupNames[normalizedName]) {
    throw new Error('Название группы «' + name + '» повторяется.');
  }

  usedGroupNames[normalizedName] = true;

  const network = normalizeNetwork(group.network);

  const url = String(group.url || '').trim();

  if (!url) {
    throw new Error('Введите URL для группы «' + name + '».');
  }

  if (network === 'vk' && !isVkUrlOrIdentifier(url)) {
    throw new Error('Для группы «' + name + '» указан некорректный адрес ВКонтакте.');
  }

  if (network === 'telegram' && !isTelegramUrlOrIdentifier(url)) {
    throw new Error('Для группы «' + name + '» указан некорректный адрес Telegram.');
  }

  if (network === 'instagram' && !isInstagramUrlOrIdentifier(url)) {
    throw new Error('Для группы «' + name + '» указан некорректный адрес Instagram.');
  }

  const dateStart = normalizeDateValue(group.dateStart);

  const dateEnd = normalizeDateValue(group.dateEnd);

  if (dateStart && dateEnd && dateStart > dateEnd) {
    throw new Error('В группе «' + name + '» дата начала не может быть позже даты окончания.');
  }

  if ((network === 'telegram' || network === 'instagram') && (!dateStart || !dateEnd)) {
    throw new Error('Для группы «' + name + '» укажите дату начала и дату окончания.');
  }

  if (!Array.isArray(group.advertisingTypes)) {
    throw new Error('В группе «' + name + '» не найден список типов рекламы.');
  }

  const usedTypes = {};

  group.advertisingTypes.forEach(function (type, typeIndex) {
    const typeName = String(type && type.type ? type.type : '').trim();

    if (!typeName) {
      throw new Error(
        'Введите название типа рекламы в группе «' + name + '», строка ' + (typeIndex + 1) + '.',
      );
    }

    const normalizedType = normalizeForSearch(typeName);

    if (usedTypes[normalizedType]) {
      throw new Error('В группе «' + name + '» повторяется тип рекламы «' + typeName + '».');
    }

    usedTypes[normalizedType] = true;
  });
}

function isVkUrlOrIdentifier(value) {
  const text = String(value || '').trim();

  return (
    /^https?:\/\/(?:www\.)?(?:vk\.com|vk\.ru)\//i.test(text) ||
    /^-?\d+$/.test(text) ||
    /^(?:public|club|event)\d+$/i.test(text) ||
    /^[a-zA-Z0-9_.-]+$/.test(text)
  );
}

function isTelegramUrlOrIdentifier(value) {
  const text = String(value || '').trim();

  return (
    /^https?:\/\/(?:www\.)?(?:t\.me|telegram\.me)\//i.test(text) ||
    /^@[a-zA-Z0-9_]+$/.test(text) ||
    /^[a-zA-Z0-9_]+$/.test(text)
  );
}

function isInstagramUrlOrIdentifier(value) {
  const text = String(value || '').trim();

  return (
    /^https?:\/\/(?:www\.)?instagram\.com\/[a-zA-Z0-9._]+\/?(?:[?#].*)?$/i.test(text) ||
    /^@[a-zA-Z0-9._]+$/.test(text) ||
    /^[a-zA-Z0-9._]+$/.test(text)
  );
}

function normalizeDateValue(value) {
  const text = String(value || '').trim();

  if (!text) {
    return '';
  }

  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    throw new Error('Дата должна иметь формат YYYY-MM-DD.');
  }

  return text;
}

function normalizeWordsArray(value) {
  let words;

  if (Array.isArray(value)) {
    words = value;
  } else {
    words = String(value || '').split(',');
  }

  const result = [];
  const used = {};

  words.forEach(function (word) {
    const cleaned = String(word || '')
      .trim()
      .replace(/\s+/g, ' ');

    if (!cleaned) {
      return;
    }

    const normalized = normalizeForSearch(cleaned);

    if (!normalized || used[normalized]) {
      return;
    }

    used[normalized] = true;
    result.push(cleaned);
  });

  return result;
}

/* =========================================================
 * ЗАПУСК АКТИВНОЙ ГРУППЫ
 * ========================================================= */

/**
 * Запускает активную группу со страницы Settings.
 */
function parseGroupBySettings(groupInternalId) {
  const settings = getStoredParserSettings();

  const group = settings.groups.find(function (item) {
    return item.id === String(groupInternalId || '');
  });

  if (!group) {
    throw new Error('Выбранная группа не найдена в сохранённых настройках.');
  }

  validateParserSettings({
    groups: [group],
  });

  if (group.network === 'telegram') {
    return parseTelegramGroup(group);
  }

  if (group.network === 'instagram') {
    return parseInstagramGroup(group);
  }

  return parseVkGroup(group);
}

/**
 * Совместимость со старой функцией.
 */
function parseVkGroupBySettings(groupInternalId) {
  return parseGroupBySettings(groupInternalId);
}

/**
 * Запускает первую группу.
 */
function parseVkPostsBySettings() {
  const settings = getStoredParserSettings();

  if (!settings.groups || settings.groups.length === 0) {
    throw new Error('В настройках нет групп.');
  }

  return parseGroupBySettings(settings.groups[0].id);
}

/* =========================================================
 * TELEGRAM
 * ========================================================= */

/**
 * Вызывает Telegram API
 * и записывает результат в таблицу.
 */
function parseTelegramGroup(group) {
  const properties = PropertiesService.getScriptProperties();

  const apiUrl = String(properties.getProperty('TELEGRAM_API_URL') || '')
    .trim()
    .replace(/\/+$/, '');

  const apiKey = String(properties.getProperty('TELEGRAM_API_KEY') || '').trim();

  if (!apiUrl) {
    throw new Error('В свойствах скрипта не задан TELEGRAM_API_URL.');
  }

  if (!apiKey) {
    throw new Error('В свойствах скрипта не задан TELEGRAM_API_KEY.');
  }

  const payload = {
    channel_url: group.url,
    date_start: group.dateStart,
    date_end: group.dateEnd,

    advertising_types: group.advertisingTypes,
  };

  const response = UrlFetchApp.fetch(apiUrl + '/parse', {
    method: 'post',

    contentType: 'application/json',

    headers: {
      'X-API-Key': apiKey,
    },

    payload: JSON.stringify(payload),

    muteHttpExceptions: true,
  });

  const statusCode = response.getResponseCode();

  const responseText = response.getContentText();

  let data;

  try {
    data = JSON.parse(responseText);
  } catch (error) {
    throw new Error(
      'Telegram API вернул некорректный ответ. HTTP ' +
        statusCode +
        ': ' +
        responseText.slice(0, 500),
    );
  }

  if (statusCode < 200 || statusCode >= 300 || !data.success) {
    throw new Error('Ошибка Telegram API: ' + String(data.error || 'HTTP ' + statusCode));
  }

  const posts = Array.isArray(data.posts) ? data.posts : [];

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();

  const sheetName = sanitizeSheetName(group.name);

  let sheet = spreadsheet.getSheetByName(sheetName);

  if (!sheet) {
    sheet = spreadsheet.insertSheet(sheetName);
  }

  sheet.clear();

  const headers = [
    'Ссылка на пост',
    'дата',
    'текст поста',
    'картинка',
    'просмотров',
    'реакций',
    'комментариев',
    'тип поста',
    'тип рекламы',
  ];

  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);

  const rows = posts.map(function (post) {
    return [
      String(post.post_url || ''),

      parseTelegramDate(post.date),

      cleanText(post.text || ''),

      String(post.image_url || ''),

      Number(post.views || 0),

      Number(post.reactions || 0),

      Number(post.comments || 0),

      String(post.post_type || ''),

      String(post.advertising_type || ''),
    ];
  });

  if (rows.length > 0) {
    sheet.getRange(2, 1, rows.length, headers.length).setValues(rows);

    rows.forEach(function (row, index) {
      const imageUrl = row[3];

      if (!imageUrl) {
        return;
      }

      setImageFormula(sheet.getRange(index + 2, 4), imageUrl);
    });
  }

  formatTelegramSheet(sheet, rows.length);

  Logger.log(
    'Парсинг Telegram-группы «' + group.name + '» завершён. Найдено публикаций: ' + rows.length,
  );

  return {
    success: true,
    network: 'telegram',
    groupId: group.id,
    groupName: group.name,
    sheetName: sheetName,
    postsCount: rows.length,

    spreadsheetUrl: spreadsheet.getUrl(),

    message: 'Парсинг Telegram завершён. Найдено публикаций: ' + rows.length,
  };
}

/**
 * Надёжно преобразует дату Telegram
 * в объект Date для Google Таблицы.
 *
 * Поддерживает:
 * 2026-07-29T15:30:45+00:00
 * 2026-07-29T15:30:45.123456+00:00
 * 2026-07-29T15:30:45Z
 * 2026-07-29 15:30:45+00:00
 */
function parseTelegramDate(value) {
  let text = String(value || '').trim();

  if (!text) {
    return '';
  }

  /*
   * Приводим разделитель даты и времени
   * к стандартному символу T.
   */
  text = text.replace(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})/, '$1T$2');

  /*
   * Python может возвращать микросекунды:
   * .123456
   *
   * JavaScript стабильно работает
   * с миллисекундами:
   * .123
   */
  text = text.replace(/\.(\d{3})\d+(?=[+-]\d{2}:\d{2}$|Z$)/, '.$1');

  /*
   * UTC +00:00 заменяем на Z.
   */
  text = text.replace(/\+00:00$/, 'Z');

  let date = new Date(text);

  if (!isNaN(date.getTime())) {
    return date;
  }

  /*
   * Резервная ручная обработка,
   * если стандартный парсер не справился.
   */
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})/);

  if (!match) {
    Logger.log('Не удалось распознать дату Telegram: ' + String(value));

    return '';
  }

  date = new Date(
    Date.UTC(
      Number(match[1]),
      Number(match[2]) - 1,
      Number(match[3]),
      Number(match[4]),
      Number(match[5]),
      Number(match[6]),
    ),
  );

  if (isNaN(date.getTime())) {
    Logger.log('Получена некорректная дата Telegram: ' + String(value));

    return '';
  }

  return date;
}

/* =========================================================
 * INSTAGRAM
 * ========================================================= */

/**
 * Вызывает Instagram API
 * и записывает результат в таблицу.
 */
function parseInstagramGroup(group) {
  const properties = PropertiesService.getScriptProperties();

  const apiUrl = String(
    properties.getProperty('INSTAGRAM_API_URL') || properties.getProperty('TELEGRAM_API_URL') || '',
  )
    .trim()
    .replace(/\/+$/, '');

  const apiKey = String(
    properties.getProperty('INSTAGRAM_API_KEY') || properties.getProperty('TELEGRAM_API_KEY') || '',
  ).trim();

  if (!apiUrl) {
    throw new Error('В свойствах скрипта не задан INSTAGRAM_API_URL или TELEGRAM_API_URL.');
  }

  if (!apiKey) {
    throw new Error('В свойствах скрипта не задан INSTAGRAM_API_KEY или TELEGRAM_API_KEY.');
  }

  const payload = {
    account_url: group.url,
    date_start: group.dateStart,
    date_end: group.dateEnd,

    advertising_types: group.advertisingTypes,
  };

  const response = UrlFetchApp.fetch(apiUrl + '/instagram/parse', {
    method: 'post',

    contentType: 'application/json',

    headers: {
      'X-API-Key': apiKey,
    },

    payload: JSON.stringify(payload),

    muteHttpExceptions: true,
  });

  const statusCode = response.getResponseCode();

  const responseText = response.getContentText();

  let data;

  try {
    data = JSON.parse(responseText);
  } catch (error) {
    throw new Error(
      'Instagram API вернул некорректный ответ. HTTP ' +
        statusCode +
        ': ' +
        responseText.slice(0, 500),
    );
  }

  if (statusCode < 200 || statusCode >= 300 || !data.success) {
    throw new Error('Ошибка Instagram API: ' + String(data.error || 'HTTP ' + statusCode));
  }

  const posts = Array.isArray(data.posts) ? data.posts : [];

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();

  const sheetName = sanitizeSheetName(group.name);

  let sheet = spreadsheet.getSheetByName(sheetName);

  if (!sheet) {
    sheet = spreadsheet.insertSheet(sheetName);
  }

  sheet.clear();

  const headers = [
    'Ссылка на пост',
    'дата',
    'текст поста',
    'картинка',
    'просмотров',
    'лайков',
    'комментариев',
    'тип поста',
    'тип рекламы',
  ];

  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);

  const rows = posts.map(function (post) {
    return [
      String(post.post_url || ''),

      parseInstagramDate(post.date),

      cleanText(post.text || ''),

      String(post.image_url || ''),

      Number(post.views || 0),

      Number(typeof post.likes !== 'undefined' ? post.likes : post.reactions || 0),

      Number(post.comments || 0),

      String(post.post_type || ''),

      String(post.advertising_type || ''),
    ];
  });

  if (rows.length > 0) {
    sheet.getRange(2, 1, rows.length, headers.length).setValues(rows);

    rows.forEach(function (row, index) {
      const imageUrl = row[3];

      if (!imageUrl) {
        return;
      }

      setImageFormula(sheet.getRange(index + 2, 4), imageUrl);
    });
  }

  formatInstagramSheet(sheet, rows.length);

  Logger.log(
    'Парсинг Instagram-группы «' + group.name + '» завершён. Найдено публикаций: ' + rows.length,
  );

  return {
    success: true,
    network: 'instagram',
    groupId: group.id,
    groupName: group.name,
    accountId: String(data.account_id || ''),
    accountUsername: String(data.account_username || ''),
    sheetName: sheetName,
    postsCount: rows.length,

    spreadsheetUrl: spreadsheet.getUrl(),

    message: 'Парсинг Instagram завершён. Найдено публикаций: ' + rows.length,
  };
}

/**
 * Дата Instagram приходит в том же ISO-формате,
 * что и дата Telegram.
 */
function parseInstagramDate(value) {
  return parseTelegramDate(value);
}

/* =========================================================
 * ВКОНТАКТЕ
 * ========================================================= */

function parseVkGroup(group) {
  const token = getVkToken();

  const community = resolveVkCommunity(group.url, token);

  const dateRange = getParsingDateRange(group);

  const posts = getVkWallPostsForPeriod(community.ownerId, token, dateRange);

  const videoDescriptions = getVideoDescriptionsMap(posts, token);

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();

  const sheetName = sanitizeSheetName(group.name);

  let sheet = spreadsheet.getSheetByName(sheetName);

  if (!sheet) {
    sheet = spreadsheet.insertSheet(sheetName);
  }

  sheet.clear();

  const headers = [
    'Ссылка на пост',
    'дата',
    'текст поста',
    'картинка',
    'просмотров',
    'лайков',
    'комментариев',
    'тип поста',
    'описание видео',
    'тип рекламы',
  ];

  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);

  const rows = posts.map(function (post) {
    const postUrl = 'https://vk.ru/wall' + post.owner_id + '_' + post.id;

    const postDate = new Date(Number(post.date || 0) * 1000);

    const postText = cleanText(post.text || '');

    const videoDescription = getPostVideoDescription(post, videoDescriptions);

    return [
      postUrl,
      postDate,
      postText,
      getPostImageUrl(post),
      getCounterValue(post.views),
      getCounterValue(post.likes),
      getCounterValue(post.comments),
      getPostType(post),
      videoDescription,

      getAdvertisingTypeFromSettings(postText, videoDescription, group.advertisingTypes),
    ];
  });

  if (rows.length > 0) {
    sheet.getRange(2, 1, rows.length, headers.length).setValues(rows);

    rows.forEach(function (row, index) {
      const imageUrl = row[3];

      if (!imageUrl) {
        return;
      }

      setImageFormula(sheet.getRange(index + 2, 4), imageUrl);
    });
  }

  formatVkSheet(sheet, rows.length);

  Logger.log('Парсинг VK-группы «' + group.name + '» завершён. Найдено публикаций: ' + rows.length);

  return {
    success: true,
    network: 'vk',
    groupId: group.id,
    groupName: group.name,
    communityId: community.objectId,
    sheetName: sheetName,
    postsCount: rows.length,

    spreadsheetUrl: spreadsheet.getUrl(),

    message: 'Парсинг ВКонтакте завершён. Найдено публикаций: ' + rows.length,
  };
}

/* =========================================================
 * VK: ОПРЕДЕЛЕНИЕ СООБЩЕСТВА
 * ========================================================= */

function resolveVkCommunity(inputUrl, token) {
  const source = String(inputUrl || '').trim();

  if (!source) {
    throw new Error('URL сообщества не указан.');
  }

  const screenName = extractVkScreenName(source);

  if (/^-\d+$/.test(screenName)) {
    const objectId = Math.abs(Number(screenName));

    return {
      objectId: objectId,
      ownerId: -objectId,
    };
  }

  const numericMatch = screenName.match(/^(?:public|club|event)(\d+)$/i);

  if (numericMatch) {
    const objectId = Number(numericMatch[1]);

    return {
      objectId: objectId,
      ownerId: -objectId,
    };
  }

  const response = callVkApi(
    'utils.resolveScreenName',
    {
      screen_name: screenName,
    },
    token,
  );

  if (!response || !response.object_id) {
    throw new Error('Не удалось определить сообщество по адресу: ' + source);
  }

  const allowedTypes = ['group', 'page', 'event'];

  if (response.type && allowedTypes.indexOf(response.type) === -1) {
    throw new Error('Указанная ссылка ведёт не на сообщество VK.');
  }

  const objectId = Number(response.object_id);

  return {
    objectId: objectId,
    ownerId: -Math.abs(objectId),
  };
}

function extractVkScreenName(input) {
  let value = String(input || '').trim();

  value = value
    .replace(/^https?:\/\/(www\.)?/i, '')
    .replace(/^m\./i, '')
    .replace(/^vk\.com\//i, '')
    .replace(/^vk\.ru\//i, '')
    .replace(/^vkontakte\.ru\//i, '');

  value = value.split(/[?#]/)[0];

  value = value.replace(/^\/+|\/+$/g, '');

  const wallMatch = value.match(/^wall(-?\d+)(?:_\d+)?$/i);

  if (wallMatch) {
    return wallMatch[1];
  }

  value = value.split('/')[0];

  if (!value) {
    throw new Error('Не удалось определить короткое имя сообщества.');
  }

  return value;
}

/* =========================================================
 * VK: ДАТЫ И ПОСТЫ
 * ========================================================= */

function getParsingDateRange(group) {
  const timeZone = Session.getScriptTimeZone();

  let startTimestamp = null;
  let endTimestamp = null;

  if (group.dateStart) {
    const startDate = Utilities.parseDate(
      group.dateStart + ' 00:00:00',
      timeZone,
      'yyyy-MM-dd HH:mm:ss',
    );

    startTimestamp = Math.floor(startDate.getTime() / 1000);
  }

  if (group.dateEnd) {
    const endDate = Utilities.parseDate(
      group.dateEnd + ' 23:59:59',
      timeZone,
      'yyyy-MM-dd HH:mm:ss',
    );

    endTimestamp = Math.floor(endDate.getTime() / 1000);
  }

  return {
    startTimestamp: startTimestamp,

    endTimestamp: endTimestamp,
  };
}

function getVkWallPostsForPeriod(ownerId, token, dateRange) {
  const hasStartDate = dateRange.startTimestamp !== null;

  const hasEndDate = dateRange.endTimestamp !== null;

  if (!hasStartDate && !hasEndDate) {
    const response = callVkApi(
      'wall.get',
      {
        owner_id: ownerId,
        count: WALL_PAGE_SIZE,
        offset: 0,
        filter: 'owner',
      },
      token,
    );

    if (!response || !Array.isArray(response.items)) {
      throw new Error('VK не вернул список публикаций.');
    }

    return response.items;
  }

  const result = [];
  const addedPosts = {};

  let offset = 0;
  let shouldContinue = true;

  while (shouldContinue && offset < MAX_POSTS_TO_SCAN) {
    const response = callVkApi(
      'wall.get',
      {
        owner_id: ownerId,
        count: WALL_PAGE_SIZE,
        offset: offset,
        filter: 'owner',
      },
      token,
    );

    if (!response || !Array.isArray(response.items)) {
      throw new Error('VK не вернул список публикаций.');
    }

    const pageItems = response.items;

    if (pageItems.length === 0) {
      break;
    }

    const regularPostDates = [];

    pageItems.forEach(function (post) {
      const timestamp = Number(post.date || 0);

      const isPinned = Number(post.is_pinned || 0) === 1;

      if (!isPinned && timestamp) {
        regularPostDates.push(timestamp);
      }

      if (hasEndDate && timestamp > dateRange.endTimestamp) {
        return;
      }

      if (hasStartDate && timestamp < dateRange.startTimestamp) {
        return;
      }

      const postKey = String(post.owner_id) + '_' + String(post.id);

      if (addedPosts[postKey]) {
        return;
      }

      addedPosts[postKey] = true;

      result.push(post);
    });

    if (hasStartDate && regularPostDates.length > 0) {
      const newestRegularDate = Math.max.apply(null, regularPostDates);

      if (newestRegularDate < dateRange.startTimestamp) {
        shouldContinue = false;
      }
    }

    /*
     * Переходим к следующему диапазону стены
     * фиксированным шагом.
     *
     * VK иногда возвращает меньше запрошенных
     * 100 записей из-за удалённых или скрытых
     * публикаций. Это не означает конец стены.
     */
    offset += WALL_PAGE_SIZE;

    Utilities.sleep(350);
  }

  result.sort(function (a, b) {
    return Number(b.date || 0) - Number(a.date || 0);
  });

  if (offset >= MAX_POSTS_TO_SCAN) {
    Logger.log('Достигнут предел просмотра: ' + MAX_POSTS_TO_SCAN + ' публикаций.');
  }

  return result;
}

/* =========================================================
 * VK API
 * ========================================================= */

function getVkToken() {
  const token = PropertiesService.getScriptProperties().getProperty('VK_TOKEN');

  if (!token) {
    throw new Error('Не найден VK_TOKEN в свойствах скрипта.');
  }

  return token;
}

function callVkApi(method, parameters, token) {
  const requestParameters = Object.assign({}, parameters, {
    access_token: token,
    v: VK_API_VERSION,
  });

  const query = Object.keys(requestParameters)
    .map(function (key) {
      return encodeURIComponent(key) + '=' + encodeURIComponent(requestParameters[key]);
    })
    .join('&');

  const url = 'https://api.vk.com/method/' + method + '?' + query;

  const maximumAttempts = 5;

  for (let attempt = 1; attempt <= maximumAttempts; attempt++) {
    const apiResponse = UrlFetchApp.fetch(url, {
      method: 'get',
      muteHttpExceptions: true,
    });

    const responseCode = apiResponse.getResponseCode();

    const responseText = apiResponse.getContentText();

    if (responseCode !== 200) {
      if (attempt < maximumAttempts) {
        Utilities.sleep(700 * attempt);

        continue;
      }

      throw new Error(
        'Ошибка соединения с VK. HTTP-код: ' + responseCode + '. Ответ: ' + responseText,
      );
    }

    let data;

    try {
      data = JSON.parse(responseText);
    } catch (error) {
      throw new Error('VK вернул некорректный ответ: ' + responseText);
    }

    if (!data.error) {
      return data.response;
    }

    if (
      (data.error.error_code === 6 || data.error.error_code === 10) &&
      attempt < maximumAttempts
    ) {
      Utilities.sleep(700 * attempt);

      continue;
    }

    throw new Error('Ошибка VK API №' + data.error.error_code + ': ' + data.error.error_msg);
  }

  throw new Error('Не удалось выполнить запрос к VK API.');
}

/* =========================================================
 * VK: ВИДЕО
 * ========================================================= */

function getVideoDescriptionsMap(posts, token) {
  const videos = {};

  posts.forEach(function (post) {
    getAllPostAttachments(post).forEach(function (attachment) {
      if (!attachment || attachment.type !== 'video' || !attachment.video) {
        return;
      }

      const video = attachment.video;

      if (typeof video.owner_id === 'undefined' || typeof video.id === 'undefined') {
        return;
      }

      const key = getVideoKey(video);

      if (!videos[key]) {
        videos[key] = {
          identifier: getVideoIdentifier(video),

          fallbackDescription: cleanText(video.description || ''),
        };
      }
    });
  });

  const keys = Object.keys(videos);

  const result = {};

  keys.forEach(function (key) {
    result[key] = videos[key].fallbackDescription;
  });

  for (let start = 0; start < keys.length; start += VIDEO_BATCH_SIZE) {
    const batchKeys = keys.slice(start, start + VIDEO_BATCH_SIZE);

    const identifiers = batchKeys.map(function (key) {
      return videos[key].identifier;
    });

    try {
      const response = callVkApi(
        'video.get',
        {
          videos: identifiers.join(','),

          extended: 0,

          extended_description: 1,
        },
        token,
      );

      if (response && Array.isArray(response.items)) {
        response.items.forEach(function (video) {
          const key = getVideoKey(video);

          const description = cleanText(video.description || '');

          if (description && (!result[key] || description.length > result[key].length)) {
            result[key] = description;
          }
        });
      }
    } catch (error) {
      Logger.log('Ошибка получения описаний видео: ' + error.message);
    }

    Utilities.sleep(350);
  }

  return result;
}

function getPostVideoDescription(post, descriptions) {
  const attachments = getAllPostAttachments(post);

  for (let index = 0; index < attachments.length; index++) {
    const attachment = attachments[index];

    if (!attachment || attachment.type !== 'video' || !attachment.video) {
      continue;
    }

    const video = attachment.video;

    const key = getVideoKey(video);

    return cleanText(descriptions[key] || video.description || '');
  }

  return '';
}

function getVideoKey(video) {
  return String(video.owner_id) + '_' + String(video.id);
}

function getVideoIdentifier(video) {
  let identifier = getVideoKey(video);

  if (video.access_key) {
    identifier += '_' + String(video.access_key);
  }

  return identifier;
}

/* =========================================================
 * КЛАССИФИКАЦИЯ РЕКЛАМЫ
 * ========================================================= */

function getAdvertisingTypeFromSettings(postText, videoDescription, advertisingTypes) {
  const normalizedPost = normalizeForSearch(postText);

  const normalizedVideo = normalizeForSearch(videoDescription);

  const rules = Array.isArray(advertisingTypes) ? advertisingTypes : [];

  for (let index = 0; index < rules.length; index++) {
    const rule = rules[index];

    const typeName = String(rule.type || '').trim();

    if (!typeName) {
      continue;
    }

    const foundInPost = normalizeWordsArray(rule.postWords).some(function (word) {
      return containsNormalizedPhrase(normalizedPost, normalizeForSearch(word));
    });

    const foundInVideo = normalizeWordsArray(rule.videoWords).some(function (word) {
      return containsNormalizedPhrase(normalizedVideo, normalizeForSearch(word));
    });

    if (foundInPost || foundInVideo) {
      return typeName;
    }
  }

  return '';
}

function containsNormalizedPhrase(text, phrase) {
  if (!text || !phrase) {
    return false;
  }

  return (' ' + text + ' ').includes(' ' + phrase + ' ');
}

function normalizeForSearch(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/[^a-zа-я0-9]+/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/* =========================================================
 * ПОСТЫ И ВЛОЖЕНИЯ VK
 * ========================================================= */

function getCounterValue(counter) {
  if (counter && typeof counter.count === 'number') {
    return counter.count;
  }

  return 0;
}

function cleanText(text) {
  return String(text || '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function getPostType(post) {
  const attachments = getAllPostAttachments(post);

  const hasVideo = attachments.some(function (attachment) {
    return attachment && attachment.type === 'video' && attachment.video;
  });

  if (hasVideo) {
    return 'Видео и текст';
  }

  const photoCount = attachments.filter(function (attachment) {
    return attachment && attachment.type === 'photo' && attachment.photo;
  }).length;

  if (photoCount >= 2) {
    return 'Карусель и текст';
  }

  if (photoCount === 1) {
    return 'Текст с картинкой';
  }

  return 'Текст';
}

function getAllPostAttachments(post) {
  let attachments = [];

  if (Array.isArray(post.attachments)) {
    attachments = attachments.concat(post.attachments);
  }

  const copyHistory = Array.isArray(post.copy_history) ? post.copy_history : [];

  copyHistory.forEach(function (repost) {
    if (Array.isArray(repost.attachments)) {
      attachments = attachments.concat(repost.attachments);
    }
  });

  return attachments;
}

/* =========================================================
 * ИЗОБРАЖЕНИЯ
 * ========================================================= */

function getPostImageUrl(post) {
  let imageUrl = getImageFromAttachments(post.attachments || []);

  if (imageUrl) {
    return imageUrl;
  }

  const copyHistory = Array.isArray(post.copy_history) ? post.copy_history : [];

  for (let index = 0; index < copyHistory.length; index++) {
    imageUrl = getImageFromAttachments(copyHistory[index].attachments || []);

    if (imageUrl) {
      return imageUrl;
    }
  }

  return '';
}

function getImageFromAttachments(attachments) {
  for (let index = 0; index < attachments.length; index++) {
    const attachment = attachments[index];

    if (attachment && attachment.type === 'photo' && attachment.photo) {
      const url = getLargestPhotoSize(attachment.photo.sizes || []);

      if (url) {
        return url;
      }
    }
  }

  for (let index = 0; index < attachments.length; index++) {
    const attachment = attachments[index];

    if (attachment && attachment.type === 'video' && attachment.video) {
      const video = attachment.video;

      if (Array.isArray(video.image)) {
        const url = getLargestPhotoSize(video.image);

        if (url) {
          return url;
        }
      }

      if (Array.isArray(video.first_frame)) {
        const url = getLargestPhotoSize(video.first_frame);

        if (url) {
          return url;
        }
      }

      if (video.photo_1280) {
        return video.photo_1280;
      }

      if (video.photo_800) {
        return video.photo_800;
      }

      if (video.photo_640) {
        return video.photo_640;
      }

      if (video.photo_320) {
        return video.photo_320;
      }
    }
  }

  for (let index = 0; index < attachments.length; index++) {
    const attachment = attachments[index];

    if (attachment && attachment.type === 'link' && attachment.link) {
      const link = attachment.link;

      if (link.photo && Array.isArray(link.photo.sizes)) {
        const url = getLargestPhotoSize(link.photo.sizes);

        if (url) {
          return url;
        }
      }

      if (link.photo_800) {
        return link.photo_800;
      }

      if (link.photo_300) {
        return link.photo_300;
      }
    }
  }

  return '';
}

function getLargestPhotoSize(sizes) {
  if (!Array.isArray(sizes) || sizes.length === 0) {
    return '';
  }

  const available = sizes
    .filter(function (size) {
      return size && size.url;
    })
    .sort(function (a, b) {
      const areaA = Number(a.width || 0) * Number(a.height || 0);

      const areaB = Number(b.width || 0) * Number(b.height || 0);

      return areaB - areaA;
    });

  return available.length > 0 ? available[0].url : '';
}

/**
 * Вставляет изображение по URL.
 */
function setImageFormula(cell, imageUrl) {
  const escaped = String(imageUrl || '').replace(/"/g, '""');

  try {
    cell.setFormula('=IMAGE("' + escaped + '";4;180;180)');

    return;
  } catch (error) {
    // Пробуем другую локаль.
  }

  try {
    cell.setFormula('=IMAGE("' + escaped + '",4,180,180)');
  } catch (error) {
    cell.setValue(imageUrl);

    Logger.log('Не удалось вставить картинку: ' + error.message);
  }
}

/* =========================================================
 * ЛИСТЫ И ОФОРМЛЕНИЕ
 * ========================================================= */

function sanitizeSheetName(name) {
  let result = String(name || 'Группа')
    .trim()
    .replace(/[\[\]\*\?\/\\:]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (!result) {
    result = 'Группа';
  }

  return result.slice(0, 100);
}

function formatVkSheet(sheet, postsCount) {
  formatCommonSheet(sheet, postsCount, 10);

  sheet.setColumnWidth(9, 250);
  sheet.setColumnWidth(10, 180);

  if (postsCount > 0) {
    sheet.getRange(2, 9, postsCount, 1).setWrapStrategy(SpreadsheetApp.WrapStrategy.CLIP);

    sheet.getRange(2, 10, postsCount, 1).setHorizontalAlignment('center');
  }
}

function formatTelegramSheet(sheet, postsCount) {
  formatCommonSheet(sheet, postsCount, 9);

  sheet.setColumnWidth(9, 180);

  if (postsCount > 0) {
    sheet.getRange(2, 9, postsCount, 1).setHorizontalAlignment('center');
  }
}

function formatInstagramSheet(sheet, postsCount) {
  formatCommonSheet(sheet, postsCount, 9);

  sheet.setColumnWidth(9, 180);

  if (postsCount > 0) {
    sheet.getRange(2, 9, postsCount, 1).setHorizontalAlignment('center');
  }
}

function formatCommonSheet(sheet, postsCount, columnsCount) {
  sheet.setFrozenRows(1);

  sheet
    .getRange(1, 1, 1, columnsCount)
    .setFontWeight('bold')
    .setHorizontalAlignment('center')
    .setVerticalAlignment('middle')
    .setWrap(true);

  sheet.setColumnWidth(1, 260);
  sheet.setColumnWidth(2, 150);
  sheet.setColumnWidth(3, 250);
  sheet.setColumnWidth(4, 200);

  sheet.setColumnWidth(5, 65);
  sheet.setColumnWidth(6, 65);
  sheet.setColumnWidth(7, 65);

  sheet.setColumnWidth(8, 160);

  sheet.setRowHeight(1, 45);

  if (postsCount <= 0) {
    return;
  }

  sheet.getRange(2, 2, postsCount, 1).setNumberFormat('dd.MM.yyyy HH:mm');

  sheet.getRange(2, 1, postsCount, columnsCount).setVerticalAlignment('top').setWrap(true);

  sheet.getRange(2, 3, postsCount, 1).setWrapStrategy(SpreadsheetApp.WrapStrategy.CLIP);

  sheet.getRange(2, 5, postsCount, 3).setHorizontalAlignment('center');

  sheet.getRange(2, 8, postsCount, 1).setHorizontalAlignment('center');

  for (let row = 2; row <= postsCount + 1; row++) {
    sheet.setRowHeight(row, 190);
  }
}

function debugVkWallOffsets() {
  const settings = getStoredParserSettings();

  const group = settings.groups.find(function (item) {
    return item.network === 'vk';
  });

  if (!group) {
    throw new Error('В настройках не найдена VK-группа.');
  }

  const token = getVkToken();

  const community = resolveVkCommunity(group.url, token);

  const offsets = [0, 500, 1000, 1500, 2000, 2500, 3000, 4000, 5000];

  offsets.forEach(function (offset) {
    try {
      const response = callVkApi(
        'wall.get',
        {
          owner_id: community.ownerId,
          count: 100,
          offset: offset,
          filter: 'owner',
        },
        token,
      );

      const posts = response && Array.isArray(response.items) ? response.items : [];

      if (posts.length === 0) {
        Logger.log('OFFSET ' + offset + ': публикаций нет');

        return;
      }

      const dates = posts
        .filter(function (post) {
          return post.date;
        })
        .map(function (post) {
          return Number(post.date);
        });

      const newest = new Date(Math.max.apply(null, dates) * 1000);

      const oldest = new Date(Math.min.apply(null, dates) * 1000);

      Logger.log(
        'OFFSET ' +
          offset +
          ': получено ' +
          posts.length +
          '; новые: ' +
          newest.toISOString() +
          '; старые: ' +
          oldest.toISOString(),
      );
    } catch (error) {
      Logger.log('OFFSET ' + offset + ': ОШИБКА — ' + error.message);
    }
  });
}

function debugVkSelectedPeriod() {
  const settings = getStoredParserSettings();

  const group = settings.groups.find(function (item) {
    return item.name === 'ВК ЗСЖ ОГТ';
  });

  if (!group) {
    throw new Error('Группа «ВК ЗСЖ ОГТ» не найдена.');
  }

  Logger.log('Группа: ' + group.name);

  Logger.log('URL: ' + group.url);

  Logger.log('Дата начала: [' + group.dateStart + ']');

  Logger.log('Дата окончания: [' + group.dateEnd + ']');

  const range = getParsingDateRange(group);

  const token = getVkToken();

  const community = resolveVkCommunity(group.url, token);

  Logger.log('ownerId: ' + community.ownerId);

  const posts = getVkWallPostsForPeriod(community.ownerId, token, range);

  Logger.log('Найдено публикаций: ' + posts.length);

  posts.slice(0, 10).forEach(function (post) {
    Logger.log(post.id + ' — ' + new Date(Number(post.date) * 1000).toISOString());
  });
}

function debugVkOldOffsets() {
  const settings = getStoredParserSettings();

  const group = settings.groups.find(function (item) {
    return item.name === 'ВК ЗСЖ ОГТ';
  });

  if (!group) {
    throw new Error('Группа «ВК ЗСЖ ОГТ» не найдена.');
  }

  const token = getVkToken();

  const community = resolveVkCommunity(group.url, token);

  const offsets = [2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000];

  offsets.forEach(function (offset) {
    const response = callVkApi(
      'wall.get',
      {
        owner_id: community.ownerId,
        count: 100,
        offset: offset,
        filter: 'owner',
      },
      token,
    );

    const posts = response && Array.isArray(response.items) ? response.items : [];

    if (posts.length === 0) {
      Logger.log('OFFSET ' + offset + ': публикаций нет');

      return;
    }

    const timestamps = posts
      .map(function (post) {
        return Number(post.date || 0);
      })
      .filter(Boolean);

    Logger.log(
      'OFFSET ' +
        offset +
        ': новые ' +
        new Date(Math.max.apply(null, timestamps) * 1000).toISOString() +
        '; старые ' +
        new Date(Math.min.apply(null, timestamps) * 1000).toISOString(),
    );

    Utilities.sleep(350);
  });
}

function debugVkJanuaryOffsets() {
  const settings = getStoredParserSettings();

  const group = settings.groups.find(function (item) {
    return item.name === 'ВК ЗСЖ ОГТ';
  });

  if (!group) {
    throw new Error('Группа «ВК ЗСЖ ОГТ» не найдена.');
  }

  const token = getVkToken();

  const community = resolveVkCommunity(group.url, token);

  const range = getParsingDateRange(group);

  const offsets = [4000, 4100, 4200, 4300, 4400, 4500];

  offsets.forEach(function (offset) {
    const response = callVkApi(
      'wall.get',
      {
        owner_id: community.ownerId,
        count: 100,
        offset: offset,
        filter: 'owner',
      },
      token,
    );

    const posts = response && Array.isArray(response.items) ? response.items : [];

    const matching = posts.filter(function (post) {
      const timestamp = Number(post.date || 0);

      return timestamp >= range.startTimestamp && timestamp <= range.endTimestamp;
    });

    const timestamps = posts
      .map(function (post) {
        return Number(post.date || 0);
      })
      .filter(Boolean);

    Logger.log(
      'OFFSET ' +
        offset +
        ': новые ' +
        (timestamps.length
          ? new Date(Math.max.apply(null, timestamps) * 1000).toISOString()
          : 'нет') +
        '; старые ' +
        (timestamps.length
          ? new Date(Math.min.apply(null, timestamps) * 1000).toISOString()
          : 'нет') +
        '; январских: ' +
        matching.length,
    );

    Utilities.sleep(350);
  });
}
