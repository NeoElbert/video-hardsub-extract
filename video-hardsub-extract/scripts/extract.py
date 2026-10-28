"""Local video hard-subtitle OCR, with evidence and explicit time sampling.

Usable as a library (`run`) by the unified entry in hardsub.py, and as a CLI.
Sampling, model and thresholds are never silently reduced to gain speed: the
only reuse is byte-identical cropped pixels, which cannot merge a digit change
or a flashed subtitle.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unicodedata
from runtime import configure

SKILL_VERSION = '0.2.0-rc9'


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def stamp(t):
    ms = max(0, round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def canonical(text):
    # Keep punctuation and numbers; near-identical lines must remain distinct.
    return ''.join(unicodedata.normalize('NFKC', text).split())


def arrange(detected):
    """Group overlapping text boxes by row before ordering left-to-right."""
    rows = []
    items = []
    for d in detected:
        if not d.get('included', True):
            continue
        xs = [p[0] for p in d['box']]
        ys = [p[1] for p in d['box']]
        items.append(dict(x=min(xs), top=min(ys), bottom=max(ys), text=d['text'], score=d['confidence']))
    for item in sorted(items, key=lambda x: (x['top'], x['x'])):
        match = None
        for row in rows:
            overlap = min(row['bottom'], item['bottom']) - max(row['top'], item['top'])
            if overlap >= .5 * min(row['bottom'] - row['top'], item['bottom'] - item['top']):
                match = row
                break
        if match is None:
            rows.append(dict(top=item['top'], bottom=item['bottom'], items=[item]))
        else:
            match['top'] = min(match['top'], item['top'])
            match['bottom'] = max(match['bottom'], item['bottom'])
            match['items'].append(item)
    lines = []
    for row in sorted(rows, key=lambda x: x['top']):
        parts = sorted(row['items'], key=lambda x: x['x'])
        line = ''
        for item in parts:
            t = item['text']
            sep = ' ' if line and t and line[-1].isascii() and line[-1].isalnum() and t[0].isascii() and t[0].isalnum() else ''
            line += sep + t
        lines.append(line)
    return '\n'.join(lines), sum(i['score'] for i in items) / len(items) if items else 0


def segments(samples, end):
    result, active = [], None
    for item in samples:
        key = canonical(item['text'])
        if active and key != active['key']:
            active['end'] = item['time']
            result.append(active)
            active = None
        if key:
            if active is None:
                active = dict(start=item['time'], end=end, key=key, variants=[], scores=[])
            active['variants'].append(item['text'])
            active['scores'].append(item['confidence'])
    if active:
        result.append(active)
    for item in result:
        item['text'] = Counter(item.pop('variants')).most_common(1)[0][0]
        item['confidence'] = round(sum(item['scores']) / len(item['scores']), 4)
        item.pop('scores')
        item.pop('key')
    return result


def write_outputs(out, cues):
    (out / '字幕.srt').write_text(
        '\n\n'.join(f'{i}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for i, c in enumerate(cues, 1)) + '\n',
        encoding='utf-8-sig')
    from readable import write_readable
    write_readable(out, cues)
    dump(out / 'cues.json', cues)


def video_facts(video):
    import cv2
    cap = cv2.VideoCapture(str(video))
    fps, count = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
    ok = cap.isOpened() and fps > 0 and count > 0
    cap.release()
    if not ok:
        raise RuntimeError('视频无法解码或时长无效。')
    return fps, count / fps


def content_sha256(video, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(video, 'rb') as handle:
        for block in iter(lambda: handle.read(chunk), b''):
            digest.update(block)
    return digest.hexdigest()


def _ocr_engine(mode, device, min_score, model_dir, paddle_runtime_dir):
    """Create one PaddleOCR instance; engine construction dominates short runs."""
    if paddle_runtime_dir:
        sys.path.insert(0, str(Path(paddle_runtime_dir).resolve(strict=True)))
    from paddleocr import PaddleOCR
    import paddle
    det, rec = f'PP-OCRv5_{mode}_det', f'PP-OCRv5_{mode}_rec'
    opts = dict(text_detection_model_name=det, text_recognition_model_name=rec,
                use_doc_orientation_classify=False, use_doc_unwarping=False,
                use_textline_orientation=False, text_rec_score_thresh=min_score,
                device=device)
    if model_dir:
        base = Path(model_dir)
        def locate(name):
            for folder in (base / (name + '_infer'), base / name):
                if folder.is_dir():
                    return str(folder)
            raise FileNotFoundError(f'模型目录缺少 {name} 或 {name}_infer：{base}')
        opts.update(text_detection_model_dir=locate(det),
                    text_recognition_model_dir=locate(rec))
    return PaddleOCR(**opts), paddle.__version__


def _iso_mask(crop, white_text, white_yellow_text):
    """Explicit opt-in colour isolation; never applied to coloured subtitles automatically."""
    import numpy as np
    import cv2
    if not (white_text or white_yellow_text):
        return crop
    low, high = crop.min(axis=2), crop.max(axis=2)
    mask = (low >= 200) & ((high.astype(np.int16) - low.astype(np.int16)) <= 40)
    if white_yellow_text:
        blue, green, red = [crop[:, :, i].astype(np.int16) for i in range(3)]
        mask |= (red >= 180) & (green >= 150) & (blue <= 140) & (red - green <= 100)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
        # Large white paper/background regions are not subtitle glyphs.
        keep = np.zeros(count, dtype=bool)
        for label in range(1, count):
            keep[label] = 2 <= stats[label, cv2.CC_STAT_AREA] <= mask.size * .12
        mask = keep[labels]
    return np.repeat(np.where(mask, 0, 255).astype(np.uint8)[:, :, None], 3, axis=2)


def _parse_roi(text):
    roi = tuple(float(x) for x in str(text).split(','))
    if len(roi) != 4 or not (0 <= roi[0] < roi[2] <= 1 and 0 <= roi[1] < roi[3] <= 1):
        raise ValueError('ROI 必须是 x0,y0,x1,y1，且在 0~1 之间。')
    return roi


def suggest_roi(video, samples=8, mode='server', device='cpu', model_dir=None, paddle_runtime_dir=None):
    """Detect text rows on a few frames and propose the dominant subtitle band."""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(video))
    fps, total = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
    if not cap.isOpened() or fps <= 0 or total <= 0:
        raise RuntimeError('视频无法解码或时长无效。')
    duration = total / fps
    ocr, _ = _ocr_engine(mode, device, .6, model_dir, paddle_runtime_dir)
    centers, heights = [], []
    for t in np.linspace(0, max(0.0, duration - 1 / fps), samples):
        cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        for result in ocr.predict(frame):
            for text, score, box in zip(result['rec_texts'], result['rec_scores'], result['rec_polys']):
                if float(score) < .6 or not text.strip():
                    continue
                pts = np.asarray(box)
                top, bottom = float(pts[:, 1].min()) / h, float(pts[:, 1].max()) / h
                if bottom - top < .015 or bottom - top > .25:
                    continue
                centers.append((top + bottom) / 2)
                heights.append((top, bottom))
    cap.release()
    if not centers:
        return None
    bins = np.zeros(20)
    for c in centers:
        bins[min(19, int(c * 20))] += 1
    best = max(range(20), key=lambda i: (bins[max(0, i - 1):min(20, i + 2)].sum(), -i))
    low, high = max(0, best - 1) / 20, min(20, best + 2) / 20
    picked = [h for c, h in zip(centers, heights) if low <= c <= high]
    if not picked:
        return None
    y0 = max(0.0, min(p[0] for p in picked) - .02)
    y1 = min(1.0, max(p[1] for p in picked) + .02)
    return [0.0, round(y0, 3), 1.0, round(y1, 3)]


def preview(video, root, roi, start=0.0, end=None, suggest=False, mode='server', device='cpu',
            model_dir=None, paddle_runtime_dir=None):
    """Write a 6-frame contact sheet with the ROI box; never leaves status=running."""
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw
    video = Path(video)
    out = root / 'output' / 'hardsub' / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '_preview')
    out.mkdir(parents=True)
    fps, duration = video_facts(video)
    stop = min(end if end is not None else duration, duration)
    manifest = dict(source=str(video), duration=duration, source_fps=fps, roi=roi, range=[start, stop],
                    status='preview', created=datetime.now(timezone.utc).isoformat(),
                    workspace=str(root), skill_version=SKILL_VERSION)
    dump(out / 'run.json', manifest)
    cap = cv2.VideoCapture(str(video))
    tiles, geometry = [], []
    for t in np.linspace(start, max(start, stop - 1 / fps), 6):
        cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        img.thumbnail((480, 420))
        tile = Image.new('RGB', (500, 450), '#202020')
        paste_x, paste_y = (500 - img.width) // 2, 25 + (420 - img.height) // 2
        tile.paste(img, (paste_x, paste_y))
        geometry.append((paste_x, paste_y, img.width, img.height))
        d = ImageDraw.Draw(tile)
        d.text((10, 5), f'{t:.2f}s', fill='white')
        d.rectangle((paste_x + roi[0] * img.width, paste_y + roi[1] * img.height,
                     paste_x + roi[2] * img.width, paste_y + roi[3] * img.height), outline='red', width=2)
        tiles.append(tile)
    cap.release()
    canvas = Image.new('RGB', (1500, 900))
    for i, tile in enumerate(tiles):
        canvas.paste(tile, ((i % 3) * 500, (i // 3) * 450))
    canvas.save(out / 'preview.jpg')
    suggested = None
    if suggest:
        suggested = suggest_roi(video, mode=mode, device=device, model_dir=model_dir,
                                paddle_runtime_dir=paddle_runtime_dir)
        if suggested:
            box = Image.open(out / 'preview.jpg')
            draw = ImageDraw.Draw(box)
            for i, (px, py, iw, ih) in enumerate(geometry):
                x, y = (i % 3) * 500, (i // 3) * 450
                draw.rectangle((x + px + suggested[0] * iw, y + py + suggested[1] * ih,
                                x + px + suggested[2] * iw, y + py + suggested[3] * ih),
                               outline='#00ff66', width=2)
            box.save(out / 'preview-suggested.jpg')
    manifest.update(status='preview', preview_frames=len(tiles), suggested_roi=suggested,
                    note='预览只确定字幕区域，不做识别统计。用 --roi 传入确认后的区域再提取。')
    dump(out / 'run.json', manifest)
    return dict(status='preview', output=str(out), preview=str(out / 'preview.jpg'),
                suggested_roi=suggested, duration=duration)


def run(video, root, roi='0,0,1,1', sample_fps=3.0, start=0.0, end=None, mode='server', device='cpu',
        min_score=.75, min_text_height=0.0, white_text=False, white_yellow_text=False,
        model_dir=None, paddle_runtime_dir=None, out=None, pixel_reuse=True, log=print):
    """Full-video OCR. Returns the finished manifest dict."""
    import cv2
    import numpy as np
    video = Path(video).resolve(strict=True)
    roi = _parse_roi(roi) if not isinstance(roi, tuple) else roi
    if sample_fps < 0 or start < 0:
        raise ValueError('采样率和起点不能为负数。')
    if model_dir:
        model_dir = Path(model_dir)
    if paddle_runtime_dir is None and (root / 'tools/paddle-cpu-compat/paddle/__init__.py').exists():
        paddle_runtime_dir = root / 'tools/paddle-cpu-compat'
    fps, duration = video_facts(video)
    stop = min(end if end is not None else duration, duration)
    if start >= stop:
        raise ValueError('起点必须小于终点。')
    if out is None:
        key = hashlib.sha256(str(video).encode()).hexdigest()[:8]
        out = root / 'output' / 'hardsub' / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '_' + key)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = dict(source=str(video), duration=duration, source_fps=fps, roi=roi,
                    range=[start, stop], sample_fps=sample_fps, model=mode, device=device,
                    min_score=min_score, min_text_height=min_text_height, white_text=white_text,
                    nvidia_tf32_override=os.environ.get('NVIDIA_TF32_OVERRIDE'),
                    white_yellow_text=white_yellow_text, status='running', skill_version=SKILL_VERSION,
                    created=datetime.now(timezone.utc).isoformat(), workspace=str(root))
    dump(out / 'run.json', manifest)
    started = time.monotonic()
    ocr, paddle_version = _ocr_engine(mode, device, min_score, model_dir, paddle_runtime_dir)
    init_seconds = time.monotonic() - started
    manifest.update(paddle_version=paddle_version,
                    paddle_runtime_dir=str(paddle_runtime_dir) if paddle_runtime_dir else 'installed environment',
                    engine_init_seconds=round(init_seconds, 3))
    dump(out / 'run.json', manifest)
    period = 1 / fps if sample_fps == 0 else max(1 / fps, 1 / sample_fps)
    cap = cv2.VideoCapture(str(video))
    samples, n, reused = [], 0, 0
    seen = {}
    ocr_started = time.monotonic()
    # Decode sequentially and use stream timestamps, avoiding rounded-frame seeks on VFR.
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    last_decoded = start
    with (out / 'frames.jsonl').open('w', encoding='utf-8') as evidence:
        while True:
            if not cap.grab():
                if last_decoded + max(1.0, 2 * period) < stop:
                    raise RuntimeError(f'视频在 {last_decoded:.3f}s 提前结束，未标记完成。')
                stop = min(stop, last_decoded + 1 / fps)
                break
            timestamp = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if timestamp == 0 and cap.get(cv2.CAP_PROP_POS_FRAMES) > 1:
                timestamp = (cap.get(cv2.CAP_PROP_POS_FRAMES) - 1) / fps
            last_decoded = timestamp
            if end is not None and timestamp >= stop:
                break
            target = start + n * period
            if timestamp + 1e-6 < target:
                continue
            ok, frame = cap.retrieve()
            if not ok:
                raise RuntimeError(f'视频在 {target:.3f}s 解码失败，未标记完成。')
            h, w = frame.shape[:2]
            manifest['frame_size']=[w,h]
            crop = frame[int(h * roi[1]):int(h * roi[3]), int(w * roi[0]):int(w * roi[2])]
            crop = _iso_mask(crop, white_text, white_yellow_text)
            # Exact byte identity only: a digit change or a new subtitle changes pixels.
            signature = None
            if pixel_reuse:
                signature = hashlib.sha256(crop.tobytes() + str(crop.shape).encode()).digest()
                if signature in seen:
                    text, confidence, detected = seen[signature]
                    reused += 1
                    item = dict(time=timestamp, text=text, confidence=confidence, detected=detected,
                                pixel_reuse=True)
                    samples.append(item)
                    evidence.write(json.dumps(item, ensure_ascii=False) + '\n')
                    evidence.flush()
                    if n % 30 == 0:
                        log(f'OCR {target:.1f}/{stop:.1f}s')
                    n += 1
                    continue
            detected = []
            for result in ocr.predict(crop):
                for text, score, box in zip(result['rec_texts'], result['rec_scores'], result['rec_polys']):
                    if float(score) >= min_score and text.strip():
                        points = np.asarray(box)
                        height = float(points[:, 1].max() - points[:, 1].min()) / h
                        from timeline import visual_style
                        detected.append(dict(text=str(text), confidence=float(score), height_ratio=height,
                                             box=points.tolist(), included=height >= min_text_height,
                                             style=visual_style(crop,points)))
            text, confidence = arrange(detected)
            if signature is not None:
                seen[signature] = (text, confidence, detected)
            item = dict(time=timestamp, text=text, confidence=confidence, detected=detected)
            samples.append(item)
            evidence.write(json.dumps(item, ensure_ascii=False) + '\n')
            evidence.flush()
            if n % 30 == 0:
                log(f'OCR {target:.1f}/{stop:.1f}s')
            n += 1
    cap.release()
    ocr_seconds = time.monotonic() - ocr_started
    if samples:
        stop = max(stop, samples[-1]['time'] + 1 / fps)
    cues = segments(samples, stop)
    write_outputs(out, cues)
    from timeline import write_timeline
    manifest.update(range=[start,stop],time_resolution_seconds=period)
    timeline=write_timeline(out,samples,manifest,manifest.get('frame_size'))
    manifest['timeline_events']=len(timeline['events'])
    total = time.monotonic() - started
    manifest.update(status='complete' if cues else 'no_text_detected', frames=len(samples), cues=len(cues),
                    range=[start, stop], seconds=round(total, 3),
                    engine_init_seconds=round(init_seconds, 3), ocr_seconds=round(ocr_seconds, 3),
                    pixel_reuse_frames=reused,
                    time_resolution_seconds=period,
                    note='仅识别所选区域；低置信度文字被过滤。采样间隔内的闪现字幕可能遗漏，未用语音补写。'
                         '逐帧证据中 pixel_reuse=true 表示该帧裁剪像素与已识别帧完全相同，直接复用其识别结果。',
                    output=str(out))
    dump(out / 'run.json', manifest)
    return manifest


def parser():
    p = argparse.ArgumentParser(description='读取视频画面字幕，导出 SRT/TXT/JSON；不使用语音补写。')
    p.add_argument('video', type=Path)
    p.add_argument('--workspace', required=True, type=Path)
    p.add_argument('--roi', default='0,0,1,1', help='识别区域 x0,y0,x1,y1，0~1；默认全画面')
    p.add_argument('--sample-fps', type=float, default=3, help='每秒识别帧数；0 表示逐帧。更快闪现字幕需提高采样率。')
    p.add_argument('--start', type=float, default=0)
    p.add_argument('--end', type=float, help='默认处理完整视频；仅验收片段时明确指定')
    p.add_argument('--mode', choices=['mobile', 'server'], default='server')
    p.add_argument('--device', default='cpu', help='cpu 或本机 Paddle 支持的 gpu:0；不静默降级')
    p.add_argument('--min-score', type=float, default=.75)
    p.add_argument('--min-text-height', type=float, default=0, help='按原画面高度比例排除过小文字；默认不过滤，需按预览确认')
    p.add_argument('--white-text', action='store_true', help='仅用于已核对为白色字幕的画面：保留亮白低色差像素，排除彩色或黑色背景文字')
    p.add_argument('--white-yellow-text', action='store_true', help='仅用于核对为白/黄色的字幕；隔离文字颜色并移除大块同色背景')
    p.add_argument('--model-dir', type=Path, help='预先下载的 V5 模型目录；省略则使用 Paddle 官方下载')
    p.add_argument('--paddle-runtime-dir', type=Path, help='显式兼容运行库目录；不改变识别模型')
    p.add_argument('--preview', action='store_true', help='只导出多个时间点的画面，方便确定字幕区域')
    p.add_argument('--suggest-roi', action='store_true', help='preview 时附带一个建议字幕区域（需加载检测模型）')
    p.add_argument('--no-pixel-reuse', action='store_true', help='关闭完全相同裁剪像素的逐帧复用')
    return p


def main():
    a = parser().parse_args()
    root = configure(a.workspace)
    if a.preview:
        info = preview(a.video, root, _parse_roi(a.roi), a.start, a.end, suggest=a.suggest_roi,
                       mode=a.mode, device=a.device, model_dir=a.model_dir,
                       paddle_runtime_dir=a.paddle_runtime_dir)
        print(json.dumps(info, ensure_ascii=False))
        return
    manifest = run(a.video, root, a.roi, a.sample_fps, a.start, a.end, a.mode, a.device, a.min_score,
                   a.min_text_height, a.white_text, a.white_yellow_text, a.model_dir,
                   a.paddle_runtime_dir, pixel_reuse=not a.no_pixel_reuse)
    print(json.dumps({'status': manifest['status'], 'output': manifest['output'],
                      'cues': manifest.get('cues'), 'frames': manifest.get('frames')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
