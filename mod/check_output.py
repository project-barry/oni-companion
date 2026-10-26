#!/usr/bin/env python3
"""Validate files written by the ONI Companion Link mod against the frozen contracts.

Usage: python3 mod/check_output.py FILE [FILE...]
  gamedata-*.json  -> contracts/mod-export.schema.json
  live.json        -> contracts/mod-live.schema.json
  sync/status.json (status*.json) -> mod-sync-status schema (v1.2)
  ack-N.json / cmd-N.json / art manifest.json -> mod-ack / mod-command / mod-art-manifest schemas
  theme.json       -> contracts/theme.schema.json#/$defs/ModTheme (and the PNG files next to it must exist)
A file with a "state" key is treated as live.json, one with "slices" as theme.json, otherwise as an export.

The export may carry a top-level "constants" object (requested contract change, not yet in the
frozen schema). It is allowed here through an in-memory overlay; nothing in contracts/ is edited.
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from tests.jsonschema_mini import Validator  # noqa: E402

CONTRACTS = os.path.join(ROOT, "contracts")


def overlay_validator():
    v = Validator(CONTRACTS)
    # constants is part of the frozen schema since v1.3 (P3); nothing to overlay any more.
    return v


def check(path, v):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    base = os.path.basename(path)
    if base.startswith("ack-"):
        schema = "mod-ack.schema.json"
    elif base.startswith("cmd-"):
        schema = "mod-command.schema.json"
    elif base == "manifest.json":
        schema = "mod-art-manifest.schema.json"
    elif base.startswith("graystroke"):
        schema = "font-atlas.schema.json"
    elif base.startswith("status") or ("stages" in data and "scope" in data):
        schema = "mod-sync-status.schema.json"
    elif "state" in data:
        schema = "mod-live.schema.json"
    elif "slices" in data:
        schema = "theme.schema.json#/$defs/ModTheme"
    else:
        schema = "mod-export.schema.json"
    errs = v.validate(data, schema)
    if "slices" in data:
        for sl in data["slices"]:
            fp = os.path.join(os.path.dirname(os.path.abspath(path)), sl.get("file", ""))
            if not os.path.isfile(fp):
                errs.append("slice %s: file %s missing" % (sl.get("name"), sl.get("file")))
    return schema, errs, data


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    v = overlay_validator()
    bad = 0
    for p in argv:
        try:
            schema, errs, data = check(p, v)
        except (OSError, ValueError) as e:
            print("FAIL %s: %s" % (p, e))
            bad += 1
            continue
        if errs:
            bad += 1
            print("FAIL %s (%s): %d errors" % (p, schema, len(errs)))
            for e in errs[:20]:
                print("   ", e)
        else:
            extra = ""
            if schema.startswith("theme"):
                extra = " colors=%d slices=%d" % (len(data["colors"]), len(data["slices"]))
            if schema == "mod-export.schema.json":
                extra = " " + ", ".join("%s=%d" % (k, len(data[k])) for k in
                                         ("buildings", "elements", "critters", "plants", "geysers", "foods",
                                          "medicines", "recipes", "techs", "traits", "skills", "rooms"))
            print("OK   %s (%s)%s" % (p, schema, extra))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
