---
name: proxmox-create-ct
description: Einen LXC-Container in Proxmox erstellen — interaktiv oder nach Vorgaben des Nutzers
argument-hint: [Hostname und optionale Vorgaben, z.B. "nginx-ct auf debian-12"]
allowed-tools:
  - AskUserQuestion
  - Bash
  - mcp__plugin_proxmox-manager_proxmox__*
---

Erstelle eigenständig einen LXC-Container in Proxmox. Argumente des Nutzers: $ARGUMENTS

## Vorgehen

1. **Verbindung prüfen:** `pve_status` aufrufen. Bei `configured: false` → den Nutzer auf `/proxmox-setup` verweisen und abbrechen.
2. **Anforderungen klären:** Aus den Argumenten und ggf. Rückfragen (AskUserQuestion) ermitteln:
   - Hostname (Pflicht)
   - Distribution/Template: Mit `pve_list_templates` (lokale LXC-Templates) oder `pve_list_appliances` prüfen. Ein Appliance-Name wie `debian-12-standard` kann direkt als `ostemplate` übergeben werden (Proxmox lädt automatisch herunter).
   - Ressourcen: Cores (Default 2), RAM in MiB (Default 1024), Swap (Default 512), Root-Disk in GB (Default 8)
   - Netzwerk: Bridge (Default `vmbr0`), DHCP (Default) oder statische IP (nur auf expliziten Wunsch → `net0=name=eth0,bridge=vmbr0,ip=<ip>/<maske>,gw=<gateway>,firewall=1`)
   - Zugang: Root-Passwort und/oder SSH-Public-Key des Nutzers. **Keine Passwörter erfinden** — wenn der Nutzer nichts angibt, nachfragen oder leer lassen und am Ende darauf hinweisen, dass das Passwort noch zu setzen ist (`pve_set_password`).
   - Zielspeicher (Default `local-lvm`, per `pve_list_storages` verifizieren) und Ziel-Node (Default: erste Online-Node)
3. **Erstellen:** `pve_create_container` aufrufen — `unprivileged: true` und `nesting: true` als Defaults beibehalten (Nesting ermöglicht z.B. Docker im Container). `start: true` setzen, wenn der Nutzer nichts anderes sagt.
4. **Verifizieren:** `pve_guest_status` (muss `running` sein) und `pve_get_ips` aufrufen. Falls die IP noch nicht da ist: einmal kurz warten und erneut versuchen.
5. **Ergebnis melden:** Kompakte Zusammenfassung mit VMID, Node, Hostname, Distribution, Ressourcen, IP und Zugangsweg (SSH).

## Leitplanken

- Lösche niemals vorhandene Guests oder Templates.
- Vergib keine statischen IPs außerhalb der vom Nutzer genannten Werte.
- Wenn `pve_create_container` fehlschlägt: Fehlermeldung analysieren, einmal gezielt korrigieren (z.B. Template-Name, Storage), sonst dem Nutzer berichten statt blind zu retryen.
