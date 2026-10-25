from relic5.doors import Doors

OWNER = "nat.wrw@gmail.com"
NODES = {"100.111.101.21": {"node": "m5.follow-rankine.ts.net", "login": OWNER},
         "100.99.9.9": {"node": "shared-node.other-tailnet.ts.net", "login": "someone-else@example.com"}}


def doors():
    return Doors({"m5": "tok"}, owner=OWNER, names={"white.follow-rankine.ts.net", "white", "100.103.52.67"}, whois=NODES.get)


def test_loopback():
    d = doors()
    assert d.door("127.0.0.1", "127.0.0.1", "localhost", "") == "loopback"
    assert d.door("127.0.0.1", "127.0.0.1", "evil.example", "") is None             # DNS rebinding: Host must name the hub


def test_own_tailnet_node_needs_no_token():
    d = doors()
    assert d.door("100.103.52.67", "100.111.101.21", "white.follow-rankine.ts.net", "") == "tailnet:m5"
    assert d.door("100.103.52.67", "100.111.101.21", "evil.example", "") is None


def test_shared_in_node_and_strangers_need_a_token():
    d = doors()
    assert d.door("100.103.52.67", "100.99.9.9", "white", "") is None             # the clinic's node: another owner
    assert d.door("100.103.52.67", "100.99.1.1", "white", "") is None                # whois knows nothing
    assert d.door("100.103.52.67", "192.168.1.5", "white", "") is None               # not a tailnet address
    assert d.door("100.103.52.67", "100.99.9.9", "white", "tok") == "token:m5"
    assert d.door("100.103.52.67", "100.111.101.21", "white", "wrong") is None       # a bad token is refused, not ignored


def test_whois_is_cached():
    calls = []
    d = Doors({}, owner=OWNER, names={"white"}, whois=lambda ip: calls.append(ip) or NODES.get(ip))
    for _ in range(3):
        d.door("100.103.52.67", "100.111.101.21", "white", "")
    assert calls == ["100.111.101.21"]
