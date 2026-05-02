#!/usr/bin/env bash
# Pre-production test suite for Proxima Image Library.
# Run: ./test_preproduction.sh
# Requires: local Flask server running on port 5000

set -euo pipefail

PASS=0
FAIL=0

run_test() {
  local name="$1"
  local script="$2"
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "▶ $name"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  if python3 "$script"; then
    echo "✅ PASSED: $name"
    PASS=$((PASS + 1))
  else
    echo "❌ FAILED: $name"
    FAIL=$((FAIL + 1))
  fi
}

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "  PROXIMA IMAGE LIBRARY — PRE-PRODUCTION TEST SUITE"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════════════════════════════"

run_test "Library Diversity"        test_library_diversity.py
run_test "Preview Guidance"         test_preview_guidance.py
run_test "Preview Endpoint"         test_preview_endpoint.py
run_test "End-to-End Workflow"      test_e2e_workflow.py
run_test "Claude Integration"       test_claude_integration.py

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "  AUTOMATED RESULTS: $PASS passed, $FAIL failed"
echo "════════════════════════════════════════════════════════════════════"

echo ""
echo "┌─────────────────────────────────────────────────────────────────┐"
echo "│  MANUAL STEPS REQUIRED BEFORE SHIPPING                         │"
echo "├─────────────────────────────────────────────────────────────────┤"
echo "│  1. /ultrareview — full codebase audit (redundancy, efficiency) │"
echo "│     Type /ultrareview in Claude Code to launch                  │"
echo "│                                                                 │"
echo "│  2. Smoke-test the UI in a browser:                             │"
echo "│     • Home page loads, Recently Added strip shows images        │"
echo "│     • Search returns results                                    │"
echo "│     • Upload flow completes (alt text + tags generated)         │"
echo "│     • Maintenance: Folder Ingest, Purge, Duplicate Detector     │"
echo "│     • Bulk Re-Tag runs without errors                           │"
echo "│                                                                 │"
echo "│  3. Verify SharePoint connection (STORAGE_MODE=sharepoint)      │"
echo "└─────────────────────────────────────────────────────────────────┘"
echo ""

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
