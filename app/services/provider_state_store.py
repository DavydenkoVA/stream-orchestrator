from __future__ import annotations
import typing
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.provider_runtime_state import ProviderRuntimeState


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class ProviderStateStore:
    def get_current_model_name(self, db: Session, provider_name: str) -> str | None:
        stmt: typing.Final = select(ProviderRuntimeState).where(ProviderRuntimeState.provider_name == provider_name)
        row: typing.Final = db.scalar(stmt)
        if row is None:
            return None
        return row.current_model_name

    def set_current_model_name(
        self,
        db: Session,
        provider_name: str,
        model_name: str | None,
    ) -> None:
        stmt: typing.Final = select(ProviderRuntimeState).where(ProviderRuntimeState.provider_name == provider_name)
        row = db.scalar(stmt)

        if row is None:
            row = ProviderRuntimeState(
                provider_name=provider_name,
                current_model_name=model_name,
                updated_at=datetime.now(UTC),
            )
            db.add(row)
        else:
            row.current_model_name = model_name
            row.updated_at = datetime.now(UTC)

        db.flush()
