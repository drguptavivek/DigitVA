import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, it } from 'node:test';

import { installWho, packageWho, verifyInstalledWho, WHO_PACKAGE_NAME } from '../build-who-package.mjs';

const SOURCE_COMMIT = '0123456789abcdef0123456789abcdef01234567';
const RELEASE = 'v2026.10.25.1';
const tempRoots = [];

function makeFixture() {
  const root = mkdtempSync(join(tmpdir(), 'digitva-who-package-'));
  tempRoots.push(root);
  const vendorDir = join(root, 'vendor');
  const outDir = join(root, 'artifact');
  const targetDir = join(root, 'target');
  mkdirSync(vendorDir, { recursive: true });
  mkdirFixture(targetDir);
  mkdirFixture(join(vendorDir, 'dist'));
  writeFileSync(join(vendorDir, 'package.json'), `${JSON.stringify({ name: WHO_PACKAGE_NAME, version: '0.1.0', files: ['dist', 'LICENSE', 'NOTICE'] }, null, 2)}\n`);
  writeFileSync(join(vendorDir, 'LICENSE'), 'MIT\n');
  writeFileSync(join(vendorDir, 'NOTICE'), 'Test fixture only.\n');
  writeFileSync(join(vendorDir, 'dist', 'entry.js'), 'export const entry = "fixture";\n');
  mkdirFixture(join(vendorDir, 'dist', 'nested'));
  writeFileSync(join(vendorDir, 'dist', 'nested', 'chunk.js'), 'export const chunk = true;\n');
  return { root, vendorDir, outDir, targetDir };
}

function mkdirFixture(directory) {
  mkdirSync(directory, { recursive: true });
}

afterEach(() => {
  while (tempRoots.length) rmSync(tempRoots.pop(), { recursive: true, force: true });
});

describe('WHO paired build package', () => {
  it('packages, installs, and verifies a compiled WHO dist round trip', () => {
    const fixture = makeFixture();
    const packaged = packageWho(fixture.vendorDir, fixture.outDir, RELEASE, SOURCE_COMMIT);
    assert.equal(packaged.metadata.schema, 1);
    assert.equal(packaged.metadata.release, RELEASE);
    assert.equal(packaged.metadata.package_name, WHO_PACKAGE_NAME);
    assert.equal(packaged.metadata.source_commit, SOURCE_COMMIT);
    assert.equal(packaged.metadata.artifact_name, `${RELEASE}-who-package.tgz`);
    assert.deepEqual(packaged.metadata.files.map((entry) => entry.path), ['entry.js', 'nested/chunk.js']);
    assert.equal(packaged.metadata.files.reduce((sum, entry) => sum + entry.size, 0), 59);
    writeFileSync(join(fixture.targetDir, 'package.json'), readFileSync(join(fixture.vendorDir, 'package.json')));
    installWho(fixture.outDir, fixture.targetDir, SOURCE_COMMIT);
    writeFileSync(join(fixture.targetDir, 'package.json'), `${JSON.stringify({ name: WHO_PACKAGE_NAME, version: '0.1.0' })}\n`);
    verifyInstalledWho(fixture.outDir, fixture.targetDir, SOURCE_COMMIT);
    assert.equal(readFileSync(join(fixture.targetDir, 'dist', 'nested', 'chunk.js'), 'utf8'), 'export const chunk = true;\n');
  });

  it('rejects a tampered copied dist file and a commit mismatch', () => {
    const fixture = makeFixture();
    packageWho(fixture.vendorDir, fixture.outDir, RELEASE, SOURCE_COMMIT);
    writeFileSync(join(fixture.outDir, 'dist', 'entry.js'), 'tampered\n');
    writeFileSync(join(fixture.targetDir, 'package.json'), readFileSync(join(fixture.vendorDir, 'package.json')));
    assert.throws(() => installWho(fixture.outDir, fixture.targetDir, SOURCE_COMMIT), /dist files or digests/);
    assert.throws(() => verifyInstalledWho(fixture.outDir, fixture.vendorDir, 'fedcba9876543210fedcba9876543210fedcba98'), /source commit mismatch/);
  });

  it('rejects a tampered archive checksum and traversal in the manifest', () => {
    const fixture = makeFixture();
    packageWho(fixture.vendorDir, fixture.outDir, RELEASE, SOURCE_COMMIT);
    const archivePath = join(fixture.outDir, `${RELEASE}-who-package.tgz`);
    const archive = readFileSync(archivePath);
    writeFileSync(archivePath, Buffer.concat([archive.subarray(0, archive.length - 1), Buffer.from([archive[archive.length - 1] ^ 0xff])]));
    writeFileSync(join(fixture.targetDir, 'package.json'), readFileSync(join(fixture.vendorDir, 'package.json')));
    assert.throws(() => installWho(fixture.outDir, fixture.targetDir, SOURCE_COMMIT), /archive sha256/);

    const fresh = makeFixture();
    packageWho(fresh.vendorDir, fresh.outDir, RELEASE, SOURCE_COMMIT);
    const metadataPath = join(fresh.outDir, 'who-build.json');
    const metadata = JSON.parse(readFileSync(metadataPath, 'utf8'));
    metadata.files[0].path = '../outside.js';
    writeFileSync(metadataPath, `${JSON.stringify(metadata)}\n`);
    assert.throws(() => verifyInstalledWho(fresh.outDir, fresh.vendorDir, SOURCE_COMMIT), /path is unsafe/);
  });

  it('rejects package identity/version mismatches before changing dist', () => {
    const fixture = makeFixture();
    packageWho(fixture.vendorDir, fixture.outDir, RELEASE, SOURCE_COMMIT);
    writeFileSync(join(fixture.targetDir, 'package.json'), `${JSON.stringify({ name: '@example/not-who', version: '0.1.0' })}\n`);
    assert.throws(() => installWho(fixture.outDir, fixture.targetDir, SOURCE_COMMIT), /vendor package name/);
    writeFileSync(join(fixture.targetDir, 'package.json'), `${JSON.stringify({ name: WHO_PACKAGE_NAME, version: '9.9.9' })}\n`);
    assert.throws(() => installWho(fixture.outDir, fixture.targetDir, SOURCE_COMMIT), /package version mismatch/);
  });

  it('rejects symlinked dist files and missing or extra artifact files', () => {
    const fixture = makeFixture();
    symlinkSync('entry.js', join(fixture.vendorDir, 'dist', 'linked.js'));
    assert.throws(() => packageWho(fixture.vendorDir, fixture.outDir, RELEASE, SOURCE_COMMIT), /symlink/);
    rmSync(join(fixture.vendorDir, 'dist', 'linked.js'));
    packageWho(fixture.vendorDir, fixture.outDir, RELEASE, SOURCE_COMMIT);
    rmSync(join(fixture.vendorDir, 'dist', 'nested', 'chunk.js'));
    assert.throws(() => verifyInstalledWho(fixture.outDir, fixture.vendorDir, SOURCE_COMMIT), /dist files or digests/);
    writeFileSync(join(fixture.vendorDir, 'dist', 'extra.js'), 'extra\n');
    assert.throws(() => verifyInstalledWho(fixture.outDir, fixture.vendorDir, SOURCE_COMMIT), /dist files or digests/);
  });
});
