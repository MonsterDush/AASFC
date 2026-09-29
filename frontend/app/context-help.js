let activeTrigger = null;
let hideTimer = null;

function getPopover() {
  let popover = document.querySelector("[data-context-popover]");
  if (popover) return popover;
  popover = document.createElement("div");
  popover.className = "context-popover";
  popover.setAttribute("data-context-popover", "");
  popover.setAttribute("role", "status");
  popover.hidden = true;
  document.body.appendChild(popover);
  return popover;
}

function positionPopover(popover, trigger) {
  const rect = trigger.getBoundingClientRect();
  const gutter = 12;
  const maxLeft = Math.max(gutter, window.innerWidth - popover.offsetWidth - gutter);
  const left = Math.min(Math.max(gutter, rect.right - popover.offsetWidth), maxLeft);
  const fitsBelow = rect.bottom + popover.offsetHeight + gutter <= window.innerHeight;
  const top = fitsBelow
    ? rect.bottom + 8
    : Math.max(gutter, rect.top - popover.offsetHeight - 8);
  popover.style.setProperty("--context-popover-left", `${Math.round(left)}px`);
  popover.style.setProperty("--context-popover-top", `${Math.round(top)}px`);
}

export function hideContextHelp() {
  if (hideTimer) window.clearTimeout(hideTimer);
  hideTimer = null;
  const popover = document.querySelector("[data-context-popover]");
  if (popover) popover.hidden = true;
  activeTrigger?.setAttribute("aria-expanded", "false");
  activeTrigger = null;
}

export function showContextHelp(trigger) {
  const message = String(trigger?.dataset?.info || "").trim();
  if (!message) return;
  const popover = getPopover();
  if (activeTrigger && activeTrigger !== trigger) activeTrigger.setAttribute("aria-expanded", "false");
  activeTrigger = trigger;
  trigger.setAttribute("aria-expanded", "true");
  popover.textContent = message;
  popover.hidden = false;
  positionPopover(popover, trigger);
  if (hideTimer) window.clearTimeout(hideTimer);
  const duration = Math.min(10000, Math.max(5000, Number(trigger.dataset.infoDuration || 7000)));
  hideTimer = window.setTimeout(hideContextHelp, duration);
}

export function installContextHelp() {
  if (typeof document === "undefined" || document.documentElement.dataset.contextHelpReady === "1") return;
  document.documentElement.dataset.contextHelpReady = "1";
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest?.("[data-info]");
    if (trigger) {
      event.preventDefault();
      event.stopPropagation();
      if (activeTrigger === trigger) hideContextHelp();
      else showContextHelp(trigger);
      return;
    }
    if (!event.target.closest?.("[data-context-popover]")) hideContextHelp();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      hideContextHelp();
      return;
    }
    const trigger = event.target.closest?.("[data-info]");
    if (trigger && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      if (activeTrigger === trigger) hideContextHelp();
      else showContextHelp(trigger);
    }
  });
  window.addEventListener("resize", hideContextHelp);
  window.addEventListener("scroll", hideContextHelp, true);
}

if (typeof document !== "undefined") installContextHelp();
