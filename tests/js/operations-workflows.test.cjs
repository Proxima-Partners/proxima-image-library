const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const workflows = path.resolve(__dirname, '../../.github/workflows');

test('all workflow actions are immutable and artifact ZIP behavior is explicit', () => {
  for (const name of fs.readdirSync(workflows).filter(name => name.endsWith('.yml'))) {
    const source = fs.readFileSync(path.join(workflows, name), 'utf8');
    for (const use of source.matchAll(/uses: (.+)/g)) assert.match(use[1], /@[a-f0-9]{40}(?: |$)/);
    if (source.includes('actions/upload-artifact@')) {
      assert.match(source, /actions\/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9/);
      assert.match(source, /archive: true/);
    }
  }
});

// Supplemental boundary checks; actionlint validates actual workflow syntax.
test('production builder is manual main-only, publisher-only and refuses reruns', () => {
  const source = fs.readFileSync(path.join(workflows, 'production-build.yml'), 'utf8');
  assert.match(source, /workflow_dispatch: \{\}/);
  assert.match(source, /if: github.ref == 'refs\/heads\/main'/);
  assert.match(source, /vars.IMAGE_LIBRARY_PRODUCTION_BUILD_ENABLED == 'true'/);
  assert.match(source, /environment: image-library-build/);
  assert.match(source, /test "\$GITHUB_RUN_ATTEMPT" = '1'/);
  assert.match(source, /cancel-in-progress: false/);
  assert.match(source, /python3 -m scripts.pilot_release_manifest/);
  assert.match(source, /--disable-pip --strict/);
  assert.match(source, /AZURE_IMAGE_BUILD_CLIENT_ID/);
  assert.doesNotMatch(source, /^\s+(push|pull_request|schedule|deploy):/m);
  assert.doesNotMatch(source, /DEPLOY_CLIENT_ID|secrets\.|production_release|az webapp|az storage/);
});

for (const name of ['azure-deploy.yml', 'container-pilot.yml', 'pilot-source-baseline.yml']) {
  test(`${name} is a credential-free retired entry point`, () => {
    const source = fs.readFileSync(path.join(workflows, name), 'utf8');
    assert.match(source, /workflow_dispatch: \{\}/);
    assert.match(source, /exit 1/);
    assert.match(source, /group: image-library-deploy/);
    assert.match(source, /cancel-in-progress: false/);
    assert.doesNotMatch(source, /^\s+(push|schedule|pull_request|uses|environment):/m);
    assert.doesNotMatch(source, /\$\{\{|id-token:|secrets\./);
  });
}

for (const [name, flag] of [
  ['operations-health.yml', 'IMAGE_LIBRARY_PUBLIC_CHECKS_ENABLED'],
  ['release-evidence-review.yml', 'IMAGE_LIBRARY_EVIDENCE_REVIEW_ENABLED']
]) {
  test(`${name} stays manual, default-branch-only, opt-in and read-only`, () => {
    const source = fs.readFileSync(path.join(workflows, name), 'utf8');
    assert.match(source, /workflow_dispatch:/);
    assert.match(source, /if: github.ref == 'refs\/heads\/main'/);
    assert.ok(source.includes(`vars.${flag}`));
    assert.ok(source.includes('test "$ENABLED" = \'true\''));
    assert.match(source, /persist-credentials: false/);
    assert.doesNotMatch(source, /^\s+(push|schedule|pull_request|environment):/m);
    assert.doesNotMatch(source, /id-token:|secrets\.|azure\/|az webapp|production_release/);
    for (const use of source.matchAll(/uses: (.+)/g)) assert.match(use[1], /@[a-f0-9]{40}(?: |$)/);
    assert.doesNotMatch(source, /run:.*\$\{\{.*inputs\./);
  });
}
