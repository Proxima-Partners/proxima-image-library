from types import SimpleNamespace

import pytest

from scripts import rehearsal_reconcile as recovery
from scripts import release_azure_io as azure


@pytest.mark.parametrize("method,url", [
    ("POST", azure.ARM + azure.APP_ID + "/start?api-version=2024-11-01"),
    ("POST", recovery.rehearsal.target.SCM + "/api/command"),
    ("GET", azure.SCM["production"] + "/api/vfs/proxima_deployment_drain"),
])
def test_diagnostic_scope_does_not_admit_production_or_shell(method, url):
    identity = SimpleNamespace(token=lambda _: pytest.fail("No credentials permitted"))
    with pytest.raises(azure.AzureIOError):
        recovery.DiagnosticTransport(identity=identity).request(method, url)


def test_only_exact_removed_runner_rule_is_normalized():
    rule = {"name": "rehearsal-ci-40065382842", "ipAddress": "20.51.199.49/32",
            "action": "Allow", "priority": 200}
    different = dict(rule, ipAddress="20.51.199.50/32")
    config = {"web": {"ipSecurityRestrictions": [rule, different],
                       "scmIpSecurityRestrictions": [rule]}}
    value = recovery.reviewed_configuration(config)
    assert value["web"]["ipSecurityRestrictions"] == [different]
    assert value["web"]["scmIpSecurityRestrictions"] == []
    assert config["web"]["scmIpSecurityRestrictions"] == [rule]


def test_deletion_request_does_not_prove_termination():
    data = b"Starting container: abc_pp-image-library-rehearsal_main.\nDeleting container: abc_pp-image-library-rehearsal_main.\n"
    assert recovery.active_containers(data) == {"abc_pp-image-library-rehearsal_main"}
    assert recovery.active_containers(data + b"Container is terminated.\n") == set()


def test_overlapping_runtimes_are_counted():
    data = b"Starting container: abc_pp-image-library-rehearsal_main.\nStarting container: def_pp-image-library-rehearsal_main.\n"
    assert len(recovery.active_containers(data)) == 2
    assert recovery.active_containers(data + b"Deleting container: abc_pp-image-library-rehearsal_main.\nContainer is terminated.\n") == {"def_pp-image-library-rehearsal_main"}


def test_ambiguous_termination_log_is_not_accepted():
    with pytest.raises(azure.AzureIOError):
        recovery.active_containers(b"Container is terminated.\n")
