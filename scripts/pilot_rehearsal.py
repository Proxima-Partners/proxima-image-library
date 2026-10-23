"""Explicit, bounded recovery rehearsals on pp-image-library ONLY.

Run after CI deployments finish. Every operation checkpoints before mutation;
an existing report is never reused to blindly repeat a restart or swap.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, build_opener

from scripts.configure_container_pilot import az, settings, verify_pilot_site, APP, RG, SUB
from scripts.deploy_container_pilot import NoRedirect

IMAGE_PATTERN = r'proximaimagelibrary\.azurecr\.io/image-library@sha256:[a-f0-9]{64}'


def slot_args(slot):
    if slot not in ('production', 'staging'):
        raise ValueError('Only the two approved pilot slots are allowed')
    return ['-g', RG, '-n', APP] + (['--slot', 'staging'] if slot == 'staging' else [])


def read_ready(host):
    try:
        with urlopen('https://' + host + '/readyz', timeout=10) as response:
            data = json.load(response)
        return data if data.get('status') == 'ready' else None
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None


def capture(slot):
    site = az('webapp', 'show', *slot_args(slot))
    verify_pilot_site(site, 'staging' if slot == 'staging' else None)
    config = settings(APP, 'staging' if slot == 'staging' else None)
    required = {'APP_READ_ONLY': 'true', 'INGEST_POLLER_ENABLED': 'false',
                'TEST_MODE': 'false', 'DEV_AUTH_BYPASS': 'false',
                'PILOT_STATE_PROBE_ENABLED': 'true', 'WEBSITES_ENABLE_APP_SERVICE_STORAGE': 'true'}
    if any(config.get(key) != value for key, value in required.items()):
        raise RuntimeError('Unsafe pilot configuration')
    containers = az('webapp', 'sitecontainers', 'list', *slot_args(slot))
    mains = [c.get('properties', c) for c in containers if c.get('properties', c).get('isMain')]
    if len(mains) > 1:
        raise RuntimeError('Ambiguous main container')
    image = mains[0]['image'] if mains else None
    if image and not re.fullmatch(IMAGE_PATTERN, image):
        raise RuntimeError('Unexpected pilot image')
    return {'resource': site['id'], 'host': site['defaultHostName'], 'image': image,
            'readiness': read_ready(site['defaultHostName']), 'safe_settings': required}


def load_release(path):
    data = json.loads(Path(path).read_text())
    if data.get('status') != 'pass' or not re.fullmatch(IMAGE_PATTERN, data.get('registry_image', '')):
        raise ValueError('A passing immutable pilot release receipt is required')
    if datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00')) <= datetime.now(timezone.utc):
        raise ValueError('Release applicability review expired')
    if not re.fullmatch(r'[0-9a-f]{40}', data.get('commit', '')) or not data.get('build_id'):
        raise ValueError('Release identity is missing')
    return data


def deploy_digest(slot, image):
    if not re.fullmatch(IMAGE_PATTERN, image):
        raise ValueError('Immutable pilot image required')
    az('webapp', 'sitecontainers', 'create', *slot_args(slot), '--container-name', 'main',
       '--image', image, '--target-port', '8080', '--is-main', 'true', '--system-assigned-identity', 'true')


def verify_ready(slot, expected, state_id, *, fresh_boot=None, seconds=600):
    started = time.monotonic()
    host = expected['host']
    while time.monotonic() - started < seconds:
        ready = read_ready(host)
        if ready and ready.get('commit') == expected['commit'] and ready.get('build_id') == expected['build_id']:
            state = ready.get('pilot_state', {})
            if state.get('state_id') != state_id or state.get('uid') != 65532 or state.get('gid') != 65532:
                raise RuntimeError('Persistent state or nonroot identity changed')
            if fresh_boot and state.get('boot_id') == fresh_boot:
                time.sleep(5)
                continue
            if not ready.get('telemetry') or ready.get('version') != 'v2.0.0':
                raise RuntimeError('Readiness contract failed')
            observed = capture(slot)
            if observed['image'] != expected['image']:
                raise RuntimeError('Configured image differs from expected digest')
            try:
                build_opener(NoRedirect).open('https://' + host + '/', timeout=10)
                raise RuntimeError('Authentication unexpectedly bypassed')
            except HTTPError as exc:
                if exc.code != 302 or not exc.headers.get('Location', '').endswith('/login'):
                    raise RuntimeError('Authentication redirect failed') from None
            return observed
        time.sleep(5)
    raise RuntimeError('Recovery deadline exceeded; reconcile before any further action')


def expected_from(snapshot):
    if not snapshot['image'] or not snapshot['readiness']:
        raise RuntimeError('A healthy container is required for this rehearsal')
    return dict(snapshot['readiness'], host=snapshot['host'], image=snapshot['image'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['restart', 'seed-main', 'swap', 'restore-swap', 'failed-readiness', 'failed-pull'])
    parser.add_argument('--release', help='Downloaded passing CI release.json; required for seed/swap')
    parser.add_argument('--checkpoint', type=Path, help='Failed completed-swap report to restore exactly')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise RuntimeError('Report already exists; reconcile recorded state instead of repeating operation')
    if az('account', 'show')['id'] != SUB:
        raise RuntimeError('Wrong subscription')
    runs = json.loads(subprocess.check_output(['gh', 'run', 'list', '--branch', 'perf/container-pilot',
        '--limit', '20', '--json', 'workflowName,status'], text=True))
    if any(r['status'] != 'completed' and r['workflowName'] in {
        'Deploy isolated Image Library pilot', 'Compare isolated pilot source baseline'} for r in runs):
        raise RuntimeError('Wait for the serialized CI deployment to finish')
    before = {slot: capture(slot) for slot in ('production', 'staging')}
    report = {'action': args.action, 'before': before, 'status': 'started',
              'started_at': datetime.now(timezone.utc).isoformat()}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x') as stream: json.dump(report, stream, indent=2)
    started = time.monotonic()
    try:
        if args.action == 'seed-main':
            release = load_release(args.release)
            prior = before['production']['readiness']
            if not prior or not prior.get('pilot_state'):
                raise RuntimeError('Complete source baseline/state verification before seeding')
            az('webapp', 'config', 'set', *slot_args('production'),
               '--linux-fx-version', 'sitecontainers', '--startup-file', '')
            # Runtime conversions may remove container-specific settings.
            # Reassert persistence AFTER switching modes, before starting image.
            az('webapp', 'config', 'appsettings', 'set', *slot_args('production'),
               '--settings', 'SCM_DO_BUILD_DURING_DEPLOYMENT=false', 'PORT=8080',
               'WEBSITES_ENABLE_APP_SERVICE_STORAGE=true',
               '--slot-settings', 'PILOT_STATE_PROBE_ENABLED=true')
            deploy_digest('production', release['registry_image'])
            expected = dict(release, host=before['production']['host'], image=release['registry_image'])
            report['verified'] = verify_ready('production', expected, prior['pilot_state']['state_id'])
        elif args.action == 'restart':
            expected = expected_from(before['staging'])
            az('webapp', 'restart', *slot_args('staging'))
            report['verified'] = verify_ready('staging', expected, expected['pilot_state']['state_id'],
                                              fresh_boot=expected['pilot_state']['boot_id'])
        elif args.action == 'restore-swap':
            checkpoint = json.loads(args.checkpoint.read_text())
            if checkpoint.get('action') != 'swap' or checkpoint.get('status') != 'failed':
                raise RuntimeError('An inspected failed-swap checkpoint is required')
            original = checkpoint['before']
            for current, prior in [('production', 'staging'), ('staging', 'production')]:
                if before[current]['image'] != original[prior]['image']:
                    raise RuntimeError('Current images do not match the confirmed completed swap')
            az('webapp', 'deployment', 'slot', 'swap', *slot_args('staging'), '--target-slot', 'production')
            report['verified'] = {slot: verify_ready(slot, expected_from(original[slot]),
                original[slot]['readiness']['pilot_state']['state_id']) for slot in ('production', 'staging')}
            report['restored_checkpoint'] = str(args.checkpoint)
            report['original_swap_gate_still_failed'] = True
        elif args.action == 'swap':
            release = load_release(args.release)
            main, staging = expected_from(before['production']), expected_from(before['staging'])
            if staging['image'] != release['registry_image'] or staging['build_id'] != release['build_id']:
                raise RuntimeError('Staging does not hold the explicitly requested promotion/rollback digest')
            if main['image'] == staging['image']:
                raise RuntimeError('Distinct images are required to prove a swap')
            az('webapp', 'deployment', 'slot', 'swap', *slot_args('staging'), '--target-slot', 'production')
            report['verified'] = {
                'production': verify_ready('production', dict(staging, host=main['host']), main['pilot_state']['state_id']),
                'staging': verify_ready('staging', dict(main, host=staging['host']), staging['pilot_state']['state_id']),
            }
        else:
            stable, expected = expected_from(before['production']), expected_from(before['staging'])
            try:
                if args.action == 'failed-readiness':
                    az('webapp', 'config', 'appsettings', 'set', *slot_args('staging'), '--settings', 'PORT=0')
                    deadline = time.monotonic() + 180
                    while time.monotonic() < deadline:
                        if read_ready(expected['host']) is None:
                            report['rejected_unready_candidate'] = True
                            break
                        time.sleep(5)
                    else: raise RuntimeError('Failed-readiness injection was not observed')
                else:
                    bad_image = 'proximaimagelibrary.azurecr.io/image-library@sha256:' + '0' * 64
                    deploy_digest('staging', bad_image)
                    deadline = time.monotonic() + 240
                    while time.monotonic() < deadline:
                        status = az('webapp', 'sitecontainers', 'status', *slot_args('staging'), '--container-name', 'main')
                        reason = str(status.get('TerminationReason', ''))
                        if 'pull' in reason.lower() or 'image' in reason.lower():
                            report['rejected_image_pull'] = {k: status.get(k) for k in ('Status', 'Image', 'TerminationReason')}
                            break
                        time.sleep(10)
                    else: raise RuntimeError('Failed-pull reason was not confirmed; candidate is not accepted')
                report['unchanged_main'] = verify_ready('production', stable, stable['pilot_state']['state_id'])
            finally:
                # Exactly one restoration, never alternate between candidates.
                report['recovery_attempts'] = 1
                if args.action == 'failed-readiness':
                    az('webapp', 'config', 'appsettings', 'set', *slot_args('staging'), '--settings', 'PORT=8080')
                else:
                    deploy_digest('staging', expected['image'])
                report['recovered'] = verify_ready('staging', expected, expected['pilot_state']['state_id'])
        report.update(status='passed', operation_seconds=round(time.monotonic() - started, 2))
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        args.report.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'action': args.action, 'status': report['status'], 'report': str(args.report),
                          'operation_seconds': report.get('operation_seconds')}))


if __name__ == '__main__':
    main()
