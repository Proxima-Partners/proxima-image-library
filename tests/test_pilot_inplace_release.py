import copy
import json
import subprocess

import pytest

from scripts import pilot_inplace_release as rollout


@pytest.fixture
def transaction(monkeypatch, tmp_path):
    old_image = 'proximaimagelibrary.azurecr.io/image-library@sha256:' + 'a' * 64
    new_image = old_image[:-64] + 'b' * 64
    before = {'image': old_image, 'host': 'pilot', 'readiness': {
        'commit': 'c' * 40, 'build_id': '111-1', 'pilot_state': {'state_id': 'd' * 64}}}
    prior = {'registry_image': old_image, 'commit': 'c' * 40, 'build_id': '111-1'}
    release = {'registry_image': new_image, 'commit': 'e' * 40, 'build_id': '222-1'}
    state = {'current': copy.deepcopy(before), 'updates': [], 'checks': [], 'config': {'secret': 'never-in-artifacts'}}
    monkeypatch.setattr(rollout, 'capture', lambda slot: copy.deepcopy(state['current']))
    monkeypatch.setattr(rollout, 'protected_configuration', lambda slot: copy.deepcopy(state['config']))
    def update(slot, image):
        state['updates'].append(image)
        state['current']['image'] = image
    def verify(slot, expected, state_id):
        state['checks'].append((expected['image'], state_id))
        return copy.deepcopy(state['current'])
    monkeypatch.setattr(rollout, 'update_digest', update)
    monkeypatch.setattr(rollout, 'verify_ready', verify)
    return state, release, prior, {}, tmp_path / 'report.json'


def test_inplace_preserves_state_without_recording_secrets(transaction):
    state, release, prior, report, path = transaction
    rollout.update_slot('production', release, prior, report, path)
    assert state['updates'] == [release['registry_image']]
    assert state['checks'] == [(release['registry_image'], 'd' * 64)]
    assert report['operations'][0]['status'] == 'passed'
    assert report['operations'][0]['settings_and_credentials_unchanged'] is True
    assert 'never-in-artifacts' not in path.read_text()


@pytest.mark.parametrize('field', ['registry_image', 'commit', 'build_id'])
def test_prior_receipt_must_match_before_any_mutation(transaction, field):
    state, release, prior, report, path = transaction
    prior[field] = 'wrong'
    with pytest.raises(RuntimeError, match='receipt does not match'):
        rollout.update_slot('production', release, prior, report, path)
    assert state['updates'] == []


@pytest.mark.parametrize('error', [RuntimeError('Azure failed'), subprocess.TimeoutExpired('az', 180)])
def test_ambiguous_update_never_blindly_rolls_back(transaction, monkeypatch, error):
    state, release, prior, report, path = transaction
    def failed_update(slot, image):
        state['updates'].append(image)
        raise error
    monkeypatch.setattr(rollout, 'update_digest', failed_update)
    with pytest.raises(RuntimeError, match='ambiguous'):
        rollout.update_slot('production', release, prior, report, path)
    assert state['updates'] == [release['registry_image']]
    assert report['operations'][0]['rollback_attempts'] == 0
    assert 'manual_reconciliation_required' in report['operations'][0]['status']


def test_confirmed_failure_restores_prior_approved_digest_once(transaction, monkeypatch):
    state, release, prior, report, path = transaction
    def verify(slot, expected, state_id):
        assert state_id == 'd' * 64
        if expected['image'] == release['registry_image']:
            raise RuntimeError('Readiness failure')
        return state['current']
    monkeypatch.setattr(rollout, 'verify_ready', verify)
    with pytest.raises(RuntimeError, match='restored once'):
        rollout.update_slot('production', release, prior, report, path)
    assert state['updates'] == [release['registry_image'], prior['registry_image']]
    assert report['operations'][0]['status'] == 'rolled_back'
    assert report['operations'][0]['rollback_attempts'] == 1


def test_failed_recovery_stops_without_oscillation(transaction, monkeypatch):
    state, release, prior, report, path = transaction
    def fail(*args): raise RuntimeError('Readiness failed')
    monkeypatch.setattr(rollout, 'verify_ready', fail)
    with pytest.raises(RuntimeError, match='single recovery failed'):
        rollout.update_slot('production', release, prior, report, path)
    assert state['updates'] == [release['registry_image'], prior['registry_image']]
    assert report['operations'][0]['rollback_attempts'] == 1


@pytest.mark.parametrize('change', ['config', 'image'])
def test_concurrent_change_refuses_automatic_recovery(transaction, monkeypatch, change):
    state, release, prior, report, path = transaction
    def verify(*args):
        if change == 'config': state['config']['secret'] = 'changed'
        else: state['current']['image'] = prior['registry_image']
        raise RuntimeError('Concurrent change')
    monkeypatch.setattr(rollout, 'verify_ready', verify)
    with pytest.raises(RuntimeError, match='no automatic rollback'):
        rollout.update_slot('production', release, prior, report, path)
    assert state['updates'] == [release['registry_image']]
    assert report['operations'][0]['rollback_attempts'] == 0


def test_already_correct_image_is_verified_without_mutation(transaction):
    state, release, prior, report, path = transaction
    rollout.update_slot('production', prior, prior, report, path)
    assert state['updates'] == []
    assert report['operations'][0]['status'] == 'already_verified'


@pytest.mark.parametrize('image', ['registry/pete:latest', 'proximaimagelibrary.azurecr.io/image-library:latest'])
def test_update_refuses_other_repo_or_moving_tag(monkeypatch, image):
    monkeypatch.setattr(rollout, 'az', lambda *args: pytest.fail('No Azure mutation allowed'))
    with pytest.raises(ValueError): rollout.update_digest('production', image)


def test_update_changes_only_image_and_exact_pilot_target(monkeypatch):
    calls = []
    monkeypatch.setattr(rollout, 'az', lambda *args: calls.append(args))
    image = 'proximaimagelibrary.azurecr.io/image-library@sha256:' + 'a' * 64
    rollout.update_digest('production', image)
    assert calls == [('webapp', 'sitecontainers', 'update', '-g', 'PP-Resources', '-n',
                      'pp-image-library', '--container-name', 'main', '--image', image)]


def test_cleanup_is_verified_not_assumed(monkeypatch):
    monkeypatch.setattr(rollout, 'az', lambda *args: {'ipSecurityRestrictions': [{'name': 'rule'}]})
    with pytest.raises(RuntimeError, match='still present'): rollout.remove_access('staging', 'rule')


@pytest.mark.parametrize('shape', ['flat', 'properties'])
def test_protected_configuration_excludes_only_image(monkeypatch, shape):
    value = {'image': 'image', 'isMain': True, 'authType': 'SystemIdentity', 'targetPort': '8080'}
    monkeypatch.setattr(rollout, 'az', lambda *args: [value if shape == 'flat' else {'properties': value}])
    monkeypatch.setattr(rollout, 'settings', lambda *args: {'FLASK_SECRET_KEY': 'sensitive'})
    result = rollout.protected_configuration('production')
    assert result == {'settings': {'FLASK_SECRET_KEY': 'sensitive'}, 'container': {
        'isMain': True, 'authType': 'SystemIdentity', 'targetPort': '8080'}}
