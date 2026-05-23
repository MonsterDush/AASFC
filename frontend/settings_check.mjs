
    import {
      applyTelegramTheme,
      mountCommonUI,
      mountNav,
      mountVenueMenu,
      ensureLogin,
      getLang,
      setLang,
      getThemePref,
      setThemePref,
      applyTheme,
      api,
      logout,
      setActiveVenueId,
      wa,
      toast,
    } from "/app.js";

    applyTelegramTheme();
    mountCommonUI("settings");
    await ensureLogin({ silent: true });
    const navState = await mountNav({ activeTab: "settings" });
    await mountVenueMenu({ containerSelector: "#venueMenuMount" });
    const me = navState?.me || null;
    const isSuperAdmin = String(me?.system_role || "").toUpperCase() === "SUPER_ADMIN";
    const notifHistoryBtn = document.getElementById("btnNotifHistory");
    if (notifHistoryBtn && !isSuperAdmin) notifHistoryBtn.remove();

    const hint = document.getElementById("langHint");
    const paintLang = () => {
      const lang = getLang();
      hint.textContent = lang === "en" ? "Current language: English" : "Текущий язык: Русский";
    };
    paintLang();
    document.getElementById("langRu").onclick = () => { setLang("ru"); location.reload(); };
    document.getElementById("langEn").onclick = () => { setLang("en"); location.reload(); };

    const themeSel = document.getElementById("themeSelect");
    const themeHint = document.getElementById("themeHint");
    if (isSuperAdmin && themeSel && !themeSel.querySelector('option[value="hookahplace"]')) {
      const opt = document.createElement("option");
      opt.value = "hookahplace";
      opt.textContent = "Hookah Place";
      themeSel.appendChild(opt);
    }

    const paintTheme = () => {
      const value = getThemePref();
      if (themeSel) themeSel.value = value;
      if (!themeHint) return;
      themeHint.textContent = value === "hookahplace"
        ? "Текущая тема: Hookah Place"
        : (value === "dark"
          ? "Текущая тема: Тёмная"
          : (value === "light" ? "Текущая тема: Светлая" : "Текущая тема: Системная"));
    };
    paintTheme();
    themeSel?.addEventListener("change", () => {
      setThemePref(themeSel.value);
      applyTheme();
      paintTheme();
    });

    function displayName(u) {
      const shortName = String(u?.short_name || "").trim();
      if (shortName) return shortName;
      const full = String(u?.full_name || "").trim();
      if (full) return full.split(/\s+/)[0];
      const username = String(u?.tg_username || "").trim();
      if (username) return username.startsWith("@") ? username : `@${username}`;
      return "друг";
    }

    try {
      const hello = document.getElementById("helloName");
      if (hello) hello.textContent = displayName(me);
    } catch {}

    const logoutCard = document.getElementById("logoutCard");
    const insideMiniApp = Boolean(wa()?.initData || "");
    if (!insideMiniApp) logoutCard?.classList.remove("hidden");

    document.getElementById("btnLogout")?.addEventListener("click", async () => {
      const ok = window.confirm("Выйти из аккаунта на этом устройстве?");
      if (!ok) return;
      try {
        await logout();
      } catch {
        // если cookie уже протухла, всё равно очищаем локальное состояние и уводим на логин
      }
      try { setActiveVenueId(""); } catch {}
      toast("Вы вышли из аккаунта", "ok");
      setTimeout(() => {
        location.href = "/auth.html";
      }, 250);
    });

    const modal = document.getElementById("modal");
    const modalTitle = modal?.querySelector(".modal__title");
    const modalBody = modal?.querySelector(".modal__body");
    function closeModal() { modal?.classList.remove("open"); }
    modal?.querySelector("[data-close]")?.addEventListener("click", closeModal);
    modal?.querySelector(".modal__backdrop")?.addEventListener("click", closeModal);
    function openModal(title, bodyHtml) {
      if (modalTitle) modalTitle.textContent = title || "";
      if (modalBody) modalBody.innerHTML = bodyHtml || "";
      modal?.classList.add("open");
    }

    function sw(id, checked, disabled = false) {
      return `
        <label class="switch">
          <input type="checkbox" id="${id}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} />
          <span class="slider"></span>
        </label>`;
    }

    function esc(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function detailLabel(value) {
      if (value === "short") return "Кратко";
      if (value === "detailed") return "Подробно";
      return "Стандартно";
    }

    function typeLabel(value) {
      const code = String(value || "").toLowerCase();
      if (code === "shift_reminder") return "Напоминание о смене";
      if (code === "day_economics_summary") return "Экономика дня";
      if (code === "salary_day_breakdown") return "Начисления за день";
      if (code === "soft_alerts") return "Мягкий алерт";
      if (code === "adjustments") return "Штрафы и корректировки";
      return value || "Уведомление";
    }

    function statusLabel(value) {
      const code = String(value || "").toLowerCase();
      if (code === "sent") return "Отправлено";
      if (code === "pending") return "В очереди";
      if (code === "failed") return "Ошибка";
      if (code === "skipped") return "Пропущено";
      return value || "—";
    }

    function statusBadgeClass(value) {
      const code = String(value || "").toLowerCase();
      if (code === "sent") return "notif-badge notif-badge--ok";
      if (code === "failed") return "notif-badge notif-badge--err";
      if (code === "pending") return "notif-badge notif-badge--wait";
      return "notif-badge";
    }

    function formatDateTime(value) {
      if (!value) return "—";
      try {
        return new Intl.DateTimeFormat("ru-RU", {
          day: "2-digit",
          month: "2-digit",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        }).format(new Date(value));
      } catch {
        return String(value);
      }
    }

    async function loadNotif() {
      return api("/me/notification-settings");
    }

    async function saveNotif(patch) {
      return api("/me/notification-settings", { method: "PATCH", body: patch });
    }

    async function loadNotifHistory(params = {}) {
      const url = new URL(`${location.origin}/__stub`);
      url.pathname = "/me/notification-history";
      Object.entries(params || {}).forEach(([key, value]) => {
        if (value === undefined || value === null || value === "") return;
        url.searchParams.set(key, String(value));
      });
      return api(`${url.pathname}${url.search}`);
    }

    function notificationCapabilityBanner(state) {
      if (state?.telegram_linked) {
        const handle = state?.tg_username ? ` @${esc(state.tg_username)}` : "";
        return `<div class="notif-state-banner notif-state-banner--ok">Telegram привязан${handle}. Бот может отправлять уведомления.</div>`;
      }
      return `<div class="notif-state-banner notif-state-banner--warn">${esc(state?.disabled_reason || "Привяжите Telegram в профиле, чтобы получать уведомления от бота.")}</div>`;
    }

    function renderNotifModal(state) {
      const enabled = !!state.notify_enabled;
      const adjustments = !!state.notify_adjustments;
      const shifts = !!state.notify_shifts;
      const dayEconomics = !!state.notify_day_economics;
      const salary = !!state.notify_salary;
      const softAlerts = !!state.notify_soft_alerts;
      const leadHours = Number(state.shift_reminder_lead_time_hours || 18);
      const detailLevel = String(state.notification_detail_level || "standard");
      const leadOptions = Array.isArray(state.shift_reminder_lead_time_options) ? state.shift_reminder_lead_time_options : [1, 2, 6, 12, 18, 24];
      const detailOptions = Array.isArray(state.notification_detail_level_options) ? state.notification_detail_level_options : ["short", "standard", "detailed"];
      const locked = !!state.settings_locked;

      const html = `
        <div class="itemcard mt-8 notif-modal-card">
          ${notificationCapabilityBanner(state)}
          <div id="notifSaveState" class="notif-inline-state muted"></div>

          <div class="toggle">
            <div class="toggle__label">
              <div class="toggle__title">Уведомления от бота</div>
              <div class="toggle__desc">Если выключить — бот не будет присылать ничего</div>
            </div>
            ${sw("swAll", enabled, locked)}
          </div>

          <div id="notifFields" class="notif-fields ${enabled && !locked ? "" : "is-dimmed"}">
            <div class="muted mb-6 mt-8 small">Штрафы / списания / премии</div>
            <div class="toggle">
              <div class="toggle__label">
                <div class="toggle__title">Уведомлять</div>
                <div class="toggle__desc">О новых начислениях и спорах</div>
              </div>
              ${sw("swAdj", adjustments, locked || !enabled)}
            </div>

            <div class="muted mb-6 mt-10 small">График</div>
            <div class="toggle">
              <div class="toggle__label">
                <div class="toggle__title">Напоминать о смене</div>
                <div class="toggle__desc">Время напоминания можно настроить ниже</div>
              </div>
              ${sw("swShift", shifts, locked || !enabled)}
            </div>
            <div class="mt-8">
              <div class="muted small mb-6">За сколько предупреждать</div>
              <select id="shiftLeadHours" class="input minw-240" ${(locked || !enabled || !shifts) ? "disabled" : ""}>
                ${leadOptions.map((value) => `<option value="${value}" ${Number(value) === leadHours ? "selected" : ""}>За ${value} ${Number(value) === 1 ? "час" : (Number(value) < 5 ? "часа" : "часов")}</option>`).join("")}
              </select>
            </div>

            <div class="muted mb-6 mt-10 small">Экономика дня</div>
            <div class="toggle">
              <div class="toggle__label">
                <div class="toggle__title">Сводка по экономике дня</div>
                <div class="toggle__desc">Для пользователей с доступом к просмотру сводки</div>
              </div>
              ${sw("swDayEconomics", dayEconomics, locked || !enabled)}
            </div>

            <div class="muted mb-6 mt-10 small">Зарплаты</div>
            <div class="toggle">
              <div class="toggle__label">
                <div class="toggle__title">Начисления за день</div>
                <div class="toggle__desc">Подробности по сумме за день и чаевым</div>
              </div>
              ${sw("swSalary", salary, locked || !enabled)}
            </div>

            <div class="muted mb-6 mt-10 small">Алерты</div>
            <div class="toggle">
              <div class="toggle__label">
                <div class="toggle__title">Мягкие алерты</div>
                <div class="toggle__desc">Предупреждения о проблемных днях без лишнего спама</div>
              </div>
              ${sw("swSoftAlerts", softAlerts, locked || !enabled)}
            </div>

            <div class="mt-10">
              <div class="muted small mb-6">Детализация сообщений</div>
              <select id="notificationDetailLevel" class="input minw-240" ${(locked || !enabled) ? "disabled" : ""}>
                ${detailOptions.map((value) => `<option value="${value}" ${String(value) === detailLevel ? "selected" : ""}>${detailLabel(String(value))}</option>`).join("")}
              </select>
            </div>
          </div>

          <div class="row gap-8 mt-12 row--end wrap">
            <button class="btn" id="btnNotifClose">Закрыть</button>
            <button class="btn primary" id="btnNotifSave" ${locked ? "disabled" : ""}>Сохранить</button>
          </div>
        </div>
      `;

      openModal("Настройка уведомлений", html);

      const elAll = document.getElementById("swAll");
      const elAdj = document.getElementById("swAdj");
      const elShift = document.getElementById("swShift");
      const elDayEconomics = document.getElementById("swDayEconomics");
      const elSalary = document.getElementById("swSalary");
      const elSoftAlerts = document.getElementById("swSoftAlerts");
      const elLeadHours = document.getElementById("shiftLeadHours");
      const elDetailLevel = document.getElementById("notificationDetailLevel");
      const fieldsWrap = document.getElementById("notifFields");
      const saveBtn = document.getElementById("btnNotifSave");
      const saveState = document.getElementById("notifSaveState");

      const setSaveState = (text, kind = "muted") => {
        if (!saveState) return;
        saveState.className = `notif-inline-state ${kind}`;
        saveState.textContent = text || "";
      };

      const syncDisabled = () => {
        const on = !!elAll?.checked && !locked;
        if (fieldsWrap) fieldsWrap.classList.toggle("is-dimmed", !on);
        [elAdj, elShift, elDayEconomics, elSalary, elSoftAlerts, elDetailLevel].forEach((el) => {
          if (el) el.disabled = !on;
        });
        if (elLeadHours) elLeadHours.disabled = !on || !elShift?.checked;
        if (saveBtn) saveBtn.disabled = locked;
      };
      elAll?.addEventListener("change", syncDisabled);
      elShift?.addEventListener("change", syncDisabled);
      syncDisabled();

      document.getElementById("btnNotifClose")?.addEventListener("click", closeModal);
      saveBtn?.addEventListener("click", async () => {
        if (locked) return;
        saveBtn.disabled = true;
        setSaveState("Сохраняем изменения…");
        try {
          const patch = {
            notify_enabled: !!elAll?.checked,
            notify_adjustments: !!elAdj?.checked,
            notify_shifts: !!elShift?.checked,
            notify_day_economics: !!elDayEconomics?.checked,
            notify_salary: !!elSalary?.checked,
            notify_soft_alerts: !!elSoftAlerts?.checked,
            shift_reminder_lead_time_hours: Number(elLeadHours?.value || 18),
            notification_detail_level: String(elDetailLevel?.value || "standard"),
          };
          const out = await saveNotif(patch);
          setSaveState("Настройки сохранены", "ok");
          toast("Настройки уведомлений сохранены", "ok");
          setTimeout(() => {
            closeModal();
            renderNotifModal(out?.settings || { ...state, ...patch, settings_locked: false });
          }, 250);
        } catch (e) {
          setSaveState(e?.data?.detail || e?.message || "Не удалось сохранить настройки", "err");
          saveBtn.disabled = false;
        }
      });
    }

    function buildHistoryCards(items) {
      const list = Array.isArray(items) ? items : [];
      if (!list.length) {
        return `<div class="itemcard mt-8"><b>Пока пусто</b><div class="muted mt-6">Когда бот начнёт отправлять уведомления, здесь появится история доставки и ошибок.</div></div>`;
      }
      return list.map((item) => {
        const timeLabel = item?.sent_at ? `Отправлено: ${formatDateTime(item.sent_at)}` : (item?.planned_at ? `Планировалось: ${formatDateTime(item.planned_at)}` : "Время не указано");
        const venue = item?.venue_name ? `<div class="muted small mt-6">Заведение: ${esc(item.venue_name)}</div>` : "";
        const preview = item?.payload_preview ? `<div class="notif-history-preview mt-8">${esc(item.payload_preview)}</div>` : "";
        const error = item?.error_text ? `<div class="notif-history-error mt-8">${esc(item.error_text)}</div>` : "";
        return `
          <div class="itemcard mt-8 notif-history-card">
            <div class="row gap-8 wrap" style="justify-content:space-between; align-items:flex-start;">
              <div>
                <b>${esc(typeLabel(item?.notification_type))}</b>
                <div class="muted small mt-6">${esc(timeLabel)}</div>
                ${venue}
              </div>
              <span class="${statusBadgeClass(item?.status)}">${esc(statusLabel(item?.status))}</span>
            </div>
            ${preview}
            ${error}
          </div>
        `;
      }).join("");
    }

    function renderNotifHistoryModal(payload, filter = "all") {
      const canReceive = !!payload?.can_receive_bot_notifications;
      const items = Array.isArray(payload?.items) ? payload.items : [];
      const filtered = items.filter((item) => {
        if (filter === "errors") return String(item?.status || "").toLowerCase() === "failed";
        if (filter === "alerts") return String(item?.notification_type || "").toLowerCase() === "soft_alerts";
        return true;
      });
      const html = `
        <div class="itemcard mt-8 notif-modal-card">
          ${canReceive ? `<div class="notif-state-banner notif-state-banner--ok">Показаны последние уведомления и попытки доставки.</div>` : `<div class="notif-state-banner notif-state-banner--warn">Telegram пока не привязан — история будет пустой, пока бот не сможет отправлять сообщения.</div>`}
          <div class="row gap-8 mt-10 wrap">
            <button class="btn ${filter === "all" ? "primary" : ""}" data-history-filter="all">Все</button>
            <button class="btn ${filter === "errors" ? "primary" : ""}" data-history-filter="errors">Ошибки</button>
            <button class="btn ${filter === "alerts" ? "primary" : ""}" data-history-filter="alerts">Алерты</button>
          </div>
          <div class="mt-8" id="notifHistoryList">${buildHistoryCards(filtered)}</div>
          <div class="row gap-8 mt-12 row--end wrap">
            <button class="btn" id="btnNotifHistoryClose">Закрыть</button>
          </div>
        </div>
      `;
      openModal("История уведомлений", html);
      document.getElementById("btnNotifHistoryClose")?.addEventListener("click", closeModal);
      document.querySelectorAll("[data-history-filter]").forEach((btn) => {
        btn.addEventListener("click", () => renderNotifHistoryModal(payload, btn.getAttribute("data-history-filter") || "all"));
      });
    }

    document.getElementById("btnNotifSettings")?.addEventListener("click", async (event) => {
      const btn = event?.currentTarget;
      const prevText = btn?.textContent || "";
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Загрузка…";
      }
      try {
        const state = await loadNotif();
        renderNotifModal(state);
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось загрузить настройки уведомлений", "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = prevText;
        }
      }
    });

    document.getElementById("btnNotifHistory")?.addEventListener("click", async (event) => {
      const btn = event?.currentTarget;
      const prevText = btn?.textContent || "";
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Загрузка…";
      }
      try {
        const payload = await loadNotifHistory({ limit: 40 });
        renderNotifHistoryModal(payload, "all");
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось загрузить историю уведомлений", "err");
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = prevText;
        }
      }
    });
  