"""Conservative display-only cleanup; raw cues and timed SRT remain evidence.

Adjacent equal lines and briefly displayed CJK prefixes can be consolidated.
Never fuzzy-match words, digits, signs or negations. Raw timed cues are retained.
"""
from collections import defaultdict
from pathlib import Path
import json
import re
import unicodedata

EDGE = ' \t\r\n，,。；;！!？?、（）()【】[]「」『』“”‘’"'


def key(text):
    # Do not strip '.' (decimal), '-' (sign), '%' or internal punctuation.
    text = unicodedata.normalize('NFKC', text).strip(EDGE)
    # Chinese decorative quotes can flicker within a caption. Never normalize
    # numeric/Latin expressions, where quotes may signify units or code.
    if re.fullmatch(r'[\u3400-\u9fff“”]+',text):
        text = text.replace('“','').replace('”','')
    return text


def _layout(cues):
    groups = []
    # A single <=400 ms clipped prefix between the SAME full Chinese caption
    # is recoverable without guessing missing text. Keep original cue IDs.
    replacements = {}
    for i in range(1,len(cues)-1):
        before, middle, after = cues[i-1:i+2]
        a,b,c = [key(x['text']) for x in (before,middle,after)]
        if (a == c and re.fullmatch(r'[\u3400-\u9fff]{6,}',a)
                and a.startswith(b) and len(a)*0.7 <= len(b) < len(a)
                and float(middle['end'])-float(middle['start']) <= 0.401
                and abs(float(middle['start'])-float(before['end'])) < 0.05
                and abs(float(after['start'])-float(middle['end'])) < 0.05):
            replacements[i] = before['text']
    for index, cue in enumerate(cues):
        text = ' '.join(replacements.get(index,cue['text']).split())
        if not text:
            continue
        same = (groups and key(text) == groups[-1]['key']
                and key(text) and -0.001 <= float(cue['start']) - groups[-1]['end'] <= 0.4)
        if not same:
            groups.append(dict(key=key(text), start=float(cue['start']),
                               end=float(cue['end']), ids=[], variants=defaultdict(float)))
        group = groups[-1]
        group['end'] = float(cue['end'])
        group['ids'].append(index + 1)
        group['variants'][text] += max(0.001, float(cue['end']) - float(cue['start']))

    for group in groups:
        # Select an actually observed variant, favouring balanced brackets.
        def rank(item):
            text, duration = item
            balanced = all(text.count(a) == text.count(b) for a,b in [('（','）'),('(',')'),('【','】'),('[',']'),('“','”')])
            return balanced, duration
        group['text'] = max(group.pop('variants').items(), key=rank)[0]
        group.pop('key')

    paragraphs, parts, count = [], [], 0
    def flush():
        if parts:
            paragraphs.append(''.join(parts))
            parts.clear()
    previous = None
    for group in groups:
        text = group['text']
        gap = group['start'] - previous['end'] if previous else 0
        if parts and (gap >= 1.2 or count >= 130 or (count >= 70 and re.search(r'[。！？.!?][”’）)]?$', parts[-1]))):
            flush(); count = 0
        if parts:
            last = parts[-1][-1]
            # Display separators only; source words and ordering are unchanged.
            if last not in '，,。.;；:：!！?？、' and text[0] not in '，,。.;；:：!！?？、':
                parts.append(' ' if last.isascii() and text[0].isascii() else '，')
            elif last.isascii() and text[0].isascii():
                parts.append(' ')
        parts.append(text); count += len(text); previous = group
    flush()
    return '\n\n'.join(paragraphs) + ('\n' if paragraphs else ''), dict(
        format_version=1, raw_cues=len(cues), display_cues=len(groups),
        merged_cues=sum(len(g['ids'])-1 for g in groups), paragraphs=len(paragraphs),
        short_prefix_repairs=[dict(cue_id=i+1,original=cues[i]['text'],replacement=t) for i,t in replacements.items()],
        note='仅相邻等价字幕去重与阅读排版，未进行视觉纠错；SRT 和 cues 保留原始时间轴。', groups=groups)


def readable(cues):
    """Track adjacent visible lines without removing differing words/numbers.

    A short-lived CJK prefix can grow into its observed completion. Matching is
    one-to-one per cue, so two identical lines simultaneously on screen remain
    two lines. We never use fuzzy similarity or delete non-adjacent repetitions.
    Raw cues/SRT are not changed; every display line records its source rows.
    """
    tracks = []
    active = []
    raw_lines = 0
    for ci, cue in enumerate(cues):
        start, end = float(cue['start']), float(cue['end'])
        lines = [' '.join(line.split()) for line in cue['text'].splitlines() if line.strip()]
        raw_lines += len(lines)
        available = [ti for ti in active if start - tracks[ti]['end'] <= .4]
        used = set()
        matches = {}
        # Exact matches first; a new prefix must not steal another existing row.
        for li, line in enumerate(lines):
            options = [ti for ti in available if ti not in used and key(line)
                       and key(line) == key(tracks[ti]['text'])]
            if options:
                matches[li] = options[0]; used.add(options[0])
        for li, line in enumerate(lines):
            if li in matches:
                continue
            new = key(line)
            options = []
            for ti in available:
                old = key(tracks[ti]['text'])
                # Prefix growth is restricted to CJK text with no digits or
                # Latin units. Longer-held complete captions stay independent.
                if (ti not in used and 2 <= len(old) < len(new)
                        and new.startswith(old)
                        and re.search(r'[\u3400-\u9fff]', old)
                        and not re.search(r'[0-9A-Za-z+\-−%‰]', old + new)
                        and tracks[ti]['end'] - tracks[ti]['variant_start'] <= .701):
                    options.append(ti)
            if len(options) == 1:
                matches[li] = options[0]; used.add(options[0])
        current = []
        for li, line in enumerate(lines):
            source = dict(cue_id=ci+1, line=li+1, text=line)
            if li in matches:
                ti = matches[li]; track = tracks[ti]
                if key(line) != key(track['text']):
                    track['text'] = line
                    track['variant_start'] = start
                    track['variants'] = {}
                track['variants'][line] = track['variants'].get(line, 0) + max(.001, end-start)
                track['end'] = end; track['sources'].append(source)
            else:
                ti = len(tracks)
                tracks.append(dict(text=line, start=start, end=end,
                                   variant_start=start, sources=[source], variants={line:max(.001,end-start)}))
            current.append(ti)
        active = current
    for track in tracks:
        def rank(item):
            t, duration = item
            balanced = all(t.count(a) == t.count(b) for a,b in [('（','）'),('(',')'),('【','】'),('[',']'),('“','”')])
            return balanced, duration
        track['text'] = max(track.pop('variants').items(), key=rank)[0]
    text, audit = _layout(tracks)
    audit.update(format_version=2, raw_cues=len(cues), raw_lines=raw_lines,
                 merged_lines=raw_lines-len(tracks), line_tracks=tracks,
                 note='连续行去重、短暂中文前缀补全和阅读排版；数字及不同文字不模糊合并。SRT/cues/原始稿保持原识别结果，未进行视觉纠错。')
    return text, audit


def write_readable(out, cues):
    out = Path(out)
    text, audit = readable(cues)
    (out / '文字稿.txt').write_text(text, encoding='utf-8-sig')
    (out / '原始文字稿.txt').write_text('\n\n'.join(c['text'] for c in cues)+'\n', encoding='utf-8-sig')
    (out / 'readable.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
