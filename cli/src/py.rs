//! The Python CLI's text rules, so the Rust client prints the same characters: json.dumps(indent=1,
//! ensure_ascii=False), str() of a JSON value, str.split()/rstrip() whitespace, slicing and padding by code point,
//! the `{n:,}` thousands separator and urllib's urlencode (quote_plus).
use serde_json::Value;

/// json.dumps(v, ensure_ascii=False, indent=1)
pub fn dumps(v: &Value) -> String {
    let mut out = Vec::new();
    let fmt = serde_json::ser::PrettyFormatter::with_indent(b" ");
    let mut ser = serde_json::Serializer::with_formatter(&mut out, fmt);
    serde::Serialize::serialize(v, &mut ser).expect("serialize");
    String::from_utf8(out).expect("utf8")
}

/// Python's str.isspace(): Unicode White_Space plus the four ASCII separators \x1c-\x1f
pub fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// " ".join(s.split())
pub fn squash(s: &str) -> String {
    s.split(is_space).filter(|w| !w.is_empty()).collect::<Vec<_>>().join(" ")
}

/// s.rstrip()
pub fn rstrip(s: &str) -> &str {
    s.trim_end_matches(is_space)
}

/// s[:n]
pub fn head(s: &str, n: usize) -> String {
    s.chars().take(n).collect()
}

/// s[a:b] by code point
pub fn mid(s: &str, a: usize, b: usize) -> String {
    s.chars().skip(a).take(b.saturating_sub(a)).collect()
}

/// f"{s:<n}"
pub fn ljust(s: &str, n: usize) -> String {
    let len = s.chars().count();
    if len >= n { s.to_string() } else { format!("{s}{}", " ".repeat(n - len)) }
}

/// f"{n:,}" for an integer (a JSON number as the hub wrote it)
pub fn commas(v: &Value) -> String {
    let t = num_text(v);
    let (sign, digits) = t.strip_prefix('-').map(|d| ("-", d)).unwrap_or(("", t.as_str()));
    let (int, frac) = digits.split_once('.').map(|(i, f)| (i, Some(f))).unwrap_or((digits, None));
    if !int.chars().all(|c| c.is_ascii_digit()) {
        return t.clone();
    }
    let mut g = String::new();
    for (i, c) in int.chars().enumerate() {
        if i > 0 && (int.len() - i) % 3 == 0 {
            g.push(',');
        }
        g.push(c);
    }
    match frac {
        Some(f) => format!("{sign}{g}.{f}"),
        None => format!("{sign}{g}"),
    }
}

fn num_text(v: &Value) -> String {
    match v {
        Value::Number(n) => n.to_string(),
        other => s(other),
    }
}

/// str(x) inside an f-string: None, True/False, numbers as written, strings raw, containers as Python repr
pub fn s(v: &Value) -> String {
    match v {
        Value::String(x) => x.clone(),
        other => repr(other),
    }
}

/// repr(x)
pub fn repr(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Number(n) => n.to_string(),
        Value::String(x) => {
            // Python picks single quotes unless the text holds a ' and no "
            let q = if x.contains('\'') && !x.contains('"') { '"' } else { '\'' };
            let mut o = String::from(q);
            for c in x.chars() {
                match c {
                    '\\' => o.push_str("\\\\"),
                    '\n' => o.push_str("\\n"),
                    '\r' => o.push_str("\\r"),
                    '\t' => o.push_str("\\t"),
                    c if c == q => {
                        o.push('\\');
                        o.push(c)
                    }
                    c if (c as u32) < 0x20 || c as u32 == 0x7f => o.push_str(&format!("\\x{:02x}", c as u32)),
                    c => o.push(c),
                }
            }
            o.push(q);
            o
        }
        Value::Array(a) => format!("[{}]", a.iter().map(repr).collect::<Vec<_>>().join(", ")),
        Value::Object(m) => format!("{{{}}}", m.iter().map(|(k, v)| format!("{}: {}", repr(&Value::String(k.clone())), repr(v))).collect::<Vec<_>>().join(", ")),
    }
}

/// Python truthiness of a JSON value
pub fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().map(|f| f != 0.0).unwrap_or(true),
        Some(Value::String(x)) => !x.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(m)) => !m.is_empty(),
    }
}

/// `a or b`: the first truthy value's str(), else str(b)
pub fn or(a: Option<&Value>, b: &str) -> String {
    if truthy(a) { s(a.unwrap()) } else { b.to_string() }
}

/// urllib.parse.urlencode(pairs): quote_plus on keys and values
pub fn urlencode(pairs: &[(String, String)]) -> String {
    pairs.iter().map(|(k, v)| format!("{}={}", quote_plus(k), quote_plus(v))).collect::<Vec<_>>().join("&")
}

fn quote_plus(s: &str) -> String {
    let mut o = String::new();
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'_' | b'.' | b'-' | b'~' => o.push(b as char),
            b' ' => o.push('+'),
            _ => o.push_str(&format!("%{b:02X}")),
        }
    }
    o
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn dumps_like_python() {
        let v: Value = serde_json::from_str(r#"{"a": [], "b": {}, "c": [1, 2.50, "ไทย\n"], "d": null}"#).unwrap();
        assert_eq!(dumps(&v), "{\n \"a\": [],\n \"b\": {},\n \"c\": [\n  1,\n  2.50,\n  \"ไทย\\n\"\n ],\n \"d\": null\n}");
    }
    #[test]
    fn commas_like_python() {
        assert_eq!(commas(&json!(1234567)), "1,234,567");
        assert_eq!(commas(&json!(-1000)), "-1,000");
        assert_eq!(commas(&json!(12)), "12");
    }
    #[test]
    fn text_rules() {
        assert_eq!(squash("  a\n\tb\u{1f}c  "), "a b c");
        assert_eq!(head("ไทยabc", 2), "ไท");
        assert_eq!(ljust("ab", 4), "ab  ");
        assert_eq!(repr(&json!(["it's", null, true])), "[\"it's\", None, True]");
        assert_eq!(urlencode(&[("q".into(), "a b/ä".into())]), "q=a+b%2F%C3%A4");
    }
}
