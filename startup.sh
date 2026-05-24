#!/bin/bash
# Azure App Service startup script
# SSE streams need long timeout; 2 workers avoids port contention on App Service
gunicorn \
  --bind=0.0.0.0:${PORT:-8000} \
  --workers=1 \
  --timeout=300 \
  --keep-alive=5 \
  --access-logfile=- \
  --error-logfile=- \
  src.app:app
