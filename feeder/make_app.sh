#!/bin/zsh
# Build "RelicFeeder.app" (menu bar, no Dock icon) from the SwiftPM release build. Pattern: ane-oracle
# tools/ane-embed-app/make_app.sh. Ad-hoc signed (no SMAppService in v1: docs/RELICFEEDER.md).
#   zsh make_app.sh && open RelicFeeder.app
set -euo pipefail
cd "${0:A:h}"
swift build -c release --product RelicFeeder
APP="RelicFeeder.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp .build/release/RelicFeeder "$APP/Contents/MacOS/RelicFeeder"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>RelicFeeder</string>
  <key>CFBundleIdentifier</key><string>studio.soulbrews.relic-feeder</string>
  <key>CFBundleExecutable</key><string>RelicFeeder</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <!-- the hub is plain http on the tailnet -->
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsArbitraryLoads</key><true/></dict>
</dict></plist>
PLIST
codesign --force --sign - "$APP"
echo "built $PWD/$APP"
