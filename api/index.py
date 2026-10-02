"""Vercel entry point: the dashboard, behind a password, reading results from Postgres.

Environment (set in the Vercel project):
    DATABASE_URL        Postgres connection string (the Neon integration sets it)
    RENTCAST_API_KEY    optional; enables the "Refresh sales" button for the Recently Sold pins
    DASHBOARD_PASSWORD  password for the browser login prompt; the username is recorded as who
                        knocked on a door, so each person should use their own name
"""
import base64
import hmac
import html
import os
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dashboard  # noqa: E402
import pgstore  # noqa: E402
import snapshot  # noqa: E402


class handler(dashboard.Handler):
    db_note = None

    def open_db(self):
        try:
            url = pgstore._database_url()
        except RuntimeError:  # no database connected yet: show an empty page instead of an error
            self.db_note = "No database is connected: DATABASE_URL (or POSTGRES_URL) is not set for this deployment."
            return pgstore.assessor.db(":memory:")
        con = pgstore.load(url)
        if not con.execute("SELECT COUNT(*) FROM parcels").fetchone()[0]:
            host = urllib.parse.urlsplit(url).hostname or "unknown host"
            self.db_note = f"The connected database ({host.split('.')[0]}) has no results yet."
        return con

    def render_page(self, con, qs):
        page = snapshot.build(con, can_save=True)
        if self.db_note:
            banner = f'<div class="wrap" style="padding-block:12px 0"><p class="sub" role="status">{html.escape(self.db_note)}</p></div>'
            page = page.replace('<div class="wrap">', banner + '\n<div class="wrap">', 1)
        return page

    def store_sales(self, sale_rows):
        pgstore.replace_sales(sale_rows)

    def save_visit(self, pid, outcome, notes, visitor):
        return pgstore.add_visit(pid, outcome, notes, visitor)

    def visitor(self):
        return (self._credentials()[0].strip() or "unknown")[:80]

    def _credentials(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                user, _, password = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
                return user, password
            except ValueError:
                pass
        return "", ""

    def authorized(self):
        password = os.environ.get("DASHBOARD_PASSWORD")
        if not password:
            self._send(503, "text/plain; charset=utf-8", b"Set DASHBOARD_PASSWORD in the Vercel project to enable this site.")
            return False
        supplied = self._credentials()[1]
        if hmac.compare_digest(supplied.encode(), password.encode()):
            return True
        self._send(401, "text/plain; charset=utf-8", b"Login required.",
                   {"WWW-Authenticate": 'Basic realm="Poor condition parcels", charset="UTF-8"'})
        return False
