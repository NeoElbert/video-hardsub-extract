"""Idempotent project-local installation with explicit workspace isolation."""
from __future__ import annotations
import argparse,json,os,subprocess,sys,time
from pathlib import Path
from runtime import configure
from library import storage_root
SCRIPT_DIR=Path(__file__).resolve().parent

def interpreter(root):
    return root / ('tools/hardsub-venv/Scripts/python.exe' if os.name=='nt' else 'tools/hardsub-venv/bin/python')

def check(python,root,requirements):
    # Check exact requested versions before imports; a merely importable 3.3
    # runtime must not be reported as the tested 3.2.2 environment.
    code = "import importlib.metadata as m,json,sys; from packaging.requirements import Requirement; reqs=[Requirement(x.strip()) for x in open(sys.argv[1],encoding='utf-8-sig') if x.strip() and not x.lstrip().startswith('#')]; bad=[str(r) for r in reqs if m.version(r.name) not in r.specifier]; print(json.dumps({'version_mismatches':bad})); assert not bad,bad; import paddle,paddleocr,cv2,numpy,PIL,yt_dlp,psutil"
    p=subprocess.run([str(python),'-c',code,str(requirements)],cwd=root,env=os.environ.copy(),capture_output=True,text=True,encoding='utf-8',errors='replace')
    return p.returncode==0,(p.stdout+'\n'+p.stderr)[-1200:]

def main():
    p=argparse.ArgumentParser(description='在明确工作目录内准备依赖；版本匹配时跳过安装。')
    p.add_argument('--workspace',type=Path)
    p.add_argument('--python',type=Path,default=Path(sys.executable))
    p.add_argument('--force',action='store_true')
    p.add_argument('--requirements',type=Path,default=SCRIPT_DIR/'requirements.txt')
    a=p.parse_args();root=configure(storage_root(a.workspace));begin=time.monotonic()
    requirements=a.requirements.resolve(strict=True);base=a.python.resolve(strict=True)
    python=interpreter(root);steps=[];installed=False
    if not python.exists():
        run=subprocess.run([str(base),'-m','venv',str(root/'tools/hardsub-venv')],cwd=root,env=os.environ.copy(),capture_output=True,text=True,encoding='utf-8',errors='replace')
        steps.append({'step':'create venv','ok':run.returncode==0})
        if run.returncode:raise RuntimeError(run.stderr[-1200:])
    ok,detail=check(python,root,requirements)
    if a.force or not ok:
        run=subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','-r',str(requirements)],cwd=root,env=os.environ.copy(),capture_output=True,text=True,encoding='utf-8',errors='replace')
        installed=True;steps.append({'step':'pip install','ok':run.returncode==0})
        if run.returncode:raise RuntimeError(run.stderr[-1200:])
        ok,detail=check(python,root,requirements)
    else:steps.append({'step':'pip install','ok':True,'detail':'版本与导入检查通过，跳过安装'})
    print(json.dumps(dict(status='ready' if ok else 'failed',python=str(python),workspace=str(root),installed=installed,imports_ok=ok,seconds=round(time.monotonic()-begin,3),detail='' if ok else detail,steps=steps),ensure_ascii=False))
    raise SystemExit(0 if ok else 1)

if __name__=='__main__':main()
