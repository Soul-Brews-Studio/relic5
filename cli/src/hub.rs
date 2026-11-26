//! The hub over HTTP: the same URL, token file and errors as the Python CLI's call().
use crate::{core, py};
use serde_json::{Value, json};
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

pub const DEFAULT_URL: &str = "http://white.follow-rankine.ts.net:8795";

pub fn url() -> String {
    std::env::var("RELIC5_URL").unwrap_or_else(|_| DEFAULT_URL.to_string())
}

pub fn expand(p: &str) -> String {
    match p.strip_prefix("~/") {
        Some(rest) => format!("{}/{rest}", std::env::var("HOME").unwrap_or_default()),
        None => p.to_string(),
    }
}

/// What can go wrong, with the exit code the Python CLI uses (0 ok · 1 error · 2 usage · 75 locked · 130 cancelled)
pub enum Fail {
    Http(u16, String),  // relic5: <code> <body[:300]>   exit 2 for 400/404, else 1
    Unreachable(String), // relic5: hub unreachable (<url>): <reason>   exit 1
    Other(String, i32),
    Exit(i32),           // the core already printed its error (embedded mode): exit with its code
}

impl Fail {
    pub fn exit(self) -> ! {
        let (msg, code) = match self {
            Fail::Http(c, body) => (format!("relic5: {c} {}", py::head(&body, 300)), if c == 400 || c == 404 { 2 } else { 1 }),
            Fail::Unreachable(r) => (format!("relic5: hub unreachable ({}): {r}\n{}", url(), fix_hint()), 1),
            Fail::Other(m, c) => (m, c),
            Fail::Exit(c) => std::process::exit(c),
        };
        eprintln!("{msg}");
        std::process::exit(code)
    }
}

fn token_file() -> String {
    expand(&std::env::var("RELIC5_TOKEN_FILE").unwrap_or_else(|_| "~/.config/relic5/token".into()))
}

fn token() -> Result<String, Fail> {
    let f = token_file();
    std::fs::read_to_string(&f).map(|t| t.trim().to_string()).map_err(|e| Fail::Other(format!("relic5: token file {f}: {e}"), 1))
}

// ---- embedded mode (#311): no hub needed for this machine's own reads; the same rules as src/relic5/local.py ----

static MODE: Mutex<Option<Value>> = Mutex::new(None);

/// How the last call() was answered, for `relic5 status`: {"used": "hub" | "local", "why": .., "url" | "root": ..}
pub fn mode() -> Value {
    MODE.lock().ok().and_then(|m| m.clone()).unwrap_or_else(|| json!({}))
}

fn set_mode(v: Value) {
    if let Ok(mut m) = MODE.lock() {
        *m = Some(v);
    }
}

pub fn local_forced() -> bool {
    matches!(std::env::var("RELIC5_LOCAL").unwrap_or_default().trim().to_lowercase().as_str(), "1" | "true" | "yes" | "on")
}

pub fn hub_forced() -> bool {
    matches!(std::env::var("RELIC5_HUB").unwrap_or_default().trim().to_lowercase().as_str(), "1" | "true" | "yes" | "on")
}

const DEFAULT_WHY: &str = "the default: a store is here, no hub needed (--hub or RELIC5_HUB=1 asks the hub)";

/// The default (#311, local.py's local_first): this machine's store when one is here, unless the hub was asked for
/// (--hub, RELIC5_HUB=1, an explicit RELIC5_URL). status asks the hub first: a local status reads everything.
fn local_first(path: &str) -> bool {
    !hub_forced() && std::env::var("RELIC5_URL").is_err() && path != "/api/status" && has_store()
}

/// --root (set as RELIC5_ROOT by main), else RELIC5_ROOT, else storage.json's root (the hub's own choice), else ~/relic5
pub fn root() -> String {
    if let Ok(r) = std::env::var("RELIC5_ROOT") {
        if !r.is_empty() {
            return expand(&r);
        }
    }
    let cfg = expand(&std::env::var("RELIC5_STORAGE").unwrap_or_else(|_| "~/.config/relic5/storage.json".into()));
    let from_cfg = std::fs::read_to_string(cfg)
        .ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
        .and_then(|v| v.get("root").and_then(Value::as_str).map(str::to_string))
        .filter(|r| !r.is_empty());
    expand(&from_cfg.unwrap_or_else(|| "~/relic5".into()))
}

/// A store a reader can answer from: the published search index, or at least the parts (an S3 root is the core's to judge)
pub fn has_store() -> bool {
    let r = root();
    if r.starts_with("s3://") {
        return true;
    }
    let p = std::path::Path::new(&r);
    p.join("index/_search/current.json").is_file() || p.join("parts").is_dir()
}

/// The commands that fix "no hub" (fleet rule: every error prints the fixing command)
pub fn fix_hint() -> String {
    let r = root();
    format!(
        "  start the hub here:        relic5 serve --root {r}\n  \
         or read a store directly:  export RELIC5_LOCAL=1   (with --root DIR or RELIC5_ROOT if it is not {r})\n  \
         or use another hub:        export RELIC5_URL=http://<host>:8795   (now {})",
        url()
    )
}

/// The engine a no-hub `search` uses: RELIC5_LOCAL_ENGINE, else `relic5 engine`'s file, else the build's own
/// (rs on a native build, py otherwise). A py-only build answers py whatever is asked. (engine, why)
pub fn engine_file() -> String {
    expand(&std::env::var("RELIC5_ENGINE_FILE").unwrap_or_else(|_| "~/.config/relic5/engine".into()))
}

pub fn engine() -> (&'static str, String) {
    let built = if cfg!(feature = "native") { "rs" } else { "py" };
    let (want, why) = match std::env::var("RELIC5_LOCAL_ENGINE") {
        Ok(e) => (if e.trim() == "py" { "py" } else { "rs" }, "RELIC5_LOCAL_ENGINE".to_string()),
        Err(_) => match std::fs::read_to_string(engine_file()).map(|t| t.trim().to_string()) {
            Ok(t) if t == "py" || t == "rs" => (if t == "py" { "py" } else { "rs" }, engine_file()),
            _ => (built, "this build's default".to_string()),
        },
    };
    if want == "rs" && built == "py" {
        return ("py", format!("{why} asks for rs, but this build has only py (just cli --engine rs)"));
    }
    (want, why)
}

/// The route answered by the Python core from this machine's store (relic5-core local-call): the same JSON, and on an
/// error the same message and exit code as the hub's, printed by the core itself
fn local(path: &str, params: &[(String, String)], why: String) -> Result<Value, Fail> {
    // --engine rs build: search answered in Rust when it can (native.rs); engine py (RELIC5_LOCAL_ENGINE=py, or
    // `relic5 engine py`) always asks the core
    #[cfg(feature = "native")]
    if path == "/api/search" && engine().0 == "rs" {
        if let Some(v) = crate::native::search(&root(), params) {
            set_mode(json!({"used": "local", "why": why, "root": root(), "engine": "rs"}));
            return Ok(v);
        }
    }
    let Some(core) = core::find() else {
        return Err(Fail::Other(
            "relic5: embedded mode runs in the Python core, and relic5-core is not installed here\n  \
             (uv tool install <relic5 checkout>, or set RELIC5_CORE)"
                .into(),
            1,
        ));
    };
    let pairs = Value::Array(params.iter().map(|(k, v)| json!([k, v])).collect());
    let out = Command::new(&core)
        .args(["local-call", path, &pairs.to_string()])
        .env("RELIC5_ROOT", root())
        .stdin(Stdio::null())
        .stderr(Stdio::piped())
        .output()
        .map_err(|e| Fail::Other(format!("relic5: cannot run {}: {e}", core.display()), 1))?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        if err.contains("unknown command 'local-call'") {   // a core from before #311
            return Err(Fail::Other(format!(
                "relic5: embedded mode needs a newer relic5-core than {} (it has no local-call)\n  \
                 upgrade it: just cli (in a relic5 checkout), or set RELIC5_CORE to a newer one",
                core.display()), 1));
        }
        eprint!("{err}");
        return Err(Fail::Exit(out.status.code().unwrap_or(1)));
    }
    set_mode(json!({"used": "local", "why": why, "root": root()}));
    serde_json::from_slice(&out.stdout).map_err(|e| Fail::Other(format!("relic5: the core sent no JSON ({e})"), 1))
}

/// GET <url><path>?<params> with the bearer token; the JSON body. Embedded instead when RELIC5_LOCAL=1, or when no hub
/// can be reached (no token, refused, no route) and a store is here
pub fn call(path: &str, params: &[(String, String)]) -> Result<Value, Fail> {
    if local_forced() {
        return local(path, params, "RELIC5_LOCAL=1".into());
    }
    if local_first(path) {
        match local(path, params, DEFAULT_WHY.into()) {
            Err(Fail::Other(m, _)) => eprintln!("{m}\n  asking the hub instead"),   // no core, or one too old: the hub
            r => return r,
        }
    }
    let tok = match token() {
        Ok(t) => t,
        Err(Fail::Other(..)) if has_store() => return local(path, params, format!("no hub token ({})", token_file())),
        Err(Fail::Other(m, c)) => return Err(Fail::Other(format!("{m}\n{}", fix_hint()), c)),
        Err(e) => return Err(e),
    };
    match get(path, params, Some(tok), 60) {
        Err(Fail::Unreachable(r)) if has_store() => local(path, params, format!("hub unreachable ({}): {r}", url())),
        Ok(v) => {
            let why = if hub_forced() {
                "RELIC5_HUB=1"
            } else if std::env::var("RELIC5_URL").is_ok() {
                "RELIC5_URL"
            } else {
                "the default hub answered"
            };
            let mut m = json!({"used": "hub", "why": why, "url": url()});
            if path == "/api/status" && local_first("/api/search") {
                m["reads"] = json!("local");   // status asked the hub; the other reads answer from the store
            }
            set_mode(m);
            Ok(v)
        }
        other => other,
    }
}

/// The same without a token (the tailnet door needs none), shorter timeout: for the import's checks
pub fn peek(path: &str, timeout_s: u64) -> Option<Value> {
    get(path, &[], token().ok(), timeout_s).ok()
}

fn get(path: &str, params: &[(String, String)], tok: Option<String>, timeout_s: u64) -> Result<Value, Fail> {
    let mut u = url().trim_end_matches('/').to_string() + path;
    if !params.is_empty() {
        u = u + "?" + &py::urlencode(params);
    }
    let agent: ureq::Agent = ureq::Agent::config_builder()
        .http_status_as_error(false)
        .timeout_global(Some(Duration::from_secs(timeout_s)))
        .build()
        .into();
    let mut req = agent.get(&u);
    if let Some(t) = tok {
        req = req.header("Authorization", &format!("Bearer {t}"));
    }
    let mut resp = req.call().map_err(|e| Fail::Unreachable(e.to_string()))?;
    let code = resp.status().as_u16();
    let body = resp
        .body_mut()
        .with_config()
        .limit(u64::MAX)
        .read_to_string()
        .map_err(|e| Fail::Other(format!("relic5: hub unreachable ({}): {e}", url()), 1))?;   // reached it: never re-run locally
    if code >= 400 {
        return Err(Fail::Http(code, body));
    }
    serde_json::from_str(&body).map_err(|e| Fail::Other(format!("relic5: the hub sent no JSON ({e})"), 1))
}
