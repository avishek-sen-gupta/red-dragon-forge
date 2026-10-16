"""Reads a TOML configuration file into its typed model, turning every fault into a ConfigError naming the file."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TypeVar

from litter.validation_message import validation_message
from pydantic import BaseModel, ValidationError

from red_dragon_forge.config_error import ConfigError

M = TypeVar("M", bound=BaseModel)


def _text(path: Path) -> str:
    try:
        return path.read_text("utf-8")
    except OSError as exc:
        raise ConfigError(f"{path}: {exc.strerror}") from exc


def toml_config(model: type[M], path: Path) -> M:
    text = _text(path)
    try:
        return model.model_validate(tomllib.loads(text))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path.name}: {exc}") from exc
    except ValidationError as invalid:
        raise ConfigError(f"{path.name}: {validation_message(invalid)}") from invalid
