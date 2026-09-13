#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/backend"

# Simple local mode: always use SQLite. Docker Compose uses PostgreSQL separately.
export DATABASE_URL='sqlite:///./warehouse.db'
export CONFIG_DIR='../config'
export EMBEDDED_MODE='mock'

if [ ! -x .venv/bin/python ]; then
  echo "[1/4] Creating virtual environment..."
  python3 -m venv .venv
  echo "[2/4] Installing backend dependencies from requirements.txt..."
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
else
  echo "[1/4] Virtual environment already exists."
  echo "[2/4] Synchronizing backend dependencies..."
  .venv/bin/python -m pip install -r requirements.txt
fi

echo "[3/4] Applying database migrations..."
.venv/bin/python -m alembic upgrade head

echo "[4/4] Starting FastAPI..."
echo "Backend: http://localhost:8000"
echo "Health:  http://localhost:8000/health"
echo "Swagger: http://localhost:8000/docs"
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
