import Foundation
import IOKit.ps

/// The folders macOS guards with a privacy prompt. A scan that walks into one from a LaunchAgent waits on a prompt
/// nobody sees: mba hung 8 minutes at 0% CPU (relic4-scan, 2026-10-23), and a replaced binary asks again. So the
/// exclude list in relic-scan's _config.json is a precondition the panel shows, not a hope.
public enum Preconditions {
    public static let protected = ["Desktop", "Documents", "Downloads", "Movies", "Music", "Pictures", "Public", "Library", "Volumes"]

    /// Protected folder names missing from `exclude` in the config at `path` (all of them when the file is unreadable).
    public static func missingExcludes(configAt path: URL) -> [String] {
        guard let data = try? Data(contentsOf: path),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return protected }
        let excludes = (obj["exclude"] as? [String]) ?? []
        return protected.filter { name in !excludes.contains { $0.contains(name) } }
    }
}

/// 10, 20, 40, 80 minutes, then 2 h, after consecutive failures; a success resets it.
public struct Backoff: Equatable {
    public private(set) var failures = 0
    public init() {}
    public mutating func failed() { failures += 1 }
    public mutating func succeeded() { failures = 0 }
    /// Seconds before the next pass may run (the plain interval when nothing failed).
    public func delay(interval: TimeInterval = 600) -> TimeInterval {
        failures == 0 ? interval : min(600 * pow(2, Double(failures - 1)), 7200)
    }
}

/// On AC power? Embedding runs only then (the plan: increments on the ANE, never on battery).
public enum Power {
    public static func onAC() -> Bool {
        guard let info = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
              let type = IOPSGetProvidingPowerSourceType(info)?.takeUnretainedValue() as String? else { return true }
        return type == kIOPSACPowerValue
    }
}

/// A step is stalled when its process gets no CPU time for `window` seconds. Output silence is not the test: a scan
/// can be quiet and busy, while the privacy-prompt hang is quiet AND idle (0% CPU).
public struct StallDetector {
    public let window: TimeInterval
    private var lastCPU: Double?
    private var idleSince: Date?
    public init(window: TimeInterval = 300) { self.window = window }

    /// Feed one sample (total CPU seconds of the process so far); true when it has been idle for the whole window.
    public mutating func sample(cpuSeconds: Double, at now: Date = Date()) -> Bool {
        defer { lastCPU = cpuSeconds }
        guard let last = lastCPU else { idleSince = nil; return false }
        if cpuSeconds - last > 0.01 { idleSince = nil; return false }
        if idleSince == nil { idleSince = now }
        return now.timeIntervalSince(idleSince!) >= window
    }
}

/// Total CPU seconds a process has used (user + system), via proc_pid_rusage; nil when it is gone.
public func cpuSeconds(pid: Int32) -> Double? {
    var usage = rusage_info_v2()
    let rc = withUnsafeMutablePointer(to: &usage) { ptr in
        ptr.withMemoryRebound(to: rusage_info_t?.self, capacity: 1) { proc_pid_rusage(pid, RUSAGE_INFO_V2, $0) }
    }
    guard rc == 0 else { return nil }
    var tb = mach_timebase_info_data_t()
    mach_timebase_info(&tb)
    let ns = Double(usage.ri_user_time + usage.ri_system_time) * Double(tb.numer) / Double(tb.denom)
    return ns / 1e9
}
