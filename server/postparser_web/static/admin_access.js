"use strict";

(function () {
  const addButton = document.getElementById("addUserButton");
  const generatedAccess = document.getElementById("generatedAccess");
  const usersList = document.getElementById("accessUsersList");
  const instagramOAuthButton = document.getElementById(
    "createInstagramOAuthLink"
  );
  const generatedInstagramOAuthLink = document.getElementById(
    "generatedInstagramOAuthLink"
  );
  const oneTimeCodes = new Map();

  function element(tagName, className, text) {
    const node = document.createElement(tagName);
    node.className = className || "";
    node.textContent = text || "";
    return node;
  }

  async function request(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(payload.error || "Не удалось выполнить запрос.");
    }
    return payload;
  }

  function renderUsers(users) {
    usersList.replaceChildren();
    if (!users.length) {
      usersList.appendChild(element("p", "access-empty", "Пользователей пока нет."));
      return;
    }
    users.forEach(function (user) {
      const row = element("div", "access-user");
      const name = element("span", "access-user-name", user.name);
      const codeCell = element("div", "access-user-code");
      const oneTimeCode = oneTimeCodes.get(user.id);
      if (oneTimeCode) {
        const code = element("code", "generated-access-code", "••••••••••••••••••••");
        const reveal = element("button", "button button-secondary", "Показать код");
        const copy = element("button", "button button-secondary", "Скопировать");
        let visible = false;
        reveal.type = "button";
        copy.type = "button";
        reveal.addEventListener("click", function () {
          visible = !visible;
          code.textContent = visible ? oneTimeCode : "••••••••••••••••••••";
          reveal.textContent = visible ? "Скрыть код" : "Показать код";
          reveal.setAttribute("aria-expanded", visible ? "true" : "false");
        });
        copy.addEventListener("click", async function () {
          await navigator.clipboard.writeText(oneTimeCode);
          copy.textContent = "Скопировано";
        });
        codeCell.append(code, reveal, copy);
      } else {
        codeCell.appendChild(
          element("span", "access-code-issued", "Код уже был выдан")
        );
      }
      const actions = element("div", "access-user-actions");
      const toggle = element(
        "button",
        "button button-secondary",
        user.active ? "Отключить" : "Включить"
      );
      toggle.type = "button";
      toggle.addEventListener("click", async function () {
        toggle.disabled = true;
        try {
          await request("/api/v1/admin/users/" + user.id, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ active: !user.active }),
          });
          await loadUsers();
        } catch (error) {
          generatedAccess.textContent = error.message;
          generatedAccess.hidden = false;
          toggle.disabled = false;
        }
      });
      const remove = element("button", "button button-danger", "Удалить");
      remove.type = "button";
      remove.addEventListener("click", async function () {
        if (!window.confirm("Удалить доступ пользователя?")) {
          return;
        }
        remove.disabled = true;
        try {
          await request("/api/v1/admin/users/" + user.id, {
            method: "DELETE",
          });
          oneTimeCodes.delete(user.id);
          await loadUsers();
        } catch (error) {
          generatedAccess.textContent = error.message;
          generatedAccess.hidden = false;
          remove.disabled = false;
        }
      });
      actions.append(toggle, remove);
      row.append(name, codeCell, actions);
      usersList.appendChild(row);
    });
  }

  async function loadUsers() {
    const payload = await request("/api/v1/admin/users");
    renderUsers(Array.isArray(payload.users) ? payload.users : []);
  }

  addButton.addEventListener("click", async function () {
    addButton.disabled = true;
    try {
      const payload = await request("/api/v1/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      oneTimeCodes.set(payload.user.id, payload.user.access_code);
      generatedAccess.hidden = true;
      await loadUsers();
    } catch (error) {
      generatedAccess.textContent = error.message;
      generatedAccess.hidden = false;
    } finally {
      addButton.disabled = false;
    }
  });

  instagramOAuthButton.addEventListener("click", async function () {
    instagramOAuthButton.disabled = true;
    generatedInstagramOAuthLink.hidden = true;
    generatedInstagramOAuthLink.replaceChildren();
    try {
      const payload = await request(
        "/api/v1/admin/instagram/oauth-invitations",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        }
      );
      const link = element("a", "instagram-oauth-link", payload.setup_url);
      link.href = payload.setup_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      const copy = element(
        "button",
        "button button-secondary",
        "Скопировать ссылку"
      );
      copy.type = "button";
      copy.addEventListener("click", async function () {
        await navigator.clipboard.writeText(payload.setup_url);
        copy.textContent = "Скопировано";
      });
      generatedInstagramOAuthLink.append(link, copy);
      generatedInstagramOAuthLink.hidden = false;
    } catch (error) {
      generatedInstagramOAuthLink.textContent = error.message;
      generatedInstagramOAuthLink.hidden = false;
    } finally {
      instagramOAuthButton.disabled = false;
    }
  });

  loadUsers().catch(function (error) {
    usersList.textContent = error.message;
  });
})();
