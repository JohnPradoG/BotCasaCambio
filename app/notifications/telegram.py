"""Envío de alertas por Telegram (Bot API, solo ``sendMessage``)."""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

MAX_LEN = 4000  # el límite de Telegram es 4096 caracteres


def split_message(text: str, limit: int = MAX_LEN) -> list[str]:
    chunks, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit:
            chunks.append(current.rstrip("\n"))
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current.rstrip("\n"))
    return chunks


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, session: requests.Session | None = None, timeout: float = 15):
        self.token = token
        self.chat_id = chat_id
        self.session = session or requests.Session()
        self.timeout = timeout

    def send(self, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        ok = True
        for chunk in split_message(text):
            try:
                resp = self.session.post(
                    url, json={"chat_id": self.chat_id, "text": chunk, "disable_web_page_preview": True},
                    timeout=self.timeout,
                )
                if resp.status_code != 200:
                    logger.error("Telegram respondió %s: %s", resp.status_code, resp.text[:300])
                    ok = False
            except requests.RequestException as exc:
                logger.error("No se pudo enviar a Telegram: %s", exc)
                ok = False
        if ok:
            logger.info("Telegram enviado")
        return ok


    def send_document(self, path, caption: str = "") -> bool:
        try:
            with open(path, "rb") as f:
                resp = self.session.post(f"https://api.telegram.org/bot{self.token}/sendDocument",
                                         data={"chat_id": self.chat_id, "caption": caption[:1000]},
                                         files={"document": f}, timeout=self.timeout * 4)
        except (OSError, requests.RequestException) as exc:
            logger.error("No se pudo enviar el archivo a Telegram: %s", exc)
            return False
        if resp.status_code != 200:
            logger.error("Telegram respondió %s: %s", resp.status_code, resp.text[:300])
            return False
        return True


class ConsoleNotifier:
    """Se usa cuando Telegram no está configurado: escribe la alerta en el log."""

    def send(self, text: str) -> bool:
        logger.info("ALERTA (Telegram no configurado):\n%s", text)
        return True


def find_chat_ids(token: str, session: requests.Session | None = None, timeout: float = 15) -> list[dict]:
    """Chats que le escribieron al bot (getUpdates), para llenar TELEGRAM_CHAT_ID."""
    session = session or requests.Session()
    resp = session.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=timeout)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram respondió: {data.get('description', resp.status_code)}")
    chats: dict[int, dict] = {}
    for update in data.get("result", []):
        message = update.get("message") or update.get("channel_post") or update.get("my_chat_member") or {}
        chat = message.get("chat") or {}
        if "id" in chat:
            name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
            chats[chat["id"]] = {"id": chat["id"], "type": chat.get("type"), "name": name or chat.get("username")}
    return list(chats.values())
