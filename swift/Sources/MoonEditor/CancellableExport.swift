// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation
import Darwin

enum CancellableExport {
    static func run(to destination: URL, write: @escaping @Sendable (URL) throws -> Void) async throws {
        let completion = ExportCompletion()
        let temporary = destination.deletingLastPathComponent().appendingPathComponent(".moonlabeler-export-\(UUID().uuidString).\(destination.pathExtension)")
        try await withTaskCancellationHandler {
            try Task.checkCancellation()
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                if completion.install(continuation) {
                    Task.detached(priority: .userInitiated) {
                        defer { try? FileManager.default.removeItem(at: temporary) }
                        do {
                            guard completion.pending else { return }
                            try write(temporary)
                            completion.commit {
                                guard Darwin.rename(temporary.path, destination.path) == 0 else {
                                    throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno), userInfo: [NSFilePathErrorKey: destination.path])
                                }
                            }
                        } catch { completion.finish(.failure(error)) }
                    }
                }
            }
        } onCancel: {
            completion.finish(.failure(CancellationError()))
        }
    }
}

private final class ExportCompletion: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Void, Error>?
    private var result: Result<Void, Error>?
    var pending: Bool { lock.lock(); defer { lock.unlock() }; return result == nil }
    func install(_ continuation: CheckedContinuation<Void, Error>) -> Bool {
        lock.lock()
        if let result { lock.unlock(); continuation.resume(with: result); return false }
        self.continuation = continuation; lock.unlock(); return true
    }
    func finish(_ result: Result<Void, Error>) { commit { try result.get() } }
    func commit(_ action: () throws -> Void) {
        lock.lock()
        guard result == nil else { lock.unlock(); return }
        // Cancellation and the short atomic rename compete for one completion.
        // A cancelled encoder can finish its temporary file, but cannot publish it.
        let result = Result(catching: action)
        self.result = result
        let continuation = self.continuation; self.continuation = nil
        lock.unlock(); continuation?.resume(with: result)
    }
}
