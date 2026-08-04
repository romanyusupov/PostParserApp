"use strict";

(function (root, factory) {
  const api = factory();

  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.PostParserResults = api;
  }
})(typeof globalThis === "object" ? globalThis : this, function () {
  function metricValue(value) {
    if (
      value === null ||
      value === undefined ||
      typeof value === "boolean" ||
      (typeof value === "string" && value.trim() === "")
    ) {
      return null;
    }

    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function nextSortState(currentState, field) {
    if (!currentState || currentState.field !== field) {
      return { field: field, direction: "descending" };
    }

    return {
      field: field,
      direction:
        currentState.direction === "descending"
          ? "ascending"
          : "descending",
    };
  }

  function sortPosts(posts, field, direction) {
    const multiplier = direction === "ascending" ? 1 : -1;

    return posts
      .map(function (post, index) {
        return {
          post: post,
          index: index,
          metric: metricValue(post[field]),
        };
      })
      .sort(function (left, right) {
        if (left.metric === null && right.metric === null) {
          return left.index - right.index;
        }
        if (left.metric === null) {
          return 1;
        }
        if (right.metric === null) {
          return -1;
        }
        if (left.metric === right.metric) {
          return left.index - right.index;
        }
        return (left.metric - right.metric) * multiplier;
      })
      .map(function (item) {
        return item.post;
      });
  }

  function collapsedText(value, maxCharacters, maxLines) {
    const text = String(value || "");
    const characters = Array.from(text);
    const lines = text.split("\n");
    let shortened = false;
    let result = text;

    if (lines.length > maxLines) {
      result = lines.slice(0, maxLines).join("\n");
      shortened = true;
    }

    const resultCharacters = Array.from(result);
    if (resultCharacters.length > maxCharacters) {
      result = resultCharacters.slice(0, maxCharacters).join("");
      shortened = true;
    } else if (!shortened && characters.length > maxCharacters) {
      result = characters.slice(0, maxCharacters).join("");
      shortened = true;
    }

    return {
      text: shortened ? result.trimEnd() + "…" : result,
      shortened: shortened,
    };
  }

  function safeHttpUrl(value) {
    try {
      const url = new URL(String(value || ""));
      return url.protocol === "http:" || url.protocol === "https:"
        ? url.href
        : "";
    } catch (error) {
      return "";
    }
  }

  function limitedRuns(runs, expanded, limit) {
    const source = Array.isArray(runs) ? runs : [];
    const safeLimit = Number.isInteger(limit) && limit > 0 ? limit : 3;
    return expanded ? source.slice() : source.slice(0, safeLimit);
  }

  function runsToggleLabel(total, expanded, limit) {
    const safeTotal = Number.isInteger(total) && total > 0 ? total : 0;
    const safeLimit = Number.isInteger(limit) && limit > 0 ? limit : 3;
    const hiddenCount = Math.max(0, safeTotal - safeLimit);

    return expanded
      ? "Скрыть"
      : "Показать остальные (" + String(hiddenCount) + ")";
  }

  return {
    collapsedText: collapsedText,
    metricValue: metricValue,
    nextSortState: nextSortState,
    limitedRuns: limitedRuns,
    runsToggleLabel: runsToggleLabel,
    safeHttpUrl: safeHttpUrl,
    sortPosts: sortPosts,
  };
});
