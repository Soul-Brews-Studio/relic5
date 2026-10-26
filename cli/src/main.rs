//! relic5: the command line. The hub client is here, in Rust: search, show, recap, conversation, readings, handoff,
//! tail, pending, status, --version, and `import` (one manual import). Every other command (index, serve, seals,
//! seal-day, token, embed, mcp, tui, eval, gc, log, import repair-meta|relic3|relic3-links|jsonl-truth, --help) is
//! handed, with the same arguments, to the Python core `relic5-core`, which stays the one implementation of the hub.
//! Output, flags and exit codes match the Python CLI (src/relic5/cli.py); tests/test_rust_cli.py compares the two.
mod cmds;
mod core;
mod hub;
mod import;
mod py;

use cmds::Args;

fn main() {
    unsafe {
        // like Python: a closed pipe (relic5 search … | head) ends quietly, Ctrl-C exits 130
        libc::signal(libc::SIGPIPE, libc::SIG_DFL);
    }
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let Some(cmd) = argv.first().cloned() else { core::exec(&argv) };   // no arguments: the core prints the help
    if matches!(cmd.as_str(), "--version" | "-V" | "version") {
        println!("relic5 {}", env!("RELIC5_VERSION"));
        return;
    }
    let mut rest: Vec<String> = argv[1..].to_vec();
    let json = rest.iter().any(|a| a == "--json");
    rest.retain(|a| a != "--json");
    let has_id = !rest.is_empty();
    let r = match cmd.as_str() {
        "search" => cmds::search(Args(rest), json),
        "show" if has_id => cmds::show(Args(rest), json),
        "conversation" if has_id => cmds::conversation(Args(rest), json),
        "readings" => cmds::readings(Args(rest), json),
        "recap" if has_id => cmds::recap(Args(rest), json),
        "handoff" if has_id => cmds::handoff(Args(rest)),
        "pending" => cmds::pending(),
        "tail" => cmds::tail(Args(rest)),
        "status" => cmds::status(),
        // `relic5 import` alone (or with flags) is the manual import; `import repair-meta|relic3|…` is the core's
        "import" if rest.first().is_none_or(|a| a.starts_with('-')) => std::process::exit(import::main(&rest)),
        _ => core::exec(&argv),
    };
    if let Err(e) = r {
        e.exit();
    }
}
