"""Atomic file and cancellation regressions independent of the GUI event loop."""

import errno
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from unittest.mock import patch

from loglens.output import Cancelled, write_atomic, write_text


class AtomicExportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.path = self.folder / "report.json"
        self.cancel = Event()

    def assert_preserved(self):
        self.assertEqual(self.path.read_bytes(), b"previous")
        self.assertEqual(list(self.folder.iterdir()), [self.path])

    def test_create_and_replace_destination(self):
        for report in ('{"first": true}', '{"second": true}'):
            with self.subTest(report=report):
                write_text(self.path, report, self.cancel)
                self.assertEqual(self.path.read_bytes(), (report + "\n").encode())
                self.assertEqual(list(self.folder.iterdir()), [self.path])

    def test_cancel_before_writing_leaves_new_destination_absent(self):
        self.cancel.set()
        with patch("loglens.output.NamedTemporaryFile") as make_temp:
            with self.assertRaises(Cancelled):
                write_text(self.path, "new", self.cancel)
            make_temp.assert_not_called()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_cancel_during_writing_preserves_original(self):
        self.path.write_bytes(b"previous")

        def chunks():
            yield "first chunk"
            self.cancel.set()
            yield "second chunk"

        with self.assertRaises(Cancelled):
            write_atomic(self.path, chunks(), self.cancel)
        self.assert_preserved()

    def test_cancel_after_final_chunk_before_replacement_preserves_original(self):
        self.path.write_bytes(b"previous")

        def chunks():
            yield "last chunk"
            self.cancel.set()

        with (
            patch("loglens.output.os.replace") as replace,
            self.assertRaises(Cancelled),
        ):
            write_atomic(self.path, chunks(), self.cancel)
            replace.assert_not_called()
        self.assert_preserved()

    def test_cancel_immediately_after_replacement_keeps_success(self):
        self.path.write_bytes(b"previous")
        replace = os.replace

        def cancel_after_replace(tmp, dest):
            replace(tmp, dest)
            self.cancel.set()

        with patch("loglens.output.os.replace", side_effect=cancel_after_replace):
            write_text(self.path, "committed", self.cancel)
        self.assertEqual(self.path.read_bytes(), b"committed\n")
        self.assertEqual(list(self.folder.iterdir()), [self.path])

    def test_permission_denied_at_replacement_preserves_original(self):
        self.path.write_bytes(b"previous")
        with (
            patch("loglens.output.os.replace", side_effect=PermissionError("denied")),
            self.assertRaisesRegex(PermissionError, "denied"),
        ):
            write_text(self.path, "new", self.cancel)
        self.assert_preserved()

    def test_disk_write_failure_cleans_partial_file(self):
        self.path.write_bytes(b"previous")

        @contextmanager
        def failing_temp(**kwargs):
            with tempfile.NamedTemporaryFile(**kwargs) as stream:
                def write_then_fail(chunk):
                    stream.file.write(chunk[:1])
                    raise OSError(errno.ENOSPC, "simulated disk full")

                with patch.object(stream, "write", side_effect=write_then_fail):
                    yield stream

        with (
            patch("loglens.output.NamedTemporaryFile", side_effect=failing_temp),
            self.assertRaisesRegex(OSError, "simulated disk full"),
        ):
            write_text(self.path, "new", self.cancel)
        self.assert_preserved()
