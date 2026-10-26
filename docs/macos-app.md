# macOS App

Apple Silicon (M1 or newer), **macOS 14.4+**. Download and opening instructions: [user guide](../README.zh-CN.md#下载与打开).

## Local build

Use an isolated Python 3.12+ environment with the project dependencies, `astropy`, `wgpu>=0.32,<0.33` and `pyinstaller==6.22.3`. The release environment uses Python 3.12.15. Install the project to build its private minimal OpenCV:

```bash
/path/to/python -m pip install --no-deps .
./build-macos.command /path/to/python
```

Output: `dist/MoonLabeler.app` and `dist/MoonLabeler-<version>-macos-arm64.zip`. The script bundles offline ephemerides, checks ARM64 dependencies and their minimum OS versions, verifies signatures, and runs the packaged functional checks before creating the ZIP.

## Qt compatibility

The initial PySide6/Shiboken6 6.12.0 PyPI bindings require macOS 26 despite their macOS 14 wheel tags. For macOS 14.4 support, use bindings rebuilt from the unmodified [v6.12.0 source](https://github.com/pyside/pyside-setup/tree/f50facb83fc3dc5f3240c854668c7a6dd93871b2), against the official Qt 6.12 SDK with Clang 22.1.8:

```bash
python setup.py bdist_wheel --qtpaths=<SDK>/bin/qtpaths \
  --module-subset=Core,Gui,Widgets,Network,DBus,Svg --parallel=4 \
  --macos-arch=arm64 --macos-deployment-target=14.4 --standalone
```

Set `MACOSX_DEPLOYMENT_TARGET=14.4`, `CMAKE_PREFIX_PATH` to the SDK and `CMAKE_IGNORE_PREFIX_PATH=/opt/homebrew`; disable optional Qt6Qml and Qt6UiTools discovery. Use upstream `create_wheels.py --no-examples --build-dir=<build-dir>` to create the split Essentials/Shiboken wheels and install them in the packaging environment. The bundle check rejects incompatible binaries.

## Verification and release

`build-macos.command` runs the bundled dependency, offline registration, image-reading, project and PNG/SVG checks. The **macOS App compatibility** workflow then tests the same published ZIP on macOS 14 and 15 using its SHA-256; it does not rebuild the app.

Release attachments contain only the macOS and Windows app ZIPs. Keep reports and intermediate files in local output or Actions artifacts.

The app is ad-hoc signed and is not Apple-notarized. Its cache and preferences are stored under `~/Library/Caches/MoonLabeler`.
