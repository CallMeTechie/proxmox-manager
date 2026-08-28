---
name: proxmox-orchestration
description: This skill should be used when the user wants to create, start, stop, clone, inspect, or delete virtual machines (VM/KVM/qemu) or LXC containers on Proxmox VE — e.g. "erstelle eine VM", "neuen Container aufsetzen", "mach mir einen Debian-Server", "Proxmox", "PVE", "VMID", "LXC". It orchestrates the proxmox MCP tools end-to-end.
version: 1.0.0
---

# Proxmox-Orchestrierung

Du verwaltest Proxmox VE eigenständig über die MCP-Tools `mcp__plugin_proxmox-manager_proxmox__pve_*`. Der Nutzer erwartet, dass du sinnvoll selbst entscheidest und nur bei echten Mehrdeutigkeiten nachfragst.

## Grundregeln

1. **Erster Schritt immer:** `pve_status` aufrufen. Bei `configured: false` auf `/proxmox-setup` verweisen und stoppen.
2. **Erst schauen, dann handeln:** Vor jeder Erstellung mit `pve_list_guests` (existierende VMIDs/Namen), `pve_list_templates`/`pve_list_appliances` (verfügbare Vorlagen) und `pve_list_storages` (Speicherplatz) den Ist-Zustand prüfen.
3. **Niemals destruktiv ohne Auftrag:** `pve_delete_guest` und `pve_stop_guest` nur, wenn der Nutzer es explizit verlangt. Vor dem Löschen immer mit dem Nutzer bestätigen (Name + VMID nennen).
4. **Keine erfundenen Zugangsdaten:** Passwörter/SSH-Keys nur vom Nutzer übernehmen, sonst nachfragen.

## Entscheidungsheuristik: VM oder LXC?

- **LXC-Container** bevorzugen für: schlanke Linux-Dienste (Webserver, Datenbank, Docker-Host mit `nesting=1`), wenn kein eigener Kernel/hypervisor-spezifische Features nötig sind. Schneller, ressourcensparender.
- **KVM/VM** für: andere Betriebssysteme als Linux, eigene Kernel, Isolation auf VM-Ebene, wenn der Nutzer explizit "VM" sagt.
- Bei "Container" ist immer LXC auf Proxmox gemeint (nicht Docker) — außer der Nutzer spricht explizit von Docker *in* einem Guest (dann LXC mit Nesting oder VM mit Docker-Setup).

## Erstellungs-Workflow

1. Ziel ermitteln: Name, OS, Ressourcen. Bei knappen Angaben sinnvolle Defaults nutzen und sie dem Nutzer im Ergebnis nennen: 2 Cores, VM 2 GB RAM / LXC 1 GB RAM, VM-Disk 32 GB / LXC 8 GB, Netzwerk DHCP über `vmbr0`.
2. **Template vor ISO:** Wenn ein passendes Template existiert (z.B. cloud-init-fähiges Debian/Ubuntu-Template), klonen (`pve_create_vm` mit `template=<VMID>`) statt ISO-Neuinstallation — das ist der schnellste und sauberste Weg. Für LXC: `pve_list_appliances`/`pve_list_templates` konsultieren; Appliance-Namen wie `debian-12-standard` werden automatisch heruntergeladen.
3. VMID automatisch vergeben lassen (nicht selbst raten; das Tool prüft Belegung).
4. Nur eine Node wählen, wenn mehrere existieren — sonst die einzige/erste Online-Node verwenden.
5. Erstellung mit `start: true`, sofern der Nutzer kein "nur anlegen/offline" verlangt.
6. **Nachbereitung:** `pve_guest_status` prüfen (Status `running`), dann `pve_get_ips` für die IP. Kommt noch keine IP: ~15–30 s warten (Cloud-Init/DHCP braucht kurz) und einmal erneut versuchen. Danach nicht weiter pollen.
7. **Abschlussbericht** immer mit: VMID, Typ, Name/Hostname, Node, Ressourcen, IP, Zugangsweg (SSH-User/Key/Passwort-Hinweis), ggf. nächste Schritte.

## Statische IPs

Nur setzen, wenn der Nutzer explizit IP, Maske und Gateway nennt:
- VM (Cloud-Init): `ipconfig0=ip=<ip>/<maske>,gw=<gateway>`
- LXC: `net0=name=eth0,bridge=vmbr0,ip=<ip>/<maske>,gw=<gateway>,firewall=1`

## Fehlerbehandlung

- Task-/API-Fehler zuerst lesen und verstehen (in der Meldung steht meist die Ursache, z.B. zu wenig Speicherplatz, Template nicht gefunden).
- Genau **ein** gezielter Korrekturversuch (z.B. anderer Storage, korrigierter Template-Name). Danach dem Nutzer den Fehler berichten statt weiter zu probieren.
- Läuft ein Guest nach dem Start nicht: `pve_guest_status` konsultieren; Logs/Tasks nur auf Nachfrage des Nutzers vertiefen.
