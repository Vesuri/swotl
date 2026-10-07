"""Independent synthetic hunk records for the read-only size audit."""
from pathlib import Path
import struct
import subprocess
import tempfile
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from hunk_size import inspect


def words(*values):
    return struct.pack(">" + "I" * len(values), *values)


def fixture():
    return (words(0x3f3, 0, 2, 0, 1, 1, 8) +
            words(0x3e9, 1) + bytes.fromhex("4e714e75") +
            words(0x3ec, 1, 1, 0, 0) +
            words(0x3f0, 1) + b"name" + words(0, 0) +
            words(0x3f1, 1, 0, 0x3f2) + words(0x3eb, 8, 0x3f2))


class HunkSize(unittest.TestCase):
    def test_exact_accounting(self):
        result = inspect(fixture())
        self.assertEqual(result["sections"], dict(headers=52, code=4,
                         relocations=20, symbols=20, debug=12))
        self.assertEqual(result["file_bytes"], len(fixture()))
        self.assertEqual(result["symbol_count"], 1)
        self.assertEqual(result["allocated_hunk_bytes"], 36)

    def test_loadable_digest_excludes_symbols_only(self):
        base = fixture()
        renamed = base.replace(b"name", b"word")
        code_changed = base.replace(bytes.fromhex("4e714e75"), bytes.fromhex("4e714e71"))
        self.assertEqual(inspect(base)["loadable_sha256"], inspect(renamed)["loadable_sha256"])
        self.assertNotEqual(inspect(base)["loadable_sha256"], inspect(code_changed)["loadable_sha256"])

    def test_release_check_rejects_symbols_debug_and_changed_code(self):
        original = fixture()
        symbols = words(0x3f0, 1) + b"name" + words(0, 0)
        debug = words(0x3f1, 1, 0)
        stripped = original.replace(symbols, b"").replace(debug, b"")
        with tempfile.TemporaryDirectory() as tmp:
            source, release = Path(tmp) / "source", Path(tmp) / "release"
            source.write_bytes(original)
            for data, passes in ((stripped, True), (original, False),
                                 (original.replace(symbols, b""), False),
                                 (stripped.replace(bytes.fromhex("4e714e75"),
                                                   bytes.fromhex("4e714e71")), False)):
                with self.subTest(passes=passes, data=data):
                    release.write_bytes(data)
                    result = subprocess.run([sys.executable,
                        str(Path(__file__).resolve().parents[1] / "tools/hunk_size.py"),
                        "--release-of", str(source), str(release)], capture_output=True)
                    self.assertEqual(result.returncode == 0, passes, result.stderr)

    def test_truncated_and_missing_end(self):
        for trim in (1, 4, 5, 12, 20):
            with self.subTest(trim=trim), self.assertRaises(ValueError):
                inspect(fixture()[:-trim])

    def test_unknown_record(self):
        with self.assertRaisesRegex(ValueError, "unsupported hunk"):
            inspect(fixture() + words(0x1234))


if __name__ == "__main__":
    unittest.main()
