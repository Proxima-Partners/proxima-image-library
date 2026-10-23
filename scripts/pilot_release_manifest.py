"""Provenance receipt: registry manifest must reference the scanned image config."""
import json
from pathlib import Path
import re
import sys
from scripts.container_security_gate import sha


def bind(image_ref, gate, manifest_bytes):
    if not re.fullmatch(r'proximaimagelibrary\.azurecr\.io/image-library@sha256:[0-9a-f]{64}', image_ref):
        raise ValueError('Unexpected repository or non-immutable image reference')
    if gate['status'] != 'pass': raise ValueError('Security gate did not pass')
    if image_ref.split('@sha256:')[1] != sha(manifest_bytes):
        raise ValueError('Registry manifest digest mismatch')
    manifest = json.loads(manifest_bytes)
    if manifest['config']['digest'] != gate['image_config_id']:
        raise ValueError('Published image differs from scanned image')
    return dict(gate, registry_image=image_ref, provenance_type='workflow-release-receipt')


if __name__ == '__main__':
    gate = json.loads(Path('reports/security-gate.json').read_text())
    # Buildx prints a newline after the original JSON. Do not include it in the digest.
    manifest = Path('reports/registry-manifest.json').read_bytes().rstrip(b'\n')
    result = bind(sys.argv[1], gate, manifest)
    Path('reports/release.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'image': result['registry_image'], 'config': result['image_config_id'], 'commit': result['commit']}))
