"""Adds `art` to a finished Screen. Builders stay free of file lookups.

What gets art:
- every Ref ({kind,id}) whose kind has art
- a list item or card: its own `art`, else the art of its ref
- the `_art` hook: builders may put {"_art": (artKind, id)} on a card, list item, heading or image block
  (the duplicant lane uses it for portraits). It is always removed here; an image block with no art is dropped.
- an entry Screen: a heading with the entry's art is put first (decorate(..., entry=(kind, id)))
Nothing is added when there is no art, so a Screen without the mod is exactly the v1 Screen.
"""


def _resolve(store, node):
    hook = node.pop("_art", None)
    if hook:
        return store.url_for(hook[0], hook[1])
    return None


def _walk(store, node):
    if isinstance(node, list):
        out = []
        for v in node:
            r = _walk(store, v)
            if r is not _DROP:
                out.append(r)
        node[:] = out
        return node
    if not isinstance(node, dict):
        return node
    t = node.get("type")
    hooked = _resolve(store, node) if "_art" in node else None
    for k in list(node):
        v = node[k]
        if k in ("actions", "onOpen"):
            continue        # action args are posted back as they are: no art inside them
        if isinstance(v, (dict, list)):
            _walk(store, v)
    r = node.get("ref")
    if set(node) <= {"kind", "id", "art"} and "kind" in node and "id" in node and isinstance(node["kind"], str):
        if "art" not in node:
            u = store.url_for_ref(node["kind"], node["id"])
            if u:
                node["art"] = u
        return node
    if hooked:
        node["art"] = hooked
    elif "art" not in node and isinstance(r, dict) and ("title" in node) and t is None:
        # list item or card: use the ref's art
        if r.get("art"):
            node["art"] = r["art"]
    if t == "image" and "art" not in node:
        return _DROP
    return node


_DROP = object()


def decorate(screen, store, entry=None):
    """Mutates and returns `screen`. `store` None or empty = no change except the hook key removal."""
    if not isinstance(screen, dict):
        return screen
    if store is None:
        class _None:
            def url_for(self, *a):
                return None
            url_for_ref = url_for
        store = _None()
    blocks = screen.get("blocks")
    if isinstance(blocks, list):
        _walk(store, blocks)
    if isinstance(screen.get("nav"), dict):
        _walk(store, screen["nav"])
    if entry:
        u = store.url_for_ref(entry[0], entry[1])
        if u:
            blocks.insert(0, {"type": "heading", "text": screen.get("title") or entry[1], "level": 1, "art": u})
    return screen
