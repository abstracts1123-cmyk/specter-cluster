#!/usr/bin/env bash
# SPECTER installer. Idempotent: safe to re-run. Detection and logging only.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$HOME/.specter"
VENV="$APP_DIR/venv"
UNIT_DIR="$HOME/.config/systemd/user"
URL="http://127.0.0.1:8770"

die() { echo "install.sh: $*" >&2; exit 1; }

# Debian, Ubuntu or Raspberry Pi OS only.
[ -r /etc/os-release ] || die "cannot read /etc/os-release"
# shellcheck disable=SC1091
. /etc/os-release
case " ${ID:-} ${ID_LIKE:-} " in
  *" debian "*|*" ubuntu "*|*" raspbian "*) ;;
  *) die "unsupported OS '${ID:-unknown}': need Debian, Ubuntu or Raspberry Pi OS" ;;
esac

# Run as your normal user, in your own home directory.
[ "$(id -u)" -ne 0 ] || die "do not run as root; run as the user who will drive (sudo is used for apt only)"
[ -n "${HOME:-}" ] && [ -d "$HOME" ] || die "HOME is not set to a directory"
[ "$(stat -c %u "$HOME")" = "$(id -u)" ] || die "$HOME is not owned by $(id -un); refusing to install there"

echo "==> apt packages (python3-venv python3-gps gpsd gpsd-clients)"
sudo apt-get install -y python3-venv python3-gps gpsd gpsd-clients

echo "==> virtualenv at $VENV"
mkdir -p "$APP_DIR"
[ -x "$VENV/bin/python" ] || python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/python" - <<'PY' || die "Python 3.11 or newer is required"
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -e "$REPO_DIR"

echo "==> config"
if [ -e "$APP_DIR/config.toml" ]; then
  echo "    keeping existing $APP_DIR/config.toml"
else
  cp "$REPO_DIR/config.example.toml" "$APP_DIR/config.toml"
  echo "    wrote $APP_DIR/config.toml"
fi

echo "==> user systemd unit"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/specter.service" <<UNIT
[Unit]
Description=SPECTER core (detection and logging only)
After=network.target gpsd.service

[Service]
ExecStart=$VENV/bin/python -m specter.core --config $APP_DIR/config.toml --host 127.0.0.1 --port 8770
WorkingDirectory=$REPO_DIR
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
UNIT
if systemctl --user daemon-reload 2>/dev/null; then
  systemctl --user enable --now specter.service \
    || echo "    could not start the unit now; run: systemctl --user enable --now specter.service"
  echo "    start at boot without login: sudo loginctl enable-linger $(id -un)"
else
  echo "    no user systemd session here; later run: systemctl --user enable --now specter.service"
fi

cat <<MSG

SPECTER is installed. It listens on 127.0.0.1 only.
  Cluster URL : $URL
  Kiosk       : chromium --kiosk --app=$URL
  Demo (no radio): $VENV/bin/python -m specter.core --demo
MSG
