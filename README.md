# proxmox-manager — Claude-Code-Plugin für Proxmox VE

Befähigt Claude Code, **eigenständig virtuelle Maschinen (KVM) und LXC-Container in Proxmox VE** zu erstellen, zu starten, zu stoppen und zu verwalten — direkt über die Proxmox-REST-API (`/api2/json`) mit API-Token-Auth.

## Enthaltene Bausteine

| Baustein | Zweck |
| --- | --- |
| MCP-Server `proxmox` | 17 Tools rund um Proxmox (`pve_create_vm`, `pve_create_container`, `pve_list_guests`, …) — **zero-dependency** (nur Python-Stdlib) |
| `/proxmox` | **Onboarding/Einstieg:** erkennt beim ersten Aufruf, dass noch kein Host eingerichtet ist, und führt durch das komplette Setup; danach Cluster-Übersicht + Cheat-Sheet |
| `/proxmox-setup` | Geführte Einrichtung: Host + API-Token konfigurieren, Verbindung testen |
| `/proxmox-create-vm` | VM erstellen (Template-Klon mit Cloud-Init oder ISO-Installation) |
| `/proxmox-create-ct` | LXC-Container erstellen (inkl. automatischem Appliance-Download) |
| `/proxmox-status` | Cluster-Übersicht: Nodes + alle Guests |
| Skill `proxmox-orchestration` | Aktiviert sich automatisch bei Proxmox-Anfragen und steuert den End-to-End-Workflow |

## Voraussetzungen

- Proxmox VE 7/8/9 mit erreichbarer API (Port 8006)
- Python 3.10+ auf dem Claude-Code-Rechner (keine pip-Pakete nötig)
- API-Token in Proxmox mit Rolle `PVEAdmin` auf `/` (oder restriktiver `PVEVMAdmin` + `PVEDatastoreAdmin`)

## Installation

```text
/plugin marketplace add /root/proxmox-manager
/plugin install proxmox-manager@proxmox-manager
```

Danach in einer Claude-Code-Session einfach **`/proxmox`** aufrufen: Das Onboarding erkennt, dass noch kein Host konfiguriert ist, fragt Host, Token-ID und Token-Secret ab (inkl. Schritt-für-Schritt-Anleitung zum Anlegen des Tokens in der Proxmox-Web-UI) und schreibt alles nach `~/.config/proxmox-mcp/config.env` (chmod 600). Der MCP-Server liest die Datei bei jedem Aufruf neu — für reine Config-Änderungen ist kein Claude-Code-Neustart nötig. Nach der Erstinstallation des Plugins empfiehlt sich aber ein Neustart, damit der MCP-Server geladen wird.

## Konfiguration

`~/.config/proxmox-mcp/config.env`:

```ini
PVE_HOST=<proxmox-host>:8006
PVE_TOKEN_ID=<user@realm!token>
PVE_TOKEN_SECRET=<uuid>
PVE_VERIFY_SSL=false
```

Umgebungsvariablen gleichen Namens (`PVE_HOST`, `PVE_TOKEN_ID`, `PVE_TOKEN_SECRET`, `PVE_VERIFY_SSL`) überschreiben die Datei. `PVE_VERIFY_SSL=false` ist der Default, da Proxmox selbstsignierte Zertifikate ausliefert.

## Beispiele

```text
/proxmox-create-vm deb12-dev, 4 Cores, 8 GB RAM, Template
/proxmox-create-ct nginx-proxy auf debian-12
Erstell mir einen Docker-Host als VM in Proxmox      → Skill greift eigenständig
/proxmox-status
```

## MCP-Tools (Auszug)

- `pve_status`, `pve_list_nodes`, `pve_list_storages`, `pve_list_guests`
- `pve_list_templates`, `pve_list_appliances`, `pve_next_vmid`
- `pve_create_vm` (Template-Klon + Cloud-Init: `ciuser`, `cipassword`, `sshkeys`, `ipconfig0`; oder ISO-Installation)
- `pve_create_container` (Appliance-Name wird automatisch heruntergeladen; `nesting=1` als Default)
- `pve_guest_status`, `pve_start_guest`, `pve_stop_guest`, `pve_delete_guest` (erfordert `confirm: true` und gestoppten Guest)
- `pve_get_ips` (QEMU-Guest-Agent, Fallback Konfiguration), `pve_set_password`, `pve_task_status`, `pve_wait_for_task`

## Sicherheit

- Das Token-Secret liegt nur in `~/.config/proxmox-mcp/config.env` (chmod 600) und wird vom Setup-Skript maskiert ausgegeben.
- `pve_delete_guest` verweigert die Arbeit ohne `confirm: true` und ohne vorherigen Stopp des Guests.
- Empfohlene minimale Rolle statt `PVEAdmin`: eigene Rolle mit `VM.Allocate`, `VM.Clone`, `VM.Config.*`, `VM.PowerMgmt`, `Datastore.AllocateSpace`, `Sys.Audit` auf `/`.
- Alle Änderungen laufen über die auditierbare Proxmox-API (der API-User erscheint im Proxmox-Task-Log).

## Deinstallation

```text
/plugin uninstall proxmox-manager@proxmox-manager
/plugin marketplace remove proxmox-manager
```

Optional Config entfernen: `rm -rf ~/.config/proxmox-mcp`
