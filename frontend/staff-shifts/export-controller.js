export function createStaffShiftExportController(context) {
  const { runtime, api, toast, el, pad2, ym, ymd, addDays, startOfWeek, weekTitle, WEEKDAYS, colorForInterval, fioInitials, displayPerson, shiftIntervalTitle, shiftIntervalId, shiftStartHHMM, sortShiftsForBadges, hasAssignments, monthTitle, filterForCalendar } = context;

  const exportState = {
    canvas: null,
    meta: null,
    pngBlob: null,
    previewUrl: "",
    filenameBase: "schedule",
  };

  function releaseExportPreviewUrl() {
    if (exportState.previewUrl) {
      try { URL.revokeObjectURL(exportState.previewUrl); } catch {}
      exportState.previewUrl = "";
    }
  }

  function resetExportState() {
    releaseExportPreviewUrl();
    exportState.canvas = null;
    exportState.meta = null;
    exportState.pngBlob = null;
    exportState.filenameBase = "schedule";
  }

  function closeExportModal() {
    el.exportModal?.classList.remove("open");
    releaseExportPreviewUrl();
    if (el.exportPreviewImage) {
      el.exportPreviewImage.src = "";
      el.exportPreviewImage.classList.add("hidden");
    }
  }

  el.exportModal?.querySelectorAll("[data-close-export]")?.forEach((btn) => btn.addEventListener("click", closeExportModal));
  el.exportModal?.querySelector(".modal__backdrop")?.addEventListener("click", closeExportModal);

  function setExportButtonsDisabled(disabled) {
    [
      el.btnExportShare,
      el.btnExportTelegram,
      el.btnExportDownload,
    ].forEach((btn) => {
      if (btn) btn.disabled = !!disabled;
    });
  }

  function setExportStatus(text, { error = false } = {}) {
    if (!el.exportStatus) return;
    el.exportStatus.textContent = text || "";
    el.exportStatus.classList.toggle("err", !!error);
  }

  function currentUserLabel() {
    const full = (runtime.me?.full_name || "").trim();
    const fi = fioInitials(full);
    if (fi) return fi;
    const short = (runtime.me?.short_name || "").trim();
    if (short) return short;
    const username = (runtime.me?.tg_username || "").trim();
    if (username) return username.startsWith("@") ? username : `@${username}`;
    return "Я";
  }

  function currentRangeContext() {
    if (runtime.calendarView === "week") {
      const start = runtime.curWeekStart ? startOfWeek(runtime.curWeekStart) : startOfWeek(new Date());
      const end = addDays(start, 6);
      const dates = [];
      for (let i = 0; i < 7; i++) dates.push(ymd(addDays(start, i)));
      return {
        view: "week",
        periodStart: ymd(start),
        periodEnd: ymd(end),
        periodLabel: weekTitle(start),
        periodDates: dates,
        gridDates: dates,
      };
    }

    const first = new Date(runtime.curMonth);
    first.setDate(1);
    const last = new Date(first.getFullYear(), first.getMonth() + 1, 0);
    const start = new Date(first);
    start.setDate(first.getDate() - ((first.getDay() + 6) % 7));
    const gridDates = [];
    for (let i = 0; i < 42; i++) {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      gridDates.push(ymd(d));
    }
    const periodDates = [];
    for (let d = new Date(first); d <= last; d = addDays(d, 1)) periodDates.push(ymd(d));
    return {
      view: "month",
      periodStart: ymd(first),
      periodEnd: ymd(last),
      periodLabel: monthTitle(first),
      periodDates,
      gridDates,
    };
  }

  function getExportShiftSlot() {
    try {
      if (typeof runtime.selectedShiftSlot !== "undefined") {
        const direct = String(runtime.selectedShiftSlot || "DAY").toUpperCase();
        if (direct === "NIGHT") return "NIGHT";
      }
    } catch {}
    try {
      const fromUrl = String(new URLSearchParams(location.search).get("shift_slot") || "").toUpperCase();
      if (fromUrl === "NIGHT") return "NIGHT";
    } catch {}
    try {
      const stored = String(localStorage.getItem("axelio.staff_shifts.shift_slot") || localStorage.getItem("axelio.shift_slot") || "").toUpperCase();
      if (stored === "NIGHT") return "NIGHT";
    } catch {}
    return "DAY";
  }

  function exportShiftSlotLabel(slot = getExportShiftSlot()) {
    return String(slot || "DAY").toUpperCase() === "NIGHT" ? "НОЧНЫЕ СМЕНЫ" : "ДНЕВНЫЕ СМЕНЫ";
  }

  function selectedIntervalTitles() {
    const byId = new Map((Array.isArray(runtime.intervals) ? runtime.intervals : []).map((it) => [String(it?.id ?? ""), it]));
    return Array.from(runtime.selectedIntervalIds)
      .map((id) => byId.get(String(id))?.title)
      .filter(Boolean);
  }

  function buildLocalExportMetadata() {
    const range = currentRangeContext();
    const intervalTitles = selectedIntervalTitles();
    const parts = [range.view === "month" ? "Месяц" : "Неделя"];
    if (runtime.calendarScope === "global") parts.push("Общий режим");
    else parts.push(runtime.showAllOnCalendar ? "Все сотрудники" : "Только мои");
    if (intervalTitles.length) parts.push(`Интервалы: ${intervalTitles.join(", ")}`);
    if (runtime.unstaffedOnly) parts.push("Только без назначений");

    const venueLabel = runtime.calendarScope === "global" ? "Мой график" : (runtime.currentVenueName || "Заведение");
    return {
      venue_id: Number(runtime.venueId || 0) || 0,
      venue_name: venueLabel,
      view: range.view,
      period_start: range.periodStart,
      period_end: range.periodEnd,
      period_label: range.periodLabel,
      filters_text: parts.join(" • "),
      interval_titles: intervalTitles,
      staffing_state: runtime.unstaffedOnly ? "unstaffed" : "all",
      shift_slot: getExportShiftSlot(),
      logo_url: null,
      app_logo_url: "/logo.png",
      deep_link_path: "/staff-shifts.html",
      share_title: `График смен · ${venueLabel}`,
      share_text: `${venueLabel}\n${range.periodLabel}\n${parts.join(" • ")}`,
    };
  }

  async function getExportMetadata() {
    const fallback = buildLocalExportMetadata();
    if (!runtime.venueId || runtime.calendarScope === "global") return fallback;

    try {
      const range = currentRangeContext();
      const q = new URLSearchParams();
      q.set("view", range.view);
      if (range.view === "week") q.set("week_start", range.periodStart);
      else {
        const dt = new Date(`${range.periodStart}T00:00:00`);
        q.set("month", `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}`);
      }
      const ids = Array.from(runtime.selectedIntervalIds)
        .map((x) => Number(x))
        .filter((x) => Number.isInteger(x) && x > 0)
        .sort((a, b) => a - b);
      for (const id of ids) q.append("interval_ids", String(id));
      if (runtime.unstaffedOnly) q.set("staffing_state", "unstaffed");
      q.set("shift_slot", getExportShiftSlot());
      const meta = await api(`/venues/${encodeURIComponent(runtime.venueId)}/shifts/export-metadata?${q.toString()}`);
      return { ...fallback, ...(meta || {}) };
    } catch {
      return fallback;
    }
  }

  function visibleShiftsForDate(dateStr) {
    return filterForCalendar(runtime.shiftsByDate.get(dateStr) || [], dateStr);
  }

  function countVisibleStats(dateList) {
    let total = 0;
    let staffed = 0;
    let unstaffed = 0;
    for (const dateStr of dateList || []) {
      for (const shift of visibleShiftsForDate(dateStr)) {
        total += 1;
        if (hasAssignments(shift)) staffed += 1;
        else unstaffed += 1;
      }
    }
    return { total, staffed, unstaffed };
  }

  function buildExportLinesForDate(dateStr) {
    const list = sortShiftsForBadges(visibleShiftsForDate(dateStr));
    const lines = [];
    const meLabel = currentUserLabel();

    for (const shift of list) {
      const color = colorForInterval(shiftIntervalId(shift));
      const intervalTitle = shiftIntervalTitle(shift);
      const startLabel = shiftStartHHMM(shift) || "—";

      if (runtime.calendarScope === "global") {
        const venueLabel = shift?.venue?.name || runtime.currentVenueName || "Заведение";
        lines.push({ color, text: `${venueLabel} — ${startLabel}` });
        continue;
      }

      if (runtime.showAllOnCalendar) {
        const assigns = Array.isArray(shift?.assignments) && shift.assignments.length ? shift.assignments : [null];
        for (const assignment of assigns) {
          const person = assignment ? displayPerson(assignment) : "Без назначения";
          const position = assignment?.position_title ? ` · ${assignment.position_title}` : "";
          lines.push({ color, text: `${intervalTitle} — ${startLabel} — ${person}${position}` });
        }
        continue;
      }

      const myAssignment = Array.isArray(shift?.assignments) && shift.assignments.length ? shift.assignments[0] : null;
      const person = myAssignment ? displayPerson(myAssignment) : meLabel;
      const position = myAssignment?.position_title ? ` · ${myAssignment.position_title}` : "";
      lines.push({ color, text: `${intervalTitle} — ${startLabel} — ${person}${position}` });
    }

    return lines;
  }

  function sanitizeFilePart(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[^a-z0-9а-яё_-]+/gi, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "") || "schedule";
  }

  function buildExportFilenameBase(meta) {
    const range = currentRangeContext();
    const venuePart = sanitizeFilePart(meta?.venue_name || runtime.currentVenueName || "schedule");
    const periodPart = range.view === "week" ? `${range.periodStart}_${range.periodEnd}` : range.periodStart.slice(0, 7);
    const slotPart = sanitizeFilePart(String(meta?.shift_slot || getExportShiftSlot()).toLowerCase());
    return `schedule_${venuePart}_${periodPart}_${slotPart}`;
  }

  function drawRoundRect(ctx, x, y, w, h, r) {
    const radius = Math.max(0, Math.min(r, w / 2, h / 2));
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + w, y, x + w, y + h, radius);
    ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius);
    ctx.arcTo(x, y, x + w, y, radius);
    ctx.closePath();
  }

  function fillRoundRect(ctx, x, y, w, h, r, fillStyle, strokeStyle = "", lineWidth = 1) {
    drawRoundRect(ctx, x, y, w, h, r);
    if (fillStyle) {
      ctx.fillStyle = fillStyle;
      ctx.fill();
    }
    if (strokeStyle) {
      ctx.strokeStyle = strokeStyle;
      ctx.lineWidth = lineWidth;
      ctx.stroke();
    }
  }

  function truncateCanvasText(ctx, text, maxWidth) {
    const value = String(text || "");
    if (!value) return "";
    if (ctx.measureText(value).width <= maxWidth) return value;
    let result = value;
    while (result.length > 1 && ctx.measureText(`${result}…`).width > maxWidth) result = result.slice(0, -1);
    return `${result}…`;
  }

  function drawBadge(ctx, text, x, y, { fill = "#EEF2FF", color = "#334155" } = {}) {
    ctx.save();
    ctx.font = "600 20px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
    const padX = 16;
    const width = ctx.measureText(text).width + padX * 2;
    fillRoundRect(ctx, x, y, width, 38, 19, fill, "");
    ctx.fillStyle = color;
    ctx.textBaseline = "middle";
    ctx.fillText(text, x + padX, y + 19);
    ctx.restore();
    return width;
  }

  function wrapCanvasText(ctx, text, maxWidth, maxLines = 2) {
    const value = String(text || "").trim();
    if (!value) return [];
    const words = value.split(/\s+/).filter(Boolean);
    const lines = [];
    let current = "";
    for (const word of words) {
      const candidate = current ? `${current} ${word}` : word;
      if (ctx.measureText(candidate).width <= maxWidth || !current) current = candidate;
      else {
        lines.push(current);
        current = word;
      }
    }
    if (current) lines.push(current);
    const visible = lines.slice(0, Math.max(1, maxLines));
    if (lines.length > visible.length) visible[visible.length - 1] = truncateCanvasText(ctx, `${visible[visible.length - 1]} …`, maxWidth);
    return visible;
  }

  function drawWrappedText(ctx, text, x, y, maxWidth, lineHeight, maxLines = 2, color = "#475569", align = "left") {
    const lines = wrapCanvasText(ctx, text, maxWidth, maxLines);
    if (!lines.length) return y;
    ctx.fillStyle = color;
    const prevAlign = ctx.textAlign;
    ctx.textAlign = align;
    const drawX = align === "right" ? x + maxWidth : x;
    for (let i = 0; i < lines.length; i++) ctx.fillText(lines[i], drawX, y + i * lineHeight);
    ctx.textAlign = prevAlign;
    return y + lines.length * lineHeight;
  }

  function getCssVar(name, fallback) {
    try {
      const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return value || fallback;
    } catch {
      return fallback;
    }
  }

  function getExportPalette() {
    return {
      bg: getCssVar("--bg", "#F3F5F9"),
      card: getCssVar("--card", "#FFFFFF"),
      border: getCssVar("--border", "#D9E0EA"),
      text: getCssVar("--text", "#0F172A"),
      muted: getCssVar("--muted", "#64748B"),
      subtle: getCssVar("--surface2", "#E8EDF5"),
      accent: getCssVar("--accent", "#6366F1"),
      accentSoft: getCssVar("--accentSoftBg", "rgba(99,102,241,.12)"),
      shadow: getCssVar("--shadow", "0 10px 24px rgba(11,18,32,.10)"),
    };
  }

  function loadImage(src) {
    return new Promise((resolve) => {
      if (!src) return resolve(null);
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null);
      img.src = src;
    });
  }

  async function loadExportLogo(meta) {
    const preferred = meta?.app_logo_url || "/logo.png";
    const sameOriginUrl = preferred.startsWith("http") ? preferred : new URL(preferred, window.location.origin).toString();
    return loadImage(sameOriginUrl);
  }


  async function renderScheduleExportCanvas(meta) {
    const range = currentRangeContext();
    const isWeek = range.view === "week";
    const padding = isWeek ? 42 : 40;
    const gridGap = isWeek ? 16 : 12;
    const palette = getExportPalette();
    const bg = palette.bg;
    const card = palette.card;
    const border = palette.border;
    const text = palette.text;
    const muted = palette.muted;
    const subtle = palette.subtle;
    const accent = palette.accent;
    const accentSoft = palette.accentSoft;
    const todayIso = ymd(new Date());
    const logo = await loadExportLogo(meta);

    function fillCircle(ctx, cx, cy, r, fillStyle, strokeStyle = "", lineWidth = 1) {
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.closePath();
      ctx.fillStyle = fillStyle;
      ctx.fill();
      if (strokeStyle) {
        ctx.strokeStyle = strokeStyle;
        ctx.lineWidth = lineWidth;
        ctx.stroke();
      }
    }

    function drawHeader(ctx, width, headerY, headerH) {
      fillRoundRect(ctx, padding, headerY, width - padding * 2, headerH, 28, card, border, 1);

      const leftX = padding + 28;
      let textX = leftX;
      const contentTop = headerY + 28;
      if (logo) {
        const size = 64;
        ctx.drawImage(logo, leftX, contentTop + 6, size, size);
        textX = leftX + size + 18;
      }

      const rightBlockW = Math.min(430, Math.max(300, width * 0.30));
      const rightX = width - padding - 28 - rightBlockW;
      const leftMaxW = Math.max(280, rightX - textX - 24);
      const periodLabel = meta?.period_label || range.periodLabel;
      const filtersText = meta?.filters_text || buildLocalExportMetadata().filters_text;
      const venueLabel = meta?.venue_name || runtime.currentVenueName || "График смен";

      ctx.textBaseline = "top";
      ctx.textAlign = "left";
      ctx.fillStyle = text;
      ctx.font = "700 34px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
      ctx.fillText(venueLabel, textX, contentTop + 2);

      ctx.fillStyle = muted;
      ctx.font = "500 20px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
      drawWrappedText(ctx, filtersText, textX, contentTop + 54, leftMaxW, 24, 2, muted, "left");

      const slotLabel = exportShiftSlotLabel(meta?.shift_slot || getExportShiftSlot());
      const slotBadgeW = Math.min(260, Math.max(198, ctx.measureText(slotLabel).width + 42));
      fillRoundRect(ctx, textX, contentTop + 116, slotBadgeW, 42, 21, String(meta?.shift_slot || getExportShiftSlot()).toUpperCase() === "NIGHT" ? "rgba(15,23,42,.96)" : accentSoft, accent, 1.5);
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = String(meta?.shift_slot || getExportShiftSlot()).toUpperCase() === "NIGHT" ? "#E0F2FE" : accent;
      ctx.font = "800 17px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
      ctx.fillText(slotLabel, textX + slotBadgeW / 2, contentTop + 137);
      ctx.textAlign = "left";
      ctx.textBaseline = "top";

      const pillW = 168;
      const pillH = 34;
      fillRoundRect(ctx, rightX + rightBlockW - pillW, headerY + 24, pillW, pillH, 17, accentSoft, "");
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = accent;
      ctx.font = "700 16px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
      ctx.fillText(range.view === "week" ? "НЕДЕЛЯ" : "МЕСЯЦ", rightX + rightBlockW - pillW / 2, headerY + 24 + pillH / 2 + 1);

      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillStyle = text;
      ctx.font = isWeek
        ? "800 48px system-ui, -apple-system, BlinkMacSystemFont, sans-serif"
        : "800 52px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
      const periodLines = wrapCanvasText(ctx, periodLabel, rightBlockW, 2);
      const periodLineHeight = isWeek ? 50 : 54;
      const periodBlockH = Math.max(1, periodLines.length) * periodLineHeight;
      const centeredPeriodTop = headerY + Math.round((headerH - periodBlockH) / 2) + 8;
      const periodTop = Math.max(centeredPeriodTop, headerY + 102);
      for (let i = 0; i < periodLines.length; i++) {
        ctx.fillText(periodLines[i], width - padding - 28, periodTop + i * periodLineHeight);
      }

      ctx.textAlign = "left";
      ctx.textBaseline = "alphabetic";
    }

    function drawStatsRow(ctx, width, statsY, statItems, columns, statsH, gap) {
      const statW = (width - padding * 2 - gap * (columns - 1)) / columns;
      for (let i = 0; i < statItems.length; i++) {
        const row = Math.floor(i / columns);
        const col = i % columns;
        const x = padding + col * (statW + gap);
        const y = statsY + row * (statsH + gap);
        fillRoundRect(ctx, x, y, statW, statsH, 22, card, border, 1);
        ctx.textAlign = "left";
        ctx.textBaseline = "top";
        ctx.fillStyle = muted;
        ctx.font = "600 18px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
        ctx.fillText(statItems[i].title, x + 20, y + 18);
        ctx.fillStyle = text;
        ctx.font = "700 28px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
        ctx.fillText(statItems[i].value, x + 20, y + 42);
      }
    }

    if (isWeek) {
      const width = 1120;
      const headerCardH = 196;
      const statsY = 248;
      const statGap = 14;
      const statsCols = 2;
      const statsH = 82;
      const statsRows = 2;
      const daysTop = statsY + statsRows * statsH + statGap + 28;
      const stats = countVisibleStats(range.periodDates);
      const scopeLabel = runtime.calendarScope === "global" ? "Общий" : (runtime.showAllOnCalendar ? "Все" : "Мои");
      const statItems = [
        { title: "Всего смен", value: String(stats.total) },
        { title: "Укомплектовано", value: String(stats.staffed) },
        { title: "Неукомплектовано", value: String(stats.unstaffed) },
        { title: "Режим", value: scopeLabel },
      ];

      const lineCols = 2;
      const lineGapX = 26;
      const lineGapY = 22;
      const dayCards = range.gridDates.map((dateStr, index) => {
        const dayDate = new Date(`${dateStr}T00:00:00`);
        const lines = buildExportLinesForDate(dateStr);
        const visibleCount = Math.max(1, Math.min(lines.length, 10));
        const rowsCount = Math.max(1, Math.ceil(visibleCount / lineCols));
        const extraH = lines.length > visibleCount ? 26 : 0;
        const cardH = Math.max(132, 86 + rowsCount * lineGapY + extraH);
        return { dateStr, index, dayDate, lines, visibleCount, rowsCount, cardH };
      });

      const daysHeight = dayCards.reduce((sum, item, idx) => sum + item.cardH + (idx ? gridGap : 0), 0);
      const footerH = 42;
      const height = daysTop + daysHeight + footerH;
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Canvas not supported");

      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, width, height);

      drawHeader(ctx, width, 32, headerCardH);
      drawStatsRow(ctx, width, statsY, statItems, statsCols, statsH, statGap);

      let y = daysTop;
      for (const item of dayCards) {
        const x = padding;
        const dayDate = item.dayDate;
        const dateLabel = `${WEEKDAYS[item.index]} · ${pad2(dayDate.getDate())}.${pad2(dayDate.getMonth() + 1)}`;
        const dayW = width - padding * 2;
        fillRoundRect(ctx, x, y, dayW, item.cardH, 22, card, item.dateStr === todayIso ? accent : border, item.dateStr === todayIso ? 2 : 1);

        ctx.fillStyle = text;
        ctx.textBaseline = "top";
        ctx.font = "700 24px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
        ctx.fillText(dateLabel, x + 20, y + 18);

        const countLabel = item.lines.length ? `${item.lines.length} смен` : "Нет смен";
        ctx.fillStyle = muted;
        ctx.font = "600 18px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
        const countWidth = ctx.measureText(countLabel).width;
        ctx.fillText(countLabel, x + dayW - 20 - countWidth, y + 22);

        if (!item.lines.length) {
          ctx.fillStyle = muted;
          ctx.font = "500 18px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
          ctx.fillText("Нет смен", x + 20, y + 66);
        } else {
          const colInnerPad = 20;
          const lineTop = y + 60;
          const colW = (dayW - colInnerPad * 2 - lineGapX) / lineCols;
          const textMaxW = colW - 20;
          const visible = item.lines.slice(0, item.visibleCount);
          ctx.font = "500 18px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
          for (let i = 0; i < visible.length; i++) {
            const row = Math.floor(i / lineCols);
            const col = i % lineCols;
            const line = visible[i];
            const lineX = x + colInnerPad + col * (colW + lineGapX);
            const lineY = lineTop + row * lineGapY;
            fillCircle(ctx, lineX + 5, lineY + 9, 4.5, line.color || accent, card, 1.5);
            ctx.fillStyle = text;
            ctx.fillText(truncateCanvasText(ctx, line.text, textMaxW), lineX + 16, lineY);
          }
          if (item.lines.length > visible.length) {
            ctx.fillStyle = muted;
            ctx.font = "600 17px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
            ctx.fillText(`+${item.lines.length - visible.length} ещё`, x + 20, lineTop + item.rowsCount * lineGapY + 4);
          }
        }

        y += item.cardH + gridGap;
      }

      ctx.fillStyle = muted;
      ctx.font = "500 16px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
      ctx.fillText("Экспортировано из Axelio", padding, height - 22);
      return canvas;
    }

    const width = 1820;
    const cols = 7;
    const rows = 6;
    const headerCardH = 196;
    const statsY = 248;
    const statsH = 86;
    const gridTop = 380;
    const footerH = 46;
    const cellW = (width - padding * 2 - gridGap * (cols - 1)) / cols;
    const cellH = 160;
    const height = gridTop + rows * cellH + (rows - 1) * gridGap + footerH;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas not supported");

    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, width, height);

    drawHeader(ctx, width, 32, headerCardH);

    const stats = countVisibleStats(range.periodDates);
    const scopeLabel = runtime.calendarScope === "global" ? "Общий" : (runtime.showAllOnCalendar ? "Все" : "Мои");
    const statItems = [
      { title: "Всего смен", value: String(stats.total) },
      { title: "Укомплектовано", value: String(stats.staffed) },
      { title: "Неукомплектовано", value: String(stats.unstaffed) },
      { title: "Режим", value: scopeLabel },
    ];
    drawStatsRow(ctx, width, statsY, statItems, 4, statsH, 12);

    const weekdayY = gridTop - 34;
    for (let i = 0; i < 7; i++) {
      const colX = padding + i * (cellW + gridGap);
      ctx.fillStyle = muted;
      ctx.font = "700 18px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
      ctx.fillText(WEEKDAYS[i], colX + 4, weekdayY);
    }

    const monthKey = ym(runtime.curMonth);
    for (let index = 0; index < range.gridDates.length; index++) {
      const dateStr = range.gridDates[index];
      const row = Math.floor(index / 7);
      const col = index % 7;
      const x = padding + col * (cellW + gridGap);
      const y = gridTop + row * (cellH + gridGap);
      const inMonth = dateStr.startsWith(monthKey);
      const isToday = dateStr === todayIso;
      fillRoundRect(ctx, x, y, cellW, cellH, 18, inMonth ? card : subtle, isToday ? accent : border, isToday ? 2 : 1);

      const dayDate = new Date(`${dateStr}T00:00:00`);
      ctx.fillStyle = text;
      ctx.font = "700 20px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
      ctx.fillText(`${dayDate.getDate()}`, x + 16, y + 14);

      const lines = buildExportLinesForDate(dateStr);
      const visible = lines.slice(0, 4);
      const lineYStart = y + 48;
      const lineH = 22;
      ctx.font = "600 15px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
      for (let i = 0; i < visible.length; i++) {
        const line = visible[i];
        const lineY = lineYStart + i * lineH;
        fillCircle(ctx, x + 20, lineY + 10, 4, line.color || accent, card, 1);
        ctx.fillStyle = text;
        const maxTextWidth = cellW - 50;
        ctx.fillText(truncateCanvasText(ctx, line.text, maxTextWidth), x + 30, lineY);
      }

      if (lines.length > visible.length) {
        ctx.fillStyle = muted;
        ctx.font = "600 15px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
        ctx.fillText(`+${lines.length - visible.length} ещё`, x + 16, lineYStart + visible.length * lineH + 2);
      }

      if (!lines.length) {
        ctx.fillStyle = muted;
        ctx.font = "500 15px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
        ctx.fillText("Нет смен", x + 16, lineYStart);
      }
    }

    ctx.fillStyle = muted;
    ctx.font = "500 16px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
    ctx.fillText("Экспортировано из Axelio", padding, height - 24);
    return canvas;
  }

  function dataUrlToBlob(dataUrl) {
    const parts = String(dataUrl || "").split(",");
    const mimeMatch = /^data:(.*?);base64$/.exec(parts[0] || "");
    const mime = mimeMatch?.[1] || "application/octet-stream";
    const binary = atob(parts[1] || "");
    const len = binary.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
    return new Blob([bytes], { type: mime });
  }

  async function canvasToBlob(canvas, type, quality = 0.95) {
    return await new Promise((resolve) => {
      canvas.toBlob((blob) => {
        if (blob) resolve(blob);
        else resolve(dataUrlToBlob(canvas.toDataURL(type, quality)));
      }, type, quality);
    });
  }


  async function ensureExportArtifact() {
    if (exportState.canvas && exportState.pngBlob && exportState.meta) return exportState;
    const meta = await getExportMetadata();
    const canvas = await renderScheduleExportCanvas(meta);
    const pngBlob = await canvasToBlob(canvas, "image/png", 0.95);
    exportState.canvas = canvas;
    exportState.meta = meta;
    exportState.pngBlob = pngBlob;
    exportState.filenameBase = buildExportFilenameBase(meta);
    return exportState;
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    try {
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } finally {
      setTimeout(() => {
        try { URL.revokeObjectURL(url); } catch {}
      }, 1000);
    }
  }

  function canShareFile(file) {
    try {
      return !!(navigator.canShare && navigator.canShare({ files: [file] }));
    } catch {
      return false;
    }
  }

  function canWriteImageToClipboard() {
    return !!(navigator.clipboard && window.ClipboardItem);
  }

  async function copyImageBlobToClipboard(blob) {
    if (!canWriteImageToClipboard()) throw new Error("Буфер обмена недоступен");
    const item = new ClipboardItem({ [blob.type || "image/png"]: blob });
    await navigator.clipboard.write([item]);
  }

  async function shareExportImage() {
    const art = await ensureExportArtifact();
    const file = new File([art.pngBlob], `${art.filenameBase}.png`, { type: "image/png" });

    if (canShareFile(file) && navigator.share) {
      await navigator.share({ files: [file] });
      return "native-file";
    }

    if (canWriteImageToClipboard()) {
      await copyImageBlobToClipboard(art.pngBlob);
      toast("Картинка скопирована в буфер обмена", "ok");
      return "clipboard";
    }

    downloadBlob(art.pngBlob, `${art.filenameBase}.png`);
    toast("Браузер не умеет передавать картинку напрямую — скачал PNG", "warn");
    return "download";
  }

  async function openTelegramShare() {
    const art = await ensureExportArtifact();
    const file = new File([art.pngBlob], `${art.filenameBase}.png`, { type: "image/png" });

    if (canShareFile(file) && navigator.share) {
      await navigator.share({ files: [file] });
      return "native-file";
    }

    if (canWriteImageToClipboard()) {
      await copyImageBlobToClipboard(art.pngBlob);
      toast("Картинка скопирована — вставь её в Telegram", "ok");
      return "clipboard";
    }

    downloadBlob(art.pngBlob, `${art.filenameBase}.png`);
    toast("Этот браузер не умеет отправлять картинку напрямую в Telegram — скачал PNG", "warn");
    return "download";
  }

  async function refreshExportPreview() {
    setExportButtonsDisabled(true);
    setExportStatus("Готовим изображение…");
    if (el.exportPreviewImage) {
      el.exportPreviewImage.src = "";
      el.exportPreviewImage.classList.add("hidden");
    }

    try {
      resetExportState();
      const art = await ensureExportArtifact();
      releaseExportPreviewUrl();
      exportState.previewUrl = URL.createObjectURL(art.pngBlob);
      if (el.exportPreviewImage) {
        el.exportPreviewImage.src = exportState.previewUrl;
        el.exportPreviewImage.classList.remove("hidden");
      }
      if (el.exportModalSubtitle) el.exportModalSubtitle.textContent = `${art.meta?.period_label || ""} · ${art.meta?.filters_text || ""}`;
      setExportStatus("");
      setExportButtonsDisabled(false);
    } catch (e) {
      setExportStatus(e?.message || "Не удалось подготовить экспорт", { error: true });
      toast(e?.message || "Не удалось подготовить экспорт", "err");
    }
  }

  async function openExportModal() {
    el.exportModal?.classList.add("open");
    await refreshExportPreview();
  }

  async function downloadExportImage() {
    const art = await ensureExportArtifact();
    downloadBlob(art.pngBlob, `${art.filenameBase}.png`);
  }

  el.btnExportImage?.addEventListener("click", () => {
    openExportModal();
  });

  el.btnExportShare?.addEventListener("click", async () => {
    try {
      await shareExportImage();
    } catch (e) {
      toast(e?.message || "Не удалось поделиться", "err");
    }
  });

  el.btnExportTelegram?.addEventListener("click", async () => {
    try {
      await openTelegramShare();
    } catch (e) {
      toast(e?.message || "Не удалось подготовить картинку для Telegram", "err");
    }
  });

  el.btnExportDownload?.addEventListener("click", async () => {
    try {
      await downloadExportImage();
    } catch (e) {
      toast(e?.message || "Не удалось скачать PNG", "err");
    }
  });

  return { openExportModal, refreshExportPreview, downloadExportImage };
}
