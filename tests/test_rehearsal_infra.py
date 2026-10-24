from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts import rehearsal_infra as infra


class Fake:
    def __init__(self): self.calls = []
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert method == "GET"
        return 404, {}, b""
    def json(self, method, url, **kwargs):
        self.calls.append((method, url, deepcopy(kwargs)))
        if method == "GET":
            return {"id": infra.PLAN_ID, "sku": {"name": "P2v3", "capacity": 1}}
        if "/userAssignedIdentities/" in url:
            return {"properties": {"principalId": "b" * 32, "clientId": "c" * 32}}
        return {"identity": {"principalId": "a" * 32}}


def test_provision_only_exact_rehearsal_resources_and_no_provider_secrets():
    fake = Fake()
    result = infra.provision("8.8.4.4", "00000000-0000-0000-0000-000000000001", transport=fake)
    assert result["production_changed"] is False
    writes = [(url, args["body"]) for method, url, args in fake.calls if method == "PUT"]
    assert writes and all(any(x in url for x in (infra.APP_ID, infra.IDENTITY_ID,
        infra.CONTAINER_ID, infra.REGISTRY_ID, infra.PLAN_ID + "/providers/Microsoft.Authorization/")) for url, _ in writes)
    app = next(body for url, body in writes if url.startswith(infra.ARM + infra.APP_ID + "?"))
    config = app["properties"]["siteConfig"]
    assert config["ipSecurityRestrictionsDefaultAction"] == config["scmIpSecurityRestrictionsDefaultAction"] == "Deny"
    settings = {v["name"]: v["value"] for v in config["appSettings"]}
    assert len(settings["FLASK_SECRET_KEY"]) >= 32
    assert settings["TEST_MODE"] == settings["DEV_AUTH_BYPASS"] == settings["INGEST_POLLER_ENABLED"] == "false"
    assert not any("SHAREPOINT" in k or k.endswith("API_KEY") or k == "MSAL_CLIENT_SECRET" for k in settings)


def test_existing_name_stops_before_any_write():
    fake = Fake()
    fake.request = lambda *a, **k: (200, {}, b"{}")
    with pytest.raises(infra.AzureIOError):
        infra.provision("8.8.4.4", "00000000-0000-0000-0000-000000000001", transport=fake)
    assert not any(method == "PUT" for method, _, _ in fake.calls)


@pytest.mark.parametrize("address", ["0.0.0.0", "127.0.0.1", "10.0.0.1", "::1", "0.0.0.0/0"])
def test_invalid_or_broad_operator_address_never_uses_network(address):
    fake = Fake()
    with pytest.raises(ValueError):
        infra.provision(address, "00000000-0000-0000-0000-000000000001", transport=fake)
    assert fake.calls == []
