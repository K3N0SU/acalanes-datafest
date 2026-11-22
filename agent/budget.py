"""Token ledger shared by all three models.

Claude and Gemini have hard caps (CLAUDE_TOKEN_BUDGET, GEMINI_TOKEN_BUDGET). DeepSeek is tracked but
unlimited. The current status is shown to Claude after every tool round so it can pace itself.
"""
import os
import threading

DEFAULTS = {"claude": 300_000, "gemini": 150_000, "deepseek": None}


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    def __init__(self, limits=None):
        self.limits = dict(DEFAULTS)
        for name, var in (("claude", "CLAUDE_TOKEN_BUDGET"), ("gemini", "GEMINI_TOKEN_BUDGET")):
            if os.environ.get(var):
                self.limits[name] = int(os.environ[var])
        self.limits.update(limits or {})
        self.used = {k: 0 for k in self.limits}
        self.calls = {k: 0 for k in self.limits}
        self._lock = threading.Lock()

    def remaining(self, name):
        lim = self.limits[name]
        return None if lim is None else max(0, lim - self.used[name])

    def check(self, name, need=0):
        """Raise before a call that would start with the budget already spent (or short of `need`)."""
        rem = self.remaining(name)
        if rem is not None and rem <= need:
            raise BudgetExceeded(f"{name} token budget exhausted ({self.used[name]:,}/{self.limits[name]:,})")

    def add(self, name, tokens):
        with self._lock:
            self.used[name] += int(tokens or 0)
            self.calls[name] += 1

    def status(self):
        parts = []
        for k in self.limits:
            lim = self.limits[k]
            if lim is None:
                parts.append(f"{k}: {self.used[k]:,} used (unlimited)")
            else:
                parts.append(f"{k}: {self.used[k]:,}/{lim:,} used, {self.remaining(k):,} left")
        return "[token budget] " + " | ".join(parts)

    def as_dict(self):
        return {k: {"used": self.used[k], "limit": self.limits[k], "calls": self.calls[k]} for k in self.limits}
