"""Observed text occurrences, ordered by time and separated by screen position.

Never join separate positions or invent words/font names. Exact adjacent text
at a compatible position can persist; changed text is a new timed occurrence.
"""
from pathlib import Path
import colorsys
from collections import Counter
import json,math,argparse

def stamp(seconds):
    ms=max(0,round(seconds*1000));h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02}.{ms:03}'

def bounds(d,width,height,roi):
    points=d['box'];x=int(width*roi[0]);y=int(height*roi[1])
    return [min(p[0] for p in points)+x,min(p[1] for p in points)+y,
            max(p[0] for p in points)+x,max(p[1] for p in points)+y]

def compatible(a,b):
    ah=max(1,a[3]-a[1]);bh=max(1,b[3]-b[1])
    overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    area=max(1,(a[2]-a[0])*ah+(b[2]-b[0])*bh-overlap)
    return overlap/area>=.25 and abs((a[1]+a[3]-b[1]-b[3])/2)<=max(ah,bh)

def visual_style(crop,box):
    # Pixel-derived candidates only. No font-family, point-size or stroke claims.
    import cv2,numpy as np
    pts=np.asarray(box);h,w=crop.shape[:2]
    x0,y0=np.floor(pts.min(axis=0)).astype(int);x1,y1=np.ceil(pts.max(axis=0)).astype(int)
    tile=crop[max(0,y0):min(h,y1+1),max(0,x0):min(w,x1+1)]
    if not tile.size:return {'colour':'未确认'}
    gray=cv2.cvtColor(tile,cv2.COLOR_BGR2GRAY)
    edge=cv2.Canny(gray,80,160)>0
    if int(edge.sum())<10:return {'colour':'未确认'}
    # Record both sides of contrast boundaries rather than guessing foreground.
    pixels=tile[cv2.dilate(edge.astype('uint8'),np.ones((3,3),np.uint8))>0]
    rgb=pixels[:,::-1].astype(int);q=(rgb//32)*32+16
    common=Counter(map(tuple,q.tolist())).most_common(2)
    def colour_name(rgb):
        r,g,b=[v/255 for v in rgb];h,s,v=colorsys.rgb_to_hsv(r,g,b)
        if v<.27:return '深色'
        if s<.18:return '浅白' if v>.78 else '灰色'
        names=['红色','橙色','黄色','绿色','青色','蓝色','紫色','粉色']
        bounds=[.04,.10,.19,.44,.53,.70,.84,1.01]
        return next(name for name,bound in zip(names,bounds) if h<bound)
    colours=list(dict.fromkeys(colour_name(c) for c,_ in common))
    return {'colour':'边缘可见'+ '/'.join(colours)+'（含描边或背景，具体字色未确认）',
            'edge_rgb_candidates':[list(c) for c,_ in common]}

def build(frames,run,width,height):
    roi=run['roi'];end=run['range'][1];events=[];active=[]
    for fi,frame in enumerate(frames):
        now=float(frame['time']);until=min(end,float(frames[fi+1]['time'])) if fi+1<len(frames) else end
        remaining=list(active);active=[]
        for di,d in enumerate(frame.get('detected',[])):
            if not d.get('included',True) or not d.get('text','').strip():continue
            rect=bounds(d,width,height,roi)
            candidates=[t for t in remaining if t['text']==d['text'] and compatible(t['last_box'],rect)]
            if candidates:
                track=min(candidates,key=lambda t:sum(abs(x-y) for x,y in zip(t['last_box'],rect)));remaining.remove(track)
            else:
                track=dict(start=now,end=until,text=d['text'],first_box=rect,last_box=rect,sources=[],styles=[])
                events.append(track)
            track['end']=until;track['last_box']=rect
            track['sources'].append([fi,di]);track['styles'].append(d.get('style',{'colour':'未确认（旧结果无样式数据）'}))
            active.append(track)
    events.sort(key=lambda e:(e['start'],e['first_box'][1],e['first_box'][0]))
    for i,e in enumerate(events,1):
        x0,y0,x1,y1=e['first_box'];cx=(x0+x1)/2/width;cy=(y0+y1)/2/height
        e['id']=i;e['region']='底部字幕区域' if cy>=.72 else '其他画面文字'
        e['position']=('下' if cy>=.66 else '上' if cy<.33 else '中')+('左' if cx<.33 else '右' if cx>.66 else '中')
        if e['position']=='中中':e['position']='居中'
        e['box_normalized']=[round(x0/width,4),round(y0/height,4),round(x1/width,4),round(y1/height,4)]
        e['box_height_px']=round(y1-y0,1)
        e['layout']='竖向字框（排版方向待核对）' if y1-y0>1.5*(x1-x0) else '横向字框'
        e['type']='底部字幕候选' if cy>=.72 else '大字/标题候选' if (y1-y0)/height>=.06 else '画面文字'
        e['font']='具体字体、字重及字号未确认；字框高度不等于字体字号'
        e['colour']=Counter(s.get('colour','未确认') for s in e.pop('styles')).most_common(1)[0][0]
    return events

def render(events,run):
    roi=run['roi'];full=all(abs(a-b)<.00001 for a,b in zip(roi,[0,0,1,1]))
    step=run.get('time_resolution_seconds') or (1/run['sample_fps'] if run.get('sample_fps') else 0)
    lines=['视频文字时间线','自动识别，未逐字精校。每条按首次观察时间排列，重复画面不重复列出；文字变化另起一条。',
           f'识别范围：{"全画面" if full else "仅选定区域 "+str(roi)+"；范围外未识别"}。采样间隔约 {step:.3f} 秒，时间为采样观察边界，不是精确到每一字的真实出现时刻。',
           '位置按画面几何标注；“字幕/标题”等类型为候选。字体名称、字重和描边未经视觉核对不作判断。','']
    if not events:lines.append('本次范围内未检测到符合阈值的文字。')
    for e in events:
        rect=e['box_normalized'];pos=f'x {rect[0]*100:.1f}%–{rect[2]*100:.1f}%，y {rect[1]*100:.1f}%–{rect[3]*100:.1f}%'
        lines += [f'[{stamp(e["start"])} → {stamp(e["end"])}]  {e["region"]} · {e["position"]}',
                  e['text'],f'位置：{pos}；类型：{e["type"]}（待核对）。',
                  f'样式：{e["layout"]}；字框高约 {e["box_height_px"]:g} 像素；{e["colour"]}；字体未确认。','']
    return '\n'.join(lines).rstrip()+'\n'

def write_timeline(out,frames=None,run=None,size=None):
    out=Path(out)
    if run is None:run=json.loads((out/'run.json').read_text(encoding='utf8'))
    if frames is None:frames=[json.loads(s) for s in (out/'frames.jsonl').read_text(encoding='utf8').splitlines()]
    if size is None:size=run.get('frame_size')
    if not size:
        import cv2
        cap=cv2.VideoCapture(str(run['source']));size=[int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))];cap.release()
    if min(size)<=0:raise ValueError('无法确认画面尺寸，不能编造位置')
    events=build(frames,run,*size)
    report=dict(format='timeline-v1',frame_size=size,roi=run['roi'],events=events,
                coverage='included OCR boxes only; no out-of-ROI or below-threshold claim')
    (out/'timeline.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    text=render(events,run)
    (out/'文字稿.txt').write_text(text,encoding='utf-8-sig')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--workspace',type=Path,required=True);a=p.parse_args()
    from runtime import configure
    root=configure(a.workspace,quiet=True);out=a.run.resolve(strict=True)
    if not out.is_relative_to(root):raise ValueError('结果不在工作目录内')
    report=write_timeline(out);print(f'时间线已生成：{len(report["events"])} 条；{out / "文字稿.txt"}')
