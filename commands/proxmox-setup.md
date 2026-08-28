---
name: proxmox-setup
description: Proxmox-Anbindung einrichten oder prüfen (Host, API-Token, Verbindungstest)
allowed-tools:
  - Bash
  - Read
  - Write
  - mcp__plugin_proxmox-manager_proxmox__pve_status
---

Richte die Proxmox-Anbindung für das proxmox-manager-Plugin ein bzw. prüfe sie. Gehe Schritt für Schritt vor:

## 1. Ist-Zustand prüfen

Führe aus: `bash ${CLAUDE_PLUGIN_ROOT}/scripts/check-setup.sh`

Wenn dort `status: KONFIGURIERT`-würdig alles gesetzt ist und der Host erreichbar ist, mach direkt mit Schritt 4 weiter.

## 2. Fehlende Werte vom Nutzer einsammeln

Frage per AskUserQuestion ab, was fehlt:

- **PVE_HOST**: IP/Hostname des Proxmox-Servers, optional mit Port (Default 8006), z.B. `192.168.1.100:8006`
- **PVE_TOKEN_ID**: API-Token-ID im Format `user@realm!tokenname`, z.B. `root@pam!claude`
- **PVE_TOKEN_SECRET**: das Token-Secret (UUID)

Wenn der Nutzer noch **keinen API-Token** hat, führe ihn durch die Anlage in der Proxmox-Web-UI:

1. Proxmox-Web-UI öffnen → **Datacenter → Permissions → API Tokens** → **Add**
2. User wählen (z.B. `root@pam`), Token ID z.B. `claude`, kein Ablaufdatum
3. **Das Secret wird nur einmal angezeigt** — sofort kopieren
4. Danach Rechte setzen: **Datacenter → Permissions → Add → API Token Permission**
   - Path: `/`, Role: `PVEAdmin` (empfohlen für eigenständiges Erstellen)
   - Alternativ restriktiver: `PVEVMAdmin` + `PVEDatastoreAdmin` auf `/` (reicht für VM/LXC-Erstellung, nicht für Netzwerk-/Storage-Änderungen)

**Wichtig:** Token-Secret niemals in Chat-Zusammenfassungen, Logs oder andere Dateien wiederholen — nur in die Config-Datei schreiben.

## 3. Config-Datei schreiben

Lege `~/.config/proxmox-mcp/config.env` an (Verzeichnis bei Bedarf mit anlegen, Dateirechte 600 setzen via `chmod 600`):

```
# Proxmox MCP Konfiguration (proxmox-manager Plugin)
PVE_HOST=<host[:port]>
PVE_TOKEN_ID=<user@realm!token>
PVE_TOKEN_SECRET=<secret>
PVE_VERIFY_SSL=false
```

Hinweis: `PVE_VERIFY_SSL=false` ist Default, weil Proxmox selbstsignierte Zertifikate nutzt. Nur auf `true` stellen, wenn eine gültige CA-Zertifikatskette vorhanden ist.

Der MCP-Server liest die Datei bei jedem Tool-Aufruf neu — **kein Neustart von Claude Code nötig**.

## 4. Verbindung verifizieren

Rufe das MCP-Tool `pve_status` auf. Wenn `connected: true` zurückkommt: Zeige dem Nutzer Proxmox-Version und Nodes in einer kompakten Tabelle und bestätige, dass das Plugin einsatzbereit ist.

Bei Fehlern:
- `401/403`: Token-ID/Secret falsch oder keine Berechtigung (API-Token-Permission fehlt) → Schritt 2 wiederholen
- Verbindungsfehler: Host/Port/Firewall prüfen
