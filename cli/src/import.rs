//! `relic5 import`: push this machine's history to the hub ONCE, by hand (Nat, 2026-10-26: "we just do manual").
//! relic-chain's steps, once, with one push: relic-scan run (draws itself), relic-extract run, relic5-push, relic5
//! index --wait on the hub, relic5 embed (AC power only), then the SYNC check, then one RELIC5·IMPORT box in
//! relic-scan's palette. Exit 0 = every stage ran and the hub agrees. docs/IMPORT.md.
use crate::hub;
use crate::py::{commas, head};
use serde_json::Value;
use std::io::Write;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

const STREAMS: [&str; 3] = ["text", "thinking", "tools"];

fn rgb(r: u8, g: u8, b: u8, s: &str) -> String {
    format!("\x1b[38;2;{r};{g};{b}m{s}\x1b[0m")
}
fn pink(s: &str) -> String { rgb(255, 60, 172, s) }
fn cyan(s: &str) -> String { rgb(0, 214, 255, s) }
fn grey(s: &str) -> String { rgb(128, 136, 156, s) }
fn amber(s: &str) -> String { rgb(245, 183, 59, s) }
fn red(s: &str) -> String { rgb(255, 90, 90, s) }
fn bold(s: &str) -> String { format!("\x1b[1m{s}\x1b[0m") }
fn secs(t: Instant) -> String { format!("{:.1}s", t.elapsed().as_secs_f64()) }

fn stamp() -> String {
    let o = Command::new("date").arg("+%F %T").output().ok();
    o.map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default()
}

struct Ctx {
    machine: String,
    log: String,
    fails: u32,
    path: String,
}

impl Ctx {
    fn log(&self, line: &str) {
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&self.log) {
            let _ = if line.ends_with('\n') { write!(f, "{line}") } else { writeln!(f, "{line}") };
        }
    }
    fn cmd(&self, prog: &str) -> Command {
        let mut c = Command::new(prog);
        c.env("PATH", &self.path).env("RELIC5_MACHINE", &self.machine).env("RELIC5_HUB_URL", hub::url()).env_remove("RELIC5_HUB");
        c
    }
    /// run one stage under a spinner; its output goes to the log, its last line shows on failure
    fn stage(&mut self, name: &str, run: impl FnOnce(&Ctx) -> (i32, String)) -> (i32, String) {
        let t = Instant::now();
        let done = Arc::new(AtomicBool::new(false));
        let d = done.clone();
        let label = pink(&format!("{name:<7}"));
        let l2 = label.clone();
        print!("\x1b[?25l");
        let spin = std::thread::spawn(move || {
            let frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
            let mut i = 0;
            while !d.load(Ordering::Relaxed) {
                print!("\r\x1b[2K  {l2} {} {}", cyan(&frames[i % 10].to_string()), grey(&secs(t)));
                let _ = std::io::stdout().flush();
                i += 1;
                std::thread::sleep(Duration::from_millis(100));
            }
        });
        let (rc, out) = run(self);
        done.store(true, Ordering::Relaxed);
        let _ = spin.join();
        if !out.is_empty() {
            self.log(&out);
        }
        if rc == 0 {
            println!("\r\x1b[2K  {label} {} {}", cyan("✓"), grey(&secs(t)));
        } else {
            self.fails += 1;
            let last = out.trim().lines().last().unwrap_or("");
            println!("\r\x1b[2K  {label} {} {}  {last}", red(&format!("✗ rc={rc}")), grey(&secs(t)));
        }
        print!("\x1b[?25h");
        (rc, out)
    }
}

fn run(mut c: Command) -> (i32, String) {
    match c.stdin(Stdio::null()).output() {
        Ok(o) => (o.status.code().unwrap_or(1), String::from_utf8_lossy(&o.stdout).into_owned() + &String::from_utf8_lossy(&o.stderr)),
        Err(e) => (127, e.to_string()),
    }
}

/// this machine's chunks per stream: relic-extract status --json (relic-extract#45); an unreadable stream ("error")
/// is left out, so it never matches the hub
fn mine(c: &Ctx) -> Vec<Option<i64>> {
    let (_, out) = run({
        let mut x = c.cmd("relic-extract");
        x.args(["status", "--json"]);
        x
    });
    let j: Value = serde_json::from_str(out.trim()).unwrap_or(Value::Null);
    STREAMS
        .iter()
        .map(|s| {
            let x = &j["streams"][s];
            if x.get("error").is_some() { None } else { x["chunks"].as_i64() }
        })
        .collect()
}

fn fmt(c: &[Option<i64>]) -> String {
    STREAMS.iter().zip(c).map(|(s, n)| format!("{s}|{}", n.map(|n| n.to_string()).unwrap_or("?".into()))).collect::<Vec<_>>().join(" ")
}

pub fn main(args: &[String]) -> i32 {
    let home = std::env::var("HOME").unwrap_or_default();
    let machine_file = format!("{home}/.config/relic5/machine");
    let machine = std::env::var("RELIC5_MACHINE").ok().filter(|m| !m.is_empty()).or_else(|| {
        std::fs::read_to_string(&machine_file).ok().map(|s| s.trim().to_string()).filter(|m| !m.is_empty())
    });
    let Some(machine) = machine else {
        eprintln!("name this machine once: echo m5 > {machine_file}   (or set RELIC5_MACHINE)");
        return 2;
    };
    if args.iter().any(|a| a == "-h" || a == "--help") {
        println!("relic5 import: one manual import to the hub (scan, extract, push, index, embed, sync). docs/IMPORT.md");
        return 0;
    }
    let path = [format!("{home}/.local/bin"), format!("{home}/.cargo/bin"), "/opt/homebrew/bin".into(), "/usr/local/bin".into(),
        "/usr/bin".into(), "/bin".into(), std::env::var("PATH").unwrap_or_default()]
    .join(":");
    let log = std::env::var("RELIC_CHAIN_LOG").unwrap_or_else(|_| {
        if cfg!(target_os = "macos") { format!("{home}/Library/Logs/relic-chain.log") } else { format!("{home}/.local/state/relic-chain.log") }
    });
    let mut c = Ctx { machine: machine.clone(), log, fails: 0, path };
    // relic5-push: beside the core's checkout (bin/), else on PATH
    let push = [std::env::var("RELIC5_PUSH_BIN").unwrap_or_default(), "/opt/Code/github.com/Soul-Brews-Studio/relic5/bin/relic5-push".into(),
        format!("{home}/relic5/app/bin/relic5-push"), format!("{home}/.local/bin/relic5-push")]
    .into_iter()
    .find(|p| !p.is_empty() && std::path::Path::new(p).is_file())
    .unwrap_or_else(|| "relic5-push".into());
    let hub_url = hub::url();
    let hub_host = hub_url.split("://").nth(1).unwrap_or(&hub_url).split([':', '/']).next().unwrap_or("").to_string();
    let hub_ssh = std::env::var("RELIC5_HUB_SSH").unwrap_or_else(|_| format!("nat@{hub_host}"));
    let t0 = Instant::now();
    let start_epoch = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);

    println!("{}", grey(&format!("{} relic5 import ({machine} -> {hub_url})", stamp())));
    // the log keeps relic-chain's line format, so `relic-scan ops` reads a manual import as a pass (relic4-scan)
    c.log(&format!("{} chain start ({machine})", stamp()));

    // 1. relic-scan draws itself on the terminal
    let scan_rc = c.cmd("relic-scan").arg("run").status().map(|s| s.code().unwrap_or(1)).unwrap_or(127);
    if scan_rc != 0 {
        c.fails += 1;
    }
    // its summary: one JSON line per run in _scans.jsonl (job "index"; dry runs carry another job)
    let scan: Option<Value> = std::fs::read_to_string(format!("{home}/.relic-scan/_scans.jsonl")).ok().and_then(|t| {
        t.lines()
            .filter_map(|l| serde_json::from_str::<Value>(l).ok())
            .filter(|j| j["job"] == "index" && j["at"].as_u64().unwrap_or(0) + 1 >= start_epoch)
            .last()
    });
    let scan_line = match &scan {
        Some(j) => format!(
            "scan {:.1}s · new {} · grown {} · rewritten {} · gone {} · {} sessions · {} rows",
            j["scan_secs"].as_f64().unwrap_or(0.0), j["new"], j["grown"], j["rewritten"], j["gone"], commas(&j["sessions"]), commas(&j["rows"])
        ),
        None => format!("scan rc={scan_rc}: no summary line from this run"),
    };
    if let Some(j) = &scan {
        c.log(&format!("run: {scan_line}\nrun: done in {:.1}s", j["secs"].as_f64().unwrap_or(0.0)));
    }
    println!();

    // 2. extract, 3. push once and have the hub index it, 4. embed what has no vector yet (AC power only)
    let (_, ex) = c.stage("extract", |c| run({ let mut x = c.cmd("relic-extract"); x.arg("run"); x }));
    let cut = ex.lines().filter_map(|l| l.find(" part(s) cut").map(|i| (l, i))).last().map(|(l, _)| {
        // "3 part(s) cut in 4.7s · 338,865 chunks"
        let start = l.find(|ch: char| ch.is_ascii_digit()).unwrap_or(0);
        let l = &l[start..];
        let mut parts = l.split(" · ");
        format!("{} · {}", parts.next().unwrap_or(""), parts.next().unwrap_or("")).trim_end_matches(" · ").to_string()
    }).unwrap_or_else(|| "0 parts cut".into());
    // what this push carries: the sync below waits for the hub to hold at least this much
    let pushed = mine(&c);
    c.stage("push", |c| run(c.cmd(&push)));
    c.stage("index", |_| run({
        let mut x = Command::new("ssh");
        x.args(["-o", "BatchMode=yes", &hub_ssh, "~/relic5/app/.venv/bin/relic5 index --wait"]);
        x
    }));
    let on_ac = run({ let mut x = Command::new("pmset"); x.args(["-g", "batt"]); x }).1.contains("AC Power");
    let mut emb = "embed skipped (battery)".to_string();
    if on_ac && crate::core::find().is_some() {
        let core = crate::core::find().unwrap();
        let (_, out) = c.stage("embed", |c| run({ let mut x = c.cmd(core.to_str().unwrap_or("relic5-core")); x.args(["embed", "--limit", "20000"]); x }));
        emb = out.lines().filter(|l| l.starts_with("embed: ")).last()
            .map(|l| format!("embedded {}", l.trim_start_matches("embed: ").split(" -> ").next().unwrap_or("").trim()))
            .unwrap_or_else(|| "embed: nothing new".into());
    } else if !on_ac && !cfg!(target_os = "macos") {
        emb = "embed skipped (not a Mac)".into();
    }
    c.log(&format!("{} chain end", stamp()));

    // 5. sync: the hub against this machine, until they agree (the hub may still be indexing). Another pass may run
    // beside this one and cut more after this push, so "agree" is a range per stream: pushed <= hub <= now.
    let mut want: Vec<Option<i64>> = vec![None; 3];
    let mut got: Vec<Option<i64>> = vec![None; 3];
    let mut status: Option<Value> = None;
    let m2 = machine.clone();
    let (sync_rc, _) = c.stage("sync", |c| {
        for _ in 0..18 {
            want = mine(c);
            status = hub::peek("/api/status", 20);
            got = STREAMS.iter().map(|s| status.as_ref().and_then(|st| st["machines"][&m2][s]["rows"].as_i64())).collect();
            let ok = (0..3).all(|i| matches!((pushed[i], got[i], want[i]), (Some(p), Some(g), Some(w)) if p <= g && g <= w));
            if ok {
                return (0, String::new());
            }
            std::thread::sleep(Duration::from_secs(10));
        }
        (1, format!("{m2}: {}  hub: {}", fmt(&want), if status.is_some() { fmt(&got) } else { "unreachable".into() }))
    });
    c.log(&if sync_rc == 0 {
        format!("{} SYNC OK  {}", stamp(), fmt(&got))
    } else {
        format!("{} SYNC MISMATCH  {machine}: {}  hub: {}", stamp(), fmt(&want), fmt(&got))
    });

    // the box
    let f = hub::peek("/api/status", 10).map(|s| s["freshness"]["machines"][&machine].clone()).unwrap_or(Value::Null);
    let ok = c.fails == 0 && sync_rc == 0;
    let n = |i: usize| commas(&Value::from(got[i].unwrap_or(0)));
    let sx = |v: &Value| v.as_str().map(String::from).unwrap_or_else(|| v.to_string());
    let lines = [
        format!("hub {machine} · text {} · thinking {} · tools {}", n(0), n(1), n(2)),
        scan_line,
        format!("{cut} · {emb}"),
        format!(
            "pushed {} · newest {} UTC · lag {}s",
            crate::py::mid(&sx(&f["pushed_at"]), 11, 19),
            head(&sx(&f["newest_ts"]), 19).replace('T', " "),
            sx(&f["lag_s"])
        ),
        format!("{} · total {}", if sync_rc == 0 { "sync OK".to_string() } else { format!("sync MISMATCH: {machine} {}", fmt(&want)) }, secs(t0)),
        format!("▸ relic5 search …   ▸ {hub_url}"),
    ];
    let title = " ▓▒░ RELIC5·IMPORT ░▒▓ ";
    let width = |s: &str| s.chars().count();
    let w = lines.iter().map(|l| width(l)).max().unwrap_or(0);
    let b = |s: &str| if ok { cyan(s) } else { amber(s) };
    println!("{}{}{}", b("╭─"), bold(&pink(title)), b(&format!("{}╮", "─".repeat(w + 1 - width(title).min(w + 1)))));
    for l in &lines {
        println!("{} {l}{} {}", b("│"), " ".repeat(w - width(l)), b("│"));
    }
    println!("{}", b(&format!("╰{}╯", "─".repeat(w + 2))));
    if c.fails > 0 { 1 } else { sync_rc }
}
