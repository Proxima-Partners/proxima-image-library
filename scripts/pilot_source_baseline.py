"""Same-plan source/Oryx comparison on the NEW app only, always read-only.

This is not the legacy production deployment. Keeps the container staging slot
intact, never copies catalog data, and never enables authentication bypass.
"""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from scripts.configure_container_pilot import az, settings, verify_pilot_site, SUB, RG, APP
from scripts.package_release import package_release


def main():
    started = time.monotonic()
    if az('account', 'show')['id'] != SUB:
        raise RuntimeError('Wrong subscription')
    site = az('webapp', 'show', '-g', RG, '-n', APP)
    verify_pilot_site(site)
    configured = settings(APP)
    for key, value in {'APP_READ_ONLY': 'true', 'INGEST_POLLER_ENABLED': 'false',
                       'TEST_MODE': 'false', 'DEV_AUTH_BYPASS': 'false'}.items():
        if configured.get(key) != value:
            raise RuntimeError('Unsafe source baseline setting: ' + key)
    if az('webapp', 'sitecontainers', 'list', '-g', RG, '-n', APP):
        raise RuntimeError('Source baseline refuses to replace an existing container')
    commit = os.environ['GITHUB_SHA']
    run_id, attempt = os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT']
    if not run_id.isdecimal() or not attempt.isdecimal():
        raise RuntimeError('Invalid workflow identity')
    with urlopen('https://api.ipify.org', timeout=15) as response:
        ip = str(ipaddress.IPv4Address(response.read().decode()))
    rule = 'pilot-source-ci-' + run_id + '-' + attempt
    report = {'target': site['id'], 'host': site['defaultHostName'], 'commit': commit,
              'src_tree': subprocess.check_output(['git', 'rev-parse', 'HEAD:src'], text=True).strip(),
              'status': 'failed', 'kind': 'source-oryx-same-plan-baseline'}
    Path('reports').mkdir(exist_ok=True)
    rule_added = False
    try:
        az('webapp', 'config', 'access-restriction', 'add', '-g', RG, '-n', APP,
           '--rule-name', rule, '--action', 'Allow', '--ip-address', ip + '/32', '--priority', '110')
        rule_added = True
        az('webapp', 'config', 'appsettings', 'set', '-g', RG, '-n', APP,
           '--settings', 'SCM_DO_BUILD_DURING_DEPLOYMENT=true', 'PORT=8000')
        # The existing app's src.app entrypoint and single-worker startup are
        # deliberate parity inputs, not Oryx's generic root-module defaults.
        az('webapp', 'config', 'set', '-g', RG, '-n', APP,
           '--linux-fx-version', 'PYTHON|3.12', '--startup-file', 'startup.sh')
        with tempfile.TemporaryDirectory(prefix='pilot-source-package-') as temp:
            archive = Path(temp) / 'source.zip'
            package_release(archive, commit=commit)
            report['archive_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
            deployment_started = time.monotonic()
            az('webapp', 'deploy', '-g', RG, '-n', APP, '--src-path', str(archive),
               '--type', 'zip', '--clean', 'false', '--async', 'true',
               '--track-status', 'false', '--timeout', '120000')
            report['upload_accepted_seconds'] = round(time.monotonic() - deployment_started, 2)
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            try:
                with urlopen('https://' + site['defaultHostName'] + '/readyz', timeout=15) as response:
                    ready = json.load(response)
                if ready.get('commit') == commit and ready.get('status') == 'ready' and ready.get('telemetry'):
                    if ready.get('version') != 'v2.0.0' or ready.get('build_id'):
                        raise RuntimeError('Expected source baseline identity')
                    report.update(status='ready', readiness=ready,
                                  source_deploy_seconds=round(time.monotonic() - deployment_started, 2),
                                  total_seconds=round(time.monotonic() - started, 2))
                    break
            except (HTTPError, URLError, TimeoutError, ValueError):
                pass
            time.sleep(10)
        else:
            raise RuntimeError('Source baseline readiness deadline exceeded; reconcile before retry')
    finally:
        if rule_added:
            az('webapp', 'config', 'access-restriction', 'remove', '-g', RG, '-n', APP, '--rule-name', rule)
            report['temporary_ci_access_removed'] = True
        Path('reports/pilot-source-baseline.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))


if __name__ == '__main__':
    main()
