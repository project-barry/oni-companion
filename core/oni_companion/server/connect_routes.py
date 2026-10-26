"""The /connect/* endpoints (v1.4). All but `claim` are loopback only: from the network listener they answer
403 local_only, so a paired device can never list, add or remove devices or turn the switch off."""
import re

from .errors import ApiError

DEVICE_ID = re.compile(r"^d-[0-9a-f]{12}$")


def _switch_value(body):
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
        raise ApiError("bad_request", "Body must be {\"enabled\": true or false}.")
    return body["enabled"]


def handle(method, parts, body, ctx, network):
    cm = ctx.connect
    sub = parts[1:]
    if sub == ["claim"] and method == "POST":
        if network is None:
            raise ApiError("not_found", "Not found.")
        if not isinstance(body, dict) or not isinstance(body.get("code"), str) or not isinstance(body.get("label"), str):
            raise ApiError("bad_request", "Body must hold code and label.")
        label = "".join(ch for ch in body["label"] if ch.isprintable()).strip()
        if not 1 <= len(label) <= 40 or not 1 <= len(body["code"]) <= 20:
            raise ApiError("bad_request", "Bad code or label.")
        platform = body.get("platform", "other")
        if platform not in ("android", "ios", "web", "other"):
            raise ApiError("bad_request", "Bad platform.")
        return cm.claim(network.source, network.kind, body["code"], label, platform)
    if network is not None:
        raise ApiError("local_only", "Only the game device can do this.")
    if method == "GET" and not sub:
        cm.ensure_identity()
        cm.refresh_addresses()
        return cm.state()
    if method == "GET" and sub == ["devices"]:
        return cm.list_devices()
    if method == "POST" and sub == ["switch"]:
        cm.set_enabled(_switch_value(body))
        return cm.state()
    if method == "POST" and sub == ["plain-http"]:
        cm.set_plain_http(_switch_value(body))
        return cm.state()
    if method == "POST" and sub == ["code"]:
        return cm.new_code()
    if method == "POST" and sub == ["reset-identity"]:
        return cm.reset_identity()
    if method == "DELETE" and len(sub) == 2 and sub[0] == "devices":
        if not DEVICE_ID.match(sub[1]):
            raise ApiError("not_found", "Device not found.")
        return cm.remove_device(sub[1])
    raise ApiError("not_found", "Not found.")
