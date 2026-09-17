import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "BASE_DIR", tmp_path)
    settings.set_user_context(None)
    yield
    settings.set_user_context(None)
