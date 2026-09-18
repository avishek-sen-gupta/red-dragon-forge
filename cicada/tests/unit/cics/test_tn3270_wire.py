import socket
import threading
import time

from cics.tn3270.negotiation import Command, Subnegotiation
from cics.tn3270.wire import SocketTelnetPeer, serve_forever
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_events_records_and_disconnect():
    ours, theirs = socket.socketpair()
    peer = SocketTelnetPeer(ours)
    theirs.sendall(
        bytes((255, 251, 24, 255, 250, 24, 0))
        + b"IBM-3278-2"
        + bytes((255, 240, 0x7D, 0x40, 255, 255, 0x41, 255, 239))
    )
    assert peer.next_event() == Command(251, 24)
    assert peer.next_event() == Subnegotiation(24, b"\x00IBM-3278-2")
    assert peer.next_record() == bytes((0x7D, 0x40, 0xFF, 0x41))
    theirs.close()
    assert peer.next_record() == b""


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition never became true")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_session_fatal_error_ends_only_its_own_session():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    handled: list[str] = []

    def handle(_peer):
        if not handled:
            handled.append("first")
            raise KeyError("no field's data starts at buffer address 0")
        handled.append("second")

    def _run_until_stopped():
        # server.close() below unblocks the loop's next accept() with an
        # OSError by design (that is the documented shutdown path); swallow
        # it here so the test's own teardown doesn't read as an unhandled
        # in-thread exception.
        try:
            serve_forever(server, handle)
        except OSError:
            pass

    server_thread = threading.Thread(target=_run_until_stopped, daemon=True)
    server_thread.start()

    first_client = socket.create_connection(("127.0.0.1", port))
    _wait_until(lambda: handled == ["first"])
    first_client.close()

    second_client = socket.create_connection(("127.0.0.1", port))
    _wait_until(lambda: handled == ["first", "second"])
    second_client.close()

    server.close()
    server_thread.join(timeout=2.0)
    assert handled == ["first", "second"]
