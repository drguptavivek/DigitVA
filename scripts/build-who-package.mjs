import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, extname, join, resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

export const WHO_PACKAGE_NAME = '@drguptavivek/who-2022-va';
export const WHO_BUILD_SCHEMA = 1;

const MAX_FILES = 4096;
const MAX_FILE_BYTES = 32 * 1024 * 1024;
const MAX_DIST_BYTES = 100 * 1024 * 1024;
const MAX_ARCHIVE_BYTES = 64 * 1024 * 1024;
const SOURCE_COMMIT_RE = /^[0-9a-f]{40}$/;
const SEMVER_RE = /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;
const RELEASE_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/;
const SAFE_COMPONENT_RE = /^[A-Za-z0-9][A-Za-z0-9._@()+-]*$/;

function fail(message) {
  throw new Error(message);
}

function assert(condition, message) {
  if (!condition) fail(message);
}

function sha256Bytes(value) {
  return createHash('sha256').update(value).digest('hex');
}

function sha256File(filePath) {
  return sha256Bytes(readFileSync(filePath));
}

function assertPathWithin(root, candidate, label) {
  const rootPath = resolve(root);
  const candidatePath = resolve(candidate);
  assert(candidatePath === rootPath || candidatePath.startsWith(`${rootPath}${sep}`), `${label} escapes its directory`);
  return candidatePath;
}

function assertSourceCommit(sourceCommit) {
  assert(typeof sourceCommit === 'string' && SOURCE_COMMIT_RE.test(sourceCommit), 'source_commit must be a 40-character hexadecimal commit');
}

function assertRelease(release) {
  assert(typeof release === 'string' && RELEASE_RE.test(release), 'release must be a safe non-empty release identifier');
}

function assertVersion(version) {
  assert(typeof version === 'string' && SEMVER_RE.test(version), `package version is not valid semver: ${version}`);
}

function assertSafeRelativePath(value, label = 'path') {
  assert(typeof value === 'string' && value.length > 0 && !value.includes('\\') && !value.startsWith('/') && !value.includes('\0'), `${label} is unsafe`);
  const parts = value.split('/');
  assert(parts.every((part) => part !== '' && part !== '.' && part !== '..' && !part.startsWith('.') && SAFE_COMPONENT_RE.test(part)), `${label} is unsafe`);
  return value;
}

function assertRegularFile(filePath, label) {
  const info = lstatSync(filePath);
  assert(info.isFile(), `${label} must be a regular file`);
  assert(!info.isSymbolicLink(), `${label} must not be a symlink`);
  return info;
}

function assertDirectory(directoryPath, label) {
  const info = lstatSync(directoryPath);
  assert(info.isDirectory() && !info.isSymbolicLink(), `${label} must be a regular directory`);
  return info;
}

function readJsonFile(filePath, label) {
  assertRegularFile(filePath, label);
  try {
    return JSON.parse(readFileSync(filePath, 'utf8'));
  } catch (error) {
    fail(`${label} is not valid JSON: ${error.message}`);
  }
}

function readPackageIdentity(vendorDir) {
  assertDirectory(vendorDir, 'vendor directory');
  const packagePath = assertPathWithin(vendorDir, join(vendorDir, 'package.json'), 'package.json');
  const packageJson = readJsonFile(packagePath, 'vendor package.json');
  assert(packageJson && typeof packageJson === 'object' && !Array.isArray(packageJson), 'vendor package.json must contain an object');
  assert(packageJson.name === WHO_PACKAGE_NAME, `vendor package name must be ${WHO_PACKAGE_NAME}`);
  assertVersion(packageJson.version);
  return {
    packageJson,
    packagePath,
    packageJsonSha256: sha256File(packagePath),
    packageVersion: packageJson.version,
  };
}

function walkDistFiles(distDir) {
  const root = resolve(distDir);
  assertDirectory(root, 'dist');
  const files = [];
  let totalBytes = 0;

  function visit(directory, prefix) {
    const entries = readdirSync(directory, { withFileTypes: true }).sort((left, right) => (left.name < right.name ? -1 : left.name > right.name ? 1 : 0));
    for (const entry of entries) {
      const relativePath = prefix ? `${prefix}/${entry.name}` : entry.name;
      assertSafeRelativePath(relativePath, 'dist file path');
      const fullPath = join(directory, entry.name);
      const info = lstatSync(fullPath);
      assert(!info.isSymbolicLink(), `dist contains symlink: ${relativePath}`);
      if (info.isDirectory()) {
        visit(fullPath, relativePath);
        continue;
      }
      assert(info.isFile(), `dist contains non-regular file: ${relativePath}`);
      assert(files.length < MAX_FILES, `dist contains more than ${MAX_FILES} files`);
      assert(info.size <= MAX_FILE_BYTES, `dist file exceeds ${MAX_FILE_BYTES} bytes: ${relativePath}`);
      totalBytes += info.size;
      assert(totalBytes <= MAX_DIST_BYTES, `dist exceeds ${MAX_DIST_BYTES} bytes`);
      files.push({ path: relativePath, size: info.size, sha256: sha256File(fullPath) });
    }
  }

  visit(root, '');
  assert(files.length > 0, 'dist must contain at least one file');
  files.sort((left, right) => (left.path < right.path ? -1 : left.path > right.path ? 1 : 0));
  return files;
}

function distDigest(files) {
  return sha256Bytes(Buffer.from(JSON.stringify(files), 'utf8'));
}

function readArtifactHeader(artifactDir) {
  const root = resolve(artifactDir);
  assertDirectory(root, 'WHO artifact directory');
  const headerPath = assertPathWithin(root, join(root, 'who-build.json'), 'who-build.json');
  const metadata = readJsonFile(headerPath, 'who-build.json');
  assert(metadata && typeof metadata === 'object' && !Array.isArray(metadata), 'who-build.json must contain an object');
  const expectedKeys = ['schema', 'release', 'package_name', 'package_version', 'source_commit', 'artifact_name', 'artifact_sha256', 'package_json_sha256', 'dist_sha256', 'files'];
  assert(JSON.stringify(Object.keys(metadata).sort()) === JSON.stringify(expectedKeys.sort()), 'who-build.json has an unexpected schema');
  assert(metadata.schema === WHO_BUILD_SCHEMA, `unsupported WHO build schema: ${metadata.schema}`);
  assertRelease(metadata.release);
  assert(metadata.package_name === WHO_PACKAGE_NAME, `who-build.json package_name must be ${WHO_PACKAGE_NAME}`);
  assertVersion(metadata.package_version);
  assertSourceCommit(metadata.source_commit);
  assert(typeof metadata.artifact_name === 'string' && metadata.artifact_name === `${metadata.release}-who-package.tgz`, 'who-build.json artifact_name is invalid');
  assert(/^[0-9a-f]{64}$/.test(metadata.artifact_sha256), 'who-build.json artifact_sha256 is invalid');
  assert(/^[0-9a-f]{64}$/.test(metadata.package_json_sha256), 'who-build.json package_json_sha256 is invalid');
  assert(/^[0-9a-f]{64}$/.test(metadata.dist_sha256), 'who-build.json dist_sha256 is invalid');
  assert(Array.isArray(metadata.files) && metadata.files.length > 0 && metadata.files.length <= MAX_FILES, 'who-build.json files is invalid');
  let previousPath = '';
  for (const entry of metadata.files) {
    assert(entry && typeof entry === 'object' && !Array.isArray(entry), 'who-build.json contains an invalid file entry');
    assert(JSON.stringify(Object.keys(entry).sort()) === JSON.stringify(['path', 'size', 'sha256'].sort()), 'who-build.json file entry has an unexpected schema');
    assertSafeRelativePath(entry.path, 'who-build.json file path');
    assert(entry.path > previousPath, 'who-build.json files must be sorted and unique');
    previousPath = entry.path;
    assert(Number.isSafeInteger(entry.size) && entry.size >= 0 && entry.size <= MAX_FILE_BYTES, `who-build.json file size is invalid: ${entry.path}`);
    assert(/^[0-9a-f]{64}$/.test(entry.sha256), `who-build.json file sha256 is invalid: ${entry.path}`);
  }
  assert(metadata.files.reduce((total, entry) => total + entry.size, 0) <= MAX_DIST_BYTES, 'who-build.json dist exceeds size limit');
  const files = metadata.files.map((entry) => ({ path: entry.path, size: entry.size, sha256: entry.sha256 }));
  assert(distDigest(files) === metadata.dist_sha256, 'who-build.json dist_sha256 does not match files');
  return { root, headerPath, metadata: { ...metadata, files } };
}

function assertExpectedCommit(metadata, expectedCommit) {
  assertSourceCommit(expectedCommit);
  assert(metadata.source_commit === expectedCommit, `source commit mismatch: expected ${expectedCommit}, got ${metadata.source_commit}`);
}

function assertManifestMatchesDist(distDir, expectedFiles, expectedDigest) {
  const actualFiles = walkDistFiles(distDir);
  assert(JSON.stringify(actualFiles) === JSON.stringify(expectedFiles), 'artifact dist files or digests do not match who-build.json');
  assert(distDigest(actualFiles) === expectedDigest, 'artifact dist_sha256 does not match who-build.json');
  return actualFiles;
}

function copyVerifiedDist(sourceDist, destinationDist, expectedFiles) {
  assert(!existsSync(destinationDist) || !lstatSync(destinationDist).isSymbolicLink(), 'destination dist must not be a symlink');
  mkdirSync(destinationDist, { recursive: true });
  for (const file of expectedFiles) {
    const sourcePath = assertPathWithin(sourceDist, join(sourceDist, ...file.path.split('/')), `artifact dist file ${file.path}`);
    assertRegularFile(sourcePath, `artifact dist file ${file.path}`);
    const destinationPath = assertPathWithin(destinationDist, join(destinationDist, ...file.path.split('/')), `installed dist file ${file.path}`);
    mkdirSync(dirname(destinationPath), { recursive: true });
    copyFileSync(sourcePath, destinationPath);
  }
}

function verifyArchive(artifactRoot, metadata) {
  const archivePath = assertPathWithin(artifactRoot, join(artifactRoot, metadata.artifact_name), 'WHO archive');
  const archiveInfo = assertRegularFile(archivePath, 'WHO archive');
  assert(archiveInfo.size <= MAX_ARCHIVE_BYTES, `WHO archive exceeds ${MAX_ARCHIVE_BYTES} bytes`);
  assert(sha256File(archivePath) === metadata.artifact_sha256, 'WHO archive sha256 does not match who-build.json');
  const checksumPath = `${archivePath}.sha256`;
  if (existsSync(checksumPath)) {
    assertRegularFile(checksumPath, 'WHO archive checksum');
    const checksum = readFileSync(checksumPath, 'utf8').trim();
    const match = checksum.match(/^([0-9a-f]{64})\s+(\S+)$/i);
    assert(match && match[1].toLowerCase() === metadata.artifact_sha256 && match[2] === metadata.artifact_name, 'WHO archive checksum does not match who-build.json');
  }
  return archivePath;
}

export function packageWho(vendorDirInput, outDirInput, release, sourceCommit) {
  const vendorDir = resolve(vendorDirInput);
  const outDir = resolve(outDirInput);
  assertDirectory(vendorDir, 'vendor directory');
  assertRelease(release);
  assertSourceCommit(sourceCommit);
  const identity = readPackageIdentity(vendorDir);
  const distDir = assertPathWithin(vendorDir, join(vendorDir, 'dist'), 'vendor dist');
  const files = walkDistFiles(distDir);
  const metadataDistDigest = distDigest(files);
  if (existsSync(outDir)) assertDirectory(outDir, 'artifact output directory');
  mkdirSync(outDir, { recursive: true });
  const archiveName = `${release}-who-package.tgz`;
  const archivePath = assertPathWithin(outDir, join(outDir, archiveName), 'WHO archive');
  const checksumPath = `${archivePath}.sha256`;
  const headerPath = assertPathWithin(outDir, join(outDir, 'who-build.json'), 'who-build.json');
  const distOutDir = assertPathWithin(outDir, join(outDir, 'dist'), 'artifact dist');
  assert(!existsSync(archivePath) && !existsSync(checksumPath) && !existsSync(headerPath) && !existsSync(distOutDir), 'WHO artifact output already exists; use a new directory');

  const packDir = mkdtempSync(join(outDir, '.who-pack-'));
  try {
    execFileSync('npm', ['pack', '--ignore-scripts', '--pack-destination', packDir], {
      cwd: vendorDir,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const archives = readdirSync(packDir).filter((entry) => extname(entry) === '.tgz');
    assert(archives.length === 1, 'npm pack did not produce exactly one archive');
    renameSync(join(packDir, archives[0]), archivePath);
  } catch (error) {
    fail(`npm pack failed: ${error.message}`);
  } finally {
    rmSync(packDir, { recursive: true, force: true });
  }

  const archiveInfo = assertRegularFile(archivePath, 'WHO archive');
  assert(archiveInfo.size <= MAX_ARCHIVE_BYTES, `WHO archive exceeds ${MAX_ARCHIVE_BYTES} bytes`);
  const artifactSha256 = sha256File(archivePath);
  writeFileSync(checksumPath, `${artifactSha256}  ${archiveName}\n`, 'utf8');
  mkdirSync(distOutDir, { recursive: true });
  copyVerifiedDist(distDir, distOutDir, files);
  const metadata = {
    schema: WHO_BUILD_SCHEMA,
    release,
    package_name: WHO_PACKAGE_NAME,
    package_version: identity.packageVersion,
    source_commit: sourceCommit,
    artifact_name: archiveName,
    artifact_sha256: artifactSha256,
    package_json_sha256: identity.packageJsonSha256,
    dist_sha256: metadataDistDigest,
    files,
  };
  writeFileSync(headerPath, `${JSON.stringify(metadata, null, 2)}\n`, 'utf8');
  return { artifactDir: outDir, archivePath, checksumPath, distPath: distOutDir, headerPath, metadata };
}

export function installWho(artifactDirInput, vendorDirInput, expectedCommit) {
  const artifact = readArtifactHeader(artifactDirInput);
  assertExpectedCommit(artifact.metadata, expectedCommit);
  const identity = readPackageIdentity(vendorDirInput);
  assert(identity.packageVersion === artifact.metadata.package_version, `package version mismatch: expected ${artifact.metadata.package_version}, got ${identity.packageVersion}`);
  assert(identity.packageJsonSha256 === artifact.metadata.package_json_sha256, 'vendor package.json sha256 does not match who-build.json');
  verifyArchive(artifact.root, artifact.metadata);
  const artifactDist = assertPathWithin(artifact.root, join(artifact.root, 'dist'), 'artifact dist');
  assertManifestMatchesDist(artifactDist, artifact.metadata.files, artifact.metadata.dist_sha256);
  const vendorDir = resolve(vendorDirInput);
  const vendorDist = assertPathWithin(vendorDir, join(vendorDir, 'dist'), 'vendor dist');
  const stagingRoot = mkdtempSync(join(vendorDir, '.who-install-'));
  const stagingDist = join(stagingRoot, 'dist');
  try {
    copyVerifiedDist(artifactDist, stagingDist, artifact.metadata.files);
    assertManifestMatchesDist(stagingDist, artifact.metadata.files, artifact.metadata.dist_sha256);
    if (existsSync(vendorDist)) {
      assertDirectory(vendorDist, 'vendor dist destination');
      rmSync(vendorDist, { recursive: true, force: true });
    }
    renameSync(stagingDist, vendorDist);
  } finally {
    rmSync(stagingRoot, { recursive: true, force: true });
  }
  verifyInstalledWho(artifactDirInput, vendorDir, expectedCommit);
  return { vendorDir, distPath: vendorDist, metadata: artifact.metadata };
}

export function verifyInstalledWho(artifactDirInput, installedPackageDirInput, expectedCommit) {
  const artifact = readArtifactHeader(artifactDirInput);
  assertExpectedCommit(artifact.metadata, expectedCommit);
  const identity = readPackageIdentity(installedPackageDirInput);
  assert(identity.packageVersion === artifact.metadata.package_version, `installed package version mismatch: expected ${artifact.metadata.package_version}, got ${identity.packageVersion}`);
  const installedDist = assertPathWithin(installedPackageDirInput, join(installedPackageDirInput, 'dist'), 'installed dist');
  assertManifestMatchesDist(installedDist, artifact.metadata.files, artifact.metadata.dist_sha256);
  return { installedPackageDir: resolve(installedPackageDirInput), distPath: installedDist, metadata: artifact.metadata };
}

function usage() {
  return [
    'Usage:',
    '  node scripts/build-who-package.mjs package <vendorDir> <outDir> <release> <sourceCommit>',
    '  node scripts/build-who-package.mjs install <artifactDir> <vendorDir> <expectedCommit>',
    '  node scripts/build-who-package.mjs verify-installed <artifactDir> <installedPackageDir> <expectedCommit>',
  ].join('\n');
}

function main(argv) {
  const [command, ...args] = argv;
  const summarize = (metadata) => {
    const { release, source_commit, package_name, package_version, artifact_sha256, dist_sha256 } = metadata;
    process.stdout.write(`${JSON.stringify({ release, source_commit, package_name, package_version, artifact_sha256, dist_sha256, files: metadata.files.length })}\n`);
  };
  if (command === 'package' && args.length === 4) {
    const result = packageWho(...args);
    summarize(result.metadata);
    return;
  }
  if (command === 'install' && args.length === 3) {
    const result = installWho(...args);
    summarize(result.metadata);
    return;
  }
  if (command === 'verify-installed' && args.length === 3) {
    const result = verifyInstalledWho(...args);
    summarize(result.metadata);
    return;
  }
  fail(usage());
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`WHO package build failed: ${error.message}\n`);
    process.exitCode = 1;
  }
}
