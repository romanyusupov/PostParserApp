"use strict";

(function () {
  const addButton = document.getElementById("addUserButton");
  const generatedAccess = document.getElementById("generatedAccess");
  const usersList = document.getElementById("accessUsersList");

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
      row.append(name, toggle);
      usersList.appendChild(row);
    });
  }

  async function loadUsers() {
    const payload = await request("/api/v1/admin/users");
    renderUsers(Array.isArray(payload.users) ? payload.users : []);
  }

  function showGenerated(user) {
    const title = element("strong", "generated-access-title", user.name);
    const code = element("code", "generated-access-code", user.access_code);
    const copy = element("button", "button button-secondary", "Скопировать код");
    copy.type = "button";
    copy.addEventListener("click", async function () {
      await navigator.clipboard.writeText(user.access_code);
      copy.textContent = "Скопировано";
    });
    generatedAccess.replaceChildren(title, code, copy);
    generatedAccess.hidden = false;
  }

  addButton.addEventListener("click", async function () {
    addButton.disabled = true;
    try {
      const payload = await request("/api/v1/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      showGenerated(payload.user);
      await loadUsers();
    } catch (error) {
      generatedAccess.textContent = error.message;
      generatedAccess.hidden = false;
    } finally {
      addButton.disabled = false;
    }
  });

  loadUsers().catch(function (error) {
    usersList.textContent = error.message;
  });
})();
