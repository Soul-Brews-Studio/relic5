//! `relic5 hindsight`: relic5's history in Hindsight (vectorize-io/hindsight, `hindsight-embed`), the memory layer that
//! extracts facts, entities and observations. relic5 holds every turn; Hindsight holds what was learned from them.
//!
//!   relic5 hindsight status  [--bank B] [--json]            the bank, its queue and an ETA, the embed engines
//!   relic5 hindsight retain  <text> [--bank B] [--context C]
//!   relic5 hindsight recall  <query> [--bank B] [--limit 10] [--json]
//!   relic5 hindsight import  <session> [<session> ...] [--bank B] [--wait]   a relic5 session's turns, queued (async)
//!   relic5 hindsight import  --source memory|vault|git|thinking   a whole relic5 source from the hub, paced and resumable
//!                         (runs embed/hindsight-import.py; Nat, 2026-10-26: "memory first then vault, git, thinking")
//!   relic5 hindsight speed [--watch]                    embed + summarize speed per machine (m5, gb300), job + observations progress, ETA
//!   relic5 hindsight banks                              every bank (relic5, one per Discord server) with its counts
//!   relic5 hindsight backup                             pg_dump of the bank into relic5's backup volume (newest 3 kept)
//!   relic5 hindsight top                                   live TUI: bank, queue + sparkline + ETA, workers, feeder log
//!   relic5 hindsight workers [list]                       every worker: up, busy, utilization and work done (last minute, total)
//!   relic5 hindsight workers add embed|llm|rerank <name> <url> [--model M] [--slots N] [--api ollama|openai] [--batch N]
//!   relic5 hindsight workers rm embed|llm|rerank <name>   the dispatcher's registry (embed/embed-router.py, workers.json)
//!   relic5 hindsight import  --since 30d [--min-events 6] [--max N] [--bank B] [--wait]   every top-level session in the
//!                         window, newest first; a session already in the bank (its block #1 exists) is skipped
//!
//! HINDSIGHT_URL (default http://127.0.0.1:8888, the hindsight-embed daemon), bank default "relic5". The daemon
//! embeds through embed/embed-router.py (gb300 for big batches, the ANE for small ones). docs/HINDSIGHT.md.
use crate::cmds::Args;
use crate::hub::{self, Fail};
use crate::py::{commas, dumps, head, s, squash};
use serde_json::{Value, json};
use std::time::Duration;

fn base() -> String {
    std::env::var("HINDSIGHT_URL").unwrap_or_else(|_| "http://127.0.0.1:8888".into()).trim_end_matches('/').to_string()
}

fn http(method: &str, url: &str, body: Option<&Value>, timeout_s: u64) -> Result<Value, Fail> {
    let agent: ureq::Agent = ureq::Agent::config_builder()
        .http_status_as_error(false)
        .timeout_global(Some(Duration::from_secs(timeout_s)))
        .build()
        .into();
    let down = |e: ureq::Error| {
        Fail::Other(format!("relic5 hindsight: Hindsight unreachable ({}): {e}\n  start it: hindsight-embed daemon start", base()), 1)
    };
    let mut resp = match (method, body) {
        ("POST", Some(b)) => agent.post(url).header("Content-Type", "application/json").send(b.to_string()).map_err(down)?,
        _ => agent.get(url).call().map_err(down)?,
    };
    let code = resp.status().as_u16();
    let text = resp.body_mut().with_config().limit(u64::MAX).read_to_string().unwrap_or_default();
    if code >= 400 {
        return Err(Fail::Other(format!("relic5 hindsight: {code} {}", head(&text, 300)), if code == 400 || code == 404 || code == 422 { 2 } else { 1 }));
    }
    serde_json::from_str(&text).map_err(|e| Fail::Other(format!("relic5 hindsight: Hindsight sent no JSON ({e})"), 1))
}

fn bank_url(bank: &str, path: &str) -> String {
    format!("{}/v1/default/banks/{bank}{path}", base())
}

/// RFC 3339 -> epoch seconds (UTC offsets only as +HH:MM / Z)
fn epoch(t: &str) -> Option<f64> {
    let (date, rest) = t.split_once('T')?;
    let mut d = date.split('-').map(|x| x.parse::<i64>().ok());
    let (y, m, dd) = (d.next()??, d.next()??, d.next()??);
    let (clock, off) = match rest.find(['+', 'Z']).or_else(|| rest.rfind('-')) {
        Some(i) => (&rest[..i], &rest[i..]),
        None => (rest, "Z"),
    };
    let mut c = clock.split(':');
    let (hh, mm, ss): (f64, f64, f64) = (c.next()?.parse().ok()?, c.next()?.parse().ok()?, c.next().unwrap_or("0").parse().ok()?);
    let off_s = if off == "Z" || off.is_empty() {
        0.0
    } else {
        let sign = if off.starts_with('-') { -1.0 } else { 1.0 };
        let mut o = off[1..].split(':');
        sign * (o.next()?.parse::<f64>().ok()? * 3600.0 + o.next().unwrap_or("0").parse::<f64>().ok()? * 60.0)
    };
    // days from civil (Howard Hinnant)
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * (m + if m > 2 { -3 } else { 9 }) + 2) / 5 + dd - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146097 + doe - 719468;
    Some(days as f64 * 86400.0 + hh * 3600.0 + mm * 60.0 + ss - off_s)
}

fn now() -> f64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

fn dur(sec: f64) -> String {
    let s = sec.max(0.0).round() as u64;
    if s < 90 { format!("{s}s") } else if s < 5400 { format!("{}m", (s + 30) / 60) } else { format!("{}h{:02}m", s / 3600, (s % 3600) / 60) }
}

/// What is queued and how fast the bank has been working through it: pending / (completed per second, last hour)
fn eta(bank: &str) -> Result<Value, Fail> {
    let mut ops: Vec<Value> = Vec::new();
    for st in ["pending", "processing", "completed", "failed"] {
        let r = http("GET", &format!("{}?status={st}&limit=100", bank_url(bank, "/operations")), None, 30)?;
        ops.extend(r["operations"].as_array().cloned().unwrap_or_default());
    }
    let retain = |o: &&Value| o["operation_type"] == "retain";
    let open: Vec<&Value> = ops.iter().filter(retain).filter(|o| o["status"] == "pending" || o["status"] == "processing").collect();
    let t = now();
    let done: Vec<&Value> = ops
        .iter()
        .filter(retain)
        .filter(|o| o["status"] == "completed" && epoch(o["updated_at"].as_str().unwrap_or("")).is_some_and(|u| t - u < 3600.0))
        .collect();
    let items = |v: &[&Value]| v.iter().map(|o| o["items_count"].as_f64().unwrap_or(1.0).max(1.0)).sum::<f64>();
    let rate = if done.len() >= 2 {
        let first = done.iter().filter_map(|o| epoch(o["created_at"].as_str()?)).fold(f64::MAX, f64::min);
        let last = done.iter().filter_map(|o| epoch(o["updated_at"].as_str()?)).fold(0.0, f64::max);
        if last > first { Some(items(&done) / (last - first)) } else { None }
    } else {
        None
    };
    let left = items(&open);
    // The rate from the bank's own document count, sampled at each status call (~/.cache/relic5/memory-<bank>.tsv):
    // a block becomes one document, so documents per minute over the last 15 minutes is the real speed. The
    // finished-operation rate above is the fallback (a child operation holds ~13 blocks and finishes late).
    let docs = http("GET", &bank_url(bank, "/stats"), None, 30).ok().and_then(|st| st["total_documents"].as_f64());
    let doc_rate = docs.and_then(|d| sample_rate(bank, t, d));
    let rate = doc_rate.or(rate);
    Ok(json!({
        "open_operations": open.len(), "open_items": left, "done_last_hour": done.len(),
        "items_per_minute": rate.map(|r| (r * 60.0 * 10.0).round() / 10.0),
        "rate_from": if doc_rate.is_some() { "documents, last 15 min" } else { "finished operations, last hour" },
        "eta_s": if left == 0.0 { Some(0.0) } else { rate.map(|r| (left / r).round()) },
        "failed": ops.iter().filter(retain).filter(|o| o["status"] == "failed").count(),
    }))
}

/// Append (time, documents) and return documents per second over the samples of the last 15 minutes (>= 2 min apart)
fn sample_rate(bank: &str, t: f64, docs: f64) -> Option<f64> {
    let dir = format!("{}/.cache/relic5", std::env::var("HOME").unwrap_or_default());
    let _ = std::fs::create_dir_all(&dir);
    let f = format!("{dir}/memory-{bank}.tsv");
    let old: Vec<(f64, f64)> = std::fs::read_to_string(&f)
        .unwrap_or_default()
        .lines()
        .filter_map(|l| l.split_once('\t').and_then(|(a, b)| Some((a.parse().ok()?, b.parse().ok()?))))
        .filter(|(at, _): &(f64, f64)| t - at < 3600.0)
        .collect();
    let mut keep: Vec<String> = old.iter().map(|(a, b)| format!("{a}\t{b}")).collect();
    keep.push(format!("{t}\t{docs}"));
    let _ = std::fs::write(&f, keep.join("\n") + "\n");
    let first = old.iter().filter(|(at, _)| t - at <= 900.0).min_by(|x, y| x.0.total_cmp(&y.0))?;
    if t - first.0 < 120.0 || docs <= first.1 {
        return None;
    }
    Some((docs - first.1) / (t - first.0))
}

pub fn main(rest: Vec<String>, json_out: bool) -> Result<(), Fail> {
    let mut a = Args(rest);
    let bank = a.opt_or("--bank", "relic5")?;
    let sub = if a.0.is_empty() { "status".to_string() } else { a.0.remove(0) };
    match sub.as_str() {
        "status" => status(&bank, json_out),
        "speed" => speed(a.has("--watch")),
        "banks" => {
            // every bank on the daemon with its counts: relic5 (all of relic5) and one bank per Discord server
            let list = http("GET", &format!("{}/v1/default/banks", base()), None, 30)?;
            let banks = list["banks"].as_array().cloned().unwrap_or_default();
            let mut rows = Vec::new();
            for b in &banks {
                let id = s(&b["bank_id"]);
                let st = http("GET", &bank_url(&id, "/stats"), None, 30).unwrap_or(Value::Null);
                rows.push(json!({"bank": id, "documents": st["total_documents"], "memories": st["total_nodes"],
                                 "observations": st["total_observations"], "open_operations": st["pending_operations"],
                                 "about": b["mission"]}));
            }
            if json_out {
                println!("{}", dumps(&Value::Array(rows)));
            } else {
                println!("{:<44} {:>9} {:>10} {:>6} {:>5}  {}", "bank", "documents", "memories", "obs", "open", "about");
                for r in &rows {
                    println!("{:<44} {:>9} {:>10} {:>6} {:>5}  {}", s(&r["bank"]), commas(&r["documents"]), commas(&r["memories"]),
                             commas(&r["observations"]), s(&r["open_operations"]), head(&s(&r["about"]), 60));
                }
                println!("{} banks · dig into one: relic5 hindsight recall \"…\" --bank <bank>", rows.len());
            }
            Ok(())
        }
        "retain" => {
            let ctx = a.opt("--context")?;
            let text = a.0.join(" ");
            if text.is_empty() {
                return Err(Fail::Other("relic5 hindsight retain <text> [--bank B] [--context C]".into(), 2));
            }
            let mut item = json!({"content": text});
            if let Some(c) = ctx {
                item["context"] = json!(c);
            }
            let r = http("POST", &bank_url(&bank, "/memories"), Some(&json!({"items": [item], "async": false})), 600)?;
            if json_out { println!("{}", dumps(&r)) } else { println!("retained in {bank}: {}", s(&r.get("items_count").cloned().unwrap_or(json!(1)))) }
            Ok(())
        }
        "recall" => {
            let limit: usize = a.opt_or("--limit", "10")?.parse().map_err(|_| Fail::Other("--limit must be a number".into(), 2))?;
            let q = a.0.join(" ");
            if q.is_empty() {
                return Err(Fail::Other("relic5 hindsight recall <query> [--bank B] [--json]".into(), 2));
            }
            let r = http("POST", &bank_url(&bank, "/memories/recall"), Some(&json!({"query": q})), 120)?;
            if json_out {
                println!("{}", dumps(&r));
                return Ok(());
            }
            let res = r["results"].as_array().cloned().unwrap_or_default();
            for (i, x) in res.iter().take(limit).enumerate() {
                let when = [x.get("occurred_start"), x.get("mentioned_at")].into_iter().flatten().find(|v| !v.is_null()).map(s).unwrap_or_default();
                println!("{:>2}. [{}] {}  {}", i + 1, s(&x["type"]), head(&when, 10), squash(&s(&x["text"])));
            }
            println!("{} of {} memories (best first: gb300's reranker when it is up)", res.len().min(limit), res.len());
            Ok(())
        }
        "import" => import(&bank, a, json_out),
        "workers" => workers(a, json_out),
        "top" => std::process::exit(crate::top::top(&bank)),
        "backup" => {
            // bin/relic5-hindsight-backup: pg_dump of the bank into relic5's backup volume, verified, newest 3 kept
            use std::os::unix::process::CommandExt;
            let home = std::env::var("HOME").unwrap_or_default();
            let script = ["/opt/Code/github.com/Soul-Brews-Studio/relic5/bin".to_string(), format!("{home}/relic5/app/bin")]
                .into_iter()
                .map(|d| format!("{d}/relic5-hindsight-backup"))
                .find(|p| std::path::Path::new(p).is_file())
                .ok_or_else(|| Fail::Other("relic5 hindsight: bin/relic5-hindsight-backup not found".into(), 1))?;
            let err = std::process::Command::new(script).exec();
            Err(Fail::Other(format!("relic5 hindsight backup: {err}"), 1))
        }
        other => Err(Fail::Other(format!("relic5 hindsight: unknown '{other}' (status, speed, banks, retain, recall, import, workers, top, backup)"), 2)),
    }
}

fn status(bank: &str, json_out: bool) -> Result<(), Fail> {
    let st = http("GET", &bank_url(bank, "/stats"), None, 30)?;
    let e = eta(bank)?;
    let router = std::env::var("RELIC5_EMBED_ROUTER").unwrap_or_else(|_| "http://127.0.0.1:11436".into());
    let engines = http("GET", &format!("{router}/health"), None, 5).ok();
    if json_out {
        println!("{}", dumps(&json!({"bank": bank, "stats": st, "queue": e, "embed": engines})));
        return Ok(());
    }
    println!("hindsight {} · bank {bank}", base());
    println!(
        "  {} documents · {} memories ({}) · last write {}",
        commas(&st["total_documents"]),
        commas(&st["total_nodes"]),
        st["nodes_by_fact_type"].as_object().map(|m| m.iter().map(|(k, v)| format!("{k} {v}")).collect::<Vec<_>>().join(", ")).unwrap_or_default(),
        s(&st["last_memory_write_at"])
    );
    let eta_txt = match e["eta_s"].as_f64() {
        Some(0.0) => "nothing queued".to_string(),
        Some(x) => format!("ETA ≤ {} ({} blocks/min, from {})", dur(x), s(&e["items_per_minute"]), s(&e["rate_from"])),
        None => "ETA: measuring (needs two status calls 2 min apart, or two finished retains)".into(),
    };
    println!("  queue: {} operations, {} items open · {} done in the last hour · {} failed · {eta_txt}",
        e["open_operations"], e["open_items"].as_f64().unwrap_or(0.0).max(0.0) as u64, e["done_last_hour"], e["failed"]);
    match engines {
        Some(h) => println!(
            "  embed router {router}: ane {} ({} texts) · gb300 {} ({} texts) · last {}",
            s(&h["engines"]["ane"]["status"]), s(&h["stats"]["ane"]["texts"]),
            s(&h["engines"]["gb300"]["status"]), s(&h["stats"]["gb300"]["texts"]), s(&h["last"]["engine"])
        ),
        None => println!("  embed router {router}: down (embed/start.sh)"),
    }
    Ok(())
}

/// A relic5 session into Hindsight: its user and assistant turns (no tool output), in blocks of about 3,000 characters
/// (Hindsight's retain chunk). Each block is its own document, `<session>#<n>` (an async batch needs one id per item,
/// and the blocks are then retained in parallel); a re-import replaces them. metadata.relic5_session ties them together.
fn import(bank: &str, mut a: Args, json_out: bool) -> Result<(), Fail> {
    if let Some(src) = a.opt("--source")? {
        use std::os::unix::process::CommandExt;
        let home = std::env::var("HOME").unwrap_or_default();
        let script = [std::env::var("RELIC5_EMBED_DIR").unwrap_or_default(), "/opt/Code/github.com/Soul-Brews-Studio/relic5/embed".into(),
                      format!("{home}/relic5/app/embed")]
            .into_iter()
            .map(|d| format!("{d}/hindsight-import.py"))
            .find(|p| std::path::Path::new(p).is_file())
            .ok_or_else(|| Fail::Other("relic5 hindsight: embed/hindsight-import.py not found (set RELIC5_EMBED_DIR)".into(), 1))?;
        let err = std::process::Command::new("python3").arg(script).arg(&src).args(["--bank", bank]).args(&a.0).exec();
        return Err(Fail::Other(format!("relic5 hindsight: cannot run python3: {err}"), 1));
    }
    let wait = a.has("--wait");
    a.0.retain(|x| x != "--wait");
    if let Some(since) = a.opt("--since")? {
        let min: i64 = a.opt_or("--min-events", "6")?.parse().map_err(|_| Fail::Other("--min-events must be a number".into(), 2))?;
        let max: usize = a.opt_or("--max", "100000")?.parse().map_err(|_| Fail::Other("--max must be a number".into(), 2))?;
        a.0 = window(&since, min, max)?;
        let total = a.0.len();
        a.0.retain(|id| http("GET", &bank_url(bank, &format!("/documents/{id}%231")), None, 20).is_err());
        eprintln!("{total} sessions in the last {since} with at least {min} events; {} not in {bank} yet", a.0.len());
        if a.0.is_empty() {
            return Ok(());
        }
    }
    if a.0.is_empty() {
        return Err(Fail::Other("relic5 hindsight import <session> [...] [--bank B] [--wait]".into(), 2));
    }
    let mut out = Vec::new();
    for id in a.0.clone() {
        let mut turns: Vec<Value> = Vec::new();
        let mut off = 0i64;
        let mut meta = Value::Null;
        loop {
            let r = hub::call("/api/conversation", &[("id".into(), id.clone()), ("offset".into(), off.to_string()), ("limit".into(), "1000".into())])?;
            if meta.is_null() {
                meta = json!({"uuid": r["uuid"], "name": r["name"], "repo": r["repo"], "startedAt": r["startedAt"]});
            }
            turns.extend(r["turns"].as_array().cloned().unwrap_or_default());
            match r["next_offset"].as_i64() {
                Some(n) => off = n,
                None => break,
            }
        }
        let uuid = s(&meta["uuid"]);
        let ctx = format!("relic5 session {uuid} · {} · {}", s(&meta["repo"]), head(&s(&meta["name"]), 120));
        let mut items: Vec<Value> = Vec::new();
        let (mut block, mut ts) = (String::new(), String::new());
        let flush = |block: &mut String, ts: &mut String, items: &mut Vec<Value>| {
            if !block.is_empty() {
                let doc = format!("{uuid}#{}", items.len() + 1);
                items.push(json!({"content": block.clone(), "timestamp": ts.clone(), "context": ctx, "document_id": doc,
                                  "tags": ["relic5"], "metadata": {"relic5_session": uuid}}));
            }
            block.clear();
            ts.clear();
        };
        for t in turns.iter().filter(|t| t["role"] == "user" || t["role"] == "assistant") {
            let text = s(&t["text"]);
            if text.trim().is_empty() {
                continue;
            }
            let line = format!("[{}] {}: {}\n\n", head(&s(&t["ts"]), 16), s(&t["role"]), text.trim());
            if !block.is_empty() && block.chars().count() + line.chars().count() > 3000 {
                flush(&mut block, &mut ts, &mut items);
            }
            if ts.is_empty() {
                ts = s(&t["ts"]);
            }
            block.push_str(&line);
        }
        flush(&mut block, &mut ts, &mut items);
        if items.is_empty() {
            eprintln!("{id}: no user or assistant turns");
            continue;
        }
        let r = http("POST", &bank_url(bank, "/memories"), Some(&json!({"items": items, "async": true})), 120)?;
        if !json_out {
            println!("{uuid}: {} turns -> {} blocks queued in {bank} (operation {})", turns.len(), items.len(), s(&r["operation_id"]));
        }
        out.push(json!({"session": uuid, "turns": turns.len(), "items": items.len(), "operation_id": r["operation_id"]}));
    }
    if json_out {
        println!("{}", dumps(&Value::Array(out)));
    }
    if wait {
        loop {
            let e = eta(bank)?;
            if e["open_operations"].as_u64().unwrap_or(0) == 0 {
                break;
            }
            eprint!("\r\x1b[2K  {} operations open · {}", e["open_operations"], e["eta_s"].as_f64().map(|x| format!("ETA {}", dur(x))).unwrap_or("ETA: measuring".into()));
            std::thread::sleep(Duration::from_secs(5));
        }
        eprintln!("\r\x1b[2K  all retained");
    }
    Ok(())
}

fn router() -> String {
    std::env::var("RELIC5_EMBED_ROUTER").unwrap_or_else(|_| "http://127.0.0.1:11436".into()).trim_end_matches('/').to_string()
}

/// Speed per machine (Nat, 2026-10-26: "embed and summarize show me the speed we have m5 and gb300 make cli cool"):
/// every dispatcher worker grouped by the machine it runs on, embedding in texts/s, summarizing (LLM extraction) in
/// tokens/s and calls a minute, a utilization bar each; --watch redraws every 2 s.
fn speed(watch: bool) -> Result<(), Fail> {
    let (p, c, g, gr, am, z, b) = ("\x1b[38;2;255;60;172m", "\x1b[38;2;0;214;255m", "\x1b[38;2;128;136;156m",
                                   "\x1b[38;2;80;220;140m", "\x1b[38;2;245;183;59m", "\x1b[0m", "\x1b[1m");
    let bar = |u: f64, w: usize| -> String {
        let cells = (u.clamp(0.0, 1.0) * (w * 8) as f64).round() as usize;
        let mut s = "█".repeat(cells / 8);
        if cells % 8 > 0 {
            s.push(['▏', '▎', '▍', '▌', '▋', '▊', '▉'][cells % 8 - 1]);
        }
        format!("{s:<w$}")
    };
    let mut samples: Vec<(f64, f64)> = Vec::new();   // (time, items done) of the job, for its rate in --watch
    loop {
        let h = http("GET", &format!("{}/health", router()), None, 30)
            .map_err(|_| Fail::Other(format!("relic5 hindsight: the dispatcher is not up at {} (embed/start.sh)", router()), 1))?;
        let job = job_progress(&mut samples);
        let w = term_cols();
        // every line cut to the pane: a wrapped line broke the redraw (fit)
        // the whole frame is built first, then drawn over the last one in place: clearing first and fetching after
        // left the screen blank while ~40 requests ran (it blinked, Nat 2026-10-27)
        let mut frame: Vec<String> = Vec::new();
        macro_rules! put { ($($t:tt)*) => { frame.push(fit(&format!($($t)*), w)) } }
        let mut lines: Vec<(String, String)> = Vec::new();   // (machine, line)
        let (mut emb_s, mut tok_s, mut calls_m) = (0.0f64, 0.0f64, 0i64);
        for kind in ["embed", "llm", "rerank"] {
            for w in h["workers"][kind].as_array().cloned().unwrap_or_default() {
                let name = s(&w["name"]);
                let url = s(&w["url"]);
                let machine = if name.contains("gb300") || url.contains(":11437") || url.contains(":11510") { "gb300" } else { "m5" };
                let util = w["util"].as_f64().unwrap_or(0.0);
                let up = w["up"] == "ok";
                let (role, rate) = match kind {
                    "embed" => {
                        let r = w["texts_1m"].as_f64().unwrap_or(0.0) / 60.0;
                        emb_s += r;
                        ("embed    ", format!("{r:>7.1} texts/s"))
                    }
                    "llm" => {
                        let r = w["tokens_1m"].as_f64().unwrap_or(0.0) / 60.0;
                        tok_s += r;
                        calls_m += w["requests_1m"].as_i64().unwrap_or(0);
                        ("summarize", format!("{r:>7.0} tok/s  {:>3} calls/min", w["requests_1m"].as_i64().unwrap_or(0)))
                    }
                    _ => ("rerank   ", format!("{:>7.1} texts/s", w["texts_1m"].as_f64().unwrap_or(0.0) / 60.0)),
                };
                let model = if w["model"].is_null() { name.clone() } else { s(&w["model"]) };
                let color = if util > 0.9 { am } else { c };
                lines.push((machine.to_string(), format!(
                    "  {p}{role}{z} {:<8} {color}{}{z} {b}{:>4.0}%{z}  {gr}{rate}{z}  {g}{} total · {}/{} busy · {}{z}{}",
                    name, bar(util, 16), util * 100.0, if kind == "llm" { commas(&w["tokens"]) + " tok" } else { commas(&w["texts"]) + " texts" },
                    w["inflight"], w["slots"].as_i64().unwrap_or(1), head(&model, 28), if up { String::new() } else { format!(" {am}DOWN{z}") })));
            }
        }
        put!("{p}{b} ▓▒░ RELIC5·SPEED ░▒▓ {z}{g} embed + summarize · last minute · {}{z}", clock_now());
        // NOW: what is being done, its progress, ETA, and what the LLM's calls of the last 2 minutes went to, at the
        // top so a short pane shows it (Nat, 2026-10-27: "i dont know progress and what happened, what doing")
        match feeder_progress() {
            Some((name, sent, todo, rate)) => {
                let eta = if rate > 0.0 { fmt_secs((todo - sent) / rate * 60.0) } else { "measuring".into() };
                put!("  {am}{b}NOW{z}  {b}{}{z}  {gr}{}{z} {b}{:.1}%{z}  {} / {}  {g}{} · ETA {eta}{z}", format!("{}{}", if name.starts_with("discord") { "" } else { "relic5 " }, name.replace(" · upgrade", " · full extraction")),
                     bar(if todo > 0.0 { sent / todo } else { 0.0 }, 16), if todo > 0.0 { sent / todo * 100.0 } else { 0.0 },
                     commas(&Value::from(sent as i64)), commas(&Value::from(todo as i64)),
                     if rate > 0.0 { format!("{rate:.0} items/min") } else { "rate: measuring".into() });
            }
            None => put!("  {am}{b}NOW{z}  {g}no import running{z}"),
        }
        if let Some(line) = llm_work() {
            put!("  {am}{b}LLM{z}  {line}");
        }
        for m in ["m5", "gb300"] {
            let ls: Vec<&String> = lines.iter().filter(|(mm, _)| mm == m).map(|(_, l)| l).collect();
            if ls.is_empty() {
                continue;
            }
            let about = if m == "m5" { "M5 Max · ANE + GPU" } else { "GB300 · shared GPU, through the tunnel" };
            put!("{c}╭─ {b}{m}{z}{c} · {about} {}{z}", "─".repeat(60usize.saturating_sub(about.len())));
            for l in ls {
                put!("{c}│{z}{l}");
            }
            put!("{c}╰{}{z}", "─".repeat(66));
        }
        put!("  {b}total{z}  embed {gr}{emb_s:.1} texts/s{z} · summarize {gr}{tok_s:.0} tok/s{z} ({calls_m} calls/min)");
        if let Some((name, done, total, rate, banks)) = &job {
            let pct = if *total > 0.0 { done / total } else { 0.0 };
            let eta = if done >= total { "done".into() } else if *rate < 0.0 { "measuring".into() } else if *rate > 0.0 { fmt_secs((total - done) / rate * 60.0) } else { "?".into() };
            put!("{c}╭─ {b}job{z}{c} · {name} {}{z}", "─".repeat(60usize.saturating_sub(name.chars().count())));
            put!("{c}│{z}  {gr}{}{z} {b}{:>5.1}%{z}  {} / {} items  {g}{}{}{z}",
                     bar(pct, 30), pct * 100.0, commas(&Value::from(*done as i64)), commas(&Value::from(*total as i64)),
                     if done >= total { String::new() } else { format!(" · ETA {eta}") },
                     if done >= total { "finished".to_string() } else if *rate < 0.0 { "rate: measuring (1 min)".to_string() } else { format!("{rate:.0} items/min") });
            for (bank, d, t) in banks {
                if d < t {
                    put!("{c}│{z}    {g}{:<34}{z} {} {:>5.1}%  {}/{}", head(bank, 34), bar(d / t, 12), d / t * 100.0,
                             commas(&Value::from(*d as i64)), commas(&Value::from(*t as i64)));
                }
            }
            put!("{c}╰{}{z}", "─".repeat(66));
        }
        // the importer's own run (embed/hindsight-import.py: ~/.cache/relic5/hindsight-feeder.json), e.g. the sessions
        // full-extraction pass: sent / to do, the rate over the last 10 minutes of samples, ETA
        if let Some((name, sent, todo, rate)) = feeder_progress() {
            let pct = if todo > 0.0 { sent / todo } else { 0.0 };
            let eta = if rate < 0.0 { "measuring".to_string() } else if rate > 0.0 { fmt_secs((todo - sent) / rate * 60.0) } else { "?".into() };
            put!("{c}╭─ {b}import{z}{c} · {name} {}{z}", "─".repeat(58usize.saturating_sub(name.chars().count())));
            put!("{c}│{z}  {gr}{}{z} {b}{:>5.1}%{z}  {} / {} items  {g}{} · ETA {eta}{z}", bar(pct, 30), pct * 100.0,
                 commas(&Value::from(sent as i64)), commas(&Value::from(todo as i64)),
                 if rate < 0.0 { "rate: measuring (1 min)".to_string() } else { format!("{rate:.0} items/min") });
            put!("{c}╰{}{z}", "─".repeat(66));
        }
        // observations: each bank's facts still waiting for consolidation, against all its facts
        if let Some((done, total, pending, rate, banks)) = consolidation_progress() {
            if pending > 0.0 {
                let pct = if total > 0.0 { done / total } else { 0.0 };
                let eta = if rate < 0.0 { "measuring".to_string() } else if rate > 0.0 { fmt_secs(pending / rate * 60.0) } else { "?".into() };
                put!("{c}╭─ {b}observations{z}{c} · consolidation of the facts {}{z}", "─".repeat(28));
                put!("{c}│{z}  {gr}{}{z} {b}{:>5.1}%{z}  {} waiting  {g}{} · ETA {eta}{z}", bar(pct, 30), pct * 100.0,
                     commas(&Value::from(pending as i64)),
                     if rate < 0.0 { "rate: measuring (1 min)".to_string() } else { format!("{rate:.0} facts/min") });
                for (bank, p_, t) in banks.iter().take(5) {
                    put!("{c}│{z}    {g}{:<34}{z} {} {:>5.1}%  {} waiting", head(&bank.replace("discord-", ""), 34),
                         bar((t - p_) / t, 12), (t - p_) / t * 100.0, commas(&Value::from(*p_ as i64)));
                }
                put!("{c}╰{}{z}", "─".repeat(66));
            }
        }
        if watch {
            let mut out = String::from("\x1b[H");
            for l in &frame {
                out.push_str(l);
                out.push_str("\x1b[K\n");
            }
            out.push_str("\x1b[J");
            print!("{out}");
            let _ = std::io::Write::flush(&mut std::io::stdout());
        } else {
            for l in &frame {
                println!("{l}");
            }
            return Ok(());
        }
        std::thread::sleep(std::time::Duration::from_secs(2));
    }
}

/// The running job (~/.cache/relic5/hindsight-job.json, written by embed/discord-all.sh: items per bank): items done =
/// each bank's documents (Hindsight makes a document when an item's extraction finished), capped at its item count.
/// Returns (name, done, total, items/min, unfinished banks with done/total). The rate is from the --watch samples of the
/// last 10 minutes (saved samples, shared by every call), "measuring" for its first minute.
#[allow(clippy::type_complexity)]
fn job_progress(samples: &mut Vec<(f64, f64)>) -> Option<(String, f64, f64, f64, Vec<(String, f64, f64)>)> {
    let path = format!("{}/.cache/relic5/hindsight-job.json", std::env::var("HOME").unwrap_or_default());
    let j: Value = serde_json::from_str(&std::fs::read_to_string(path).ok()?).ok()?;
    let (mut done, mut total, mut open) = (0.0, 0.0, Vec::new());
    for (bank, n) in j["banks"].as_object()? {
        let t = n.as_f64().unwrap_or(0.0);
        if t <= 0.0 {
            continue;
        }
        let d = http("GET", &bank_url(bank, "/stats"), None, 10).ok().and_then(|st| st["total_documents"].as_f64()).unwrap_or(0.0).min(t);
        done += d;
        total += t;
        open.push((bank.clone(), d, t));
    }
    // The rate from samples saved beside the job file (~/.cache/relic5/hindsight-job.tsv: time, items done), shared by
    // every `speed` call: only samples of this job (after its "started") over the last 10 minutes, and after the newest
    // drop (a recount of the job lowers "done"), so neither a recount nor documents made before the job skew it.
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
    let started = j["started"].as_f64().unwrap_or(0.0);
    let tsv = format!("{}/.cache/relic5/hindsight-job.tsv", std::env::var("HOME").unwrap_or_default());
    samples.clear();
    for l in std::fs::read_to_string(&tsv).unwrap_or_default().lines() {
        let mut f = l.split('\t').filter_map(|x| x.parse::<f64>().ok());
        if let (Some(t), Some(d)) = (f.next(), f.next()) {
            if t >= started && now - t <= 600.0 {
                samples.push((t, d));
            }
        }
    }
    if samples.last().is_none_or(|(t, _)| now - t >= 10.0) {
        samples.push((now, done));
        let keep: String = samples.iter().map(|(t, d)| format!("{t:.0}\t{d:.0}\n")).collect();
        let _ = std::fs::write(&tsv, keep);
    }
    let cut = samples.windows(2).rposition(|w| w[1].1 < w[0].1).map(|i| i + 1).unwrap_or(0);
    let (t0, d0) = samples[cut];
    let rate = if now - t0 >= 60.0 && done >= d0 { (done - d0) / (now - t0) * 60.0 } else { -1.0 };   // -1: measuring
    open.sort_by(|a, b| (b.2 - b.1).total_cmp(&(a.2 - a.1)));
    open.truncate(5);
    Some((s(&j["name"]), done, total, rate, open))
}

/// Whether each bank has observations on, and when that was asked: re-asked after 60 s (a board running for hours
/// kept showing the Discord banks after their observations were switched off, 2026-10-27 07:52)
static OBS_ON: std::sync::LazyLock<std::sync::Mutex<std::collections::HashMap<String, (bool, u64)>>> =
    std::sync::LazyLock::new(|| std::sync::Mutex::new(std::collections::HashMap::new()));

/// Consolidation across every bank with observations on: (facts done, facts, facts waiting, facts/min, banks with the most waiting).
/// Facts = world + experience; waiting = the bank's pending_consolidation. The rate comes from samples saved in
/// ~/.cache/relic5/hindsight-consolidation.tsv (shared by every call, last 10 minutes); -1 while measuring.
#[allow(clippy::type_complexity)]
fn consolidation_progress() -> Option<(f64, f64, f64, f64, Vec<(String, f64, f64)>)> {
    let list = http("GET", &format!("{}/v1/default/banks", base()), None, 20).ok()?;
    let (mut total, mut pending, mut banks) = (0.0, 0.0, Vec::new());
    for b in list["banks"].as_array()? {
        let id = s(&b["bank_id"]);
        // a bank with observations off (relic5: embed-first) never consolidates; its waiting count is not work
        let now_s = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
        let cached = OBS_ON.lock().unwrap().get(&id).copied();
        let on = match cached {
            Some((v, at)) if now_s.saturating_sub(at) < 60 => v,
            _ => {
                let v = http("GET", &bank_url(&id, "/config"), None, 10).map(|c| c["config"]["enable_observations"] != false).unwrap_or(true);
                OBS_ON.lock().unwrap().insert(id.clone(), (v, now_s));
                v
            }
        };
        if !on {
            continue;
        }
        let Ok(st) = http("GET", &bank_url(&id, "/stats"), None, 10) else { continue };
        let f = &st["nodes_by_fact_type"];
        let t = f["world"].as_f64().unwrap_or(0.0) + f["experience"].as_f64().unwrap_or(0.0);
        let p = st["pending_consolidation"].as_f64().unwrap_or(0.0).min(t);
        total += t;
        pending += p;
        if p > 0.0 {
            banks.push((id, p, t));
        }
    }
    banks.sort_by(|a, b| b.1.total_cmp(&a.1));
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
    let tsv = format!("{}/.cache/relic5/hindsight-consolidation.tsv", std::env::var("HOME").unwrap_or_default());
    let mut pts: Vec<(f64, f64)> = std::fs::read_to_string(&tsv).unwrap_or_default().lines()
        .filter_map(|l| { let mut f = l.split('\t').filter_map(|x| x.parse::<f64>().ok()); Some((f.next()?, f.next()?)) })
        .filter(|(t, _)| now - t <= 600.0).collect();
    if pts.last().is_none_or(|(t, _)| now - t >= 10.0) {
        pts.push((now, pending));
        let _ = std::fs::write(&tsv, pts.iter().map(|(t, p)| format!("{t:.0}\t{p:.0}\n")).collect::<String>());
    }
    // waiting only falls while consolidation runs; a rise means new facts came in: start after the newest rise
    let cut = pts.windows(2).rposition(|w| w[1].1 > w[0].1).map(|i| i + 1).unwrap_or(0);
    let (t0, p0) = pts[cut];
    let rate = if now - t0 >= 60.0 && pending <= p0 { (p0 - pending) / (now - t0) * 60.0 } else { -1.0 };
    Some((total - pending, total, pending, rate, banks))
}

/// The importer's running pass, when one is running (state not "done", status written in the last 5 minutes):
/// (source · strategy, items sent, items to do, items/min from ~/.cache/relic5/hindsight-feeder.tsv; -1 measuring)
fn feeder_progress() -> Option<(String, f64, f64, f64)> {
    let home = std::env::var("HOME").unwrap_or_default();
    let f: Value = serde_json::from_str(&std::fs::read_to_string(format!("{home}/.cache/relic5/hindsight-feeder.json")).ok()?).ok()?;
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
    if s(&f["state"]).starts_with("done") || now - f["at"].as_f64().unwrap_or(0.0) > 300.0 {
        return None;
    }
    let (sent, todo) = (f["queued"].as_f64().unwrap_or(0.0), f["todo"].as_f64().unwrap_or(0.0));
    let key = format!("{}\t{}", s(&f["source"]), f["started"].as_f64().unwrap_or(0.0));
    let tsv = format!("{home}/.cache/relic5/hindsight-feeder.tsv");
    let mut pts: Vec<(f64, f64)> = std::fs::read_to_string(&tsv).unwrap_or_default().lines()
        .filter(|l| l.starts_with(&format!("{key}\t")))
        .filter_map(|l| { let v: Vec<f64> = l.rsplitn(3, '\t').take(2).filter_map(|x| x.parse().ok()).collect(); (v.len() == 2).then(|| (v[1], v[0])) })
        .filter(|(t, _)| now - t <= 600.0).collect();
    if pts.last().is_none_or(|(t, _)| now - t >= 10.0) {
        pts.push((now, sent));
        let _ = std::fs::write(&tsv, pts.iter().map(|(t, n)| format!("{key}\t{t:.0}\t{n:.0}\n")).collect::<String>());
    }
    let (t0, n0) = pts[0];
    let rate = if now - t0 >= 60.0 && sent >= n0 { (sent - n0) / (now - t0) * 60.0 } else { -1.0 };
    Some((format!("{} · {}", s(&f["source"]), s(&f["strategy"])), sent, todo, rate))
}

/// What the LLM calls of the last 2 minutes went to, from the hindsight-embed log (~/.hindsight/profiles/relic.log):
/// fact extraction (retain) vs consolidation per bank. None when there is no log or no call.
fn llm_work() -> Option<String> {
    use std::io::{Read, Seek, SeekFrom};
    let path = format!("{}/.hindsight/profiles/relic.log", std::env::var("HOME").unwrap_or_default());
    let mut f = std::fs::File::open(path).ok()?;
    let len = f.metadata().ok()?.len();
    f.seek(SeekFrom::Start(len.saturating_sub(3_000_000))).ok()?;
    let mut buf = String::new();
    let mut raw = Vec::new();
    f.read_to_end(&mut raw).ok()?;
    buf.push_str(&String::from_utf8_lossy(&raw));
    let cutoff = unsafe {
        let t = libc::time(std::ptr::null_mut()) - 120;
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&t, &mut tm);
        format!("{:04}-{:02}-{:02} {:02}:{:02}:{:02}", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec)
    };
    let (mut extract, mut cons) = (0usize, std::collections::BTreeMap::<String, usize>::new());
    for l in buf.lines().filter(|l| l.len() > 19 && l[..19] >= cutoff[..]) {
        if l.contains("scope=retain") {
            extract += 1;
        } else if let Some(i) = l.find("[CONSOLIDATION] bank=") {
            let b: String = l[i + 21..].chars().take_while(|c| !c.is_whitespace()).collect();
            *cons.entry(if b.starts_with("discord-") { "discord".to_string() } else { b }).or_default() += 1;
        }
    }
    let total = extract + cons.values().sum::<usize>();
    if total == 0 {
        return None;
    }
    let pc = |n: usize| n * 100 / total;
    let mut parts = vec![format!("extracting facts {}%", pc(extract))];
    for (b, n) in &cons {
        parts.push(format!("consolidating {b} {}%", pc(*n)));
    }
    Some(format!("{} \x1b[38;2;128;136;156m(last 2 min, {total} calls)\x1b[0m", parts.join(" · ")))
}

fn fmt_secs(x: f64) -> String {
    let m = (x / 60.0).round() as i64;
    if m >= 60 { format!("{}h {:02}m", m / 60, m % 60) } else { format!("{m}m") }
}

/// The terminal's width in columns (80 when it cannot tell, e.g. a pipe)
fn term_cols() -> usize {
    unsafe {
        let mut ws: libc::winsize = std::mem::zeroed();
        if libc::ioctl(1, libc::TIOCGWINSZ, &mut ws) == 0 && ws.ws_col > 0 { ws.ws_col as usize } else { 80 }
    }
}

/// A line cut to `w` visible columns, colour codes kept (a wrapped line broke the --watch redraw: Nat's screenshot,
/// 2026-10-27, a narrow pane showed old frames under the new one)
fn fit(line: &str, w: usize) -> String {
    let mut out = String::new();
    let (mut n, mut esc) = (0usize, false);
    for c in line.chars() {
        if esc {
            out.push(c);
            if c.is_ascii_alphabetic() { esc = false; }
            continue;
        }
        if c == '\x1b' { esc = true; out.push(c); continue; }
        if n >= w { continue; }
        out.push(c);
        n += 1;
    }
    out + "\x1b[0m"
}

fn clock_now() -> String {
    unsafe {
        let t = libc::time(std::ptr::null_mut());
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&t, &mut tm);
        format!("{:02}:{:02}:{:02}", tm.tm_hour, tm.tm_min, tm.tm_sec)
    }
}

/// The dispatcher's workers: list (with utilization and work done), add, rm
fn workers(mut a: Args, json_out: bool) -> Result<(), Fail> {
    let sub = if a.0.is_empty() { "list".to_string() } else { a.0.remove(0) };
    match sub.as_str() {
        "list" => {
            let h = http("GET", &format!("{}/health", router()), None, 30)
                .map_err(|_| Fail::Other(format!("relic5 hindsight: the dispatcher is not up at {} (embed/start.sh)", router()), 1))?;
            if json_out {
                println!("{}", dumps(&h["workers"]));
                return Ok(());
            }
            println!("dispatcher {} · registry {}", router(), s(&h["registry"]));
            println!("{:<7} {:<7} {:<4} {:>9} {:>6}  {:>8} {:>8} {:>9}  {:>9} {:>9} {:>6} {:>6}  {}",
                     "kind", "name", "up", "busy", "util", "calls/1m", "texts/1m", "tokens/1m", "calls", "texts", "err", "avg_s", "model / url");
            for kind in ["llm", "embed", "rerank"] {
                for w in h["workers"][kind].as_array().cloned().unwrap_or_default() {
                    let slots = w["slots"].as_i64().unwrap_or(1);
                    let busy = format!("{}/{}", w["inflight"].as_i64().unwrap_or(0), slots);
                    let util = format!("{:.0}%", w["util"].as_f64().unwrap_or(0.0) * 100.0);
                    let model = if w["model"].is_null() { s(&w["url"]) } else { format!("{} · {}", s(&w["model"]), s(&w["url"])) };
                    println!("{:<7} {:<7} {:<4} {:>9} {:>6}  {:>8} {:>8} {:>9}  {:>9} {:>9} {:>6} {:>6}  {}",
                             kind, s(&w["name"]), if w["up"] == "ok" { "ok" } else { "DOWN" }, busy, util,
                             s(&w["requests_1m"]), commas(&w["texts_1m"]), commas(&w["tokens_1m"]),
                             commas(&w["requests"]), commas(&w["texts"]), s(&w["errors"]), s(&w["avg_s"]), model);
                }
            }
            Ok(())
        }
        "add" => {
            let model = a.opt("--model")?;
            let slots = a.opt("--slots")?;
            let api = a.opt("--api")?;
            let batch = a.opt("--batch")?;
            let note = a.opt("--note")?;
            if a.0.len() != 3 {
                return Err(Fail::Other("relic5 hindsight workers add embed|llm|rerank <name> <url> [--model M] [--slots N] [--api ollama|openai] [--batch N] [--note T]".into(), 2));
            }
            let mut w = json!({"kind": a.0[0], "name": a.0[1], "url": a.0[2]});
            if let Some(m) = model { w["model"] = json!(m) }
            if let Some(n) = slots { w["slots"] = json!(n.parse::<i64>().map_err(|_| Fail::Other("--slots must be a number".into(), 2))?) }
            if let Some(x) = api { w["api"] = json!(x) }
            if let Some(n) = batch { w["batch"] = json!(n.parse::<i64>().map_err(|_| Fail::Other("--batch must be a number".into(), 2))?) }
            if let Some(t) = note { w["note"] = json!(t) }
            let r = http("POST", &format!("{}/workers", router()), Some(&w), 120)?;
            println!("{}", if json_out { dumps(&r) } else { format!("added {} worker {}", s(&r["added"]), s(&r["worker"]["name"])) });
            Ok(())
        }
        "rm" => {
            if a.0.len() != 2 {
                return Err(Fail::Other("relic5 hindsight workers rm embed|llm|rerank <name>".into(), 2));
            }
            let agent: ureq::Agent = ureq::Agent::config_builder().http_status_as_error(false).build().into();
            let mut r = agent
                .delete(&format!("{}/workers?kind={}&name={}", router(), a.0[0], a.0[1]))
                .call()
                .map_err(|e| Fail::Other(format!("relic5 hindsight: dispatcher unreachable: {e}"), 1))?;
            let code = r.status().as_u16();
            let body = r.body_mut().read_to_string().unwrap_or_default();
            if code >= 400 {
                return Err(Fail::Other(format!("relic5 hindsight: {code} {body}"), 2));
            }
            println!("removed {} worker {}", a.0[0], a.0[1]);
            Ok(())
        }
        other => Err(Fail::Other(format!("relic5 hindsight workers: unknown '{other}' (list, add, rm)"), 2)),
    }
}

/// Top-level sessions in a window, newest first. /api/sessions answers at most 500 at a time, so it pages back with
/// `until` = the oldest end time seen.
fn window(since: &str, min_events: i64, max: usize) -> Result<Vec<String>, Fail> {
    let mut ids: Vec<String> = Vec::new();
    let mut seen = std::collections::HashSet::new();
    let mut until: Option<String> = None;
    loop {
        let mut q = vec![("since".to_string(), since.to_string()), ("limit".to_string(), "500".to_string())];
        if let Some(u) = &until {
            q.push(("until".into(), u.clone()));
        }
        let r = hub::call("/api/sessions", &q)?;
        let page = r["sessions"].as_array().cloned().unwrap_or_default();
        let mut new = 0;
        for x in &page {
            let id = s(&x["uuid"]);
            if x["uuid"].is_null() || !seen.insert(id.clone()) {
                continue;
            }
            new += 1;
            if x["events"].as_i64().unwrap_or(0) >= min_events {
                ids.push(id);
            }
        }
        let oldest = page.iter().filter_map(|x| x["endedAt"].as_str()).min().map(String::from);
        if new == 0 || page.len() < 500 || ids.len() >= max || oldest.is_none() || oldest == until {
            break;
        }
        until = oldest;
    }
    ids.truncate(max);
    Ok(ids)
}

#[cfg(test)]
mod tests {
    #[test]
    fn epoch_parses_hindsight_times() {
        assert_eq!(super::epoch("1970-01-01T00:00:00Z"), Some(0.0));
        assert_eq!(super::epoch("2026-10-26T02:24:14+00:00"), Some(1792981454.0));
        assert_eq!(super::epoch("2026-10-26T09:24:14+07:00"), Some(1792981454.0));
    }
}
