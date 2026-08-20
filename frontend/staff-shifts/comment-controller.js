export function mentionTokenForMember(member) {
  const displayName = String(member?.display_name || member?.tg_username || `Сотрудник ${member?.user_id || ""}`).trim();
  return `@${displayName.replace(/^@+/, "")}`;
}


export function findMentionQuery(input) {
  const text = String(input?.value || "");
  const caret = Number(input?.selectionStart ?? text.length);
  const beforeCaret = text.slice(0, caret);
  const match = /(?:^|[\s(])@([^@\n]{0,64})$/u.exec(beforeCaret);
  if (!match) return null;
  const query = String(match[1] || "");
  if (/\s$/u.test(query)) return null;
  return {
    start: caret - query.length - 1,
    end: caret,
    query,
  };
}


export function containsMentionToken(text, token) {
  const source = String(text || "").toLocaleLowerCase((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"));
  const needle = String(token || "").trim().toLocaleLowerCase((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"));
  if (!needle) return false;
  const isWordCharacter = (value) => Boolean(value) && /[\p{L}\p{N}_]/u.test(value);
  let fromIndex = 0;
  while (fromIndex <= source.length - needle.length) {
    const index = source.indexOf(needle, fromIndex);
    if (index < 0) return false;
    const before = source[index - 1] || "";
    const after = source[index + needle.length] || "";
    if ((!before || (!isWordCharacter(before) && before !== "@")) && !isWordCharacter(after)) return true;
    fromIndex = index + needle.length;
  }
  return false;
}


export function createStaffShiftCommentController(context) {
  const { runtime, api, toast } = context;
  let mentionableMembersPromise = null;

  function renderCommentsSection(shiftId, canComment) {
    if (!canComment) {
      return `
        <div class="comments">
          <div class="comments__head"><b>Комментарии</b></div>
          <div class="muted small mt-6">Комментарии доступны в режимах «Все» или «Только мои».</div>
        </div>
      `;
    }
    return `
      <div class="comments">
        <div class="comments__head">
          <b>Комментарии</b>
          <span class="muted small" data-comments-status="${shiftId}"></span>
        </div>
        <div data-comments-list="${shiftId}" class="commentlist"><div class="muted small">Загрузка…</div></div>
        <div class="commentform" data-comments-form="${shiftId}">
          <div class="commentform__reply hidden" data-comments-reply="${shiftId}">
            <div class="commentform__reply-copy">
              <b data-comments-reply-author="${shiftId}"></b>
              <span data-comments-reply-text="${shiftId}"></span>
            </div>
            <button class="btn sm subtle" type="button" data-comments-reply-cancel="${shiftId}" aria-label="Отменить ответ">Отмена</button>
          </div>
          <div class="commentform__row">
            <div class="commentform__composer">
              <textarea
                class="commentform__input"
                data-comments-input="${shiftId}"
                placeholder="Написать комментарий… Используйте @ для упоминания"
                aria-autocomplete="list"
                aria-expanded="false"
              ></textarea>
              <div class="comment-mentions hidden" data-comments-mentions="${shiftId}" role="listbox"></div>
            </div>
            <button class="btn commentform__send" data-comments-send="${shiftId}">Отправить</button>
          </div>
          <div class="commentform__hint muted small">@ — упомянуть коллегу · Ctrl/⌘ + Enter — отправить</div>
        </div>
      </div>
    `;
  }

  async function loadShiftComments(shiftId) {
    const out = await api(
      `/venues/${encodeURIComponent(runtime.venueId)}/shifts/${encodeURIComponent(shiftId)}/comments`
    ).catch(() => []);
    return Array.isArray(out) ? out : [];
  }

  async function loadMentionableMembers(shiftId) {
    if (!mentionableMembersPromise) {
      mentionableMembersPromise = api(
        `/venues/${encodeURIComponent(runtime.venueId)}/shifts/${encodeURIComponent(shiftId)}/mentionable-members`
      )
        .then((out) => Array.isArray(out) ? out : [])
        .catch((error) => {
          mentionableMembersPromise = null;
          throw error;
        });
    }
    return mentionableMembersPromise;
  }

  function formatCommentAuthor(user) {
    if (!user) return "—";
    return user.display_name || user.short_name || user.full_name || (user.tg_username ? `@${user.tg_username}` : "Сотрудник");
  }

  function formatCommentDate(value) {
    const date = value ? new Date(value) : null;
    return date && !Number.isNaN(date.getTime())
      ? date.toLocaleString((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"), { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
      : "";
  }

  function commentPreview(value, limit = 140) {
    const text = String(value || "").trim().replace(/\s+/gu, " ");
    if (text.length <= limit) return text;
    return `${text.slice(0, Math.max(limit - 1, 0)).trimEnd()}…`;
  }

  function escapeRegExp(value) {
    return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function renderCommentText(target, text, mentions) {
    target.textContent = "";
    const tokens = (Array.isArray(mentions) ? mentions : [])
      .map((mention) => `@${String(mention?.display_name || "").replace(/^@+/, "").trim()}`)
      .filter((token) => token.length > 1)
      .sort((a, b) => b.length - a.length);
    if (!tokens.length) {
      target.textContent = String(text || "");
      return;
    }

    const matcher = new RegExp(`(${tokens.map(escapeRegExp).join("|")})`, "giu");
    let lastIndex = 0;
    for (const match of String(text || "").matchAll(matcher)) {
      const index = Number(match.index || 0);
      if (index > lastIndex) target.append(document.createTextNode(String(text || "").slice(lastIndex, index)));
      const badge = document.createElement("span");
      badge.className = "comment__mention";
      badge.textContent = match[0];
      target.append(badge);
      lastIndex = index + match[0].length;
    }
    if (lastIndex < String(text || "").length) {
      target.append(document.createTextNode(String(text || "").slice(lastIndex)));
    }
  }

  function buildCommentElement(comment, onReply) {
    const item = document.createElement("div");
    item.className = "comment";
    item.dataset.commentId = String(comment?.id || "");

    const head = document.createElement("div");
    head.className = "comment__head";
    const author = document.createElement("div");
    author.className = "comment__author";
    author.textContent = formatCommentAuthor(comment?.author);
    const when = document.createElement("div");
    when.className = "comment__when";
    when.textContent = formatCommentDate(comment?.created_at);
    head.append(author, when);
    item.append(head);

    if (comment?.reply_to) {
      const reply = document.createElement("div");
      reply.className = "comment__reply";
      const replyAuthor = document.createElement("b");
      replyAuthor.textContent = formatCommentAuthor(comment.reply_to.author);
      const replyText = document.createElement("span");
      replyText.textContent = commentPreview(comment.reply_to.text);
      reply.append(replyAuthor, replyText);
      item.append(reply);
    }

    const body = document.createElement("div");
    body.className = "comment__text";
    renderCommentText(body, comment?.text || "", comment?.mentions || []);
    item.append(body);

    const actions = document.createElement("div");
    actions.className = "comment__actions";
    const replyButton = document.createElement("button");
    replyButton.type = "button";
    replyButton.className = "comment__reply-button";
    replyButton.textContent = "Ответить";
    replyButton.addEventListener("click", () => onReply(comment));
    actions.append(replyButton);
    item.append(actions);
    return item;
  }

  function renderCommentsInto(shiftId, comments, onReply) {
    const box = document.querySelector(`[data-comments-list="${shiftId}"]`);
    if (!box) return;
    if (!comments?.length) {
      box.innerHTML = '<div class="muted small">Нет комментариев</div>';
      return;
    }
    box.innerHTML = "";
    for (const comment of comments) box.append(buildCommentElement(comment, onReply));
  }

  function normalizeForSearch(value) {
    return String(value || "").trim().toLocaleLowerCase((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"));
  }

  function matchesMentionQuery(member, query) {
    const needle = normalizeForSearch(query);
    if (!needle) return true;
    const haystack = [
      member?.display_name,
      member?.tg_username,
      member?.position_title,
    ].map(normalizeForSearch).join(" ");
    return haystack.includes(needle);
  }

  async function wireShiftComments(shiftId) {
    const button = document.querySelector(`[data-comments-send="${shiftId}"]`);
    const input = document.querySelector(`[data-comments-input="${shiftId}"]`);
    const menu = document.querySelector(`[data-comments-mentions="${shiftId}"]`);
    const replyBox = document.querySelector(`[data-comments-reply="${shiftId}"]`);
    const replyAuthor = document.querySelector(`[data-comments-reply-author="${shiftId}"]`);
    const replyText = document.querySelector(`[data-comments-reply-text="${shiftId}"]`);
    const replyCancel = document.querySelector(`[data-comments-reply-cancel="${shiftId}"]`);
    if (!button || !input || !menu) return;

    const selectedMentions = new Map();
    let replyTarget = null;
    let menuItems = [];
    let menuIndex = 0;
    let mentionQuery = null;

    const closeMentionMenu = () => {
      menu.classList.add("hidden");
      menu.innerHTML = "";
      menuItems = [];
      menuIndex = 0;
      mentionQuery = null;
      input.setAttribute("aria-expanded", "false");
    };

    const setReplyTarget = (comment) => {
      replyTarget = comment || null;
      replyBox?.classList.toggle("hidden", !replyTarget);
      if (replyAuthor) replyAuthor.textContent = replyTarget ? `Ответ для ${formatCommentAuthor(replyTarget.author)}` : "";
      if (replyText) replyText.textContent = replyTarget ? commentPreview(replyTarget.text) : "";
      if (replyTarget) {
        input.placeholder = "Написать ответ… Используйте @ для упоминания";
        input.focus();
      } else {
        input.placeholder = "Написать комментарий… Используйте @ для упоминания";
      }
    };

    const syncMenuSelection = () => {
      menu.querySelectorAll("[data-mention-index]").forEach((element) => {
        const selected = Number(element.dataset.mentionIndex) === menuIndex;
        element.classList.toggle("is-active", selected);
        element.setAttribute("aria-selected", selected ? "true" : "false");
      });
    };

    const chooseMention = (member) => {
      if (!mentionQuery || !member) return;
      const token = mentionTokenForMember(member);
      const value = String(input.value || "");
      input.value = `${value.slice(0, mentionQuery.start)}${token} ${value.slice(mentionQuery.end)}`;
      selectedMentions.set(Number(member.user_id), member);
      const caret = mentionQuery.start + token.length + 1;
      input.setSelectionRange(caret, caret);
      closeMentionMenu();
      input.focus();
      input.dispatchEvent(new Event("input", { bubbles: true }));
    };

    const renderMentionMenu = (members) => {
      menu.innerHTML = "";
      menuItems = members.slice(0, 8);
      menuIndex = Math.min(menuIndex, Math.max(menuItems.length - 1, 0));
      if (!menuItems.length) {
        const empty = document.createElement("div");
        empty.className = "comment-mentions__empty";
        empty.textContent = "Сотрудники не найдены";
        menu.append(empty);
      } else {
        menuItems.forEach((member, index) => {
          const option = document.createElement("button");
          option.type = "button";
          option.className = "comment-mentions__item";
          option.dataset.mentionIndex = String(index);
          option.setAttribute("role", "option");
          const name = document.createElement("b");
          name.textContent = mentionTokenForMember(member);
          const meta = document.createElement("span");
          meta.textContent = [member.position_title, member.tg_username ? `@${String(member.tg_username).replace(/^@+/, "")}` : ""]
            .filter(Boolean)
            .join(" · ");
          option.append(name, meta);
          option.addEventListener("mousedown", (event) => event.preventDefault());
          option.addEventListener("click", () => chooseMention(member));
          menu.append(option);
        });
      }
      menu.classList.remove("hidden");
      input.setAttribute("aria-expanded", "true");
      syncMenuSelection();
    };

    const updateMentionMenu = async () => {
      const query = findMentionQuery(input);
      if (!query) {
        closeMentionMenu();
        return;
      }
      mentionQuery = query;
      try {
        const members = await loadMentionableMembers(shiftId);
        if (mentionQuery !== query) return;
        renderMentionMenu(members.filter((member) => matchesMentionQuery(member, query.query)));
      } catch {
        closeMentionMenu();
      }
    };

    const activeMentionIds = () => {
      return Array.from(selectedMentions.values())
        .filter((member) => containsMentionToken(input.value, mentionTokenForMember(member)))
        .map((member) => Number(member.user_id));
    };

    const syncButton = () => {
      const hasText = String(input.value || "").trim().length > 0;
      if (!button.dataset.sending) button.disabled = !hasText;
    };

    const scrollToComment = (commentId, highlight = false) => {
      if (!commentId) return;
      const target = document.querySelector(`[data-comment-id="${String(commentId).replace(/"/g, '\\"')}"]`);
      if (!target) return;
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      if (highlight) {
        target.classList.add("is-target");
        setTimeout(() => target.classList.remove("is-target"), 2600);
      }
    };

    const refresh = async () => {
      const comments = await loadShiftComments(shiftId);
      renderCommentsInto(shiftId, comments, setReplyTarget);
      if (String(runtime.deepLinkShiftId || "") === String(shiftId) && runtime.deepLinkCommentId) {
        requestAnimationFrame(() => scrollToComment(runtime.deepLinkCommentId, true));
      }
      return comments;
    };

    input.addEventListener("input", () => {
      syncButton();
      updateMentionMenu();
    });
    input.addEventListener("click", updateMentionMenu);
    input.addEventListener("keydown", (event) => {
      if (!menu.classList.contains("hidden")) {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          const delta = event.key === "ArrowDown" ? 1 : -1;
          menuIndex = (menuIndex + delta + Math.max(menuItems.length, 1)) % Math.max(menuItems.length, 1);
          syncMenuSelection();
          return;
        }
        if ((event.key === "Enter" || event.key === "Tab") && menuItems[menuIndex]) {
          event.preventDefault();
          chooseMention(menuItems[menuIndex]);
          return;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          closeMentionMenu();
          return;
        }
      }
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        button.click();
      }
    });
    input.addEventListener("blur", () => setTimeout(closeMentionMenu, 120));
    replyCancel?.addEventListener("click", () => setReplyTarget(null));

    syncButton();
    refresh();

    button.onclick = async () => {
      const text = String(input.value || "").trim();
      if (!text) return;
      button.dataset.sending = "1";
      button.disabled = true;
      try {
        const created = await api(
          `/venues/${encodeURIComponent(runtime.venueId)}/shifts/${encodeURIComponent(shiftId)}/comments`,
          {
            method: "POST",
            body: {
              text,
              mentioned_user_ids: activeMentionIds(),
              reply_to_comment_id: replyTarget?.id || null,
            },
          }
        );
        input.value = "";
        selectedMentions.clear();
        setReplyTarget(null);
        await refresh();
        requestAnimationFrame(() => scrollToComment(created?.id, true));
      } catch (error) {
        toast(error?.data?.detail || error?.message || "Не удалось отправить комментарий", "err");
      } finally {
        delete button.dataset.sending;
        syncButton();
      }
    };
  }

  return {
    renderCommentsSection,
    wireShiftComments,
  };
}
