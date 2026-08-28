#!/usr/bin/env bash
# Read-only setup check for the proxmox-manager plugin.
set -u
CONFIG_FILE="${PROXMOX_CONFIG_FILE:-$HOME/.config/proxmox-mcp/config.env}"

echo "== proxmox-manager Setup-Check =="
if command -v python3 >/dev/null 2>&1; then
  echo "python3: OK ($(python3 --version 2>&1))"
else
  echo "python3: FEHLT — der MCP-Server benötigt Python 3.10+"
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "config: $CONFIG_FILE existiert NICHT"
  echo "status: NICHT KONFIGURIERT"
  exit 0
fi
echo "config: $CONFIG_FILE vorhanden"

get() { grep -E "^$1=" "$CONFIG_FILE" | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'"; }
HOST="$(get PVE_HOST)"
TOKEN_ID="$(get PVE_TOKEN_ID)"
SECRET="$(get PVE_TOKEN_SECRET)"
VERIFY="$(get PVE_VERIFY_SSL)"

echo "PVE_HOST: ${HOST:-<leer>}"
echo "PVE_TOKEN_ID: ${TOKEN_ID:-<leer>}"
if [[ -n "$SECRET" ]]; then echo "PVE_TOKEN_SECRET: ***gesetzt***"; else echo "PVE_TOKEN_SECRET: <leer>"; fi
echo "PVE_VERIFY_SSL: ${VERIFY:-false}"

if [[ -z "$HOST" || -z "$TOKEN_ID" || -z "$SECRET" ]]; then
  echo "status: KONFIGURATION UNVOLLSTÄNDIG"
  exit 0
fi

python3 - "$HOST" <<'PY'
import ssl, sys, urllib.error, urllib.request
host = sys.argv[1]
if "://" in host:
    url = host.rstrip("/")
else:
    name, _, port = host.partition(":")
    url = f"https://{name}:{port or 8006}"
url += "/api2/json/version"
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
try:
    with urllib.request.urlopen(url, context=ctx, timeout=8) as r:
        print(f"Host erreichbar: HTTP {r.status}")
except urllib.error.HTTPError as e:
    print(f"Host erreichbar: HTTP {e.code} (API antwortet — Auth-Prüfung macht der MCP-Server)")
except Exception as e:
    print(f"Host NICHT erreichbar: {e}")
PY
