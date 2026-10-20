"""Generate local disposable CI secrets; never print credentials."""
from pathlib import Path
from secrets import token_urlsafe

from sqlalchemy.engine import URL

admin = token_urlsafe(32)
runtime = token_urlsafe(32) + "@:/?%$="
Path(".env").write_text(
    f"POSTGRES_ADMIN_PASSWORD='{admin}'\nIGES_DB_PASSWORD='{runtime}'\n"
    "IGES_PUBLIC_PROJECT_ID=00000000-0000-4000-8000-000000000001\n",
    encoding="utf-8",
)
Path("work").mkdir(exist_ok=True)
Path("work/ci-admin-url").write_text(URL.create(
    "postgresql+psycopg", username="postgres", password=admin, host="db", port=5432,
    database="iges").render_as_string(hide_password=False), encoding="utf-8")
