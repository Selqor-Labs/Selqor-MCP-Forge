from __future__ import annotations

from sqlalchemy import create_engine as real_create_engine

from selqor_forge.dashboard import db as dashboard_db


def test_init_db_falls_back_to_embedded_sqlite_when_configured_database_is_unavailable(
    tmp_state_dir,
    monkeypatch,
):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@127.0.0.1:1/forge")

    attempts: list[tuple[str, dict[str, object]]] = []

    def fake_create_engine(url, **kwargs):
        attempts.append((str(url), kwargs))
        if str(url).startswith("postgresql+psycopg://"):
            raise OSError("connection refused")
        return real_create_engine(url, **kwargs)

    monkeypatch.setattr(dashboard_db, "create_engine", fake_create_engine)

    session_factory = dashboard_db.init_db(state_dir=tmp_state_dir)

    assert session_factory is not None
    assert attempts[0][0].startswith("postgresql+psycopg://")
    assert attempts[0][1]["connect_args"]["connect_timeout"] == 30
    bind = session_factory.kw["bind"]
    assert str(bind.url).startswith("sqlite:///")
