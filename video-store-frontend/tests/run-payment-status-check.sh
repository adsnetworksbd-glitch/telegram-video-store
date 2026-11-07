#!/bin/sh
# Runs tests/payment-status.check.mts against a temp copy of src/ (pure modules only). Needs Node 22+.
set -e
cd "$(dirname "$0")/.."
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cp -r src tests "$TMP/"
cd "$TMP" && node --experimental-strip-types --no-warnings tests/payment-status.check.mts
