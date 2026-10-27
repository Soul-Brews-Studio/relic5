//! `relic5 searched` and `relic5 trace`: search what was already searched, and read a trace chain (Nat, 2026-10-27:
//! "we should have search from the searched! and we can add relic link trace?", "relic tag it seems helper").
//!
//!   relic5 searched <words> [--since D] [--until D] [--limit 20]   past searches, found notes and tags with these words
//!   relic5 searched --link relic5://…                              the way back: every search that returned the message,
//!                                                                  every call that opened it, every found note citing it
//!   relic5 trace [<trace id>] [--limit 30]                         one chain, or the newest chains
use crate::cmds::Args;
use crate::hub::{self, Fail};
use crate::py::{dumps, head, s, squash};
use serde_json::Value;

fn list(v: &Value) -> Vec<Value> {
    v.as_array().cloned().unwrap_or_default()
}

pub fn searched(mut a: Args, json: bool) -> Result<(), Fail> {
    let link = a.opt("--link")?;
    let since = a.opt("--since")?;
    let until = a.opt("--until")?;
    let limit = a.opt_or("--limit", "20")?;
    let q = a.0.join(" ");
    if q.is_empty() && link.is_none() {
        return Err(Fail::Other("relic5 searched <words> | --link relic5://… [--since D] [--until D] [--limit 20]".into(), 2));
    }
    let mut p: Vec<(String, String)> = vec![("limit".into(), limit)];
    if !q.is_empty() {
        p.push(("q".into(), q.clone()));
    }
    for (k, v) in [("link", &link), ("since", &since), ("until", &until)] {
        if let Some(v) = v {
            p.push((k.into(), v.clone()));
        }
    }
    let r = hub::call("/api/searched", &p)?;
    if json {
        println!("{}", dumps(&r));
        return Ok(());
    }
    let chains = list(&r["chains"]);
    match &link {
        Some(l) => println!("{} searches lead to {l}{}", chains.len(),
                            if list(&r["tags"]).is_empty() { String::new() } else { format!(" · tags {}", list(&r["tags"]).iter().map(s).collect::<Vec<_>>().join(", ")) }),
        None => println!("{} earlier chains match \"{q}\" (of {})", chains.len(), s(&r["total"])),
    }
    for c in &chains {
        let qs: Vec<String> = list(&c["queries"]).iter().map(|x| head(&squash(&s(x)), 60)).collect();
        let tags = list(&c["tags"]).iter().map(s).collect::<Vec<_>>();
        println!("\n{}  trace {}  {}{}{}", head(&s(&c["last"]), 16).replace('T', " "), s(&c["root"]),
                 list(&c["why"]).iter().map(s).collect::<Vec<_>>().join("+"),
                 if c["hits"].is_null() { String::new() } else { format!(" · {} hits", s(&c["hits"])) },
                 if tags.is_empty() { String::new() } else { format!(" · #{}", tags.join(" #")) });
        if !qs.is_empty() {
            println!("  asked: {}", qs.join(" | "));
        }
        for f in list(&c["found"]) {
            println!("  found: {}", head(&squash(&s(&f["found"])), 110));
            if !f["goal"].is_null() {
                println!("    goal {}", head(&squash(&s(&f["goal"])), 100));
            }
            for l in list(&f["links"]).iter().take(3) {
                println!("    -> {}", s(l));
            }
        }
        if list(&c["found"]).is_empty() {
            for l in list(&c["links"]).iter().take(3) {
                println!("  -> {}", s(l));
            }
        }
    }
    if !chains.is_empty() {
        println!("\n(a whole chain: relic5 trace <trace id>)");
    }
    Ok(())
}

pub fn trace(mut a: Args, json: bool) -> Result<(), Fail> {
    let limit = a.opt_or("--limit", "30")?;
    let id = a.0.first().cloned();
    let p: Vec<(String, String)> = match &id {
        Some(i) => vec![("id".into(), i.clone())],
        None => vec![("limit".into(), limit)],
    };
    let r = hub::call("/api/trace", &p)?;
    if json {
        println!("{}", dumps(&r));
        return Ok(());
    }
    if id.is_none() {
        for c in list(&r["chains"]) {
            println!("{}  trace {}  {} steps  {}{}", head(&s(&c["last"]), 16).replace('T', " "), s(&c["root"]), s(&c["steps"]),
                     head(&squash(&s(&c["query"])), 60),
                     if c["found"].is_null() { String::new() } else { format!("  -> found: {}", head(&squash(&s(&c["found"])), 60)) });
        }
        return Ok(());
    }
    println!("trace {} · {} searches · {} opened · {} → {}", s(&r["root"]), s(&r["searches"]), s(&r["opened"]),
             head(&s(&r["first"]), 16).replace('T', " "), head(&s(&r["last"]), 16).replace('T', " "));
    for st in list(&r["steps"]) {
        let depth = st["depth"].as_u64().unwrap_or(0) as usize;
        let what = match s(&st["tool"]).as_str() {
            "relic_search" => format!("search \"{}\" → {} hits", head(&squash(&s(&st["query"])), 70), s(&st["hits"])),
            "relic_show" | "relic_session" => format!("open {}", s(&st["args"]["id"])),
            "relic_found" => format!("FOUND {}", head(&squash(&s(&st["args"]["found"])), 80)),
            t => format!("{t} {}", head(&squash(&s(&st["query"])), 60)),
        };
        println!("{}  {}{}  {}", head(&s(&st["at"]), 19).replace('T', " "), "  ".repeat(depth), s(&st["id"]), what);
    }
    Ok(())
}
