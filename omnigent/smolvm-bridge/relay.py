"""Forward guest connections through service-specific UNIX sockets."""

import socket
from contextlib import ExitStack
from pathlib import Path
from socketserver import BaseRequestHandler, ThreadingTCPServer, ThreadingUnixStreamServer
from threading import Thread


GUEST_SOCKET = "/run/omnigent-server.sock"
SERVER_ADDRESS = ("127.0.0.1", 8000)
MAAS_SOCKET = "/run/omnigent-maas.sock"
MAAS_HOST = "models.corp.redhat.com"
MAAS_ADDRESS = ("127.0.0.2", 443)
RHAI_MAAS_SOCKET = "/run/omnigent-rhai-maas.sock"
RHAI_MAAS_HOST = "maas.apps.ocp.cloud.rhai-tmm.dev"
RHAI_MAAS_ADDRESS = ("127.0.0.3", 443)


def copy_stream(source, destination):
    try:
        while data := source.recv(65536):
            destination.sendall(data)
    except OSError:
        pass
    finally:
        try:
            destination.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class RelayHandler(BaseRequestHandler):
    def handle(self):
        try:
            with self.server.connect() as upstream:
                upload = Thread(target=copy_stream, args=(self.request, upstream), daemon=True)
                upload.start()
                copy_stream(upstream, self.request)
                upload.join()
        except OSError:
            pass


def connect_unix(path):
    upstream = socket.socket(socket.AF_UNIX)
    try:
        upstream.connect(path)
    except OSError:
        upstream.close()
        raise
    return upstream


def host_relay(path, address):
    server = ThreadingUnixStreamServer(str(path), RelayHandler)
    server.daemon_threads = True
    server.connect = lambda: socket.create_connection(address)
    return server


class GuestRelay(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, upstream_path):
        self.upstream_path = upstream_path
        super().__init__(address, RelayHandler)

    def connect(self):
        return connect_unix(self.upstream_path)


def add_maas_host(address, hostname):
    hosts = Path("/etc/hosts")
    entry = f"{address[0]} {hostname}"
    if entry not in hosts.read_text().splitlines():
        with hosts.open("a") as hosts_file:
            hosts_file.write(f"\n{entry}\n")


if __name__ == "__main__":
    with ExitStack() as stack:
        server = stack.enter_context(GuestRelay(SERVER_ADDRESS, GUEST_SOCKET))
        for path, address, hostname in (
            (MAAS_SOCKET, MAAS_ADDRESS, MAAS_HOST),
            (RHAI_MAAS_SOCKET, RHAI_MAAS_ADDRESS, RHAI_MAAS_HOST),
        ):
            if Path(path).is_socket():
                maas = stack.enter_context(GuestRelay(address, path))
                add_maas_host(address, hostname)
                Thread(target=maas.serve_forever, daemon=True).start()
        server.serve_forever()
