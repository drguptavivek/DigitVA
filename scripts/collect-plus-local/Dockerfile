# Toolchain for the local Collect Plus build (scripts/collect-plus-local/run.sh). Layers only, no repo code: reruns
# skip this setup. Build with --platform linux/amd64 (run.sh does) because NativeAOT for linux-bionic-arm64 needs a Linux x64 ILC host.
# Versions arrive as build args from the repo's own pins (pins.sh); the defaults here are only for a bare `docker build`.
FROM ubuntu:24.04
ARG NODE_MAJOR=22
ARG PNPM_VERSION=11.9.0
ARG NDK_VERSION=28.2.13676358
ARG DOTNET_SDK_VERSION=10.0.402
ARG CMDLINE_TOOLS=11076708
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq && apt-get install -y -qq curl ca-certificates git unzip xz-utils openjdk-17-jdk-headless libicu74 build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - >/dev/null \
    && apt-get install -y -qq nodejs && rm -rf /var/lib/apt/lists/* \
    && corepack enable && corepack prepare "pnpm@${PNPM_VERSION}" --activate
ENV ANDROID_HOME=/opt/android COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN mkdir -p "$ANDROID_HOME/cmdline-tools" \
    && curl -fsSL -o /tmp/cmdline.zip "https://dl.google.com/android/repository/commandlinetools-linux-${CMDLINE_TOOLS}_latest.zip" \
    && unzip -q /tmp/cmdline.zip -d "$ANDROID_HOME/cmdline-tools" && mv "$ANDROID_HOME/cmdline-tools/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest" \
    && rm /tmp/cmdline.zip \
    && { yes || true; } | "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --licenses >/dev/null \
    && "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" "ndk;${NDK_VERSION}" >/dev/null
ENV DOTNET_ROOT=/opt/dotnet DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 PATH=/opt/dotnet:/root/.cargo/bin:$PATH
RUN curl -fsSL https://dot.net/v1/dotnet-install.sh | bash -s -- --version "${DOTNET_SDK_VERSION}" --install-dir /opt/dotnet >/dev/null
# CI uses the stable toolchain (collect-plus-release.yml); this layer is as old as the image, rebuild with --pull to refresh.
RUN curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable >/dev/null \
    && rustup target add aarch64-linux-android >/dev/null
