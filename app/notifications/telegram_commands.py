"""Comandos por Telegram mientras corre ``loop``: cargar precios desde el celular.

Solo se aceptan mensajes del chat configurado en ``TELEGRAM_CHAT_ID``; el resto se
ignora. Comandos:

* ``/precio <casa> <divisa> <compra> <venta>``: guarda un precio visto en una pizarra
  o confirmado por teléfono y responde con la mejor ruta actual.
* ``/top``: Top N con lo que hay guardado (sin consultar las casas).
* ``/casas``: nombres que se pueden usar en ``/precio``.
* ``/lista``: planilla con todas las casas, con y sin precio, y sus teléfonos.
* ``/precios [divisa]``: precios guardados de hoy (resumen, o detalle de una divisa).
* ``/cerca``: por divisa, la ruta más cercana a dar ganancia y cuánto le falta.
* ``/estado``: qué casas con precio en la web se están leyendo bien.
* ``/ayuda``.

El bot nunca ejecuta operaciones: solo registra y calcula.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests

from app.config.settings import Settings
from app.models.currency import normalize_currency_code
from app.services.manual_entry import USAGE, ManualEntryError, parse_price_command, save_manual_price

logger = logging.getLogger(__name__)

HELP = (
    "Comandos:\n"
    "/precio <casa> <divisa> <compra> <venta>: guarda un precio (ej. /precio gamaex USD 970 990)\n"
    "/top: mejores rutas con los precios guardados\n"
    "/casas: nombres de casas para /precio\n"
    "/lista: planilla de casas con y sin precio, con teléfonos para llamar\n"
    "/precios: mejores precios de hoy; /precios USD: todas las casas para esa divisa\n"
    "/cerca: qué tan cerca está cada divisa de dar ganancia\n"
    "/estado: qué casas se están leyendo bien desde su web\n"
    "El bot solo calcula y avisa; nunca compra ni vende."
)


@dataclass
class CommandHandlers:
    """Acciones que necesitan la base de datos; se inyectan para poder probarlas."""

    known_houses: Callable[[], dict[str, str]]
    after_price: Callable[[], str]  # recalcula y devuelve un resumen corto
    top: Callable[[], str]
    house_list: Callable[[], tuple[Path, str]] | None = None  # (archivo CSV, resumen)
    prices: Callable[[str | None], str] | None = None  # divisa o None → texto
    near: Callable[[], str] | None = None  # rutas más cercanas a dar ganancia
    health: Callable[[], str] | None = None  # estado de las casas leídas desde su web


@dataclass
class TelegramCommandPoller:
    settings: Settings
    handlers: CommandHandlers
    session: requests.Session = field(default_factory=requests.Session)
    offset_file: Path | None = None
    timeout: float = 15

    def __post_init__(self):
        self.base = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}"
        self.offset_file = self.offset_file or Path(self.settings.manual_quotes_file).with_name("telegram_offset.txt")

    # ------------------------------------------------------------ offset
    def _offset(self) -> int | None:
        try:
            return int(self.offset_file.read_text().strip())
        except (OSError, ValueError):
            return None

    def _save_offset(self, value: int) -> None:
        self.offset_file.parent.mkdir(parents=True, exist_ok=True)
        self.offset_file.write_text(str(value))

    # -------------------------------------------------------------- API
    def _send(self, text: str) -> None:
        try:
            self.session.post(f"{self.base}/sendMessage", json={"chat_id": self.settings.telegram_chat_id,
                                                                  "text": text}, timeout=self.timeout)
        except requests.RequestException as exc:
            logger.warning("No se pudo responder por Telegram: %s", exc)

    def _send_document(self, path: Path, caption: str) -> bool:
        try:
            with path.open("rb") as f:
                resp = self.session.post(f"{self.base}/sendDocument", data={"chat_id": self.settings.telegram_chat_id,
                                                                            "caption": caption[:1000]},
                                         files={"document": f}, timeout=self.timeout * 4)
            return resp.status_code == 200
        except (OSError, requests.RequestException) as exc:
            logger.warning("No se pudo enviar el archivo por Telegram: %s", exc)
            return False

    def poll_once(self, wait_seconds: int = 0) -> int:
        """Lee mensajes nuevos y los procesa. Devuelve cuántos comandos atendió."""
        params = {"timeout": wait_seconds, "allowed_updates": '["message"]'}
        offset = self._offset()
        if offset is not None:
            params["offset"] = offset
        try:
            resp = self.session.get(f"{self.base}/getUpdates", params=params, timeout=wait_seconds + self.timeout)
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Telegram getUpdates falló: %s", exc)
            return 0
        if not data.get("ok"):
            logger.warning("Telegram getUpdates: %s", data.get("description"))
            return 0
        handled = 0
        for update in data.get("result", []):
            self._save_offset(update["update_id"] + 1)
            message = update.get("message") or {}
            chat_id = str((message.get("chat") or {}).get("id", ""))
            text = (message.get("text") or "").strip()
            if chat_id != str(self.settings.telegram_chat_id):
                logger.warning("Mensaje de Telegram ignorado: chat %s no autorizado", chat_id or "?")
                continue
            if text.startswith("/"):
                self._send(self.handle(text))
                handled += 1
        return handled

    def wait(self, seconds: float) -> None:
        """Espera ``seconds`` atendiendo comandos (long polling) en vez de dormir."""
        end = time.monotonic() + seconds
        while (remaining := end - time.monotonic()) > 1:
            self.poll_once(wait_seconds=int(min(remaining, 50)))

    # ---------------------------------------------------------- comandos
    def handle(self, text: str) -> str:
        command = text.split()[0].split("@")[0].lower()
        try:
            if command in ("/precio", "/p"):
                price = parse_price_command(text, self.handlers.known_houses())
                save_manual_price(self.settings.manual_quotes_file, price,
                                  source=f"telegram:{self.settings.telegram_chat_id}", notes="ingresado por Telegram")
                sides = []
                if price.buy_rate is not None:
                    sides.append(f"compra {price.buy_rate:g}")
                if price.sell_rate is not None:
                    sides.append(f"venta {price.sell_rate:g}")
                return f"✅ Guardado: {price.house} {price.currency} {' · '.join(sides)}\n\n{self.handlers.after_price()}"
            if command == "/top":
                return self.handlers.top()
            if command == "/casas":
                houses = self.handlers.known_houses()
                return "Casas registradas:\n" + "\n".join(f"{slug} ({name})" for slug, name in sorted(houses.items()))
            if command == "/precios" and self.handlers.prices:
                arg = text.split()[1] if len(text.split()) > 1 else None
                currency = normalize_currency_code(arg) if arg else None
                if arg and not currency:
                    return f"No reconozco la divisa {arg!r}. Ejemplo: /precios USD"
                return self.handlers.prices(currency)
            if command == "/cerca" and self.handlers.near:
                return self.handlers.near()
            if command == "/estado" and self.handlers.health:
                return self.handlers.health()
            if command == "/lista" and self.handlers.house_list:
                path, text = self.handlers.house_list()
                return text if self._send_document(path, "Casas de cambio") else f"{text}\n⚠️ No se pudo enviar la planilla."
            if command in ("/ayuda", "/help", "/start"):
                return HELP
            return f"No conozco ese comando.\n\n{HELP}"
        except ManualEntryError as exc:
            return f"⚠️ {exc}" if str(exc) != USAGE else USAGE
        except Exception as exc:  # noqa: BLE001 - un comando roto no debe tumbar el bucle
            logger.exception("Error atendiendo comando de Telegram")
            return f"⚠️ Error: {type(exc).__name__}"
