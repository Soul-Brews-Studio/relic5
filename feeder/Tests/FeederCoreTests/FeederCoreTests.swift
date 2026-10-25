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

    // relic-scan ops --json (relic4-scan src/ops.rs chain_view), a pass in its push stage
    static let running = #"{"at":"x","chain":{"state":"running","machine":"m5","started":"2026-10-24 15:18:15","ended":null,"stages":[{"name":"scan","state":"done","secs":147.3,"typical_s":140.0,"detail":"scan 98.6s"},{"name":"extract","state":"done","secs":14.2,"typical_s":14.2,"detail":null},{"name":"push to the hub","state":"running","secs":null,"typical_s":16.0,"detail":null},{"name":"hub index + embed","state":"waiting","secs":null,"typical_s":null,"detail":null},{"name":"sync check","state":"waiting","secs":null,"typical_s":null,"detail":null}],"sync":null,"elapsed_s":180,"typical_total_s":300.0,"eta_s":120.0}}"#
    static let idle = #"{"chain":{"state":"idle","machine":"m5","stages":[],"sync":"SYNC OK  text|1075420","elapsed_s":null,"typical_total_s":299.0,"eta_s":null,"took_s":285,"next_in_s":217}}"#

    func testChainSnapshotRunning() throws {
        let s = try ChainSnapshot.decode(Data(Self.running.utf8))
        XCTAssertTrue(s.running)
        XCTAssertEqual(s.stages.map(\.mark), ["✓", "✓", "●", "·", "·"])
        XCTAssertEqual(s.progress ?? 0, 0.6, accuracy: 1e-9)
        XCTAssertEqual(s.leftLine, "about 2:00 left")
        XCTAssertEqual(s.stages[0].secs, 147.3)
    }

    func testChainSnapshotIdleAndClock() throws {
        let s = try ChainSnapshot.decode(Data(Self.idle.utf8))
        XCTAssertFalse(s.running); XCTAssertNil(s.progress); XCTAssertNil(s.leftLine)
        XCTAssertEqual(s.tookS, 285); XCTAssertEqual(s.nextInS, 217); XCTAssertEqual(s.syncOK, true)
        XCTAssertEqual(clock(105), "1:45"); XCTAssertEqual(clock(3725), "1:02:05"); XCTAssertEqual(clock(0), "0:00")
        XCTAssertThrowsError(try ChainSnapshot.decode(Data("{}".utf8)))
    }

    func testChainWatchShowsSyncOnceAfterAPassEnds() throws {
        var w = ChainWatch(hold: 8)
        let run = try ChainSnapshot.decode(Data(Self.running.utf8)), idle = try ChainSnapshot.decode(Data(Self.idle.utf8))
        let t0 = Date()
        XCTAssertFalse(w.see(idle, now: t0))                     // idle at start: nothing just ended
        XCTAssertFalse(w.see(run, now: t0))
        XCTAssertTrue(w.see(idle, now: t0.addingTimeInterval(3)))  // running -> idle
        XCTAssertEqual(w.justEnded(now: t0.addingTimeInterval(5)), "SYNC OK  text|1075420")
        XCTAssertNil(w.justEnded(now: t0.addingTimeInterval(12)))
        XCTAssertFalse(w.see(idle, now: t0.addingTimeInterval(13)))
    }
}
