#!/bin/bash
set -euo pipefail

swift_root="$(cd "$(dirname "$0")" && pwd)"
cd "$swift_root"
mkdir -p .build/ModuleCache dist
./Native/build.command
./tools/prepare-data.command
export CLANG_MODULE_CACHE_PATH="$swift_root/.build/ModuleCache"
export SWIFT_MODULECACHE_PATH="$swift_root/.build/ModuleCache"
swift tools/prepare-resources.swift
swift_options=(--disable-sandbox --cache-path .build/cache --config-path .build/config --security-path .build/security)
swift build -c release "${swift_options[@]}"
release_bin="$(swift build -c release "${swift_options[@]}" --show-bin-path)"
destination="$swift_root/dist/MoonLabeler Swift.app"
package_stage="$(mktemp -d "$swift_root/.build/app-package.XXXXXX")"
trap 'rm -rf "$package_stage"' EXIT
app="$package_stage/MoonLabeler Swift.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources" "$app/Contents/Frameworks"
cp "$release_bin/MoonLabelerSwift" "$app/Contents/MacOS/MoonLabelerSwift"
install_name_tool -delete_rpath "$swift_root/.build/native/lib" "$app/Contents/MacOS/MoonLabelerSwift"
cp "$swift_root/.build/native/lib/libMoonNative.dylib" "$app/Contents/Frameworks/"
for resources in "$release_bin/MoonLabelerSwift_MoonCore.bundle"; do
    if [ -d "$resources" ]; then
        ditto "$resources" "$app/Contents/Resources/$(basename "$resources")"
    fi
done
# CSPICE's f2c runtime tries read/write before read-only even for input kernels.
# Immutable bundle data must fail that first attempt before macOS app protection.
find "$app/Contents/Resources" -type f \( -name '*.bsp' -o -name '*.bpc' -o -name '*.tls' -o -name '*.tf' -o -name '*.tpc' \) -exec chmod a-w {} +
cp "$swift_root/LICENSE" "$swift_root/THIRD_PARTY_NOTICES.md" "$swift_root/ACKNOWLEDGEMENTS.md" "$swift_root/DATA_SOURCES.md" "$app/Contents/Resources/"
ditto "$swift_root/Licenses" "$app/Contents/Resources/Licenses"
ditto "$swift_root/Native/vendor/libarchive" "$app/Contents/Resources/Licenses/libarchive"
cp "$swift_root/README.md" "$app/Contents/Resources/Swift-README.md"
if [ -f "$swift_root/../build/moonlabeler.icns" ]; then
    cp "$swift_root/../build/moonlabeler.icns" "$app/Contents/Resources/moonlabeler.icns"
fi
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>CFBundleExecutable</key><string>MoonLabelerSwift</string>
    <key>CFBundleIdentifier</key><string>org.fluorine.moonlabeler-swift</string>
    <key>CFBundleName</key><string>MoonLabeler Swift</string>
    <key>CFBundleDisplayName</key><string>MoonLabeler Swift</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>0.12.3</string>
    <key>CFBundleVersion</key><string>0.12.3</string>
    <key>CFBundleIconFile</key><string>moonlabeler.icns</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSPrincipalClass</key><string>NSApplication</string>
    <key>NSHumanReadableCopyright</key><string>© 2026 Fluorine Zhu · GPL-3.0-or-later</string>
    <key>CFBundleDocumentTypes</key><array>
        <dict><key>CFBundleTypeName</key><string>MoonLabeler Swift Project</string>
            <key>CFBundleTypeRole</key><string>Editor</string>
            <key>LSHandlerRank</key><string>Owner</string>
            <key>LSItemContentTypes</key><array><string>org.fluorine.moonlabeler-swift.project</string></array></dict>
        <dict><key>CFBundleTypeName</key><string>MoonLabeler Project</string>
            <key>CFBundleTypeRole</key><string>Viewer</string>
            <key>LSHandlerRank</key><string>Alternate</string>
            <key>CFBundleTypeExtensions</key><array><string>moonlabel</string></array></dict>
    </array>
    <key>UTExportedTypeDeclarations</key><array><dict>
        <key>UTTypeIdentifier</key><string>org.fluorine.moonlabeler-swift.project</string>
        <key>UTTypeDescription</key><string>MoonLabeler Swift Project</string>
        <key>UTTypeConformsTo</key><array><string>public.json</string></array>
        <key>UTTypeTagSpecification</key><dict><key>public.filename-extension</key><array><string>moonswift</string></array></dict>
    </dict></array>
</dict></plist>
PLIST
codesign --force --deep --sign - "$app"
codesign --verify --deep --strict "$app"
swift -module-cache-path "$swift_root/.build/ModuleCache" tools/install-app.swift "$app" "$destination"
printf '\nBuilt: %s\n' "$destination"
du -sh "$destination"
