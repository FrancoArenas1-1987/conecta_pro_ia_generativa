from __future__ import annotations

from pathlib import Path

import yaml

from .exceptions import ConfigurationError
from .models import BrandContext


def load_brand_context(path: Path) -> BrandContext:
    if not path.exists():
        raise ConfigurationError(f"Context file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}

    if not isinstance(payload, dict):
        raise ConfigurationError(f"Invalid context payload in {path}")

    return BrandContext.model_validate(payload)
