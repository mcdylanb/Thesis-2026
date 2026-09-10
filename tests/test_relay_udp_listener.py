"""Tests for scripts/relay_udp_listener.py's pure per-datagram handling.

scripts/ isn't an installed package, so the module under test is loaded
directly from its file path.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

from tests.conftest import make_csi_line, make_stat_line

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "relay_udp_listener.py"
_spec = importlib.util.spec_from_file_location("relay_udp_listener", _SCRIPT_PATH)
relay_udp_listener = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = relay_udp_listener
_spec.loader.exec_module(relay_udp_listener)


def test_csi_line_for_new_anchor_opens_file_and_writes_row():
    anchor_files: dict[str, io.StringIO] = {}
    opened = []

    def open_anchor_file(anchor):
        opened.append(anchor)
        return io.StringIO()

    stats = relay_udp_listener.ListenerStats()
    line = make_csi_line(anchor="A1", seq=1)

    relay_udp_listener.handle_line(
        anchor_files,
        line,
        host_iso="2026-09-10T00:00:00+00:00",
        host_ns=1000,
        stats=stats,
        open_anchor_file=open_anchor_file,
    )

    assert opened == ["A1"]
    assert set(anchor_files) == {"A1"}
    written = anchor_files["A1"].getvalue()
    assert written == (
        "host_iso,host_ns,line\n"
        f'2026-09-10T00:00:00+00:00,1000,"{line}"\n'
    )
    assert stats.lines == 1
    assert stats.skipped == 0


def test_stat_line_for_known_anchor_reuses_existing_file_no_new_header():
    existing_file = io.StringIO()
    existing_file.write("host_iso,host_ns,line\n")
    anchor_files = {"A2": existing_file}

    def open_anchor_file(anchor):
        raise AssertionError(f"should not open a new file for known anchor {anchor}")

    stats = relay_udp_listener.ListenerStats()
    line = make_stat_line(anchor="A2", dropped=3)

    relay_udp_listener.handle_line(
        anchor_files,
        line,
        host_iso="2026-09-10T00:00:01+00:00",
        host_ns=2000,
        stats=stats,
        open_anchor_file=open_anchor_file,
    )

    assert existing_file.getvalue() == (
        "host_iso,host_ns,line\n"
        f'2026-09-10T00:00:01+00:00,2000,"{line}"\n'
    )
    assert stats.lines == 1


def test_heartbeat_line_is_counted_and_not_written_to_any_file():
    anchor_files: dict[str, io.StringIO] = {}

    def open_anchor_file(anchor):
        raise AssertionError("a heartbeat line has no anchor to route to")

    stats = relay_udp_listener.ListenerStats()

    relay_udp_listener.handle_line(
        anchor_files,
        "HEARTBEAT,123456",
        host_iso="2026-09-10T00:00:02+00:00",
        host_ns=3000,
        stats=stats,
        open_anchor_file=open_anchor_file,
    )

    assert anchor_files == {}
    assert stats.heartbeats == 1
    assert stats.lines == 0
    assert stats.skipped == 0


def test_unrecognized_line_is_skipped_not_raised():
    anchor_files: dict[str, io.StringIO] = {}

    def open_anchor_file(anchor):
        raise AssertionError("boot noise has no anchor to route to")

    stats = relay_udp_listener.ListenerStats()

    relay_udp_listener.handle_line(
        anchor_files,
        "ets Jul 29 2019 12:21:46",
        host_iso="2026-09-10T00:00:03+00:00",
        host_ns=4000,
        stats=stats,
        open_anchor_file=open_anchor_file,
    )

    assert anchor_files == {}
    assert stats.skipped == 1
    assert stats.lines == 0


def test_truncated_csi_line_with_no_anchor_field_is_skipped_not_raised():
    anchor_files: dict[str, io.StringIO] = {}

    def open_anchor_file(anchor):
        raise AssertionError("no anchor field to route to")

    stats = relay_udp_listener.ListenerStats()

    relay_udp_listener.handle_line(
        anchor_files,
        "CSI,",
        host_iso="2026-09-10T00:00:04+00:00",
        host_ns=5000,
        stats=stats,
        open_anchor_file=open_anchor_file,
    )

    assert anchor_files == {}
    assert stats.skipped == 1
    assert stats.lines == 0
