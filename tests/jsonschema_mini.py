"""Small stdlib JSON Schema validator for the ONI Companion contracts.

Supports the subset the contracts use. An unsupported keyword raises
SchemaError, so a contract can never silently rely on something unchecked.
Cross-file $ref ("blocks.schema.json#/$defs/Ref") resolves inside one
contracts directory.
"""
import json
import os
import re

ANNOTATIONS = {"$schema", "$id", "title", "description", "$comment", "default",
               "examples", "$defs", "definitions", "format"}
SUPPORTED = {"$ref", "type", "enum", "const", "properties", "required",
             "additionalProperties", "items", "minItems", "maxItems",
             "uniqueItems", "minLength", "maxLength", "pattern", "minimum",
             "maximum", "oneOf", "anyOf", "allOf", "if", "then", "else"}
DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


class SchemaError(Exception):
    pass


class Validator:
    def __init__(self, contracts_dir):
        self.dir = contracts_dir
        self.docs = {}

    def doc(self, name):
        if name not in self.docs:
            with open(os.path.join(self.dir, name), encoding="utf-8") as f:
                self.docs[name] = json.load(f)
        return self.docs[name]

    def resolve(self, ref, current):
        name, _, frag = ref.partition("#")
        name = name or current
        node = self.doc(name)
        if frag:
            for part in frag.lstrip("/").split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                if not isinstance(node, dict) or part not in node:
                    raise SchemaError("unresolved $ref %s" % ref)
                node = node[part]
        return node, name

    def validate(self, instance, schema_ref):
        """schema_ref like 'screen.schema.json' or 'api.schema.json#/$defs/Status'.
        Returns a list of error strings (empty = valid)."""
        schema, name = self.resolve(schema_ref, schema_ref.partition("#")[0])
        errs = []
        self._check(instance, schema, name, "$", errs)
        return errs

    # ---- core ----
    def _check(self, inst, schema, doc, path, errs):
        if schema is True:
            return
        if schema is False:
            errs.append("%s: not allowed" % path)
            return
        for k in schema:
            if k not in SUPPORTED and k not in ANNOTATIONS:
                raise SchemaError("unsupported keyword %r at %s" % (k, path))
        if "$ref" in schema:
            sub, subdoc = self.resolve(schema["$ref"], doc)
            self._check(inst, sub, subdoc, path, errs)
        if "type" in schema:
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(self._is(inst, t) for t in types):
                errs.append("%s: expected %s, got %s" % (path, "/".join(types), type(inst).__name__))
                return
        if "const" in schema and not _eq(inst, schema["const"]):
            errs.append("%s: expected %r" % (path, schema["const"]))
        if "enum" in schema and not any(_eq(inst, e) for e in schema["enum"]):
            errs.append("%s: %r not in %r" % (path, inst, schema["enum"]))
        if isinstance(inst, str):
            if "minLength" in schema and len(inst) < schema["minLength"]:
                errs.append("%s: shorter than %d" % (path, schema["minLength"]))
            if "maxLength" in schema and len(inst) > schema["maxLength"]:
                errs.append("%s: longer than %d" % (path, schema["maxLength"]))
            if "pattern" in schema and not re.search(schema["pattern"], inst):
                errs.append("%s: %r does not match %s" % (path, inst, schema["pattern"]))
            if schema.get("format") == "date-time" and not DATETIME.match(inst):
                errs.append("%s: %r is not a date-time" % (path, inst))
        if _is_num(inst):
            if "minimum" in schema and inst < schema["minimum"]:
                errs.append("%s: %r below minimum %r" % (path, inst, schema["minimum"]))
            if "maximum" in schema and inst > schema["maximum"]:
                errs.append("%s: %r above maximum %r" % (path, inst, schema["maximum"]))
        if isinstance(inst, list):
            if "minItems" in schema and len(inst) < schema["minItems"]:
                errs.append("%s: fewer than %d items" % (path, schema["minItems"]))
            if "maxItems" in schema and len(inst) > schema["maxItems"]:
                errs.append("%s: more than %d items" % (path, schema["maxItems"]))
            if schema.get("uniqueItems"):
                seen = [json.dumps(x, sort_keys=True) for x in inst]
                if len(set(seen)) != len(seen):
                    errs.append("%s: items not unique" % path)
            if "items" in schema:
                for i, x in enumerate(inst):
                    self._check(x, schema["items"], doc, "%s[%d]" % (path, i), errs)
        if isinstance(inst, dict):
            for r in schema.get("required", []):
                if r not in inst:
                    errs.append("%s: missing required %r" % (path, r))
            props = schema.get("properties", {})
            for k, v in inst.items():
                if k in props:
                    self._check(v, props[k], doc, "%s.%s" % (path, k), errs)
                elif "additionalProperties" in schema:
                    ap = schema["additionalProperties"]
                    if ap is False:
                        errs.append("%s: unexpected property %r" % (path, k))
                    elif ap is not True:
                        self._check(v, ap, doc, "%s.%s" % (path, k), errs)
        for sub in schema.get("allOf", []):
            self._check(inst, sub, doc, path, errs)
        if "anyOf" in schema:
            if not any(not self._sub(inst, s, doc, path) for s in schema["anyOf"]):
                errs.append("%s: matches none of anyOf" % path)
        if "oneOf" in schema:
            results = [self._sub(inst, s, doc, path) for s in schema["oneOf"]]
            ok = [r for r in results if not r]
            if len(ok) != 1:
                if not ok:
                    best = min(results, key=len)
                    errs.append("%s: matches none of oneOf; closest branch errors: %s" % (path, "; ".join(best[:4])))
                else:
                    errs.append("%s: matches %d branches of oneOf" % (path, len(ok)))
        if "if" in schema:
            if not self._sub(inst, schema["if"], doc, path):
                if "then" in schema:
                    self._check(inst, schema["then"], doc, path, errs)
            elif "else" in schema:
                self._check(inst, schema["else"], doc, path, errs)

    def _sub(self, inst, schema, doc, path):
        e = []
        self._check(inst, schema, doc, path, e)
        return e

    @staticmethod
    def _is(inst, t):
        if t == "object":
            return isinstance(inst, dict)
        if t == "array":
            return isinstance(inst, list)
        if t == "string":
            return isinstance(inst, str)
        if t == "boolean":
            return isinstance(inst, bool)
        if t == "null":
            return inst is None
        if t == "integer":
            return (isinstance(inst, int) and not isinstance(inst, bool)) or (isinstance(inst, float) and inst.is_integer())
        if t == "number":
            return _is_num(inst)
        raise SchemaError("unknown type %r" % t)

    # ---- contract self-check ----
    def check_schema(self, name):
        """Walk a schema file: unsupported keywords and unresolved $refs raise SchemaError."""
        self._walk(self.doc(name), name, "$")

    def _walk(self, node, doc, path):
        if isinstance(node, dict):
            if "$ref" in node:
                self.resolve(node["$ref"], doc)
            for k, v in node.items():
                if k in ("properties", "$defs", "definitions"):
                    for kk, vv in v.items():
                        self._walk(vv, doc, "%s.%s.%s" % (path, k, kk))
                elif k in ("enum", "const", "default", "examples", "required"):
                    continue
                elif k in SUPPORTED or k in ANNOTATIONS:
                    if isinstance(v, (dict, list)):
                        self._walk(v, doc, path + "." + k)
                else:
                    raise SchemaError("unsupported keyword %r at %s" % (k, path))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                self._walk(v, doc, "%s[%d]" % (path, i))


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _eq(a, b):
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b
