export function createStaffShiftCalendarController(context) {
  const { runtime, toast, DEMO_MODE, shouldShowDemoSalaryValue, el, toHHMM, pad2, ym, ymd, addDays, WEEKDAYS, isPastDay, colorForInterval, escapeHtml, pickShortName, displayPerson, shiftSlotLabel, shiftIntervalId, shiftStartHHMM, formatShiftIntervalRange, sortShiftsForBadges, shiftDonePrefix, formatGlobalLine, canEditDay, openDay } = context;

  function updateBadgesCols(box) {
    // v6: hard 2 columns are controlled by CSS (#calGrid.is-week .cal-badges)
    // leaving this as no-op to avoid accidental 1-col overrides.
    return;
  }

  let _colsRaf = 0;
  function scheduleColsUpdate() {
    if (_colsRaf) cancelAnimationFrame(_colsRaf);
    _colsRaf = requestAnimationFrame(() => {
      _colsRaf = 0;
      document.querySelectorAll(".cal.is-week .cal-badges").forEach(updateBadgesCols);
    });
  }
  window.addEventListener("resize", scheduleColsUpdate);
  window.addEventListener("orientationchange", scheduleColsUpdate);

  function renderWeek(ws) {
    try {
      // No month "expand" mechanics in week view
      collapseExpanded();

      wireGlobalCollapse();
      el.grid.innerHTML = "";

      const body = document.createElement("div");
      body.className = "cal-body";

      const todayStr = ymd(new Date());

      for (let i = 0; i < 7; i++) {
        const d = addDays(ws, i);
        const dateStr = ymd(d);

        const cell = document.createElement("button");
        cell.type = "button";
        cell.className =
          "cal-cell" +
          (dateStr === todayStr ? " cal-cell--today" : "") +
          (dateStr === runtime.selectedDate ? " cal-cell--selected" : "");
        cell.setAttribute("data-date", dateStr);

        // Ideal header: weekday + date + meta
        const top = document.createElement("div");
        top.className = "cal-weektop";

        const left = document.createElement("div");
        left.className = "minw-0";
        left.innerHTML = `
          <div class="cal-weekname">${escapeHtml(WEEKDAYS[i])}</div>
          <div class="cal-weekdate">${pad2(d.getDate())}.${pad2(d.getMonth()+1)}</div>
        `;

        const meta = document.createElement("div");
        meta.className = "cal-daymeta";
        const dayList = filterForCalendar(runtime.shiftsByDate.get(dateStr) || [], dateStr);
        const hasClosed = dayList.some((item) => shiftIsClosed(item));
        if (dayList.length) meta.textContent = hasClosed ? `✓ ${dayList.length} смен` : `${dayList.length} смен`;
        else meta.textContent = "";

        top.appendChild(left);
        top.appendChild(meta);

        cell.appendChild(top);

        const box = document.createElement("div");
        box.className = "cal-badges";
        const _r = renderCellBadges(dateStr, box, { isWeek: true });
        cell.classList.toggle('is-empty', !!(_r && _r.isEmpty));
        cell.appendChild(box);

        // Week is already readable: click opens day immediately
        cell.addEventListener("click", (e) => {
          e.preventDefault();
          e.stopPropagation();
          selectDate(dateStr, { noExpand: true });
          openDay(dateStr);
        });

        body.appendChild(cell);
      }

      el.grid.appendChild(body);
      scheduleColsUpdate();
    }
    catch (e) {
      console.error(e);
      toast("Ошибка в renderWeek: " + (e?.message || e), "err");
      throw e;
    }
  }


  function buildIndex() {
    runtime.shiftsByDate = new Map();
    runtime.salaryByDate = new Map();

    const list = (runtime.calendarScope === "global") ? runtime.globalShifts : runtime.shifts;

    const sorted = sortShiftsForBadges(list);

      for (const s of sorted) {
      const date = s.date || s.shift_date || s.day;
      if (!date) continue;

      if (!runtime.shiftsByDate.has(date)) runtime.shiftsByDate.set(date, []);
      runtime.shiftsByDate.get(date).push(s);

    }

    for (const [d, arr] of runtime.shiftsByDate.entries()) {
      arr.sort((a, b) => {
        const at = (a.interval?.start_time || a.shift_interval?.start_time || a.start_time || "");
        const bt = (b.interval?.start_time || b.shift_interval?.start_time || b.start_time || "");
        return String(at).localeCompare(String(bt));
      });
    }
  }

  function defaultSelectedDateForMonth() {
    const monthPrefix = ym(runtime.curMonth);
    const today = ymd(new Date());
    if (String(today).startsWith(monthPrefix)) return today;

    // first day with runtime.shifts in this month
    const keys = Array.from(runtime.shiftsByDate.keys()).filter(k => String(k).startsWith(monthPrefix)).sort();
    if (keys.length) return keys[0];

    return `${monthPrefix}-01`;
  }

  function selectDate(dateStr, { noExpand = false } = {}) {
    if (!dateStr) return;
    runtime.selectedDate = dateStr;

    // update selected style
    document.querySelectorAll('.cal-cell--selected').forEach(x => x.classList.remove('cal-cell--selected'));
    const esc = (window.CSS && CSS.escape) ? CSS.escape(String(dateStr)) : String(dateStr).replace(/"/g, "\"");
    const cell = document.querySelector(`.cal-cell[data-date="${esc}"]`);
    if (cell) cell.classList.add('cal-cell--selected');


    // optionally expand the cell on desktop for readability
    if (!noExpand && cell) {
      if (expandedDate !== dateStr) expandCell(cell, dateStr);
    }
  }

  function uniqAssignedPeopleCount(shiftsList) {
    const set = new Set();
    for (const s of (shiftsList || [])) {
      const assigns = (s.assignments || s.shift_assignments || []);
      for (const a of assigns) {
        const id = a.member_user_id ?? a.user_id ?? a.id;
        if (id != null) set.add(String(id));
      }
    }
    return set.size;
  }

  function countAssignments(shiftsList) {
    let n = 0;
    for (const s of (shiftsList || [])) {
      const assigns = (s.assignments || s.shift_assignments || []);
      n += (assigns?.length || 0);
    }
    return n;
  }

  function sumMySalary(shiftsList) {
    let total = 0;
    let has = false;
    for (const s of (shiftsList || [])) {
      const sal = Number(s?.my_salary);
      if (shouldShowDemoSalaryValue(sal)) { total += sal; has = true; }
    }
    return has ? total : null;
  }

  function hhmmToMin(hhmm) {
    const s = toHHMM(hhmm);
    if (!/^\d{2}:\d{2}$/.test(s)) return null;
    const h = Number(s.slice(0,2));
    const m = Number(s.slice(3,5));
    if (!Number.isFinite(h) || !Number.isFinite(m)) return null;
    return h*60 + m;
  }

  function timelineRowLabel(s) {
    // In "global" scope: Venue • HH:MM
    if (runtime.calendarScope === 'global') {
      const venueName = s?.venue?.name || 'Заведение';
      const t = shiftStartHHMM(s);
      return t ? `${venueName} • ${t}` : venueName;
    }
    // In venue scope: HH:MM
    return shiftStartHHMM(s);
  }

  function renderDayTimeline(shiftsList) {
    if (!shiftsList || !shiftsList.length) return '';

    // group by interval (and by venue in global scope)
    const groups = new Map();
    for (const s of shiftsList) {
      const intervalId = shiftIntervalId(s);
      const venueKey = (runtime.calendarScope === 'global') ? String(s?.venue_id ?? s?.venue?.id ?? 'v') : 'v';
      const key = `${venueKey}:${intervalId}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(s);
    }

    const items = [];
    for (const arr of groups.values()) {
      const s0 = arr[0] || {};
      const i = s0.interval || s0.shift_interval || {};
      const st = toHHMM(i.start_time || s0.start_time || '');
      const et = toHHMM(i.end_time || s0.end_time || '');
      const stMin = hhmmToMin(st);
      const etMin = hhmmToMin(et);

      const c = colorForInterval(shiftIntervalId(s0));
      const rgb = hexToRgbTriplet(c);

      let leftPct = 0;
      let widthPct = 100;
      if (stMin != null && etMin != null && etMin >= stMin) {
        leftPct = (stMin / 1440) * 100;
        widthPct = Math.max(2, ((etMin - stMin) / 1440) * 100);
      }

      const assigns = (runtime.calendarScope === 'global') ? null : countAssignments(arr);
      const people = (runtime.calendarScope === 'global') ? null : uniqAssignedPeopleCount(arr);
      let meta = '';
      if (arr.some((item) => shiftIsClosed(item))) meta = '✓ закрыта';
      else if (people != null && people > 0) meta = `${people} чел.`;
      else if (assigns != null && assigns > 0) meta = `${assigns} назнач.`;

      const label = (st && et)
        ? formatShiftIntervalRange(st, et)
        : (st || timelineRowLabel(s0) || '');

      items.push({ stMin: stMin ?? 9999, leftPct, widthPct, rgb, label, meta });
    }

    items.sort((a, b) => a.stMin - b.stMin);

    const rows = items.map(it => `
      <div class="timeline__row">
        <div class="timeline__time">${escapeHtml(it.label)}</div>
        <div class="timeline__track">
          <div class="timeline__seg" style="--left:${it.leftPct}%;--w:${it.widthPct}%;--line-rgb:${it.rgb}"></div>
        </div>
        <div class="timeline__meta">${escapeHtml(it.meta || '')}</div>
      </div>
    `).join('');

    return `
      <div class="timeline">
        <div class="timeline__axis">
          <div>00</div><div>06</div><div>12</div><div>18</div><div>24</div>
        </div>
        <div class="timeline__rows">${rows}</div>
      </div>
    `;
  }

  function renderDayPanel(dateStr) {
    if (!el.dayPanel) return;

    const listAll = runtime.shiftsByDate.get(dateStr) || [];
    const list = filterForCalendar(listAll, dateStr);
    const allowEdit = canEditDay(dateStr);

    const scopeLabel = (runtime.calendarScope === 'global') ? 'Общий' : (runtime.showAllOnCalendar ? 'Все' : 'Мои');

    if (!list.length) {
      el.dayPanel.innerHTML = `
        <div class="card daypanel-card">
          <div class="daypanel__head">
            <div class="daypanel__title">
              <b>${escapeHtml(formatDateRuNoG(dateStr))}</b>
              <div class="muted">Режим: ${escapeHtml(scopeLabel)}</div>
            </div>
          </div>
          <div class="daypanel__empty muted">На этот день нет смен в выбранном режиме.</div>
        </div>
      `;
      return;
    }

    const shiftsCount = list.length;
    const people = (runtime.calendarScope === 'global') ? null : uniqAssignedPeopleCount(list);
    const assigns = (runtime.calendarScope === 'global') ? null : countAssignments(list);
    const closedCount = list.filter((item) => shiftIsClosed(item)).length;

    const kpis = [
      `<div class="kpi">Смен: <span class="muted">${shiftsCount}</span></div>`,
    ];
    if (people != null) kpis.push(`<div class="kpi">Людей: <span class="muted">${people}</span></div>`);
    if (assigns != null) kpis.push(`<div class="kpi">Назначений: <span class="muted">${assigns}</span></div>`);
    if (closedCount > 0) kpis.push(`<div class="kpi shift-done-badge">✓ закрыто: <span>${closedCount}</span></div>`);

    el.dayPanel.innerHTML = `
      <div class="card daypanel-card">
        <div class="daypanel__head">
          <div class="daypanel__title">
            <b>${escapeHtml(formatDateRuNoG(dateStr))}</b>
            <div class="muted">Режим: ${escapeHtml(scopeLabel)}</div>
          </div>
          <div class="daypanel__actions">
            <button class="btn" id="btnDayOpen">Открыть</button>
            ${allowEdit ? `<button class="btn primary" id="btnDayEdit">Редактировать</button>` : ``}
          </div>
        </div>
        <div class="kpirow">${kpis.join('')}</div>
        ${renderDayTimeline(list)}
        <div class="daypanel__hint muted">Клик по дню в календаре обновляет график. Повторный клик открывает детали.</div>
      </div>
    `;

    document.getElementById('btnDayOpen')?.addEventListener('click', () => openDay(dateStr));
    document.getElementById('btnDayEdit')?.addEventListener('click', () => openDay(dateStr));
  }

  function monthTitle(d) {
    const dt = new Date(d);
    const month = dt.toLocaleString((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"), { month: "long" });
    const year = dt.getFullYear();
    const s = `${month} ${year}`;
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function formatDateRuNoG(iso) {
    const x = String(iso);
    const dt = new Date(x.length === 10 ? x + "T00:00:00" : x);
    const dd = String(dt.getDate()).padStart(2, "0");
    const mm = String(dt.getMonth() + 1).padStart(2, "0");
    const yyyy = dt.getFullYear();
    return `${dd}.${mm}.${yyyy}`;
  }

  function shiftHasMyAssignment(s, myId) {
    if (!myId) return false;

    const directUid = s?.member_user_id ?? s?.user_id ?? s?.user?.id;
    if (directUid !== undefined && directUid !== null && String(directUid) === String(myId)) return true;

    const assigns = (s?.assignments || s?.shift_assignments || []);
    if (!Array.isArray(assigns) || !assigns.length) return false;

    for (const a of assigns) {
      const uid = a?.member_user_id ?? a?.user_id ?? a?.user?.id;
      if (uid !== undefined && uid !== null && String(uid) === String(myId)) return true;
    }
    return false;
  }

  function filterForCalendar(listAll, dateStr) {
    const myId = runtime.me?.id ?? null;

    // "Общий" (multi-venue): /me/shifts already returns only current user assignments.
    if (runtime.calendarScope === "global") {
      const arr = Array.isArray(listAll) ? listAll : [];
      if (!myId) return [];
      return arr;
    }

    const canUseAllMode = runtime.canEdit || DEMO_MODE;

    // В DEMO/режиме редактора переключатель «Все» должен реально показывать все интервалы дня,
    // а не только назначения текущего пользователя.
    if (canUseAllMode && runtime.calendarScope === "venue" && runtime.showAllOnCalendar) {
      return Array.isArray(listAll) ? listAll : [];
    }

    // staff w/o edit -> only mine
    if (!runtime.canEdit && myId) {
      return (Array.isArray(listAll) ? listAll : [])
        .map((s) => {
          const assigns = (s.assignments || s.shift_assignments || []).filter((a) => (a.member_user_id ?? a.user_id) === myId);
          if (!assigns.length) return null;
          return { ...s, assignments: assigns };
        })
        .filter(Boolean);
    }

    // editor toggle -> mine
    if (runtime.canEdit && !runtime.showAllOnCalendar && myId) {
      return (Array.isArray(listAll) ? listAll : [])
        .map((s) => {
          const assigns = (s.assignments || s.shift_assignments || []).filter((a) => (a.member_user_id ?? a.user_id) === myId);
          if (!assigns.length) return null;
          return { ...s, assignments: assigns };
        })
        .filter(Boolean);
    }

    return Array.isArray(listAll) ? listAll : [];
  }

  // Формат строки для ALL-режима: "Имя/логин — HH:MM"
  function formatAllModeLine(shift, assignment) {
    const who = assignment ? displayPerson(assignment) : pickShortName(shift);
    const t = shiftStartHHMM(shift);
    return t ? `${who} — ${t}` : `${who}`;
  }


  function hexToRgbTriplet(hex) {
    const h = String(hex || "").replace("#", "");
    if (h.length !== 6) return "0 0 0";
    const r = parseInt(h.slice(0,2), 16);
    const g = parseInt(h.slice(2,4), 16);
    const b = parseInt(h.slice(4,6), 16);
    return `${r} ${g} ${b}`;
  }

  function makeCalLine(text, shift) {
    const line = document.createElement("div");
    line.className = "cal-line" + (shiftIsClosed(shift) ? " cal-line--done" : "");

    const span = document.createElement("span");
    span.className = "cal-line__text";
    span.textContent = text;
    line.appendChild(span);

    // Tooltip on desktop (helps when ellipsis kicks in)
    try { line.title = text; } catch {}

    // colorize by interval
    const c = colorForInterval(shiftIntervalId(shift));
    line.dataset.icolor = "1";
    line.style.setProperty("--line-rgb", hexToRgbTriplet(c));
    return line;
  }
  function shiftHasAssignees(shift) {
    const assigns = shift?.assignments || shift?.shift_assignments || [];
    if (Array.isArray(assigns) && assigns.length) return true;
    const c1 = Number(shift?.assigned_count);
    const c2 = Number(shift?.assignees_count);
    const c3 = Number(shift?.members_count);
    return (Number.isFinite(c1) && c1 > 0) || (Number.isFinite(c2) && c2 > 0) || (Number.isFinite(c3) && c3 > 0);
  }

  function shiftIsClosed(shift) {
    const status = String(shift?.report_status || shift?.report?.status || "").toUpperCase();
    return !!shift?.report_closed || status === "CLOSED";
  }

  function makeCalDot({ color, filled = false, label = "", title = "" } = {}) {
    const dot = document.createElement("div");
    dot.className = "cal-dot" + (filled ? " is-filled" : "");
    dot.style.setProperty("--dot", color || "var(--muted)");
    if (label) {
      dot.classList.add("is-more");
      dot.textContent = label;
    }
    if (title) {
      try { dot.title = title; } catch {}
      dot.setAttribute("aria-label", title);
    }
    return dot;
  }


  // dotrow removed: calendar uses only text labels (cal-line)

  function calcExpandedAllMonthMaxLines(box) {
    try {
      const cell = box?.closest?.(".cal-cell");
      if (!cell) return 10;

      const boxStyles = window.getComputedStyle(box);
      const gap = parseFloat(boxStyles.rowGap || boxStyles.gap || "4") || 4;

      const probe = document.createElement("div");
      probe.className = "cal-line cal-line--probe";
      probe.innerHTML = '<span class="cal-line__text">Probe — 11:00</span>';
      document.body.appendChild(probe);
      const lineH = probe.getBoundingClientRect().height || 18;
      probe.remove();

      const topH = cell.querySelector?.(".cal-daynum")?.getBoundingClientRect()?.height || 18;
      const cellH = cell.getBoundingClientRect().height || 0;

      const cs = window.getComputedStyle(cell);
      const padT = parseFloat(cs.paddingTop || "0") || 0;
      const padB = parseFloat(cs.paddingBottom || "0") || 0;

      const available = Math.max(0, cellH - topH - padT - padB - 10);
      const per = lineH + gap;
      const n = per > 0 ? Math.floor((available + gap) / per) : 10;

      return Math.max(6, Math.min(16, n));
    } catch {
      return 10;
    }
  }

  function rerenderMonthCellBadges(cell, dateISO, { forceText = false, expanded = false } = {}) {
    try { if (el?.grid?.classList?.contains("is-week")) return; } catch {}
    const box = cell?.querySelector?.(".cal-badges");
    if (!box) return;

    box.innerHTML = "";
    box.classList.remove("cal-badges--dots");
    renderCellBadges(dateISO, box, { isWeek: false, forceText, expanded });
  }

  let expandedDate = null;
  let expandWired = false;

  function collapseExpanded() {
    if (!expandedDate) return;
    const dateISO = expandedDate;
    const prev = document.querySelector(`.cal-cell[data-date="${expandedDate}"]`);
    if (prev) {
      // restore dots in month "All"
      try { rerenderMonthCellBadges(prev, dateISO, { forceText: false, expanded: false }); } catch {}
      prev.classList.remove("is-expanded", "cal-cell--expanded-layout");
    }
    expandedDate = null;
  }


  function expandCell(cell, dateISO) {
    collapseExpanded();
    expandedDate = dateISO;

    cell.classList.add("cal-cell--expanded-layout");

    // month "All": show text badges inside expanded cell (instead of dots)
    try { rerenderMonthCellBadges(cell, dateISO, { forceText: true, expanded: true }); } catch {}

    requestAnimationFrame(() => {
      cell.classList.add("is-expanded");
      // re-render after layout settles to compute max lines
      requestAnimationFrame(() => {
        try { rerenderMonthCellBadges(cell, dateISO, { forceText: true, expanded: true }); } catch {}
      });
    });
  }


  function wireGlobalCollapse() {
    if (expandWired) return;
    expandWired = true;

    document.addEventListener("click", (e) => {
      const inCell = e.target.closest?.(".cal-cell");
      const inModal = e.target.closest?.(".modal__panel");
      if (!inCell && !inModal) collapseExpanded();
    });
  }

  function renderCellBadges(dateStr, box, { isWeek = false, forceText = false, expanded = false } = {}) {
    const listAll = runtime.shiftsByDate.get(dateStr) || [];
    const list = filterForCalendar(listAll, dateStr);
    const pastDay = isPastDay(dateStr);

    // limits per view
    const maxMine = isWeek ? 10 : 3;
    const maxAll = isWeek ? 12 : 2;
  // MONTH + ALL: show interval dots (no text), 4 max
  if (runtime.showAllOnCalendar && !isWeek && !forceText && runtime.calendarScope !== "global") {
    box.classList.add("cal-badges--dots");

    const sorted = sortShiftsForBadges(list);

    // unique by interval, preserve time order
    const byInterval = new Map(); // intervalId -> {shift, assigned}
    for (const s of sorted) {
      const iidRaw = shiftIntervalId(s);
      const iid = (iidRaw === undefined || iidRaw === null) ? "" : String(iidRaw);
      if (!iid) continue;

      const assigned = shiftHasAssignees(s);
      if (!byInterval.has(iid)) byInterval.set(iid, { shift: s, assigned });
      else byInterval.get(iid).assigned = byInterval.get(iid).assigned || assigned;
    }

    const arr = Array.from(byInterval.values());
    const total = arr.length;

    const maxDots = 4;

    if (total <= maxDots) {
      for (const it of arr) {
        const color = colorForInterval(shiftIntervalId(it.shift));
        box.appendChild(makeCalDot({ color, filled: !!it.assigned }));
      }
      return;
    }

    // show first 3, 4th = "+N"/"…"
    for (let i = 0; i < 3; i++) {
      const it = arr[i];
      const color = colorForInterval(shiftIntervalId(it.shift));
      box.appendChild(makeCalDot({ color, filled: !!it.assigned }));
    }

    const more = total - 3;
    const label = (more <= 9) ? `+${more}` : "…";
    box.appendChild(makeCalDot({ color: "var(--muted)", filled: false, label, title: `+${more}` }));
    return;
  }


    if (!runtime.showAllOnCalendar) {
      let shown = 0;
      const sorted = sortShiftsForBadges(list);

      for (const s of sorted) {
        let txt = "";

        if (runtime.calendarScope === "global") {
          const venueName = s?.venue?.name || "Заведение";
          const t = shiftStartHHMM(s) || (s?.interval?.start_time ? String(s.interval.start_time).slice(0, 5) : "");

          txt = `${shiftDonePrefix(s)}${t ? `${venueName} • ${t}` : `${venueName}`}`;
        } else {
          txt = `${shiftDonePrefix(s)}${shiftStartHHMM(s) || ""}`;
        }

        if (txt && txt !== "—") {
          box.appendChild(makeCalLine(txt, s));
          shown++;
        }
        if (shown >= maxMine) break;
      }

      if (shown > 0 && list.length > shown) {
        const more = document.createElement("div");
        more.className = "cal-line muted cal-line--more";
        more.textContent = `+${list.length - shown}`;
        box.appendChild(more);
      }
      return;
    }

    // ALL mode
    const lines = [];

    const sorted2 = sortShiftsForBadges(list);

    for (const s of sorted2) {
      if (runtime.calendarScope === "global") {
        lines.push({ text: formatGlobalLine(s), shift: s });
        if (lines.length >= maxAll) break;
        continue;
      }

      const assigns = (s.assignments || s.shift_assignments || []);
      if (assigns.length) {
        for (const a of assigns) {
          lines.push({ text: formatAllModeLine(s, a), shift: s });
          if (lines.length >= maxAll) break;
        }
      } else {
        lines.push({ text: formatAllModeLine(s, null), shift: s });
      }

      if (lines.length >= maxAll) break;
    }

    for (const item of lines) box.appendChild(makeCalLine(item.text, item.shift));

    const totalLines = list.reduce((acc, s) => {
      const assigns = (s.assignments || s.shift_assignments || []);
      return acc + Math.max(1, assigns.length);
    }, 0);

    if (lines.length > 0 && totalLines > maxAll) {
      const more = document.createElement("div");
      more.className = "cal-line muted cal-line--more";
      more.textContent = `+${totalLines - maxAll}`;
      box.appendChild(more);
    }
  }

  function renderMonth() {
    try {
    wireGlobalCollapse();

    el.grid.classList.remove("is-week");

    el.monthLabel.textContent = runtime.nightShiftsEnabled ? `${monthTitle(runtime.curMonth)} · ${shiftSlotLabel(runtime.selectedShiftSlot)}` : monthTitle(runtime.curMonth);
    el.grid.innerHTML = "";

    const head = document.createElement("div");
    head.className = "cal-head";
    for (const wd of WEEKDAYS) {
      const c = document.createElement("div");
      c.className = "cal-hcell";
      c.textContent = wd;
      head.appendChild(c);
    }
    el.grid.appendChild(head);

    const body = document.createElement("div");
    body.className = "cal-body";

    const first = new Date(runtime.curMonth);
    const jsDow = first.getDay();
    const mondayBased = (jsDow + 6) % 7;
    const start = new Date(first);
    start.setDate(first.getDate() - mondayBased);

    const todayStr = ymd(new Date());

    for (let i = 0; i < 42; i++) {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      const inMonth = d.getMonth() === runtime.curMonth.getMonth();
      const dateStr = ymd(d);

      const cell = document.createElement("button");
      cell.type = "button";
      cell.className =
        "cal-cell" +
        (inMonth ? "" : " cal-cell--out") +
        (dateStr === todayStr ? " cal-cell--today" : "") +
        (dateStr === runtime.selectedDate ? " cal-cell--selected" : "");
      cell.setAttribute("data-date", dateStr);

      const top = document.createElement("div");
      top.className = "cal-daynum";
      top.textContent = String(d.getDate());
      cell.appendChild(top);

      const box = document.createElement("div");
      box.className = "cal-badges";

      renderCellBadges(dateStr, box, { isWeek: false });

      cell.appendChild(box);

      // 1-й клик: expand, 2-й клик: modal
      cell.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();

        selectDate(dateStr, { noExpand: true });

        if (expandedDate !== dateStr) {
          expandCell(cell, dateStr);
          return;
        }

        collapseExpanded();
        openDay(dateStr);
      });

      body.appendChild(cell);
    }

    el.grid.appendChild(body);
  } catch (e) {
      console.error(e);
      toast("Ошибка в renderMonth: " + (e?.message || e), "err");
      throw e;
    }
  }

  return { renderWeek, buildIndex, defaultSelectedDateForMonth, selectDate, monthTitle, formatDateRuNoG, filterForCalendar, shiftIsClosed, renderMonth };
}
