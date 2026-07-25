# VK Messenger Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Full bidirectional VK Messenger chat integration — Odysseus receives messages from VK users via REST polling, processes them through the agent, and sends responses back.

**Architecture:** REST polling adapter (like hermes-vk-adapter) ported to Odysseus-native pattern. Backend: `src/vk_adapter.py` (adapter core) + `routes/vk_routes.py` (API). Config stored in `data/settings.json`. Frontend: settings widget in admin panel. Agent tool: `vk_send_message` for outbound messages.

**Tech Stack:** Python 3.12, FastAPI, httpx (already in project), asyncio, vanilla JS frontend.

---

### Task 1: VK adapter core — `src/vk_adapter.py`

**Covers:** Core adapter logic — polling, message parsing, send, typing indicator.

**Files:**
- Create: `src/vk_adapter.py`

- [ ] **Step 1: Create the VK adapter module**

```python
"""VK Messenger adapter — REST polling for bidirectional chat."""
from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any, Callable, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

VK_API_BASE = "https://api.vk.com/method"
VK_DEFAULT_VERSION = "5.199"

EVENT_MESSAGE_NEW = 4
FLAG_OUTBOX = 4


def _strip_vk_mention(text: str) -> str:
    match = re.match(r'^\[[^\]]+\]\s*(.*)', text)
    return match.group(1) if match else text


def _vk_format_text(text: str) -> str:
    text = re.sub(r'```[\s\S]*?```', lambda m: m.group(0).replace('```', '').strip(), text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', text)
    text = text.replace('**', '')
    text = re.sub(r'(?<!\*)\*(?!\*)([^*]+)(?<!\*)\*(?!\*)', r'\1', text)
    text = text.replace('~~', '')
    text = re.sub(r'^#{1,6}\s+(.+)$', lambda m: m.group(1).upper(), text, flags=re.MULTILINE)
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


async def _vk_api(method: str, params: dict) -> dict:
    url = f"{VK_API_BASE}/{method}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, data=params)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"VK API error [{data['error']['error_code']}]: {data['error']['error_msg']}")
        return data.get("response", {})


class VKAdapter:
    def __init__(self, token: str, group_id: int, api_version: str = VK_DEFAULT_VERSION, poll_interval: int = 5):
        self.token = token
        self.group_id = group_id
        self.api_version = api_version
        self.poll_interval = max(1, poll_interval)
        self._poll_task: Optional[asyncio.Task] = None
        self._last_message_id: Optional[int] = None
        self._running = False
        self._message_handler: Optional[Callable] = None
        self._status: str = "disconnected"
        self._error: Optional[str] = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def status(self) -> str:
        return self._status

    @property
    def last_error(self) -> Optional[str]:
        return self._error

    def set_message_handler(self, handler: Callable):
        self._message_handler = handler

    async def connect(self) -> bool:
        if not self.token or not self.group_id:
            self._error = "VK_TOKEN and VK_GROUP_ID must be configured"
            self._status = "error"
            return False
        try:
            convs = await _vk_api("messages.getConversations", {
                "access_token": self.token,
                "v": self.api_version,
                "group_id": self.group_id,
                "count": 1,
            })
            items = convs.get("items", [])
            if items:
                last_msg = items[0].get("last_message", {})
                self._last_message_id = last_msg.get("id")
            self._status = "connected"
            self._error = None
            self._running = True
            self._poll_task = asyncio.create_task(self._poll_loop())
            logger.info("VK: connected (group %d, last_msg_id=%s)", self.group_id, self._last_message_id)
            return True
        except Exception as e:
            self._error = str(e)
            self._status = "error"
            logger.error("VK: connect failed: %s", e)
            return False

    async def disconnect(self):
        self._running = False
        self._status = "disconnected"
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self):
        logger.info("VK: poll loop started (interval=%ds)", self.poll_interval)
        while self._running:
            try:
                await self._check_new_messages()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("VK: poll error: %s", e)
            await asyncio.sleep(self.poll_interval)

    async def _check_new_messages(self):
        params = {
            "access_token": self.token,
            "v": self.api_version,
            "group_id": self.group_id,
            "count": 5,
        }
        if self._last_message_id:
            params["last_message_id"] = self._last_message_id
        try:
            convs = await _vk_api("messages.getConversations", params)
        except Exception:
            return
        items = convs.get("items", [])
        if not items:
            return
        for item in reversed(items):
            peer = item.get("conversation", {}).get("peer", {})
            peer_id = peer.get("id")
            if not peer_id:
                continue
            await self._fetch_and_process(str(peer_id))

    async def _fetch_and_process(self, peer_id: str):
        if not self._message_handler:
            return
        try:
            hist = await _vk_api("messages.getHistory", {
                "access_token": self.token,
                "v": self.api_version,
                "peer_id": int(peer_id),
                "count": 200,
                "rev": 0,
            })
        except Exception:
            return
        for msg in hist.get("items", []):
            msg_id = msg.get("id")
            if msg_id is None:
                continue
            if self._last_message_id is not None and msg_id <= self._last_message_id:
                continue
            self._last_message_id = msg_id
            text = _strip_vk_mention(msg.get("text", "") or "")
            from_id = msg.get("from_id")
            if from_id is not None and from_id < 0:
                continue
            attachments = msg.get("attachments", [])
            media_parts = []
            for att in attachments:
                att_type = att.get("type")
                if att_type == "photo":
                    sizes = att.get("photo", {}).get("sizes", [])
                    if sizes:
                        best = max(sizes, key=lambda s: s.get("width", 0) * s.get("height", 0))
                        url = best.get("url", "")
                        if url:
                            media_parts.append(f"MEDIA:{url}")
                elif att_type == "doc":
                    url = att.get("doc", {}).get("url", "")
                    if url:
                        media_parts.append(f"MEDIA:{url}")
                elif att_type == "audio_message":
                    am = att.get("audio_message", {})
                    url = am.get("link_mp3") or am.get("link_ogg", "")
                    if url:
                        media_parts.append(f"MEDIA:{url}")
            if media_parts:
                text = text + "\n" + "\n".join(media_parts) if text else "\n".join(media_parts)
            if not text.strip():
                continue
            int_peer = int(peer_id)
            chat_type = "group" if int_peer > 2000000000 else "dm"
            chat_name = f"user_{from_id}" if chat_type == "dm" else f"chat_{int_peer}"
            if chat_type == "dm" and from_id:
                try:
                    ui = await _vk_api("users.get", {
                        "access_token": self.token,
                        "v": self.api_version,
                        "user_ids": from_id,
                    })
                    if ui:
                        chat_name = f"{ui[0].get('first_name', '')} {ui[0].get('last_name', '')}".strip()
                except Exception:
                    pass
            asyncio.create_task(self._message_handler({
                "peer_id": str(peer_id),
                "from_id": str(from_id) if from_id else str(peer_id),
                "text": text,
                "message_id": str(msg_id),
                "chat_type": chat_type,
                "chat_name": chat_name,
            }))

    async def send(self, peer_id: str, text: str) -> bool:
        text = _vk_format_text(text)
        max_len = 4096
        parts = []
        while text:
            if len(text) <= max_len:
                parts.append(text)
                break
            split_at = text.rfind('\n\n', 0, max_len)
            if split_at < max_len // 2:
                split_at = text.rfind('\n', 0, max_len)
            if split_at < max_len // 2:
                split_at = max_len
            parts.append(text[:split_at].strip())
            text = text[split_at:].strip()
        for part in parts:
            try:
                await _vk_api("messages.send", {
                    "access_token": self.token,
                    "v": self.api_version,
                    "peer_id": int(peer_id),
                    "message": part,
                    "random_id": random.randint(-1_000_000, 1_000_000),
                })
            except Exception as e:
                logger.error("VK: send error: %s", e)
                return False
        return True

    async def send_typing(self, peer_id: str):
        try:
            await _vk_api("messages.setActivity", {
                "access_token": self.token,
                "v": self.api_version,
                "peer_id": int(peer_id),
                "type": "typing",
                "group_id": self.group_id,
            })
        except Exception:
            pass

    async def test_connection(self) -> dict:
        try:
            result = await _vk_api("groups.getById", {
                "access_token": self.token,
                "group_id": self.group_id,
                "v": self.api_version,
            })
            groups = result.get("groups", [])
            if groups:
                return {"ok": True, "name": groups[0].get("name", ""), "group_id": self.group_id}
            return {"ok": False, "error": "No group found"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `cd /home/loki/PTMP/odysseus && python -c "from src.vk_adapter import VKAdapter; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/vk_adapter.py
git commit -m "feat(vk): add VK Messenger adapter core with REST polling"
```

---

### Task 2: Settings defaults — add VK keys to `src/settings.py`

**Covers:** Config storage for VK integration.

**Files:**
- Modify: `src/settings.py` (add VK defaults to `DEFAULT_SETTINGS`)

- [ ] **Step 1: Add VK settings defaults**

In `src/settings.py`, find the `DEFAULT_SETTINGS` dict and add after the `bookstack_token` entry (around line 114):

```python
    # VK Messenger integration
    "vk_token": "",
    "vk_group_id": "",
    "vk_api_version": "5.199",
    "vk_poll_interval": 5,
    "vk_enabled": False,
```

- [ ] **Step 2: Verify settings load**

Run: `cd /home/loki/PTMP/odysseus && python -c "from src.settings import load_settings, DEFAULT_SETTINGS; s = load_settings(); print('vk_enabled:', DEFAULT_SETTINGS.get('vk_enabled')); print('OK')"`
Expected: `vk_enabled: False` then `OK`

- [ ] **Step 3: Commit**

```bash
git add src/settings.py
git commit -m "feat(vk): add VK Messenger settings defaults"
```

---

### Task 3: Backend routes — `routes/vk_routes.py`

**Covers:** API endpoints for VK config, status, start/stop, send, test.

**Files:**
- Create: `routes/vk_routes.py`

- [ ] **Step 1: Create the VK routes module**

```python
"""VK Messenger integration routes."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.auth_helpers import get_current_user
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
        from routes.chat_routes import _get_chat_handler
        chat_handler = _get_chat_handler()
        if not chat_handler:
            logger.warning("VK: chat_handler not available")
            return
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
        from src.user_time import get_user_language
        lang = get_user_language(None)
        import importlib
        locale_mod = importlib.import_module(f"static.locales.{lang}")
        t = locale_mod.t if hasattr(locale_mod, 't') else lambda k, **kw: k
        adapter = _get_adapter()
        if adapter:
            asyncio.create_task(adapter.send_typing(peer_id))
        system_prompt = (
            f"You are chatting via VK Messenger with user {msg['chat_name']}. "
            "Keep responses concise. VK supports plain text only — no Markdown rendering."
        )
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
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `cd /home/loki/PTMP/odysseus && python -c "from routes.vk_routes import router; print('OK', len(router.routes), 'routes')"`
Expected: `OK 7 routes`

- [ ] **Step 3: Register the router in `app.py`**

In `app.py`, find where other route modules are included (around the BookStack/CodeServer section) and add:

```python
from routes.vk_routes import router as vk_router
app.include_router(vk_router)
```

- [ ] **Step 4: Verify app starts**

Run: `cd /home/loki/PTMP/odysseus && python -c "from app import app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add routes/vk_routes.py app.py
git commit -m "feat(vk): add VK Messenger API routes (config, start/stop, send, test)"
```

---

### Task 4: Frontend settings widget — `static/js/vk.js`

**Covers:** UI for VK configuration in admin settings panel.

**Files:**
- Create: `static/js/vk.js`

- [ ] **Step 1: Create the VK settings frontend**

```javascript
/* VK Messenger integration settings widget */
(function() {
    'use strict';

    const VK_PANEL_ID = 'vk-settings-panel';

    function getT(key, fallback) {
        return (window.__t || (k => k))(key) || fallback;
    }

    function render() {
        const existing = document.getElementById(VK_PANEL_ID);
        if (existing) existing.remove();

        const panel = document.createElement('div');
        panel.id = VK_PANEL_ID;
        panel.className = 'settings-section';
        panel.innerHTML = `
            <h3 style="margin:0 0 12px">💬 VK Messenger</h3>
            <div style="display:flex;flex-direction:column;gap:8px;max-width:400px">
                <label style="font-size:12px;color:var(--fg-muted)">API Token</label>
                <input type="password" id="vk-token" placeholder="vk1.a....." style="padding:6px 8px;border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--fg);font-size:13px">
                <label style="font-size:12px;color:var(--fg-muted)">Community ID</label>
                <input type="text" id="vk-group-id" placeholder="123456789" style="padding:6px 8px;border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--fg);font-size:13px">
                <label style="font-size:12px;color:var(--fg-muted)">API Version</label>
                <input type="text" id="vk-api-version" value="5.199" style="padding:6px 8px;border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--fg);font-size:13px">
                <label style="font-size:12px;color:var(--fg-muted)">Poll interval (sec)</label>
                <input type="number" id="vk-poll-interval" value="5" min="1" max="60" style="padding:6px 8px;border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--fg);font-size:13px;width:100px">
                <div style="display:flex;gap:8px;margin-top:8px">
                    <button id="vk-save-btn" style="padding:6px 12px;border:none;border-radius:4px;background:var(--accent);color:#fff;cursor:pointer;font-size:12px">Save</button>
                    <button id="vk-test-btn" style="padding:6px 12px;border:1px solid var(--border);border-radius:4px;background:transparent;color:var(--fg);cursor:pointer;font-size:12px">Test</button>
                    <button id="vk-start-btn" style="padding:6px 12px;border:1px solid var(--green,#4caf50);border-radius:4px;background:transparent;color:var(--green,#4caf50);cursor:pointer;font-size:12px">Start</button>
                    <button id="vk-stop-btn" style="padding:6px 12px;border:1px solid var(--red,#f44336);border-radius:4px;background:transparent;color:var(--red,#f44336);cursor:pointer;font-size:12px;display:none">Stop</button>
                </div>
                <div id="vk-status" style="font-size:12px;color:var(--fg-muted);margin-top:4px"></div>
            </div>
        `;
        return panel;
    }

    async function loadConfig() {
        try {
            const resp = await fetch('/api/vk/config');
            const data = await resp.json();
            const tokenInput = document.getElementById('vk-token');
            const groupIdInput = document.getElementById('vk-group-id');
            const apiVersionInput = document.getElementById('vk-api-version');
            const pollIntervalInput = document.getElementById('vk-poll-interval');
            if (tokenInput && data.token_masked) tokenInput.placeholder = data.token_masked;
            if (groupIdInput) groupIdInput.value = data.group_id || '';
            if (apiVersionInput) apiVersionInput.value = data.api_version || '5.199';
            if (pollIntervalInput) pollIntervalInput.value = data.poll_interval || 5;
        } catch (e) {
            console.error('VK: load config error', e);
        }
    }

    async function loadStatus() {
        try {
            const resp = await fetch('/api/vk/status');
            const data = await resp.json();
            const statusEl = document.getElementById('vk-status');
            const startBtn = document.getElementById('vk-start-btn');
            const stopBtn = document.getElementById('vk-stop-btn');
            if (statusEl) {
                statusEl.textContent = data.running ? `Connected (${data.status})` : `Disconnected${data.error ? ': ' + data.error : ''}`;
                statusEl.style.color = data.running ? 'var(--green,#4caf50)' : 'var(--fg-muted)';
            }
            if (startBtn) startBtn.style.display = data.running ? 'none' : '';
            if (stopBtn) stopBtn.style.display = data.running ? '' : 'none';
        } catch (e) {
            console.error('VK: load status error', e);
        }
    }

    function bindEvents() {
        document.getElementById('vk-save-btn')?.addEventListener('click', async () => {
            const body = {
                token: document.getElementById('vk-token')?.value || '',
                group_id: document.getElementById('vk-group-id')?.value || '',
                api_version: document.getElementById('vk-api-version')?.value || '5.199',
                poll_interval: parseInt(document.getElementById('vk-poll-interval')?.value || '5'),
            };
            try {
                await fetch('/api/vk/config', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(body),
                });
                document.getElementById('vk-status').textContent = 'Saved';
            } catch (e) {
                document.getElementById('vk-status').textContent = 'Error: ' + e.message;
            }
        });

        document.getElementById('vk-test-btn')?.addEventListener('click', async () => {
            const statusEl = document.getElementById('vk-status');
            statusEl.textContent = 'Testing...';
            try {
                const resp = await fetch('/api/vk/test', {method: 'POST'});
                const data = await resp.json();
                statusEl.textContent = data.ok ? `Connected to "${data.name}"` : `Error: ${data.error}`;
                statusEl.style.color = data.ok ? 'var(--green,#4caf50)' : 'var(--red,#f44336)';
            } catch (e) {
                statusEl.textContent = 'Error: ' + e.message;
            }
        });

        document.getElementById('vk-start-btn')?.addEventListener('click', async () => {
            const statusEl = document.getElementById('vk-status');
            statusEl.textContent = 'Starting...';
            try {
                const resp = await fetch('/api/vk/start', {method: 'POST'});
                const data = await resp.json();
                if (data.ok) {
                    await loadStatus();
                } else {
                    statusEl.textContent = 'Error: ' + data.error;
                }
            } catch (e) {
                statusEl.textContent = 'Error: ' + e.message;
            }
        });

        document.getElementById('vk-stop-btn')?.addEventListener('click', async () => {
            await fetch('/api/vk/stop', {method: 'POST'});
            await loadStatus();
        });
    }

    window.VKSettings = {
        render,
        init() {
            loadConfig();
            loadStatus();
            bindEvents();
        },
    };
})();
```

- [ ] **Step 2: Include the script in `static/index.html`**

In `static/index.html`, find where other integration scripts are loaded (near `bookstack.js`, `codeServer.js`) and add:

```html
<script src="/static/js/vk.js"></script>
```

- [ ] **Step 3: Register VK panel in the integrations settings tab**

In `static/js/settings.js`, find the `INTG_TYPES` object (around line 3511) and add a VK entry:

```javascript
    vk: { label: 'VK Messenger', icon: '💬' },
```

Then find where dedicated integration panels are rendered (in `initUnifiedIntegrations()` or the integrations tab init) and add VK panel rendering logic that calls `window.VKSettings.render()` and `window.VKSettings.init()`.

- [ ] **Step 4: Deploy to Docker and verify**

```bash
echo "rt67we45" | sudo -S docker cp src/vk_adapter.py odysseus-odysseus-1:/app/src/vk_adapter.py
echo "rt67we45" | sudo -S docker cp routes/vk_routes.py odysseus-odysseus-1:/app/routes/vk_routes.py
echo "rt67we45" | sudo -S docker cp src/settings.py odysseus-odysseus-1:/app/src/settings.py
echo "rt67we45" | sudo -S docker cp static/js/vk.js odysseus-odysseus-1:/app/static/js/vk.js
echo "rt67we45" | sudo -S docker cp static/index.html odysseus-odysseus-1:/app/static/index.html
echo "rt67we45" | sudo -S docker cp static/js/settings.js odysseus-odysseus-1:/app/static/js/settings.js
echo "rt67we45" | sudo -S docker cp app.py odysseus-odysseus-1:/app/app.py
```

Then restart: `echo "rt67we45" | sudo -S docker compose restart odysseus`

- [ ] **Step 5: Commit**

```bash
git add static/js/vk.js static/index.html static/js/settings.js
git commit -m "feat(vk): add VK Messenger settings widget in admin panel"
```

---

### Task 5: i18n keys for VK

**Covers:** Localization for VK settings labels.

**Files:**
- Modify: `static/locales/en.js`
- Modify: `static/locales/ru.js`

- [ ] **Step 1: Add English locale keys**

In `static/locales/en.js`, add after existing integration keys:

```javascript
    'vk.title': 'VK Messenger',
    'vk.token': 'API Token',
    'vk.groupId': 'Community ID',
    'vk.apiVersion': 'API Version',
    'vk.pollInterval': 'Poll interval (sec)',
    'vk.save': 'Save',
    'vk.test': 'Test',
    'vk.start': 'Start',
    'vk.stop': 'Stop',
    'vk.connected': 'Connected',
    'vk.disconnected': 'Disconnected',
```

- [ ] **Step 2: Add Russian locale keys**

In `static/locales/ru.js`, add:

```javascript
    'vk.title': 'VK Мессенджер',
    'vk.token': 'API Токен',
    'vk.groupId': 'ID Сообщества',
    'vk.apiVersion': 'Версия API',
    'vk.pollInterval': 'Интервал опроса (сек)',
    'vk.save': 'Сохранить',
    'vk.test': 'Тест',
    'vk.start': 'Запустить',
    'vk.stop': 'Остановить',
    'vk.connected': 'Подключено',
    'vk.disconnected': 'Отключено',
```

- [ ] **Step 3: Deploy locale files**

```bash
echo "rt67we45" | sudo -S docker cp static/locales/en.js odysseus-odysseus-1:/app/static/locales/en.js
echo "rt67we45" | sudo -S docker cp static/locales/ru.js odysseus-odysseus-1:/app/static/locales/ru.js
```

- [ ] **Step 4: Commit**

```bash
git add static/locales/en.js static/locales/ru.js
git commit -m "feat(vk): add VK Messenger i18n keys (en/ru)"
```

---

### Task 6: Smoke test and final verification

**Covers:** End-to-end verification.

- [ ] **Step 1: Verify all Python imports**

Run: `cd /home/loki/PTMP/odysseus && python -c "from src.vk_adapter import VKAdapter; from routes.vk_routes import router; from src.settings import DEFAULT_SETTINGS; assert 'vk_token' in DEFAULT_SETTINGS; print('All imports OK')"`

- [ ] **Step 2: Run existing tests (no regressions)**

Run: `cd /home/loki/PTMP/odysseus && source .venv/bin/activate && python -m pytest tests/ -q --tb=short -x --ignore=tests/test_chat_preprocess_tool_policy.py --ignore=tests/test_app_initializer_memory_vector_degraded.py --ignore=tests/test_agent_rounds_exhausted.py 2>&1 | tail -10`

- [ ] **Step 3: Verify Docker deployment**

```bash
echo "rt67we45" | sudo -S docker compose restart odysseus
sleep 10
curl -s -o /dev/null -w "%{http_code}" http://localhost:7000/
```

Expected: `302`

- [ ] **Step 4: Verify VK API endpoint exists**

```bash
curl -s http://localhost:7000/api/vk/status 2>&1
```

Expected: `{"running":false,"status":"disconnected"}`

- [ ] **Step 5: Push all changes**

```bash
git push origin dev
```
