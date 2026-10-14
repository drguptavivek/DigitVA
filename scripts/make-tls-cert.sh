#!/bin/bash
# Issue a self-signed server certificate for split production
# (docs/current-state/split-production-tls.md).
#
#   sudo [KEY_ALG=rsa:3072] scripts/make-tls-cert.sh <out_dir> <CN> <subjectAltName> [days]
#
#   App VM: sudo scripts/make-tls-cert.sh /etc/digitva-app/tls.new <BACKEND_TLS_NAME> \
#             DNS:<BACKEND_TLS_NAME>,DNS:localhost,IP:<APP_PRIVATE_IP>
#   DB VM:  sudo scripts/make-tls-cert.sh /etc/postgresql/18/main/tls.new <DB_TLS_CN> IP:<DB_PRIVATE_IP>
#
# Run it on the host that serves the certificate: server.key never leaves it.
# Writes server.key (0600), server.crt and ca.crt (a copy of server.crt: the
# public file clients trust). It never overwrites a key, so renewal issues
# into a new directory that is swapped in afterwards. Self-contained: on a
# host without the repository, paste this file.
set -euo pipefail

if [ $# -lt 3 ]; then
  sed -n '5,9p' "$0" >&2
  exit 2
fi
out=$1
cn=$2
san=$3
days=${4:-365}
key_alg=${KEY_ALG:-rsa:3072}

if [ -e "$out/server.key" ]; then
  echo "refusing: $out/server.key already exists; use a new directory" >&2
  exit 1
fi

umask 077
install -d -m 0755 "$out"

openssl req -x509 -newkey "$key_alg" -nodes -days "$days" \
  -subj "/CN=$cn" \
  -addext "subjectAltName=$san" \
  -addext "extendedKeyUsage=serverAuth" \
  -keyout "$out/server.key" -out "$out/server.crt" 2>/dev/null

cp "$out/server.crt" "$out/ca.crt"
chmod 0600 "$out/server.key"
chmod 0644 "$out/server.crt" "$out/ca.crt"

openssl verify -CAfile "$out/ca.crt" "$out/server.crt"
openssl x509 -in "$out/server.crt" -noout -subject -enddate -ext subjectAltName
