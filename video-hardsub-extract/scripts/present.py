"""Validate punctuation-only reading layout, then save the user-facing TXT."""
import argparse,json,re,unicodedata,sys
from datetime import datetime,timezone
from pathlib import Path
from runtime import configure

def content(text):
    return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))

def validate(original,reading):
    if content(original)!=content(reading):
        raise ValueError('阅读版改变了原有文字或顺序，请仅调整标点和段落。')
    numeric=r'[+\-−]?\d+(?:[.,]\d+)*(?:[%‰])?'
    if re.findall(numeric,original)!=re.findall(numeric,reading):
        raise ValueError('阅读版改变了数字、小数或正负号。')

def save_reading(out, reading):
    out=Path(out)
    original=(out/'文字稿.txt').read_text(encoding='utf-8-sig')
    reading=reading.strip()+'\n'
    if (out/'timeline.json').exists() and reading!=original.strip()+'\n':
        raise ValueError('时间线结果须逐条保留时间、位置和文字，不能改成合并段落。')
    validate(original,reading)
    target=out/'文字稿-阅读版.txt';target.write_text(reading,encoding='utf-8-sig')
    (out/'presentation.json').write_text(json.dumps(dict(status='passed',
        saved_utc=datetime.now(timezone.utc).isoformat(),paragraphs=len(reading.strip().split('\n\n')),
        characters=len(content(reading)),txt=str(target)),ensure_ascii=False,indent=2),encoding='utf-8')
    return target,reading

def final_message(out, target, reading):
    out=Path(out)
    job=out/'job.json'
    report=json.loads(job.read_text(encoding='utf-8')) if job.exists() else {}
    run=json.loads((out/'run.json').read_text(encoding='utf-8'))
    bounds=run.get('range') or [0,0]
    duration=float(bounds[1])-float(bounds[0])
    timing=f'，程序处理 {report["wall_seconds"]:.1f} 秒' if 'wall_seconds' in report else ''
    reused='（复用识别缓存）' if run.get('cache',{}).get('hit') else ''
    return (f'视频 {duration:.1f} 秒{timing}{reused}。以下为自动整理稿，未精校。\n\n'
            +reading+'\n'+f'[下载文字稿](<{target}>) · [下载字幕 SRT](<{out / "字幕.srt"}>)\n')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('run',type=Path);p.add_argument('draft',type=Path,nargs='?')
    p.add_argument('--stdin',action='store_true',help='从标准输入读取排版稿，省去草稿文件写入与再读取')
    p.add_argument('--workspace',required=True,type=Path)
    a=p.parse_args();root=configure(a.workspace)
    out=a.run.resolve(strict=True)
    if not out.is_relative_to(root):raise ValueError('结果必须位于工作目录内。')
    if a.stdin:
        if a.draft:p.error('--stdin 和草稿路径只能选一个')
        reading=sys.stdin.read()
    else:
        if not a.draft:p.error('提供草稿路径或 --stdin')
        draft=a.draft.resolve(strict=True)
        if not draft.is_relative_to(root):raise ValueError('阅读草稿必须位于工作目录内。')
        reading=draft.read_text(encoding='utf-8-sig')
    target,reading=save_reading(out,reading)
    print(final_message(out,target,reading))

if __name__=='__main__':main()
