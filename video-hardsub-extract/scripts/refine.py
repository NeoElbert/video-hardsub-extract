"""Reorder saved OCR boxes and optionally select a verified subtitle band; preserve original run."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import time
from runtime import configure
from extract import arrange,dump,segments,stamp

p=argparse.ArgumentParser(description='依据原识别框重新排序或限定字幕带；不改写识别文字，原结果保留。')
p.add_argument('run',type=Path)
p.add_argument('--workspace',required=True,type=Path)
p.add_argument('--subtitle-band',help='原画面 y0,y1 比例；按识别框中心筛选，只在核对预览后使用')
a=p.parse_args();root=configure(a.workspace);started=time.monotonic()
source=a.run.resolve(strict=True)
meta=json.loads((source/'run.json').read_text(encoding='utf-8'))
if meta.get('status') not in ('complete','no_text_detected'):raise ValueError('仅处理已经完整完成的识别结果。')
band=tuple(map(float,a.subtitle_band.split(','))) if a.subtitle_band else None
if band and (len(band)!=2 or not 0<=band[0]<band[1]<=1):raise ValueError('字幕带必须是 0~1 的 y0,y1。')
height=None
if band:
    import cv2
    cap=cv2.VideoCapture(meta['source']);height=cap.get(cv2.CAP_PROP_FRAME_HEIGHT);cap.release()
    if not height:raise ValueError('无法确认原画面高度。')
rows=[]
for raw in (source/'frames.jsonl').read_text(encoding='utf-8').splitlines():
    row=json.loads(raw)
    if 'detected' not in row:raise ValueError('该旧版本结果未保存识别框，不能重排。')
    for d in row['detected']:
        if band:
            ys=[point[1] for point in d['box']]
            center=meta['roi'][1]+(min(ys)+max(ys))/(2*height)
            d['included']=d.get('included',True) and band[0]<=center<=band[1]
            d['frame_center_y']=center
    row['text'],row['confidence']=arrange(row['detected']);rows.append(row)
cues=segments(rows,meta['range'][1])
out=root/'output/hardsub'/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'_refined')
out.mkdir(parents=True)
(out/'frames.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
(out/'字幕.srt').write_text('\n\n'.join(f'{i}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(cues,1))+'\n',encoding='utf-8-sig')
from readable import write_readable
write_readable(out,cues)
dump(out/'cues.json',cues)
meta.update(status='complete' if cues else 'no_text_detected',cues=len(cues),
            refinement=dict(source_run=str(source),subtitle_band=band,seconds=round(time.monotonic()-started,3),
                            method='Reorder original OCR boxes by overlapping row, then x; optional center-band filter. No text correction.'))
dump(out/'run.json',meta)
print(json.dumps({'status':meta['status'],'output':str(out),'cues':len(cues)},ensure_ascii=False))
