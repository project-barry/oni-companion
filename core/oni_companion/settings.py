"""Core settings (contracts/settings.schema.json). Shared by every front end.

One file, settings.json, in the core's data folder. Written atomically (temp file, fsync, rename).
A missing or damaged file means the defaults. Keys this version does not know are kept when saving.
"""
import json
import os
import threading

SCHEMA = 1
DEFAULTS = {"zoomToDupeOnSelect": False}
FILE_NAME = "settings.json"


class SettingsError(ValueError):
    """A value the core will not take. The message names the setting."""


def _check(name, value):
    if name == "zoomToDupeOnSelect":
        if not isinstance(value, bool):
            raise SettingsError("%s must be true or false." % name)
        return value
    raise KeyError(name)


class Settings:
    """path=None keeps everything in memory (tests, previews). on_change() runs after each save."""

    def __init__(self, path=None, on_change=None):
        self.path = path
        self.on_change = on_change
        self._lock = threading.Lock()
        self._extra = {}                     # keys we do not know, kept on save
        self._values = dict(DEFAULTS)
        self._load()

    def _load(self):
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for k, v in data.items():
            if k == "schema":
                continue
            if k in DEFAULTS:
                try:
                    self._values[k] = _check(k, v)
                except SettingsError:
                    pass                     # a bad value in the file means the default
            else:
                self._extra[k] = v

    def get(self, name):
        with self._lock:
            return self._values[name]

    def values(self):
        with self._lock:
            return dict(self._values)

    def update(self, values):
        """Validate every known key first, then save once. Unknown keys in `values` are ignored.
        Returns the new values. Raises SettingsError (nothing is saved)."""
        if not isinstance(values, dict):
            raise SettingsError("values must be an object.")
        clean = {k: _check(k, v) for k, v in values.items() if k in DEFAULTS}
        with self._lock:
            new = dict(self._values)
            new.update(clean)
            self._write(new)
            self._values = new
            out = dict(new)
        if self.on_change:
            self.on_change()
        return out

    def _write(self, values):
        if not self.path:
            return
        doc = dict(self._extra)
        doc.update(values)
        doc["schema"] = SCHEMA
        folder = os.path.dirname(self.path) or "."
        os.makedirs(folder, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
