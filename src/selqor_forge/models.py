# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Core data models for the Selqor Forge pipeline."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SpecKind(StrEnum):
    OPEN_API_3 = "open_api3"
    SWAGGER_2 = "swagger2"


class AuthKind(StrEnum):
    NONE = "none"
    API_KEY_HEADER = "api_key_header"
    API_KEY_QUERY = "api_key_query"
    BEARER = "bearer"
    OAUTH2_CLIENT_CREDENTIALS = "oauth2_client_credentials"
    BASIC = "basic"
    UNKNOWN = "unknown"


class AuthScheme(BaseModel):
    name: str
    kind: AuthKind
    raw_type: str | None = None
    details: str | None = None


class ApiParameter(BaseModel):
    name: str
    location: str
    required: bool
    description: str | None = None
    schema_: Any = Field(default=None, alias="schema")

    model_config = {"populate_by_name": True}


class ParsedEndpoint(BaseModel):
    id: str
    method: str
    path: str
    summary: str
    description: str
    tags: list[str] = Field(default_factory=list)
    parameters: list[ApiParameter] = Field(default_factory=list)
    request_body_schema: Any | None = None
    response_schema: Any | None = None
    security: list[str] = Field(default_factory=list)


class ParsedSpec(BaseModel):
    source: str
    title: str
    version: str
    spec_kind: SpecKind
    auth_schemes: list[AuthScheme] = Field(default_factory=list)
    global_security: list[str] = Field(default_factory=list)
    endpoints: list[ParsedEndpoint] = Field(default_factory=list)


class EndpointIntent(StrEnum):
    READ = "read"
    SEARCH = "search"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    WORKFLOW = "workflow"
    ADMIN = "admin"
    UNKNOWN = "unknown"


class UasfEndpoint(BaseModel):
    id: str
    method: str
    path: str
    summary: str
    description: str
    domain: str
    intent: EndpointIntent
    tags: list[str] = Field(default_factory=list)
    parameters: list[ApiParameter] = Field(default_factory=list)
    request_body_schema: Any | None = None
    response_schema: Any | None = None
    security: list[str] = Field(default_factory=list)


class UasfSurface(BaseModel):
    source: str
    title: str
    version: str
    endpoints: list[UasfEndpoint] = Field(default_factory=list)
    auth_schemes: list[AuthScheme] = Field(default_factory=list)


class ToolDefinition(BaseModel):
    name: str
    description: str
    covered_endpoints: list[str] = Field(default_factory=list)
    input_schema: Any = Field(default_factory=dict)
    confidence: float = 0.0


class ToolPlan(BaseModel):
    tools: list[ToolDefinition] = Field(default_factory=list)
    endpoint_catalog: dict[str, UasfEndpoint] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class AnalysisSource(StrEnum):
    ANTHROPIC = "anthropic"
    OPEN_AI = "open_ai"
    VLLM = "vllm"
    SARVAM = "sarvam"
    MISTRAL = "mistral"
    GEMINI = "gemini"
    AWS_BEDROCK = "aws_bedrock"
    VERTEX_AI = "vertex_ai"
    HEURISTIC = "heuristic"


class AnalysisToolCandidate(BaseModel):
    name: str
    description: str
    covered_endpoints: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class AnalysisPlan(BaseModel):
    source: AnalysisSource
    model: str | None = None
    tools: list[AnalysisToolCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class QualityReport(BaseModel):
    score: int
    compression_ratio: float
    coverage: float
    description_clarity: float
    schema_completeness: float
    warnings: list[str] = Field(default_factory=list)
