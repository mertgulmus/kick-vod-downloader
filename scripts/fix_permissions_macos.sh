#!/bin/bash
# Fix ChromeDriver permissions and quarantine on macOS

set -euo pipefail

echo "Fixing ChromeDriver permissions and quarantine..."

USER_HOME="/Users/$USER"
WDM_DIR="$USER_HOME/.wdm"
SELENIUM_CACHE="$USER_HOME/Library/Caches/selenium"

# Ensure base directories exist with sane perms
mkdir -p "$WDM_DIR" "$SELENIUM_CACHE" || true
chmod 755 "$WDM_DIR" "$SELENIUM_CACHE" || true

# Helper: remove quarantine and ensure executable bit on candidate binaries
fix_driver_dir() {
  local dir="$1"
  if [ -d "$dir" ]; then
    echo "- Processing $dir"
    # Remove quarantine recursively (ignore errors if not present)
    xattr -dr com.apple.quarantine "$dir" 2>/dev/null || true
    # Ensure binaries are executable
    find "$dir" -type f \( -name "chromedriver" -o -name "Chrome.app" -o -name "Google Chrome" \) -exec chmod +x {} + 2>/dev/null || true
    # Ad-hoc sign chromedriver if present (Gatekeeper often requires this)
    if [ -f "$dir/chromedriver" ]; then
      codesign --force --deep --sign - "$dir/chromedriver" 2>/dev/null || true
    fi
  fi
}

# Known webdriver_manager locations (versioned subdirs)
for d in "$WDM_DIR/drivers/chromedriver"/*/*/*; do
  fix_driver_dir "$d"
done

# Selenium Manager cache sometimes stores drivers too
for d in "$SELENIUM_CACHE"/*; do
  fix_driver_dir "$d"
done

echo "ChromeDriver permissions/quarantine fixed. You can now run the app without sudo."
