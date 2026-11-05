#!/usr/bin/env swift
// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import Darwin

// Swap directories instead of overwriting binaries mapped by a running app.
let paths = CommandLine.arguments
guard paths.count == 3 else { fatalError("Usage: install-app.swift staged.app destination.app") }
let staged = URL(fileURLWithPath: paths[1]), destination = URL(fileURLWithPath: paths[2])
if FileManager.default.fileExists(atPath: destination.path) {
    let result = staged.path.withCString { source in
        destination.path.withCString { target in renameatx_np(AT_FDCWD, source, AT_FDCWD, target, UInt32(RENAME_SWAP)) }
    }
    if result != 0 { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
} else {
    try FileManager.default.moveItem(at: staged, to: destination)
}
