#!/bin/zsh
# Builds Hermes Wall and installs it for this user:
#   ~/Applications/Hermes Wall Reader.app   copies your chat with the agent out of Messages (needs Full Disk Access)
#   ~/Library/Application Support/Hermes Wall/
#       bin/hermes-wall    draws the Lock Screen and serves it to the phone
#       config.json        the agent's contact name, the port and the token the phone sends (made once, kept)
#   two launch agents that keep both running, logging to ~/Library/Logs/Hermes Wall/
#
#   ./install.sh "Hermes"          the first time (the agent's name as its contact is called)
#   ./install.sh                   after changing the code
#
# The reader is replaced only when its code changed: macOS ties Full Disk Access to the exact build, so a new reader
# has to be given access again (this script says so).
set -euo pipefail
here=${0:A:h}
repo=${here:h}
label=${HERMES_WALL_LABEL:-local.hermeswall}
support="$HOME/Library/Application Support/Hermes Wall"
logs="$HOME/Library/Logs/Hermes Wall"
reader_app="$HOME/Applications/Hermes Wall Reader.app"
port=${HERMES_WALL_PORT:-7337}

swift build -c release --package-path "$here" 2>&1 | grep -E "error|warning: |Build complete" || true
built="$here/.build/release"
[[ -x "$built/hermes-wall" && -x "$built/hermes-wall-reader" ]] || { echo "build failed"; exit 1; }
mkdir -p "$support/bin" "$logs" "$HOME/Applications" "$HOME/Library/LaunchAgents"

if [[ ! -f "$support/config.json" ]]; then
  [[ -n "${1:-}" ]] || { echo "First install: give the agent's contact name, e.g. ./install.sh \"Hermes\""; exit 1; }
  AGENT="$1" PORT="$port" TOKEN="$(openssl rand -hex 24)" ASSETS="$repo/assets" TOKENS="$repo/design/tokens.json" \
    python3 -c 'import json, os; print(json.dumps({"agent": os.environ["AGENT"], "handles": [], "limit": 60,
      "port": int(os.environ["PORT"]), "token": os.environ["TOKEN"], "assets": os.environ["ASSETS"],
      "tokens": os.environ["TOKENS"]}, indent=2))' > "$support/config.json"
  chmod 600 "$support/config.json"
  echo "wrote $support/config.json"
fi

# The reader, as an app so it can be picked in System Settings › Privacy & Security › Full Disk Access.
new_reader=0
if ! cmp -s "$built/hermes-wall-reader" "$reader_app/Contents/MacOS/hermes-wall-reader.source" 2>/dev/null; then
  rm -rf "$reader_app"
  mkdir -p "$reader_app/Contents/MacOS"
  cp "$built/hermes-wall-reader" "$reader_app/Contents/MacOS/hermes-wall-reader"
  cp "$built/hermes-wall-reader" "$reader_app/Contents/MacOS/hermes-wall-reader.source"   # to tell a new build
  cat > "$reader_app/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>$label.reader</string>
  <key>CFBundleName</key><string>Hermes Wall Reader</string>
  <key>CFBundleExecutable</key><string>hermes-wall-reader</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSUIElement</key><true/>
</dict></plist>
EOF
  codesign --force --sign - --identifier "$label.reader" "$reader_app" 2>/dev/null
  new_reader=1
fi
cp "$built/hermes-wall" "$support/bin/hermes-wall"
codesign --force --sign - "$support/bin/hermes-wall" 2>/dev/null

agent() {   # name, restart (1 when its program changed), program, arguments...
  local name=$1 restart=$2; shift 2
  local plist="$HOME/Library/LaunchAgents/$label.$name.plist" service="gui/$UID/$label.$name"
  local args=""
  for a in "$@"; do args+="<string>${a//&/&amp;}</string>"; done
  cat > "$plist.new" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label.$name</string>
  <key>ProgramArguments</key><array>$args</array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$logs/$name.log</string>
  <key>StandardErrorPath</key><string>$logs/$name.log</string>
</dict></plist>
EOF
  if [[ -f $plist ]] && cmp -s "$plist.new" "$plist" && launchctl print "$service" >/dev/null 2>&1; then
    rm -f "$plist.new"
    if (( restart )); then launchctl kickstart -k "$service"; fi
  else
    mv "$plist.new" "$plist"
    launchctl bootout "$service" 2>/dev/null || true
    for _ in {1..50}; do launchctl print "$service" >/dev/null 2>&1 || break; sleep 0.1; done   # bootout returns early
    launchctl bootstrap "gui/$UID" "$plist"
  fi
}
agent reader $new_reader "$reader_app/Contents/MacOS/hermes-wall-reader"
agent server 1 "$support/bin/hermes-wall" serve

echo "installed: reader and server running (logs in $logs)"
if (( new_reader )); then
  echo "The reader is new: give \"Hermes Wall Reader\" Full Disk Access in System Settings › Privacy & Security ›"
  echo "Full Disk Access (remove an older entry of the same name first), then run:"
  echo "  launchctl kickstart -k gui/$UID/$label.reader"
fi
