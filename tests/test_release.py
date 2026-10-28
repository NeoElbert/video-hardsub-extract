"""Offline packaging tests; never import the OCR engine."""
from pathlib import Path
import ast, hashlib, json, sys, tempfile, unittest, zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'video-hardsub-extract/scripts'))
from fetch_release import unpack

class ReleaseTests(unittest.TestCase):
    def test_manifest_and_syntax(self):
        skill = ROOT/'video-hardsub-extract'
        files = sorted(p.relative_to(skill).as_posix() for p in skill.rglob('*') if p.is_file())
        self.assertEqual(files, json.loads((ROOT/'release-files.json').read_text(encoding='utf8')))
        for p in ROOT.rglob('*.py'):
            ast.parse(p.read_text(encoding='utf-8-sig'), filename=str(p))

    def test_unpack_integrity_and_paths(self):
        temp = ROOT/'tools/temp'
        temp.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp) as directory:
            base = Path(directory)
            for index, bad in enumerate([None, '../escape.py', '/escape.py', 'C:/escape.py',
                    'video-hardsub-extract/NUL.txt', 'video-hardsub-extract/../../escape.py']):
                archive = base/f'{index}.zip'
                with zipfile.ZipFile(archive, 'w') as z:
                    for entry in ['SKILL.md','scripts/setup.py','scripts/install_local.py']:
                        z.writestr('video-hardsub-extract/'+entry, '# fixture')
                    if bad: z.writestr(bad, '# invalid')
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                destination = base/f'out-{index}'
                if bad:
                    with self.assertRaises(ValueError): unpack(archive, destination, digest)
                    self.assertFalse(destination.exists())
                else:
                    with self.assertRaises(ValueError): unpack(archive, destination, '0'*64)
                    self.assertFalse(destination.exists())
                    unpack(archive, destination, digest)
                    self.assertEqual((destination/'video-hardsub-extract/SKILL.md').read_text(), '# fixture')

if __name__ == '__main__': unittest.main()
