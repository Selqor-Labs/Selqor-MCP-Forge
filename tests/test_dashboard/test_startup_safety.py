# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: LicenseRef-Selqor-Attribution-Marketing-1.0

"""Tests for dashboard startup safety guards."""

from selqor_forge.dashboard.app import (
    _collect_local_dev_risks,
    _is_loopback_host,
    _print_local_dev_banner,
)
from selqor_forge.dashboard.secrets import DashboardSecretManager


def test_secret_manager_generates_state_dir_key(tmp_state_dir):
    manager = DashboardSecretManager.from_environment(tmp_state_dir)
    assert manager.auto_generated_this_run is True
    assert (tmp_state_dir / ".forge-secret.key").is_file()


def test_loopback_host_detection():
    assert _is_loopback_host("127.0.0.1") is True
    assert _is_loopback_host("localhost") is True
    assert _is_loopback_host("::1") is True
    assert _is_loopback_host("0.0.0.0") is False
    assert _is_loopback_host("192.168.1.15") is False


def test_collect_local_dev_risks_includes_banner_triggers(tmp_state_dir):
    manager = DashboardSecretManager.from_environment(tmp_state_dir)
    risks = _collect_local_dev_risks(
        bind_host="0.0.0.0",
        secret_manager=manager,
        cors_allow_origins=["*"],
    )
    assert risks["non_loopback_bind"] is True
    assert risks["placeholder_auth"] is True
    assert risks["auto_generated_secret_key"] is True
    assert risks["wildcard_cors"] is True


def test_print_local_dev_banner(capsys):
    _print_local_dev_banner(
        {
            "non_loopback_bind": True,
            "placeholder_auth": True,
            "auto_generated_secret_key": False,
            "wildcard_cors": True,
        }
    )
    captured = capsys.readouterr()
    assert "Dashboard running in LOCAL DEV mode." in captured.out
    assert "docs/AUTH_MODULE_INTEGRATION.md" in captured.out
