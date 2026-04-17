# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the smarter heuristic grouping logic.

Covers: adaptive granularity, cross-domain workflows, agent intent filtering,
and intent affinity merging.
"""

from selqor_forge.config import AppConfig
from selqor_forge.models import (
    ApiParameter,
    EndpointIntent,
    UasfEndpoint,
    UasfSurface,
)
from selqor_forge.pipeline.analyze import heuristic_analysis
from selqor_forge.pipeline.curate import curate


def _ep(
    id: str,
    method: str,
    path: str,
    domain: str,
    intent: EndpointIntent,
    summary: str = "",
    tags: list[str] | None = None,
    parameters: list[ApiParameter] | None = None,
) -> UasfEndpoint:
    """Shorthand factory for test endpoints."""
    return UasfEndpoint(
        id=id,
        method=method,
        path=path,
        summary=summary,
        description="",
        domain=domain,
        intent=intent,
        tags=tags or [domain],
        parameters=parameters or [],
    )


def _surface(endpoints: list[UasfEndpoint]) -> UasfSurface:
    return UasfSurface(
        source="test",
        title="Test API",
        version="1.0",
        endpoints=endpoints,
    )


# ---------------------------------------------------------------------------
# Adaptive granularity: small domain → lifecycle tool
# ---------------------------------------------------------------------------


class TestSmallDomainLifecycle:
    """Domains with 1-4 endpoints should produce a single manage_{domain} tool."""

    def test_single_endpoint_domain(self):
        """A lone singleton domain creates a catch-all tool (no standalone 1-ep tools)."""
        surface = _surface([
            _ep("get_health", "GET", "/health", "health", EndpointIntent.READ),
        ])
        plan = heuristic_analysis(surface)
        non_custom = [t for t in plan.tools if "custom" not in t.name]
        assert len(non_custom) == 1
        assert "get_health" in non_custom[0].covered_endpoints

    def test_singleton_absorbed_when_peers_exist(self):
        """A 1-endpoint domain should merge into a nearby tool, not standalone."""
        surface = _surface([
            _ep("list_pets", "GET", "/pets", "pets", EndpointIntent.READ),
            _ep("create_pet", "POST", "/pets", "pets", EndpointIntent.CREATE),
            _ep("get_pet", "GET", "/pets/{id}", "pets", EndpointIntent.READ),
            _ep("get_health", "GET", "/health", "health", EndpointIntent.READ),
        ])
        plan = heuristic_analysis(surface)
        # health singleton should be absorbed, not get its own tool
        tool_names = [t.name for t in plan.tools]
        assert "manage_health" not in tool_names
        # But it should still be covered
        all_covered = set()
        for t in plan.tools:
            all_covered.update(t.covered_endpoints)
        assert "get_health" in all_covered

    def test_four_endpoint_crud_domain(self):
        surface = _surface([
            _ep("list_pets", "GET", "/pets", "pets", EndpointIntent.READ),
            _ep("create_pet", "POST", "/pets", "pets", EndpointIntent.CREATE),
            _ep("get_pet", "GET", "/pets/{id}", "pets", EndpointIntent.READ),
            _ep("delete_pet", "DELETE", "/pets/{id}", "pets", EndpointIntent.DELETE),
        ])
        plan = heuristic_analysis(surface)
        non_custom = [t for t in plan.tools if "custom" not in t.name]
        # 4 endpoints in one domain → single lifecycle tool
        assert len(non_custom) == 1
        assert "manage_pets" in non_custom[0].name
        assert len(non_custom[0].covered_endpoints) == 4


# ---------------------------------------------------------------------------
# Adaptive granularity: medium domain → intent split
# ---------------------------------------------------------------------------


class TestMediumDomainIntentSplit:
    """Domains with 5-12 endpoints should split by intent."""

    def test_splits_read_and_write(self):
        surface = _surface([
            _ep("list_users", "GET", "/users", "users", EndpointIntent.READ),
            _ep("get_user", "GET", "/users/{id}", "users", EndpointIntent.READ),
            _ep("search_users", "GET", "/users/search", "users", EndpointIntent.SEARCH),
            _ep("create_user", "POST", "/users", "users", EndpointIntent.CREATE),
            _ep("update_user", "PUT", "/users/{id}", "users", EndpointIntent.UPDATE),
            _ep("delete_user", "DELETE", "/users/{id}", "users", EndpointIntent.DELETE),
        ])
        plan = heuristic_analysis(surface)
        # Should have read and write groups, not 6 individual tools
        assert len(plan.tools) <= 3  # read, write (merged create+update+delete)
        # All endpoints covered
        all_covered = set()
        for t in plan.tools:
            all_covered.update(t.covered_endpoints)
        assert len(all_covered) == 6

    def test_tiny_intent_merges_by_affinity(self):
        """A single DELETE endpoint should merge into write, not read."""
        surface = _surface([
            _ep("list_orders", "GET", "/orders", "orders", EndpointIntent.READ),
            _ep("get_order", "GET", "/orders/{id}", "orders", EndpointIntent.READ),
            _ep("search_orders", "GET", "/orders/search", "orders", EndpointIntent.SEARCH),
            _ep("create_order", "POST", "/orders", "orders", EndpointIntent.CREATE),
            _ep("update_order", "PUT", "/orders/{id}", "orders", EndpointIntent.UPDATE),
            _ep("delete_order", "DELETE", "/orders/{id}", "orders", EndpointIntent.DELETE),
        ])
        plan = heuristic_analysis(surface)
        for tool in plan.tools:
            if "delete_order" in tool.covered_endpoints:
                # DELETE should be in a write-family tool, not a read tool
                assert "read" not in tool.name.lower(), (
                    f"DELETE endpoint should not be in read tool: {tool.name}"
                )
                break


# ---------------------------------------------------------------------------
# Cross-domain workflow detection
# ---------------------------------------------------------------------------


class TestCrossDomainWorkflows:
    """Endpoints sharing resources across domains should form workflow tools."""

    def test_no_workflow_for_single_domain(self):
        surface = _surface([
            _ep("list_pets", "GET", "/pets", "pets", EndpointIntent.READ),
            _ep("create_pet", "POST", "/pets", "pets", EndpointIntent.CREATE),
            _ep("get_pet", "GET", "/pets/{id}", "pets", EndpointIntent.READ),
        ])
        plan = heuristic_analysis(surface)
        workflow_tools = [t for t in plan.tools if "workflow" in t.name]
        assert len(workflow_tools) == 0

    def test_coverage_always_complete(self):
        """Every endpoint must be covered regardless of grouping strategy."""
        surface = _surface([
            _ep("list_pets", "GET", "/pets", "pets", EndpointIntent.READ),
            _ep("create_pet", "POST", "/pets", "pets", EndpointIntent.CREATE),
            _ep("get_pet", "GET", "/pets/{id}", "pets", EndpointIntent.READ),
            _ep("list_toys", "GET", "/toys", "toys", EndpointIntent.READ),
            _ep("create_toy", "POST", "/toys", "toys", EndpointIntent.CREATE),
        ])
        plan = heuristic_analysis(surface)
        all_covered = set()
        for t in plan.tools:
            all_covered.update(t.covered_endpoints)
        expected = {ep.id for ep in surface.endpoints}
        assert all_covered == expected


# ---------------------------------------------------------------------------
# Agent intent filtering
# ---------------------------------------------------------------------------


class TestAgentIntentFiltering:
    """Agent prompt should focus tools on relevant domains."""

    def test_agent_prompt_creates_core_tools(self):
        surface = _surface([
            _ep("list_pets", "GET", "/pets", "pets", EndpointIntent.READ,
                 summary="List all pets in the store"),
            _ep("create_pet", "POST", "/pets", "pets", EndpointIntent.CREATE,
                 summary="Add a new pet to the store"),
            _ep("get_pet", "GET", "/pets/{id}", "pets", EndpointIntent.READ,
                 summary="Find pet by ID"),
            _ep("list_users", "GET", "/users", "users", EndpointIntent.READ,
                 summary="List users"),
            _ep("get_logs", "GET", "/admin/logs", "admin", EndpointIntent.ADMIN,
                 summary="Get system logs"),
        ])
        plan = heuristic_analysis(surface, agent_prompt="manage pet inventory in the store")

        core_tools = [t for t in plan.tools if "core" in t.name.lower()]
        # Pet endpoints should be core (high relevance to "pet inventory")
        assert len(core_tools) >= 1
        # Core tools should have high confidence
        for t in core_tools:
            assert t.confidence >= 0.8

    def test_no_agent_prompt_gives_neutral_grouping(self):
        surface = _surface([
            _ep("list_a", "GET", "/a", "a", EndpointIntent.READ),
            _ep("list_b", "GET", "/b", "b", EndpointIntent.READ),
        ])
        plan = heuristic_analysis(surface)
        # No core/supporting prefixes without agent prompt
        for t in plan.tools:
            assert "core_" not in t.name
            assert "supporting_" not in t.name


# ---------------------------------------------------------------------------
# Full pipeline integration: heuristic → curate → score
# ---------------------------------------------------------------------------


class TestFullPipelineIntegration:
    """End-to-end tests ensuring the new heuristic works with curate + score."""

    def test_petstore_compression_improved(self):
        """Petstore-like API should produce ≤8 tools (was 12 before)."""
        surface = _surface([
            # Pet CRUD (8 endpoints — medium, splits by intent)
            _ep("addPet", "POST", "/pet", "pet", EndpointIntent.CREATE),
            _ep("updatePet", "PUT", "/pet", "pet", EndpointIntent.UPDATE),
            _ep("findByStatus", "GET", "/pet/findByStatus", "pet", EndpointIntent.SEARCH),
            _ep("findByTags", "GET", "/pet/findByTags", "pet", EndpointIntent.SEARCH),
            _ep("getPet", "GET", "/pet/{petId}", "pet", EndpointIntent.READ),
            _ep("updatePetForm", "POST", "/pet/{petId}", "pet", EndpointIntent.CREATE),
            _ep("deletePet", "DELETE", "/pet/{petId}", "pet", EndpointIntent.DELETE),
            _ep("uploadImage", "POST", "/pet/{petId}/uploadImage", "pet", EndpointIntent.CREATE),
            # Store CRUD (4 endpoints — small, lifecycle tool)
            _ep("getInventory", "GET", "/store/inventory", "store", EndpointIntent.READ),
            _ep("placeOrder", "POST", "/store/order", "store", EndpointIntent.CREATE),
            _ep("getOrder", "GET", "/store/order/{id}", "store", EndpointIntent.READ),
            _ep("deleteOrder", "DELETE", "/store/order/{id}", "store", EndpointIntent.DELETE),
            # User CRUD (7 endpoints — medium, splits by intent)
            _ep("createUser", "POST", "/user", "user", EndpointIntent.CREATE),
            _ep("createUsers", "POST", "/user/createWithList", "user", EndpointIntent.CREATE),
            _ep("loginUser", "GET", "/user/login", "user", EndpointIntent.READ),
            _ep("logoutUser", "GET", "/user/logout", "user", EndpointIntent.READ),
            _ep("getUser", "GET", "/user/{username}", "user", EndpointIntent.READ),
            _ep("updateUser", "PUT", "/user/{username}", "user", EndpointIntent.UPDATE),
            _ep("deleteUser", "DELETE", "/user/{username}", "user", EndpointIntent.DELETE),
        ])

        plan = heuristic_analysis(surface)
        config = AppConfig().with_anthropic_enabled(False)
        curated = curate(surface, config, plan)

        # Should be significantly fewer than the old 12 tools
        non_custom = [t for t in curated.tools if t.name != "custom_request"]
        assert len(non_custom) <= 8, f"Expected ≤8 tools, got {len(non_custom)}: {[t.name for t in non_custom]}"

        # Coverage must be 100%
        covered = set()
        for t in curated.tools:
            covered.update(t.covered_endpoints)
        assert covered >= {ep.id for ep in surface.endpoints}

    def test_single_domain_api_gets_lifecycle_tool(self):
        """A tiny 3-endpoint API should get a single manage_ tool."""
        surface = _surface([
            _ep("list", "GET", "/items", "items", EndpointIntent.READ),
            _ep("create", "POST", "/items", "items", EndpointIntent.CREATE),
            _ep("get", "GET", "/items/{id}", "items", EndpointIntent.READ),
        ])
        plan = heuristic_analysis(surface)
        config = AppConfig().with_anthropic_enabled(False)
        curated = curate(surface, config, plan)

        non_custom = [t for t in curated.tools if t.name != "custom_request"]
        assert any("manage_items" in t.name for t in non_custom), (
            f"Expected manage_items, got: {[t.name for t in non_custom]}"
        )
