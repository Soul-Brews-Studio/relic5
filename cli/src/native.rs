//! The Rust-native embedded engine (feature "native", binary relic5-rs, #311): `search` read straight from the
//! published BM25 index with lancedb, the same lance (13.0.0) the Python core runs, so no Python is needed for the
//! command people run most. A line-for-line port of src/relic5/search.py `search()` (keyword, no cursor):
//! widening 7d -> 15d -> 1m -> 3m -> archive, phrase hits first, the fold, the best older hits after the window,
//! sort newest, the page with repo / session name / snippet / matched tokens, freshness.
//!
//! Anything outside that envelope returns None and the caller hands the route to the Python core: a cursor, repo /
//! tier / cwd / branch / title / via / chat / from_user / home, semantic, discord, a vault session on the page, an
//! FTS error (the core answers by substring), a window it cannot read (the core prints the error). So the answer is
//! the core's own wherever this port has not been proven equal (tests/test_rust_cli.py compares the two engines).
use arrow_array::{Array, ListArray, RecordBatch, StringArray};
use futures::TryStreamExt;
use lance_tokenizer::TokenStream;
use lancedb::query::{ExecutableQuery, QueryBase, Select};
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};

type Row = HashMap<String, Value>;
const WIDEN: [&str; 5] = ["7d", "15d", "1m", "3m", "archive"];
const CAP: usize = 8192;
const COLS: [&str; 15] = ["uid", "msgkey", "chunk", "key", "month", "sid", "ts", "ts_th", "role", "engine", "cat", "layer", "machines", "text", "title"];
const HOME_COLS: [&str; 3] = ["home", "homes", "agent"];
const KNOWN: [&str; 7] = ["q", "limit", "since", "until", "horizon", "role", "session"];

fn horizon_days(h: &str) -> Option<Option<i64>> {
    match h {
        "7d" => Some(Some(7)),
        "15d" => Some(Some(15)),
        "1m" => Some(Some(30)),
        "3m" => Some(Some(90)),
        "archive" => Some(None),
        _ => None,
    }
}

// ---- time: UTC millis <-> the parts' ts text (YYYY-MM-DDTHH:MM:SS.mmmZ), as window.py iso() ----

fn now_ms() -> Option<i64> {
    match std::env::var("RELIC5_NOW") {
        Ok(v) if !v.is_empty() => parse_iso(&v),
        _ => Some(std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).ok()?.as_millis() as i64),
    }
}

fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

fn civil_from_days(z: i64) -> (i64, i64, i64) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}

fn iso(ms: i64) -> String {
    let (days, rem) = (ms.div_euclid(86_400_000), ms.rem_euclid(86_400_000));
    let (y, m, d) = civil_from_days(days);
    format!("{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}.{:03}Z", rem / 3_600_000, rem / 60_000 % 60, rem / 1000 % 60, rem % 1000)
}

fn digits(s: &str) -> Option<i64> {
    (!s.is_empty() && s.bytes().all(|b| b.is_ascii_digit())).then(|| s.parse().ok()).flatten()
}

/// The plain shapes only: YYYY-MM-DDTHH:MM[:SS[.fff]] with Z or ±HH:MM. Anything else: None (the core decides).
fn parse_iso(v: &str) -> Option<i64> {
    let b = v.as_bytes();
    if b.len() < 16 || b[4] != b'-' || b[7] != b'-' || b[10] != b'T' || b[13] != b':' {
        return None;
    }
    let (y, mo, d, h, mi) = (digits(&v[0..4])?, digits(&v[5..7])?, digits(&v[8..10])?, digits(&v[11..13])?, digits(&v[14..16])?);
    let mut rest = &v[16..];
    let mut sec = 0i64;
    let mut ms = 0i64;
    if let Some(r) = rest.strip_prefix(':') {
        sec = digits(r.get(0..2)?)?;
        rest = &r[2..];
        if let Some(r) = rest.strip_prefix('.') {
            let n = r.bytes().take_while(u8::is_ascii_digit).count();
            if n == 0 {
                return None;
            }
            let frac = &r[..n];
            ms = digits(&format!("{:0<3}", &frac[..n.min(3)]))?;
            rest = &r[n..];
        }
    }
    let off = match rest {
        "Z" | "+00:00" => 0,
        "" => 0,
        r if r.len() == 6 && (r.starts_with('+') || r.starts_with('-')) && &r[3..4] == ":" => {
            let o = digits(&r[1..3])? * 60 + digits(&r[4..6])?;
            if r.starts_with('+') { o } else { -o }
        }
        _ => return None,
    };
    if !(1..=12).contains(&mo) || !(1..=31).contains(&d) || h > 23 || mi > 59 || sec > 59 {
        return None;
    }
    Some(days_from_civil(y, mo, d) * 86_400_000 + (h * 3600 + mi * 60 + sec - off * 60) * 1000 + ms)
}

/// window.py bound(): Nd/Nh/Nm/Nw/Nmo, a UTC day, an ISO time. Err(()) = let the core read it (and maybe refuse it).
fn bound(v: Option<&str>, end: bool, now: i64) -> Result<Option<String>, ()> {
    let Some(v) = v.filter(|v| !v.is_empty()) else { return Ok(None) };
    let n = v.bytes().take_while(u8::is_ascii_digit).count();
    if n > 0 && n < v.len() {
        let (num, unit) = (digits(&v[..n]).ok_or(())?, &v[n..]);
        let ms = match unit {
            "mo" => num * 30 * 86_400_000,
            "d" => num * 86_400_000,
            "h" => num * 3_600_000,
            "m" => num * 60_000,
            "w" => num * 7 * 86_400_000,
            _ => -1,
        };
        if ms >= 0 {
            return Ok(Some(iso(now - ms)));
        }
    }
    if v.len() == 10 && v.as_bytes()[4] == b'-' && v.as_bytes()[7] == b'-' {
        let (y, m, d) = (digits(&v[0..4]).ok_or(())?, digits(&v[5..7]).ok_or(())?, digits(&v[8..10]).ok_or(())?);
        if !(1..=12).contains(&m) || d < 1 || civil_from_days(days_from_civil(y, m, d)) != (y, m, d) {
            return Err(());
        }
        let start = days_from_civil(y, m, d) * 86_400_000;
        return Ok(Some(iso(if end { start + 86_400_000 - 1 } else { start })));
    }
    parse_iso(v).map(|ms| Some(iso(ms))).ok_or(())
}

// ---- Python's text rules ----

/// str.split() then " ".join
fn squash(s: &str) -> String {
    crate::py::squash(s)
}

/// json.dumps(x) with Python's defaults: ensure_ascii, ", " and ": " separators
fn py_json(v: &Value) -> String {
    match v {
        Value::Null => "null".into(),
        Value::Bool(b) => b.to_string(),
        Value::Number(n) => n.to_string(),
        Value::String(s) => {
            let mut o = String::from("\"");
            for c in s.chars() {
                match c {
                    '"' => o.push_str("\\\""),
                    '\\' => o.push_str("\\\\"),
                    '\n' => o.push_str("\\n"),
                    '\r' => o.push_str("\\r"),
                    '\t' => o.push_str("\\t"),
                    '\u{8}' => o.push_str("\\b"),
                    '\u{c}' => o.push_str("\\f"),
                    c if (c as u32) < 0x20 || (c as u32) > 0x7e => {
                        let mut buf = [0u16; 2];
                        for u in c.encode_utf16(&mut buf) {
                            o.push_str(&format!("\\u{:04x}", u));
                        }
                    }
                    c => o.push(c),
                }
            }
            o.push('"');
            o
        }
        Value::Array(a) => format!("[{}]", a.iter().map(py_json).collect::<Vec<_>>().join(", ")),
        Value::Object(m) => format!("{{{}}}", m.iter().map(|(k, v)| format!("{}: {}", py_json(&json!(k)), py_json(v))).collect::<Vec<_>>().join(", ")),
    }
}

fn q_(v: &str) -> String {
    format!("'{}'", v.replace('\'', "''"))
}

/// search.py snippet(): the window of text around the first query word found, whitespace collapsed
fn snippet(text: &str, words: &[String], width: usize) -> String {
    let chars: Vec<char> = text.chars().collect();
    let low: Vec<char> = text.chars().flat_map(char::to_lowercase).collect();
    let find = |w: &str| -> Option<usize> {
        let wl: Vec<char> = w.chars().flat_map(char::to_lowercase).collect();
        if wl.is_empty() {
            return Some(0);
        }
        low.windows(wl.len()).position(|x| x == wl.as_slice())
    };
    let at = words.iter().filter_map(|w| find(w)).min().unwrap_or(0);
    let s = at.saturating_sub(width / 3);
    let end = (s + width).min(chars.len());
    let body: String = chars.get(s.min(chars.len())..end).map(|c| c.iter().collect()).unwrap_or_default();
    format!("{}{}{}", if s > 0 { "…" } else { "" }, squash(&body), if s + width < chars.len() { "…" } else { "" })
}

// ---- the index ----

/// The query Python's lancedb builds from a string: wrapped in double quotes it is a phrase (the words in order,
/// slop 0), anything else a match of any term
fn fts_query(q: &str) -> lancedb::index::scalar::FullTextSearchQuery {
    use lance_index::scalar::inverted::query::PhraseQuery;
    use lancedb::index::scalar::FullTextSearchQuery;
    if q.len() >= 2 && q.starts_with('"') && q.ends_with('"') {
        FullTextSearchQuery::new_query(PhraseQuery::new(q[1..q.len() - 1].to_string()).into())
    } else {
        FullTextSearchQuery::new(q.to_string())
    }
}

struct Index {
    rt: tokio::runtime::Runtime,
    tables: HashMap<String, lancedb::Table>,
    schemas: HashMap<String, Vec<String>>,
}

fn s(v: &Value) -> &str {
    v.as_str().unwrap_or("")
}

impl Index {
    fn open(root: &str) -> Option<Index> {
        let sd = format!("{root}/index/_search");
        let cur: Value = serde_json::from_str(&std::fs::read_to_string(format!("{sd}/current.json")).ok()?).ok()?;
        let rt = tokio::runtime::Builder::new_multi_thread().worker_threads(4).enable_all().build().ok()?;
        let mut tables = HashMap::new();
        let mut schemas = HashMap::new();
        for (name, rel) in cur.as_object()? {
            let Some((gen_, fname)) = rel.as_str().and_then(|r| r.split_once('/')) else { continue };
            let opened = rt.block_on(async {
                let db = lancedb::connect(&format!("{sd}/{gen_}")).execute().await.ok()?;
                let t = db.open_table(fname.trim_end_matches(".lance")).execute().await.ok()?;
                let sc = t.schema().await.ok()?;
                Some((t, sc.fields().iter().map(|f| f.name().clone()).collect::<Vec<_>>()))
            });
            if let Some((t, cols)) = opened {   // a table current.json names but the folder lacks: serve the rest
                tables.insert(name.clone(), t);
                schemas.insert(name.clone(), cols);
            }
        }
        (!tables.is_empty()).then_some(Index { rt, tables, schemas })
    }

    /// fts.py _fts(): one layer's open + history tables, best first
    fn fts(&self, layer: &str, q: &str, filter: Option<&str>, limit: usize) -> Result<Vec<Row>, String> {
        let mut out: Vec<Row> = Vec::new();
        for part in ["open", "history"] {
            let name = format!("{layer}_{part}");
            let Some(t) = self.tables.get(&name) else { continue };
            let have = &self.schemas[&name];
            let cols: Vec<String> = COLS.iter().chain(HOME_COLS.iter()).filter(|c| have.iter().any(|h| h == *c)).map(|c| c.to_string()).collect();
            let batches: Vec<RecordBatch> = self.rt.block_on(async {
                let mut qb = t.query().full_text_search(fts_query(q)).limit(limit);
                if let Some(w) = filter {
                    qb = qb.only_if(w);
                }
                qb.select(Select::columns(&cols)).execute().await.map_err(|e| e.to_string())?.try_collect().await.map_err(|e| e.to_string())
            })?;
            for b in &batches {
                out.extend(rows_of(b)?);
            }
        }
        out.sort_by(|a, b| {
            let (sa, sb) = (a["_score"].as_f64().unwrap_or(0.0), b["_score"].as_f64().unwrap_or(0.0));
            sb.partial_cmp(&sa).unwrap_or(std::cmp::Ordering::Equal).then_with(|| s(&a["ts"]).cmp(s(&b["ts"])))
        });
        out.truncate(limit);
        Ok(out)
    }

    /// fts.py _query_untimed(): two or more words also run as an exact phrase, whose hits come first
    fn query(&self, layer: &str, q: &str, filter: Option<&str>, limit: usize) -> Result<Vec<Row>, String> {
        let q = q.trim();
        if (q.starts_with('"') && q.ends_with('"') && q.chars().count() > 2) || q.split_whitespace().count() < 2 {
            return self.fts(layer, q, filter, limit);
        }
        let phrase = self.fts(layer, &format!("\"{}\"", q.replace('"', " ")), filter, limit).unwrap_or_default();
        let seen: HashSet<String> = phrase.iter().map(|r| s(&r["uid"]).to_string()).collect();
        let mut out = phrase;
        out.extend(self.fts(layer, q, filter, limit)?.into_iter().filter(|r| !seen.contains(s(&r["uid"]))));
        out.truncate(limit);
        Ok(out)
    }
}

/// One record batch -> rows of JSON values (strings, ints, the machines list, _score as f64)
fn rows_of(b: &RecordBatch) -> Result<Vec<Row>, String> {
    let n = b.num_rows();
    let mut rows: Vec<Row> = (0..n).map(|_| Row::new()).collect();
    for (i, f) in b.schema().fields().iter().enumerate() {
        let col = b.column(i);
        let name = f.name().as_str();
        let vals: Vec<Value> = if name == "_score" {
            let c = arrow_cast::cast(col, &arrow_schema::DataType::Float64).map_err(|e| e.to_string())?;
            let a = c.as_any().downcast_ref::<arrow_array::Float64Array>().ok_or("score")?;
            (0..n).map(|j| if a.is_null(j) { Value::Null } else { json!(a.value(j)) }).collect()
        } else if name == "chunk" {
            let c = arrow_cast::cast(col, &arrow_schema::DataType::Int64).map_err(|e| e.to_string())?;
            let a = c.as_any().downcast_ref::<arrow_array::Int64Array>().ok_or("chunk")?;
            (0..n).map(|j| if a.is_null(j) { Value::Null } else { json!(a.value(j)) }).collect()
        } else if let Some(l) = col.as_any().downcast_ref::<ListArray>() {
            (0..n)
                .map(|j| {
                    if l.is_null(j) {
                        return Ok(Value::Null);
                    }
                    let c = arrow_cast::cast(&l.value(j), &arrow_schema::DataType::Utf8).map_err(|e| e.to_string())?;
                    let a = c.as_any().downcast_ref::<StringArray>().ok_or("list")?;
                    Ok(Value::Array((0..a.len()).map(|k| if a.is_null(k) { Value::Null } else { json!(a.value(k)) }).collect()))
                })
                .collect::<Result<_, String>>()?
        } else {
            let c = arrow_cast::cast(col, &arrow_schema::DataType::Utf8).map_err(|e| e.to_string())?;
            let a = c.as_any().downcast_ref::<StringArray>().ok_or("str")?;
            (0..n).map(|j| if a.is_null(j) { Value::Null } else { json!(a.value(j)) }).collect()
        };
        for (r, v) in rows.iter_mut().zip(vals) {
            r.insert(name.to_string(), v);
        }
    }
    Ok(rows)
}

fn fold_key(r: &Row) -> (String, String, String) {
    (s(&r["ts"]).to_string() + if r["ts"].is_null() { "\u{0}" } else { "" }, s(&r["role"]).to_string(), squash(s(r.get("text").unwrap_or(&Value::Null))))
}

/// search.py fold(): drop a row whose (ts, role, text) or chunk key was seen; the first one stays
fn fold(rows: Vec<Row>, seen: &mut HashSet<(String, String, String)>) -> Vec<Row> {
    let mut out = Vec::new();
    for r in rows {
        let k = fold_key(&r);
        let kk = ("\u{1}key".to_string(), s(&r["key"]).to_string(), String::new());
        if seen.contains(&k) || seen.contains(&kk) {
            continue;
        }
        seen.insert(k);
        seen.insert(kk);
        out.push(r);
    }
    out
}

/// search.py run(): folded hits of every layer, prose first; fetches more while the fold drops rows
fn run(ix: &Index, q: &str, layers: &[String], filter: Option<&str>, want: usize) -> Result<Vec<Row>, String> {
    let mut seen = HashSet::new();
    let mut out: Vec<Row> = Vec::new();
    for layer in layers {
        let mut k = (want as f64 * 1.5) as usize + 8;
        let rows = loop {
            let rows = ix.query(layer, q, filter, k)?;
            let got = fold(rows.clone(), &mut seen.clone()).len();
            if got >= want.saturating_sub(out.len()) || rows.len() < k || k >= CAP {
                break rows;
            }
            k = (k * 4).min(CAP);
        };
        out.extend(fold(rows, &mut seen));
        if out.len() >= want {
            break;
        }
    }
    Ok(out)
}

// ---- side tables: session repos (meta), names, freshness ----

fn read_parquet(path: &str, want: &[&str]) -> Vec<HashMap<String, Value>> {
    use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
    let Ok(f) = std::fs::File::open(path) else { return vec![] };
    let Ok(b) = ParquetRecordBatchReaderBuilder::try_new(f) else { return vec![] };
    let schema = b.schema().clone();
    let idx: Vec<usize> = want.iter().filter_map(|w| schema.fields().iter().position(|f| f.name() == w)).collect();
    let mask = parquet::arrow::ProjectionMask::roots(b.parquet_schema(), idx);
    let Ok(reader) = b.with_projection(mask).build() else { return vec![] };
    let mut out = Vec::new();
    for batch in reader.flatten() {
        if let Ok(rows) = rows_of(&batch) {
            out.extend(rows);
        }
    }
    out
}

/// query.py _repos() over Relic5._meta(): one row per sid (main over subagent, a real machine over an import, the
/// first machine by name, the latest last_ts, the most rows, then the file name), its proj
fn repos(root: &str, sids: &HashSet<String>) -> HashMap<String, Value> {
    let mut best: HashMap<String, (Vec<Value>, Value)> = HashMap::new();
    let Ok(rd) = std::fs::read_dir(format!("{root}/parts")) else { return HashMap::new() };
    let mut machines: Vec<String> = rd.flatten().filter_map(|e| e.file_name().into_string().ok())
        .filter(|m| !m.is_empty() && m.bytes().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')).collect();
    machines.sort();
    for m in machines {
        let p = format!("{root}/parts/{m}/meta/sessions.parquet");
        for r in read_parquet(&p, &["sid", "tier", "last_ts", "n_rows", "base", "proj"]) {
            let sid = s(r.get("sid").unwrap_or(&Value::Null)).to_string();
            if !sids.contains(&sid) {
                continue;
            }
            let g = |k: &str| r.get(k).cloned().unwrap_or(Value::Null);
            let n_rows = g("n_rows").as_str().and_then(|x| x.parse::<i64>().ok()).or_else(|| g("n_rows").as_i64());
            // ORDER BY tier <> 'main', machine LIKE '%-import', machine, last_ts DESC NULLS LAST, n_rows DESC NULLS LAST, base
            let key = vec![json!(g("tier").as_str() != Some("main")), json!(m.ends_with("-import")), json!(m),
                           json!(g("last_ts").is_null()), g("last_ts"), json!(n_rows.is_none()), json!(n_rows.unwrap_or(0)), g("base")];
            let better = match best.get(&sid) {
                None => true,
                Some((k0, _)) => cmp_key(&key, k0) == std::cmp::Ordering::Less,
            };
            if better {
                best.insert(sid, (key, g("proj")));
            }
        }
    }
    best.into_iter().map(|(k, (_, v))| (k, v)).collect()
}

fn cmp_key(a: &[Value], b: &[Value]) -> std::cmp::Ordering {
    use std::cmp::Ordering::*;
    for (i, (x, y)) in a.iter().zip(b).enumerate() {
        let o = match (x, y) {
            (Value::Bool(p), Value::Bool(q)) => p.cmp(q),
            (Value::String(p), Value::String(q)) => p.cmp(q),
            (Value::Number(p), Value::Number(q)) => p.as_i64().cmp(&q.as_i64()),
            (Value::Null, Value::Null) => Equal,
            (Value::Null, _) => Greater,
            (_, Value::Null) => Less,
            _ => Equal,
        };
        let o = if i == 4 || i == 6 { o.reverse() } else { o };   // last_ts and n_rows: DESC
        if o != Equal {
            return o;
        }
    }
    Equal
}

fn names(root: &str, sids: &HashSet<String>) -> HashMap<String, Value> {
    read_parquet(&format!("{root}/index/_search/names.parquet"), &["sid", "name"])
        .into_iter()
        .filter_map(|r| {
            let sid = r.get("sid")?.as_str()?.to_string();
            sids.contains(&sid).then(|| (sid, r.get("name").cloned().unwrap_or(Value::Null)))
        })
        .collect()
}

fn freshness(root: &str) -> Value {
    let sd = format!("{root}/index/_search");
    let built = std::fs::metadata(format!("{sd}/current.json")).ok().and_then(|m| m.modified().ok())
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| iso(d.as_secs() as i64 * 1000)[..19].to_string() + "Z");
    let vs: Option<Value> = std::fs::read_to_string(format!("{sd}/vectors.json")).ok().and_then(|t| serde_json::from_str(&t).ok());
    let pending = vs.as_ref().and_then(|v| {
        let mut n: i64 = 0;
        for w in v.get("models")?.as_object()?.values() {
            for x in w.as_object()?.values() {
                let p = &x["pending"];
                n += p.as_i64().or_else(|| p.as_str().and_then(|t| t.trim().parse().ok()))?;
            }
        }
        Some(n)
    });
    let (vat, counted) = match (&vs, pending) {
        (Some(v), Some(_)) => (v.get("at").cloned().unwrap_or(Value::Null), v.get("counted_at").cloned().unwrap_or(Value::Null)),
        _ => (Value::Null, Value::Null),
    };
    json!({"index_built": built, "vectors_at": vat, "vectors_pending": pending, "pending_counted_at": counted})
}

// ---- tokens (fts.py tokens(): lance's query tokenizer, ICU, no stemming, no stop words, max 128) ----

struct Tok(Box<dyn lance_index::scalar::inverted::tokenizer::document_tokenizer::LanceTokenizer>);

impl Tok {
    fn new() -> Option<Tok> {
        let p = lance_index::scalar::InvertedIndexParams::default()
            .base_tokenizer("icu".to_string())
            .stem(false)
            .remove_stop_words(false)
            .max_token_length(Some(128));
        p.build().ok().map(Tok)
    }
    fn tokens(&mut self, text: &str) -> Vec<String> {
        let mut out = Vec::new();
        let mut st = self.0.token_stream_for_search(text);
        while st.advance() {
            out.push(st.token().text.clone());
        }
        out
    }
}

// ---- search ----

/// GET /api/search?<params> answered natively, or None: the core answers it (see the top of this file)
pub fn search(root: &str, params: &[(String, String)]) -> Option<Value> {
    let mut p: HashMap<&str, &str> = HashMap::new();
    for (k, v) in params {
        if !KNOWN.contains(&k.as_str()) && k != "with" && k != "sort" {
            return None;   // a filter this port does not carry
        }
        p.insert(k.as_str(), v.as_str());   // the last value wins, as the hub's args_of
    }
    let query = p.get("q").copied().unwrap_or("");
    if query.split_whitespace().next().is_none() {
        return None;   // the core's usage error
    }
    let limit: usize = match p.get("limit") {
        None => 20,
        Some(v) => match v.parse::<usize>() { Ok(n) if n >= 1 => n.min(100), _ => return None },
    };
    let sort = p.get("sort").copied().filter(|x| !x.is_empty());
    if !matches!(sort, None | Some("relevant") | Some("newest")) {
        return None;
    }
    let with_ = p.get("with").copied().filter(|x| !x.is_empty());
    let mut layers: Vec<String> = match with_ {
        Some(w @ ("memory" | "config" | "git")) => vec![w.to_string()],
        Some("discord") => return None,
        Some("all") => ["prose", "tools", "thinking", "memory", "config", "git"].map(String::from).to_vec(),
        Some(w) => std::iter::once("prose".to_string()).chain(w.split(',').filter(|x| !x.is_empty()).map(String::from)).collect(),
        None => vec!["prose".into()],
    };
    layers = layers.into_iter().map(|l| if l == "vault" { "prose".into() } else { l }).collect();
    let mut uniq = Vec::new();
    for l in layers {
        if !uniq.contains(&l) {
            uniq.push(l);
        }
    }
    let layers = uniq;
    if layers.iter().any(|l| !["prose", "tools", "thinking", "memory", "config", "git"].contains(&l.as_str())) {
        return None;
    }
    let now = now_ms()?;
    let (since, until, horizon) = (p.get("since").copied(), p.get("until").copied(), p.get("horizon").copied().filter(|x| !x.is_empty()));
    let lo = bound(since, false, now).ok()?;
    let hi = bound(until, true, now).ok()?;
    if horizon.is_some() && (since.is_some_and(|x| !x.is_empty()) || until.is_some_and(|x| !x.is_empty())) {
        return None;
    }
    if let Some(h) = horizon {
        horizon_days(h)?;
    }
    let role = p.get("role").copied().filter(|x| !x.is_empty());
    let session = p.get("session").copied().filter(|x| !x.is_empty());
    let mut conds: Vec<String> = Vec::new();
    if let Some(h) = &hi {
        conds.push(format!("ts <= {}", q_(h)));
    }
    if let Some(r) = role {
        conds.push(format!("role = {}", q_(r)));
    }
    if let Some(sess) = session {
        conds.push(format!("sid LIKE {}", q_(&(sess.replace('%', "") + "%"))));
    }
    let ix = Index::open(root)?;
    // the cursor's signature hashes the arguments as the core received them ("" stays "", absent is null)
    let raw = |k: &str| p.get(k).map(|x| json!(x)).unwrap_or(Value::Null);
    let sig_src = json!([query, lo, hi, null, raw("session"), raw("role"), null, raw("with"), raw("sort"), null, null, null, null, null, null]);
    let sig: String = sha1_smol::Sha1::from(py_json(&sig_src)).digest().to_string()[..12].to_string();
    let fixed: Option<String> = horizon.map(String::from).or_else(|| (lo.is_some() || hi.is_some() || session.is_some()).then(|| "window".into()));
    let mut tried: Vec<String> = Vec::new();
    let mut hits: Vec<Row> = Vec::new();
    let mut chosen: Option<String> = None;
    let want = limit + 1;
    let mut filter: Option<String> = None;
    let hzs: Vec<String> = match &fixed { Some(f) => vec![f.clone()], None => WIDEN.map(String::from).to_vec() };
    for hz in hzs {
        let start = if hz == "window" { lo.clone() } else { horizon_days(&hz)?.map(|d| iso(now - d * 86_400_000)) };
        let mut c = conds.clone();
        if let Some(st) = &start {
            c.push(format!("ts >= {}", q_(st)));
        }
        filter = (!c.is_empty()).then(|| c.join(" AND "));
        tried.push(hz.clone());
        hits = run(&ix, query, &layers, filter.as_deref(), want).ok()?;   // an FTS error: the core answers by substring
        chosen = Some(hz);
        if fixed.is_some() || hits.len() >= limit.min(10) {
            break;
        }
    }
    let mut older = 0usize;
    let mut note: Option<String> = None;
    let ch = chosen.clone().unwrap_or_default();
    if horizon.is_none() && lo.is_none() && hi.is_none() && session.is_none() && !["", "archive", "window"].contains(&ch.as_str()) {
        if let Some(d) = horizon_days(&ch).flatten() {
            let cut = iso(now - d * 86_400_000);
            let mut c = conds.clone();
            c.push(format!("ts < {}", q_(&cut)));
            let mut seen: HashSet<(String, String, String)> = HashSet::new();
            for r in &hits {
                seen.insert(fold_key(r));
                seen.insert(("\u{1}key".to_string(), s(&r["key"]).to_string(), String::new()));
            }
            let more = fold(run(&ix, query, &layers, Some(&c.join(" AND ")), want).ok()?, &mut seen);
            older = more.len();
            hits.extend(more);
            note = Some(if older > 0 {
                format!("{} hits in the last {ch}, then the best {older} older ones", hits.len() - older)
            } else {
                format!("nothing older than {ch} matches")
            });
        }
    }
    if sort == Some("newest") {
        if hits.len() < 600.min(limit + 1) {
            hits = run(&ix, query, &layers, filter.as_deref(), 600).ok()?;
        }
        hits.truncate(600);
        hits.sort_by(|a, b| s(&b["ts"]).cmp(s(&a["ts"])));
    }
    let page: Vec<Row> = hits.iter().take(limit).cloned().collect();
    let more = hits.len() > limit;
    let sids: HashSet<String> = page.iter().map(|h| s(&h["sid"]).to_string()).filter(|x| !x.is_empty()).collect();
    if sids.iter().any(|x| x.starts_with("vault:")) {
        return None;   // vault names come from vaults.py: the core's
    }
    let repo_of = repos(root, &sids);
    let name_of = names(root, &sids);
    let mut tok = Tok::new();
    let qtok: Vec<String> = match tok.as_mut() {
        Some(t) => {
            let mut v: Vec<String> = Vec::new();
            for x in t.tokens(query) {
                if !v.contains(&x) {
                    v.push(x);
                }
            }
            v
        }
        None => vec![],
    };
    let words: Vec<String> = query.split_whitespace().map(String::from).collect();
    let ephemeral = regex::Regex::new(r"(?:/private)?/tmp/\S+|/var/folders/\S+|\bscratchpad/\S*|claude-\d+/\S*").ok()?;
    let mut out: Vec<Value> = Vec::new();
    for r in &page {
        let text = s(r.get("text").unwrap_or(&Value::Null));
        let sid = s(&r["sid"]);
        let htok: HashSet<String> = match (&mut tok, qtok.is_empty()) {
            (Some(t), false) => t.tokens(&text.chars().take(20000).collect::<String>()).into_iter().collect(),
            _ => HashSet::new(),
        };
        let mut eph: Vec<String> = ephemeral.find_iter(text).map(|m| m.as_str().to_string()).collect::<HashSet<_>>().into_iter().collect();
        eph.sort();
        eph.truncate(5);
        let day: String = s(r.get("ts_th").unwrap_or(&Value::Null)).chars().take(10).collect();
        let score: f64 = format!("{:.4}", r["_score"].as_f64().unwrap_or(0.0)).parse().unwrap_or(0.0);
        let repo_key = if let Some(rest) = sid.strip_prefix("git:") { json!(rest) } else { repo_of.get(sid).cloned().unwrap_or(Value::Null) };
        let homes = r.get("homes").and_then(|h| h.as_str()).filter(|h| !h.is_empty()).map(|h| json!(h.split('\n').collect::<Vec<_>>())).unwrap_or(Value::Null);
        let mut h = Map::new();
        h.insert("uid".into(), r["uid"].clone());
        h.insert("partition".into(), r["month"].clone());
        h.insert("session_uuid".into(), r["sid"].clone());
        h.insert("role".into(), r["role"].clone());
        h.insert("ts".into(), r["ts"].clone());
        h.insert("day".into(), if day.is_empty() { Value::Null } else { json!(day) });
        h.insert("repo_key".into(), repo_key);
        h.insert("session_name".into(), name_of.get(sid).cloned().unwrap_or(Value::Null));
        h.insert("text_snippet".into(), json!(snippet(text, &words, 240)));
        h.insert("score".into(), json!(score));
        h.insert("layer".into(), r["layer"].clone());
        h.insert("source_present".into(), json!(false));
        h.insert("ephemeral".into(), if eph.is_empty() { Value::Null } else { json!(eph) });
        h.insert("machines".into(), r.get("machines").cloned().unwrap_or(Value::Null));
        h.insert("title".into(), r.get("title").cloned().unwrap_or(Value::Null));
        h.insert("home".into(), r.get("home").cloned().unwrap_or(Value::Null));
        h.insert("homes".into(), homes);
        h.insert("agent".into(), r.get("agent").cloned().unwrap_or(Value::Null));
        h.insert("link".into(), json!(format!("relic5://{}/{}", s(&r["month"]), s(&r["uid"]))));
        h.insert("matched".into(), if qtok.is_empty() { Value::Null } else { json!(qtok.iter().filter(|t| htok.contains(*t)).collect::<Vec<_>>()) });
        h.insert("locator".into(), json!({"month": r["month"], "stream": r["layer"], "key": r["key"], "chunk": r["chunk"]}));
        out.push(Value::Object(h));
    }
    if out.is_empty() && since.is_some_and(|x| x.len() > 1 && x.ends_with('m') && x[..x.len() - 1].bytes().all(|b| b.is_ascii_digit())) {
        return None;   // #95's note: the core words it
    }
    let nxt = more.then(|| {
        use base64::Engine;
        let c = py_json(&json!({"o": limit, "q": sig, "h": chosen}));
        base64::engine::general_purpose::URL_SAFE.encode(c).trim_end_matches('=').to_string()
    });
    let mut months: Vec<String> = hits.iter().filter_map(|h| h.get("month").and_then(|m| m.as_str()).filter(|m| !m.is_empty()).map(String::from)).collect();
    months.sort();
    months.dedup();
    let mut r = Map::new();
    r.insert("hits".into(), Value::Array(out));
    r.insert("next_cursor".into(), json!(nxt));
    r.insert("horizon".into(), json!(chosen));
    r.insert("widened".into(), json!(tried.len() > 1));
    r.insert("horizons_tried".into(), json!(tried));
    r.insert("searched_weeks".into(), json!(months));
    r.insert("searched_months".into(), json!(months));
    r.insert("older_hits".into(), json!(older));
    r.insert("note".into(), json!(note));
    r.insert("collapsed".into(), json!(0));
    r.insert("freshness".into(), freshness(root));
    // the hub's key order: hits, next_cursor, horizon, horizons_tried, widened, ...
    let order = ["hits", "next_cursor", "horizon", "horizons_tried", "widened", "searched_weeks", "searched_months", "older_hits", "note", "collapsed", "freshness"];
    Some(Value::Object(order.iter().map(|k| (k.to_string(), r.remove(*k).unwrap_or(Value::Null))).collect()))
}
