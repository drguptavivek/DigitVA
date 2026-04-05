#!/bin/bash
# Extract ffmpeg + ffprobe static binaries and their shared libs
# into bin/ for volume-mounting into app containers.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$SCRIPT_DIR/../bin"

echo "Building ffmpeg extraction container..."
docker build -t ffmpeg-extractor -f - . <<'DF'
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg
# Copy binaries and all their shared library dependencies
RUN mkdir -p /out/bin /out/lib && \
    cp /usr/bin/ffmpeg /usr/bin/ffprobe /out/bin/ && \
    ldd /usr/bin/ffmpeg | grep "=> /" | awk '{print $3}' | xargs -I '{}' cp -v '{}' /out/lib/ && \
    ldd /usr/bin/ffprobe | grep "=> /" | awk '{print $3}' | xargs -I '{}' cp -v '{}' /out/lib/ 2>/dev/null || true && \
    cp /lib64/ld-linux-x86-64.so.2 /out/lib/ 2>/dev/null || true
CMD ["cp", "-a", "/out/.", "/dest/"]
DF

echo "Extracting binaries to $BIN_DIR..."
rm -rf "$BIN_DIR"
mkdir -p "$BIN_DIR"
docker run --rm -v "$BIN_DIR:/dest" ffmpeg-extractor

# Cleanup
docker rmi ffmpeg-extractor > /dev/null 2>&1 || true

echo "Done. Binaries in $BIN_DIR/:"
ls -lh "$BIN_DIR/bin/"
echo "Libs in $BIN_DIR/lib/:"
ls "$BIN_DIR/lib/" | wc -l
echo "Total size:"
du -sh "$BIN_DIR"
