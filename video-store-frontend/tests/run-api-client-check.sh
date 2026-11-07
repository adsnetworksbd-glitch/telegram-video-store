#!/bin/sh
# Runs tests/api-client.check.mts against a temporary copy of src/ in which
# `import.meta.env` (a Vite-only construct) is replaced by a test object, so it
# can run under plain Node/tsx. Requires `npm install` first (real axios + zustand).
set -e
cd "$(dirname "$0")/.."
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cp -r src tests "$TMP/"
cp package.json tsconfig.json "$TMP/"
find "$TMP/src" -name '*.ts' -o -name '*.tsx' | xargs sed -i 's/import\.meta\.env/globalThis.__VITE_ENV__/g'
ln -s "$(pwd)/${NODE_MODULES_DIR:-node_modules}" "$TMP/node_modules"
cd "$TMP"
npx tsx tests/api-client.check.mts
