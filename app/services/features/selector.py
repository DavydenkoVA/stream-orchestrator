from __future__ import annotations

from app.services.features.base import ChatRequest, FeatureHandler


class FeatureSelector:
    """Selects a handler for a chat request.

    Current implementation uses ordered rules (first match wins).
    Can be replaced with model-based selector later without changing handlers.
    """

    def __init__(self, handlers: list[FeatureHandler]) -> None:
        self.handlers = handlers

    def select(self, request: ChatRequest) -> FeatureHandler:
        for handler in self.handlers:
            if handler.matches(request):
                return handler
        raise RuntimeError("No feature handler matched request")
