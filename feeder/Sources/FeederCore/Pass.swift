import Foundation

/// One step of a pass: an executable and its arguments (no shell), plus the environment it needs.
public struct Step: Equatable {
    public var name: String
    public var executable: URL
    public var arguments: [String]
    public var environment: [String: String]
    public init(_ name: String, _ executable: URL, _ arguments: [String] = [], environment: [String: String] = [:]) {
        self.name = name; self.executable = executable; self.arguments = arguments; self.environment = environment
    }
}

public enum StepResult: Equatable {
    case ok
    case failed(Int32, String)     // exit code, the last output line
    case stalled(String)           // no CPU time for the stall window: killed
}

/// How a step runs. The app runs real processes; tests use a fake.
public protocol Runner {
    func run(_ step: Step, onLine: @escaping (String) -> Void) async -> StepResult
}

/// The chain the existing studio.soulbrews.relic-chain job runs, in order. relic-extract's [extract] after hook pushes
/// to the hub and indexes there; embed runs only on AC power (the policy picks ANE for an increment).
public struct Chain {
    public var scan: Step, extract: Step, embed: Step?
    public init(scan: Step, extract: Step, embed: Step?) { self.scan = scan; self.extract = extract; self.embed = embed }

    public static func standard(home: URL, relic5Repo: URL, machine: String) -> Chain {
        let bin = home.appendingPathComponent(".local/bin")
        let env = ["PATH": "\(bin.path):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "NO_COLOR": "1", "RELIC5_MACHINE": machine]
        return Chain(scan: Step("scan", bin.appendingPathComponent("relic-scan"), ["run"], environment: env),
                     extract: Step("extract", bin.appendingPathComponent("relic-extract"), ["run"], environment: env),
                     embed: Step("embed", relic5Repo.appendingPathComponent(".venv/bin/relic5"), ["embed", "--limit", "20000"], environment: env))
    }
}

public struct PassReport: Equatable {
    public var started: Date
    public var steps: [(String, StepResult)]
    public var ok: Bool { steps.allSatisfy { $0.1 == .ok } }
    public static func == (a: PassReport, b: PassReport) -> Bool {
        a.started == b.started && a.steps.map { $0.0 } == b.steps.map { $0.0 } && a.steps.map { $0.1 } == b.steps.map { $0.1 }
    }
}

/// One pass at a time, across this app and anything else that takes the same lock file (flock: released when the
/// process dies, so a crash never leaves it stuck). A failed or stalled step stops the pass.
public final class Feeder {
    public let chain: Chain
    public let runner: Runner
    public let lockPath: URL
    public private(set) var backoff = Backoff()
    public var onAC: () -> Bool = Power.onAC
    public var onLine: (String) -> Void = { _ in }

    public init(chain: Chain, runner: Runner, lockPath: URL) {
        self.chain = chain; self.runner = runner; self.lockPath = lockPath
    }

    /// nil when another pass holds the lock.
    public func pass(now: Date = Date()) async -> PassReport? {
        let fd = open(lockPath.path, O_CREAT | O_RDWR, 0o600)
        guard fd >= 0, flock(fd, LOCK_EX | LOCK_NB) == 0 else { if fd >= 0 { close(fd) }; return nil }
        defer { flock(fd, LOCK_UN); close(fd) }
        var report = PassReport(started: now, steps: [])
        var steps = [chain.scan, chain.extract]
        if let e = chain.embed, onAC() { steps.append(e) }
        for s in steps {
            let r = await runner.run(s, onLine: onLine)
            report.steps.append((s.name, r))
            if r != .ok { break }
        }
        if report.ok { backoff.succeeded() } else { backoff.failed() }
        return report
    }
}
