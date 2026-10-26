"""Token set with labels. Constant-time compare against every token."""
import hmac
import secrets
import threading


class TokenSet:
    def __init__(self):
        self._tokens = {}   # label -> token
        self._lock = threading.Lock()

    def add(self, label, token=None):
        token = token or secrets.token_urlsafe(24)
        with self._lock:
            self._tokens[label] = token
        return token

    def revoke(self, label):
        with self._lock:
            return self._tokens.pop(label, None) is not None

    def labels(self):
        with self._lock:
            return sorted(self._tokens)

    def check(self, candidate):
        """Return the label of the matching token or None. Never exits early."""
        if not isinstance(candidate, str) or not candidate:
            candidate = ""
        cand = candidate.encode("utf-8", "replace")
        found = None
        with self._lock:
            items = list(self._tokens.items())
        for label, tok in items:
            if hmac.compare_digest(cand, tok.encode("utf-8")) and candidate:
                found = label
        return found
