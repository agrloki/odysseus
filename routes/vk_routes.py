"""VK Messenger integration routes."""
from __future__ import annotations

import asyncio
import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.settings import load_settings, save_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vk", tags=["vk"])

_vk_adapter = None


def _get_adapter():
    global _vk_adapter
    return _vk_adapter


def _require_admin(request: Request):
    auth_manager = getattr(request.app.state, "auth_manager", None)
    if not auth_manager:
        return
    user = getattr(request.state, "current_user", None)
    if not user or user == "api":
        raise JSONResponse(status_code=403, content={"error": "Admin only"})
    if not auth_manager.is_admin(user):
        raise JSONResponse(status_code=403, content={"error": "Admin only"})


@router.get("/config")
async def get_config(request: Request):
    _require_admin(request)
    settings = load_settings()
    token = settings.get("vk_token", "")
    masked = token[:4] + "****" + token[-4:] if len(token) > 8 else "****"
    return {
        "token_masked": masked if token else "",
        "group_id": settings.get("vk_group_id", ""),
        "api_version": settings.get("vk_api_version", "5.199"),
        "poll_interval": settings.get("vk_poll_interval", 5),
        "enabled": settings.get("vk_enabled", False),
    }


@router.post("/config")
async def save_config(request: Request):
    _require_admin(request)
    body = await request.json()
    settings = load_settings()
    if "token" in body and body["token"]:
        settings["vk_token"] = body["token"]
    if "group_id" in body:
        settings["vk_group_id"] = body["group_id"]
    if "api_version" in body:
        settings["vk_api_version"] = body["api_version"]
    if "poll_interval" in body:
        settings["vk_poll_interval"] = max(1, int(body["poll_interval"]))
    if "enabled" in body:
        settings["vk_enabled"] = bool(body["enabled"])
    save_settings(settings)
    return {"ok": True}


@router.post("/test")
async def test_connection(request: Request):
    _require_admin(request)
    from src.vk_adapter import VKAdapter
    settings = load_settings()
    token = settings.get("vk_token", "")
    group_id = int(settings.get("vk_group_id", "0") or "0")
    if not token or not group_id:
        return {"ok": False, "error": "VK token and group_id must be configured"}
    adapter = VKAdapter(token=token, group_id=group_id)
    result = await adapter.test_connection()
    return result


@router.post("/start")
async def start_polling(request: Request):
    global _vk_adapter
    _require_admin(request)
    from src.vk_adapter import VKAdapter
    settings = load_settings()
    token = settings.get("vk_token", "")
    group_id = int(settings.get("vk_group_id", "0") or "0")
    api_version = settings.get("vk_api_version", "5.199")
    poll_interval = int(settings.get("vk_poll_interval", 5))
    if not token or not group_id:
        return JSONResponse(status_code=400, content={"error": "VK token and group_id required"})
    if _vk_adapter and _vk_adapter.is_running:
        await _vk_adapter.disconnect()
    _vk_adapter = VKAdapter(token=token, group_id=group_id, api_version=api_version, poll_interval=poll_interval)

    async def _on_message(msg: dict):
        await _handle_vk_message(msg)

    _vk_adapter.set_message_handler(_on_message)
    ok = await _vk_adapter.connect()
    if not ok:
        return {"ok": False, "error": _vk_adapter.last_error}
    settings["vk_enabled"] = True
    save_settings(settings)
    return {"ok": True}


@router.post("/stop")
async def stop_polling(request: Request):
    global _vk_adapter
    _require_admin(request)
    if _vk_adapter and _vk_adapter.is_running:
        await _vk_adapter.disconnect()
    settings = load_settings()
    settings["vk_enabled"] = False
    save_settings(settings)
    return {"ok": True}


@router.get("/status")
async def get_status(request: Request):
    adapter = _get_adapter()
    if not adapter:
        return {"running": False, "status": "disconnected"}
    return {
        "running": adapter.is_running,
        "status": adapter.status,
        "error": adapter.last_error,
    }


@router.post("/send")
async def send_message(request: Request):
    _require_admin(request)
    body = await request.json()
    peer_id = body.get("peer_id", "")
    text = body.get("text", "")
    if not peer_id or not text:
        return JSONResponse(status_code=400, content={"error": "peer_id and text required"})
    adapter = _get_adapter()
    if not adapter or not adapter.is_running:
        return JSONResponse(status_code=503, content={"error": "VK adapter not running"})
    ok = await adapter.send(str(peer_id), text)
    return {"ok": ok}


async def _handle_vk_message(msg: dict):
    """Route incoming VK message to Odysseus agent."""
    try:
        from src.chat_handler import ChatHandler
        from core.session_manager import SessionManager

        session_manager = SessionManager()
        peer_id = msg["peer_id"]
        from_id = msg["from_id"]
        session_id = f"vk_{peer_id}"

        session = session_manager.get_session(session_id)
        if not session:
            session = session_manager.create_session(
                session_id,
                title=f"VK: {msg['chat_name']}",
                metadata={"source": "vk", "peer_id": peer_id, "from_id": from_id},
            )

        adapter = _get_adapter()
        if adapter:
            asyncio.create_task(adapter.send_typing(peer_id))

        system_prompt = (
            f"You are chatting via VK Messenger with user {msg['chat_name']}. "
            "Keep responses concise. VK supports plain text only — no Markdown rendering."
        )

        chat_handler = ChatHandler(session_manager=session_manager)
        result = await chat_handler.process_message(
            session_id=session_id,
            message=msg["text"],
            system_prompt_override=system_prompt,
        )

        response_text = result.get("response", "") if isinstance(result, dict) else str(result)
        if response_text and adapter:
            await adapter.send(peer_id, response_text)
    except Exception as e:
        logger.error("VK: _handle_vk_message error: %s", e)
