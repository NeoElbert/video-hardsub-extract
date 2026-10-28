"""One durable queue item; all disposable artifacts are owned by that item."""
import argparse,sys
from library import Library
from job import run_job

def process(workspace,id,refresh=False,device='cpu'):
    lib=Library(workspace);row=lib.get(id)
    with lib.connect() as c:
        if c.execute("UPDATE items SET state='running',error=NULL WHERE id=? AND state NOT IN ('running','importing','deleting')",(id,)).rowcount!=1:
            raise ValueError('此视频正在处理')
    try:
        options=['--roi',row['roi'],'--mode','server','--sample-fps','3','--device',device,
                 '--model-cache-dir',str(lib.root/'tools/cache/paddlex')]
        compat=lib.root/'tools/paddle-cpu-compat'
        if device=='cpu' and (compat/'paddle/__init__.py').exists():options+=['--paddle-runtime-dir',str(compat)]
        if refresh:options.append('--refresh')
        report=run_job(lib.source(id),lib.folder(id),options,
                       lambda s:print(s,flush=True) if s.startswith('OCR ') else None)
        lib.finish(id,report)
        print('保存完成',flush=True)
        return report
    except Exception as exc:
        lib.set_state(id,'failed',str(exc));raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--workspace',required=True);p.add_argument('--id',required=True)
    p.add_argument('--refresh',action='store_true');p.add_argument('--device',choices=['cpu','gpu:0'],default='cpu');a=p.parse_args()
    try:process(a.workspace,a.id,a.refresh,a.device)
    except Exception as exc:print(str(exc),file=sys.stderr);raise SystemExit(1)
