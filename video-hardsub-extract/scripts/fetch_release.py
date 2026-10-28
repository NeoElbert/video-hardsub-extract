"""Download and verify a fixed GitHub release; never execute downloaded code."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import stat
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from runtime import configure
from library import storage_root


def unpack(archive, destination, expected_sha256):
    archive, destination = Path(archive), Path(destination)
    expected_sha256 = expected_sha256.lower()
    if not re.fullmatch(r'[a-f0-9]{64}', expected_sha256):
        raise ValueError('需要发布方提供的完整 SHA256')
    with archive.open('rb') as source:
        hasher = hashlib.sha256()
        for block in iter(lambda: source.read(1024 * 1024), b''):
            hasher.update(block)
        digest = hasher.hexdigest()
    if digest != expected_sha256:
        raise ValueError('SHA256 不匹配：保留下载供检查，不解压、不执行')
    if destination.exists():
        raise ValueError('版本目录已存在，请核验后复用或选择新目录；不覆盖已有文件')
    with zipfile.ZipFile(archive) as z:
        names = set()
        for item in z.infolist():
            raw = item.filename
            path = PurePosixPath(raw)
            if (not raw or '\\' in raw or ':' in raw or path.is_absolute()
                    or '..' in path.parts or not path.parts
                    or path.parts[0] != 'video-hardsub-extract'
                    or any(part.endswith((' ', '.')) for part in path.parts)
                    or any(re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part) for part in path.parts)
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError('压缩包路径不符合技能包边界')
            key = raw.rstrip('/').casefold()
            if key in names:
                raise ValueError('压缩包包含重复路径')
            names.add(key)
        required = {'video-hardsub-extract/skill.md',
                    'video-hardsub-extract/scripts/setup.py',
                    'video-hardsub-extract/scripts/install_local.py'}
        if not required <= names:
            raise ValueError('压缩包缺少技能或安装入口')
        destination.mkdir(parents=True)
        z.extractall(destination)
    return destination / 'video-hardsub-extract'


def main():
    p = argparse.ArgumentParser(description='下载固定 GitHub 发布包并校验；不会自动安装或运行')
    p.add_argument('--workspace', required=True, type=Path)
    p.add_argument('--repository', required=True, help='发布方核实的 owner/repo')
    p.add_argument('--tag', required=True)
    p.add_argument('--asset', required=True)
    p.add_argument('--sha256', required=True)
    a = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', a.repository):
        raise ValueError('仓库必须为 owner/repo')
    if any(part in ('.', '..') for part in a.repository.split('/')):
        raise ValueError('仓库路径无效')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', a.tag) or a.tag.lower() in ('latest', 'main', 'master', '.', '..'):
        raise ValueError('必须指定固定发布 tag')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+\.zip', a.asset):
        raise ValueError('资产必须为 ZIP 文件名')
    if not re.fullmatch(r'[a-fA-F0-9]{64}', a.sha256):
        raise ValueError('需要完整 SHA256')
    root = configure(storage_root(a.workspace), quiet=True)
    folder = root / 'tools/downloads' / a.repository / a.tag
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / a.asset
    url = f'https://github.com/{a.repository}/releases/download/{urllib.parse.quote(a.tag)}/{a.asset}'
    # Exclusive creation preserves previous downloads and avoids silent replacement.
    with archive.open('xb') as out:
        with urllib.request.urlopen(url, timeout=60) as response:
            while block := response.read(1024 * 1024):
                out.write(block)
    skill = unpack(archive, folder / 'verified', a.sha256)
    print(json.dumps(dict(status='verified', source=url, skill=str(skill),
                         sha256=a.sha256.lower(), executed=False), ensure_ascii=False))


if __name__ == '__main__':
    main()
