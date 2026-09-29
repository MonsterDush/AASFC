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

export async function showContextHelp(trigger) {
  const sourceSelector = String(trigger?.dataset?.infoSource || "").trim();
  const source = sourceSelector ? document.querySelector(sourceSelector) : null;
  const rawMessage = String(source?.textContent || trigger?.dataset?.info || "").trim();
  const message = await (window.AxelioI18n?.translateText?.(rawMessage, { report: false }) || rawMessage);
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

const DESCRIPTION_SELECTORS = [
  "[data-context-description]",
  ".section-card__title > .muted:not([id]):not([data-keep-visible])",
  ".section-card__head > div > .muted:not([id]):not([data-keep-visible])",
  ".screen-hero__head > div > .muted:not([id]):not([data-keep-visible])",
  ".section-head > div > .muted:not([id]):not([data-keep-visible])",
  ".demo-analytics-section > .demo-analytics-note:not([id])",
  ".demo-analytics-header-main > .demo-analytics-note:not([id])",
  ".demo-analytics-stacktitle > .demo-analytics-note:not([id])",
];

let descriptionId = 0;

export function promoteContextDescriptions(root = document) {
  const descriptions = [];
  if (root instanceof Element && root.matches(DESCRIPTION_SELECTORS.join(","))) descriptions.push(root);
  root.querySelectorAll?.(DESCRIPTION_SELECTORS.join(",")).forEach((node) => descriptions.push(node));

  descriptions.forEach((description) => {
    if (description.dataset.contextHelpPromoted === "1" || !String(description.textContent || "").trim()) return;
    const parent = description.parentElement;
    if (!parent) return;
    const nestedTitleRow = Array.from(parent.children).find((node) => node !== description && node.matches?.(".section-title,.block-title-with-info"));
    const title = Array.from(parent.children).find((node) => node !== description && node.matches?.("b,strong,h1,h2,h3,h4"))
      || nestedTitleRow?.querySelector("b,strong,h1,h2,h3,h4");
    if (!title) return;

    if (!description.id) {
      descriptionId += 1;
      description.id = `contextDescription${descriptionId}`;
    }
    const titleRow = nestedTitleRow || document.createElement("div");
    titleRow.classList.add("block-title-with-info");
    if (!nestedTitleRow) {
      parent.insertBefore(titleRow, title);
      titleRow.appendChild(title);
    }

    const button = document.createElement("button");
    button.className = "info-button";
    button.type = "button";
    button.textContent = "i";
    button.setAttribute("aria-label", document.documentElement.lang === "en" ? "About this section" : "О разделе");
    button.setAttribute("aria-expanded", "false");
    button.dataset.info = "";
    button.dataset.infoSource = `#${CSS.escape(description.id)}`;
    titleRow.appendChild(button);

    description.hidden = true;
    description.dataset.contextHelpPromoted = "1";
  });
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

  const enhance = () => promoteContextDescriptions(document);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", enhance, { once: true });
  else enhance();

  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
      if (node instanceof Element) promoteContextDescriptions(node);
    }));
  });
  const observe = () => observer.observe(document.body, { childList: true, subtree: true });
  if (document.body) observe();
  else document.addEventListener("DOMContentLoaded", observe, { once: true });
}

if (typeof document !== "undefined") installContextHelp();
