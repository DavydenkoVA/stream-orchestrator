from __future__ import annotations
import typing
from datetime import UTC, datetime  # noqa: COP002
from typing import TYPE_CHECKING  # noqa: COP002

from sqlalchemy import select

from app.models.provider_runtime_state import ProviderRuntimeState


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@typing.final
class ProviderStateStore:
    def get_current_model_name(self, db: Session, provider_name: str) -> str | None:  # noqa: COP006
        stmt: typing.Final = select(ProviderRuntimeState).where(ProviderRuntimeState.provider_name == provider_name)  # noqa: COP005, COP011
        row: typing.Final = db.scalar(stmt)  # noqa: COP005
        if row is None:
            return None
        return row.current_model_name

    def set_current_model_name(
        self,
        db: Session,  # noqa: COP006
        provider_name: str,
        model_name: str | None,
    ) -> None:
        stmt: typing.Final = select(ProviderRuntimeState).where(ProviderRuntimeState.provider_name == provider_name)  # noqa: COP005, COP011
        row = db.scalar(stmt)  # noqa: COP005

        if row is None:
            row = ProviderRuntimeState(  # noqa: COP005
                provider_name=provider_name,
                current_model_name=model_name,
                updated_at=datetime.now(UTC),
            )
            db.add(row)
        else:
            row.current_model_name = model_name
            row.updated_at = datetime.now(UTC)

        db.flush()
