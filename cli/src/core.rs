//! The Python core: every command the Rust client does not own goes to `relic5-core` with the same arguments
//! (the process is replaced, so its output, exit code and signals are the core's own).
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};

/// Where the core is, first found: $RELIC5_CORE, `relic5-core` on PATH, beside this binary, the uv tool, the hub's venv.
pub fn find() -> Option<PathBuf> {
    let me = std::env::current_exe().ok().and_then(|p| p.canonicalize().ok());
    let home = std::env::var("HOME").unwrap_or_default();
    let mut c: Vec<PathBuf> = Vec::new();
    if let Ok(p) = std::env::var("RELIC5_CORE") {
        c.push(p.into());
    }
    if let Ok(path) = std::env::var("PATH") {
        c.extend(std::env::split_paths(&path).map(|d| d.join("relic5-core")));
    }
    if let Some(d) = std::env::current_exe().ok().as_deref().and_then(Path::parent) {
        c.push(d.join("relic5-core"));
    }
    c.push(format!("{home}/.local/share/uv/tools/relic5/bin/relic5-core").into());
    c.push(format!("{home}/relic5/app/.venv/bin/relic5-core").into());
    c.into_iter().find(|p| {
        p.is_file() && p.canonicalize().ok() != me   // never this binary again
    })
}

pub fn exec(args: &[String]) -> ! {
    match find() {
        Some(core) => {
            let err = std::process::Command::new(&core).args(args).exec();
            eprintln!("relic5: cannot run {}: {err}", core.display());
            std::process::exit(1)
        }
        None => {
            eprintln!(
                "relic5: '{}' runs in the Python core, and relic5-core is not installed here\n  \
                 (uv tool install <relic5 checkout>, or set RELIC5_CORE)",
                args.first().map(String::as_str).unwrap_or("")
            );
            std::process::exit(1)
        }
    }
}
