#!/usr/bin/env python3
"""Idempotent configuration copy to the approved pilot ONLY; never logs secrets.

Preserves existing destination settings and session keys. No production writes.
Explicit --apply is required. --callbacks adds only the two pilot callback URIs
to the existing registration after confirming its production callback identity.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

SUB = '9528fb58-4fa4-43f8-9940-e5c3e1f1903f'
RG = 'PP-Resources'
APP = 'pp-image-library'
SOURCE = 'PP-App-Serv'
PRODUCTION_CALLBACK = 'https://library.liveproxima.org/auth/callback'
COPY_KEYS = {
    'MSAL_CLIENT_ID', 'MSAL_CLIENT_SECRET', 'MSAL_TENANT_ID',
    'SHAREPOINT_CLIENT_ID', 'SHAREPOINT_CLIENT_SECRET', 'SHAREPOINT_TENANT_ID',
    'SHAREPOINT_DRIVE_ID', 'SHAREPOINT_SITE_ID', 'SHAREPOINT_IMAGE_FOLDER',
    'SHAREPOINT_LIST_NAME', 'MAINTENANCE_ADMIN_USERS',
    'APPLICATIONINSIGHTS_CONNECTION_STRING',
}
SAFE = {
    'APP_READ_ONLY': 'true', 'INGEST_POLLER_ENABLED': 'false',
    'TEST_MODE': 'false', 'DEV_AUTH_BYPASS': 'false', 'PORT': '8080',
    'WEBSITES_ENABLE_APP_SERVICE_STORAGE': 'true', 'APP_STATE_DIR': '/home',
    'TAG_LIBRARY_PATH': '/home/tag_library.json', 'SCM_DO_BUILD_DURING_DEPLOYMENT': 'false',
    'WEBSITE_WARMUP_PATH': '/readyz', 'WEBSITE_WARMUP_STATUSES': '200',
    'WEBSITE_SWAP_WARMUP_PING_PATH': '/readyz', 'WEBSITE_SWAP_WARMUP_PING_STATUSES': '200',
    'WEBSITE_HTTPLOGGING_RETENTION_DAYS': '7', 'PYTHON_DOTENV_DISABLED': '1',
    'SESSION_COOKIE_SECURE': 'true', 'SESSION_COOKIE_SAMESITE': 'Lax',
    'STORAGE_MODE': 'sharepoint', 'TELEMETRY_ENABLED': 'true',
}


def az(*args):
    # Capture stderr as well: Azure CLI errors can echo request bodies.
    result = subprocess.run(['az', *args, '--only-show-errors', '-o', 'json'],
                            capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError('Azure command failed (details withheld to protect settings): ' + ' '.join(args[:3]))
    return json.loads(result.stdout) if result.stdout.strip() else None


def settings(name, slot=None):
    args = ['webapp', 'config', 'appsettings', 'list', '-g', RG, '-n', name, '--subscription', SUB]
    if slot: args += ['--slot', slot]
    return {r['name']: r['value'] for r in az(*args)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--callbacks', action='store_true')
    args = parser.parse_args()
    if az('account', 'show')['id'] != SUB:
        raise RuntimeError('Wrong active subscription')
    source = settings(SOURCE)
    if source.get('MSAL_REDIRECT_URI') != PRODUCTION_CALLBACK:
        raise RuntimeError('Source callback identity differs')
    missing = COPY_KEYS - source.keys()
    if missing: raise RuntimeError('Missing required configuration keys: ' + ', '.join(sorted(missing)))
    registration = az('ad', 'app', 'show', '--id', source['MSAL_CLIENT_ID'])
    callbacks = registration['web']['redirectUris']
    if PRODUCTION_CALLBACK not in callbacks:
        raise RuntimeError('Intended registration does not contain production callback')
    destinations = []
    with tempfile.TemporaryDirectory(prefix='image-library-pilot-config-') as temp:
        for slot in [None, 'staging']:
            show_args = ['webapp', 'show', '-g', RG, '-n', APP, '--subscription', SUB]
            if slot: show_args += ['--slot', slot]
            site = az(*show_args)
            if site['appServicePlanId'].lower() != f'/subscriptions/{SUB}/resourcegroups/{RG}/providers/microsoft.web/serverfarms/asp-image-library-p2v3'.lower():
                raise RuntimeError('Unexpected pilot plan')
            host = site['defaultHostName']
            base = 'https://' + host
            merged = settings(APP, slot)
            for forbidden in ['WEBSITE_RUN_FROM_PACKAGE', 'WEBSITES_PORT', 'DOCKER_REGISTRY_SERVER_PASSWORD']:
                if forbidden in merged: raise RuntimeError('Conflicting legacy setting: ' + forbidden)
            merged.update({key: source[key] for key in COPY_KEYS})
            merged.update(SAFE)
            merged.update(APP_BASE_URL=base, MSAL_REDIRECT_URI=base + '/auth/callback', CORS_ORIGINS=base,
                          INGEST_OWNER_HOSTNAME='disabled-pilot')
            for key in ['FLASK_SECRET_KEY', 'MCP_INTERNAL_SECRET']:
                merged.setdefault(key, secrets.token_hex(32))
            path = Path(temp) / ((slot or 'production') + '.json')
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w') as stream: json.dump({'properties': merged}, stream)
            if args.apply:
                az('rest', '--method', 'put', '--url', 'https://management.azure.com' + site['id'] +
                   '/config/appsettings?api-version=2024-04-01', '--body', '@' + str(path))
                observed = settings(APP, slot)
                if any(observed.get(k) != v for k, v in merged.items()):
                    raise RuntimeError('Configuration verification failed')
            destinations.append({'slot': slot or 'production', 'host': host, 'settings_verified': args.apply})
        wanted = sorted(set(callbacks + ['https://' + d['host'] + '/auth/callback' for d in destinations]))
        if args.apply and args.callbacks and wanted != sorted(callbacks):
            body = Path(temp) / 'callbacks.json'
            body.write_text(json.dumps({'web': {'redirectUris': wanted}}))
            az('rest', '--method', 'patch', '--url', 'https://graph.microsoft.com/v1.0/applications/' + registration['id'],
               '--body', '@' + str(body))
            check = az('ad', 'app', 'show', '--id', source['MSAL_CLIENT_ID'])
            if sorted(check['web']['redirectUris']) != wanted:
                raise RuntimeError('Callback verification failed')
        print(json.dumps({'applied': args.apply, 'destinations': destinations,
                          'registration': registration['displayName'], 'callbacks_added': len(set(wanted) - set(callbacks)) if args.callbacks else 0,
                          'production_changed': False}))


if __name__ == '__main__':
    main()
