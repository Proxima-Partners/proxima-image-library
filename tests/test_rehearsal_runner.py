from types import SimpleNamespace

import pytest

from scripts import rehearsal_runner as rehearsal
from scripts import release_azure_io as azure


@pytest.mark.parametrize("method,url", [
    ("PUT", azure.ARM + azure.APP_ID + "/sitecontainers/main?api-version=x"),
    ("POST", azure.ARM + azure.APP_ID + "/stop?api-version=x"),
    ("GET", azure.SCM["production"] + "/api/vfs/"),
    ("GET", azure.SCM["staging"] + "/api/vfs/"),
    ("GET", azure.STORAGE + "/rollback-backups/private"),
    ("PUT", azure.STORAGE + "/release-control/production.json?comp=lease"),
    ("PUT", azure.ARM + rehearsal.target.APP_ID + "/config/appsettings?api-version=x"),
    ("POST", rehearsal.target.SCM + "/api/command"),
    ("DELETE", azure.ARM + rehearsal.target.APP_ID + "?api-version=x"),
])
def test_physical_fence_blocks_live_targets_and_unneeded_rehearsal_writes(method, url):
    identity = SimpleNamespace(token=lambda _: pytest.fail("Must reject before credentials"))
    with pytest.raises(azure.AzureIOError):
        rehearsal.IsolatedTransport(identity=identity).request(method, url)


def test_runner_refuses_unapproved_context_before_network(monkeypatch):
    monkeypatch.delenv("IMAGE_LIBRARY_RECOVERY_REHEARSAL_ENABLED", raising=False)
    monkeypatch.setattr(rehearsal, "GitHubReads", lambda _: pytest.fail("No network permitted"))
    with pytest.raises(azure.AzureIOError): rehearsal.execute()


@pytest.mark.parametrize("key,value", [("authType", "UserCredentials"), ("isMain", False),
    ("targetPort", "80"), ("startUpCommand", "override"), ("environmentVariables", [{"name": "bad"}])])
def test_container_execution_overrides_rejected(key, value):
    props = {"image": rehearsal.target.PRIOR_IMAGE, "authType": "SystemIdentity", "isMain": True, "targetPort": "8080"}
    props[key] = value
    with pytest.raises(azure.AzureIOError): rehearsal.immutable_container({"properties": props})
