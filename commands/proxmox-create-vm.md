---
name: proxmox-create-vm
description: Eine VM (KVM) in Proxmox erstellen — interaktiv oder nach Vorgaben des Nutzers
argument-hint: [Name und optionale Vorgaben, z.B. "deb12, 4 Cores, 8 GB RAM"]
allowed-tools:
  - AskUserQuestion
  - Bash
  - mcp__plugin_proxmox-manager_proxmox__*
---

Erstelle eigenständig eine KVM/VM in Proxmox. Argumente des Nutzers: $ARGUMENTS

## Vorgehen

1. **Verbindung prüfen:** `pve_status` aufrufen. Bei `configured: false` → den Nutzer auf `/proxmox-setup` verweisen und abbrechen.
2. **Anforderungen klären:** Aus den Argumenten und ggf. Rückfragen (AskUserQuestion) ermitteln:
   - Name/Hostname (Pflicht)
   - Betriebssystem/Vorlage: **Bevorzugt ein vorhandenes Template klonen** (schneller, mit Cloud-Init) statt ISO-Neuinstallation. Mit `pve_list_templates` prüfen, was da ist. Nur wenn kein passendes Template existiert: ISO-Installation (`pve_list_templates` zeigt ISOs).
   - Ressourcen: Cores (Default 2), RAM in MiB (Default 2048), Disk-Größe (Default 32G)
   - Netzwerk: Bridge (Default `vmbr0`), DHCP (Default) oder statische IP (nur wenn der Nutzer explizit eine angibt → dann `ipconfig0=ip=<ip>/<maske>,gw=<gateway>`)
   - Zielspeicher (Default `local-lvm`, per `pve_list_storages` verifizieren) und Ziel-Node (Default: erste Online-Node)
3. **Erstellen:** `pve_create_vm` mit den gesammelten Parametern. Bei Template-Klon mit Cloud-Init immer `ciuser` setzen; `cipassword` oder `sshkeys` nur wenn vom Nutzer geliefert. **Keine Zugangsdaten erfinden.** `start: true` setzen, wenn der Nutzer nichts anderes sagt.
4. **Verifizieren:** `pve_guest_status` (muss `running` sein) und `pve_get_ips` aufrufen. Falls die IP noch nicht da ist (Cloud-Init braucht ~10–30 s): einmal kurz warten und erneut versuchen.
5. **Ergebnis melden:** Kompakte Zusammenfassung mit VMID, Node, Name, Ressourcen, IP und Hinweisen (z.B. SSH-Zugang bei gesetztem Key/Passwort).

## Leitplanken

- Lösche niemals vorhandene Guests oder Templates.
- Vergib keine statischen IPs außerhalb der vom Nutzer genannten Werte.
- Wenn `pve_create_vm` fehlschlägt: Fehlermeldung analysieren, einmal gezielt korrigieren (z.B. anderer Storage), sonst dem Nutzer berichten statt blind zu retryen.
