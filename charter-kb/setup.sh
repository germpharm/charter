#!/bin/bash
echo "=== Charter KB Activation ==="

# Create the live knowledge vault in your working directory
mkdir -p ~/AI\ Ethical\ Engine/knowledge
cp -r knowledge-template/* ~/AI\ Ethical\ Engine/knowledge/ 2>/dev/null || true

# Install the logger
cp tools/charter-logger.py ~/AI\ Ethical\ Engine/tools/ 2>/dev/null || true

echo "Charter KB activated."
echo "Open Obsidian -> 'Open folder as vault' -> ~/AI Ethical Engine/knowledge"
echo "Run 'python tools/generate-indexes.py' to build fresh indexes (they will auto-log to the chain)."
