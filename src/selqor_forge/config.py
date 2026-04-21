# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Application configuration."""

from __future__ import annotations

import json
import logging
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TransportMode(StrEnum):
    STDIO = "stdio"
    HTTP = "http"


class OutputTarget(StrEnum):
    TYPESCRIPT = "typescript"
    RUST = "rust"


class ToolCountBounds(BaseModel):
    min: int = 5
    max: int = 15


class AnthropicConfig(BaseModel):
    enabled: bool = True
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 3200
    temperature: float = 0.0


class AppConfig(BaseModel):
    target_tool_count: ToolCountBounds = ToolCountBounds()
    include_custom_request_tool: bool = False
    output_targets: list[OutputTarget] = [OutputTarget.TYPESCRIPT, OutputTarget.RUST]
    default_transport: TransportMode = TransportMode.STDIO
    anthropic: AnthropicConfig = AnthropicConfig()

    @classmethod
    def load(cls, path: Path | None) -> AppConfig:
        if path is None:
            logger.debug("no config path provided; using defaults")
            return cls()

        if not path.exists():
            logger.debug("config file not found at %s; using defaults", path)
            return cls()

        logger.debug("loading configuration file from %s", path)
        raw = path.read_text()
        logger.debug("read config file: %d bytes", len(raw))

        parsed = cls.model_validate(json.loads(raw))
        logger.debug(
            "config loaded: targets=%d transport=%s anthropic_enabled=%s",
            len(parsed.output_targets),
            parsed.default_transport,
            parsed.anthropic.enabled,
        )
        return parsed

    def with_targets(self, targets: list[OutputTarget]) -> AppConfig:
        return self.model_copy(update={"output_targets": targets})

    def with_transport(self, transport: TransportMode | None) -> AppConfig:
        if transport is not None:
            return self.model_copy(update={"default_transport": transport})
        return self

    def with_anthropic_enabled(self, enabled: bool) -> AppConfig:
        return self.model_copy(update={"anthropic": self.anthropic.model_copy(update={"enabled": enabled})})
