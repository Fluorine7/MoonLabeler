// SPDX-License-Identifier: GPL-3.0-or-later
import Foundation

// ImageIO can remain inside a file-system read after the user cancels. Resume
// the editor immediately and discard that worker's eventual result.
enum CancellableRead {
    static func run<Value: Sendable>(_ read: @escaping @Sendable () throws -> Value) async throws -> Value {
        let completion = ReadCompletion<Value>()
        return try await withTaskCancellationHandler {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { continuation in
                if completion.install(continuation) {
                    Task.detached(priority: .userInitiated) { completion.finish(Result(catching: read)) }
                }
            }
        } onCancel: {
            completion.finish(.failure(CancellationError()))
        }
    }
}

private final class ReadCompletion<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Value, Error>?
    private var result: Result<Value, Error>?
    func install(_ continuation: CheckedContinuation<Value, Error>) -> Bool {
        lock.lock()
        if let result {
            lock.unlock(); continuation.resume(with: result); return false
        }
        self.continuation = continuation; lock.unlock(); return true
    }
    func finish(_ result: Result<Value, Error>) {
        lock.lock()
        guard self.result == nil else { lock.unlock(); return }
        self.result = result
        let continuation = self.continuation; self.continuation = nil
        lock.unlock(); continuation?.resume(with: result)
    }
}
