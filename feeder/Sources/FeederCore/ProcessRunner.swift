import Foundation

/// Runs a Step as a real process. The pipe draining follows agent-relic-v3 app/Sources/RelicMonitorRuntime/CLIProcess.swift
/// (@9f0bdb5): stdout and stderr are drained independently, so a verbose stderr cannot block stdout or the exit.
/// Every `sampleEvery` seconds the process's CPU time is sampled; idle for the StallDetector's window = stalled, killed.
public struct ProcessRunner: Runner {
    public var stallWindow: TimeInterval = 300
    public var sampleEvery: TimeInterval = 30
    public init(stallWindow: TimeInterval = 300, sampleEvery: TimeInterval = 30) {
        self.stallWindow = stallWindow; self.sampleEvery = sampleEvery
    }

    public func run(_ step: Step, onLine: @escaping (String) -> Void) async -> StepResult {
        let p = Process()
        p.executableURL = step.executable
        p.arguments = step.arguments
        p.environment = ProcessInfo.processInfo.environment.merging(step.environment) { _, new in new }
        p.standardInput = FileHandle.nullDevice
        let out = Pipe(), err = Pipe()
        p.standardOutput = out
        p.standardError = err
        let last = LastLine()
        for h in [out.fileHandleForReading, err.fileHandleForReading] {
            h.readabilityHandler = { fh in
                let d = fh.availableData
                guard !d.isEmpty, let s = String(data: d, encoding: .utf8) else { return }
                for line in s.replacingOccurrences(of: "\r", with: "\n").split(separator: "\n") where !line.isEmpty {
                    last.set(String(line)); onLine(String(line))
                }
            }
        }
        do { try p.run() } catch { return .failed(-1, "\(step.name): \(error.localizedDescription)") }
        var detector = StallDetector(window: stallWindow)
        while p.isRunning {
            try? await Task.sleep(nanoseconds: UInt64(sampleEvery * 1e9))
            guard p.isRunning, let cpu = cpuSeconds(pid: p.processIdentifier) else { continue }
            if detector.sample(cpuSeconds: cpu) {
                p.terminate()
                return .stalled("\(step.name): no CPU for \(Int(stallWindow / 60)) min (a privacy prompt? check the exclude list)")
            }
        }
        p.waitUntilExit()
        out.fileHandleForReading.readabilityHandler = nil
        err.fileHandleForReading.readabilityHandler = nil
        return p.terminationStatus == 0 ? .ok : .failed(p.terminationStatus, last.get())
    }
}

private final class LastLine: @unchecked Sendable {
    private var value = ""
    private let lock = NSLock()
    func set(_ s: String) { lock.lock(); value = s; lock.unlock() }
    func get() -> String { lock.lock(); defer { lock.unlock() }; return value }
}
