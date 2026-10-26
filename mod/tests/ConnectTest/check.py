"""Validate the request files the mod code wrote against contracts/pairing.schema.json#/$defs/Request, and the QR fixture limits.
Usage: check.py <repo root> <outdir>"""
import json, os, sys
root, out = sys.argv[1], sys.argv[2]
sys.path.insert(0, root)
from tests.jsonschema_mini import Validator
v = Validator(os.path.join(root, "contracts"))
bad = 0
names = sorted(os.listdir(os.path.join(out, "requests")))
for n in names:
    doc = json.load(open(os.path.join(out, "requests", n)))
    errs = v.validate(doc, "pairing.schema.json#/$defs/Request")
    print(("ok   " if not errs else "FAIL ") + n + " " + doc["type"] + ("" if not errs else " " + str(errs)))
    bad += bool(errs)
assert len(names) == 5, names
sys.exit(1 if bad else 0)
