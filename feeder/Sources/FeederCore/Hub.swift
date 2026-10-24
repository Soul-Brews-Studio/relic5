import Foundation

/// What the panel shows, decoded from the hub's own answers (GET /api/status, GET /api/log): no local guesses.
public struct MachineRow: Equatable {
    public var name: String
    public var newest: String?
    public var behindSeconds: Int?
    public var pushedAt: String?
    public var sync: String?        // the machine's own relic-chain verdict: "2026-10-23 23:28:07 SYNC OK  text|…"
    public var vectorsPending: Int?

    /// "OK 23:28" / "MISMATCH 23:40" / "no chain log", for the one-line view of the other machines.
    public var syncShort: String {
        guard let s = sync else { return "no chain log" }
        let verdict = s.contains("MISMATCH") ? "MISMATCH" : "OK"
        let time = s.split(separator: " ").dropFirst().first.map { String($0.prefix(5)) } ?? ""
        return "\(verdict) \(time)"
    }
}

public struct HubStatus: Equatable {
    public var machines: [MachineRow]
    public var warnings: [String]
    public var diskFreePct: Double?

    public static func decode(_ data: Data) throws -> HubStatus {
        guard let o = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw HubError.shape }
        let fresh = ((o["freshness"] as? [String: Any])?["machines"] as? [String: [String: Any]]) ?? [:]
        let models = (((o["watermarks"] as? [String: Any])?["vectors"] as? [String: Any])?["models"] as? [String: [String: [String: Any]]]) ?? [:]
        let pending = models.values.first ?? [:]
        let rows = fresh.keys.sorted().map { m -> MachineRow in
            let f = fresh[m] ?? [:]
            return MachineRow(name: m, newest: f["newest_ts"] as? String, behindSeconds: f["lag_s"] as? Int,
                              pushedAt: f["pushed_at"] as? String, sync: f["sync"] as? String,
                              vectorsPending: pending[m]?["pending"] as? Int)
        }
        let disk = ((o["store"] as? [String: Any])?["disk"] as? [String: Any])?["free_pct"] as? Double
        return HubStatus(machines: rows, warnings: (o["warnings"] as? [String]) ?? [], diskFreePct: disk)
    }

    /// This machine's row, and the others as one read-only line: "white OK 23:40 · mba OK 23:35".
    public func row(_ me: String) -> MachineRow? { machines.first { $0.name == me } }
    public func othersLine(_ me: String) -> String {
        machines.filter { $0.name != me && !$0.name.hasSuffix("-import") }.map { "\($0.name) \($0.syncShort)" }.joined(separator: " · ")
    }
}

public struct JobLine: Equatable {
    public var at: String, verb: String, state: String, rc: Int?, host: String?, message: String?

    public static func decode(_ data: Data, host: String? = nil, limit: Int = 5) throws -> [JobLine] {
        guard let a = try JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { throw HubError.shape }
        let all = a.map { JobLine(at: $0["at"] as? String ?? "", verb: $0["verb"] as? String ?? "", state: $0["state"] as? String ?? "",
                                  rc: $0["rc"] as? Int, host: $0["host"] as? String, message: $0["message"] as? String) }
        let mine = host.map { h in all.filter { ($0.host ?? "").lowercased().hasPrefix(h.lowercased()) || ($0.message ?? "").contains("machine \(h)") } } ?? all
        return Array(mine.prefix(limit))
    }
}

public enum HubError: Error { case shape }

/// GET a hub route; the tailnet door needs no token (doors.py).
public func fetch(_ base: URL, _ path: String, timeout: TimeInterval = 20) async throws -> Data {
    var req = URLRequest(url: base.appendingPathComponent(path), timeoutInterval: timeout)
    req.setValue("relic-feeder", forHTTPHeaderField: "X-Relic5-Client")
    let (data, resp) = try await URLSession.shared.data(for: req)
    guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw HubError.shape }
    return data
}
