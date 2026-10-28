"""Create a persistent local tool inside the selected workspace, using its venv."""
import argparse,json,shutil
from pathlib import Path
from runtime import configure
from library import storage_root

VERSION='0.2.0-rc9'

def install(workspace=None):
    root=configure(storage_root(workspace),quiet=True)
    python=root/'tools/hardsub-venv/Scripts/pythonw.exe'
    if not python.exists():
        raise RuntimeError('请先由 WorkBuddy 按安装说明建立当前工作目录的 Python 环境。')
    tool=root/'local-tool'
    app=tool/f'app-{VERSION}'
    source=Path(__file__).resolve().parent
    destination=app/'scripts'
    if source!=destination:
        shutil.copytree(source,destination,dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    launcher=tool/'打开字幕工具.cmd'
    launcher.write_text('@echo off\nsetlocal\ncd /d "%~dp0.."\n'
        'set "TEMP=%CD%\\tools\\temp"\nset "TMP=%TEMP%"\nset "TMPDIR=%TEMP%"\n'
        'set "HOME=%CD%\\tools\\user"\nset "USERPROFILE=%HOME%"\n'
        'set "APPDATA=%HOME%\\AppData\\Roaming"\nset "LOCALAPPDATA=%HOME%\\AppData\\Local"\n'
        'set "PYTHONDONTWRITEBYTECODE=1"\nset "PYTHONUTF8=1"\n'
        'set "NVIDIA_TF32_OVERRIDE=0"\n'
        f'start "" /b "%CD%\\tools\\hardsub-venv\\Scripts\\pythonw.exe" -B "%~dp0app-{VERSION}\\scripts\\batch_app.py" --workspace "%CD%"\n',
        encoding='ascii')
    return dict(status='installed',launcher=str(launcher),workspace=str(root),version=VERSION)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path)
    print(json.dumps(install(p.parse_args().workspace),ensure_ascii=False))
