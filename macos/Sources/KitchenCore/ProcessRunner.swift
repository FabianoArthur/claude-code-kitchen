import Foundation

public struct ProcessOutput: Equatable, Sendable {
    public var status: Int32
    public var stdout: Data
    public var stderr: Data

    public init(status: Int32, stdout: Data, stderr: Data) {
        self.status = status
        self.stdout = stdout
        self.stderr = stderr
    }
}

public enum ProcessFailure: Error, Equatable, Sendable {
    case launchFailed
    case timedOut
    case outputTooLarge
}

/// Runs a child process with a deadline. Both pipes are drained concurrently (no pipe-buffer
/// deadlock), output is capped, and on timeout the child gets SIGTERM, then SIGKILL 1 s later.
public enum ProcessRunner {
    public static func run(_ executable: URL, _ arguments: [String], timeout: TimeInterval,
                           stdoutLimit: Int = 2 << 20, stderrLimit: Int = 64 << 10,
                           environment: [String: String]? = nil) async -> Result<ProcessOutput, ProcessFailure> {
        await withCheckedContinuation { continuation in
            Job(executable, arguments, environment, stdoutLimit, stderrLimit, timeout) { continuation.resume(returning: $0) }
                .start()
        }
    }
}

private final class Job: @unchecked Sendable {
    private let process = Process()
    private let out = Pipe()
    private let err = Pipe()
    private let limits: (Int, Int)
    private let timeout: TimeInterval
    private let finish: @Sendable (Result<ProcessOutput, ProcessFailure>) -> Void
    private let lock = NSLock()
    private var buffers = (Data(), Data())
    private var tooLarge = false
    private var timedOut = false
    private var finished = false

    init(_ executable: URL, _ arguments: [String], _ environment: [String: String]?, _ stdoutLimit: Int,
         _ stderrLimit: Int, _ timeout: TimeInterval,
         finish: @escaping @Sendable (Result<ProcessOutput, ProcessFailure>) -> Void) {
        process.executableURL = executable
        process.arguments = arguments
        if let environment { process.environment = environment }
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = out
        process.standardError = err
        limits = (stdoutLimit, stderrLimit)
        self.timeout = timeout
        self.finish = finish
    }

    func start() {
        let group = DispatchGroup()
        group.enter()
        process.terminationHandler = { _ in group.leave() }
        do {
            try process.run()
        } catch {
            complete(.failure(.launchFailed))
            return
        }
        for stream in [0, 1] {
            group.enter()
            DispatchQueue.global(qos: .utility).async {
                self.drain(stream)
                group.leave()
            }
        }
        group.notify(queue: .global(qos: .utility)) { self.completeNormally() }
        let queue = DispatchQueue.global(qos: .utility)
        queue.asyncAfter(deadline: .now() + timeout) {
            guard self.process.isRunning else { return }
            self.locked { self.timedOut = true }
            self.stop()
            // A grandchild may keep the pipes open after the kill: don't wait for it forever.
            queue.asyncAfter(deadline: .now() + 2) { self.complete(.failure(.timedOut)) }
        }
    }

    private func stop() {
        process.terminate()
        let pid = process.processIdentifier
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 1) {
            if self.process.isRunning { kill(pid, SIGKILL) }
        }
    }

    private func drain(_ stream: Int) {
        let fd = (stream == 0 ? out : err).fileHandleForReading.fileDescriptor
        let limit = stream == 0 ? limits.0 : limits.1
        var chunk = [UInt8](repeating: 0, count: 65_536)
        while true {
            let n = chunk.withUnsafeMutableBytes { read(fd, $0.baseAddress, $0.count) }
            if n < 0 && errno == EINTR { continue }
            if n <= 0 { break }
            let overflow: Bool = locked {
                if stream == 0 { buffers.0.append(contentsOf: chunk[0..<n]) } else { buffers.1.append(contentsOf: chunk[0..<n]) }
                let size = stream == 0 ? buffers.0.count : buffers.1.count
                if size > limit && !tooLarge {
                    tooLarge = true
                    return true
                }
                return false
            }
            if overflow { stop() }
        }
    }

    private func completeNormally() {
        let (timedOut, tooLarge, buffers) = locked { (self.timedOut, self.tooLarge, self.buffers) }
        if timedOut { complete(.failure(.timedOut)) }
        else if tooLarge { complete(.failure(.outputTooLarge)) }
        else { complete(.success(ProcessOutput(status: process.terminationStatus, stdout: buffers.0, stderr: buffers.1))) }
    }

    private func complete(_ result: Result<ProcessOutput, ProcessFailure>) {
        let first: Bool = locked {
            defer { finished = true }
            return !finished
        }
        if first { finish(result) }
    }

    private func locked<T>(_ body: () -> T) -> T {
        lock.lock()
        defer { lock.unlock() }
        return body()
    }
}
