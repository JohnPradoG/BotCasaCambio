#!/usr/bin/env bash
# Instala o actualiza BotCasaCambio en un VPS Ubuntu/Debian. Ejecutar como root:
#
#   curl -fsSL https://raw.githubusercontent.com/JohnPradoG/BotCasaCambio/main/scripts/install_vps.sh | bash
#
# Se puede volver a ejecutar: actualiza el código y reinicia el bot sin tocar .env ni la base.
# Pide el token de Telegram y el chat id solo la primera vez.
set -euo pipefail

REPO=https://github.com/JohnPradoG/BotCasaCambio.git
DIR=/opt/BotCasaCambio
BRANCH=${BRANCH:-main}
FALLBACK_BRANCH=claude/fase-1-arquitectura-aiiadm
SCRAPERS=manual_csv,web_discovery,gamaex,cambios_lyon,inmonex,brollano,cambio_costero,afex,more_exchange,cambios_santiago,orion

[ "$(id -u)" -eq 0 ] || { echo "Ejecutar como root"; exit 1; }
as_bot() { sudo -u bot -H bash -c "cd $DIR && $*"; }

echo "==> Paquetes del sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 python3-venv python3-pip git sudo curl tzdata

id bot >/dev/null 2>&1 || useradd -m -s /bin/bash bot

echo "==> Código"
if [ -d "$DIR/.git" ]; then
    as_bot "git pull --ff-only"
else
    mkdir -p "$DIR" && chown bot: "$DIR"
    as_bot "git clone $REPO ."
    # Mientras el PR no esté en main, el bot vive en la rama de desarrollo.
    if [ ! -f "$DIR/app/main.py" ] || [ "$BRANCH" != main ]; then
        target=$BRANCH; [ -f "$DIR/app/main.py" ] || target=$FALLBACK_BRANCH
        as_bot "git checkout $target"
    fi
fi

echo "==> Dependencias de Python y navegador (para webs con JavaScript)"
as_bot "[ -d .venv ] || python3 -m venv .venv"
as_bot ".venv/bin/pip install -q --upgrade pip"
as_bot ".venv/bin/pip install -q -r requirements.txt -r requirements-browser.txt"
"$DIR/.venv/bin/python" -m playwright install-deps chromium
as_bot ".venv/bin/python -m playwright install chromium"

echo "==> Configuración (.env)"
if [ ! -f "$DIR/.env" ]; then
    cp "$DIR/.env.example" "$DIR/.env"
    read -r -p "Token del bot de Telegram (de BotFather): " token </dev/tty
    read -r -p "Chat id de Telegram: " chat </dev/tty
    sed -i "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=$token|; s|^TELEGRAM_CHAT_ID=.*|TELEGRAM_CHAT_ID=$chat|; \
s|^ENABLED_SCRAPERS=.*|ENABLED_SCRAPERS=$SCRAPERS|" "$DIR/.env"
    chown bot: "$DIR/.env" && chmod 600 "$DIR/.env"
else
    echo ".env ya existe; no se modifica"
fi
as_bot ".venv/bin/python -m app.main init-db"

echo "==> Servicios"
cp "$DIR"/deploy/botcasacambio.service "$DIR"/deploy/botcasacambio-dashboard.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable botcasacambio botcasacambio-dashboard
systemctl restart botcasacambio botcasacambio-dashboard

echo "==> Prueba de Telegram"
as_bot ".venv/bin/python -m app.main telegram-test" || echo "Telegram falló: revisa TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en $DIR/.env"

echo "==> Revisión de todas las webs (puede tardar varios minutos)"
as_bot ".venv/bin/python -m app.main probe-all" || true

cat <<EOF

Listo. El bot corre solo y vuelve a arrancar si el servidor se reinicia.
  Ver lo que hace:   journalctl -u botcasacambio -f
  Reiniciar:         systemctl restart botcasacambio
  Actualizar:        vuelve a ejecutar este mismo comando
  Reporte de webs:   $DIR/data/probe/report.json
EOF
