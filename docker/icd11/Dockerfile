# WHO ICD-11 API 2.6.0 + DORIS 1.2.0 served by the Rust in-process host
# (desktop/crates/digitva-icd11, vendor/who-icd11-api) instead of the
# whoicd/icd-api container. Build context: the repository root.
#
# The image holds only our binary on the Microsoft ASP.NET Core runtime. The
# unmodified WHO assemblies and offline data are not baked in: the binary
# downloads them on first start into the /var/lib/icd11 volume and verifies
# every file against the SHA-256 pins in vendor/who-icd11-api/src/bootstrap.rs
# (and re-verifies them on every start).

FROM rust:1.99-slim-bookworm@sha256:16113eb5d5c1e25d9359f40115225ce8719997fb0d9a3dab83e921da0308992f AS build
WORKDIR /src
COPY desktop/Cargo.toml desktop/Cargo.lock desktop/
COPY desktop/crates desktop/crates
COPY vendor/who-icd11-api vendor/who-icd11-api
# Only so the workspace resolves (digitva-smartva path dependency); not compiled.
COPY vendor/smartva-analyze/rust/Cargo.toml vendor/smartva-analyze/rust/Cargo.toml
COPY vendor/smartva-analyze/rust/src vendor/smartva-analyze/rust/src
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/src/desktop/target \
    cd desktop \
    && cargo build --release --locked -p digitva-icd11 --bin digitva-icd11-server \
    && cp target/release/digitva-icd11-server /usr/local/bin/

# ICD-API.dll is framework-dependent net10.0 and needs both
# Microsoft.NETCore.App and Microsoft.AspNetCore.App (the aspnet image).
FROM mcr.microsoft.com/dotnet/aspnet:10.0.13@sha256:d5633778c754e89a386882eddf8dbee6942447a8a4b8267c19cf1e1158d0b0ac
COPY --from=build /usr/local/bin/digitva-icd11-server /usr/local/bin/
COPY docker/icd11/healthcheck.sh /usr/local/bin/icd11-healthcheck
RUN mkdir -p /var/lib/icd11 && chown app:app /var/lib/icd11
USER app
ENV DIGITVA_ICD11_RUNTIME_DIR=/var/lib/icd11 \
    DOTNET_ROOT=/usr/share/dotnet
VOLUME /var/lib/icd11
EXPOSE 80
HEALTHCHECK --interval=1m --timeout=10s --start-period=2m --retries=3 CMD ["icd11-healthcheck"]
ENTRYPOINT ["digitva-icd11-server", "--bind", "http://0.0.0.0:80"]
