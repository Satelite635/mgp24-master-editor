#!/bin/sh
# Builds ../motogp_master_editor.zip (the tool) with the Blender add-on zip inside it.
set -e
cd "$(dirname "$0")"
T=$(mktemp -d)
cp -r blender_addon/mgp_projectors "$T/" && cp uprops.py mgp_core.py projfile.py "$T/mgp_projectors/"
find "$T" -name __pycache__ -prune -exec rm -rf {} +
(cd "$T" && zip -qr mgp24_projectors_addon.zip mgp_projectors)
cp "$T/mgp24_projectors_addon.zip" .
rm -f ../motogp_master_editor.zip
# Microsoft texconv (MIT licence) for good DXT/BC5/BC7 encoding; skipped if it can't be downloaded
curl -sSLf -o "$T/texconv.exe" https://github.com/microsoft/DirectXTex/releases/latest/download/texconv.exe || rm -f "$T/texconv.exe"
[ -f "$T/texconv.exe" ] && cp "$T/texconv.exe" . || echo "texconv.exe not downloaded - zip ships without it"
zip -q ../motogp_master_editor.zip *.py webui.html README.txt start.bat mgp24_projectors_addon.zip $( [ -f texconv.exe ] && echo texconv.exe )
rm -rf "$T" mgp24_projectors_addon.zip texconv.exe
