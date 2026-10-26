//! The hub over HTTP: the same URL, token file and errors as the Python CLI's call().
use crate::py;
use serde_json::Value;
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
}

impl Fail {
    pub fn exit(self) -> ! {
        let (msg, code) = match self {
            Fail::Http(c, body) => (format!("relic5: {c} {}", py::head(&body, 300)), if c == 400 || c == 404 { 2 } else { 1 }),
            Fail::Unreachable(r) => (format!("relic5: hub unreachable ({}): {r}", url()), 1),
            Fail::Other(m, c) => (m, c),
        };
        eprintln!("{msg}");
        std::process::exit(code)
    }
}

fn token() -> Result<String, Fail> {
    let f = expand(&std::env::var("RELIC5_TOKEN_FILE").unwrap_or_else(|_| "~/.config/relic5/token".into()));
    std::fs::read_to_string(&f).map(|t| t.trim().to_string()).map_err(|e| Fail::Other(format!("relic5: token file {f}: {e}"), 1))
}

/// GET <url><path>?<params> with the bearer token; the JSON body
pub fn call(path: &str, params: &[(String, String)]) -> Result<Value, Fail> {
    get(path, params, Some(token()?), 60)
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
        .map_err(|e| Fail::Unreachable(e.to_string()))?;
    if code >= 400 {
        return Err(Fail::Http(code, body));
    }
    serde_json::from_str(&body).map_err(|e| Fail::Other(format!("relic5: the hub sent no JSON ({e})"), 1))
}
