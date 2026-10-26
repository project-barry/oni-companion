"""The addresses other devices can use: LAN first, then Tailscale. IPv4 only.

Read from the system's `ip` (Linux) or `ifconfig` (macOS) command, with the default-route trick as a fallback.
Interfaces of containers and virtual machines are skipped. Nothing here opens a network connection.
"""
import ipaddress
import re
import shutil
import socket
import subprocess

SKIP_PREFIXES = ("lo", "docker", "br-", "veth", "virbr", "vmnet", "vboxnet", "utun", "awdl", "llw", "bridge", "gif", "stf", "anpi", "ap")
TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


def classify(addr, ifname=""):
    """'lan', 'tailscale' or None (loopback, public, link-local ...)."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return None
    if ip.version != 4 or ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_link_local:
        return None
    if ip in TAILSCALE_NET:
        return "tailscale"
    if ip.is_private:
        return "tailscale" if ifname.startswith("tailscale") else "lan"
    return None


def _skip(ifname):
    return ifname.startswith(SKIP_PREFIXES) and not ifname.startswith("tailscale")


def _from_ip_cmd(text):
    out = []
    for line in text.splitlines():           # "2: wlan0    inet 192.168.1.73/24 brd ..."
        m = re.match(r"\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/", line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def _from_ifconfig(text):
    out, cur = [], ""
    for line in text.splitlines():
        m = re.match(r"^(\S+?):\s+flags=", line)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r"^\s+inet\s+(\d+\.\d+\.\d+\.\d+)\s", line)
        if m and cur:
            out.append((cur, m.group(1)))
    return out


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _default_route_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))           # UDP connect sends nothing; it only picks the outgoing address
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def local_addresses(run=_run):
    """[{"address", "kind"}], LAN first then Tailscale, no duplicates."""
    pairs = []
    if shutil.which("ip"):
        pairs = _from_ip_cmd(run(["ip", "-o", "-4", "addr", "show", "scope", "global"]))
    elif shutil.which("ifconfig"):
        pairs = _from_ifconfig(run(["ifconfig"]))
    seen, lan, ts = set(), [], []
    for ifname, addr in pairs:
        kind = classify(addr, ifname)
        if addr in seen or (_skip(ifname) and kind != "tailscale"):
            continue
        if kind:
            seen.add(addr)
            (ts if kind == "tailscale" else lan).append({"address": addr, "kind": kind})
    if not lan and not ts:
        a = _default_route_address()
        if a and classify(a):
            (ts if classify(a) == "tailscale" else lan).append({"address": a, "kind": classify(a)})
    return lan + ts


def allowed_destination(addr):
    """True for an address a client may reach us on (private or Tailscale); false for loopback and public."""
    return classify(addr, "") is not None
