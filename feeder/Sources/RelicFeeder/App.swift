import AppKit
import FeederCore
import SwiftUI

/// RelicFeeder: a menu-bar panel that runs this Mac's relic chain every 10 minutes and shows what the hub says about it
/// (docs/RELICFEEDER.md). Everything shown comes from the hub or from the pass itself.
@main
struct RelicFeederApp: App {
    @StateObject private var model = Model()
    var body: some Scene {
        MenuBarExtra {
            Panel(model: model).frame(width: 440)
        } label: {
            // while a pass runs: the turning icon and the time left; for a few seconds after: its sync verdict
            if let left = model.chain?.running == true ? model.chain?.etaS : nil, left > 0 {
                HStack(spacing: 3) { Image(systemName: model.symbol); Text(clock(left)).monospacedDigit() }
            } else {
                Image(systemName: model.symbol)
            }
        }
        .menuBarExtraStyle(.window)
    }
}

@MainActor
final class Model: ObservableObject {
    let home = FileManager.default.homeDirectoryForCurrentUser
    let hub = URL(string: ProcessInfo.processInfo.environment["RELIC5_URL"] ?? "http://white.follow-rankine.ts.net:8795")!
    let machine = ProcessInfo.processInfo.environment["RELIC5_MACHINE"]
        ?? (Host.current().localizedName ?? "m5").lowercased().replacingOccurrences(of: " ", with: "-")
    let repo = URL(fileURLWithPath: ProcessInfo.processInfo.environment["RELIC5_REPO"] ?? "/opt/Code/github.com/Soul-Brews-Studio/relic5")

    @Published var status: HubStatus?
    @Published var jobs: [JobLine] = []
    @Published var missing: [String] = []
    @Published var running = false
    @Published var lastPass: String = "no pass yet"
    @Published var lastLine = ""
    @Published var error: String?
    /// While the old LaunchAgent studio.soulbrews.relic-chain is loaded it runs the passes; this app only watches
    /// (one scheduler, no doubled runs). Unloading it is Nat's call (relic4-scan, 2026-10-23).
    @Published var oldChainLoaded = false
    /// relic-scan's own view of the pass in flight (relic-scan ops --json), polled: 3 s while running, 15 s idle.
    @Published var chain: ChainSnapshot?
    @Published var ended: String?
    private var watch = ChainWatch(hold: 8)
    let relicScan = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin/relic-scan")
    private var feeder: Feeder!
    private var timer: Timer?

    init() {
        feeder = Feeder(chain: .standard(home: home, relic5Repo: repo, machine: machine), runner: ProcessRunner(),
                        lockPath: home.appendingPathComponent(".relic-scan/.feeder.lock"))
        feeder.onLine = { [weak self] line in Task { @MainActor in self?.lastLine = line } }
        oldChainLoaded = Self.launchAgentLoaded("studio.soulbrews.relic-chain")
        refresh()
        if !oldChainLoaded { schedule(after: 5) }
        Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in Task { @MainActor in self?.refresh() } }
        pollChain()
    }

    func pollChain() {
        Task {
            if let s = try? await readOps(relicScan) {
                if watch.see(s) {
                    ended = s.sync
                    refresh()
                    DispatchQueue.main.asyncAfter(deadline: .now() + watch.hold) { [weak self] in self?.ended = nil }
                }
                chain = s
            }
            let next: TimeInterval = (chain?.running ?? false) || running ? 3 : 15
            DispatchQueue.main.asyncAfter(deadline: .now() + next) { [weak self] in self?.pollChain() }
        }
    }

    static func launchAgentLoaded(_ label: String) -> Bool {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        p.arguments = ["list", label]
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run(); p.waitUntilExit(); return p.terminationStatus == 0 } catch { return false }
    }

    var symbol: String {
        if running || chain?.running == true { return "arrow.triangle.2.circlepath" }
        if let e = ended { return e.contains("MISMATCH") ? "xmark.octagon" : "checkmark.circle" }
        if error != nil || !missing.isEmpty || !(status?.warnings.isEmpty ?? true) { return "exclamationmark.triangle" }
        return "archivebox"
    }

    func schedule(after seconds: TimeInterval) {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: seconds, repeats: false) { [weak self] _ in
            Task { @MainActor in await self?.runPass() }
        }
    }

    func refresh() {
        missing = Preconditions.missingExcludes(configAt: home.appendingPathComponent(".relic-scan/_config.json"))
        Task {
            do {
                status = try HubStatus.decode(try await fetch(hub, "api/status"))
                jobs = try JobLine.decode(try await fetch(hub, "api/log"), host: machine)
                error = nil
            } catch { self.error = "hub: \(error.localizedDescription)" }
        }
    }

    func runPass() async {
        guard !running else { return }
        running = true
        defer { running = false }
        if let r = await feeder.pass() {
            let parts = r.steps.map { name, res -> String in
                switch res {
                case .ok: return "\(name) ok"
                case .failed(let rc, let line): return "\(name) rc=\(rc): \(line)"
                case .stalled(let why): return why
                }
            }
            lastPass = "\(Date().formatted(date: .omitted, time: .shortened)) · " + parts.joined(separator: " · ")
        } else {
            lastPass = "skipped: another pass holds the lock"
        }
        refresh()
        oldChainLoaded = Self.launchAgentLoaded("studio.soulbrews.relic-chain")
        if !oldChainLoaded { schedule(after: feeder.backoff.delay()) }
    }
}

struct Panel: View {
    @ObservedObject var model: Model
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("relic5 · \(model.machine)").font(.headline)
                Spacer()
                Text(model.hub.host ?? "").font(.caption).foregroundStyle(.secondary)
            }
            if !model.missing.isEmpty {
                Label("relic-scan's _config.json does not exclude: \(model.missing.joined(separator: ", ")). A scan can hang on a privacy prompt.",
                      systemImage: "hand.raised").foregroundStyle(.orange).font(.caption)
            }
            if let me = model.status?.row(model.machine) {
                Grid(alignment: .leading, verticalSpacing: 3) {
                    GridRow { Text("newest row").foregroundStyle(.secondary); Text(me.newest ?? "unknown") }
                    GridRow { Text("behind now").foregroundStyle(.secondary); Text(me.behindSeconds.map { "\($0 / 60) min" } ?? "unknown") }
                    GridRow { Text("last push").foregroundStyle(.secondary); Text(me.pushedAt ?? "unknown") }
                    GridRow { Text("sync").foregroundStyle(.secondary); Text(me.sync ?? "no chain log").foregroundStyle(me.sync?.contains("MISMATCH") == true ? .red : .primary) }
                    GridRow { Text("vectors pending").foregroundStyle(.secondary); Text(me.vectorsPending.map(String.init) ?? "unknown") }
                }.font(.caption)
                Text(model.status?.othersLine(model.machine) ?? "").font(.caption).foregroundStyle(.secondary)
            } else {
                Text(model.error ?? "the hub has no row for \(model.machine) yet").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(model.status?.warnings ?? [], id: \.self) { Text("⚠︎ \($0)").font(.caption).foregroundStyle(.orange) }
            Divider()
            Activity(chain: model.chain, ended: model.ended)
            Divider()
            if model.oldChainLoaded {
                Text("watching: the LaunchAgent studio.soulbrews.relic-chain runs the passes (Run now still works)")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Text(model.running ? "running… \(model.lastLine)" : "last pass: \(model.lastPass)").font(.caption).lineLimit(3)
            ForEach(Array(model.jobs.enumerated()), id: \.offset) { _, j in
                Text("\(j.at.dropFirst(11).prefix(8)) \(j.verb) \(j.state)\(j.rc.map { " rc=\($0)" } ?? "") \(j.message ?? "")")
                    .font(.caption2.monospaced()).foregroundStyle(j.state == "error" ? .red : .secondary).lineLimit(1)
            }
            Divider()
            HStack {
                Button("Run now") { Task { await model.runPass() } }.disabled(model.running)
                Button("Open hub UI") { NSWorkspace.shared.open(model.hub) }
                Button("Refresh") { model.refresh() }
                Spacer()
                Button("Quit") { NSApplication.shared.terminate(nil) }
            }
        }.padding(14)
    }
}

/// The pass in flight, as relic-scan sees it: the stages (✓ done, ● running, · waiting), a bar of elapsed over the
/// typical total, the time left; when idle, how long the last pass took and when the next starts.
struct Activity: View {
    let chain: ChainSnapshot?
    let ended: String?
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let c = chain {
                HStack {
                    Text(c.running ? "pass running" : "idle").font(.subheadline.bold())
                    Spacer()
                    if c.running, let e = c.elapsedS {
                        Text("\(clock(e))\(c.typicalTotalS.map { " / typical \(clock($0))" } ?? "")").font(.caption.monospacedDigit())
                    } else if let took = c.tookS {
                        Text("took \(clock(took))\(c.nextInS.map { " · next in \(clock($0))" } ?? "")").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                    }
                }
                if let p = c.progress { ProgressView(value: p) }
                if let left = c.leftLine { Text(left).font(.caption).foregroundStyle(.secondary) }
                ForEach(Array(c.stages.enumerated()), id: \.offset) { _, st in
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(st.mark).frame(width: 12).foregroundStyle(st.state == "running" ? Color.accentColor : st.state == "done" ? .green : .secondary)
                        Text(st.name).frame(width: 118, alignment: .leading)
                        Text(st.secs.map { clock($0) } ?? (st.state == "running" ? "…" : "")).frame(width: 40, alignment: .trailing).monospacedDigit()
                        Text(st.typicalS.map { "~\(clock($0))" } ?? "").frame(width: 44, alignment: .trailing).foregroundStyle(.secondary).monospacedDigit()
                        Text(st.detail ?? "").foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                    }.font(.caption)
                }
                if let e = ended {
                    Text(e).font(.caption.bold()).foregroundStyle(e.contains("MISMATCH") ? .red : .green)
                }
            } else {
                Text("relic-scan ops: no snapshot (is relic-scan 26.10.24-alpha.1312+ in ~/.local/bin?)").font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}
