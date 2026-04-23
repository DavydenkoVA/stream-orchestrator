from __future__ import annotations
from typing import TYPE_CHECKING  # noqa: COP002


if TYPE_CHECKING:
    from app.services.features.base import ChatRequest, FeatureHandler


class FeatureSelector:  # noqa: COP012
    """Selects a handler for a chat request.

    Current implementation uses ordered rules (first match wins).
    Can be replaced with model-based selector later without changing handlers.
    """

    def __init__(self, handlers: list[FeatureHandler]) -> None:
        self.handlers = handlers

    def select(self, request: ChatRequest) -> FeatureHandler:  # noqa: COP006, COP007, COP009
        for handler in self.handlers:  # noqa: COP015
            if handler.matches(request):
                return handler
        raise RuntimeError("No feature handler matched request")
