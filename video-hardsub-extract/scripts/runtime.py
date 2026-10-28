"""Keep every task write inside the explicit workspace, before heavy OCR imports.

Portable: no drive letter or personal path is hard-coded. A workspace on the
system drive is allowed but reported once, so the user can see where data lands.
"""
from __future__ import annotations
import os
from pathlib import Path

_WARNED = []


def _refuse(path: Path):
    text = str(path).lower()
    if path == Path(path.anchor or '/'):
        raise ValueError(f'工作目录不能是磁盘根目录：{path}')
    for anchor in ('\\windows', '/windows', '/system', '/usr', '/etc', '/bin', '/sbin', '/lib'):
        if anchor in text:
            raise ValueError(f'工作目录不能位于系统目录：{path}')


def configure(workspace, quiet=False):
    """Point TEMP/HOME/caches at <workspace>/tools and create them.

    Must run before importing paddle/opencv so their caches and temporary files
    never escape the workspace.
    """
    root = Path(workspace).expanduser().resolve()
    _refuse(root)
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        'TEMP': 'tools/temp', 'TMP': 'tools/temp', 'TMPDIR': 'tools/temp',
        'HOME': 'tools/user', 'USERPROFILE': 'tools/user',
        'APPDATA': 'tools/user/AppData/Roaming', 'LOCALAPPDATA': 'tools/user/AppData/Local',
        'XDG_CACHE_HOME': 'tools/cache', 'PIP_CACHE_DIR': 'tools/cache/pip',
        'HF_HOME': 'tools/cache/huggingface', 'TORCH_HOME': 'tools/cache/torch',
        'PADDLE_HOME': 'tools/cache/paddle', 'PADDLE_PDX_CACHE_HOME': 'tools/cache/paddlex',
        'PYTHONUSERBASE': 'tools/user/python', 'MPLCONFIGDIR': 'tools/cache/matplotlib',
        'CUDA_CACHE_PATH': 'tools/cache/cuda',
    }
    for key, relative in paths.items():
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    os.environ.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1',
                      PYTHONIOENCODING='utf-8', PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True',
                      NVIDIA_TF32_OVERRIDE='0')
    if not quiet and os.name == 'nt' and root.drive and root.drive.upper() != 'D:':
        drive = root.drive.upper()
        if drive not in _WARNED:
            _WARNED.append(drive)
            print(f'[提示] 工作目录位于 {drive}：本次所有缓存、临时文件和结果都会写入 {root}。'
                  f'如需与系统盘隔离，请换一个显式 --workspace。', flush=True)
    return root


def task_python(workspace):
    """Return the workspace venv interpreter when it exists, else the current one."""
    root = Path(workspace).expanduser().resolve()
    for rel in ('tools/hardsub-venv/Scripts/python.exe', 'tools/hardsub-venv/bin/python'):
        p = root / rel
        if p.exists():
            return p
    return Path(os.sys.executable)


FONT_CANDIDATES = (
    'C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/msyhl.ttc', 'C:/Windows/Fonts/simhei.ttf',
    'C:/Windows/Fonts/arial.ttf',
    '/System/Library/Fonts/PingFang.ttc', '/System/Library/Fonts/Hiragino Sans GB.ttc',
    '/Library/Fonts/Arial Unicode.ttf',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
)


def find_font():
    """First available TrueType font for review sheets; None means PIL default."""
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None

