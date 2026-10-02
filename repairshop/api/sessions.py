"""Signed-in sessions for the single backend process.

Sessions live in memory: there is exactly one backend process, and restarting it ends
every session, matching the desktop application's sign-in on each start. The browser
holds only an opaque random token in an HTTP-only, same-site cookie; identity and role
are always re-read from the database and never trusted from the client.
"""
import secrets
import threading
import time

COOKIE = 'rs_session'
#: Unsafe requests must carry this header. A cross-site form cannot set it, which closes
#: the cross-site request forgery route alongside the SameSite=Strict cookie.
CSRF_HEADER = 'x-requested-with'
CSRF_VALUE = 'RepairShop'


class Sessions:
    def __init__(self, idle_seconds):
        self.idle = idle_seconds
        self.lock = threading.Lock()
        self.items = {}

    def create(self, user_id):
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.items[token] = dict(user_id=user_id, seen=time.monotonic())
        return token

    def user_id(self, token):
        if not token:
            return None
        with self.lock:
            entry = self.items.get(token)
            if not entry:
                return None
            if time.monotonic() - entry['seen'] > self.idle:
                self.items.pop(token, None)
                return None
            entry['seen'] = time.monotonic()
            return entry['user_id']

    def end(self, token):
        with self.lock:
            self.items.pop(token, None)

    def end_user(self, user_id):
        with self.lock:
            for token in [t for t, e in self.items.items() if e['user_id'] == user_id]:
                self.items.pop(token)

    def most_recent_user(self):
        """The person background work runs as, exactly as the desktop app did while open."""
        with self.lock:
            live = [e for e in self.items.values() if time.monotonic() - e['seen'] <= self.idle]
        return max(live, key=lambda e: e['seen'])['user_id'] if live else None
