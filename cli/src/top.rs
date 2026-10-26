//! `relic5 memory top`: the Hindsight import and its workers, live, in relic-scan's look (ratatui, same palette).
//! Nat, 2026-10-26: "cool like tui? of relic scanner?".
//!
//!   bank        documents, memories by type, observations, consolidation waiting, last write
//!   queue       open operations, documents a minute (sparkline, 15 minutes), the feeder's ETA
//!   workers     every dispatcher worker: up, busy x/slots, utilization bar, calls / tokens / texts a minute, totals
//!   feeder      the last lines of ~/Library/Logs/hindsight-import.log
//!
//! Refreshes every 2 s (a background thread does the HTTP, so keys never wait). q / Esc quits, r refreshes now.
use ratatui::crossterm::event::{self, Event, KeyCode, KeyEventKind};
use ratatui::layout::{Constraint, Layout};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, BorderType, Cell, Paragraph, Row, Sparkline, Table};
use ratatui::{DefaultTerminal, Frame};
use serde_json::Value;
use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

const CYAN: Color = Color::Rgb(0, 214, 255);
const PINK: Color = Color::Rgb(255, 60, 172);
const AMBER: Color = Color::Rgb(255, 184, 0);
const VIOLET: Color = Color::Rgb(160, 120, 255);
const RED: Color = Color::Rgb(255, 99, 72);
const DIM: Color = Color::Rgb(128, 136, 156);
const GREEN: Color = Color::Rgb(80, 220, 140);

#[derive(Default, Clone)]
struct Snap {
    at: String,
    stats: Option<Value>,
    health: Option<Value>,
    feeder: Vec<String>,
    // (seconds since start, documents, memories, open operations)
    hist: VecDeque<(f64, f64, f64, f64)>,
    err: Option<String>,
}

fn get(url: &str) -> Option<Value> {
    let agent: ureq::Agent = ureq::Agent::config_builder().timeout_global(Some(Duration::from_secs(8))).build().into();
    let mut r = agent.get(url).call().ok()?;
    serde_json::from_str(&r.body_mut().read_to_string().ok()?).ok()
}

fn fetch(snap: &Arc<Mutex<Snap>>, bank: &str, t0: Instant) {
    let hs = std::env::var("HINDSIGHT_URL").unwrap_or_else(|_| "http://127.0.0.1:8888".into());
    let router = std::env::var("RELIC5_EMBED_ROUTER").unwrap_or_else(|_| "http://127.0.0.1:11436".into());
    let stats = get(&format!("{}/v1/default/banks/{bank}/stats", hs.trim_end_matches('/')));
    let health = get(&format!("{}/health", router.trim_end_matches('/')));
    let log = format!("{}/Library/Logs/hindsight-import.log", std::env::var("HOME").unwrap_or_default());
    let feeder: Vec<String> = std::fs::read_to_string(&log)
        .unwrap_or_default()
        .lines()
        .rev()
        .take(6)
        .map(String::from)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect();
    let mut s = snap.lock().unwrap();
    s.at = clock();
    s.err = match (&stats, &health) {
        (None, _) => Some(format!("Hindsight not answering at {hs} (hindsight-embed daemon start)")),
        (_, None) => Some(format!("dispatcher not answering at {router} (embed/start.sh)")),
        _ => None,
    };
    if let Some(st) = &stats {
        let f = |k: &str| st[k].as_f64().unwrap_or(0.0);
        s.hist.push_back((t0.elapsed().as_secs_f64(), f("total_documents"), f("total_nodes"), f("pending_operations")));
        while s.hist.len() > 2 && s.hist[0].0 < t0.elapsed().as_secs_f64() - 900.0 {
            s.hist.pop_front();
        }
    }
    s.stats = stats;
    s.health = health;
    s.feeder = feeder;
}

/// local time HH:MM:SS (libc, no extra crate)
fn clock() -> String {
    unsafe {
        let t = libc::time(std::ptr::null_mut());
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&t, &mut tm);
        format!("{:02}:{:02}:{:02}", tm.tm_hour, tm.tm_min, tm.tm_sec)
    }
}

/// a bar in eighths, `w` cells wide, for a share 0..1
fn bar(share: f64, w: usize) -> String {
    let cells = (share.clamp(0.0, 1.0) * (w * 8) as f64).round() as usize;
    let mut s = "█".repeat(cells / 8);
    if cells % 8 > 0 {
        s.push(['▏', '▎', '▍', '▌', '▋', '▊', '▉'][cells % 8 - 1]);
    }
    format!("{s:<w$}")
}

fn num(v: f64) -> String {
    crate::py::commas(&Value::from(v.round() as i64))
}

fn block(title: &str) -> Block<'static> {
    Block::bordered()
        .border_type(BorderType::Rounded)
        .border_style(Style::new().fg(DIM))
        .title(Line::from(Span::styled(format!(" {title} "), Style::new().fg(CYAN).add_modifier(Modifier::BOLD))))
}

/// documents a minute between consecutive samples, for the sparkline; and the rate over the whole window
fn rates(h: &VecDeque<(f64, f64, f64, f64)>) -> (Vec<u64>, f64, f64) {
    let per: Vec<u64> = h
        .iter()
        .zip(h.iter().skip(1))
        .map(|(a, b)| if b.0 > a.0 { (((b.1 - a.1).max(0.0)) / (b.0 - a.0) * 60.0).round() as u64 } else { 0 })
        .collect();
    let (docs, mems) = match (h.front(), h.back()) {
        (Some(a), Some(b)) if b.0 - a.0 > 30.0 => ((b.1 - a.1) / (b.0 - a.0) * 60.0, (b.2 - a.2) / (b.0 - a.0) * 60.0),
        _ => (0.0, 0.0),
    };
    (per, docs, mems)
}

fn draw(f: &mut Frame, s: &Snap, bank: &str) {
    // fit the height: everything from 30 rows; below that the sparkline goes, then the feeder shrinks to 3 rows
    let n_workers = ["llm", "embed", "rerank"].iter().map(|k| s.health.as_ref().and_then(|h| h["workers"][k].as_array().map(|a| a.len())).unwrap_or(0)).sum::<usize>();
    let w_h = (n_workers as u16 + 3).max(5);
    let h = f.area().height;
    let (spark_h, feed_h) = if h >= 1 + 5 + 6 + w_h + 8 { (6, 8) } else if h >= 1 + 5 + w_h + 8 { (0, 8) } else if h >= 1 + 5 + w_h + 3 { (0, 3) } else { (0, 0) };
    let [title, top, spark, workers, feeder] = Layout::vertical([
        Constraint::Length(1),
        Constraint::Length(5),
        Constraint::Length(spark_h),
        Constraint::Fill(1),
        Constraint::Length(feed_h),
    ])
    .areas(f.area());

    let head = Line::from(vec![
        Span::styled(" ▓▒░ RELIC5·MEMORY ░▒▓ ", Style::new().fg(PINK).add_modifier(Modifier::BOLD)),
        Span::styled(format!(" bank {bank} · Hindsight + the dispatcher's workers · {} ", s.at), Style::new().fg(DIM)),
        Span::styled(" q quit · r refresh ", Style::new().fg(DIM)),
    ]);
    f.render_widget(Paragraph::new(head), title);

    // ── bank and queue cards ──
    let st = s.stats.clone().unwrap_or(Value::Null);
    let g = |k: &str| st[k].as_f64().unwrap_or(0.0);
    let by = |k: &str| st["nodes_by_fact_type"][k].as_f64().unwrap_or(0.0);
    let (per, docs_min, mems_min) = rates(&s.hist);
    let [c1, c2, c3] = Layout::horizontal([Constraint::Ratio(1, 3); 3]).areas(top);
    let big = |v: String, c: Color| Span::styled(v, Style::new().fg(c).add_modifier(Modifier::BOLD));
    f.render_widget(
        Paragraph::new(vec![
            Line::from(vec![big(num(g("total_documents")), CYAN), Span::styled(" documents", Style::new().fg(DIM))]),
            Line::from(vec![Span::styled(format!("{:.0} docs/min", docs_min), Style::new().fg(GREEN))]),
            Line::from(Span::styled(format!("last write {}", st["last_memory_write_at"].as_str().unwrap_or("-").get(11..19).unwrap_or("-")), Style::new().fg(DIM))),
        ])
        .block(block("documents")),
        c1,
    );
    f.render_widget(
        Paragraph::new(vec![
            Line::from(vec![big(num(g("total_nodes")), PINK), Span::styled(format!(" memories · {:.0}/min", mems_min), Style::new().fg(DIM))]),
            Line::from(vec![
                Span::styled(format!("world {} ", num(by("world"))), Style::new().fg(VIOLET)),
                Span::styled(format!("experience {} ", num(by("experience"))), Style::new().fg(PINK)),
                Span::styled(format!("observation {}", num(by("observation"))), Style::new().fg(CYAN)),
            ]),
            Line::from(Span::styled(format!("{} links", num(st["total_links"].as_f64().unwrap_or(0.0))), Style::new().fg(DIM))),
        ])
        .block(block("memories")),
        c2,
    );
    let eta = s.feeder.iter().rev().find_map(|l| {
        l.find("ETA ").map(|i| l[i..].to_string()).or_else(|| l.find("starts in").map(|i| l[i..].trim_end_matches(')').to_string()))
    });
    f.render_widget(
        Paragraph::new(vec![
            Line::from(vec![big(num(g("pending_operations")), AMBER), Span::styled(" open operations", Style::new().fg(DIM))]),
            Line::from(Span::styled(format!("consolidation waiting {}", num(g("pending_consolidation"))), Style::new().fg(DIM))),
            Line::from(Span::styled(eta.unwrap_or_else(|| "ETA: from the feeder".into()), Style::new().fg(GREEN))),
        ])
        .block(block("queue")),
        c3,
    );

    // ── documents a minute, 15 minutes ──
    let w = spark.width.saturating_sub(2) as usize;
    let show_spark = spark.height > 0;
    let data: Vec<u64> = per.iter().rev().take(w).rev().cloned().collect();
    if show_spark { f.render_widget(
        Sparkline::default()
            .block(block(&format!("documents a minute · last {} samples (2 s each) · max {}", data.len(), data.iter().max().unwrap_or(&0))))
            .data(&data)
            .style(Style::new().fg(CYAN)),
        spark,
    ); }

    // ── workers ──
    let h = s.health.clone().unwrap_or(Value::Null);
    let mut rows = Vec::new();
    for kind in ["llm", "embed", "rerank"] {
        for w in h["workers"][kind].as_array().cloned().unwrap_or_default() {
            let up = w["up"] == "ok";
            let util = w["util"].as_f64().unwrap_or(0.0);
            let slots = w["slots"].as_i64().unwrap_or(1);
            let work = if kind == "llm" {
                format!("{} tok", num(w["tokens_1m"].as_f64().unwrap_or(0.0)))
            } else {
                format!("{} texts", num(w["texts_1m"].as_f64().unwrap_or(0.0)))
            };
            let speed = if kind == "llm" {
                format!("{:.0} tok/s", w["tokens_1m"].as_f64().unwrap_or(0.0) / 60.0)
            } else {
                format!("{:.1} texts/s", w["texts_1m"].as_f64().unwrap_or(0.0) / 60.0)
            };
            let total = if kind == "llm" { num(w["tokens"].as_f64().unwrap_or(0.0)) + " tok" } else { num(w["texts"].as_f64().unwrap_or(0.0)) + " texts" };
            let color = match kind { "llm" => PINK, "embed" => CYAN, _ => VIOLET };
            let errs = w["errors"].as_i64().unwrap_or(0);
            rows.push(vec![
                Cell::from(Span::styled(kind, Style::new().fg(color))),
                Cell::from(crate::py::s(&w["name"])),
                Cell::from(Span::styled(if up { "ok" } else { "DOWN" }, Style::new().fg(if up { GREEN } else { RED }))),
                Cell::from(format!("{}/{}", w["inflight"].as_i64().unwrap_or(0), slots)),
                Cell::from(Line::from(vec![
                    Span::styled(bar(util, 12), Style::new().fg(if util > 0.9 { AMBER } else { color })),
                    Span::styled(format!(" {:>3.0}%", util * 100.0), Style::new().fg(DIM)),
                ])),
                Cell::from(crate::py::s(&w["requests_1m"])),
                Cell::from(work),
                Cell::from(Span::styled(speed, Style::new().fg(GREEN))),
                Cell::from(num(w["requests"].as_f64().unwrap_or(0.0))),
                Cell::from(total),
                Cell::from(Span::styled(errs.to_string(), Style::new().fg(if errs > 0 { RED } else { DIM }))),
                Cell::from(format!("{:.1}s", w["avg_s"].as_f64().unwrap_or(0.0))),
                Cell::from(Span::styled(
                    if w["model"].is_null() { crate::py::s(&w["url"]) } else { crate::py::s(&w["model"]) },
                    Style::new().fg(DIM),
                )),
            ]);
        }
    }
    // wide: every column; narrow (< 110 cells): kind, name, up, busy, utilization, work a minute, errors
    let wide = workers.width >= 110;
    // narrow keeps the model and the speed (Nat: "each worker should show model and tok/s")
    let keep: Vec<usize> = if wide { (0..13).collect() } else { vec![0, 1, 3, 4, 7, 10, 12] };
    let names = ["kind", "name", "up", "busy", "utilization (1 min)", "calls/m", "work/m", "speed", "calls", "work", "err", "avg", "model"];
    let widths = [
        Constraint::Length(6), Constraint::Length(7), Constraint::Length(4), Constraint::Length(6), Constraint::Length(18),
        Constraint::Length(7), Constraint::Length(12), Constraint::Length(12), Constraint::Length(8), Constraint::Length(16),
        Constraint::Length(4), Constraint::Length(6), Constraint::Min(10),
    ];
    let header = Row::new(keep.iter().map(|&i| names[i]).collect::<Vec<_>>()).style(Style::new().fg(DIM).add_modifier(Modifier::BOLD));
    let rows: Vec<Row> = rows
        .into_iter()
        .map(|cells: Vec<Cell>| Row::new(keep.iter().map(|&i| cells[i].clone()).collect::<Vec<_>>()))
        .collect();
    f.render_widget(
        Table::new(rows, keep.iter().map(|&i| widths[i]).collect::<Vec<_>>())
            .header(header)
            .block(block("workers · the dispatcher (embed/embed-router.py)")),
        workers,
    );

    // ── feeder log tail, or the error ──
    let lines: Vec<Line> = match &s.err {
        Some(e) => vec![Line::from(Span::styled(e.clone(), Style::new().fg(RED)))],
        None => {
            let fit = feeder.height.saturating_sub(2) as usize;
            s.feeder.iter().rev().take(fit).rev().map(|l| Line::from(Span::styled(l.clone(), Style::new().fg(DIM)))).collect()
        }
    };
    f.render_widget(Paragraph::new(lines).block(block("feeder · ~/Library/Logs/hindsight-import.log")), feeder);
}

fn run(term: &mut DefaultTerminal, snap: Arc<Mutex<Snap>>, bank: &str, kick: std::sync::mpsc::Sender<()>) -> std::io::Result<()> {
    loop {
        let s = snap.lock().unwrap().clone();
        term.draw(|f| draw(f, &s, bank))?;
        if !event::poll(Duration::from_millis(500))? {
            continue;
        }
        if let Event::Key(k) = event::read()? {
            if k.kind == KeyEventKind::Press {
                match k.code {
                    KeyCode::Char('q') | KeyCode::Esc => return Ok(()),
                    KeyCode::Char('r') => {
                        let _ = kick.send(());
                    }
                    _ => {}
                }
            }
        }
    }
}

pub fn top(bank: &str) -> i32 {
    let snap = Arc::new(Mutex::new(Snap::default()));
    let t0 = Instant::now();
    let (kick, rx) = std::sync::mpsc::channel::<()>();
    {
        let snap = snap.clone();
        let bank = bank.to_string();
        std::thread::spawn(move || loop {
            fetch(&snap, &bank, t0);
            let _ = rx.recv_timeout(Duration::from_secs(2));
        });
    }
    match ratatui::run(|term| run(term, snap, bank, kick)) {
        Ok(()) => 0,
        Err(e) => {
            eprintln!("relic5 memory top: {e}");
            1
        }
    }
}
