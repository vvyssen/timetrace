"""Read-only access to the dashboard from a phone on the same network. Off by default.

When on, the dashboard also listens on the local network, and a request from another device must
carry the read-only token (in the link as ?t=…, then as a cookie). Writes — tagging, settings —
stay limited to this Mac.
"""
import ipaddress
import os
import re
import secrets
import subprocess

from . import settings

# addresses that are not "the Wi-Fi": proxy TUN ranges (Surge, Clash) and Tailscale's CGNAT range
_SKIP = [ipaddress.ip_network("198.18.0.0/15"), ipaddress.ip_network("100.64.0.0/10")]


def _out(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return ""


def hostname():
    """Bonjour name, e.g. Yans-MacBook-Air.local — stays the same when the router hands out a new IP."""
    name = _out(["scutil", "--get", "LocalHostName"]).strip()
    return f"{name}.local" if name else None


def lan_ips():
    ips, iface = [], ""
    for line in _out(["ifconfig"]).splitlines():
        if line and not line[0].isspace():
            iface = line.split(":", 1)[0]
            continue
        m = re.match(r"\s+inet (\d+\.\d+\.\d+\.\d+)", line)
        if not m or not iface.startswith(("en", "bridge")):
            continue
        ip = ipaddress.ip_address(m.group(1))
        if ip.is_private and not ip.is_loopback and not ip.is_link_local and not any(ip in n for n in _SKIP):
            ips.append(str(ip))
    return ips


def firewall_on():
    return "enabled" in _out(["/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate"]).lower()


def enabled():
    s = settings.load()
    return bool(s.get("lan_enabled") and s.get("lan_token"))


def check(token):
    s = settings.load()
    good = s.get("lan_token") or ""
    return bool(s.get("lan_enabled") and good and token and secrets.compare_digest(str(token), good))


def enable():
    tok = settings.load().get("lan_token") or secrets.token_urlsafe(16)
    settings.save(lan_enabled=True, lan_token=tok)


def disable():
    settings.save(lan_enabled=False)


def rotate():
    """New token: every link sent so far stops working."""
    settings.save(lan_token=secrets.token_urlsafe(16))


def urls(date=None):
    """Links for a phone, the stable .local one first. `date` (YYYY-MM-DD) opens that day's overview."""
    if not enabled():
        return []
    s = settings.load()
    frag = f"#range=day&date={date}" if date else ""
    port = os.environ.get("TIMETRACE_PORT") or s["port"]
    hosts = [h for h in [hostname()] + lan_ips() if h]
    return [f"http://{h}:{port}/?t={s['lan_token']}{frag}" for h in hosts]


def status():
    return {"enabled": enabled(), "urls": urls(), "hostname": hostname(), "ips": lan_ips(), "firewall": firewall_on()}
