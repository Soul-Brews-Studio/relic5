import Foundation
import XCTest
@testable import FeederCore

final class FeederCoreTests: XCTestCase {
    func testPreconditionsListMissingProtectedFolders() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let cfg = dir.appendingPathComponent("_config.json")
        try #"{"roots":["~"],"exclude":["/Desktop","/Documents","/Downloads","/Movies","/Music","/Pictures","/Public","/Volumes","/Library"]}"#
            .write(to: cfg, atomically: true, encoding: .utf8)
        XCTAssertEqual(Preconditions.missingExcludes(configAt: cfg), [])
        try #"{"roots":["~"],"exclude":["/Desktop"]}"#.write(to: cfg, atomically: true, encoding: .utf8)
        XCTAssertTrue(Preconditions.missingExcludes(configAt: cfg).contains("Documents"))
        XCTAssertEqual(Preconditions.missingExcludes(configAt: dir.appendingPathComponent("none")), Preconditions.protected)
    }

    func testBackoff() {
        var b = Backoff()
        XCTAssertEqual(b.delay(), 600)
        b.failed(); XCTAssertEqual(b.delay(), 600)
        b.failed(); XCTAssertEqual(b.delay(), 1200)
        b.failed(); b.failed(); b.failed(); b.failed(); XCTAssertEqual(b.delay(), 7200)
        b.succeeded(); XCTAssertEqual(b.delay(), 600)
    }

    func testStallIsIdleCPUNotSilence() {
        var d = StallDetector(window: 300)
        let t0 = Date()
        XCTAssertFalse(d.sample(cpuSeconds: 1.0, at: t0))
        XCTAssertFalse(d.sample(cpuSeconds: 5.0, at: t0 + 60))           // busy
        XCTAssertFalse(d.sample(cpuSeconds: 5.0, at: t0 + 120))          // idle starts
        XCTAssertFalse(d.sample(cpuSeconds: 5.0, at: t0 + 300))
        XCTAssertTrue(d.sample(cpuSeconds: 5.0, at: t0 + 421))           // idle for 5 min: the mba hang
        var e = StallDetector(window: 300)
        for i in 0..<20 { XCTAssertFalse(e.sample(cpuSeconds: Double(i), at: t0 + Double(i * 60))) }   // quiet but busy
    }

    func testCPUSecondsOfThisProcess() {
        XCTAssertNotNil(cpuSeconds(pid: getpid()))
        XCTAssertNil(cpuSeconds(pid: 999_999))
    }

    final class Fake: Runner, @unchecked Sendable {
        var results: [String: StepResult]
        var ran: [String] = []
        init(_ r: [String: StepResult]) { results = r }
        func run(_ step: Step, onLine: @escaping (String) -> Void) async -> StepResult {
            ran.append(step.name); return results[step.name] ?? .ok
        }
    }

    func chain() -> Chain {
        let u = URL(fileURLWithPath: "/usr/bin/true")
        return Chain(scan: Step("scan", u), extract: Step("extract", u), embed: Step("embed", u))
    }

    func lock() -> URL { FileManager.default.temporaryDirectory.appendingPathComponent("feeder-\(UUID().uuidString).lock") }

    func testPassRunsTheChainAndEmbedsOnlyOnAC() async {
        let f = Fake([:]); let feeder = Feeder(chain: chain(), runner: f, lockPath: lock())
        feeder.onAC = { false }
        let r = await feeder.pass()
        XCTAssertEqual(f.ran, ["scan", "extract"]); XCTAssertEqual(r?.ok, true)
        feeder.onAC = { true }
        _ = await feeder.pass()
        XCTAssertEqual(f.ran, ["scan", "extract", "scan", "extract", "embed"])
    }

    func testAFailedStepStopsThePassAndBacksOff() async {
        let f = Fake(["scan": .stalled("scan: no CPU for 5 min")]); let feeder = Feeder(chain: chain(), runner: f, lockPath: lock())
        let r = await feeder.pass()
        XCTAssertEqual(f.ran, ["scan"]); XCTAssertEqual(r?.ok, false); XCTAssertEqual(feeder.backoff.failures, 1)
    }

    func testOnePassAtATime() async {
        let path = lock()
        let fd = open(path.path, O_CREAT | O_RDWR, 0o600); XCTAssertEqual(flock(fd, LOCK_EX | LOCK_NB), 0)
        let f = Fake([:]); let feeder = Feeder(chain: chain(), runner: f, lockPath: path)
        let r = await feeder.pass()
        XCTAssertNil(r); XCTAssertEqual(f.ran, [])
        flock(fd, LOCK_UN); close(fd)
    }

    func testRealProcessRunnerAndExitCodes() async {
        let r = ProcessRunner(stallWindow: 300, sampleEvery: 0.2)
        let ok = await r.run(Step("t", URL(fileURLWithPath: "/bin/sh"), ["-c", "echo hello"]), onLine: { _ in })
        XCTAssertEqual(ok, .ok)
        let bad = await r.run(Step("t", URL(fileURLWithPath: "/bin/sh"), ["-c", "echo boom; exit 3"]), onLine: { _ in })
        XCTAssertEqual(bad, .failed(3, "boom"))
        let idle = ProcessRunner(stallWindow: 0.5, sampleEvery: 0.2)
        let stalled = await idle.run(Step("t", URL(fileURLWithPath: "/bin/sleep"), ["30"]), onLine: { _ in })
        if case .stalled = stalled {} else { XCTFail("sleep should stall: \(stalled)") }
    }

    func testHubStatusDecodingAndTheOthersLine() throws {
        let json = #"""
        {"warnings": [], "store": {"disk": {"free_pct": 22.0}},
         "watermarks": {"vectors": {"models": {"g@1": {"m5": {"pending": 0}, "mba": {"pending": 3}}}}},
         "freshness": {"machines": {
           "m5": {"newest_ts": "2026-10-23T16:28:00Z", "lag_s": 60, "pushed_at": "2026-10-23T23:28:05+0700", "sync": "2026-10-23 23:28:07 SYNC OK  text|1"},
           "mba": {"sync": "2026-10-23 23:35:02 SYNC OK  text|2"},
           "white": {"sync": "2026-10-23 23:40:37 SYNC MISMATCH  white: text|3  hub: text|2"},
           "jsonl-truth-import": {}}}}
        """#
        let s = try HubStatus.decode(Data(json.utf8))
        XCTAssertEqual(s.row("m5")?.vectorsPending, 0)
        XCTAssertEqual(s.row("mba")?.vectorsPending, 3)
        XCTAssertEqual(s.othersLine("m5"), "mba OK 23:35 · white MISMATCH 23:40")
        XCTAssertEqual(s.diskFreePct, 22.0)
    }
}
