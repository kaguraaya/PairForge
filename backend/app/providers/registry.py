from collections.abc import Iterable

from app.providers.base import ModelCapabilities
from app.providers.capabilities import MODEL_CAPABILITIES


class ModelRegistry:
    def __init__(self, capabilities: Iterable[ModelCapabilities]) -> None:
        self._models = {(item.provider, item.model): item for item in capabilities}

    def get(self, provider: str, model: str) -> ModelCapabilities:
        return self._models[(provider, model)]

    def list(self) -> tuple[ModelCapabilities, ...]:
        return tuple(self._models.values())


model_registry = ModelRegistry(MODEL_CAPABILITIES)

