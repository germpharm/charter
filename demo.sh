#!/bin/bash
# Charter Demo — shows the full workflow in a clean environment
# Usage: bash demo.sh
# This creates a temp directory, runs Charter commands, and shows the output.

set -e

DEMO_DIR=$(mktemp -d)
echo "Charter Demo"
echo "============"
echo ""
echo "Working in: $DEMO_DIR"
echo ""

cd "$DEMO_DIR"

# Step 1: Init
echo "$ charter init --domain healthcare --non-interactive"
echo ""
charter init --domain healthcare --non-interactive
echo ""

# Step 2: Generate
echo "---"
echo ""
echo "$ charter generate"
echo ""
charter generate
echo ""

# Step 3: Show the generated CLAUDE.md
echo "---"
echo ""
echo "$ head -30 CLAUDE.md"
echo ""
head -30 CLAUDE.md
echo ""

# Step 4: Identity
echo "---"
echo ""
echo "$ charter identity"
echo ""
charter identity
echo ""

# Step 5: Status
echo "---"
echo ""
echo "$ charter status"
echo ""
charter status
echo ""

# Step 6: Audit
echo "---"
echo ""
echo "$ charter audit"
echo ""
charter audit
echo ""

echo "---"
echo ""
echo "Done. Charter governance is active."
echo "Config: $DEMO_DIR/charter.yaml"
echo "Instructions: $DEMO_DIR/CLAUDE.md"
echo ""

# Cleanup prompt
echo "Run 'rm -rf $DEMO_DIR' to clean up."
