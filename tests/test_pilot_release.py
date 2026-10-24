import copy
import json
import io
import pytest
from scripts.container_security_gate import sha
from scripts.pilot_release_manifest import bind
from scripts.deploy_container_pilot import main
from scripts.configure_container_pilot import verify_pilot_site, APP_ID, PLAN_ID


@pytest.fixture
def release():
    data = json.dumps({'config': {'digest': 'sha256:tested'}}).encode()
    ref = 'proximaimagelibrary.azurecr.io/image-library@sha256:' + sha(data)
    return ref, {'status': 'pass', 'image_config_id': 'sha256:tested'}, data


def test_registry_digest_binds_to_tested_image(release):
    result = bind(*release)
    assert result['registry_image'] == release[0]
    assert result['provenance_type'] == 'workflow-release-receipt'


@pytest.mark.parametrize('case', ['tag', 'registry', 'repository', 'gate', 'config', 'digest'])
def test_reject_different_or_unverified_release(release, case):
    ref, gate, data = copy.deepcopy(release)
    if case == 'tag': ref = 'proximaimagelibrary.azurecr.io/image-library:latest'
    elif case == 'registry': ref = ref.replace('proximaimagelibrary', 'other')
    elif case == 'repository': ref = ref.replace('/image-library@', '/pete@')
    elif case == 'gate': gate['status'] = 'fail'
    elif case == 'config': gate['image_config_id'] = 'untested'
    elif case == 'digest': data += b' '
    with pytest.raises((ValueError, KeyError)): bind(ref, gate, data)


def test_deploy_rejects_unapproved_target_before_azure(monkeypatch):
    monkeypatch.setenv('RELEASE_IMAGE', 'pete.azurecr.io/server:latest')
    with pytest.raises(RuntimeError, match='Unexpected image target'): main()


@pytest.mark.parametrize('plan_key', ['serverFarmId', 'appServicePlanId'])
def test_pilot_target_guard_supports_both_cli_shapes(plan_key):
    verify_pilot_site({'id': APP_ID + '/slots/staging', plan_key: PLAN_ID.upper()}, 'staging')


@pytest.mark.parametrize('case', ['missing_plan', 'wrong_plan', 'wrong_group', 'wrong_app', 'wrong_slot', 'conflicting_fields'])
def test_pilot_target_guard_rejects_ambiguous_or_wrong_resources(case):
    site = {'id': APP_ID + '/slots/staging', 'serverFarmId': PLAN_ID}
    if case == 'missing_plan': site.pop('serverFarmId')
    elif case == 'wrong_plan': site['serverFarmId'] = PLAN_ID.replace('asp-image-library-p2v3', 'proxima-plan-s1')
    elif case == 'wrong_group': site['serverFarmId'] = PLAN_ID.replace('PP-Resources', 'another-rg')
    elif case == 'wrong_app': site['id'] = site['id'].replace('pp-image-library', 'PP-App-Serv')
    elif case == 'wrong_slot': site['id'] = APP_ID
    elif case == 'conflicting_fields': site['appServicePlanId'] = 'different'
    with pytest.raises(RuntimeError, match='Unexpected pilot'): verify_pilot_site(site, 'staging')


@pytest.mark.parametrize('case', ['legacy_app', 'unsafe_setting', 'existing_container'])
def test_source_baseline_refuses_unsafe_target_before_mutation(monkeypatch, case):
    from scripts import pilot_source_baseline as baseline
    from scripts.configure_container_pilot import SUB
    site = {'id': APP_ID, 'serverFarmId': PLAN_ID}
    if case == 'legacy_app': site['id'] = APP_ID.replace('pp-image-library', 'PP-App-Serv')
    def fake_az(*args):
        if args == ('account', 'show'): return {'id': SUB}
        if args[:2] == ('webapp', 'show'): return site
        if args[:3] == ('webapp', 'sitecontainers', 'list'): return [{'name': 'existing'}]
        raise AssertionError('Unexpected mutation')
    monkeypatch.setattr(baseline, 'az', fake_az)
    config = {'APP_READ_ONLY': 'true', 'INGEST_POLLER_ENABLED': 'false',
              'TEST_MODE': 'false', 'DEV_AUTH_BYPASS': 'false'}
    if case == 'unsafe_setting': config['APP_READ_ONLY'] = 'false'
    monkeypatch.setattr(baseline, 'settings', lambda _app: config)
    with pytest.raises(RuntimeError): baseline.main()


def test_existing_pilot_state_must_be_observed_before_replacement(monkeypatch):
    from scripts import deploy_container_pilot as deploy
    monkeypatch.setattr(deploy, 'urlopen', lambda *_a, **_kw: io.BytesIO(
        json.dumps({'pilot_state': {'state_id': 'a' * 64}}).encode()))
    assert deploy.prior_persistent_state('https://pilot', True) == 'a' * 64
    assert deploy.prior_persistent_state('https://pilot', False) is None
    with pytest.raises(RuntimeError, match='could not be verified'):
        deploy.prior_persistent_state('https://pilot', True, seconds=0)


def test_rehearsal_slot_guard():
    from scripts.pilot_rehearsal import slot_args
    assert slot_args('staging')[-2:] == ['--slot', 'staging']
    assert 'PP-App-Serv' not in slot_args('production')
    with pytest.raises(ValueError): slot_args('legacy-production')


def test_rehearsal_does_not_accept_state_loss(monkeypatch):
    from scripts import pilot_rehearsal as rehearsal
    expected = {'host': 'pilot', 'commit': 'a'*40, 'build_id': 'build-1'}
    monkeypatch.setattr(rehearsal, 'read_ready', lambda _host: dict(expected,
        pilot_state={'uid': 65532, 'gid': 65532, 'state_id': 'changed'}))
    with pytest.raises(RuntimeError, match='Persistent state'):
        rehearsal.verify_ready('staging', expected, 'original')


@pytest.mark.parametrize('case', ['expired', 'unverified', 'moving_tag'])
def test_rehearsal_refuses_untrusted_release_receipt(tmp_path, case):
    from scripts.pilot_rehearsal import load_release
    data = {'status': 'pass', 'registry_image': 'proximaimagelibrary.azurecr.io/image-library@sha256:' + 'a'*64,
            'commit': 'b'*40, 'build_id': 'run-1', 'expires_at': '2000-01-01T00:00:00Z'}
    if case == 'unverified': data['status'] = 'fail'
    if case == 'moving_tag': data['registry_image'] = 'proximaimagelibrary.azurecr.io/image-library:latest'
    path = tmp_path / 'release.json'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError): load_release(path)
