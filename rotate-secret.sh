#!/bin/bash
# Rotates MCP_INTERNAL_SECRET in .env, updates the Stock Image Skill, rebuilds the zip,
# and restarts the app. You still need to re-upload skill-zips/stock-image.zip to Claude.ai.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
SKILLS_REPO="/Users/mike-j4c/Projects/proxima-claude-org-skills"
SKILL_FILE="$SKILLS_REPO/Stock-Image-Skill/SKILL.md"

# ── 1. Generate new secret ────────────────────────────────────────────────────
NEW_SECRET=$(openssl rand -hex 32)
echo "New secret generated."

# ── 2. Update .env ────────────────────────────────────────────────────────────
OLD_SECRET=$(grep "^MCP_INTERNAL_SECRET=" "$ENV_FILE" | cut -d= -f2-)
if [ -z "$OLD_SECRET" ]; then
  echo "ERROR: MCP_INTERNAL_SECRET not found in $ENV_FILE"
  exit 1
fi

sed -i '' "s|^MCP_INTERNAL_SECRET=.*|MCP_INTERNAL_SECRET=$NEW_SECRET|" "$ENV_FILE"
echo ".env updated."

# ── 3. Update skill file ──────────────────────────────────────────────────────
if [ ! -f "$SKILL_FILE" ]; then
  echo "ERROR: Skill file not found at $SKILL_FILE"
  exit 1
fi

sed -i '' "s|$OLD_SECRET|$NEW_SECRET|g" "$SKILL_FILE"
echo "Skill file updated."

# ── 4. Rebuild skill zip ──────────────────────────────────────────────────────
cd "$SKILLS_REPO"
./build-skills.sh 2>&1 | grep "stock-image\|ERROR"
echo "Zip rebuilt at $SKILLS_REPO/skill-zips/stock-image.zip"

# ── 5. Restart app ────────────────────────────────────────────────────────────
cd "$SCRIPT_DIR"
pkill -f "src.app" 2>/dev/null || true
lsof -ti:5000 | xargs kill -9 2>/dev/null || true
sleep 1
.venv/bin/python -m src.app >> /tmp/app.log 2>&1 &
sleep 3
if curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/ | grep -q "302\|200"; then
  echo "App restarted on port 5000."
else
  echo "WARNING: App may not have started — check /tmp/app.log"
fi

echo ""
echo "✓ Done. Upload $SKILLS_REPO/skill-zips/stock-image.zip to Claude.ai org settings to complete the rotation."
