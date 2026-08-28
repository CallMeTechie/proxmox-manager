#!/usr/bin/env python3
"""Zero-dependency MCP stdio server for Proxmox VE.

Implements the MCP stdio transport (newline-delimited JSON-RPC 2.0) and talks
to the Proxmox VE REST API (/api2/json) using an API token.

Configuration (env vars win over the config file):
  PVE_HOST          host[:port] or full URL (default port 8006)
  PVE_TOKEN_ID      e.g. root@pam!claude
  PVE_TOKEN_SECRET  the token secret (UUID)
  PVE_VERIFY_SSL    true/false (default false; Proxmox ships self-signed certs)

Config file fallback: ~/.config/proxmox-mcp/config.env (KEY=VALUE lines).
"""

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "proxmox-mcp"
SERVER_VERSION = "1.0.0"
CONFIG_PATH = Path.home() / ".config" / "proxmox-mcp" / "config.env"
CONFIG_KEYS = ("PVE_HOST", "PVE_TOKEN_ID", "PVE_TOKEN_SECRET", "PVE_VERIFY_SSL")


def log(msg: str) -> None:
    print(f"[{SERVER_NAME}] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def load_config() -> dict:
    cfg = {}
    try:
        if CONFIG_PATH.exists():
            for line in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                cfg[key.strip()] = value.strip().strip('"').strip("'")
    except OSError as exc:
        log(f"config file read error: {exc}")
    for key in CONFIG_KEYS:
        value = os.environ.get(key, "")
        if value:
            cfg[key] = value
    return cfg


class PVEError(Exception):
    """Raised for any Proxmox/config problem; message is user-facing."""


class ProxmoxClient:
    def __init__(self, cfg: dict):
        host = (cfg.get("PVE_HOST") or "").strip()
        if not host:
            raise PVEError(
                "PVE_HOST ist nicht konfiguriert. Bitte /proxmox-setup ausführen "
                f"(legt {CONFIG_PATH} an) oder PVE_HOST setzen."
            )
        if "://" in host:
            self.base = host.rstrip("/")
            if not self.base.endswith("/api2/json"):
                self.base += "/api2/json"
        else:
            name, _, port = host.partition(":")
            self.base = f"https://{name}:{port or '8006'}/api2/json"

        token_id = (cfg.get("PVE_TOKEN_ID") or "").strip()
        token_secret = (cfg.get("PVE_TOKEN_SECRET") or "").strip()
        if not token_id or not token_secret:
            raise PVEError(
                "PVE_TOKEN_ID / PVE_TOKEN_SECRET fehlen. Bitte /proxmox-setup ausführen."
            )
        self.auth_header = f"PVEAPIToken={token_id}={token_secret}"

        verify = (cfg.get("PVE_VERIFY_SSL") or "false").strip().lower()
        self.ctx = ssl.create_default_context()
        if verify not in ("1", "true", "yes", "on"):
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE

    def request(self, method: str, path: str, params: dict | None = None):
        url = self.base + path
        data = None
        if params:
            if method == "GET":
                url += "?" + urllib.parse.urlencode(params, doseq=True)
            else:
                data = urllib.parse.urlencode(params, doseq=True).encode()
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": self.auth_header,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=60) as resp:
                body = resp.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:2000]
            raise PVEError(f"Proxmox-API-Fehler {exc.code} bei {method} {path}: {detail}")
        except urllib.error.URLError as exc:
            raise PVEError(f"Verbindungsfehler zu {self.base}: {exc.reason}")
        except Exception as exc:  # noqa: BLE001 - surface anything as tool error
            raise PVEError(f"Verbindungsfehler zu {self.base}: {exc}")
        try:
            return json.loads(body).get("data")
        except (json.JSONDecodeError, AttributeError):
            return body

    # convenience wrappers -------------------------------------------------
    def get(self, path: str, params: dict | None = None):
        return self.request("GET", path, params)

    def post(self, path: str, params: dict | None = None):
        return self.request("POST", path, params)

    def put(self, path: str, params: dict | None = None):
        return self.request("PUT", path, params)

    def delete(self, path: str):
        return self.request("DELETE", path)


def client() -> ProxmoxClient:
    return ProxmoxClient(load_config())


def wait_task(pve: ProxmoxClient, node: str, upid: str, timeout: int = 300) -> dict:
    deadline = time.monotonic() + min(max(timeout, 5), 600)
    while time.monotonic() < deadline:
        status = pve.get(f"/nodes/{node}/tasks/{upid}/status")
        if status.get("status") != "running":
            return status
        time.sleep(2)
    raise PVEError(f"Timeout nach {timeout}s beim Warten auf Task {upid}.")


def guest_type(pve: ProxmoxClient, vmid: int) -> str | None:
    """Return 'qemu' or 'lxc' for a guest id."""
    for res in pve.get("/cluster/resources", {"type": "vm"}):
        if int(res.get("vmid", -1)) == int(vmid):
            return res.get("type")
    return None


# --------------------------------------------------------------------------
# Tool implementations (each returns a JSON-serialisable dict)
# --------------------------------------------------------------------------

def tool_status(_args: dict) -> dict:
    cfg = load_config()
    out = {
        "configured": False,
        "config_file": str(CONFIG_PATH),
        "config_file_exists": CONFIG_PATH.exists(),
        "host": cfg.get("PVE_HOST", ""),
        "token_id": cfg.get("PVE_TOKEN_ID", ""),
        "verify_ssl": cfg.get("PVE_VERIFY_SSL", "false"),
    }
    if not (cfg.get("PVE_HOST") and cfg.get("PVE_TOKEN_ID") and cfg.get("PVE_TOKEN_SECRET")):
        out["hint"] = "Konfiguration unvollständig — /proxmox-setup ausführen."
        return out
    pve = client()
    version = pve.get("/version")
    nodes = []
    for n in pve.get("/nodes"):
        entry = {"node": n.get("node"), "status": n.get("status")}
        try:
            details = pve.get(f"/nodes/{n['node']}/status")
            mem = details.get("memory", {})
            entry.update(
                {
                    "uptime_s": details.get("uptime"),
                    "cpu_usage": details.get("cpu", 0),
                    "loadavg": details.get("loadavg"),
                    "mem_used_gb": round(mem.get("used", 0) / 1e9, 1),
                    "mem_total_gb": round(mem.get("total", 0) / 1e9, 1),
                    "pve_version": details.get("pveversion"),
                }
            )
        except PVEError as exc:
            entry["detail_error"] = str(exc)
        nodes.append(entry)
    out.update({"configured": True, "connected": True, "api_version": version, "nodes": nodes})
    return out


def tool_list_nodes(_args: dict) -> dict:
    pve = client()
    nodes = []
    for n in pve.get("/nodes"):
        entry = dict(n)
        try:
            entry["status_details"] = pve.get(f"/nodes/{n['node']}/status")
        except PVEError:
            pass
        nodes.append(entry)
    return {"nodes": nodes}


def tool_list_storages(args: dict) -> dict:
    pve = client()
    node = args.get("node")
    if node:
        storages = pve.get(f"/nodes/{node}/storage")
    else:
        storages = pve.get("/storage")
    rows = [
        {
            "storage": s.get("storage"),
            "type": s.get("type"),
            "content": s.get("content"),
            "shared": bool(s.get("shared")),
            "enabled": bool(s.get("enabled", True)),
            "avail_gb": round(s.get("avail", 0) / 1e9, 1) if s.get("avail") else None,
            "total_gb": round(s.get("total", 0) / 1e9, 1) if s.get("total") else None,
        }
        for s in storages
    ]
    return {"storages": rows}


def tool_list_guests(_args: dict) -> dict:
    pve = client()
    guests = []
    for res in pve.get("/cluster/resources", {"type": "vm"}):
        guests.append(
            {
                "vmid": res.get("vmid"),
                "type": res.get("type"),
                "name": res.get("name"),
                "node": res.get("node"),
                "status": res.get("status"),
                "template": bool(res.get("template")),
                "cpus": res.get("cpus"),
                "maxmem_gb": round(res.get("maxmem", 0) / 1e9, 1),
                "disk_gb": round(res.get("maxdisk", 0) / 1e9, 1),
                "tags": res.get("tags"),
            }
        )
    guests.sort(key=lambda g: int(g["vmid"]))
    return {"guests": guests, "count": len(guests)}


def tool_list_templates(args: dict) -> dict:
    pve = client()
    node = args.get("node")
    nodes = [n["node"] for n in pve.get("/nodes")]
    if node:
        if node not in nodes:
            raise PVEError(f"Node '{node}' unbekannt. Verfügbar: {', '.join(nodes)}")
        nodes = [node]

    isos, lxc_templates = [], []
    for n in nodes:
        storages = [s["storage"] for s in pve.get(f"/nodes/{n}/storage", {"enabled": 1})]
        for st in storages:
            try:
                contents = pve.get(f"/nodes/{n}/storage/{st}/content")
            except PVEError:
                continue
            for item in contents:
                content = item.get("content")
                entry = {
                    "node": n,
                    "storage": st,
                    "volid": item.get("volid"),
                    "name": item.get("name"),
                    "size_gb": round(item.get("size", 0) / 1e9, 1),
                }
                if content == "vztmpl":
                    lxc_templates.append(entry)
                elif content == "iso":
                    isos.append(entry)
                elif content == "backup":
                    continue
    template_guests = [
        {
            "vmid": g["vmid"],
            "name": g.get("name"),
            "node": g.get("node"),
            "storage": g.get("storage"),
            "disk_gb": round(g.get("maxdisk", 0) / 1e9, 1),
        }
        for g in pve.get("/cluster/resources", {"type": "vm"})
        if g.get("template")
    ]
    return {
        "vm_template_guests": template_guests,
        "isos": isos,
        "lxc_templates": lxc_templates,
    }


def tool_list_appliances(args: dict) -> dict:
    pve = client()
    node = args.get("node")
    nodes = [n["node"] for n in pve.get("/nodes")]
    if node:
        nodes = [node]
    result = {}
    for n in nodes:
        try:
            infos = pve.get(f"/nodes/{n}/aplinfo")
        except PVEError as exc:
            result[n] = {"error": str(exc)}
            continue
        result[n] = [
            {
                "package": a.get("package"),
                "template": a.get("template"),
                "os": a.get("os"),
                "section": a.get("section"),
                "headline": a.get("headline"),
                "location": a.get("location"),  # 'proxmox' = bereits lokal, sonst Download nötig
            }
            for a in infos
        ]
    return {"appliances": result}


def tool_next_vmid(_args: dict) -> dict:
    pve = client()
    return {"vmid": pve.get("/cluster/nextid")}


def _pick_node(pve: ProxmoxClient, node: str | None) -> str:
    nodes = pve.get("/nodes")
    names = [n["node"] for n in nodes]
    if not names:
        raise PVEError("Keine Nodes im Cluster gefunden.")
    if node:
        if node not in names:
            raise PVEError(f"Node '{node}' unbekannt. Verfügbar: {', '.join(names)}")
        return node
    online = [n["node"] for n in nodes if n.get("status") == "online"]
    return online[0] if online else names[0]


def _ensure_vmid(pve: ProxmoxClient, vmid) -> int:
    if vmid in (None, "", 0):
        return int(pve.get("/cluster/nextid"))
    vmid = int(vmid)
    for res in pve.get("/cluster/resources", {"type": "vm"}):
        if int(res.get("vmid", -1)) == vmid:
            raise PVEError(f"VMID {vmid} ist bereits belegt ({res.get('name')}).")
    return vmid


def tool_create_vm(args: dict) -> dict:
    pve = client()
    name = args.get("name")
    if not name:
        raise PVEError("Parameter 'name' ist Pflicht.")
    template = args.get("template")
    iso = args.get("iso")
    if not template and not iso:
        raise PVEError("Entweder 'template' (VMID einer Vorlage) oder 'iso' angeben.")
    node = _pick_node(pve, args.get("node"))
    storage = args.get("storage") or "local-lvm"
    vmid = _ensure_vmid(pve, args.get("vmid"))
    cores = int(args.get("cores", 2))
    sockets = int(args.get("sockets", 1))
    memory = int(args.get("memory", 2048))
    net0 = args.get("net0") or "virtio,bridge=vmbr0"
    onboot = bool(args.get("onboot", False))
    start = bool(args.get("start", False))
    tags = args.get("tags")

    if template:
        # ---- Clone from template --------------------------------------
        clone_params = {"newid": vmid, "name": name, "full": 1}
        if args.get("pool"):
            clone_params["pool"] = args["pool"]
        upid = pve.post(f"/nodes/{node}/qemu/{int(template)}/clone", clone_params)
        result = wait_task(pve, node, upid)
        if result.get("exitstatus") != "OK":
            raise PVEError(f"Klonen von Template {template} fehlgeschlagen: {result}")

        config: dict = {
            "cores": cores,
            "sockets": sockets,
            "memory": memory,
            "net0": net0,
            "onboot": 1 if onboot else 0,
        }
        if bool(args.get("agent", True)):
            config["agent"] = 1
        if tags:
            config["tags"] = tags
        # Cloud-Init (nur sinnvoll bei Templates mit cloud-init-Support)
        ci_user = args.get("ciuser")
        if ci_user or args.get("cipassword") or args.get("sshkeys") or args.get("ipconfig0"):
            config.setdefault("ide2", f"{storage}:cloudinit")
            if ci_user:
                config["ciuser"] = ci_user
            if args.get("cipassword"):
                config["cipassword"] = args["cipassword"]
            if args.get("sshkeys"):
                config["sshkeys"] = args["sshkeys"]
            config["ipconfig0"] = args.get("ipconfig0") or "ip=dhcp"
        pve.put(f"/nodes/{node}/qemu/{vmid}/config", config)

        disk_size = args.get("disk_size")
        if disk_size:
            try:
                upid = pve.post(
                    f"/nodes/{node}/qemu/{vmid}/resize", {"disk": "scsi0", "size": disk_size}
                )
                result = wait_task(pve, node, upid, 120)
                if result.get("exitstatus") != "OK":
                    raise PVEError(str(result))
            except PVEError as exc:
                log(f"resize übersprungen: {exc}")

        method = f"Klon von Template {template}"
    else:
        # ---- Fresh install from ISO ------------------------------------
        disk_size = args.get("disk_size") or "32G"
        params = {
            "vmid": vmid,
            "name": name,
            "cores": cores,
            "sockets": sockets,
            "memory": memory,
            "net0": net0,
            "ostype": args.get("ostype") or "l26",
            "scsihw": args.get("scsihw") or "virtio-scsi-single",
            "scsi0": f"{storage}:{disk_size}",
            "ide2": iso,
            "boot": "order=scsi0",
            "onboot": 1 if onboot else 0,
            "agent": 1 if bool(args.get("agent", True)) else 0,
        }
        if tags:
            params["tags"] = tags
        if args.get("pool"):
            params["pool"] = args["pool"]
        upid = pve.post(f"/nodes/{node}/qemu", params)
        result = wait_task(pve, node, upid)
        if result.get("exitstatus") != "OK":
            raise PVEError(f"VM-Erstellung fehlgeschlagen: {result}")
        method = f"Neuinstallation von ISO {iso}"

    if start:
        pve.post(f"/nodes/{node}/qemu/{vmid}/status/start")

    return {
        "vmid": vmid,
        "node": node,
        "name": name,
        "method": method,
        "started": start,
        "next_steps": (
            "Status mit pve_guest_status prüfen; IP mit pve_get_ips holen "
            "(QEMU-Guest-Agent erforderlich, sonst DHCP-Lease des Routers prüfen)."
        ),
    }


def tool_create_container(args: dict) -> dict:
    pve = client()
    hostname = args.get("hostname")
    ostemplate = args.get("ostemplate")
    if not hostname or not ostemplate:
        raise PVEError("Parameter 'hostname' und 'ostemplate' sind Pflicht.")
    node = _pick_node(pve, args.get("node"))
    storage = args.get("storage") or "local-lvm"
    vmid = _ensure_vmid(pve, args.get("vmid"))
    cores = int(args.get("cores", 2))
    memory = int(args.get("memory", 1024))
    swap = int(args.get("swap", 512))
    rootfs_size = str(args.get("rootfs_size") or "8")
    net0 = args.get("net0") or "name=eth0,bridge=vmbr0,ip=dhcp,firewall=1"
    start = bool(args.get("start", False))

    params = {
        "vmid": vmid,
        "hostname": hostname,
        "ostemplate": ostemplate,
        "cores": cores,
        "memory": memory,
        "swap": swap,
        "rootfs": f"{storage}:{rootfs_size}",
        "net0": net0,
        "unprivileged": 1 if bool(args.get("unprivileged", True)) else 0,
        "onboot": 1 if bool(args.get("onboot", False)) else 0,
        "start": 1 if start else 0,
    }
    if bool(args.get("nesting", True)):
        params["features"] = "nesting=1"
    if args.get("password"):
        params["password"] = args["password"]
    if args.get("ssh_public_keys"):
        params["ssh-public-keys"] = args["ssh_public_keys"]
    if args.get("tags"):
        params["tags"] = args["tags"]
    if args.get("pool"):
        params["pool"] = args["pool"]

    upid = pve.post(f"/nodes/{node}/lxc", params)
    result = wait_task(pve, node, upid, 600)
    if result.get("exitstatus") != "OK":
        raise PVEError(f"LXC-Erstellung fehlgeschlagen: {result}")

    return {
        "vmid": vmid,
        "node": node,
        "hostname": hostname,
        "ostemplate": ostemplate,
        "started": start,
        "next_steps": (
            "Status mit pve_guest_status prüfen; IP mit pve_get_ips holen. "
            "Root-Passwort setzen via pve_set_password falls keines angegeben wurde."
        ),
    }


def tool_guest_status(args: dict) -> dict:
    pve = client()
    vmid = int(args["vmid"])
    gtype = args.get("type") or guest_type(pve, vmid)
    if not gtype:
        raise PVEError(f"Guest {vmid} nicht gefunden.")
    node = args.get("node")
    if not node:
        for res in pve.get("/cluster/resources", {"type": "vm"}):
            if int(res.get("vmid", -1)) == vmid:
                node = res["node"]
                break
    if gtype == "qemu":
        status = pve.get(f"/nodes/{node}/qemu/{vmid}/status")
        config = pve.get(f"/nodes/{node}/qemu/{vmid}/config")
    else:
        status = pve.get(f"/nodes/{node}/lxc/{vmid}/status")
        config = pve.get(f"/nodes/{node}/lxc/{vmid}/config")
    return {"vmid": vmid, "node": node, "type": gtype, "status": status, "config": config}


def tool_start_guest(args: dict) -> dict:
    pve = client()
    vmid = int(args["vmid"])
    gtype = args.get("type") or guest_type(pve, vmid)
    if not gtype:
        raise PVEError(f"Guest {vmid} nicht gefunden.")
    node = args.get("node")
    if not node:
        for res in pve.get("/cluster/resources", {"type": "vm"}):
            if int(res.get("vmid", -1)) == vmid:
                node = res["node"]
                break
    upid = pve.post(f"/nodes/{node}/{gtype}/{vmid}/status/start")
    result = wait_task(pve, node, upid, 120)
    return {"vmid": vmid, "node": node, "type": gtype, "task": result}


def tool_stop_guest(args: dict) -> dict:
    pve = client()
    vmid = int(args["vmid"])
    force = bool(args.get("force", False))
    gtype = args.get("type") or guest_type(pve, vmid)
    if not gtype:
        raise PVEError(f"Guest {vmid} nicht gefunden.")
    node = args.get("node")
    if not node:
        for res in pve.get("/cluster/resources", {"type": "vm"}):
            if int(res.get("vmid", -1)) == vmid:
                node = res["node"]
                break
    action = "stop" if force else "shutdown"
    params = {} if force else {"timeout": int(args.get("timeout", 60))}
    upid = pve.post(f"/nodes/{node}/{gtype}/{vmid}/status/{action}", params or None)
    result = wait_task(pve, node, upid, int(args.get("timeout", 60)) + 60)
    return {"vmid": vmid, "node": node, "type": gtype, "action": action, "task": result}


def tool_delete_guest(args: dict) -> dict:
    vmid = int(args["vmid"])
    if args.get("confirm") is not True:
        raise PVEError(
            f"Löschen von Guest {vmid} erfordert confirm=true. "
            "Bitte zuerst stoppen und bewusst bestätigen."
        )
    pve = client()
    gtype = args.get("type") or guest_type(pve, vmid)
    if not gtype:
        raise PVEError(f"Guest {vmid} nicht gefunden.")
    node = args.get("node")
    if not node:
        for res in pve.get("/cluster/resources", {"type": "vm"}):
            if int(res.get("vmid", -1)) == vmid:
                node = res["node"]
                break
    for res in pve.get("/cluster/resources", {"type": "vm"}):
        if int(res.get("vmid", -1)) == vmid and res.get("status") == "running":
            raise PVEError(f"Guest {vmid} läuft noch — zuerst stoppen (pve_stop_guest).")
    upid = pve.delete(f"/nodes/{node}/{gtype}/{vmid}")
    result = wait_task(pve, node, upid, 120)
    return {"vmid": vmid, "node": node, "type": gtype, "deleted": True, "task": result}


def tool_task_status(args: dict) -> dict:
    pve = client()
    return {"status": pve.get(f"/nodes/{args['node']}/tasks/{args['upid']}/status")}


def tool_wait_for_task(args: dict) -> dict:
    pve = client()
    return {
        "status": wait_task(pve, args["node"], args["upid"], int(args.get("timeout", 300)))
    }


def tool_get_ips(args: dict) -> dict:
    pve = client()
    vmid = int(args["vmid"])
    gtype = args.get("type") or guest_type(pve, vmid)
    if not gtype:
        raise PVEError(f"Guest {vmid} nicht gefunden.")
    node = args.get("node")
    if not node:
        for res in pve.get("/cluster/resources", {"type": "vm"}):
            if int(res.get("vmid", -1)) == vmid:
                node = res["node"]
                break
    out = {"vmid": vmid, "node": node, "type": gtype, "ips": [], "source": None}
    if gtype == "qemu":
        try:
            ifaces = pve.get(f"/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces")
            result = ifaces.get("result", ifaces) if isinstance(ifaces, dict) else ifaces
            for iface in result or []:
                addrs = [
                    a["ip-address"]
                    for a in iface.get("ip-addresses", [])
                    if not a["ip-address"].startswith(("127.", "fe80"))
                ]
                if addrs:
                    out["ips"].append({"interface": iface.get("name"), "addresses": addrs})
            out["source"] = "qemu-guest-agent"
            return out
        except PVEError as exc:
            out["agent_error"] = str(exc)
    # Fallback: statische Konfiguration auswerten
    config = pve.get(f"/nodes/{node}/{gtype}/{vmid}/config")
    for key, value in config.items():
        if key.startswith("net") and "ip=" in str(value):
            for part in str(value).split(","):
                if part.startswith("ip="):
                    out["ips"].append({"interface": key, "addresses": [part[3:]]})
    out["source"] = "config" if out["ips"] else None
    if not out["ips"]:
        out["hint"] = (
            "Keine IP ermittelbar. Bei DHCP: Lease des Routers prüfen. "
            "Bei VMs muss der QEMU-Guest-Agent installiert und aktiv sein (agent=1)."
        )
    return out


def tool_set_password(args: dict) -> dict:
    pve = client()
    vmid = int(args["vmid"])
    gtype = args.get("type") or guest_type(pve, vmid)
    if gtype != "lxc":
        raise PVEError("pve_set_password funktioniert nur für LXC-Container.")
    node = args.get("node")
    if not node:
        for res in pve.get("/cluster/resources", {"type": "vm"}):
            if int(res.get("vmid", -1)) == vmid:
                node = res["node"]
                break
    pve.put(f"/nodes/{node}/lxc/{vmid}/config", {"password": args["password"]})
    return {"vmid": vmid, "node": node, "password_set": True}


TOOLS = {
    "pve_status": (
        "Verbindungs- und Konfigurationscheck: Proxmox-Version, Nodes, Ressourcennutzung. "
        "Immer zuerst aufrufen, um die Verbindung zu verifizieren.",
        {"type": "object", "properties": {}},
        tool_status,
    ),
    "pve_list_nodes": (
        "Listet alle Proxmox-Nodes mit Status, CPU, RAM und Uptime.",
        {"type": "object", "properties": {}},
        tool_list_nodes,
    ),
    "pve_list_storages": (
        "Listet Storages (local, local-lvm, NFS, ...). Optional pro Node, sonst clusterweit.",
        {
            "type": "object",
            "properties": {"node": {"type": "string", "description": "Optional: nur Storages dieser Node"}},
        },
        tool_list_storages,
    ),
    "pve_list_guests": (
        "Listet alle VMs und LXC-Container im Cluster (vmid, Name, Status, Node, Ressourcen).",
        {"type": "object", "properties": {}},
        tool_list_guests,
    ),
    "pve_list_templates": (
        "Listet verfügbare VM-Templates, ISOs und LXC-Templates auf einer Node "
        "(inkl. Template-Guests mit template-Flag).",
        {
            "type": "object",
            "properties": {"node": {"type": "string", "description": "Optional: nur diese Node"}},
        },
        tool_list_templates,
    ),
    "pve_list_appliances": (
        "Listet herunterladbare LXC-Appliance-Templates (pveam) einer Node. "
        "Für LXC-Erstellung per 'ostemplate' nutzbar.",
        {
            "type": "object",
            "properties": {"node": {"type": "string", "description": "Optional: nur diese Node"}},
        },
        tool_list_appliances,
    ),
    "pve_next_vmid": (
        "Gibt die nächste freie VMID zurück.",
        {"type": "object", "properties": {}},
        tool_next_vmid,
    ),
    "pve_create_vm": (
        "Erstellt eine KVM/VM — entweder als Klon eines Templates (mit optional Cloud-Init: "
        "ciuser, cipassword, sshkeys, ipconfig0) oder als Neuinstallation von einer ISO. "
        "Wartet automatisch auf Abschluss des Proxmox-Tasks.",
        {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "description": "Hostname/Name der VM"},
                "node": {"type": "string", "description": "Ziel-Node (Default: erste Online-Node)"},
                "vmid": {"type": "integer", "description": "Optional; Default: nächste freie VMID"},
                "template": {"type": "integer", "description": "VMID eines Templates zum Klonen"},
                "iso": {"type": "string", "description": "ISO-volid, z.B. 'local:iso/debian-12.iso'"},
                "storage": {"type": "string", "description": "Ziel-Storage für Disks (Default local-lvm)"},
                "cores": {"type": "integer", "default": 2},
                "sockets": {"type": "integer", "default": 1},
                "memory": {"type": "integer", "description": "RAM in MiB", "default": 2048},
                "disk_size": {"type": "string", "description": "z.B. '32G' (ISO: neue Disk; Template: resize scsi0)"},
                "net0": {"type": "string", "description": "Default 'virtio,bridge=vmbr0'"},
                "ostype": {"type": "string", "description": "Default l26 (Linux 6.x)"},
                "scsihw": {"type": "string", "description": "Default virtio-scsi-single"},
                "agent": {"type": "boolean", "description": "QEMU-Guest-Agent aktivieren (Default true)"},
                "onboot": {"type": "boolean", "description": "Beim Node-Boot starten (Default false)"},
                "tags": {"type": "string", "description": "Semikolon-getrennte Tags"},
                "pool": {"type": "string", "description": "Optional: Resource-Pool"},
                "ciuser": {"type": "string", "description": "Cloud-Init-User"},
                "cipassword": {"type": "string", "description": "Cloud-Init-Passwort"},
                "sshkeys": {"type": "string", "description": "Cloud-Init SSH-Public-Keys (eine oder mehrere Zeilen)"},
                "ipconfig0": {"type": "string", "description": "Default 'ip=dhcp'; z.B. 'ip=192.168.1.50/24,gw=192.168.1.1'"},
                "start": {"type": "boolean", "description": "VM nach Erstellung direkt starten (Default false)"},
            },
        },
        tool_create_vm,
    ),
    "pve_create_container": (
        "Erstellt einen LXC-Container. 'ostemplate' kann ein Appliance-Name (z.B. 'debian-12-standard', "
        "wird automatisch heruntergeladen) oder ein lokales Template sein (z.B. 'local:vztmpl/...'). "
        "Wartet automatisch auf Abschluss des Proxmox-Tasks.",
        {
            "type": "object",
            "required": ["hostname", "ostemplate"],
            "properties": {
                "hostname": {"type": "string"},
                "ostemplate": {"type": "string", "description": "Appliance-Name oder volid"},
                "node": {"type": "string", "description": "Ziel-Node (Default: erste Online-Node)"},
                "vmid": {"type": "integer", "description": "Optional; Default: nächste freie VMID"},
                "storage": {"type": "string", "description": "Ziel-Storage für rootfs (Default local-lvm)"},
                "cores": {"type": "integer", "default": 2},
                "memory": {"type": "integer", "description": "RAM in MiB", "default": 1024},
                "swap": {"type": "integer", "description": "Swap in MiB", "default": 512},
                "rootfs_size": {"type": "string", "description": "Root-Disk-Größe in GB (Default 8)"},
                "net0": {"type": "string", "description": "Default 'name=eth0,bridge=vmbr0,ip=dhcp,firewall=1'"},
                "unprivileged": {"type": "boolean", "description": "Default true"},
                "nesting": {"type": "boolean", "description": "nesting=1 erlauben, z.B. für Docker im LXC (Default true)"},
                "password": {"type": "string", "description": "Root-Passwort"},
                "ssh_public_keys": {"type": "string", "description": "SSH-Public-Keys für root"},
                "onboot": {"type": "boolean", "description": "Beim Node-Boot starten (Default false)"},
                "tags": {"type": "string", "description": "Semikolon-getrennte Tags"},
                "pool": {"type": "string", "description": "Optional: Resource-Pool"},
                "start": {"type": "boolean", "description": "Container nach Erstellung direkt starten (Default false)"},
            },
        },
        tool_create_container,
    ),
    "pve_guest_status": (
        "Status und Konfiguration einer VM/eines Containers (vmid).",
        {
            "type": "object",
            "required": ["vmid"],
            "properties": {
                "vmid": {"type": "integer"},
                "node": {"type": "string"},
                "type": {"type": "string", "enum": ["qemu", "lxc"], "description": "Optional; sonst Auto-Detect"},
            },
        },
        tool_guest_status,
    ),
    "pve_start_guest": (
        "Startet eine VM oder einen Container.",
        {
            "type": "object",
            "required": ["vmid"],
            "properties": {
                "vmid": {"type": "integer"},
                "node": {"type": "string"},
                "type": {"type": "string", "enum": ["qemu", "lxc"]},
            },
        },
        tool_start_guest,
    ),
    "pve_stop_guest": (
        "Fährt eine VM/einen Container sauber herunter (ACPI-Shutdown) oder erzwingt das Stoppen mit force=true.",
        {
            "type": "object",
            "required": ["vmid"],
            "properties": {
                "vmid": {"type": "integer"},
                "node": {"type": "string"},
                "type": {"type": "string", "enum": ["qemu", "lxc"]},
                "force": {"type": "boolean", "description": "Default false (sauberer Shutdown)"},
                "timeout": {"type": "integer", "description": "Shutdown-Timeout in Sekunden (Default 60)"},
            },
        },
        tool_stop_guest,
    ),
    "pve_delete_guest": (
        "LÖSCHT eine VM/einen Container unwiderruflich. Guest muss gestoppt sein; "
        "erfordert zwingend confirm=true.",
        {
            "type": "object",
            "required": ["vmid", "confirm"],
            "properties": {
                "vmid": {"type": "integer"},
                "confirm": {"type": "boolean", "description": "Muss true sein"},
                "node": {"type": "string"},
                "type": {"type": "string", "enum": ["qemu", "lxc"]},
            },
        },
        tool_delete_guest,
    ),
    "pve_task_status": (
        "Status eines Proxmox-Tasks (UPID) abfragen.",
        {
            "type": "object",
            "required": ["node", "upid"],
            "properties": {"node": {"type": "string"}, "upid": {"type": "string"}},
        },
        tool_task_status,
    ),
    "pve_wait_for_task": (
        "Blockiert, bis ein Proxmox-Task (UPID) abgeschlossen ist (max. timeout Sekunden).",
        {
            "type": "object",
            "required": ["node", "upid"],
            "properties": {
                "node": {"type": "string"},
                "upid": {"type": "string"},
                "timeout": {"type": "integer", "default": 300},
            },
        },
        tool_wait_for_task,
    ),
    "pve_get_ips": (
        "Ermittelt die IP-Adresse(n) eines laufenden Guests — bevorzugt über den QEMU-Guest-Agent, "
        "Fallback über statische Netzkonfiguration.",
        {
            "type": "object",
            "required": ["vmid"],
            "properties": {
                "vmid": {"type": "integer"},
                "node": {"type": "string"},
                "type": {"type": "string", "enum": ["qemu", "lxc"]},
            },
        },
        tool_get_ips,
    ),
    "pve_set_password": (
        "Setzt das Root-Passwort eines LXC-Containers (nachträglich über die Konfiguration).",
        {
            "type": "object",
            "required": ["vmid", "password"],
            "properties": {
                "vmid": {"type": "integer"},
                "password": {"type": "string"},
                "node": {"type": "string"},
            },
        },
        tool_set_password,
    ),
}


# --------------------------------------------------------------------------
# MCP stdio transport (newline-delimited JSON-RPC 2.0)
# --------------------------------------------------------------------------

def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def reply(req_id, result: dict) -> None:
    send({"jsonrpc": "2.0", "id": req_id, "result": result})


def reply_error(req_id, code: int, message: str) -> None:
    send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def handle_request(msg: dict) -> None:
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        reply(
            req_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    elif method == "tools/list":
        tools = [
            {"name": name, "description": desc, "inputSchema": schema}
            for name, (desc, schema, _fn) in TOOLS.items()
        ]
        reply(req_id, {"tools": tools})
    elif method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        if name not in TOOLS:
            reply(req_id, {
                "content": [{"type": "text", "text": f"Unbekanntes Tool: {name}"}],
                "isError": True,
            })
            return
        _desc, _schema, fn = TOOLS[name]
        try:
            result = fn(arguments)
            reply(
                req_id,
                {
                    "content": [
                        {"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}
                    ],
                    "isError": False,
                },
            )
        except PVEError as exc:
            reply(
                req_id,
                {"content": [{"type": "text", "text": str(exc)}], "isError": True},
            )
        except Exception as exc:  # noqa: BLE001
            log(f"unexpected error in {name}: {exc!r}")
            reply(
                req_id,
                {
                    "content": [{"type": "text", "text": f"Interner Fehler: {exc}"}],
                    "isError": True,
                },
            )
    elif method == "ping":
        reply(req_id, {})
    elif req_id is not None:
        reply_error(req_id, -32601, f"Method not found: {method}")
    # Notifications (initialized, cancelled, ...) brauchen keine Antwort.


def main() -> None:
    log(f"{SERVER_NAME} {SERVER_VERSION} gestartet (config: {CONFIG_PATH})")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            log(f"ungültiges JSON ignoriert: {exc}")
            continue
        try:
            handle_request(msg)
        except Exception as exc:  # noqa: BLE001
            log(f"handler error: {exc!r}")
            if msg.get("id") is not None:
                reply_error(msg.get("id"), -32603, f"Internal error: {exc}")


if __name__ == "__main__":
    main()
