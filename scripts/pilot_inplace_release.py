"""Checkpointed staging -> main digest updates on the isolated pilot only.

Never swap slots or copy settings. Preserve all settings (including credentials)
in memory for comparison, never in reports. One rollback is allowed only after
an acknowledged update and a reconciled candidate configuration. Ambiguous
control-plane errors stop without another mutation. Re-running an existing
checkpoint is deliberately refused; inspect it and live state first.
"""
import argparse
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.request import urlopen

from scripts.configure_container_pilot import az, settings, APP, SUB
from scripts.pilot_rehearsal import (
    IMAGE_PATTERN, capture, expected_from, load_release, read_ready,
    slot_args, verify_ready,
)

REPO = 'Proxima-Partners/proxima-image-library'


def checkpoint(path, report):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, indent=2) + '\n')
    temporary.replace(path)


def receipt_matches(release, snapshot):
    expected = expected_from(snapshot)
    if any(release.get(key) != expected.get(target) for key, target in (
        ('registry_image', 'image'), ('commit', 'commit'), ('build_id', 'build_id')
    )):
        raise RuntimeError('Release receipt does not match the observed exact image/build')


def download_receipt(build_id, destination):
    if not re.fullmatch(r'[0-9]+-[0-9]+', build_id):
        raise ValueError('Invalid CI build identity')
    run_id, _ = build_id.split('-')
    subprocess.run(['gh', 'run', 'download', run_id, '--repo', REPO,
                    '--name', 'pilot-build-' + build_id, '--dir', str(destination)],
                   check=True, capture_output=True, timeout=90)
    return load_release(destination / 'release.json')


def protected_configuration(slot):
    containers = az('webapp', 'sitecontainers', 'list', *slot_args(slot))
    if len(containers) != 1:
        raise RuntimeError('Expected exactly one pilot container')
    container = dict(containers[0].get('properties', containers[0]))
    if (not container.get('isMain') or container.get('authType') != 'SystemIdentity' or
            str(container.get('targetPort')) != '8080' or container.get('startUpCommand') or
            container.get('environmentVariables') or container.get('volumeMounts')):
        raise RuntimeError('Unexpected container identity/configuration')
    container.pop('image', None)
    # Azure updates this audit timestamp on every successful image update.
    # It is not configuration; all other properties remain compared.
    container.pop('lastModifiedTime', None)
    return {'settings': settings(APP, 'staging' if slot == 'staging' else None),
            'container': container}


def update_digest(slot, image):
    if not re.fullmatch(IMAGE_PATTERN, image):
        raise ValueError('An immutable approved-repository image is required')
    # CLI update preserves the existing object but resets an omitted port in
    # some versions. Reassert the already-verified port, changing only the image.
    az('webapp', 'sitecontainers', 'update', *slot_args(slot),
       '--container-name', 'main', '--image', image, '--target-port', '8080')


def update_slot(slot, release, prior_release, report, path):
    before = capture(slot)
    receipt_matches(prior_release, before)
    prior = expected_from(before)
    state_id = prior['pilot_state']['state_id']
    original_config = protected_configuration(slot)
    operation = {'slot': slot, 'before': before, 'candidate_image': release['registry_image'],
                 'status': 'checkpointed', 'rollback_attempts': 0}
    report.setdefault('operations', []).append(operation)
    checkpoint(path, report)
    expected = dict(release, image=release['registry_image'], host=before['host'])
    if before['image'] == release['registry_image']:
        operation.update(status='already_verified', after=verify_ready(slot, expected, state_id))
        checkpoint(path, report)
        return
    started = time.monotonic()
    operation['status'] = 'update_submitted'
    checkpoint(path, report)
    try:
        update_digest(slot, release['registry_image'])
    except Exception:
        operation['status'] = 'ambiguous_control_plane_result_manual_reconciliation_required'
        # Never retry or rollback an unacknowledged operation, including timeout.
        checkpoint(path, report)
        raise RuntimeError('Update result ambiguous; no automatic retry or rollback') from None
    operation['status'] = 'update_acknowledged'
    checkpoint(path, report)
    try:
        after = verify_ready(slot, expected, state_id)
        if protected_configuration(slot) != original_config:
            raise RuntimeError('Protected configuration changed')
        operation.update(status='passed', after=after, settings_and_credentials_unchanged=True,
                         rollout_seconds=round(time.monotonic() - started, 2))
    except Exception as exc:
        operation.update(status='verification_failed', error_type=type(exc).__name__)
        checkpoint(path, report)
        current = capture(slot)
        if current['image'] != release['registry_image'] or protected_configuration(slot) != original_config:
            operation['status'] = 'reconciliation_required_no_rollback'
            checkpoint(path, report)
            raise RuntimeError('Candidate/configuration changed; no automatic rollback') from None
        operation.update(status='rollback_submitted', rollback_attempts=1)
        checkpoint(path, report)
        recovery_started = time.monotonic()
        try:
            update_digest(slot, prior['image'])
            recovered = verify_ready(slot, prior, state_id)
            if protected_configuration(slot) != original_config:
                raise RuntimeError('Protected configuration changed during recovery')
            operation.update(status='rolled_back', recovered=recovered,
                             settings_and_credentials_unchanged=True,
                             recovery_seconds=round(time.monotonic() - recovery_started, 2))
        except Exception:
            operation['status'] = 'recovery_failed_manual_reconciliation_required'
            checkpoint(path, report)
            raise RuntimeError('The single recovery failed; further mutations stopped') from None
        checkpoint(path, report)
        raise RuntimeError('Candidate failed verification; previous approved image restored once') from None
    checkpoint(path, report)


def remove_access(slot, rule):
    az('webapp', 'config', 'access-restriction', 'remove', *slot_args(slot), '--rule-name', rule)
    observed = az('webapp', 'config', 'access-restriction', 'show', *slot_args(slot))
    if any(row.get('name') == rule for row in observed.get('ipSecurityRestrictions', [])):
        raise RuntimeError('Temporary CI access still present')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--main-only', action='store_true', help='Local rehearsal: require this digest already healthy in staging')
    args = parser.parse_args()
    if args.report.exists():
        raise RuntimeError('Existing checkpoint: reconcile live state instead of repeating the release')
    release = load_release(args.release)
    if az('account', 'show')['id'] != SUB:
        raise RuntimeError('Wrong subscription')
    is_ci = os.environ.get('GITHUB_ACTIONS') == 'true'
    if is_ci and (release['commit'] != os.environ['GITHUB_SHA'] or
                  release['build_id'] != os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT'] or
                  release['registry_image'] != os.environ['RELEASE_IMAGE']):
        raise RuntimeError('Release receipt is not this CI build')
    if not is_ci:
        runs = json.loads(subprocess.check_output(['gh', 'run', 'list', '--repo', REPO,
            '--branch', 'perf/container-pilot', '--limit', '20', '--json', 'workflowName,status'], text=True))
        if any(r['status'] != 'completed' and r['workflowName'] in {
            'Deploy isolated Image Library pilot', 'Compare isolated pilot source baseline'} for r in runs):
            raise RuntimeError('A CI deployment is active; wait before a local rehearsal')
    report = {'status': 'started', 'started_at': datetime.now(timezone.utc).isoformat(),
              'release': release, 'strategy': 'in-place-no-swap', 'temporary_access_removed': {}}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x') as stream: json.dump(report, stream, indent=2)
    started = time.monotonic()
    rules = []
    try:
        if is_ci:
            with urlopen('https://api.ipify.org', timeout=15) as response:
                ip = str(ipaddress.IPv4Address(response.read().decode()))
            rule = 'pilot-ci-' + release['build_id']
            for slot in ('staging', 'production'):
                # Remember even a failed add; cleanup must reconcile partial success.
                rules.append((slot, rule))
                az('webapp', 'config', 'access-restriction', 'add', *slot_args(slot),
                   '--rule-name', rule, '--action', 'Allow', '--ip-address', ip + '/32', '--priority', '110')
        before = {slot: capture(slot) for slot in ('staging', 'production')}
        for snapshot in before.values():
            deadline = time.monotonic() + 45
            while not snapshot['readiness'] and time.monotonic() < deadline:
                time.sleep(3)
                snapshot['readiness'] = read_ready(snapshot['host'])
            expected_from(snapshot)  # Fail closed if either prior image/state is unknown.
        report['before'] = before
        checkpoint(args.report, report)
        with tempfile.TemporaryDirectory(prefix='pilot-release-receipts-') as directory:
            priors = {slot: download_receipt(snapshot['readiness']['build_id'], Path(directory) / slot)
                      for slot, snapshot in before.items()}
            for slot in priors:
                receipt_matches(priors[slot], before[slot])
            if args.main_only:
                receipt_matches(release, before['staging'])
            else:
                update_slot('staging', release, priors['staging'], report, args.report)
            staging = capture('staging')
            receipt_matches(release, staging)
            verify_ready('staging', expected_from(staging), before['staging']['readiness']['pilot_state']['state_id'])
            report['staging_gate_passed'] = True
            checkpoint(args.report, report)
            update_slot('production', release, priors['production'], report, args.report)
        report['status'] = 'passed'
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        cleanup_failed = False
        for slot, rule in rules:
            try:
                remove_access(slot, rule)
                report['temporary_access_removed'][slot] = True
            except Exception:
                report['temporary_access_removed'][slot] = False
                report['status'] = 'failed'
                cleanup_failed = True
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)
        checkpoint(args.report, report)
        print(json.dumps({'status': report['status'], 'report': str(args.report),
                          'elapsed_seconds': report['elapsed_seconds']}))
        if cleanup_failed:
            raise RuntimeError('Temporary access cleanup requires reconciliation')


if __name__ == '__main__':
    main()
