"""Full-result cache for hard-subtitle OCR.

A cache entry is reused only when everything that can change the recognition
result is identical: the video bytes (SHA-256), the subtitle region, sampling
rate, time range, model/mode/device, thresholds, colour isolation, the actual
model file contents, the runtime that performs the inference, and the OCR code
itself. Reuse also requires the complete artifact set to match its recorded
hashes, so a half-written, trimmed or edited result is never served.
"""
from __future__ import annotations
import gzip
import hashlib
import json
import shutil
import time
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

CACHE_VERSION = 'hardsub-cache-3'
# Every one of these must exist and match, otherwise the entry is not usable.
REQUIRED_ARTIFACTS = ('字幕.srt', '文字稿.txt', '原始文字稿.txt', 'readable.json', 'timeline.json', 'cues.json', 'frames.jsonl.gz')
# Semantics of the original finished run, replayed into a cache-hit run.json.
SEMANTIC_FIELDS = ('status', 'duration', 'source_fps', 'roi', 'range', 'sample_fps', 'model', 'device',
                   'min_score', 'min_text_height', 'white_text', 'white_yellow_text', 'cues', 'frames',
                   'time_resolution_seconds', 'paddle_version', 'pixel_reuse_frames', 'frame_size', 'timeline_events', 'nvidia_tf32_override')

DISTRIBUTIONS = ('paddlepaddle', 'paddleocr', 'paddlex', 'opencv-python', 'opencv-contrib-python',
                 'numpy', 'pillow', 'yt-dlp')


def _pkg_version(name):
    try:
        return metadata.version(name)
    except Exception:
        return None


def engine_versions():
    """Installed distribution versions; None means 'not installed via this metadata'."""
    return {name: _pkg_version(name) for name in DISTRIBUTIONS}


def code_digest(scripts_dir):
    """Hash the implementation that produces results, not just one file."""
    digest = hashlib.sha256()
    for name in ('extract.py', 'readable.py', 'timeline.py', 'cache.py', 'hardsub.py', 'runtime.py'):
        path = Path(scripts_dir) / name
        digest.update(name.encode())
        digest.update(path.read_bytes() if path.exists() else b'')
    return digest.hexdigest()


def tree_digest(folders):
    """Content digest of model files (path + bytes). Never size or mtime alone."""
    digest = hashlib.sha256()
    found = False
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            return None
        digest.update(folder.name.encode())
        for path in sorted(p for p in folder.rglob('*') if p.is_file()):
            found = True
            digest.update(path.relative_to(folder).as_posix().encode())
            with open(path, 'rb') as handle:
                for block in iter(lambda: handle.read(1 << 20), b''):
                    digest.update(block)
    return digest.hexdigest() if found else None


def model_identity(root, mode, model_dir=None):
    """Model identity from actual file contents, including PaddleX's own cache."""
    if model_dir:
        base, source = Path(model_dir), 'explicit --model-dir'
    else:
        base, source = Path(root) / 'tools/cache/paddlex/official_models', 'paddlex official cache'
    folders = [base / f'PP-OCRv5_{mode}_det_infer', base / f'PP-OCRv5_{mode}_rec_infer']
    if not all(f.is_dir() for f in folders):
        # PaddleX may store the weights without the _infer suffix.
        folders = [base / f'PP-OCRv5_{mode}_det', base / f'PP-OCRv5_{mode}_rec']
    digest = tree_digest(folders)
    return dict(source=source, path=str(base), digest=digest,
                name=f'PP-OCRv5_{mode}', ready=digest is not None)


def runtime_identity(runtime_dir=None):
    """Inference runtime actually in effect (may shadow the installed package)."""
    if not runtime_dir:
        return dict(path='installed environment', digest=None)
    path = Path(runtime_dir)
    return dict(path=str(path), digest=tree_digest([path]))


def build_key(video_sha256, params, scripts_dir, mode, model=None, runtime=None):
    payload = dict(
        cache_version=CACHE_VERSION,
        content_sha256=video_sha256,
        params=params,
        model=model,
        runtime=runtime or dict(path='installed environment', digest=None),
        engine=engine_versions(),
        code=code_digest(scripts_dir),
    )
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest(), payload


def entry_dir(root, key):
    return Path(root) / 'tools' / 'cache' / 'hardsub' / key


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _lookup_checked(root, key, model=None):
    """Return (ok, entry, reason). Never returns a partially valid entry."""
    if model is not None and not model.get('ready'):
        return False, None, '未命中：模型文件尚未缓存，无法确认模型内容身份'
    folder = entry_dir(root, key)
    manifest_path = folder / 'manifest.json'
    if not manifest_path.exists():
        return False, None, '未命中：无该缓存键'
    try:
        entry = json.loads(manifest_path.read_text(encoding='utf-8'))
    except Exception as exc:
        return False, None, f'未命中：缓存清单损坏（{type(exc).__name__}）'
    if entry.get('cache_version') != CACHE_VERSION:
        return False, None, '未命中：缓存格式版本不同'
    if entry.get('status') not in ('complete', 'no_text_detected'):
        return False, None, '未命中：缓存状态不完整'
    artifacts = entry.get('artifacts') or {}
    missing = [name for name in REQUIRED_ARTIFACTS if name not in artifacts]
    if missing:
        return False, None, '未命中：清单缺少必需产物 ' + '、'.join(missing)
    for name in REQUIRED_ARTIFACTS:
        meta = artifacts.get(name) or {}
        path = folder / 'result' / name
        if not path.exists():
            return False, None, f'未命中：缺少产物 {name}'
        if 'bytes' not in meta or 'sha256' not in meta:
            return False, None, f'未命中：产物清单不完整 {name}'
        if path.stat().st_size != meta['bytes']:
            return False, None, f'未命中：产物大小不符 {name}'
        if file_sha256(path) != meta['sha256']:
            return False, None, f'未命中：产物哈希不符 {name}'
    try:
        cues = json.loads((folder / 'result' / 'cues.json').read_text(encoding='utf-8'))
        with gzip.open(folder / 'result' / 'frames.jsonl.gz', 'rb') as handle:
            first = handle.readline()
        json.loads(first.decode('utf-8')) if first.strip() else None
    except Exception:
        return False, None, '未命中：产物无法解析（形状异常）'
    if not isinstance(cues, list) or len(cues) != entry.get('cues'):
        return False, None, '未命中：字幕条数与清单不一致'
    semantics = entry.get('semantics') or {}
    if 'range' not in semantics or 'roi' not in semantics:
        return False, None, '未命中：缺少原运行语义字段'
    return True, entry, '命中'


def store(root, key, source_out, payload, meta, hits=0):
    """Copy a finished run into the cache atomically."""
    folder = entry_dir(root, key)
    folder.parent.mkdir(parents=True, exist_ok=True)
    staging = folder.parent / f'.{key}.tmp{int(time.time() * 1000)}'
    if staging.exists():
        shutil.rmtree(staging)
    result = staging / 'result'
    result.mkdir(parents=True)
    artifacts = {}
    for name in REQUIRED_ARTIFACTS:
        if name == 'frames.jsonl.gz':
            src = Path(source_out) / 'frames.jsonl'
            if not src.exists():
                shutil.rmtree(staging, ignore_errors=True)
                raise RuntimeError('无法缓存缺少的逐帧证据 frames.jsonl')
            dst = result / name
            with gzip.open(dst, 'wb', compresslevel=6) as handle, open(src, 'rb') as data:
                shutil.copyfileobj(data, handle)
        else:
            src = Path(source_out) / name
            if not src.exists():
                shutil.rmtree(staging, ignore_errors=True)
                raise RuntimeError(f'无法缓存缺少的产物：{name}')
            dst = result / name
            shutil.copy2(src, dst)
        artifacts[name] = dict(bytes=dst.stat().st_size, sha256=file_sha256(dst))
    entry = dict(key=key, cache_version=CACHE_VERSION, payload=payload, status=meta.get('status'),
                 cues=meta.get('cues'), frames=meta.get('frames'), duration=meta.get('duration'),
                 created=datetime.now(timezone.utc).isoformat(), hits=hits, artifacts=artifacts,
                 semantics={k: meta.get(k) for k in SEMANTIC_FIELDS},
                 seconds=dict(total=meta.get('seconds'), engine_init=meta.get('engine_init_seconds'),
                              ocr=meta.get('ocr_seconds')),
                 source_name=Path(meta.get('source', '')).name)
    (staging / 'manifest.json').write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding='utf-8')
    if folder.exists():
        shutil.rmtree(folder)
    staging.rename(folder)
    return entry


def restore(root, key, out_dir, entry):
    """Materialise a cached result as a normal run directory."""
    folder = entry_dir(root, key)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_ARTIFACTS:
        if name == 'frames.jsonl.gz':
            with gzip.open(folder / 'result' / name, 'rb') as src, open(out_dir / 'frames.jsonl', 'wb') as dst:
                shutil.copyfileobj(src, dst)
        else:
            shutil.copy2(folder / 'result' / name, out_dir / name)
    return out_dir


def touch_hits(root, key, entry):
    """Record how often a cached result was reused (reporting only)."""
    entry = dict(entry)
    entry['hits'] = int(entry.get('hits') or 0) + 1
    entry['last_hit'] = datetime.now(timezone.utc).isoformat()
    path = entry_dir(root, key) / 'manifest.json'
    try:
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass
    return entry


def summary(root):
    base = Path(root) / 'tools' / 'cache' / 'hardsub'
    rows = []
    if base.exists():
        for folder in sorted(base.iterdir()):
            manifest = folder / 'manifest.json'
            if not manifest.exists():
                continue
            try:
                entry = json.loads(manifest.read_text(encoding='utf-8'))
            except Exception:
                continue
            size = sum(f.stat().st_size for f in folder.rglob('*') if f.is_file())
            rows.append(dict(key=folder.name, cues=entry.get('cues'), hits=entry.get('hits'),
                             bytes=size, created=entry.get('created'), source=entry.get('source_name')))
    return rows


def lookup(root, key, model=None):
    """A damaged cache is a miss, never a fatal extraction error."""
    try:
        return _lookup_checked(root, key, model)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, EOFError):
        return False, None, '未命中：缓存结构损坏或读取失败，将重新识别'
