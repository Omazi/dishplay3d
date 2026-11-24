"""The calculator's certificate and addresses. The iPhone pins the SHA-256 of the certificate and does not
look at the addresses written in it (ios/Network/PinnedSessionDelegate.swift): a new certificate means every
iPhone must be paired again, so the certificate is kept as long as it is valid."""
import datetime as dt
import ipaddress
import socket

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app import main
from app.tls import ensure_certificate, fingerprint


def test_the_certificate_is_kept_when_the_addresses_of_the_pc_change(tmp_path):
    cert, key, first = ensure_certificate(tmp_path, ["192.168.1.20"])
    assert fingerprint(cert) == first and len(first) == 64
    for ips in (["192.168.1.20"], ["192.168.1.20", "172.28.5.1"], ["10.0.0.7"], [], ["192.168.1.20"]):
        assert ensure_certificate(tmp_path, ips)[2] == first, f"a new certificate was made for {ips}"


def test_a_new_certificate_can_be_forced(tmp_path):
    first = ensure_certificate(tmp_path, ["192.168.1.20"])[2]
    second = ensure_certificate(tmp_path, ["192.168.1.20"], new=True)[2]
    assert second != first
    assert ensure_certificate(tmp_path, ["192.168.1.20"])[2] == second       # and that one is kept in turn


def write_certificate(directory, days_left):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DishPlay Scan local calculator")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=300))
            .not_valid_after(now + dt.timedelta(days=days_left))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("192.168.1.20"))]), critical=False)
            .sign(key, hashes.SHA256()))
    (directory / "server.key").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                              serialization.NoEncryption()))
    (directory / "server.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return fingerprint(directory / "server.crt")


def test_a_certificate_about_to_expire_is_replaced_and_a_valid_one_is_not(tmp_path):
    old = write_certificate(tmp_path, days_left=3)
    renewed = ensure_certificate(tmp_path, ["192.168.1.20"])[2]
    assert renewed != old
    (tmp_path / "other").mkdir()
    valid = write_certificate(tmp_path / "other", days_left=60)
    assert ensure_certificate(tmp_path / "other", ["10.0.0.7"])[2] == valid


def test_an_unreadable_certificate_is_replaced_instead_of_stopping_the_calculator(tmp_path):
    ensure_certificate(tmp_path, ["192.168.1.20"])
    (tmp_path / "server.crt").write_bytes(b"-----BEGIN CERTIFICATE-----\ncut in the middle")
    cert, key, fp = ensure_certificate(tmp_path, ["192.168.1.20"])
    assert fingerprint(cert) == fp


class FakeUDP:
    """The UDP socket lan_addresses() uses to ask the system which address goes out by the default route."""
    route = "192.168.1.20"

    def __init__(self, *args):
        pass

    def connect(self, target):
        if self.route is None:
            raise OSError("network is unreachable")

    def getsockname(self):
        return (self.route, 50000)

    def close(self):
        pass


def fake_network(monkeypatch, route, addresses):
    FakeUDP.route = route
    monkeypatch.setattr(main.socket, "socket", FakeUDP)
    monkeypatch.setattr(main.socket, "gethostname", lambda: "pc")
    monkeypatch.setattr(main.socket, "getaddrinfo",
                        lambda host, port, family=0, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in addresses])


def test_the_address_of_the_default_route_comes_first(monkeypatch):
    # A VPN ("10.") and a virtual network card ("172.") sort before the Wi-Fi address when sorted as text.
    fake_network(monkeypatch, "192.168.1.20", ["10.8.0.2", "172.28.5.1", "192.168.1.20", "127.0.0.1"])
    assert main.lan_addresses() == ["192.168.1.20", "10.8.0.2", "172.28.5.1"]
    fake_network(monkeypatch, "192.168.1.20", ["172.28.5.1"])          # not listed under the computer's name: still first
    assert main.lan_addresses() == ["192.168.1.20", "172.28.5.1"]
    fake_network(monkeypatch, None, ["172.28.5.1", "10.8.0.2"])        # no default route: the others, in a stable order
    assert main.lan_addresses() == ["10.8.0.2", "172.28.5.1"]


def run_main(monkeypatch, capsys, data, *options):
    """Start the calculator as `python -m app.main` does, without serving: what it would have served, and
    what it printed on the console."""
    import uvicorn
    served = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: served.update(app=app, **kwargs))
    main.main(["--data", str(data), "--code", "424242", *options])
    return served, capsys.readouterr().out


def test_the_terminal_qr_and_the_pairing_page_use_the_default_route_address(tmp_path, monkeypatch, capsys):
    links = []
    real_link = main.pairing_link
    with monkeypatch.context() as m:      # (the fake network must be gone before a browser is simulated below)
        fake_network(m, "192.168.1.20", ["10.8.0.2", "172.28.5.1", "192.168.1.20"])
        m.setattr(main, "pairing_link", lambda url, code, fp: links.append(url) or real_link(url, code, fp))
        served, out = run_main(m, capsys, tmp_path)
    fp = fingerprint(tmp_path / "tls" / "server.crt")
    assert links[-1] == "https://192.168.1.20:8765", "the QR shown in the terminal is the last link made"
    assert links[0] == "https://192.168.1.20:8765" and set(links) == {f"https://{ip}:8765" for ip in ("192.168.1.20", "10.8.0.2", "172.28.5.1")}
    lines = [line for line in out.splitlines() if "https://" in line and "dishplayscan://" not in line and "127.0.0.1" not in line]
    assert "192.168.1.20" in lines[0], lines
    assert fp in out and "424242" in out
    # The pairing page (opened on the calculator itself) shows one QR per address, in the same order.
    from fastapi.testclient import TestClient
    with TestClient(served["app"], client=("127.0.0.1", 50000)) as browser:
        page = browser.get("/").text
    shown = [page.index(f"<b>https://{ip}:8765</b>") for ip in ("192.168.1.20", "10.8.0.2", "172.28.5.1")]
    assert shown == sorted(shown), "the first QR of the pairing page is not the one of the default route"


def test_restarting_keeps_the_certificate_and_new_certificate_replaces_it(tmp_path, monkeypatch, capsys):
    fake_network(monkeypatch, "192.168.1.20", ["192.168.1.20"])
    run_main(monkeypatch, capsys, tmp_path)
    first = fingerprint(tmp_path / "tls" / "server.crt")
    fake_network(monkeypatch, "192.168.1.20", ["192.168.1.20", "172.28.5.1"])      # a virtual network card appeared
    _, out = run_main(monkeypatch, capsys, tmp_path)
    assert fingerprint(tmp_path / "tls" / "server.crt") == first
    assert "rescann" not in out.lower()
    _, out = run_main(monkeypatch, capsys, tmp_path, "--new-certificate")
    second = fingerprint(tmp_path / "tls" / "server.crt")
    assert second != first and second in out
    assert "rescann" in out.lower(), "the person must be told that every iPhone has to be paired again"
