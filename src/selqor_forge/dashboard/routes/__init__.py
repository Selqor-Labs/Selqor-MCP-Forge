# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Dashboard API route routers."""

from fastapi import APIRouter

from selqor_forge.dashboard.routes import (
    auth_routes,
    cicd,
    compliance,
    dashboard_api,
    integration_auth,
    integration_deploy,
    integration_runs,
    integration_tooling,
    integrations,
    llm_configs,
    llm_test,
    monitoring,
    notifications,
    org_routes,
    playground,
    registry,
    remediation,
    reports,
    run_jobs,
    scanner,
    settings,
    versions,
)

api_router = APIRouter()

api_router.include_router(dashboard_api.router, tags=["dashboard"])
api_router.include_router(integrations.router, tags=["integrations"])
api_router.include_router(integration_runs.router, tags=["integration-runs"])
api_router.include_router(integration_tooling.router, tags=["integration-tooling"])
api_router.include_router(integration_auth.router, tags=["integration-auth"])
api_router.include_router(integration_deploy.router, tags=["integration-deploy"])
api_router.include_router(llm_configs.router, tags=["llm-configs"])
api_router.include_router(llm_test.router, tags=["llm-test"])
api_router.include_router(auth_routes.router, tags=["auth"])
api_router.include_router(org_routes.router, tags=["organizations"])
api_router.include_router(run_jobs.router, tags=["run-jobs"])
api_router.include_router(reports.router, tags=["reports"])
api_router.include_router(scanner.router, tags=["scans"])
api_router.include_router(playground.router, tags=["playground"])
api_router.include_router(remediation.router, tags=["remediation"])
api_router.include_router(cicd.router, tags=["cicd"])
api_router.include_router(registry.router, tags=["registry"])
api_router.include_router(versions.router, tags=["versions"])
api_router.include_router(monitoring.router, tags=["monitoring"])
api_router.include_router(compliance.router, tags=["compliance"])
api_router.include_router(settings.router, tags=["settings"])
api_router.include_router(notifications.router, tags=["notifications"])

__all__ = ["api_router"]
