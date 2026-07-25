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
