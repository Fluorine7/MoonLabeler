# SPDX-License-Identifier: GPL-3.0-or-later
"""Reject dependencies that would prevent a standalone macOS 14.4 ARM64 app."""
import argparse
import json
from pathlib import Path
import plistlib

from macholib.MachO import MachO
from macholib import mach_o


def version(value):
    return (value >> 16, (value >> 8) & 255, value & 255)


def check(bundle):
    bundle = bundle.resolve()
    with (bundle / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    assert info["LSMinimumSystemVersion"] == "14.4", info
    magics = {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
              b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}
    seen, binaries = set(), []
    dylib_commands = {mach_o.LC_LOAD_DYLIB, mach_o.LC_LOAD_WEAK_DYLIB, mach_o.LC_REEXPORT_DYLIB,
                      mach_o.LC_LOAD_UPWARD_DYLIB}
    for entry in sorted(bundle.rglob("*")):
        if entry.is_symlink():
            assert entry.resolve().is_relative_to(bundle), f"External symlink: {entry}"
            assert entry.exists(), f"Broken symlink: {entry}"
        if not entry.is_file():
            continue
        path = entry.resolve()
        if path in seen:
            continue
        seen.add(path)
        with path.open("rb") as stream:
            if stream.read(4) not in magics:
                continue
        image = MachO(str(path))
        assert len(image.headers) == 1, f"Expected a thin ARM64 binary: {entry}"
        header = image.headers[0]
        assert header.header.cputype == 0x0100000C, f"Non-ARM64 binary: {entry}"
        minimum = None
        for load, command, data in header.commands:
            if load.cmd == mach_o.LC_BUILD_VERSION:
                assert command.platform == 1, (entry, command.platform)
                minimum = version(command.minos)
            elif load.cmd == mach_o.LC_VERSION_MIN_MACOSX:
                minimum = version(command.version)
            elif load.cmd in dylib_commands or load.cmd == mach_o.LC_RPATH:
                name = data.split(b"\0", 1)[0].decode("utf-8")
                assert name.startswith(("@rpath/", "@loader_path/", "@executable_path/", "/System/Library/", "/usr/lib/")), (entry, name)
                if name.startswith("@loader_path/"):
                    assert (path.parent / name.removeprefix("@loader_path/")).resolve().is_relative_to(bundle), (entry, name)
                elif name.startswith("@executable_path/"):
                    assert (bundle / "Contents/MacOS" / name.removeprefix("@executable_path/")).resolve().is_relative_to(bundle), (entry, name)
        assert minimum is not None and minimum <= (14, 4, 0), f"{entry}: macOS {minimum} required"
        binaries.append({"path": str(path.relative_to(bundle)), "minimum_macos": ".".join(map(str, minimum)), "architecture": "arm64"})
    assert binaries, "No Mach-O binaries found"
    return {"app_version": info["CFBundleShortVersionString"], "minimum_macos": "14.4", "architecture": "arm64",
            "binary_count": len(binaries), "binaries": binaries, "success": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = check(args.bundle)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {report['binary_count']} standalone ARM64 binaries, macOS 14.4 or earlier deployment targets")
