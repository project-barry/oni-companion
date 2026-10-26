"""Small file helpers: atomic JSON writes with mode 600 for secrets."""
import json
import os


def write_atomic(path, data, mode=0o600):
    """Write bytes or text to path through a temp file in the same folder, then rename. Never leaves a half file."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path, obj, mode=0o600):
    write_atomic(path, json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True), mode)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, RecursionError, MemoryError):
        return default
