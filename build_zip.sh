#!/bin/sh
# Builds ../motogp_master_editor.zip (the tool) with the Blender add-on zip inside it.
set -e
cd "$(dirname "$0")"
T=$(mktemp -d)
cp -r blender_addon/mgp_projectors "$T/" && cp uprops.py mgp_core.py "$T/mgp_projectors/"
find "$T" -name __pycache__ -prune -exec rm -rf {} +
(cd "$T" && zip -qr mgp24_projectors_addon.zip mgp_projectors)
cp "$T/mgp24_projectors_addon.zip" .
rm -f ../motogp_master_editor.zip
zip -q ../motogp_master_editor.zip *.py webui.html README.txt start.bat mgp24_projectors_addon.zip
rm -rf "$T" mgp24_projectors_addon.zip
