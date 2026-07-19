export function createAuthActions(context) {
  const { wa, api } = context;

  async function loginWithTelegramWidget(authData) {
    return api("/auth/telegram/widget", {
      method: "POST",
      body: authData || {},
      handle401: false,
    });
  }

  async function startTelegramBrowserLogin(nextPath = "") {
    return api("/auth/telegram/browser/start", {
      method: "POST",
      body: { next_path: nextPath || null },
      handle401: false,
      timeoutMs: 8000,
    });
  }

  async function getTelegramBrowserLoginStatus(sessionToken) {
    return api(`/auth/telegram/browser/status/${encodeURIComponent(sessionToken)}`, {
      handle401: false,
      timeoutMs: 8000,
    });
  }

  async function finalizeTelegramBrowserLogin(sessionToken) {
    return api("/auth/telegram/browser/finalize", {
      method: "POST",
      body: { session_token: sessionToken },
      handle401: false,
      timeoutMs: 8000,
    });
  }

  async function startTelegramBrowserLink(nextPath = "") {
    return api("/auth/link/telegram/browser/start", {
      method: "POST",
      body: { next_path: nextPath || null },
      timeoutMs: 8000,
    });
  }

  async function getTelegramBrowserLinkStatus(sessionToken) {
    return api(`/auth/link/telegram/browser/status/${encodeURIComponent(sessionToken)}`, {
      timeoutMs: 8000,
    });
  }

  async function finalizeTelegramBrowserLink(sessionToken) {
    return api("/auth/link/telegram/browser/finalize", {
      method: "POST",
      body: { session_token: sessionToken },
      timeoutMs: 8000,
    });
  }

  async function getPhoneAuthConfig() {
    return api("/auth/phone/config", {
      handle401: false,
    });
  }

  async function requestPhoneCall(phone) {
    return api("/auth/phone/request-call", {
      method: "POST",
      body: { phone },
      handle401: false,
    });
  }

  async function getPhoneCallStatus(phone, challengeId) {
    return api(`/auth/phone/call-status/${encodeURIComponent(challengeId)}?phone=${encodeURIComponent(phone)}`, {
      handle401: false,
    });
  }

  async function requestPhoneCode(phone) {
    return api("/auth/phone/request-code", {
      method: "POST",
      body: { phone },
      handle401: false,
    });
  }

  async function verifyPhoneCode(phone, code = "", challengeId = null) {
    const body = { phone };
    const normalizedCode = String(code || "").trim();
    if (normalizedCode) body.code = normalizedCode;
    if (challengeId != null && challengeId !== "") body.challenge_id = challengeId;
    return api("/auth/phone/verify-code", {
      method: "POST",
      body,
      handle401: false,
    });
  }

  async function loginWithPassword(phone, password) {
    return api("/auth/password/login", {
      method: "POST",
      body: { phone, password },
      handle401: false,
    });
  }

  async function setPasswordAfterPhoneVerify(phone, code = "", newPassword = "", challengeId = null) {
    const body = { phone, new_password: newPassword };
    const normalizedCode = String(code || "").trim();
    if (normalizedCode) body.code = normalizedCode;
    if (challengeId != null && challengeId !== "") body.challenge_id = challengeId;
    return api("/auth/password/set-after-phone-verify", {
      method: "POST",
      body,
      handle401: false,
    });
  }

  async function requestPasswordResetCall(phone) {
    return api("/auth/password/reset/request-call", {
      method: "POST",
      body: { phone },
      handle401: false,
    });
  }

  async function requestPasswordResetCode(phone) {
    return api("/auth/password/reset/request-code", {
      method: "POST",
      body: { phone },
      handle401: false,
    });
  }

  async function confirmPasswordReset(phone, code = "", newPassword = "", challengeId = null) {
    const body = { phone, new_password: newPassword };
    const normalizedCode = String(code || "").trim();
    if (normalizedCode) body.code = normalizedCode;
    if (challengeId != null && challengeId !== "") body.challenge_id = challengeId;
    return api("/auth/password/reset/confirm", {
      method: "POST",
      body,
      handle401: false,
    });
  }

  async function getPasswordState() {
    return api("/auth/password/state");
  }

  async function changePassword(currentPassword, newPassword) {
    return api("/auth/password/change", {
      method: "POST",
      body: { current_password: currentPassword, new_password: newPassword },
    });
  }

  async function logout() {
    return api("/auth/logout", {
      method: "POST",
      handle401: false,
    });
  }

  async function requestLinkPhoneCall(phone) {
    return api("/auth/link/phone/request-call", {
      method: "POST",
      body: { phone },
    });
  }

  async function requestLinkPhoneCode(phone) {
    return api("/auth/link/phone/request-code", {
      method: "POST",
      body: { phone },
    });
  }

  async function verifyLinkPhoneCode(phone, code = "", newPassword = "", challengeId = null) {
    const body = { phone };
    const normalizedCode = String(code || "").trim();
    const normalizedPassword = String(newPassword || "").trim();
    if (normalizedCode) body.code = normalizedCode;
    if (challengeId != null && challengeId !== "") body.challenge_id = challengeId;
    if (normalizedPassword) body.new_password = normalizedPassword;
    return api("/auth/link/phone/verify-code", {
      method: "POST",
      body,
    });
  }

  async function linkTelegramAccount(initData = "") {
    const value = String(initData || wa()?.initData || "").trim();
    if (!value) throw new Error("Telegram Mini App недоступен для привязки");
    return api("/auth/link/telegram", {
      method: "POST",
      body: { initData: value },
    });
  }

  return { loginWithTelegramWidget, startTelegramBrowserLogin, getTelegramBrowserLoginStatus, finalizeTelegramBrowserLogin, startTelegramBrowserLink, getTelegramBrowserLinkStatus, finalizeTelegramBrowserLink, getPhoneAuthConfig, requestPhoneCall, getPhoneCallStatus, requestPhoneCode, verifyPhoneCode, loginWithPassword, setPasswordAfterPhoneVerify, requestPasswordResetCall, requestPasswordResetCode, confirmPasswordReset, getPasswordState, changePassword, logout, requestLinkPhoneCall, requestLinkPhoneCode, verifyLinkPhoneCode, linkTelegramAccount };
}
