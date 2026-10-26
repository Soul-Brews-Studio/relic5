// The version `relic5 --version` prints: pyproject's version (PEP 440, e.g. 26.10.26a316) as CalVer
// (26.10.26-alpha.316), the same as relic5/__init__.py _calver. One source for both CLIs.
fn main() {
    println!("cargo:rerun-if-changed=../pyproject.toml");
    let py = std::fs::read_to_string("../pyproject.toml").unwrap_or_default();
    let v = py
        .lines()
        .find_map(|l| l.strip_prefix("version = \"").and_then(|r| r.strip_suffix('"')))
        .unwrap_or("unknown");
    println!("cargo:rustc-env=RELIC5_VERSION={}", calver(v));
}

fn calver(v: &str) -> String {
    // (\d+\.\d+\.\d+)(?:(a|b)(\d+))?
    let i = v.find(|c: char| c == 'a' || c == 'b');
    match i {
        Some(i) if v[..i].split('.').count() == 3 && v[i + 1..].chars().all(|c| c.is_ascii_digit()) && i + 1 < v.len() => {
            let kind = if &v[i..i + 1] == "a" { "alpha" } else { "beta" };
            format!("{}-{}.{}", &v[..i], kind, &v[i + 1..])
        }
        _ => v.to_string(),
    }
}
