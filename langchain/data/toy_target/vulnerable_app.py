"""Deliberately vulnerable toy Flask app: the shared target every Foundry
harness notebook points at, from the Indexer onward.

This is fixture data, not a real service -- it is never run as a live
process during the source-only phase (no testbed configured yet). Do not
"fix" the vulnerabilities below; the whole point is for the pipeline to
(re)discover them.

Seeded vulnerabilities:
  1. SQL injection in `get_user_by_name` -- exercises the CodeGuard
     `input-validation-injection` rule.
  2. Hardcoded credential in `STRIPE_API_KEY` -- exercises
     `hardcoded-credentials`.
  3. Path traversal in `read_uploaded_file` -- exercises
     `file-handling-and-uploads`.
"""
from __future__ import annotations

import sqlite3

from flask import Flask, request

app = Flask(__name__)

# Vulnerability 2: hardcoded credential. Deliberately NOT in any real vendor's
# key format (no "sk_live_"-style prefix) so this fixture doesn't trip
# GitHub's secret-push-protection scanning -- the point is the "warning
# signs" pattern (suspicious variable name + random-looking string literal,
# per codeguard-1-hardcoded-credentials.md), not a vendor-format match.
STRIPE_API_KEY = "fixture-hardcoded-not-a-real-key-9f8e7d6c5b4a3210"

UPLOAD_DIR = "/var/app/uploads"


def get_db() -> sqlite3.Connection:
    return sqlite3.connect("app.db")


def get_user_by_name(username: str) -> list[tuple]:
    """Vulnerability 1: SQL injection.

    The query is built by string interpolation instead of a parameterized
    query, so a username like `' OR '1'='1` alters the query's meaning.
    """
    conn = get_db()
    cursor = conn.cursor()
    query = f"SELECT id, username, email FROM users WHERE username = '{username}'"
    cursor.execute(query)
    return cursor.fetchall()


def read_uploaded_file(filename: str) -> bytes:
    """Vulnerability 3: path traversal.

    `filename` is joined onto `UPLOAD_DIR` with no normalization or
    containment check, so a value like `../../etc/passwd` escapes the
    upload directory.
    """
    path = UPLOAD_DIR + "/" + filename
    with open(path, "rb") as f:
        return f.read()


@app.route("/users")
def users_endpoint():
    username = request.args.get("username", "")
    rows = get_user_by_name(username)
    return {"users": rows}


@app.route("/files/<path:filename>")
def files_endpoint(filename: str):
    return read_uploaded_file(filename)


if __name__ == "__main__":
    app.run(debug=True)
