#!/bin/bash
mkdir -p backups static/uploads/products static/uploads/influencers

# Print local IP for LAN access
echo ""
echo "=== BLEND PUNCH OS — Dev Server ==="
HOST_IP=$(hostname -I | awk '{print $1}')
echo "  Local:   http://localhost:8000"
echo "  Network: http://${HOST_IP}:8000"
echo ""
echo "  For internet access, run in another terminal:"
echo "    ngrok http 8000"
echo "    → https://<random>.ngrok-free.app"
echo "==================================="
echo ""

uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
