#!/bin/bash
mkdir -p backups static/uploads/products static/uploads/influencers
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
