#!/bin/bash
# Construit « Imprimer étiquette Chronopost.app » à côté du script.
# Icône facultative : dépose un fichier icone.icns dans ce dossier avant de lancer.
set -euo pipefail
ICI="$(cd "$(dirname "$0")" && pwd)"
APP="$ICI/Imprimer étiquette Chronopost.app"
TMP="$(mktemp -d)"
sed "s|@@SCRIPT@@|$ICI/imprimer_etiquette.py|" "$ICI/app/Imprimer-etiquette.applescript" > "$TMP/app.applescript"
rm -rf "$APP"
osacompile -o "$APP" "$TMP/app.applescript"
if [ -f "$ICI/icone.icns" ]; then
  cp "$ICI/icone.icns" "$APP/Contents/Resources/droplet.icns"
  /usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$APP/Contents/Info.plist" 2>/dev/null || true
  rm -f "$APP/Contents/Resources/Assets.car"
  codesign --force --deep -s - "$APP"
fi
rm -rf "$TMP"
echo "Application construite : $APP"
