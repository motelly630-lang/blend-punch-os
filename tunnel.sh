#!/bin/bash
# Cloudflare Quick Tunnel — no account or config needed
# Gives a public HTTPS URL like https://abc123.trycloudflare.com
# URL changes every time you restart. For a permanent URL, use a named tunnel.

echo ""
echo "=== BLEND PUNCH OS — Cloudflare Tunnel ==="
echo "  Make sure the server is running first:"
echo "    bash start-dev.sh"
echo ""
echo "  Opening tunnel to http://localhost:8000 ..."
echo "  Look for a line like:"
echo "    https://xxxx-xxxx.trycloudflare.com"
echo "==========================================="
echo ""

~/.local/bin/cloudflared tunnel --url http://localhost:8000
