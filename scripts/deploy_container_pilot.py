"""Deploy only the approved read-only staging slot; temporary CI IP access is removed.

No legacy app, DNS, settings, promotion or catalog mutation. This is a readiness
gate, not a claim that SSO, telemetry ingestion and rollback acceptance passed.
"""
import json
import os
from pathlib import Path
import re
import time
from urllib.request import urlopen, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from scripts.configure_container_pilot import az, settings, verify_pilot_site, SUB, RG, APP


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def main():
    started = time.monotonic()
    image = os.environ['RELEASE_IMAGE']
    if not re.fullmatch(r'proximaimagelibrary\.azurecr\.io/image-library@sha256:[0-9a-f]{64}', image):
        raise RuntimeError('Unexpected image target')
    if az('account', 'show')['id'] != SUB: raise RuntimeError('Wrong subscription')
    site = az('webapp', 'show', '-g', RG, '-n', APP, '--slot', 'staging')
    verify_pilot_site(site, 'staging')
    configured = settings(APP, 'staging')
    for k, v in {'APP_READ_ONLY': 'true', 'INGEST_POLLER_ENABLED': 'false', 'TEST_MODE': 'false',
                 'DEV_AUTH_BYPASS': 'false', 'WEBSITES_ENABLE_APP_SERVICE_STORAGE': 'true'}.items():
        if configured.get(k) != v: raise RuntimeError('Unsafe pilot setting: ' + k)
    with urlopen('https://api.ipify.org', timeout=15) as response:
        ip = response.read().decode()
    import ipaddress
    ipaddress.IPv4Address(ip)
    run_id = os.environ['GITHUB_RUN_ID']
    attempt = os.environ['GITHUB_RUN_ATTEMPT']
    if not run_id.isdecimal() or not attempt.isdecimal(): raise RuntimeError('Invalid run identity')
    rule = 'pilot-ci-' + run_id + '-' + attempt
    output = {'image': image, 'host': site['defaultHostName'], 'slot': 'staging', 'status': 'failed'}
    Path('reports').mkdir(exist_ok=True)
    rule_added = False
    try:
        az('webapp', 'config', 'access-restriction', 'add', '-g', RG, '-n', APP, '--slot', 'staging',
           '--rule-name', rule, '--action', 'Allow', '--ip-address', ip + '/32', '--priority', '110')
        rule_added = True
        az('webapp', 'sitecontainers', 'create', '-g', RG, '-n', APP, '--slot', 'staging',
           '--container-name', 'main', '--image', image, '--target-port', '8080', '--is-main', 'true',
           '--system-assigned-identity', 'true')
        deadline = time.monotonic() + 600
        base = 'https://' + site['defaultHostName']
        while time.monotonic() < deadline:
            try:
                with urlopen(base + '/readyz', timeout=15) as response: ready = json.load(response)
                if ready.get('commit') == os.environ['GITHUB_SHA'] and ready.get('build_id') == run_id + '-' + attempt:
                    if ready.get('version') != 'v2.0.0' or ready.get('status') != 'ready' or not ready.get('telemetry'):
                        raise RuntimeError('Readiness contract failed')
                    break
            except (HTTPError, URLError, TimeoutError, ValueError):
                pass
            time.sleep(10)
        else: raise RuntimeError('Exact image not ready within 600 seconds')
        try:
            build_opener(NoRedirect).open(base + '/', timeout=15)
            raise RuntimeError('Anonymous catalog access unexpectedly allowed')
        except HTTPError as exc:
            if exc.code != 302 or not exc.headers.get('Location', '').endswith('/login'):
                raise RuntimeError('Authentication redirect failed') from None
        observed = az('webapp', 'sitecontainers', 'list', '-g', RG, '-n', APP, '--slot', 'staging')
        if not any(r.get('properties', r).get('image') == image for r in observed):
            raise RuntimeError('Configured digest verification failed')
        output.update(status='ready', readiness=ready, elapsed_seconds=round(time.monotonic() - started, 2))
    finally:
        if rule_added:
            az('webapp', 'config', 'access-restriction', 'remove', '-g', RG, '-n', APP, '--slot', 'staging', '--rule-name', rule)
            output['temporary_ci_access_removed'] = True
        Path('reports/pilot-readiness.json').write_text(json.dumps(output, indent=2) + '\n')
        print(json.dumps(output))


if __name__ == '__main__':
    main()
