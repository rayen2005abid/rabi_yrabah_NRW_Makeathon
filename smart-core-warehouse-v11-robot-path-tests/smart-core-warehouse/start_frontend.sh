#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/frontend"
if [ ! -d node_modules ]; then
  npm install
fi
exec npm run dev
