//! The hub-client commands, line for line from src/relic5/cli.py (search, show, conversation, readings, recap,
//! handoff, pending, tail, status). Same flags, same requests, same output.
use crate::hub::{self, Fail};
use crate::py::{self, commas, dumps, head, ljust, or, rstrip, s, squash};
use serde_json::Value;

/// The arguments after the command, consumed the way cli.py's _opt does
pub struct Args(pub Vec<String>);

impl Args {
    /// _opt(args, name): the value after the first `name`, both removed
    pub fn opt(&mut self, name: &str) -> Result<Option<String>, Fail> {
        match self.0.iter().position(|a| a == name) {
            Some(i) if i + 1 < self.0.len() => {
                let v = self.0[i + 1].clone();
                self.0.drain(i..i + 2);
                Ok(Some(v))
            }
            Some(_) => Err(Fail::Other(format!("relic5: {name} needs a value"), 2)),
            None => Ok(None),
        }
    }
    pub fn opt_or(&mut self, name: &str, default: &str) -> Result<String, Fail> {
        Ok(self.opt(name)?.unwrap_or_else(|| default.to_string()))
    }
    pub fn has(&self, flag: &str) -> bool {
        self.0.iter().any(|a| a == flag)
    }
}

type P = Vec<(String, String)>;
fn kv(k: &str, v: impl Into<String>) -> (String, String) {
    (k.to_string(), v.into())
}
fn set(p: &mut P, k: &str, v: String) {
    match p.iter_mut().find(|(x, _)| x == k) {
        Some(e) => e.1 = v,
        None => p.push(kv(k, v)),
    }
}
fn missing(k: &str) -> Fail {
    Fail::Other(format!("relic5: the hub's answer has no '{k}'"), 1)
}
fn g<'a>(v: &'a Value, k: &str) -> Result<&'a Value, Fail> {
    v.get(k).ok_or_else(|| missing(k))
}
fn gs(v: &Value, k: &str) -> Result<String, Fail> {
    Ok(s(g(v, k)?))
}
fn arr(v: Option<&Value>) -> Vec<Value> {
    v.and_then(Value::as_array).cloned().unwrap_or_default()
}
fn text(v: Option<&Value>) -> String {
    or(v, "")
}
/// x['ts_th'][:16].replace('T', ' ')
fn when(x: &Value) -> Result<String, Fail> {
    Ok(head(&gs(x, "ts_th")?, 16).replace('T', " "))
}

fn flags(a: &mut Args, names: &[&str]) -> Result<P, Fail> {
    let mut p = P::new();
    for k in names {
        if let Some(o) = a.opt(&format!("--{k}"))? {
            if !o.is_empty() {
                p.push(kv(k, o));
            }
        }
    }
    Ok(p)
}

/// _line(h): one search hit on one line
fn line(h: &Value, width: usize) -> String {
    let src = if py::truthy(h.get("text_snippet")) { h.get("text_snippet") } else { h.get("text") };
    let txt = head(&squash(&text(src)), width);
    let who = arr(h.get("machines")).iter().map(s).collect::<Vec<_>>().join(",");
    format!(
        "{}  {} {} {}  {txt}",
        head(&text(h.get("ts")), 16),
        ljust(&who, 7),
        ljust(&text(h.get("role")), 9),
        head(&text(h.get("session_uuid")), 8)
    )
}

pub fn search(mut a: Args, json: bool) -> Result<(), Fail> {
    let params = flags(&mut a, &["with", "limit", "role", "since", "until", "repo", "session", "horizon"])?;
    let mut p = vec![kv("q", a.0.join(" "))];
    p.extend(params);
    let r = hub::call("/api/search", &p)?;
    if json {
        println!("{}", dumps(&r));
        return Ok(());
    }
    let hits = arr(r.get("hits"));
    for h in &hits {
        println!("{}", line(h, 110));
    }
    println!("{} hits{}", hits.len(), if py::truthy(r.get("next_cursor")) { " (more: next_cursor)" } else { "" });
    if py::truthy(r.get("note")) {
        println!("note: {}", s(&r["note"]));
    }
    Ok(())
}

pub fn show(mut a: Args, json: bool) -> Result<(), Fail> {
    let id = a.0[0].clone();
    let before = a.opt_or("--before", "2")?;
    let after = a.opt_or("--after", "2")?;
    let r = hub::call("/api/show", &[kv("id", id), kv("before", before), kv("after", after)])?;
    if json {
        println!("{}", dumps(&r));
        return Ok(());
    }
    let t = g(&r, "target")?;
    let near = |x: &Value| -> Result<String, Fail> {
        Ok(format!("   {} {}: {}", when(x)?, gs(x, "role")?, head(&squash(&text(x.get("text"))), 200)))
    };
    for x in arr(r.get("before")) {
        println!("{}", near(&x)?);
    }
    println!("── {} {}  {}  {}:{}", when(t)?, gs(t, "role")?, text(t.get("sid")), text(t.get("src_path")), text(t.get("src_line")));
    let parts = if py::truthy(r.get("parts")) { arr(r.get("parts")) } else { vec![t.clone()] };
    let body: String = parts.iter().map(|x| text(x.get("text"))).collect();
    println!("{}\n", rstrip(&body));
    for x in arr(r.get("after")) {
        println!("{}", near(&x)?);
    }
    Ok(())
}

pub fn conversation(mut a: Args, json: bool) -> Result<(), Fail> {
    let id = a.0[0].clone();
    let offset = a.opt_or("--offset", "0")?;
    let limit = a.opt_or("--limit", "0")?;
    let limit = if limit.is_empty() { "0".to_string() } else { limit };
    let mut p: P = vec![kv("id", id), kv("offset", offset.clone()), kv("limit", limit.clone())];
    if a.has("--tools") {
        p.push(kv("tools", "1"));
    }
    if let Some(who) = a.opt("--role")? {
        if !who.is_empty() {
            p.push(kv("role", who));
        }
    }
    let mut off: i64 = offset.parse().map_err(|_| Fail::Other("relic5: --offset must be a number".into(), 2))?;
    let mut total: Option<Value> = None;
    loop {
        let mut q = p.clone();
        set(&mut q, "offset", off.to_string());
        set(&mut q, "limit", if limit != "0" { limit.clone() } else { "1000".into() });
        let r = hub::call("/api/conversation", &q)?;
        if json {
            println!("{}", dumps(&r));
            break;
        }
        if total.is_none() {
            total = Some(g(&r, "total")?.clone());
            println!(
                "{}  {}\n{}  {} .. {}  {} turns\n",
                gs(&r, "uuid")?,
                text(r.get("name")),
                text(r.get("repo")),
                gs(&r, "startedAt")?,
                gs(&r, "endedAt")?,
                s(total.as_ref().unwrap())
            );
        }
        for t in arr(r.get("turns")) {
            if gs(&t, "role")? == "tool" {
                println!("   {} {}: {}", py::mid(&gs(&t, "ts_th")?, 11, 16), gs(&t, "name")?, gs(&t, "text")?);
            } else {
                println!("── {} {}\n{}\n", when(&t)?, gs(&t, "role")?, rstrip(&text(t.get("text"))));
            }
        }
        let next = g(&r, "next_offset")?;
        if limit != "0" || next.is_null() {
            break;
        }
        off = next.as_i64().ok_or_else(|| missing("next_offset"))?;
    }
    Ok(())
}

pub fn readings(mut a: Args, json: bool) -> Result<(), Fail> {
    let mut p = flags(&mut a, &["since", "until", "grain", "model", "q", "limit", "offset"])?;
    if !p.iter().any(|(k, _)| k == "limit") {
        p.push(kv("limit", "20"));
    }
    let r = hub::call("/api/readings", &p)?;
    if json {
        println!("{}", dumps(&r));
        return Ok(());
    }
    let models = g(&r, "models")?.as_object().cloned().unwrap_or_default();
    let m = models.iter().map(|(k, n)| format!("{k} {}", commas(n))).collect::<Vec<_>>().join(", ");
    let note = if py::truthy(r.get("note")) { format!("\n{}", s(&r["note"])) } else { String::new() };
    println!("{} readings · {m}{note}", commas(g(&r, "total")?));
    for x in arr(r.get("rows")) {
        let deep = if py::truthy(x.get("deep")) { " deep" } else { "" };
        println!("\n── {} {}  {}{deep}  {}", gs(&x, "start")?, gs(&x, "grain")?, gs(&x, "model")?, text(x.get("type")));
        println!("focus: {}", x.get("focus").map(s).unwrap_or_else(|| "None".into()));
        for w in arr(x.get("work")) {
            println!("  - {}", s(&w));
        }
        for k in ["distraction", "friction", "lesson"] {
            if py::truthy(x.get(k)) && x[k] != Value::String("none".into()) {
                println!("{k}: {}", s(&x[k]));
            }
        }
        if py::truthy(x.get("th")) {
            println!("th: {}", s(&x["th"]));
        }
    }
    Ok(())
}

pub fn recap(mut a: Args, json: bool) -> Result<(), Fail> {
    let id = a.0[0].clone();
    let limit = a.opt_or("--limit", "20")?;
    let r = hub::call("/api/recap", &[kv("id", id), kv("limit", limit)])?;
    if json {
        println!("{}", dumps(&r));
        return Ok(());
    }
    let turns = g(&r, "turns")?;
    println!(
        "{}  {}\n{}  {} .. {}  {} turns asked, {} shown",
        gs(&r, "uuid")?,
        text(r.get("name")),
        text(r.get("repo")),
        gs(&r, "startedAt")?,
        gs(&r, "endedAt")?,
        gs(turns, "user")?,
        gs(turns, "shown")?
    );
    for t in arr(r.get("asked")) {
        println!("  {}  {}", head(&gs(&t, "ts")?, 16), head(&squash(&gs(&t, "text")?), 160));
    }
    let tools = g(&r, "tools")?.as_object().cloned().unwrap_or_default();
    println!("tools: {}", tools.iter().take(12).map(|(k, v)| format!("{k} {}", s(v))).collect::<Vec<_>>().join(", "));
    let files: Vec<String> = match g(&r, "files_edited")? {
        Value::Object(m) => m.keys().cloned().collect(),
        Value::Array(v) => v.iter().map(s).collect(),
        _ => vec![],
    };
    let f = files.into_iter().take(12).collect::<Vec<_>>().join(", ");
    println!("files edited: {}", if f.is_empty() { "none".to_string() } else { f });
    let ended = g(&r, "ended")?;
    if py::truthy(Some(ended)) {
        println!("ended {}: {}", head(&gs(ended, "ts")?, 16), head(&squash(&gs(ended, "text")?), 300));
    }
    if py::truthy(r.get("more")) {
        println!("{}", s(&r["more"]));
    }
    Ok(())
}

pub fn handoff(a: Args) -> Result<(), Fail> {
    let r = hub::call("/api/handoff", &[kv("id", a.0[0].clone()), kv("user_only", if a.has("--role") { "1" } else { "0" })])?;
    println!("{}", gs(&r, "text")?);
    Ok(())
}

pub fn pending() -> Result<(), Fail> {
    let st = hub::call("/api/status", &[])?;
    let empty = Value::Object(Default::default());
    let f = st.get("freshness").unwrap_or(&empty);
    let marks = g(&st, "watermarks")?;
    let v = g(marks, "vectors")?;
    let fts_age = f.get("fts").filter(|x| py::truthy(Some(x))).and_then(|x| x.get("age_s")).map(s).unwrap_or_else(|| "None".into());
    let stale: Vec<String> = arr(st.get("warnings"))
        .iter()
        .map(s)
        .filter(|w| w.starts_with("month "))
        .filter_map(|w| w.split(py::is_space).filter(|x| !x.is_empty()).nth(1).map(|x| x.trim_end_matches(':').to_string()))
        .collect();
    println!(
        "BM25: index {} ({fts_age} s ago); stale months: {}",
        gs(g(marks, "fts")?, "at")?,
        if stale.is_empty() { "none".to_string() } else { stale.join(", ") }
    );
    if let Some(models) = v.get("models").filter(|x| py::truthy(Some(x))).and_then(Value::as_object) {
        for (model, per) in models {
            let mut per: Vec<(String, Value)> = per.as_object().cloned().unwrap_or_default().into_iter().collect();
            per.sort_by(|x, y| x.0.cmp(&y.0));
            let items = per
                .iter()
                .map(|(m, x)| Ok(format!("{m} {} pending (embedded to {})", commas(g(x, "pending")?), gs(x, "at")?)))
                .collect::<Result<Vec<_>, Fail>>()?;
            println!("vectors {model}: {}", items.join(", "));
        }
    }
    let mut machines: Vec<(String, Value)> = f.get("machines").and_then(Value::as_object).cloned().unwrap_or_default().into_iter().collect();
    machines.sort_by(|x, y| x.0.cmp(&y.0));
    for (m, x) in machines {
        println!("push {m}: newest row {}, pushed {}, {} s behind now", gs(&x, "newest_ts")?, gs(&x, "pushed_at")?, gs(&x, "lag_s")?);
    }
    Ok(())
}

pub fn tail(mut a: Args) -> Result<(), Fail> {
    let mut params = flags(&mut a, &["session", "machine", "n"])?;
    let full = a.has("--full");
    if full {
        params.push(kv("full", "1"));
    }
    let follow = a.has("-f");
    let mut seen = std::collections::HashSet::<String>::new();
    loop {
        let r = hub::call("/api/tail", &params)?;
        let mut rows = arr(r.get("rows"));
        rows.reverse();
        for x in rows {
            // one message is often written twice (a queued prompt, a re-sent assistant block): show it once
            let said_text = squash(&text(x.get("text")));
            let said = format!("said\u{0}{}\u{0}{}\u{0}{said_text}", s(x.get("sid").unwrap_or(&Value::Null)), gs(&x, "role")?);
            let key = format!("key\u{0}{}", s(g(&x, "msgkey")?));
            if seen.contains(&key) || seen.contains(&said) {
                continue;
            }
            seen.insert(key);
            seen.insert(said);
            let who = arr(x.get("machines")).iter().map(s).collect::<Vec<_>>().join(",");
            let name = if py::truthy(x.get("session_name")) { s(&x["session_name"]) } else { text(x.get("sid")) };
            let head_ = format!("{} {} {} {}", head(&gs(&x, "ts_th")?, 16), ljust(&who, 9), ljust(&gs(&x, "role")?, 9), ljust(&head(&name, 24), 24));
            if full {
                println!("── {}  {}\n{}\n", rstrip(&head_), head(&text(x.get("sid")), 8), rstrip(&text(x.get("text"))));
            } else {
                println!("{head_} {}", head(&said_text, 110));
            }
        }
        if !follow {
            break;
        }
        std::thread::sleep(std::time::Duration::from_secs(30));
    }
    Ok(())
}

pub fn status() -> Result<(), Fail> {
    println!("{}", dumps(&hub::call("/api/status", &[])?));
    Ok(())
}

