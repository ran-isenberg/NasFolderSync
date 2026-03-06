#!/bin/bash
set -e

echo ""
echo "╔══════════════════════════════════════╗"
echo "║       UNasSync  Builder             ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. Check Homebrew ──────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
  echo "❌  Homebrew not found. Install it first: https://brew.sh"
  exit 1
fi

# ── 2. Check / install rclone ──────────────────────────────────────────
if ! command -v rclone &>/dev/null; then
  echo "📦  Installing rclone..."
  brew install rclone
else
  echo "✅  rclone already installed"
fi

# ── 3. Check / install Python 3 ───────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo "📦  Installing Python 3..."
  brew install python
else
  echo "✅  Python 3: $(python3 --version)"
fi

# ── 4. Check / install uv ─────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
  echo "📦  Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
else
  echo "✅  uv already installed"
fi

# ── 5. Install Python dependencies ───────────────────────────────────
echo ""
echo "📦  Installing Python packages with uv..."
uv sync

# ── 6. Install create-dmg ─────────────────────────────────────────────
if ! command -v create-dmg &>/dev/null; then
  echo "📦  Installing create-dmg..."
  brew install create-dmg
else
  echo "✅  create-dmg already installed"
fi

# ── 7. Build the .app ─────────────────────────────────────────────────
echo ""
echo "🔨  Building UNasSync.app..."
uv run pyinstaller UNasSync.spec --noconfirm --clean

APP_SRC="dist/UNasSync.app"

if [ ! -d "$APP_SRC" ]; then
  echo "❌  Build failed — dist/UNasSync.app not found"
  exit 1
fi

echo "✅  App built successfully"

# ── 8. Generate icon (simple PNG → icns) ──────────────────────────────
echo ""
echo "🎨  Generating app icon..."

ICON_DIR="icon.iconset"
mkdir -p "$ICON_DIR"

python3 - <<'PYEOF'
import os, struct, zlib

def make_png(size, color=(100, 160, 255)):
    """Create a minimal solid-color PNG."""
    def chunk(name, data):
        c = zlib.crc32(name + data) & 0xffffffff
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', c)

    w = h = size
    raw = b''
    for _ in range(h):
        row = b'\x00'
        for _ in range(w):
            row += bytes(color) + b'\xff'
        raw += row

    compressed = zlib.compress(raw, 9)
    png  = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', compressed)
    png += chunk(b'IEND', b'')
    return png

sizes = [16, 32, 64, 128, 256, 512, 1024]
for s in sizes:
    with open(f"icon.iconset/icon_{s}x{s}.png", "wb") as f:
        f.write(make_png(s))
    if s <= 512:
        with open(f"icon.iconset/icon_{s}x{s}@2x.png", "wb") as f:
            f.write(make_png(s * 2))

print("  PNG frames written")
PYEOF

iconutil -c icns "$ICON_DIR" -o UNasSync.icns 2>/dev/null || true

if [ -f "UNasSync.icns" ]; then
  cp UNasSync.icns "$APP_SRC/Contents/Resources/UNasSync.icns"
  /usr/libexec/PlistBuddy -c "Set :CFBundleIconFile UNasSync" \
    "$APP_SRC/Contents/Info.plist" 2>/dev/null || true
  echo "✅  Icon applied"
fi

rm -rf "$ICON_DIR"

# ── 9. Build the DMG ──────────────────────────────────────────────────
echo ""
echo "💿  Building UNasSync.dmg..."

DMG_OUT="UNasSync.dmg"
[ -f "$DMG_OUT" ] && rm "$DMG_OUT"

create-dmg \
  --volname "UNasSync" \
  --volicon "UNasSync.icns" \
  --window-pos 200 120 \
  --window-size 560 340 \
  --icon-size 100 \
  --icon "UNasSync.app" 140 170 \
  --hide-extension "UNasSync.app" \
  --app-drop-link 420 170 \
  "$DMG_OUT" \
  "dist/" \
  || true  # exit 2 is normal when app is unsigned

if [ -f "$DMG_OUT" ]; then
  echo "✅  UNasSync.dmg created"
else
  echo "⚠️  DMG not created — continuing with direct install"
fi

# ── 10. Install & Launch (only with --install flag) ──────────────────
if [ "${1:-}" = "--install" ]; then
  echo ""
  APP_DST="/Applications/UNasSync.app"

  if [ -d "$APP_DST" ]; then
    echo "🗑   Removing old version..."
    rm -rf "$APP_DST"
  fi

  cp -r "$APP_SRC" "/Applications/"
  echo "✅  Installed to /Applications"

  # Strip quarantine so Gatekeeper doesn't block first launch
  xattr -rd com.apple.quarantine "/Applications/UNasSync.app" 2>/dev/null || true

  echo ""
  echo "🚀  Launching UNasSync..."
  open "/Applications/UNasSync.app"

  echo ""
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║  ✅  Done!                                                    ║"
  echo "║                                                              ║"
  echo "║  • App running — look for ☁️  in your menu bar (top right)   ║"
  echo "║  • UNasSync.dmg available in project directory              ║"
  echo "║  • Click ☁️  → Configure to set your NAS path               ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
else
  echo ""
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║  ✅  Build complete!                                         ║"
  echo "║                                                              ║"
  echo "║  • dist/UNasSync.app ready                                 ║"
  echo "║  • UNasSync.dmg ready (if create-dmg succeeded)            ║"
  echo "║                                                              ║"
  echo "║  Run './build.sh --install' to install & launch              ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
fi
