#!/bin/bash

set -e

echo "Building FGSEditor Executable with PyInstaller (Linux)..."
echo ""
echo "Please wait..."

rm -rf build dist

if [ -f ".venv/bin/pyinstaller" ]; then
    PYINSTALLER=".venv/bin/pyinstaller"
elif command -v pyinstaller &> /dev/null; then
    PYINSTALLER="pyinstaller"
else
    echo "Error: PyInstaller not found. Please install it or activate your virtual environment."
    exit 1
fi

$PYINSTALLER --noconfirm --noconsole --onefile \
    --icon="images/icon.ico" \
    --add-data "images:images" \
    --hidden-import="fgseditor_qt.core" \
    --hidden-import="fgseditor_qt.math" \
    --hidden-import="fgseditor_qt.tools" \
    --hidden-import="fgseditor_qt.ui" \
    --hidden-import="fgseditor_qt.ui.panels" \
    --hidden-import="fgseditor_qt.panels" \
    --name "FGSEditor" \
    --paths="$(pwd)" \
    fgseditor_qt/fgsview_loader.py

echo ""
echo "Copying images, FGS_grain_size and Templates next to the executable..."
rm -rf dist/images
cp -r images dist/images

rm -rf dist/FGS_grain_size
cp -r FGS_grain_size dist/FGS_grain_size

rm -rf dist/Templates
cp -r Templates dist/Templates

echo "Copying external executables (grav1synth, regrain, av-denoise)..."
for bin_name in grav1synth regrain av-denoise; do
    if [ -f "$bin_name" ]; then
        cp "$bin_name" "dist/$bin_name"
        chmod +x "dist/$bin_name"
    elif [ -f "${bin_name}.exe" ]; then
        cp "${bin_name}.exe" "dist/${bin_name}.exe"
        chmod +x "dist/${bin_name}.exe"
    fi
done

echo "Copying NOTICE.md..."
if [ -f "NOTICE.md" ]; then
    cp NOTICE.md dist/NOTICE.md
fi

echo "Copying settings.json..."
if [ -f "settings.json" ]; then
    cp settings.json dist/settings.json
fi

echo ""
echo "=============================================="
echo "Build completed successfully!" 
echo "You can find your executable inside:"
echo "$(pwd)/dist/"
echo "Make sure to distribute FGS_grain_size, Templates, grav1synth, regrain, and av-denoise alongside FGSEditor"
echo "=============================================="
