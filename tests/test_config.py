from sqlalchemy.engine import make_url

from app.config import Settings


def test_database_password_is_not_interpreted_as_url(monkeypatch):
    password = "p@ss:/?#%word with spaces'and-quotes"
    monkeypatch.delenv("IGES_DATABASE_URL", raising=False)
    monkeypatch.setenv("IGES_DB_PASSWORD", password)
    assert make_url(Settings.from_env().database_url).password == password
