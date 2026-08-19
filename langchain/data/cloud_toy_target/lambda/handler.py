"""A small, deliberately-vulnerable Lambda handler -- the code half of
the cloud_toy_target scenario. Mirrors data/toy_target/vulnerable_app.py's
own SQL-injection pattern, kept self-contained here rather than sharing a
file across fixtures, so this fixture doesn't break if that one changes.
"""


def get_db():
    import sqlite3

    return sqlite3.connect(":memory:")


def get_user_by_name(username: str) -> list[tuple]:
    """Vulnerability: SQL injection via string interpolation instead of a
    parameterized query."""
    conn = get_db()
    cursor = conn.cursor()
    query = f"SELECT id, username, email FROM users WHERE username = '{username}'"
    cursor.execute(query)
    return cursor.fetchall()


def handler(event, context):
    return get_user_by_name(event.get("username", ""))
