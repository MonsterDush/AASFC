from __future__ import annotations

import json
import logging
import secrets
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.account_merge import merge_user_accounts
from app.auth.deps import get_current_user
from app.auth.phone_auth import (
    get_user_phone,
    link_telegram_identity_to_user,
)
from app.auth.telegram_webapp import TelegramInitDataError, verify_init_data
from app.auth.telegram_widget import TelegramLoginWidgetError, verify_login_widget_data
from app.core.db import get_db
from app.core.tg import normalize_tg_username
from app.models import TelegramBrowserAuthSession, User
from app.services.invites import accept_invites_for_user
from app.settings import settings

from .auth_common import (
    _auth_state,
    _client_ip,
    _normalize_next_path,
    _send_phone_link_reminder_if_due,
    _upsert_user_from_telegram_payload,
    _utcnow,
    _write_access_cookie,
)
from .auth_schemas import (
    AuthStateOut,
    LinkTelegramIn,
    TelegramAuthIn,
    TelegramBrowserAuthFinalizeIn,
    TelegramBrowserAuthStartIn,
    TelegramBrowserAuthStartOut,
    TelegramBrowserAuthStatusOut,
    TelegramMiniAppLinkOut,
    TelegramWidgetAuthIn,
)


_LOG = logging.getLogger("axelio.auth.telegram_browser")

router = APIRouter()
link_router = APIRouter()


def _telegram_browser_bot_username() -> str:
    """Return bot username for browser auth without calling Telegram API.

    Browser Telegram auth must not depend on outbound api.telegram.org calls.
    Set TG_BROWSER_LOGIN_BOT_USERNAME (preferred) or TG_LOGIN_WIDGET_BOT_USERNAME
    in backend .env.
    """
    return (
        str(settings.TG_BROWSER_LOGIN_BOT_USERNAME or settings.TG_LOGIN_WIDGET_BOT_USERNAME or "").strip().lstrip("@")
    )


def _telegram_mini_app_url(*, startapp: str = "auth") -> tuple[str, str]:
    bot_username = _telegram_browser_bot_username()
    if not bot_username:
        raise HTTPException(status_code=503, detail="Telegram Mini App bot is not configured")
    safe_startapp = (
        "".join(ch for ch in str(startapp or "auth").strip() if ch.isalnum() or ch in {"_", "-"})[:64] or "auth"
    )
    return bot_username, f"https://t.me/{bot_username}?startapp={safe_startapp}"


def _browser_login_ttl_seconds() -> int:
    return max(int(settings.TG_BROWSER_LOGIN_SESSION_TTL_SECONDS or 600), 60)


def _browser_login_prefix() -> str:
    return "browser_login_"


def _browser_link_prefix() -> str:
    return "browser_link_"


def _new_browser_login_token() -> str:
    return secrets.token_hex(16)


def _get_browser_login_session(db: Session, *, session_token: str) -> TelegramBrowserAuthSession:
    token = str(session_token or "").strip().lower()
    session = db.execute(
        select(TelegramBrowserAuthSession).where(TelegramBrowserAuthSession.public_token == token)
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Сессия входа через Telegram не найдена")
    return session


def _expire_browser_login_session(session: TelegramBrowserAuthSession) -> bool:
    if str(session.status or "").upper() == "EXPIRED":
        return True
    if session.expires_at <= _utcnow():
        session.status = "EXPIRED"
        return True
    return False


def _browser_login_status_payload(session: TelegramBrowserAuthSession) -> TelegramBrowserAuthStatusOut:
    expires_in_seconds = max(0, int((session.expires_at - _utcnow()).total_seconds()))
    status_value = str(session.status or "PENDING").upper()
    return TelegramBrowserAuthStatusOut(
        status=status_value,
        authorized=status_value in {"COMPLETED", "FINALIZED"} and bool(session.user_id),
        expires_in_seconds=expires_in_seconds,
        finalized=status_value == "FINALIZED",
        telegram_username=(normalize_tg_username(session.tg_username) if session.tg_username else None),
    )


# Browser Telegram auth is intentionally inbound-only.
#
# Previous versions tried to answer /start with sendMessage and then waited for an
# inline callback. On this VPS outgoing Telegram API calls are unstable, so the
# browser flow no longer calls api.telegram.org at all. Opening the deep-link is
# treated as confirmation: Telegram sends /start <token> to our webhook, backend
# marks the session COMPLETED, and the browser polling endpoint finalizes login.


def _telegram_user_from_update(value: dict | None) -> tuple[int, str | None, str, str]:
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="Telegram user payload is missing")
    try:
        tg_user_id = int(value.get("id"))
    except Exception:
        raise HTTPException(status_code=400, detail="Telegram user id is missing")
    return (
        tg_user_id,
        normalize_tg_username(value.get("username")),
        str(value.get("first_name") or "").strip(),
        str(value.get("last_name") or "").strip(),
    )


def _complete_browser_login_session(
    db: Session,
    *,
    session_token: str,
    tg_user_id: int,
    tg_username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> tuple[TelegramBrowserAuthSession, User]:
    session = _get_browser_login_session(db, session_token=session_token)
    if _expire_browser_login_session(session):
        db.commit()
        raise HTTPException(status_code=410, detail="Сессия входа через Telegram истекла")

    if str(session.status or "PENDING").upper() in {"COMPLETED", "FINALIZED"} and session.user_id:
        user = db.execute(select(User).where(User.id == session.user_id)).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="Пользователь для этой сессии не найден")
        return session, user

    user = _upsert_user_from_telegram_payload(
        db,
        tg_user_id=tg_user_id,
        tg_username=tg_username,
        first_name=first_name,
        last_name=last_name,
    )
    accept_invites_for_user(db, user_id=user.id, tg_username=user.tg_username)
    session.user_id = user.id
    session.tg_user_id = tg_user_id
    session.tg_username = tg_username
    session.status = "COMPLETED"
    session.completed_at = _utcnow()
    db.flush()
    db.commit()
    db.refresh(user)
    return session, user


def _complete_browser_link_session(
    db: Session,
    *,
    session_token: str,
    tg_user_id: int,
    tg_username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> tuple[TelegramBrowserAuthSession, User]:
    session = _get_browser_login_session(db, session_token=session_token)
    if _expire_browser_login_session(session):
        db.commit()
        raise HTTPException(status_code=410, detail="Сессия привязки Telegram истекла")
    if not session.user_id:
        raise HTTPException(status_code=409, detail="Для этой сессии не найден пользователь")

    target_user = db.execute(select(User).where(User.id == session.user_id)).scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="Пользователь для этой сессии не найден")

    if str(session.status or "PENDING").upper() in {"COMPLETED", "FINALIZED"} and session.tg_user_id == tg_user_id:
        return session, target_user

    default_full_name = " ".join([p for p in [(last_name or "").strip(), (first_name or "").strip()] if p]) or None
    default_short_name = (first_name or "").strip() or (tg_username.lstrip("@") if tg_username else None)

    existing_tg_user = db.execute(select(User).where(User.tg_user_id == tg_user_id)).scalar_one_or_none()
    if existing_tg_user is not None and existing_tg_user.id != target_user.id:
        target_user = merge_user_accounts(db, target_user=target_user, source_user=existing_tg_user)

    link_telegram_identity_to_user(
        db,
        user=target_user,
        tg_user_id=tg_user_id,
        tg_username=tg_username,
        default_full_name=default_full_name,
        default_short_name=default_short_name,
    )
    if tg_user_id in settings.super_admin_ids() and target_user.system_role != "SUPER_ADMIN":
        target_user.system_role = "SUPER_ADMIN"

    accept_invites_for_user(db, user_id=target_user.id, tg_username=target_user.tg_username)
    session.user_id = target_user.id
    session.tg_user_id = tg_user_id
    session.tg_username = tg_username
    session.status = "COMPLETED"
    session.completed_at = _utcnow()
    db.flush()
    db.commit()
    db.refresh(target_user)
    return session, target_user


def _handle_browser_login_start_message(db: Session, *, text: str, from_user: dict | None = None) -> None:
    """Auto-confirm browser login/link from Telegram /start payload.

    No messages are sent back to Telegram. This makes the flow independent from
    outbound Telegram API availability.
    """
    raw = str(text or "").strip()
    if not raw.startswith("/start"):
        return

    parts = raw.split(maxsplit=1)
    command = str(parts[0] if parts else "").split("@", 1)[0].strip().lower()
    if command != "/start":
        return

    start_arg = parts[1].strip() if len(parts) > 1 else ""
    if not start_arg:
        return

    try:
        tg_user_id, tg_username, first_name, last_name = _telegram_user_from_update(from_user)

        if start_arg.startswith(_browser_login_prefix()):
            session_token = start_arg[len(_browser_login_prefix()) :].strip().lower()
            _complete_browser_login_session(
                db,
                session_token=session_token,
                tg_user_id=tg_user_id,
                tg_username=tg_username,
                first_name=first_name,
                last_name=last_name,
            )
            return

        if start_arg.startswith(_browser_link_prefix()):
            session_token = start_arg[len(_browser_link_prefix()) :].strip().lower()
            _complete_browser_link_session(
                db,
                session_token=session_token,
                tg_user_id=tg_user_id,
                tg_username=tg_username,
                first_name=first_name,
                last_name=last_name,
            )
            return

        # Unknown /start payload: do nothing. The browser flow is driven only by
        # Axelio-generated browser_login_/browser_link_ tokens.
        return
    except HTTPException:
        db.rollback()
        _LOG.exception("telegram browser auto-confirm rejected")
    except Exception:
        db.rollback()
        _LOG.exception("telegram browser auto-confirm failed")


def _handle_browser_login_callback(db: Session, *, callback_query: dict) -> None:
    """Backward-compatible no-outbound callback handler.

    Old messages with inline buttons may still exist in Telegram. If clicked, we
    complete the session but do not call answerCallbackQuery/editMessageText.
    """
    data = str(callback_query.get("data") or "")
    if data.startswith("browser_login:"):
        mode = "login"
    elif data.startswith("browser_link:"):
        mode = "link"
    else:
        return

    try:
        session_token = data.split(":", 1)[1].strip().lower()
        tg_user_id, tg_username, first_name, last_name = _telegram_user_from_update(callback_query.get("from") or {})
        if mode == "login":
            _complete_browser_login_session(
                db,
                session_token=session_token,
                tg_user_id=tg_user_id,
                tg_username=tg_username,
                first_name=first_name,
                last_name=last_name,
            )
        else:
            _complete_browser_link_session(
                db,
                session_token=session_token,
                tg_user_id=tg_user_id,
                tg_username=tg_username,
                first_name=first_name,
                last_name=last_name,
            )
    except HTTPException:
        db.rollback()
        _LOG.exception("telegram browser callback auto-confirm rejected")
    except Exception:
        db.rollback()
        _LOG.exception("telegram browser callback auto-confirm failed")


@router.get("/telegram/miniapp-link", response_model=TelegramMiniAppLinkOut)
def telegram_miniapp_link(startapp: str = Query(default="auth", max_length=64)):
    bot_username, mini_app_url = _telegram_mini_app_url(startapp=startapp)
    return TelegramMiniAppLinkOut(
        bot_username=bot_username,
        mini_app_url=mini_app_url,
    )


@router.post("/telegram/browser/start", response_model=TelegramBrowserAuthStartOut)
def start_telegram_browser_auth(
    payload: TelegramBrowserAuthStartIn,
    request: Request,
    db: Session = Depends(get_db),
):
    bot_username = _telegram_browser_bot_username()
    if not bot_username:
        raise HTTPException(status_code=503, detail="Telegram browser login is not configured")

    session = TelegramBrowserAuthSession(
        public_token=_new_browser_login_token(),
        status="PENDING",
        next_path=_normalize_next_path(payload.next_path),
        request_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        expires_at=_utcnow() + timedelta(seconds=_browser_login_ttl_seconds()),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return TelegramBrowserAuthStartOut(
        session_token=session.public_token,
        bot_username=bot_username,
        deep_link_url=f"https://t.me/{bot_username}?start={_browser_login_prefix()}{session.public_token}",
        expires_in_seconds=_browser_login_ttl_seconds(),
    )


@router.get("/telegram/browser/status/{session_token}", response_model=TelegramBrowserAuthStatusOut)
def telegram_browser_auth_status(session_token: str, db: Session = Depends(get_db)):
    session = _get_browser_login_session(db, session_token=session_token)
    if _expire_browser_login_session(session):
        db.commit()
    else:
        db.flush()
    return _browser_login_status_payload(session)


@router.post("/telegram/browser/finalize", response_model=AuthStateOut)
def finalize_telegram_browser_auth(
    payload: TelegramBrowserAuthFinalizeIn,
    response: Response,
    db: Session = Depends(get_db),
):
    session = _get_browser_login_session(db, session_token=payload.session_token)
    if _expire_browser_login_session(session):
        db.commit()
        raise HTTPException(status_code=410, detail="Сессия входа через Telegram истекла")

    if str(session.status or "PENDING").upper() not in {"COMPLETED", "FINALIZED"} or not session.user_id:
        raise HTTPException(status_code=409, detail="Подтверждение в Telegram ещё не завершено")

    user = db.execute(select(User).where(User.id == session.user_id)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь для этой сессии не найден")

    session.status = "FINALIZED"
    if session.finalized_at is None:
        session.finalized_at = _utcnow()
    db.commit()
    db.refresh(user)
    _write_access_cookie(response, user=user)
    return _auth_state(db, user=user)


async def process_telegram_browser_webhook_request(
    request: Request,
    *,
    x_telegram_bot_api_secret_token: str | None,
    db: Session,
) -> None:
    """Process Telegram browser-auth updates for canonical and legacy routes."""
    secret = str(settings.TG_WEBHOOK_SECRET_TOKEN or "").strip()
    if secret and str(x_telegram_bot_api_secret_token or "").strip() != secret:
        raise HTTPException(status_code=401, detail="bad telegram secret")

    update = await request.json()
    callback_query = update.get("callback_query")
    if isinstance(callback_query, dict):
        _handle_browser_login_callback(db, callback_query=callback_query)
        return

    message = update.get("message")
    if isinstance(message, dict):
        text = message.get("text")
        if text:
            _handle_browser_login_start_message(
                db,
                text=str(text),
                from_user=(message.get("from") or {}),
            )


@router.post("/telegram/browser/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def telegram_browser_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    await process_telegram_browser_webhook_request(
        request,
        x_telegram_bot_api_secret_token=x_telegram_bot_api_secret_token,
        db=db,
    )
    return None


@router.post("/telegram", status_code=status.HTTP_204_NO_CONTENT)
def auth_telegram(
    payload: TelegramAuthIn, response: Response, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    try:
        data = verify_init_data(payload.initData, settings.TG_BOT_TOKEN)
    except TelegramInitDataError as e:
        raise HTTPException(status_code=401, detail=str(e))

    user_raw = data.get("user")
    if not user_raw:
        raise HTTPException(status_code=400, detail="user is missing in initData")

    try:
        tg_user = json.loads(user_raw)
        tg_user_id = int(tg_user["id"])
        tg_username = normalize_tg_username(tg_user.get("username"))
        first_name = (tg_user.get("first_name") or "").strip()
        last_name = (tg_user.get("last_name") or "").strip()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user payload")

    user = _upsert_user_from_telegram_payload(
        db,
        tg_user_id=tg_user_id,
        tg_username=tg_username,
        first_name=first_name,
        last_name=last_name,
    )
    db.commit()
    db.refresh(user)

    accept_invites_for_user(db, user_id=user.id, tg_username=user.tg_username)
    if not get_user_phone(db, user_id=int(user.id)):
        background_tasks.add_task(_send_phone_link_reminder_if_due, int(user.id))
    _write_access_cookie(response, user=user)
    return


@router.get("/telegram/widget/config")
def telegram_widget_config():
    bot_username = str(settings.TG_LOGIN_WIDGET_BOT_USERNAME or "").strip()
    return {
        "ok": True,
        "enabled": bool(bot_username),
        "bot_username": bot_username or None,
    }


@router.post("/telegram/widget", status_code=status.HTTP_204_NO_CONTENT)
def auth_telegram_widget(payload: TelegramWidgetAuthIn, response: Response, db: Session = Depends(get_db)):
    bot_username = str(settings.TG_LOGIN_WIDGET_BOT_USERNAME or "").strip()
    if not bot_username:
        raise HTTPException(status_code=503, detail="Telegram Login Widget is not configured")

    try:
        data = verify_login_widget_data(
            payload.model_dump(exclude_none=True),
            settings.TG_BOT_TOKEN,
            max_age_seconds=int(settings.TG_LOGIN_WIDGET_MAX_AGE_SECONDS or 3600),
        )
    except TelegramLoginWidgetError as e:
        raise HTTPException(status_code=401, detail=str(e))

    try:
        tg_user_id = int(data["id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Telegram widget payload")

    tg_username = normalize_tg_username(data.get("username"))
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()

    user = _upsert_user_from_telegram_payload(
        db,
        tg_user_id=tg_user_id,
        tg_username=tg_username,
        first_name=first_name,
        last_name=last_name,
    )
    db.commit()
    db.refresh(user)

    accept_invites_for_user(db, user_id=user.id, tg_username=user.tg_username)
    _write_access_cookie(response, user=user)
    return


@link_router.post("/link/telegram/browser/start", response_model=TelegramBrowserAuthStartOut)
def start_telegram_browser_link(
    payload: TelegramBrowserAuthStartIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    bot_username = _telegram_browser_bot_username()
    if not bot_username:
        raise HTTPException(status_code=503, detail="Telegram browser login is not configured")

    session = TelegramBrowserAuthSession(
        public_token=_new_browser_login_token(),
        status="PENDING",
        next_path=_normalize_next_path(payload.next_path),
        user_id=user.id,
        request_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        expires_at=_utcnow() + timedelta(seconds=_browser_login_ttl_seconds()),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return TelegramBrowserAuthStartOut(
        session_token=session.public_token,
        bot_username=bot_username,
        deep_link_url=f"https://t.me/{bot_username}?start={_browser_link_prefix()}{session.public_token}",
        expires_in_seconds=_browser_login_ttl_seconds(),
    )


@link_router.get("/link/telegram/browser/status/{session_token}", response_model=TelegramBrowserAuthStatusOut)
def telegram_browser_link_status(
    session_token: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = _get_browser_login_session(db, session_token=session_token)
    if int(session.user_id or 0) != int(user.id):
        raise HTTPException(status_code=404, detail="Сессия привязки Telegram не найдена")
    if _expire_browser_login_session(session):
        db.commit()
    else:
        db.flush()
    return _browser_login_status_payload(session)


@link_router.post("/link/telegram/browser/finalize", response_model=AuthStateOut)
def finalize_telegram_browser_link(
    payload: TelegramBrowserAuthFinalizeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = _get_browser_login_session(db, session_token=payload.session_token)
    if int(session.user_id or 0) != int(user.id):
        raise HTTPException(status_code=404, detail="Сессия привязки Telegram не найдена")
    if _expire_browser_login_session(session):
        db.commit()
        raise HTTPException(status_code=410, detail="Сессия привязки Telegram истекла")
    if str(session.status or "PENDING").upper() not in {"COMPLETED", "FINALIZED"} or not session.tg_user_id:
        raise HTTPException(status_code=409, detail="Подтверждение в Telegram ещё не завершено")

    linked_user = db.execute(select(User).where(User.id == session.user_id)).scalar_one_or_none()
    if linked_user is None:
        raise HTTPException(status_code=404, detail="Пользователь для этой сессии не найден")

    session.status = "FINALIZED"
    if session.finalized_at is None:
        session.finalized_at = _utcnow()
    db.commit()
    db.refresh(linked_user)
    return _auth_state(db, user=linked_user)


@link_router.post("/link/telegram", response_model=AuthStateOut)
def link_telegram_account(
    payload: LinkTelegramIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        data = verify_init_data(payload.initData, settings.TG_BOT_TOKEN)
    except TelegramInitDataError as e:
        raise HTTPException(status_code=401, detail=str(e))

    user_raw = data.get("user")
    if not user_raw:
        raise HTTPException(status_code=400, detail="user is missing in initData")

    try:
        tg_user = json.loads(user_raw)
        tg_user_id = int(tg_user["id"])
        tg_username = normalize_tg_username(tg_user.get("username"))
        first_name = (tg_user.get("first_name") or "").strip()
        last_name = (tg_user.get("last_name") or "").strip()
        default_full_name = " ".join([p for p in [last_name, first_name] if p]) or None
        default_short_name = first_name or (tg_username.lstrip("@") if tg_username else None)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user payload")

    existing_tg_user = db.execute(select(User).where(User.tg_user_id == tg_user_id)).scalar_one_or_none()
    if existing_tg_user is not None and existing_tg_user.id != user.id:
        user = merge_user_accounts(db, target_user=user, source_user=existing_tg_user)

    link_telegram_identity_to_user(
        db,
        user=user,
        tg_user_id=tg_user_id,
        tg_username=tg_username,
        default_full_name=default_full_name,
        default_short_name=default_short_name,
    )

    if tg_user_id in settings.super_admin_ids() and user.system_role != "SUPER_ADMIN":
        user.system_role = "SUPER_ADMIN"

    db.commit()
    db.refresh(user)
    accept_invites_for_user(db, user_id=user.id, tg_username=user.tg_username)
    return _auth_state(db, user=user)
