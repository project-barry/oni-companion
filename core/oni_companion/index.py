"""Search over the merged dataset, plus the "produced by / used by" graph.

Search is event-free and in-memory: a prefix index over name/id/alias tokens, a substring
scan over names, and (only when needed) a bounded edit-distance pass for typos.
"""
import bisect
import re
import unicodedata

from .gamedata import KIND_LABELS

KIND_ORDER = ["building", "element", "critter", "plant", "geyser", "food", "medicine", "recipe",
              "tech", "trait", "skill", "room", "codex"]
_KIND_RANK = {k: i for i, k in enumerate(KIND_ORDER)}

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON = re.compile(r"[^a-z0-9]+")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = s.encode("ascii", "ignore").decode("ascii").lower()
    return _NON.sub(" ", s).strip()


def id_words(ident):
    """'GasGrass_Seed' -> 'gas grass seed' (also handles the all-caps ids from the .pot)."""
    return norm(_CAMEL.sub(" ", ident.replace("_", " ")))


def _lev_within(a, b, k):
    """True if the optimal-string-alignment distance (edits + adjacent swaps) of a and b is <= k."""
    if abs(len(a) - len(b)) > k:
        return False
    prev2 = None
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if prev2 is not None and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                v = min(v, prev2[j - 2] + 1)
            cur.append(v)
            if v < best:
                best = v
        if best > k:
            return False
        prev2, prev = prev, cur
    return prev[-1] <= k


def _fuzz_k(tok):
    return 0 if len(tok) < 4 else (1 if len(tok) < 7 else 2)


class Index:
    def __init__(self, dataset):
        self.ds = dataset
        self.kinds = dataset.kinds
        self._upper = {}     # (kind, ID.upper()) -> id
        self._docs = []      # per doc: (kind, id, name_norm, name_tokens, id_norm, id_tokens, alias_tokens)
        self._post = {}      # token -> list of doc idx
        for kind, entries in self.kinds.items():
            for ident, e in entries.items():
                self._upper[(kind, ident.upper())] = ident
                if e.get("hidden"):          # still resolves by id, but never listed or found by search
                    continue
                name = e.get("name") or ident
                aliases = list(e.get("aliases") or []) + list(e.get("tags") or [])
                if kind == "codex":
                    aliases.append(ident)
                doc = (kind, ident, norm(name), norm(name).split(), norm(ident), id_words(ident).split(),
                       [t for a in aliases for t in norm(str(a)).split()])
                idx = len(self._docs)
                self._docs.append(doc)
                for t in set(doc[3]) | set(doc[5]) | set(doc[6]) | {doc[4].replace(" ", "")}:
                    if t:
                        self._post.setdefault(t, []).append(idx)
        self._vocab = sorted(self._post)
        self._graph = None

    # ---- lookup ----
    def get(self, kind, ident):
        entries = self.kinds.get(kind) or {}
        if ident in entries:
            return entries[ident]
        real = self._upper.get((kind, str(ident).upper()))
        return entries.get(real) if real else None

    def resolve_id(self, kind, ident):
        e = self.get(kind, ident)
        return e["id"] if e else None

    def kind_counts(self):
        out = []
        for k in KIND_ORDER:
            n = sum(1 for e in (self.kinds.get(k) or {}).values() if not e.get("hidden"))
            if n:
                out.append({"kind": k, "label": KIND_LABELS.get(k, k.title()), "count": n})
        return out

    def list_kind(self, kind, dlc=None, sort="name"):
        """Entries of one kind. dlc = a DLC id, or "base" for entries known to have no DLC tag (entries whose DLC is unknown are left out)."""
        rows = [r for r in (self.kinds.get(kind) or {}).values() if not r.get("hidden")]
        if dlc == "base":
            rows = [r for r in rows if not r.get("dlc") and r.get("dlcKnown") is not False]
        elif dlc:
            rows = [r for r in rows if dlc in (r.get("dlc") or [])]
        if sort == "dlc":
            rows.sort(key=lambda r: (",".join(r.get("dlc") or []), r["name"].lower()))
        else:
            rows.sort(key=lambda r: (r["name"].lower(), r["id"]))
        return rows

    # ---- search ----
    def subtitle(self, kind, e):
        if kind == "element":
            return (e.get("state") or "").capitalize() or "Element"
        if kind == "building":
            cat = e.get("category")
            if cat:
                return "Not in a build menu" if cat == "Uncategorized" else "Build menu: %s" % cat
        if kind == "codex":
            return e.get("category") or "Codex"
        text = e.get("effect") or e.get("desc") or ""
        text = text.split("\n")[0]
        return text if len(text) <= 60 else text[:57].rstrip() + "..."

    def _prefix_tokens(self, tok):
        i = bisect.bisect_left(self._vocab, tok)
        out = []
        while i < len(self._vocab) and self._vocab[i].startswith(tok):
            out.append(self._vocab[i])
            i += 1
        return out

    def _score(self, doc, qn, qtoks, via_fuzzy):
        kind, ident, name_n, name_t, id_n, id_t, alias_t = doc
        rank = _KIND_RANK.get(kind, 20)
        base = 0
        if name_n == qn:
            base = 1000
        elif id_n.replace(" ", "") == qn.replace(" ", ""):
            base = 950
        elif name_n.startswith(qn):
            base = 800
        else:
            # every query token must prefix some name token (in order of appearance, distinct)
            used, ok, pos_pen = set(), True, 0
            for q in qtoks:
                hit = None
                for i, t in enumerate(name_t):
                    if i not in used and t.startswith(q):
                        hit = i
                        break
                if hit is None:
                    ok = False
                    break
                used.add(hit)
                pos_pen += hit
            if ok:
                base = 650 - min(pos_pen, 50)
            elif all(any(t.startswith(q) for t in id_t) or any(t.startswith(q) for t in name_t) for q in qtoks):
                base = 500
            elif all(any(t.startswith(q) for t in alias_t) or any(t.startswith(q) for t in name_t + id_t) for q in qtoks):
                base = 400
            elif qn in name_n:
                base = 300
            elif via_fuzzy:
                base = 100
        if not base:
            return None
        return (-base, len(name_n), rank, name_n)

    def search(self, q, kind=None, limit=20):
        qn = norm(q)
        if not qn:
            return {"query": q, "results": [], "truncated": False}
        qtoks = qn.split()
        cand = None
        for t in qtoks:
            hits = set()
            for v in self._prefix_tokens(t):
                hits.update(self._post[v])
            cand = hits if cand is None else cand & hits
        cand = set(cand or ())
        # substring matches inside names (e.g. "rbon" in "carbon")
        for i, d in enumerate(self._docs):
            if i not in cand and qn in d[2]:
                cand.add(i)
        scored = []
        for i in cand:
            d = self._docs[i]
            if kind and d[0] != kind:
                continue
            s = self._score(d, qn, qtoks, False)
            if s:
                scored.append((s, i))
        if len(scored) < limit:
            for i in self._fuzzy_candidates(qtoks) - cand:
                d = self._docs[i]
                if kind and d[0] != kind:
                    continue
                s = self._score(d, qn, qtoks, True) or (-100, len(d[2]), _KIND_RANK.get(d[0], 20), d[2])
                scored.append((s, i))
        scored.sort()
        truncated = len(scored) > limit
        results = []
        for _s, i in scored[:limit]:
            k, ident = self._docs[i][0], self._docs[i][1]
            e = self.kinds[k][ident]
            results.append({"kind": k, "id": ident, "name": e.get("name") or ident,
                            "dlc": list(e.get("dlc") or []), "subtitle": self.subtitle(k, e)})
        return {"query": q, "results": results, "truncated": truncated}

    def _fuzzy_candidates(self, qtoks):
        """Docs where every query token matches some token exactly, by prefix, or within a typo."""
        sets = []
        for t in qtoks:
            k = _fuzz_k(t)
            hits = set()
            for v in self._vocab:
                if v.startswith(t) or (k and _lev_within(t, v[: len(t) + k], k)) or (k and _lev_within(t, v, k)):
                    hits.update(self._post[v])
            sets.append(hits)
        out = sets[0]
        for s in sets[1:]:
            out = out & s
        return out

    # ---- produced by / used by ----
    def _build_graph(self):
        prod, used = {}, {}

        def add(table, ref, kind, e, role, amt=None):
            rk = (ref[0], ref[1].upper())
            table.setdefault(rk, []).append((kind, e["id"], role, amt))

        def amounts(items, table, kind, e, role):
            for a in items or []:
                if not isinstance(a, dict):
                    continue
                ref = ("element", a["element"]) if a.get("element") else (("tag", a["tag"]) if a.get("tag") else None)
                if ref:
                    add(table, ref, kind, e, role, a.get("kg"))

        for e in self.kinds.get("building", {}).values():
            for c in e.get("converters") or []:
                amounts(c.get("inputs"), used, "building", e, "converter")
                amounts(c.get("outputs"), prod, "building", e, "converter")
            for m in e.get("materials") or []:
                for t in m.get("tags") or []:
                    add(used, ("tag", t), "building", e, "material", m.get("kg"))
        for e in self.kinds.get("recipe", {}).values():
            amounts(e.get("inputs"), used, "recipe", e, "recipe")
            amounts(e.get("outputs"), prod, "recipe", e, "recipe")
        for e in self.kinds.get("critter", {}).values():
            for d in e.get("diets") or []:
                amounts(d.get("consumes"), used, "critter", e, "diet")
                amounts(d.get("produces"), prod, "critter", e, "diet")
            amounts(e.get("drops"), prod, "critter", e, "drop")
        for e in self.kinds.get("plant", {}).values():
            amounts(e.get("irrigation"), used, "plant", e, "irrigation")
            amounts(e.get("fertilizer"), used, "plant", e, "fertilizer")
            amounts(e.get("yield"), prod, "plant", e, "yield")
        for e in self.kinds.get("geyser", {}).values():
            if e.get("element"):
                add(prod, ("element", e["element"]), "geyser", e, "geyser", None)
        for e in self.kinds.get("element", {}).values():
            for side in ("highTransition", "lowTransition"):
                t = e.get(side)
                if t:
                    add(prod, ("element", t["target"]), "element", e, "transition", None)
                    if t.get("secondary"):
                        add(prod, ("element", t["secondary"]), "element", e, "transition", None)
        self._graph = (prod, used)

    def _relations(self, table_ix, kind, ident):
        if self._graph is None:
            self._build_graph()
        table = self._graph[table_ix]
        e = self.get(kind, ident)
        if e is None:
            return []
        keys = [(kind, e["id"].upper())]
        via = {}
        if kind == "element":
            for t in e.get("tags") or []:
                keys.append(("tag", t.upper()))
        seen, out = set(), []
        for k in keys:
            for rk, rid, role, amt in table.get(k, []):
                if (rk, rid, role) in seen:
                    continue
                seen.add((rk, rid, role))
                src = self.kinds[rk][rid]
                row = {"kind": rk, "id": rid, "name": src.get("name") or rid, "dlc": list(src.get("dlc") or []),
                       "role": role}
                if amt is not None:
                    row["kg"] = amt
                if k[0] == "tag":
                    row["viaTag"] = k[1]
                out.append(row)
        out.sort(key=lambda r: (r.get("viaTag") is not None, _KIND_RANK.get(r["kind"], 20), r["name"].lower()))
        return out

    def produced_by(self, kind, ident):
        return self._relations(0, kind, ident)

    def used_by(self, kind, ident):
        return self._relations(1, kind, ident)
