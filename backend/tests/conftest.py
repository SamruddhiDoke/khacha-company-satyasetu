"""Test configuration.

Unit/integration tests run against a separate Postgres database
(`satyasetu_test`) and NEVER call real providers: provider keys are blanked
unless SATYASETU_LIVE_TESTS=1 (used only by tests marked `live`)."""
import os
import subprocess
import sys

_base = os.environ.get("DATABASE_URL", "postgresql+asyncpg://satyasetu:satyasetu-local@db:5432/satyasetu")
os.environ["DATABASE_URL"] = _base.rsplit("/", 1)[0] + "/satyasetu_test"
os.environ["DATA_DIR"] = "/tmp/satyasetu-test"
if os.environ.get("SATYASETU_LIVE_TESTS") != "1":
    for k in ("GEMINI_API_KEY", "TAVILY_API_KEY", "FACTCHECK_API_KEY"):
        os.environ[k] = ""

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.providers import registry  # noqa: E402

TABLES = ("provider_usage", "document_findings", "corrections", "evidence", "sources", "claims",
          "verification_events", "verification_jobs", "messages", "attachments", "conversations", "sessions")


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    env = dict(os.environ)
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], check=False, env=env, capture_output=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env)
    yield


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    from app.core import events
    events.bus._seq.clear()
    registry.reset()
    yield
    from app.core import jobs
    await jobs.wait_all(timeout=20)
    registry.reset()


@pytest.fixture
def settings():
    s = get_settings()
    snapshot = s.model_dump()
    yield s
    for k, v in snapshot.items():
        setattr(s, k, v)


@pytest_asyncio.fixture
async def client():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def other_client():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def pytest_collection_modifyitems(items):
    # One event loop for the whole run: the DB engine pool and event bus are process-wide.
    session_loop = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if pytest_asyncio.is_async_test(item):
            item.add_marker(session_loop, append=False)
