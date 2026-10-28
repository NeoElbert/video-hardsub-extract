"""Platform transport is separate from visual OCR; yt-dlp is not a support guarantee.

Exposed as `fetch()` so the unified entry can download and OCR inside one
process (one model initialisation) instead of paying interpreter start-up twice.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit, parse_qs
from runtime import configure


def normalize(value):
    found = re.search(r'https?://[^\s<>"\u00a0]+', value)
    if not found:
        raise ValueError('需要视频 HTTP(S) 链接。')
    url = found.group().rstrip('，。；）)]}')
    p = urlsplit(url)
    if p.username or p.password:
        raise ValueError('不接受内嵌账号密码的链接。')
    host = (p.hostname or '').lower()
    if host == 'douyin.com' or host.endswith('.douyin.com'):
        vid = re.search(r'/video/(\d+)', p.path)
        mid = parse_qs(p.query).get('modal_id', [''])[0]
        if vid or mid.isdigit():
            url = 'https://www.douyin.com/video/' + (vid.group(1) if vid else mid)
    return url


class Log:
    def __init__(self):
        self.messages = []

    def debug(self, s):
        pass

    def warning(self, s):
        self.messages.append(self.clean(s))

    def error(self, s):
        self.messages.append(self.clean(s))

    @staticmethod
    def clean(s):
        return re.sub(r'https?://\S+', '[URL]', str(s))


def ffmpeg_paths(ffmpeg_dir=None):
    """Accept an explicit ffmpeg directory or rely on PATH."""
    if ffmpeg_dir:
        base = Path(ffmpeg_dir)
        exe = base / ('ffmpeg.exe' if (base / 'ffmpeg.exe').exists() else 'ffmpeg')
        if not exe.exists():
            raise ValueError(f'指定的 FFmpeg 目录里没有 ffmpeg 可执行文件：{base}')
        probe = base / 'ffprobe.exe'
        return exe, (probe if probe.exists() else Path(shutil.which('ffprobe') or 'ffprobe')), base
    exe = shutil.which('ffmpeg')
    if not exe:
        raise ValueError('未找到 FFmpeg。请把 FFmpeg 的 bin 目录加入 PATH，或用 --ffmpeg-dir 指定。')
    probe = shutil.which('ffprobe') or 'ffprobe'
    return Path(exe), Path(probe), Path(exe).parent


def fetch(url, root, ffmpeg_dir=None, node=None, probe=False, platform_subs=False, cookies=None, log=print):
    """Download one URL; returns the result dict (also written to result.json)."""
    from yt_dlp import YoutubeDL
    root = Path(root)
    url = normalize(url)
    _, ffprobe, ffmpeg_location = ffmpeg_paths(ffmpeg_dir)
    runid = datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '_' + hashlib.sha256(url.encode()).hexdigest()[:8]
    out = root / 'output' / 'platform-download' / runid
    out.mkdir(parents=True)
    sink = Log()
    opts = dict(paths={'home': str(out), 'temp': str(root / 'tools/temp' / runid)},
                outtmpl={'default': '%(extractor)s_%(id)s.%(ext)s'},
                cachedir=str(root / 'tools/cache/yt-dlp'), ffmpeg_location=str(ffmpeg_location),
                noplaylist=True, quiet=True, logger=sink, format='bv*+ba/b',
                writesubtitles=platform_subs, writeautomaticsub=platform_subs,
                subtitleslangs=['all', '-live_chat'],
                socket_timeout=25, retries=2, extractor_retries=2)
    if node:
        opts['js_runtimes'] = {'node': {'path': str(node)}}
    if cookies:
        opts['cookiefile'] = str(Path(cookies).resolve(strict=True))
    result = dict(source=url, workspace=str(root), created=datetime.now(timezone.utc).isoformat(), status='started')
    try:
        host = urlsplit(url).hostname or ''
        ks = None
        if host == 'kuaishou.com' or host.endswith('.kuaishou.com'):
            from kuaishou import resolve
            ks = resolve(url)
            opts['http_headers'] = ks['headers']
            opts['outtmpl'] = {'default': 'kuaishou_' + ks['id'] + '.%(ext)s'}
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(ks['urls'][0] if ks else url, download=not probe)
        if ks:
            info.update({k: ks[k] for k in ('id', 'title', 'extractor')})
            result['numeric_id'] = ks['numeric_id']
        result.update(status='probe_ok' if probe else 'downloaded', id=info.get('id'), title=info.get('title'),
                      extractor=info.get('extractor'), duration=info.get('duration'),
                      subtitle_languages=list((info.get('subtitles') or {}).keys()),
                      automatic_caption_languages=list((info.get('automatic_captions') or {}).keys()))
        videos = []
        if not probe:
            for path in out.iterdir():
                if path.suffix.lower() not in ('.mp4', '.mkv', '.webm', '.mov', '.flv'):
                    continue
                checked = subprocess.run([str(ffprobe), '-v', 'error', '-show_entries',
                                          'format=duration:stream=codec_type,width,height', '-of', 'json', str(path)],
                                         capture_output=True, cwd=root)
                if checked.returncode:
                    raise RuntimeError('下载文件无法通过 ffprobe 验证。')
                meta = json.loads(checked.stdout)
                if not any(s.get('codec_type') == 'video' for s in meta.get('streams', [])):
                    raise RuntimeError('下载文件没有视频轨。')
                videos.append(dict(path=str(path), bytes=path.stat().st_size, media=meta))
            if not videos:
                raise RuntimeError('未生成可验证的视频文件。')
        result['videos'] = videos
    except Exception as e:
        result.update(status='failed', error=Log.clean(str(e)), error_type=type(e).__name__)
    result['messages'] = sink.messages
    result['output'] = str(out)
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    p = argparse.ArgumentParser(description='下载视频并独立保留平台字幕；成功后可运行 extract.py 做画面识别。')
    p.add_argument('url')
    p.add_argument('--workspace', type=Path, required=True)
    p.add_argument('--ffmpeg-dir', type=Path, help='FFmpeg 的 bin 目录；省略则使用 PATH')
    p.add_argument('--node', type=Path)
    p.add_argument('--probe', action='store_true')
    p.add_argument('--platform-subs', action='store_true', help='另存平台字幕轨；画面 OCR 不需要此选项')
    p.add_argument('--cookies', type=Path, help='仅显式指定的本地 Netscape cookie 文件；不自动提取浏览器凭据')
    a = p.parse_args()
    root = configure(a.workspace)
    result = fetch(a.url, root, a.ffmpeg_dir, a.node, a.probe, a.platform_subs, a.cookies)
    print(json.dumps({'status': result['status'], 'output': result['output'], 'error': result.get('error'),
                      'videos': [v['path'] for v in result.get('videos', [])]}, ensure_ascii=False))
    raise SystemExit(1 if result['status'] == 'failed' else 0)


if __name__ == '__main__':
    main()
