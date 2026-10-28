"""Build the Skill archive from an explicit source manifest, without OCR."""
from pathlib import Path
import argparse, hashlib, json, zipfile

ROOT = Path(__file__).resolve().parents[1]

def build(output):
    manifest = json.loads((ROOT / 'release-files.json').read_text(encoding='utf-8'))
    skill = ROOT / 'video-hardsub-extract'
    actual = sorted(p.relative_to(skill).as_posix() for p in skill.rglob('*') if p.is_file())
    if actual != manifest:
        raise ValueError('Skill files differ from release-files.json; review changes first')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = output / 'video-hardsub-extract-0.2.1.zip'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in manifest:
            info = zipfile.ZipInfo('video-hardsub-extract/' + name, (2026,10,28,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (skill/name).read_bytes())
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return {'file':target.name, 'sha256':digest, 'files':len(manifest)}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(build(parser.parse_args().output), indent=2))
