"""Operator-only creation of the explicitly approved isolated rehearsal target.

No production settings are copied. No updates/adoption of pre-existing targets,
no retries, deletion, network broadening or production app mutation. Secret
material stays in memory. Runtime/provider read acceptance is not claimed here.
"""
import argparse
import ipaddress
import json
import secrets
import subprocess
import uuid

from scripts.configure_container_pilot import SUB, RG, PLAN_ID
from scripts.release_azure_io import ARM, STORAGE, AzureTransport, AzureIOError

BASE = f"/subscriptions/{SUB}/resourceGroups/{RG}"
APP_NAME = "pp-image-library-rehearsal"
APP_ID = BASE + "/providers/Microsoft.Web/sites/" + APP_NAME
IDENTITY_NAME = "id-image-library-rehearsal"
IDENTITY_ID = BASE + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/" + IDENTITY_NAME
REGISTRY_ID = BASE + "/providers/Microsoft.ContainerRegistry/registries/proximaimagelibrary"
CONTAINER_ID = BASE + "/providers/Microsoft.Storage/storageAccounts/pilrelease9528/blobServices/default/containers/ci-rehearsal"
SCM = "https://" + APP_NAME + ".scm.azurewebsites.net"
HOST = "https://" + APP_NAME + ".azurewebsites.net"
ENVIRONMENT = "image-library-recovery-rehearsal"
API = "2024-11-01"
PRIOR_IMAGE = "proximaimagelibrary.azurecr.io/image-library@sha256:1a1d24ede2eb7bfd81cb1ea2b11ea5518f0df5c4441dd714f2ef49ab5e1afa9a"


def create_only(transport, resource, body, version):
    url = ARM + resource + "?api-version=" + version
    status, _, _ = transport.request("GET", url, accepted=(200, 404))
    if status != 404:
        raise AzureIOError("Target already exists; inspect and reconcile instead of overwriting")
    return transport.json("PUT", url, body=body, accepted=(200, 201, 202), timeout=60)


def role(transport, scope, principal, role_id, *, condition=None, principal_type="ServicePrincipal"):
    name = str(uuid.uuid5(uuid.NAMESPACE_URL, scope + principal + role_id))
    properties = {"roleDefinitionId": f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/{role_id}",
                  "principalId": principal, "principalType": principal_type}
    if condition:
        properties.update(conditionVersion="2.0", condition=condition)
    create_only(transport, scope + "/providers/Microsoft.Authorization/roleAssignments/" + name,
                {"properties": properties}, "2022-04-01")


def provision(operator_ipv4, operator_object_id, *, transport=None):
    address = ipaddress.ip_address(operator_ipv4)
    if address.version != 4 or not address.is_global:
        raise ValueError("A global operator IPv4 address is required")
    uuid.UUID(operator_object_id)
    io = transport or AzureTransport()
    # Preflight the exact dedicated plan and all create-only names before writes.
    plan = io.json("GET", ARM + PLAN_ID + "?api-version=" + API)
    if plan["id"].lower() != PLAN_ID.lower() or plan["sku"]["name"] != "P2v3" or plan["sku"]["capacity"] != 1:
        raise AzureIOError("Dedicated one-instance P2v3 plan differs")
    for resource, version in ((APP_ID, API), (IDENTITY_ID, "2023-01-31"), (CONTAINER_ID, "2023-05-01")):
        status, _, _ = io.request("GET", ARM + resource + "?api-version=" + version, accepted=(200, 404))
        if status != 404:
            raise AzureIOError("Rehearsal target already exists; no adoption or re-provisioning")
    settings = {
        "FLASK_SECRET_KEY": secrets.token_hex(32), "APP_STATE_DIR": "/home",
        "TAG_LIBRARY_PATH": "/home/tag_library.json", "STORAGE_MODE": "local",
        "TEST_MODE": "false", "DEV_AUTH_BYPASS": "false", "TELEMETRY_ENABLED": "false",
        # Protocol uses production semantics, but the physical app is isolated.
        "TELEMETRY_SLOT": "production", "APP_READ_ONLY": "false",
        "INGEST_POLLER_ENABLED": "false", "PILOT_STATE_PROBE_ENABLED": "false",
        "PRODUCTION_RELEASE_CONTROL_ENABLED": "true", "PRODUCTION_RELEASE_RESUME_ENABLED": "true",
        "WEBSITES_ENABLE_APP_SERVICE_STORAGE": "true", "SCM_DO_BUILD_DURING_DEPLOYMENT": "false",
        "PYTHON_DOTENV_DISABLED": "1", "SESSION_COOKIE_SECURE": "true", "PORT": "8080",
        "APP_BASE_URL": HOST, "MSAL_REDIRECT_URI": HOST + "/auth/callback",
        "WEBSITE_WARMUP_PATH": "/readyz", "WEBSITE_WARMUP_STATUSES": "200",
    }
    restrictions = [{"name": "rehearsal-operator", "ipAddress": str(address) + "/32", "action": "Allow", "priority": 100}]
    app = create_only(io, APP_ID, {"location": "westus2", "kind": "app,linux",
        "tags": {"application": "image-library", "purpose": "isolated-recovery-rehearsal", "synthetic-data-only": "true"},
        "identity": {"type": "SystemAssigned"}, "properties": {"serverFarmId": PLAN_ID,
            "httpsOnly": True, "publicNetworkAccess": "Enabled", "clientCertEnabled": False,
            "siteConfig": {"linuxFxVersion": "sitecontainers", "alwaysOn": True, "ftpsState": "Disabled",
                "minTlsVersion": "1.2", "scmMinTlsVersion": "1.2", "healthCheckPath": "/readyz",
                "ipSecurityRestrictions": restrictions, "ipSecurityRestrictionsDefaultAction": "Deny",
                "scmIpSecurityRestrictions": restrictions, "scmIpSecurityRestrictionsDefaultAction": "Deny",
                "scmIpSecurityRestrictionsUseMain": False,
                "appSettings": [{"name": k, "value": v} for k, v in settings.items()]}}}, API)
    principal = app["identity"]["principalId"]
    identity = create_only(io, IDENTITY_ID, {"location": "westus2",
        "tags": {"application": "image-library", "purpose": "isolated-recovery-rehearsal"}}, "2023-01-31")
    identity = identity["properties"]
    create_only(io, IDENTITY_ID + "/federatedIdentityCredentials/github-recovery-rehearsal", {"properties": {
        "issuer": "https://token.actions.githubusercontent.com",
        "subject": "repo:Proxima-Partners/proxima-image-library:environment:" + ENVIRONMENT,
        "audiences": ["api://AzureADTokenExchange"]}}, "2023-01-31")
    create_only(io, CONTAINER_ID, {"properties": {"publicAccess": "None"}}, "2023-05-01")
    role(io, APP_ID, identity["principalId"], "de139f84-1756-47ae-9be6-808fbbe84772")
    role(io, PLAN_ID, identity["principalId"], "acdd72a7-3385-48ef-bd42-f606fba81ae7")
    role(io, CONTAINER_ID, identity["principalId"], "ba92f5b4-2d11-453d-a403-e96b0029c9fe")
    role(io, CONTAINER_ID, operator_object_id, "ba92f5b4-2d11-453d-a403-e96b0029c9fe", principal_type="User")
    role(io, REGISTRY_ID, principal, "b93aa761-3e63-49ed-ac28-beffa264f7ac", condition=
         "((!(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/content/read'}) AND "
         "!(ActionMatches{'Microsoft.ContainerRegistry/registries/repositories/metadata/read'})) OR "
         "(@Request[Microsoft.ContainerRegistry/registries/repositories:name] StringEquals 'image-library'))")
    create_only(io, APP_ID + "/sitecontainers/main", {"properties": {
        "image": PRIOR_IMAGE, "targetPort": "8080", "isMain": True, "authType": "SystemIdentity"}}, API)
    return {"status": "provisioned_not_accepted", "app": APP_NAME, "identity": IDENTITY_NAME,
            "client_id": identity["clientId"], "principal_id": identity["principalId"],
            "provider_credentials_copied": False, "production_changed": False}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--operator-ipv4", required=True)
    p.add_argument("--apply", action="store_true", required=True)
    args = p.parse_args()
    try:
        operator = subprocess.run(["az", "ad", "signed-in-user", "show", "--query", "id", "-o", "tsv"],
                                  capture_output=True, text=True, check=True, timeout=30).stdout.strip()
        print(json.dumps(provision(args.operator_ipv4, operator)))
    except Exception:
        print(json.dumps({"status": "stopped", "reason": "reconcile_exact_rehearsal_resources_no_retry"}))
        raise SystemExit(1)
