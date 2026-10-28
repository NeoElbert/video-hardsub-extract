"""Build visual review sheets; apply explicit, accountable edits without changing OCR evidence."""
import argparse,hashlib,json,re,unicodedata
from pathlib import Path
from datetime import datetime
from runtime import configure,find_font
from extract import arrange,dump,stamp

def lexical(text):
    text=unicodedata.normalize('NFKC',text)
    return ''.join(c for c in text if unicodedata.category(c)[0] in 'LN'),re.findall(r'[+\-−]?\d+(?:[.,]\d+)*(?:[%‰])?',text)

def save_outputs(out,cues):
    dump(out/'cues.json',cues)
    (out/'字幕.srt').write_text('\n\n'.join(f'{i}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(cues,1))+'\n',encoding='utf-8-sig')
    from readable import write_readable
    write_readable(out,cues)

def representative_frames(cap, cues, cv2):
    """Walk source timestamps once; random OpenCV seeks can drift on VFR media."""
    fps=cap.get(cv2.CAP_PROP_FPS)
    previous=-1.0
    for cue in cues:
        target=cue['sample_time']
        if target<previous:raise ValueError('Review samples must be in timestamp order')
        while True:
            if not cap.grab():raise RuntimeError(f'Cannot decode review frame at {target:.6f}s')
            actual=cap.get(cv2.CAP_PROP_POS_MSEC)/1000
            if actual==0 and cap.get(cv2.CAP_PROP_POS_FRAMES)>1:
                actual=(cap.get(cv2.CAP_PROP_POS_FRAMES)-1)/fps
            if actual+1e-6>=target:break
        ok,frame=cap.retrieve()
        if not ok:raise RuntimeError(f'Cannot retrieve review frame at {actual:.6f}s')
        if abs(actual-target)>max(1/fps,0.001)+1e-6:
            raise RuntimeError(f'Review frame timestamp mismatch: expected {target:.6f}, got {actual:.6f}')
        previous=actual
        yield frame,actual

def main():
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--workspace',required=True,type=Path)
    p.add_argument('--min-text-height',type=float,default=0);p.add_argument('--band',help='original-frame center y0,y1')
    p.add_argument('--apply',type=Path,help='explicit review JSON, with every cue ID accounted for')
    a=p.parse_args();root=configure(a.workspace);source=a.run.resolve(strict=True)
    meta=json.loads((source/'run.json').read_text(encoding='utf-8'))
    if meta.get('status') not in ('complete','no_text_detected'):raise ValueError('Source OCR is incomplete')
    out=root/'output/hardsub'/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+('_reviewed' if a.apply else '_review'))
    out.mkdir(parents=True)
    if a.apply:
        base=json.loads((source/'review.json').read_text(encoding='utf-8'))
        edits=json.loads(a.apply.read_text(encoding='utf-8'))
        assert edits['source_sha256']==hashlib.sha256((source/'review.json').read_bytes()).hexdigest()
        used=[];final=[]
        for group in edits['groups']:
            ids=group['ids'];assert ids==list(range(min(ids),max(ids)+1))
            assert group.get('reason'),'Each accepted/corrected/deleted group needs an audit note'
            used.extend(ids);rows=[base['cues'][i-1] for i in ids]
            if group['text'] is not None:
                assert group['text'].strip()
                final.append(dict(start=rows[0]['start'],end=rows[-1]['end'],text=group['text'],source_ids=ids))
        assert used==list(range(1,len(base['cues'])+1)),'Every cue must be accounted for exactly once, in order'
        save_outputs(out,final);dump(out/'review-edits.json',edits)
        meta.update(cues=len(final),review=dict(status='visually_reviewed',source=str(source),edits=str(a.apply.resolve()),
                    boundary='Explicit visual correction; not a claim of error-free automatic OCR.'))
        dump(out/'run.json',meta);print(json.dumps({'output':str(out),'cues':len(final)},ensure_ascii=False));return
    import cv2
    from PIL import Image,ImageDraw,ImageFont
    cap=cv2.VideoCapture(meta['source']);h=cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    band=tuple(map(float,a.band.split(','))) if a.band else None
    samples=[]
    for line in (source/'frames.jsonl').read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if 'detected' in row:
            for d in row['detected']:
                center=meta['roi'][1]+sum(p[1] for p in d['box'])/(len(d['box'])*h)
                d['included']=d.get('included',True) and d['height_ratio']>=a.min_text_height and (not band or band[0]<=center<=band[1])
            row['text'],row['confidence']=arrange(row['detected'])
        samples.append(row)
    cues=[];active=None
    for row in samples:
        key=lexical(row['text']) if row['text'].strip() else None
        if active and key!=active['key']:
            active['end']=row['time'];cues.append(active);active=None
        if key:
            if active is None:active=dict(start=row['time'],end=meta['range'][1],key=key,variants=[])
            active['variants'].append(row)
    if active:cues.append(active)
    for i,c in enumerate(cues,1):
        variants={}
        for r in c['variants']:variants.setdefault(r['text'],[]).append(r['confidence'])
        best=max(variants,key=lambda t:(len(variants[t]),sum(variants[t])/len(variants[t])))
        c.update(id=i,text=best,alternatives=list(variants),sample_time=min(c['variants'],key=lambda r:abs(r['time']-(c['start']+c['end'])/2))['time'])
        del c['variants'];del c['key']
    save_outputs(out,cues)
    font_path=find_font()
    font=ImageFont.truetype(font_path,19) if font_path else ImageFont.load_default()
    tiles=[]
    for c,(frame,actual_time) in zip(cues,representative_frames(cap,cues,cv2)):
        c['actual_frame_time']=actual_time
        height,width=frame.shape[:2];x0,y0,x1,y1=meta['roi']
        pixels=frame[int(height*y0):int(height*y1),int(width*x0):int(width*x1)]
        im=Image.fromarray(cv2.cvtColor(pixels,cv2.COLOR_BGR2RGB));im.thumbnail((1180,155))
        tile=Image.new('RGB',(1200,230),'#f2f2f2');tile.paste(im,((1200-im.width)//2,28))
        d=ImageDraw.Draw(tile);d.text((8,2),f'#{c["id"]:03}  {c["start"]:.3f}–{c["end"]:.3f}s  frame {c["sample_time"]:.3f}',font=font,fill='black')
        d.text((8,188),c['text'].replace('\n',' / '),font=font,fill='black');tiles.append(tile)
    cap.release()
    for start in range(0,len(tiles),8):
        group=tiles[start:start+8];sheet=Image.new('RGB',(1200,len(group)*230),'white')
        for j,tile in enumerate(group):sheet.paste(tile,(0,j*230))
        sheet.save(out/f'review-{start//8+1:02}.jpg')
    dump(out/'review.json',dict(source=str(source),cues=cues,filters=dict(min_text_height=a.min_text_height,band=band)))
    meta.update(cues=len(cues),review=dict(status='pending',source=str(source),method='Adjacent identical letters/digits; numeric punctuation preserved; most frequent punctuation variant.'))
    dump(out/'run.json',meta)
    (out/'frames.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in samples),encoding='utf-8')
    print(json.dumps({'output':str(out),'cues':len(cues),'sheets':(len(cues)+7)//8},ensure_ascii=False))

if __name__=='__main__':main()
