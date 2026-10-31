#!/usr/bin/env bash
# Local Collect Plus build in Docker: `make collect-plus-local`. Runs every step to the arm64 release APK in a pinned
# linux/amd64 toolchain container, from this working tree (default) or a clean clone (SRC=git REF=<branch|sha>).
# NATIVE=1 runs the same build.sh on this Mac instead (much faster: the container is amd64 and emulated on Apple Silicon).
# LOCAL VERIFICATION BUILD, NOT FOR DISTRIBUTION: release APKs come only from CI (owner rule). The local APK is signed
# with the Expo template's debug key (the release key exists only in CI); it is printed at the end.
#
#   SRC=worktree|git   source: tracked + untracked-not-ignored files of the repo and vendor/smartva-analyze (default), or a clone
#   REF=<branch|sha>   with SRC=git; default main
#   NATIVE=1           build on the host with its own tools, caches and Gradle: checks them against the pins, stops naming
#                      any that is missing or off. Not pinned like the image, so its engine bytes differ from a Linux build.
#                      Work dir build/collect-plus-local/.work; ANDROID_HOME defaults to ~/Library/Android/sdk
#   DRY_RUN=1          prepare the source and the WHO assemblies, print the commands, build nothing
#   SKIP_CHECKS=1      skip typecheck, Jest and the module's JVM unit tests (CI runs them)
#   MIN_DOCKER_GB=11   memory floor for Docker's VM (the engine's ILC was OOM-killed at 6 GB; Docker reports a "12 GB"
#                      setting as ~11.7 GiB)
#
# The container gets no docker.sock and no private/: WHO's /usr/share/icdapi is copied out of the pinned image here, on the host
# (the only Docker use of NATIVE=1, and only when that copy is not cached).
# Output: build/collect-plus-local/ (APK, digitva_icd11.so, SHA256SUMS, SOURCE.txt, SIGNER.txt). Caches are named Docker
# volumes digitva-cp-*; `docker volume rm $(docker volume ls -q -f name=digitva-cp-)` resets them (WHO downloads are
# sha256-checked on every run regardless).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
out="$repo/build/collect-plus-local"
work="$out/.work"
src_mode=${SRC:-worktree}
engine_src=mobile/digitva-collect/modules/digitva-icd11/engine-src
ref=${REF:-main}
native=${NATIVE:-}
repo_url=https://github.com/drguptavivek/DigitVA.git
image=digitva-collect-plus-build:local
# shellcheck source=pins.sh
. "$here/pins.sh"

die() { echo "collect-plus-local: $*" >&2; exit 1; }
[[ $src_mode == worktree || $src_mode == git ]] || die "SRC must be worktree or git, not '$src_mode'"
[[ $ref =~ ^[A-Za-z0-9._/-]+$ && $ref != -* ]] || die "REF must be a branch name or sha"
[[ -z $native || $native == 1 ]] || die "NATIVE must be 1 or unset"

docker_ok() { command -v docker >/dev/null && docker info >/dev/null 2>&1; }
if [[ $native != 1 ]]; then
  docker_ok || die "Docker is not running"
  mem=$(docker info --format '{{.MemTotal}}')
  min=$(( ${MIN_DOCKER_GB:-11} * 1024 * 1024 * 1024 ))
  (( mem >= min )) || die "Docker has $((mem / 1024 / 1024 / 1024)) GiB; the engine compile needs about 12 GB. Raise Docker Desktop > Settings > Resources > Memory."
fi

# --- 1. source -----------------------------------------------------------------------------------------------------
# Existing files of `git ls-files -co --exclude-standard` under $1 (a deleted tracked file or a submodule dir is skipped),
# minus anything the build does not read: private/, docs/, resource/ (but the one file the app's tests read), build dirs,
# node_modules, prebuilt android/ios.
source_files() {
  (cd "$1" && git ls-files -z -co --exclude-standard --deduplicate | xargs -0 -n 500 bash -c '
    for f; do
      case $f in
        resource/doris_help_examples.json) ;;
        private/*|docs/*|resource/*|.claude/*|.beads/*|build/*|node_modules/*|*/node_modules/*|mobile/digitva-collect/android/*|mobile/digitva-collect/ios/*|mobile/digitva-collect/coverage/*|mobile/digitva-collect/dist/*|mobile/digitva-collect/.expo/*) continue ;;
      esac
      if [[ -f $f || -L $f ]]; then printf "%s\0" "$f"; fi
    done' _)
}
copy_tree() { source_files "$1" | COPYFILE_DISABLE=1 tar -C "$1" --no-xattrs --null -T - -cf - | tar -C "$2" -xf -; }

rm -rf "$work/src"; mkdir -p "$work/src" "$work/cache"
if [[ $src_mode == git ]]; then
  git clone --quiet "$repo_url" "$work/src"
  git -C "$work/src" checkout --quiet "$ref"
  git -C "$work/src" submodule update --init --depth 1 vendor/smartva-analyze
  commit=$(git -C "$work/src" rev-parse HEAD); dirty=no
else
  [[ -e $repo/vendor/smartva-analyze/.git ]] || die "vendor/smartva-analyze is not checked out: git submodule update --init vendor/smartva-analyze"
  copy_tree "$repo" "$work/src"
  mkdir -p "$work/src/vendor/smartva-analyze"
  copy_tree "$repo/vendor/smartva-analyze" "$work/src/vendor/smartva-analyze"
  commit=$(git -C "$repo" rev-parse HEAD)
  changed=$(git -C "$repo" status --porcelain | wc -l | tr -d ' ')
  sub=$(git -C "$repo/vendor/smartva-analyze" status --porcelain | wc -l | tr -d ' ')
  if [[ $changed == 0 && $sub == 0 && $(git -C "$repo/vendor/smartva-analyze" rev-parse HEAD) == $(git -C "$repo" rev-parse HEAD:vendor/smartva-analyze) ]]; then dirty=no
  else dirty="yes ($changed paths changed/untracked in the repo, $sub in smartva-analyze)"; fi
fi
src="$work/src"
require_pins "$src"
ndk=$(pin_ndk "$src")

# NATIVE=1: every host tool against the pins; all problems are listed at once, nothing is installed.
if [[ $native == 1 ]]; then
  export ANDROID_HOME=${ANDROID_HOME:-$HOME/Library/Android/sdk}
  export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 COREPACK_ENABLE_DOWNLOAD_PROMPT=0
  problems=()
  want_node=$(pin_node_major "$src"); want_pnpm=$(pin_pnpm "$src"); want_dotnet=$(pin_dotnet "$src")
  have_node=$(command -v node >/dev/null && node -p 'process.versions.node.split(".")[0]' || true)
  # Native mode is not pinned like the image: a newer major than CI's is used with a warning, an older one refused.
  if [[ -z $have_node || $have_node -lt $want_node ]]; then problems+=("Node $want_node or newer needed, found ${have_node:-none}. Install: nvm install $want_node && nvm use $want_node (or brew install node@$want_node and put it first on PATH)")
  elif [[ $have_node != "$want_node" ]]; then echo "warning: Node $have_node, CI uses $want_node" >&2; fi
  have_pnpm=$(command -v pnpm >/dev/null && pnpm --version 2>/dev/null || true)
  [[ $have_pnpm == "$want_pnpm" ]] || problems+=("pnpm $want_pnpm needed, found ${have_pnpm:-none}. Install: corepack enable && corepack prepare pnpm@$want_pnpm --activate")
  # CI uses Java 17 (setup-java); java_home -v 17 can return a newer JDK, so the version is read from the JDK itself.
  java_major() { [[ -x $1/bin/java ]] && "$1/bin/java" -version 2>&1 | sed -n '1s/[^"]*"\([0-9]*\).*/\1/p'; }
  jhome=${JAVA_HOME:-}; have_java=$(java_major "$jhome" || true)
  if [[ $have_java != 17 && -x /usr/libexec/java_home ]]; then
    jhome=$(/usr/libexec/java_home -v 17 2>/dev/null || true); have_java=$(java_major "$jhome" || true)
  fi
  if [[ -z $have_java || $have_java -lt 17 ]] && [[ -n ${JAVA_HOME:-} ]]; then jhome=$JAVA_HOME; have_java=$(java_major "$jhome" || true); fi
  if [[ -n $have_java && $have_java -ge 17 ]]; then
    export JAVA_HOME=$jhome PATH="$jhome/bin:$PATH"
    [[ $have_java == 17 ]] || echo "warning: Java $have_java, CI uses 17" >&2
  else problems+=("Java 17 or newer needed (JAVA_HOME=${JAVA_HOME:-unset}, found ${have_java:-none}). Install: brew install openjdk@17, then export JAVA_HOME=\$(/usr/libexec/java_home -v 17) (or the path under \$(brew --prefix openjdk@17)/libexec/openjdk.jdk/Contents/Home)"); fi
  # dotnet applies global.json (version + rollForward latestPatch) itself and fails when no installed SDK matches.
  have_dotnet=$(command -v dotnet >/dev/null && cd "$src/$engine_src" && dotnet --version 2>/dev/null || true)
  [[ -n $have_dotnet ]] || problems+=(".NET SDK $want_dotnet (latestPatch) needed for $engine_src/global.json, none matches. Install: curl -fsSL https://dot.net/v1/dotnet-install.sh | bash -s -- --version $want_dotnet (then put ~/.dotnet first on PATH and set DOTNET_ROOT=~/.dotnet)")
  ndk_dir=${ANDROID_NDK:-$ANDROID_HOME/ndk/$ndk}
  have_ndk=$(sed -n 's/^Pkg.Revision *= *//p' "$ndk_dir/source.properties" 2>/dev/null || true)
  [[ $have_ndk == "$ndk" ]] || problems+=("Android NDK $ndk needed at $ndk_dir, found ${have_ndk:-none}. Install: $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager \"ndk;$ndk\" (or set ANDROID_HOME / ANDROID_NDK)")
  command -v cargo >/dev/null && command -v rustup >/dev/null || problems+=("Rust (rustup and cargo) needed. Install: curl https://sh.rustup.rs -sSf | sh -s -- -y --profile minimal")
  if command -v rustup >/dev/null; then
    RUSTUP_TOOLCHAIN=stable rustup target list --installed 2>/dev/null | grep -qx aarch64-linux-android || problems+=("Rust target aarch64-linux-android missing on the stable toolchain. Install: rustup target add aarch64-linux-android --toolchain stable")
  fi
  if (( ${#problems[@]} )); then printf 'collect-plus-local: NATIVE=1 host tools:\n' >&2; printf '  - %s\n' "${problems[@]}" >&2; exit 1; fi
  echo "host tools: node $(node -v), pnpm $have_pnpm, java $have_java, dotnet $have_dotnet, ndk $have_ndk, $(cargo --version)"
fi
echo "source: $src_mode, commit $commit, dirty: $dirty, $(find "$src" -type f | wc -l | tr -d ' ') files"

# --- 2. WHO's assemblies, from the pinned image, on the host ------------------------------------------------------
icd_image=$(pin_icd_image "$src")
icdapi="$work/cache/icdapi-$(echo "${icd_image##*@sha256:}" | cut -c1-12)"
if [[ ! -s $icdapi/ICD-API.dll ]]; then
  echo "copying /usr/share/icdapi out of $icd_image"
  docker_ok || die "Docker is needed once to copy WHO's assemblies out of $icd_image"
  docker pull --platform linux/amd64 -q "$icd_image" >/dev/null
  id=$(docker create --platform linux/amd64 "$icd_image")
  rm -rf "$icdapi" "$icdapi.tmp"
  docker cp "$id:/usr/share/icdapi" "$icdapi.tmp" && mv "$icdapi.tmp" "$icdapi"; docker rm "$id" >/dev/null
fi
[[ -s $icdapi/ICD-API.dll ]] || die "WHO assemblies missing in $icdapi"

# --- 3. toolchain image and build container (or, NATIVE=1, this host) ---------------------------------------------
build_cmd=(docker build --platform linux/amd64 -t "$image"
  --build-arg "NODE_MAJOR=$(pin_node_major "$src")" --build-arg "PNPM_VERSION=$(pin_pnpm "$src")"
  --build-arg "NDK_VERSION=$ndk" --build-arg "DOTNET_SDK_VERSION=$(pin_dotnet "$src")" "$here")
run_cmd=(docker run --rm --platform linux/amd64 --name digitva-collect-plus-local $([[ -t 1 ]] && echo -t)
  -v "$src:/src:ro" -v "$icdapi:/icdapi:ro" -v "$here:/ci:ro" -v "$out:/out"
  -v digitva-cp-who:/cache/who -v digitva-cp-gradle:/root/.gradle -v digitva-cp-npm:/root/.npm
  -v digitva-cp-pnpm:/cache/pnpm -v digitva-cp-nuget:/root/.nuget/packages
  -v digitva-cp-cargo-registry:/root/.cargo/registry -v digitva-cp-cargo-git:/root/.cargo/git
  -v "digitva-cp-android-$ndk:/opt/android"
  -e "SRC_MODE=$src_mode" -e "SRC_REF=$([[ $src_mode == git ]] && echo "$ref")" -e "SRC_COMMIT=$commit" -e "SRC_DIRTY=$dirty"
  -e "SKIP_CHECKS=${SKIP_CHECKS:-}" -e npm_config_store_dir=/cache/pnpm
  -e "HOST_UID=$(id -u)" -e "HOST_GID=$(id -g)" "$image" /ci/build.sh)
src_ref=""; [[ $src_mode != git ]] || src_ref=$ref
native_cmd=(env NATIVE_BUILD=1 SRC_DIR="$src" ICDAPI_DIR="$icdapi" CACHE_DIR="$work/cache" OUT_DIR="$out" WORK_DIR="$work/w"
  SRC_MODE="$src_mode" SRC_REF="$src_ref" SRC_COMMIT="$commit" SRC_DIRTY="$dirty"
  SKIP_CHECKS="${SKIP_CHECKS:-}" "$here/build.sh")
if [[ $native == 1 ]]; then
  if [[ ${DRY_RUN:-} == 1 ]]; then printf 'DRY_RUN: would run\n'; printf '%q ' "${native_cmd[@]}"; printf '\n'; exit 0; fi
  rm -f "$out"/*.apk "$out/BUILD_OK"
  time "${native_cmd[@]}"
  echo
  echo "APK and checksums: $out"
  echo "LOCAL VERIFICATION BUILD, NOT FOR DISTRIBUTION. Signed with the Expo template's debug key, not the CI release key:"
  grep -E "^Signer #1 certificate (DN|SHA-256)" "$out/SIGNER.txt" || cat "$out/SIGNER.txt"
  exit 0
fi
if [[ ${DRY_RUN:-} == 1 ]]; then
  printf 'DRY_RUN: would run\n'; printf '%q ' "${build_cmd[@]}"; printf '\n'; printf '%q ' "${run_cmd[@]}"; printf '\n'
  exit 0
fi
time "${build_cmd[@]}"
rm -f "$out"/*.apk "$out/BUILD_OK"
"${run_cmd[@]}"
echo
echo "APK and checksums: $out"
echo "LOCAL VERIFICATION BUILD, NOT FOR DISTRIBUTION. Signed with the Expo template's debug key, not the CI release key:"
grep -E "^Signer #1 certificate (DN|SHA-256)" "$out/SIGNER.txt" || cat "$out/SIGNER.txt"
