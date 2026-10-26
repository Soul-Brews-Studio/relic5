//! `relic5 memory`: relic5's own memory — the Claude Code memory notes the hub holds (src/relic5/memory.py: one row per
//! note, type user | feedback | project | reference). Hindsight is `relic5 hindsight` (Nat, 2026-10-26: "relic5 memory
//! status not hindsight ... the hindsight should relic5 hindsight").
//!
//!   relic5 memory [status]                                   notes by type, by machine, projects, the newest ones
//!   relic5 memory list [--type T] [--project P] [--limit 20] the notes, newest first
//!   relic5 memory search <words> [--limit 20]                the hub's memory search layer
//!   relic5 memory recall|retain|import|workers|top …         still Hindsight: forwarded to `relic5 hindsight …`
use crate::cmds::Args;
use crate::hub::{self, Fail};
use crate::py::{commas, dumps, head, ljust, s, squash};
use serde_json::Value;
use std::collections::BTreeMap;

const HINDSIGHT: [&str; 5] = ["recall", "retain", "import", "workers", "top"];

pub fn main(mut rest: Vec<String>, json: bool) -> Result<(), Fail> {
    let sub = rest.first().cloned().unwrap_or_else(|| "status".into());
    if HINDSIGHT.contains(&sub.as_str()) {
        eprintln!("relic5 memory {sub}: Hindsight lives at `relic5 hindsight {sub}` now; forwarding");
        return crate::memory::main(rest, json);
    }
    if !rest.is_empty() {
        rest.remove(0);
    }
    let mut a = Args(rest);
    match sub.as_str() {
        "status" => status(json),
        "list" => list(&mut a, json),
        "search" => search(&mut a, json),
        other => Err(Fail::Other(format!("relic5 memory: unknown '{other}' (status, list, search; Hindsight: relic5 hindsight …)"), 2)),
    }
}

fn notes() -> Result<Vec<Value>, Fail> {
    let r = hub::call("/api/memory", &[])?;
    Ok(r["notes"].as_array().cloned().unwrap_or_default())
}

fn status(json: bool) -> Result<(), Fail> {
    let n = notes()?;
    let mut by_type: BTreeMap<String, i64> = BTreeMap::new();
    let mut by_machine: BTreeMap<String, i64> = BTreeMap::new();
    let mut projects: BTreeMap<String, i64> = BTreeMap::new();
    for x in &n {
        *by_type.entry(s(&x["type"])).or_default() += 1;
        for m in x["machines"].as_array().cloned().unwrap_or_default() {
            *by_machine.entry(s(&m)).or_default() += 1;
        }
        *projects.entry(s(&x["project"])).or_default() += 1;
    }
    let mut newest: Vec<&Value> = n.iter().collect();
    newest.sort_by(|a, b| s(&b["ts"]).cmp(&s(&a["ts"])));
    if json {
        let out = serde_json::json!({"notes": n.len(), "by_type": by_type, "by_machine": by_machine, "projects": projects.len(),
                                     "newest": newest.iter().take(10).collect::<Vec<_>>()});
        println!("{}", dumps(&out));
        return Ok(());
    }
    println!("relic5 memory · {} notes on the hub ({} projects) · newest {}", commas(&Value::from(n.len())), projects.len(),
             newest.first().map(|x| head(&s(&x["ts"]), 16).replace('T', " ")).unwrap_or_default());
    println!("  by type    {}", by_type.iter().map(|(k, v)| format!("{k} {}", commas(&Value::from(*v)))).collect::<Vec<_>>().join(" · "));
    println!("  by machine {}", by_machine.iter().map(|(k, v)| format!("{k} {}", commas(&Value::from(*v)))).collect::<Vec<_>>().join(" · "));
    let mut top: Vec<(&String, &i64)> = projects.iter().collect();
    top.sort_by(|a, b| b.1.cmp(a.1));
    println!("  top projects {}", top.iter().take(5).map(|(k, v)| format!("{} {v}", head(k, 32))).collect::<Vec<_>>().join(" · "));
    println!("  newest:");
    for x in newest.iter().take(5) {
        println!("    {}  {}  {}  {}", head(&s(&x["ts"]), 16).replace('T', " "), ljust(&s(&x["type"]), 9),
                 ljust(&head(&s(&x["project"]), 28), 28), head(&squash(&s(&x["title"])), 60));
    }
    println!("  (Hindsight, the facts learned from all of relic5: relic5 hindsight status)");
    Ok(())
}

fn list(a: &mut Args, json: bool) -> Result<(), Fail> {
    let ty = a.opt("--type")?;
    let proj = a.opt("--project")?;
    let limit: usize = a.opt_or("--limit", "20")?.parse().map_err(|_| Fail::Other("--limit must be a number".into(), 2))?;
    let mut n: Vec<Value> = notes()?
        .into_iter()
        .filter(|x| ty.as_ref().is_none_or(|t| s(&x["type"]) == *t))
        .filter(|x| proj.as_ref().is_none_or(|p| s(&x["project"]).to_lowercase().contains(&p.to_lowercase())))
        .collect();
    n.sort_by(|a, b| s(&b["ts"]).cmp(&s(&a["ts"])));
    n.truncate(limit);
    if json {
        println!("{}", dumps(&Value::Array(n)));
        return Ok(());
    }
    for x in &n {
        println!("{}  {}  {}  {}", head(&s(&x["ts"]), 16).replace('T', " "), ljust(&s(&x["type"]), 9),
                 ljust(&head(&s(&x["project"]), 28), 28), head(&squash(&s(&x["title"])), 70));
        let d = squash(&s(&x["description"]));
        if !d.is_empty() && d != "None" {
            println!("      {}", head(&d, 110));
        }
    }
    println!("{} notes", n.len());
    Ok(())
}

fn search(a: &mut Args, json: bool) -> Result<(), Fail> {
    let limit = a.opt_or("--limit", "20")?;
    let q = a.0.join(" ");
    if q.is_empty() {
        return Err(Fail::Other("relic5 memory search <words> [--limit 20]".into(), 2));
    }
    let r = hub::call("/api/search", &[("q".into(), q), ("with".into(), "memory".into()), ("limit".into(), limit)])?;
    let hits: Vec<Value> = r["hits"].as_array().cloned().unwrap_or_default()
        .into_iter()
        .filter(|h| s(&h["role"]).starts_with("memory"))
        .collect();
    if json {
        println!("{}", dumps(&Value::Array(hits)));
        return Ok(());
    }
    for h in &hits {
        let txt = if h["text_snippet"].is_null() { s(&h["text"]) } else { s(&h["text_snippet"]) };
        println!("{}  {}  {}", head(&s(&h["ts"]), 16).replace('T', " "), ljust(&s(&h["role"]).replace("memory-", ""), 9), head(&squash(&txt), 110));
    }
    println!("{} memory notes", hits.len());
    Ok(())
}
