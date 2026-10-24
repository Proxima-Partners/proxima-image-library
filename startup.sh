#!/bin/bash
# Azure App Service startup script
# One process preserves current in-memory state. Concurrency changes are Phase 3.
exec gunicorn \
  --bind=0.0.0.0:${PORT:-8000} \
  --workers=1 \
  --timeout=300 \
  --keep-alive=5 \
  --access-logfile=- \
  --error-logfile=- \
  src.app:app
