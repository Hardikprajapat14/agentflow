import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="agentflow-test-")
os.environ.update({
    "EMBEDDING_BACKEND": "hashing", "CELERY_EAGER": "true", "LLM_API_KEY": "test-key", "ENVIRONMENT": "test",
    "UPLOAD_DIR": f"{_tmp}/uploads", "REPORT_DIR": f"{_tmp}/reports",
})
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://agentflow:agentflow@localhost:5432/agentflow")

import pathlib  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402

SAMPLE = pathlib.Path(__file__).resolve().parents[2] / "sample_data"


@pytest.fixture(scope="session", autouse=True)
def _db_ready():
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1 FROM users LIMIT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Database with migrations not available: {exc}", allow_module_level=True)


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def auth(client):
    import uuid

    email = f"t{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/auth/register", json={"email": email, "password": "supersecret1", "name": "Tester"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def sample_dir():
    return SAMPLE
