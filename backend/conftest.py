"""
Keep the backend test suite away from the production database.

app.py calls load_dotenv(../.env) at import time, and that file holds the
production DATABASE_URL. Any test module that imports app (most of them) used
to leak that URL into os.environ before test_endpoints.py evaluated its
"is a DB configured?" check -- so `pytest` seeded TEST: rows into the live
alerts table and the results depended on whatever real alerts were there.

Rules, applied before any test module is imported:

* TEST_DATABASE_URL set   -> DB-backed tests run against it.
* ALLOW_LIVE_DB_TESTS=1   -> DB-backed tests run against whatever DATABASE_URL
                             resolves to (the old behaviour; opt-in only).
* otherwise               -> DATABASE_URL is pinned to a placeholder so that
                             load_dotenv() cannot override it (it never
                             replaces existing variables), database.py imports
                             cleanly, and DB-backed tests skip.
"""

import os

TEST_DB_PLACEHOLDER = "postgresql://polybot-tests-no-db@127.0.0.1:1/placeholder"


def _configure_test_database() -> bool:
    test_url = os.environ.get("TEST_DATABASE_URL")
    if test_url:
        os.environ["DATABASE_URL"] = test_url
        return True
    if os.environ.get("ALLOW_LIVE_DB_TESTS") == "1":
        # Leave DATABASE_URL alone; load_dotenv in app.py will fill it in.
        return True
    os.environ["DATABASE_URL"] = TEST_DB_PLACEHOLDER
    return False


HAS_TEST_DB = _configure_test_database()
