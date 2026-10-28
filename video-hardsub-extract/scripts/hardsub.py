"""One entry for a local video or a share link: self-check, preview, cache, SRT/TXT.

    python scripts/hardsub.py <视频或链接> --workspace <目录> [--roi ...]
    python scripts/hardsub.py --check --workspace <目录>
    python scripts/hardsub.py <视频> --workspace <目录> --preview --suggest-roi

Every write stays inside --workspace. Reused results are labelled; a cache hit is
never reported as a fresh OCR run.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from runtime import configure, find_font  # noqa: E402  (must run before OCR imports)

VERSION = '0.2.0-rc9'
VIDEO_EXT = {'.mp4', '.mkv', '.webm', '.mov', '.flv', '.ts', '.avi', '.m4v', '.wmv'}


def _ver(name):
    try:
        return metadata.version(name)
    except Exception:
        return None


def disk_free(path):
    try:
        return shutil.disk_usage(path).free
    except Exception:
        return None


def doctor(root, deep=True):
    """Report what is ready and what is missing; never installs anything."""
    checks = []

    def add(name, ok, detail, required=True):
        checks.append(dict(name=name, ok=bool(ok), detail=detail, required=required))

    add('python', sys.version_info >= (3, 10), f'{sys.version.split()[0]} @ {sys.executable}')
    modules = {}
    for mod, pkg in (('cv2', 'opencv'), ('numpy', 'numpy'), ('PIL', 'pillow'),
                     ('paddle', 'paddlepaddle'), ('paddleocr', 'paddleocr')):
        try:
            __import__(mod)
            version = _ver(pkg) if pkg != 'opencv' else (_ver('opencv-contrib-python') or _ver('opencv-python'))
            modules[pkg] = version
            add(f'import {mod}', True, f'{pkg} {version or "已安装"}')
        except Exception as exc:
            add(f'import {mod}', False, f'缺少 {pkg}：{type(exc).__name__}')
    try:
        __import__('yt_dlp')
        add('import yt_dlp', True, f'yt-dlp {_ver("yt-dlp")}', required=False)
    except Exception:
        add('import yt_dlp', False, '未安装 yt-dlp：仅影响链接下载，本地视频不受影响', required=False)
    opencv_dists = {n: _ver(n) for n in ('opencv-python', 'opencv-contrib-python')}
    add('opencv distribution', any(opencv_dists.values()),
        '、'.join(f'{k} {v}' for k, v in opencv_dists.items() if v) or 'cv2 可导入但未找到发行包元数据')
    ffmpeg = shutil.which('ffmpeg')
    add('ffmpeg', bool(ffmpeg), ffmpeg or '未在 PATH 中；链接下载需要，或用 --ffmpeg-dir 指定', required=False)
    model_dirs = list((root / 'tools/cache/paddlex/official_models').glob('PP-OCRv5_*')) \
        if (root / 'tools/cache/paddlex/official_models').exists() else []
    size = sum(f.stat().st_size for d in model_dirs for f in d.rglob('*') if f.is_file())
    add('models', bool(model_dirs),
        f'{len(model_dirs)} 组已缓存，{size / 1048576:.1f} MB（首次运行会自动下载）' if model_dirs
        else '未缓存：首次运行会按官方源下载约 165 MB', required=False)
    add('review font', bool(find_font()), find_font() or '未找到中文 TrueType 字体，对照图将退回默认字体', required=False)
    add('workspace', os.access(root, os.W_OK), str(root))
    free = disk_free(root)
    add('free space', (free or 0) > 2 * 1024 ** 3, f'{(free or 0) / 1073741824:.1f} GB 可用' if free else '未知')
    cache_rows = 0
    cache_size = 0
    try:
        from cache import summary
        rows = summary(root)
        cache_rows, cache_size = len(rows), sum(r['bytes'] for r in rows)
    except Exception:
        pass
    add('result cache', True, f'{cache_rows} 条，{cache_size / 1048576:.1f} MB', required=False)
    ok = all(c['ok'] for c in checks if c['required'])
    report = dict(status='ready' if ok else 'missing_dependencies', python=sys.executable, workspace=str(root),
                  checks=checks, versions=dict(paddlepaddle=_ver('paddlepaddle'), paddleocr=_ver('paddleocr'),
                                               paddlex=_ver('paddlex'), yt_dlp=_ver('yt-dlp'),
                                               **opencv_dists),
                  skill_version=VERSION)
    return report, ok


def print_doctor(report):
    print(f'技能 {report["skill_version"]} | 工作目录 {report["workspace"]}')
    for item in report['checks']:
        mark = 'OK  ' if item['ok'] else ('缺失' if item['required'] else '提示')
        print(f'  [{mark}] {item["name"]}: {item["detail"]}')
    if report['status'] == 'ready':
        print('环境就绪。安装依赖请用 scripts/setup.ps1（Windows）或 pip install -r scripts/requirements.txt。')
    else:
        print('缺少必需依赖：先安装依赖再运行；本技能不会自动把包装进系统盘。')


def params_of(args):
    return dict(roi=','.join(f'{v:g}' for v in args.roi) if isinstance(args.roi, tuple) else str(args.roi),
                start=float(args.start), end=('full' if args.end is None else float(args.end)),
                sample_fps=float(args.sample_fps), mode=args.mode, device=args.device,
                min_score=float(args.min_score), min_text_height=float(args.min_text_height),
                white_text=bool(args.white_text), white_yellow_text=bool(args.white_yellow_text),
                pixel_reuse=not args.no_pixel_reuse)


def parse_roi(text):
    from extract import _parse_roi
    return _parse_roi(text)


def main():
    ap = argparse.ArgumentParser(description='视频画面字幕提取：本地视频或分享链接 → SRT/TXT（画面 OCR，不是语音转写）。')
    ap.add_argument('target', nargs='?', help='本地视频文件或视频分享链接')
    ap.add_argument('--workspace', required=True, type=Path, help='工作目录：下载、缓存、模型与结果都写入这里')
    ap.add_argument('--check', action='store_true', help='只做环境自检')
    ap.add_argument('--preview', action='store_true', help='只导出多时点预览图，用来看字幕区域')
    ap.add_argument('--suggest-roi', action='store_true', help='预览时附一个建议字幕区域（会加载检测模型）')
    ap.add_argument('--roi', default='0,0,1,1', help='识别区域 x0,y0,x1,y1（0~1）；默认全画面，底部及其他文字分区记录')
    ap.add_argument('--sample-fps', type=float, default=3, help='每秒识别帧数，默认 3；闪现字幕可用 0（逐帧）')
    ap.add_argument('--start', type=float, default=0)
    ap.add_argument('--end', type=float)
    ap.add_argument('--mode', choices=['mobile', 'server'], default='server')
    ap.add_argument('--device', default='cpu')
    ap.add_argument('--min-score', type=float, default=.75)
    ap.add_argument('--min-text-height', type=float, default=0, help='按原画面高度比例排除过小文字；默认不过滤')
    ap.add_argument('--white-text', action='store_true')
    ap.add_argument('--white-yellow-text', action='store_true')
    ap.add_argument('--model-dir', type=Path)
    ap.add_argument('--model-cache-dir', type=Path, help='批量工具共用的模型缓存目录；各视频结果仍独立保存')
    ap.add_argument('--paddle-runtime-dir', type=Path)
    ap.add_argument('--ffmpeg-dir', type=Path, help='FFmpeg bin 目录；省略则使用 PATH')
    ap.add_argument('--node', type=Path, help='Node 可执行文件；个别站点需要')
    ap.add_argument('--cookies', type=Path, help='显式提供的 Netscape cookie 文件；不自动导出浏览器凭据')
    ap.add_argument('--refresh', action='store_true', help='忽略已有缓存，强制重新识别（仍会更新缓存）')
    ap.add_argument('--no-cache', action='store_true', help='本次既不读也不写结果缓存')
    ap.add_argument('--no-pixel-reuse', action='store_true', help='关闭完全相同裁剪像素的逐帧复用')
    ap.add_argument('--cache-info', action='store_true', help='列出已有缓存条目')
    a = ap.parse_args()
    begin = time.monotonic()
    root = configure(a.workspace, quiet=False)
    shared_models = None
    if a.model_cache_dir:
        model_cache = a.model_cache_dir.resolve()
        model_cache.mkdir(parents=True, exist_ok=True)
        os.environ['PADDLE_PDX_CACHE_HOME'] = str(model_cache)
        shared_models = model_cache / 'official_models'
        if not a.model_dir and all((shared_models / f'PP-OCRv5_{a.mode}_{part}').is_dir() for part in ('det','rec')):
            a.model_dir = shared_models

    if a.check:
        report, ok = doctor(root)
        print_doctor(report)
        print(json.dumps(report, ensure_ascii=False))
        raise SystemExit(0 if ok else 2)

    if a.cache_info:
        from cache import summary
        rows = summary(root)
        for row in rows:
            print(f'{row["key"][:12]}  cues={row["cues"]}  hits={row["hits"]}  '
                  f'{row["bytes"] / 1048576:.1f} MB  {row["source"]}')
        print(json.dumps(dict(status='ok', entries=len(rows), items=rows), ensure_ascii=False))
        return

    if not a.target:
        ap.error('需要本地视频路径或分享链接')

    roi = parse_roi(a.roi)
    timings = {}
    download_info = None
    # Share text ("复制打开抖音… https://v.douyin.com/xxx/") is a link, not a path.
    link = re.search(r'https?://[^\s<>"\u00a0]+', a.target)
    is_url = bool(link)
    if is_url:
        from download import fetch, normalize
        stage = time.monotonic()
        try:
            download_info = fetch(normalize(a.target), root, a.ffmpeg_dir, a.node, platform_subs=False,
                                  cookies=a.cookies)
        except ValueError as exc:
            print(json.dumps(dict(status='download_failed', error=str(exc), timings=timings),
                             ensure_ascii=False))
            raise SystemExit(3)
        timings['download'] = round(time.monotonic() - stage, 3)
        if download_info['status'] != 'downloaded' or not download_info.get('videos'):
            payload = dict(status='download_failed', error=download_info.get('error'),
                           output=download_info.get('output'), timings=timings,
                           hint='链接需要登录/验证码/新 Cookie 时按提示由用户处理；不要把别的视频当作目标结果。')
            print(json.dumps(payload, ensure_ascii=False))
            raise SystemExit(3)
        video = Path(download_info['videos'][0]['path'])
    else:
        video = Path(a.target).expanduser()
        if not video.exists():
            raise SystemExit(f'找不到视频文件：{video}')
        if video.suffix.lower() not in VIDEO_EXT:
            print(f'[提示] 扩展名 {video.suffix} 不是常见视频后缀，仍按视频尝试解码。', flush=True)
        video = video.resolve()
        download_info = None

    if a.preview:
        from extract import preview
        info = preview(video, root, roi, a.start, a.end, suggest=a.suggest_roi, mode=a.mode,
                       device=a.device, model_dir=a.model_dir, paddle_runtime_dir=a.paddle_runtime_dir)
        info.update(video=str(video), timings=dict(total=round(time.monotonic() - begin, 3)))
        print(json.dumps(info, ensure_ascii=False))
        return

    import cache as cache_mod
    from extract import run as ocr_run, content_sha256

    stage = time.monotonic()
    digest = content_sha256(video)
    timings['content_hash'] = round(time.monotonic() - stage, 3)
    params = params_of(a)
    runtime_dir = a.paddle_runtime_dir
    if runtime_dir is None and (root / 'tools/paddle-cpu-compat/paddle/__init__.py').exists():
        runtime_dir = root / 'tools/paddle-cpu-compat'
    stage = time.monotonic()
    model = cache_mod.model_identity(root, a.mode, a.model_dir)
    runtime = cache_mod.runtime_identity(runtime_dir)
    timings['identity'] = round(time.monotonic() - stage, 3)
    key, payload = cache_mod.build_key(digest, params, SCRIPT_DIR, a.mode, model, runtime)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')

    if not a.no_cache and not a.refresh:
        stage = time.monotonic()
        hit, entry, reason = cache_mod.lookup(root, key, model)
        timings['cache_lookup'] = round(time.monotonic() - stage, 3)
        if hit:
            out = root / 'output' / 'hardsub' / (stamp + '_' + key[:8] + '_cached')
            cache_mod.restore(root, key, out, entry)
            entry = cache_mod.touch_hits(root, key, entry)
            semantics = entry.get('semantics') or {}
            manifest = {k: v for k, v in semantics.items()}
            manifest.update(source=str(video), skill_version=VERSION, output=str(out), workspace=str(root),
                            created=datetime.now(timezone.utc).isoformat(),
                            cache=dict(hit=True, key=key, reason=reason, entry_created=entry.get('created'),
                                       hits=entry.get('hits'), model_identity=model,
                                       runtime_identity=runtime,
                                       original_run_seconds=(entry.get('seconds') or {}).get('total')),
                            note='本次没有重新识别：结果来自缓存（视频内容、区域、采样率、参数、模型文件内容、'
                                 '运行库与代码版本一致）。需要重新识别请加 --refresh。')
            (out / 'run.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            result = dict(status=manifest['status'],
                          cache=dict(hit=True, key=key, reason=reason, entry_created=entry.get('created'),
                                     hits=entry.get('hits')),
                          video=str(video), output=str(out), cues=manifest.get('cues'),
                          frames=manifest.get('frames'),
                          files={'srt': str(out / '字幕.srt'), 'txt': str(out / '文字稿.txt'),
                                 'cues': str(out / 'cues.json')},
                          timings=dict(**timings, total=round(time.monotonic() - begin, 3)))
            if download_info:
                result['download'] = dict(output=download_info.get('output'), title=download_info.get('title'),
                                          duration=download_info.get('duration'))
            print(json.dumps(result, ensure_ascii=False))
            return

    out = root / 'output' / 'hardsub' / (stamp + '_' + key[:8])
    stage = time.monotonic()
    manifest = ocr_run(video, root, roi, a.sample_fps, a.start, a.end, a.mode, a.device, a.min_score,
                       a.min_text_height, a.white_text, a.white_yellow_text, a.model_dir,
                       a.paddle_runtime_dir, out=out, pixel_reuse=not a.no_pixel_reuse,
                       log=lambda m: print(m, flush=True))
    timings['ocr'] = round(time.monotonic() - stage, 3)
    stored = None
    stored_key = None
    if not a.no_cache:
        # The first run may have just downloaded the models, which changes their
        # content identity: store under the key a later call will compute.
        stage = time.monotonic()
        model_after = cache_mod.model_identity(root, a.mode, a.model_dir or shared_models)
        key_after, payload_after = cache_mod.build_key(digest, params, SCRIPT_DIR, a.mode, model_after, runtime)
        timings['identity_post'] = round(time.monotonic() - stage, 3)
        try:
            stored = cache_mod.store(root, key_after, out, payload_after, manifest)
            stored_key = key_after
        except Exception as exc:
            print(f'[提示] 结果已产出，但写入缓存失败：{type(exc).__name__}: {exc}', file=sys.stderr)
    manifest.update(cache=dict(hit=False, key=stored_key or key, stored=bool(stored),
                               reason='本次执行了完整识别' if not a.no_cache else '本次禁用了缓存',
                               model_identity=model,
                               key_before_run=key if stored_key and stored_key != key else None))
    manifest.update(output=str(out))
    (out / 'run.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    result = dict(status=manifest['status'],
                  cache=dict(hit=False, key=stored_key or key, stored=bool(stored)),
                  video=str(video), output=str(out), cues=manifest.get('cues'), frames=manifest.get('frames'),
                  files={'srt': str(out / '字幕.srt'), 'txt': str(out / '文字稿.txt'),
                         'cues': str(out / 'cues.json')},
                  timings=dict(**timings, engine_init=manifest.get('engine_init_seconds'),
                               ocr_only=manifest.get('ocr_seconds'),
                               pixel_reuse_frames=manifest.get('pixel_reuse_frames'),
                               total=round(time.monotonic() - begin, 3)))
    if download_info:
        result['download'] = dict(output=download_info.get('output'), title=download_info.get('title'),
                                  duration=download_info.get('duration'))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps(dict(status='error', error=f'{type(exc).__name__}: {exc}',
                              trace=traceback.format_exc(limit=2)), ensure_ascii=False))
        raise SystemExit(1)
