"""DOS read provenance: overwritten files must use bytes captured at the read."""
import argparse
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import load_image as L


class ReadData(unittest.TestCase):
    def check_reads(self, lines, payload=b'X', captured=b'ABCDE'):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'trace').mkdir()
            if captured is not None:
                (root / 'trace/reads.bin').write_bytes(captured)
            (root / 'root').mkdir()
            (root / 'ref').mkdir()
            (root / 'root/RP2.TMP').write_bytes(payload)
            events = root / 'trace/events.csv'
            events.write_text('icount,kind,module,offset,detail\n' + lines)
            return L.dos_reads(events, 20, root / 'ref')

    def test_rewrite_overlap_and_cutoff(self):
        self.assertEqual(self.check_reads(
            '1,read,-,0,RP2.TMP linear=0x100 pos=0x20 got=3 data=0\n'
            '2,read,-,0,RP2.TMP linear=0x101 pos=0 got=1 data=3\n'
            '21,read,-,0,RP2.TMP linear=0x100 pos=0 got=1 data=4\n'),
            {0x100: 65, 0x101: 68, 0x102: 67})

    def test_empty_read(self):
        self.assertEqual(self.check_reads(
            '1,read,-,0,RP2.TMP linear=0x100 pos=0xffff got=0 data=5\n'), {})

    def test_malformed_payload_fails(self):
        for data in ('-1', '4', 'bad'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.check_reads(f'1,read,-,0,RP2.TMP linear=0x100 pos=0 got=2 data={data}\n')

    def test_new_capture_missing_offset_fails(self):
        with self.assertRaises(ValueError):
            self.check_reads('1,read,-,0,RP2.TMP linear=0x100 pos=0 got=1\n')

    def test_legacy_capture(self):
        self.assertEqual(self.check_reads(
            '1,read,-,0,RP2.TMP linear=0x100 pos=0x1 got=2\n', b'ABC', captured=None),
            {0x100: 66, 0x101: 67})

    def test_legacy_short_file_fails(self):
        with self.assertRaises(ValueError):
            self.check_reads('1,read,-,0,RP2.TMP linear=0x100 pos=0 got=2\n', captured=None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sabotage', action='store_true')
    args = parser.parse_args()
    if args.sabotage:
        original = L.dos_reads
        def broken(*args):
            result = original(*args)
            return {address: 0 for address in result}
        with patch.object(L, 'dos_reads', broken):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(
                unittest.TestSuite([ReadData('test_rewrite_overlap_and_cutoff')]))
        assert len(result.failures) == 1 and not result.errors, 'lost DOS read bytes escaped detection'
        print('sabotage: corrupted DOS read payload caught')
    else:
        unittest.main(argv=[sys.argv[0]])
