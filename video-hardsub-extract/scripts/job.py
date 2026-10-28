"""Single measured invocation for agents and the local UI; OCR is unchanged."""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from runtime import configure

SCRIPTS = Path(__file__).resolve().parent


def utc():
    return datetime.now(timezone.utc).isoformat()


def run_job(target, workspace, options=(), progress=None):
    # Child cwd is the output workspace; preserve local paths relative to caller.
    if not str(target).lower().startswith(('http://','https://')):
        target=str(Path(target).expanduser().resolve())
    root = configure(workspace, quiet=True)
    started = utc()
    begin = time.monotonic()
    folder = root / 'output/jobs' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder.mkdir(parents=True)
    interpreter = Path(sys.executable)
    if interpreter.name.lower() == 'pythonw.exe':
        interpreter = interpreter.with_name('python.exe')
    command = [str(interpreter), '-B', '-u', str(SCRIPTS / 'hardsub.py'), str(target),
               '--workspace', str(root), *map(str, options)]
    report = dict(started_utc=started, status='running', command=command,
                  workspace=str(root), log=str(folder / 'engine.log'))
    report_path = folder / 'job.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    result = None
    # A dedicated pipe keeps progress available without ever mixing it with the
    # user transcript. No shell invocation, copied answer, or external service.
    with (folder / 'engine.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        report['pid'] = process.pid
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        for line in process.stdout:
            log.write(line); log.flush()
            if progress:
                progress(line.rstrip())
            if line.lstrip().startswith('{'):
                try:
                    row = json.loads(line)
                    if isinstance(row, dict) and 'status' in row:
                        result = row
                except ValueError:
                    pass
        code = process.wait()
    report.update(ended_utc=utc(), wall_seconds=round(time.monotonic()-begin, 3),
                  exit_code=code, status='complete' if code == 0 and result else 'failed', result=result)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if report['status'] != 'complete':
        detail = (result or {}).get('error') or f'识别进程退出码 {code}，详见 {folder / "engine.log"}'
        raise RuntimeError(detail)
    if result.get('output'):
        out = Path(result['output']).resolve()
        if not out.is_relative_to(root):
            raise ValueError('输出目录不在当前工作目录中')
        (out / 'job.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def handoff(report):
    result = report['result']
    out = Path(result['output'])
    text = Path(result['files']['txt']).read_text(encoding='utf-8-sig')
    manifest = json.loads((out / 'run.json').read_text(encoding='utf-8'))
    return (f'处理完成。程序耗时 {report["wall_seconds"]:.3f} 秒；'
            f'视频范围 {manifest.get("range")} 秒；采样帧 {result.get("frames")}；'
            f'缓存复用 {result.get("cache", {}).get("hit", False)}。\n'
            f'本次结果目录：{out}\n'
            '以下是完整时间线文字稿，按时间与画面位置逐条展示，勿合并成段落或猜测字体。'
            '直接展示正文并给出 TXT/SRT；无需再读取 JSON 或另写报告。\n\n' + text
            +f'\n[下载时间线文字稿](<{out / "文字稿.txt"}>) · [下载字幕 SRT](<{out / "字幕.srt"}>)\n')


def main():
    p = argparse.ArgumentParser(description='一次调用完成下载、识别、计时和全文读取')
    p.add_argument('target')
    p.add_argument('--workspace', required=True, type=Path)
    a, options = p.parse_known_args()
    report = run_job(a.target, a.workspace, options,
                     progress=lambda s: print(s, flush=True) if s.startswith('OCR ') else None)
    print(handoff(report), flush=True)


if __name__ == '__main__':
    main()
