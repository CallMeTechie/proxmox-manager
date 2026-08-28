---
name: proxmox
description: Einstiegspunkt des proxmox-manager-Plugins — beim ersten Aufruf Onboarding/Host-Setup, danach Cluster-Übersicht
allowed-tools:
  - AskUserQuestion
  - Bash
  - Read
  - Write
  - mcp__plugin_proxmox-manager_proxmox__*
---

Einstiegspunkt des proxmox-manager-Plugins. Prüfe zuerst den Einrichtungszustand:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/check-setup.sh
```

## Fall A: Noch nicht konfiguriert (erstmaliger Aufruf / Onboarding)

Lies `${CLAUDE_PLUGIN_ROOT}/commands/proxmox-setup.md` und führe das dort beschriebene Setup **Schritt für Schritt** aus:

1. Ist-Zustand ist bereits geprüft (siehe oben).
2. Fehlende Werte per AskUserQuestion einsammeln (Host, Token-ID, Token-Secret). Wenn der Nutzer noch keinen API-Token hat: Anleitung zum Anlegen in der Proxmox-Web-UI geben (inkl. Rolle `PVEAdmin` auf `/` nicht vergessen — häufigster Fehler!).
3. Config-Datei `~/.config/proxmox-mcp/config.env` schreiben (chmod 600).
4. Verbindung mit `pve_status` verifizieren.
5. Zum Abschluss des Onboardings die Willkommens-Übersicht aus Fall B anzeigen.

## Fall B: Konfiguriert

1. `pve_status` und `pve_list_guests` aufrufen.
2. Kompakte Übersicht zeigen: Proxmox-Version, Node(s) mit CPU/RAM, Anzahl VMs/Container (davon laufend).
3. Danach die verfügbaren Befehle als Cheat-Sheet auflisten:

| Befehl | Zweck |
| --- | --- |
| `/proxmox-setup` | Verbindung neu einrichten/prüfen (Host, Token) |
| `/proxmox-create-vm` | VM erstellen (Template-Klon oder ISO) |
| `/proxmox-create-ct` | LXC-Container erstellen |
| `/proxmox-status` | Detaillierte Cluster-/Guest-Übersicht |

Hinweis: Alternativ kann der Nutzer Proxmox-Aufträge auch frei formulieren (z.B. „Erstell mir einen Debian-Container mit 2 GB RAM“) — der Skill `proxmox-orchestration` übernimmt dann eigenständig.
