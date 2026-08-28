---
name: proxmox-status
description: Übersicht über Proxmox-Cluster, Nodes und alle Guests (VMs/LXC) anzeigen
allowed-tools:
  - mcp__plugin_proxmox-manager_proxmox__*
---

Zeige eine kompakte Statusübersicht des Proxmox-Clusters:

1. `pve_status` aufrufen. Bei `configured: false` → auf `/proxmox-setup` verweisen und abbrechen.
2. `pve_list_guests` aufrufen.
3. Ergebnis als zwei Tabellen präsentieren:

**Nodes:** Name, Status, Version, CPU-Auslastung, RAM (belegt/gesamt), Uptime.

**Guests:** VMID, Typ (VM/LXC), Name, Node, Status, Cores, RAM, Disk. Templates separat kennzeichnen oder in einer dritten kompakten Gruppe auflisten.

Schließe mit einer Zeile Gesamtzahl: X VMs, Y Container, davon Z laufend.
