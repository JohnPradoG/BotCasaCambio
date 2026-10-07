"""``/actualizar``: baja la última versión desde GitHub y reinicia el bot.

Solo hace ``git pull --ff-only`` en la carpeta del bot (nunca borra cambios locales:
si no puede avanzar, avisa y no hace nada) y, si cambió ``requirements.txt``, instala
las dependencias. El reinicio lo hace systemd (``Restart=always``) cuando el proceso sale.
Solo responde al chat autorizado, como el resto de los comandos. John lo aprobó el 2026-10-07.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class UpdateResult:
    text: str
    restart: bool


def _run(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def self_update(root: Path, run=_run) -> UpdateResult:
    code, before = run(["git", "rev-parse", "--short", "HEAD"], root)
    if code != 0:
        return UpdateResult(f"⚠️ No pude leer la versión actual:\n{before[-500:]}", False)
    code, out = run(["git", "pull", "--ff-only"], root)
    if code != 0:
        return UpdateResult(f"⚠️ No pude actualizar (no cambié nada):\n{out[-800:]}", False)
    _, after = run(["git", "rev-parse", "--short", "HEAD"], root)
    if after == before:
        return UpdateResult(f"✅ Ya estaba en la última versión ({after}).", False)
    _, changed = run(["git", "diff", "--name-only", before, after], root)
    notes = []
    if "requirements.txt" in changed.split():
        code, out = run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"], root, timeout=900)
        if code != 0:
            return UpdateResult(f"⚠️ Bajé la versión {after}, pero falló la instalación de librerías. "
                                f"Sigo con la versión anterior hasta el próximo reinicio:\n{out[-800:]}", False)
        notes.append("Librerías instaladas.")
    _, log = run(["git", "log", "--format=• %s", f"{before}..{after}"], root)
    lines = [f"✅ Actualizado {before} → {after}.", *notes, "Cambios:", log[:1500],
             "Me reinicio ahora; vuelvo a responder en unos minutos."]
    return UpdateResult("\n".join(lines), True)
