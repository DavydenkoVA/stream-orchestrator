from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.services.provider_state_store import ProviderStateStore


def test_set_current_model_name_does_not_commit(db_session, monkeypatch) -> None:
    store = ProviderStateStore()
    commit_calls = 0
    original_commit = db_session.commit

    def counting_commit():
        nonlocal commit_calls
        commit_calls += 1
        return original_commit()

    monkeypatch.setattr(db_session, "commit", counting_commit)

    store.set_current_model_name(db_session, "primary", "model_a")

    assert commit_calls == 0


def test_set_current_model_name_persists_after_external_commit(tmp_path) -> None:
    db_file = tmp_path / "provider_state_store.db"
    engine = create_engine(f"sqlite:///{db_file}", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    store = ProviderStateStore()

    first: Session = SessionLocal()
    second: Session = SessionLocal()
    try:
        store.set_current_model_name(first, "primary", "model_a")
        assert store.get_current_model_name(second, "primary") is None

        first.commit()
        assert store.get_current_model_name(second, "primary") == "model_a"
    finally:
        second.close()
        first.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
