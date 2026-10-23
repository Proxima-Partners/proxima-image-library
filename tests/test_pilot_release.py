import copy
import json
import pytest
from scripts.container_security_gate import sha
from scripts.pilot_release_manifest import bind
from scripts.deploy_container_pilot import main


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
