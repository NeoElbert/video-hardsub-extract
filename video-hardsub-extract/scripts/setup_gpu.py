"""Optional isolated NVIDIA runtime. Does not change drivers or the CPU venv."""
import argparse,json,os,subprocess,sys,shutil
from pathlib import Path
from library import storage_root
from runtime import configure

def gpu_python(root):return Path(root)/'tools/hardsub-gpu-venv/Scripts/python.exe'

def gpu_ready(root):
    try:
        report=json.loads((Path(root)/'tools/gpu-ready.json').read_text(encoding='utf8'))
        return report.get('status')=='passed' and gpu_python(root).is_file()
    except (OSError,ValueError):return False

def probe(root):
    import paddle
    assert paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count()>0, '未找到可用的 NVIDIA 计算设备'
    paddle.set_device('gpu:0')
    a=paddle.ones([16,16],dtype='float32')
    assert float(paddle.matmul(a,a).sum().numpy())==4096
    # Exercise real detection+recognition, including cuDNN, before enabling UI.
    from PIL import Image,ImageDraw,ImageFont
    import numpy as np
    from extract import _ocr_engine
    frame=Image.new('RGB',(700,140),'white')
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',40)
    ImageDraw.Draw(frame).text((30,40),'OCR TEST 23.5',font=font,fill='black')
    sample=root/'tools/gpu-selfcheck.png';frame.save(sample)
    engine,_=_ocr_engine('server','gpu:0',.75,root/'tools/cache/paddlex/official_models',None)
    recognized=' '.join(t for row in engine.predict(np.asarray(frame)) for t in row['rec_texts'])
    assert ''.join(recognized.split())=='OCRTEST23.5', '显卡识别自检未匹配测试文字：'+recognized
    return dict(status='passed',paddle=paddle.__version__,cuda=paddle.version.cuda(),
                device=paddle.device.cuda.get_device_name(0),python=sys.executable,
                model='PP-OCRv5_server',recognized=recognized)

def install(root):
    if os.name!='nt':raise RuntimeError('此可选安装入口当前只验证 Windows NVIDIA 环境')
    smi=shutil.which('nvidia-smi')
    if not smi:raise RuntimeError('未找到 NVIDIA 检查工具，请先核对本机显卡及驱动；普通 CPU 方式仍可用')
    detected=subprocess.run([smi,'--query-gpu=name','--format=csv,noheader'],cwd=root,check=True,capture_output=True,text=True)
    if not detected.stdout.strip():raise RuntimeError('未检测到 NVIDIA 显卡，不下载显卡环境')
    cpu=root/'tools/hardsub-venv/Scripts/python.exe'
    if not cpu.is_file():raise RuntimeError('请先完成普通环境与模型配置')
    (root/'tools/gpu-ready.json').write_text(json.dumps(dict(status='configuring')),encoding='utf8')
    gpu=gpu_python(root)
    if not gpu.is_file():subprocess.run([str(cpu),'-B','-m','venv',str(gpu.parents[1])],cwd=root,check=True)
    shared=root/'tools/hardsub-venv/Lib/site-packages'
    (gpu.parents[1]/'Lib/site-packages/hardsub_shared_dependencies.pth').write_text(str(shared)+'\n',encoding='utf8')
    pip=[str(gpu),'-B','-m','pip','install','--disable-pip-version-check']
    subprocess.run(pip+['--no-deps','paddlepaddle-gpu==3.2.2','--index-url','https://www.paddlepaddle.org.cn/packages/stable/cu129/'],cwd=root,check=True)
    cuda=['nvidia-cuda-runtime-cu12==12.9.37','nvidia-cudnn-cu12==9.9.0.52','nvidia-cublas-cu12==12.9.0.13',
          'nvidia-cufft-cu12==11.4.0.6','nvidia-curand-cu12==10.3.10.19','nvidia-cusolver-cu12==11.7.4.40','nvidia-cusparse-cu12==12.5.9.5','nvidia-nvjitlink-cu12==12.9.86']
    subprocess.run(pip+cuda+['--index-url','https://pypi.org/simple'],cwd=root,check=True)
    subprocess.run([str(gpu),'-B',str(Path(__file__).resolve()),'--workspace',str(root),'--probe'],cwd=root,check=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path);p.add_argument('--probe',action='store_true');a=p.parse_args()
    root=configure(storage_root(a.workspace),quiet=True)
    if a.probe:
        try:report=probe(root)
        except Exception as exc:report=dict(status='failed',error=str(exc))
        (root/'tools/gpu-ready.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(report,ensure_ascii=False));raise SystemExit(report['status']!='passed')
    install(root)
