# v0.8.0 build and verification records

These records were moved from Release attachments into the repository to keep the user download list short. The released application binaries have not changed during this cleanup. The Release retains the macOS App, Windows portable ZIP, Linux x64 installation wheel and one `SHA256SUMS` file. GitHub also displays its two automatic source archives.

- [macOS compatibility](macos-app-compatibility.json): the locally built Apple Silicon App tested unchanged on macOS 14.8.9 and 15.7.9, including registration, crater detection, TIFF/FITS, project roundtrip, exports, GUI startup and Metal/CPU agreement.
- [macOS native binary checks](macos-bundle-verification.json), [build provenance](macos-build-info.json) and [Python dependency audit](macos-dependency-audit.json).
- [Windows frozen-program checks](portable-frozen-verification.json), [native verification](portable-native-verification.json) and [packaging dependency inventory](portable-audit-requirements.txt). The final EXE embeds CPython 3.12.15.
- Original private OpenCV wheel verification: [macOS](minimal-opencv-macos-latest-verification.json), [Windows](minimal-opencv-windows-latest-verification.json), [Linux](minimal-opencv-ubuntu-latest-verification.json).

Completed runs: [macOS 14/15 App checks](https://github.com/Fluorine7/MoonLabeler/actions/runs/39718000558), [patched Windows portable build](https://github.com/Fluorine7/MoonLabeler/actions/runs/39718603541), [three-platform regression tests and audits](https://github.com/Fluorine7/MoonLabeler/actions/runs/39713471197). The macOS minimum deployment target is 14.4; actual OS test versions are recorded separately in the report. These records do not claim coverage of all hardware or absence of every native vulnerability.
