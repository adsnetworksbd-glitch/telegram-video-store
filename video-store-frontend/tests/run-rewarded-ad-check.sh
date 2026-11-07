#!/bin/sh
# Runs tests/rewarded-ad.check.mts against a temp copy of src/ (import.meta.env replaced). Needs Node 22+.
set -e
cd "$(dirname "$0")/.."
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cp -r src tests "$TMP/"
sed -i 's/import\.meta\.env/globalThis.__VITE_ENV__/g' "$TMP/src/utils/rewardedAd.ts"
cd "$TMP" && node --experimental-strip-types --no-warnings tests/rewarded-ad.check.mts
