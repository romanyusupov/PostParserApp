"use strict";

(function () {
  const meta = document.querySelector('meta[name="csrf-token"]');
  const token = meta ? meta.content : "";
  const originalFetch = window.fetch.bind(window);

  window.fetch = function (input, init) {
    const options = Object.assign({}, init || {});
    const method = String(options.method || "GET").toUpperCase();
    const url = new URL(
      typeof input === "string" ? input : input.url,
      window.location.href
    );
    if (
      token &&
      url.origin === window.location.origin &&
      ["POST", "PUT", "PATCH", "DELETE"].includes(method)
    ) {
      const headers = new Headers(options.headers || {});
      headers.set("X-CSRF-Token", token);
      options.headers = headers;
    }
    return originalFetch(input, options);
  };
})();
