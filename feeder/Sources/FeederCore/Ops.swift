import Foundation

/// What the relic chain on this Mac is doing now, from `relic-scan ops --json --no-hub` (relic4-scan src/ops.rs, the
/// same snapshot as its page's Activity view and `relic-scan tui` tab 6). Read only: the app never changes the chain.
public struct ChainStage: Equatable {
    public var name: String
    public var state: String          // done | running | waiting
    public var secs: Double?
    public var typicalS: Double?
    public var detail: String?

    /// ✓ done, ● running, · waiting.
    public var mark: String { state == "done" ? "✓" : state == "running" ? "●" : "·" }
}

public struct ChainSnapshot: Equatable {
    public var state: String          // running | idle | never
    public var machine: String?
    public var stages: [ChainStage]
    public var sync: String?
    public var elapsedS: Double?
    public var typicalTotalS: Double?
    public var etaS: Double?
    public var tookS: Double?
    public var nextInS: Double?

    public var running: Bool { state == "running" }

    /// 0...1 for the progress bar: elapsed over the typical total (nil when there is no typical yet).
    public var progress: Double? {
        guard running, let e = elapsedS, let t = typicalTotalS, t > 0 else { return nil }
        return min(1, e / t)
    }

    /// "about 1:42 left", "over the typical time now", or nil when idle.
    public var leftLine: String? {
        guard running else { return nil }
        guard let eta = etaS, typicalTotalS != nil else { return nil }
        return eta > 0 ? "about \(clock(eta)) left" : "over the typical time now"
    }

    public var syncOK: Bool? { sync.map { !$0.contains("MISMATCH") } }

    public static func decode(_ data: Data) throws -> ChainSnapshot {
        guard let o = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let c = o["chain"] as? [String: Any] else { throw HubError.shape }
        let num = { (k: String, d: [String: Any]) -> Double? in (d[k] as? NSNumber)?.doubleValue }
        let stages = (c["stages"] as? [[String: Any]] ?? []).map {
            ChainStage(name: $0["name"] as? String ?? "", state: $0["state"] as? String ?? "waiting",
                       secs: num("secs", $0), typicalS: num("typical_s", $0), detail: $0["detail"] as? String)
        }
        return ChainSnapshot(state: c["state"] as? String ?? "never", machine: c["machine"] as? String, stages: stages,
                             sync: c["sync"] as? String, elapsedS: num("elapsed_s", c), typicalTotalS: num("typical_total_s", c),
                             etaS: num("eta_s", c), tookS: num("took_s", c), nextInS: num("next_in_s", c))
    }
}

/// 105 -> "1:45", 3725 -> "1:02:05".
public func clock(_ s: Double) -> String {
    let t = Int(s.rounded())
    return t >= 3600 ? String(format: "%d:%02d:%02d", t / 3600, t / 60 % 60, t % 60) : String(format: "%d:%02d", t / 60, t % 60)
}

/// Remembers the last state so a running → idle flip is seen once: the sync line then shows for `hold` seconds.
public struct ChainWatch {
    public private(set) var last: ChainSnapshot?
    public private(set) var endedAt: Date?
    public var hold: TimeInterval
    public init(hold: TimeInterval = 8) { self.hold = hold }

    /// Feed the newest snapshot; true when a pass just ended.
    public mutating func see(_ s: ChainSnapshot, now: Date = Date()) -> Bool {
        defer { last = s }
        if last?.running == true && !s.running { endedAt = now; return true }
        return false
    }

    /// The sync line to show, only within `hold` of a pass ending.
    public func justEnded(now: Date = Date()) -> String? {
        guard let t = endedAt, now.timeIntervalSince(t) < hold else { return nil }
        return last?.sync
    }
}

/// One `relic-scan ops --json --no-hub` (a ps and a log tail: a few ms), off the main thread.
public func readOps(_ relicScan: URL) async throws -> ChainSnapshot {
    try await Task.detached {
        let p = Process(), out = Pipe()
        p.executableURL = relicScan
        p.arguments = ["ops", "--json", "--no-hub"]
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        p.standardInput = FileHandle.nullDevice
        try p.run()
        let data = out.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        guard p.terminationStatus == 0 else { throw HubError.shape }
        return try ChainSnapshot.decode(data)
    }.value
}
