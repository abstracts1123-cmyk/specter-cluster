"""Keep the suite network-free: only loopback connections are allowed."""

import socket

import pytest

_real_connect = socket.socket.connect


def _is_local(address) -> bool:
    return not isinstance(address, tuple) or address[0] in ("127.0.0.1", "::1", "localhost")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def guarded(self, address):
        if self.family != socket.AF_UNIX and not _is_local(address):
            raise RuntimeError(f"network access blocked in tests: {address!r}")
        return _real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    real_getaddrinfo = socket.getaddrinfo

    def guarded_dns(host, *args, **kwargs):
        if host not in (None, "127.0.0.1", "localhost", "::1"):
            raise RuntimeError(f"DNS blocked in tests: {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_dns)
