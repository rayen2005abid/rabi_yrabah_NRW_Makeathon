#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/backend"
export DATABASE_URL='sqlite:///./warehouse.db'
export CONFIG_DIR='../config'
export EMBEDDED_MODE='mock'
if [ ! -x .venv/bin/python ]; then
  echo "Backend environment not installed. Run ./start_backend.sh once first."
  exit 1
fi
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.demo.seed
echo "Demo data seeded successfully."
