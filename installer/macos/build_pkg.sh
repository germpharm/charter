#!/bin/bash
# Build the Charter macOS installer .pkg
# Run from: charter/installer/macos/

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"
VERSION="0.7.0"

echo "Building Charter $VERSION installer..."

# Clean
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/payload"

# Make postinstall executable
chmod +x "$SCRIPT_DIR/scripts/postinstall"

# Build the component package
# The payload is empty — all work happens in the postinstall script
pkgbuild \
    --nopayload \
    --scripts "$SCRIPT_DIR/scripts" \
    --identifier "com.germpharm.charter.pkg" \
    --version "$VERSION" \
    "$BUILD_DIR/charter-core.pkg"

# Build the product archive with the Distribution.xml (adds welcome/conclusion pages)
productbuild \
    --distribution "$SCRIPT_DIR/Distribution.xml" \
    --resources "$SCRIPT_DIR/resources" \
    --package-path "$BUILD_DIR" \
    "$SCRIPT_DIR/Charter-$VERSION.pkg"

echo ""
echo "Done: $SCRIPT_DIR/Charter-$VERSION.pkg"
echo "Double-click to install, or distribute to users."

# Clean up intermediate files
rm -rf "$BUILD_DIR"
