"""Codex entries (lore + guide text) from StreamingAssets/codex/**/*.yaml."""
import os

from . import yamlmini
from .pot import strip_markup, markup_links

TEXT_STYLES = ("Title", "Subtitle", "Body", "BodyWhite", "Warning")


def _list(v):
    return [x for x in (v or []) if isinstance(x, str)]


def _walk(node, out):
    """Collect (kind, value) in document order from CodexText / label blocks."""
    if isinstance(node, list):
        for x in node:
            _walk(x, out)
    elif isinstance(node, dict):
        key = node.get("stringKey")
        if isinstance(key, str) and key:
            out.append((node.get("style") or "Body", key))
        for k, v in node.items():
            if isinstance(v, (list, dict)):
                _walk(v, out)


def load_codex(assets_dir, strings):
    """Returns (entries, unresolved_keys). Entries are kind `codex`."""
    root = os.path.join(assets_dir, "codex")
    entries = []
    unresolved = []
    seen = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            if not fn.endswith(".yaml"):
                continue
            path = os.path.join(dirpath, fn)
            doc = yamlmini.load(path)
            if not isinstance(doc, dict) or not doc.get("id"):
                continue  # fully commented-out files
            rel = os.path.relpath(dirpath, root)
            category = "" if rel == "." else rel.split(os.sep)[0]
            paras = []
            links = []
            raw = []
            _walk(doc.get("contentContainers"), raw)
            for style, key in raw:
                text = strings.get(key)
                if text is None:
                    if key.startswith("STRINGS."):
                        unresolved.append(key)
                    continue
                for lid in markup_links(text):
                    if lid not in links:
                        links.append(lid)
                paras.append({"style": style, "text": strip_markup(text)})
            title_key = doc.get("title") or ""
            title = strip_markup(strings.get(title_key, ""))
            if not title:
                if title_key.startswith("STRINGS."):
                    unresolved.append(title_key)
                title = str(doc["id"])
            e = {
                "id": str(doc["id"]),
                "name": title,
                "dlc": _list(doc.get("requiredDlcIds")),
                "category": category,
                "paragraphs": paras,
                "links": links,
                "source": "yaml",
            }
            if doc.get("requiredAtLeastOneDlcIds"):
                e["dlcAny"] = _list(doc["requiredAtLeastOneDlcIds"])
            if doc.get("forbiddenDlcIds"):
                e["dlcForbidden"] = _list(doc["forbiddenDlcIds"])
            if doc.get("parentId") or doc.get("parentEntryID"):
                e["parent"] = str(doc.get("parentId") or doc.get("parentEntryID"))
            if doc.get("disabled") is True:
                e["disabled"] = True
            made = [m.get("tag") for m in (doc.get("contentMadeAndUsed") or []) if isinstance(m, dict) and m.get("tag")]
            if made:
                e["tags"] = made
            prev = seen.get(e["id"])
            if prev is not None:  # two files can share an id (sub-entry + dynamic entry): merge them
                prev["paragraphs"].extend(e["paragraphs"])
                prev["links"] = prev["links"] + [x for x in e["links"] if x not in prev["links"]]
                prev["dlc"] = prev["dlc"] + [x for x in e["dlc"] if x not in prev["dlc"]]
                continue
            seen[e["id"]] = e
            entries.append(e)
    return entries, sorted(set(unresolved))
