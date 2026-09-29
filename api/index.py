"""Vercel entry point: the dashboard, behind a password, reading results from Postgres.

Environment (set in the Vercel project):
    DATABASE_URL        Postgres connection string (the Neon integration sets it)
    DASHBOARD_PASSWORD  password for the browser login prompt; any username works
"""
import base64
import hmac
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dashboard  # noqa: E402
import pgstore  # noqa: E402
import snapshot  # noqa: E402


class handler(dashboard.Handler):
    def open_db(self):
        try:
            return pgstore.load()
        except RuntimeError:  # no database connected yet: show an empty page instead of an error
            return pgstore.assessor.db(":memory:")

    def render_page(self, con, qs):
        return snapshot.build(con)

    def authorized(self):
        password = os.environ.get("DASHBOARD_PASSWORD")
        if not password:
            self._send(503, "text/plain; charset=utf-8", b"Set DASHBOARD_PASSWORD in the Vercel project to enable this site.")
            return False
        supplied = ""
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                supplied = base64.b64decode(auth[6:]).decode("utf-8").partition(":")[2]
            except ValueError:
                supplied = ""
        if hmac.compare_digest(supplied.encode(), password.encode()):
            return True
        self._send(401, "text/plain; charset=utf-8", b"Login required.",
                   {"WWW-Authenticate": 'Basic realm="Poor condition parcels", charset="UTF-8"'})
        return False
