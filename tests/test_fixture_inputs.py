"""Filesystem fixture declarations must match the original capture exactly."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import fixture_inputs as F


def rejected(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError('invalid fixture input accepted')


def check(sabotage=False):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'ac').mkdir()
        a, b = root / 'ac/specs.spc', root / 'ac/other.spc'
        a.write_bytes(b'original'); b.write_bytes(b'keep')
        paths = F.missing_files('ac\\specs.spc')
        assert paths == ('AC/SPECS.SPC',)
        for invalid in ('../x', '/x', 'a//b', 'a/./b', 'a a', 'a A', 'a:b'):
            rejected(lambda: F.missing_files(invalid))
        F.record(root, ())
        F.verify(root, ())
        assert not (root / 'fixture-inputs.json').exists()
        rejected(lambda: F.stage_missing(root, paths + ('AC/ABSENT.SPC',)))
        assert a.read_bytes() == b'original', 'invalid request partially applied'
        rejected(lambda: F.verify(root, paths))
        F.record(root, paths)
        F.verify(root, paths)
        rejected(lambda: F.verify(root, ()))
        rejected(lambda: F.verify(root, ('AC/OTHER.SPC',)))
        F.stage_missing(root, ('AC/OTHER.SPC',) if sabotage else paths)
        assert not a.exists() and b.read_bytes() == b'keep', 'wrong fixture file removed'
        rejected(lambda: F.stage_missing(root, paths))
        (root / 'alias').symlink_to(root / 'ac', target_is_directory=True)
        rejected(lambda: F.stage_missing(root, ('ALIAS/OTHER.SPC',)))
        assert b.read_bytes() == b'keep'
    print('fixture inputs: canonical paths, exact manifest, absent file and retained neighbour pass')


if __name__ == '__main__':
    check()
    if '--sabotage' in sys.argv:
        try:
            check(True)
        except AssertionError as e:
            assert str(e) == 'wrong fixture file removed'
        else:
            raise AssertionError('wrong missing file escaped')
        print('sabotage: wrong missing file caught')
