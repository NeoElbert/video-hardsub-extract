"""Windows browser transport using a workspace-local profile and an owned CDP port."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit
from urllib.request import urlopen,Request
from runtime import configure
from download import normalize,Log


def main():
    p=argparse.ArgumentParser(description='抖音/B站专用浏览器下载；不导出登录 Cookie。')
    p.add_argument('url')
    p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--browser',type=Path,required=True)
    p.add_argument('--node',type=Path,required=True)
    p.add_argument('--ffmpeg-dir',type=Path,required=True)
    p.add_argument('--port',type=int,default=9347)
    p.add_argument('--show-browser',action='store_true',help='需要用户登录或验证码时显示专用浏览器')
    p.add_argument('--reuse-browser',action='store_true',help='复用同一工作目录、平台和端口的本技能专用浏览器')
    a=p.parse_args();root=configure(a.workspace)
    url=normalize(a.url);host=urlsplit(url).hostname or ''
    platform='douyin' if host=='douyin.com' or host.endswith('.douyin.com') else 'bilibili' if host=='b23.tv' or host=='bilibili.com' or host.endswith('.bilibili.com') else None
    if not platform: raise ValueError('此入口只处理抖音/B站，其他平台使用 download.py。')
    profile=root/'tools/browser-profile/hardsub'/platform;profile.mkdir(parents=True,exist_ok=True)
    cache=root/'tools/cache'/('browser-'+platform);cache.mkdir(parents=True,exist_ok=True)
    # Do not connect to another program's listener or reuse an unrelated browser profile.
    import socket
    with socket.socket() as sock:occupied=sock.connect_ex(('127.0.0.1',a.port))==0
    if occupied:
        import psutil
        matched=False
        for process in psutil.process_iter(['name','cmdline']):
            args=process.info.get('cmdline') or []
            if f'--remote-debugging-port={a.port}' in args and f'--user-data-dir={profile}' in args:
                matched=True;break
        if not a.reuse_browser or not matched:
            raise RuntimeError('指定浏览器端口已被占用或目录身份不一致；未连接其他实例。')
    hidden={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    cmd=[str(a.browser),f'--user-data-dir={profile}',f'--disk-cache-dir={cache}',
         f'--remote-debugging-port={a.port}','--remote-debugging-address=127.0.0.1',
         '--no-first-run','--disable-extensions']
    if not a.show_browser:cmd.append('--headless=new')
    browser=None if occupied else subprocess.Popen(cmd+['about:blank'],cwd=root,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**hidden)
    out=root/'output/platform-download'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    out.mkdir(parents=True)
    result=dict(source=url,platform=platform,status='started',workspace=str(root))
    try:
        for i in range(40):
            try:
                with urlopen(f'http://127.0.0.1:{a.port}/json/version',timeout=1):break
            except OSError:time.sleep(.25)
        else:raise RuntimeError('工作目录内的专用浏览器启动失败。')
        req=dict(port=a.port,url=url,platform=platform,mode='video',adapter=str(Path(__file__).with_name('douyin-fields.cjs')))
        proc=subprocess.run([str(a.node),str(Path(__file__).with_name('browser_capture.mjs'))],input=json.dumps(req),
                            text=True,encoding='utf-8',capture_output=True,cwd=root,**hidden)
        info=json.loads(proc.stdout)
        if proc.returncode or info.get('status')!='ok':raise RuntimeError(info.get('error','浏览器没有返回作品数据。'))
        if info.get('multiPart'):raise RuntimeError('当前返回分段视频，尚未完成合并适配，未下载不完整视频。')
        result.update(id=info['id'],title=info['title'],reported_duration=info['duration'])
        def fetch(urls,dest):
            failures=[]
            for direct in urls:
                if not direct:continue
                try:
                    req=Request(direct,headers={'User-Agent':'Mozilla/5.0','Referer':url})
                    with urlopen(req,timeout=30) as response, dest.open('wb') as f:
                        while block:=response.read(1024*1024):f.write(block)
                    if dest.stat().st_size:return
                except Exception as e:failures.append(type(e).__name__)
            raise RuntimeError('媒体地址下载失败：'+','.join(sorted(set(failures))))
        video=out/'视频.mp4'
        if info.get('separate'):
            vp,ap=out/'video-stream.mp4',out/'audio-stream.m4a'
            fetch(info['videoUrls'],vp);fetch(info['audioUrls'],ap)
            mux=subprocess.run([str(a.ffmpeg_dir/'ffmpeg.exe'),'-v','error','-n','-i',str(vp),'-i',str(ap),'-c','copy',str(video)],capture_output=True,cwd=root,**hidden)
            if mux.returncode:raise RuntimeError('音视频合并失败。')
        else: fetch(info['videoUrls'],video)
        probe=subprocess.run([str(a.ffmpeg_dir/'ffprobe.exe'),'-v','error','-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(video)],capture_output=True,cwd=root,**hidden)
        if probe.returncode:raise RuntimeError('下载文件无法通过 ffprobe 验证。')
        meta=json.loads(probe.stdout)
        actual=float(meta.get('format',{}).get('duration',0))
        if not any(s.get('codec_type')=='video' for s in meta.get('streams',[])):raise RuntimeError('没有视频轨。')
        if actual+1<float(info.get('duration') or 0):raise RuntimeError('下载时长短于页面声明，未通过完整性核验。')
        result.update(status='downloaded',videos=[dict(path=str(video),bytes=video.stat().st_size,media=meta)])
    except Exception as e:result.update(status='failed',error=Log.clean(str(e)))
    finally:
        # Only our dedicated browser process is stopped; interactive login stays visible.
        if browser is not None and not a.show_browser:
            browser.terminate()
            try:browser.wait(timeout=10)
            except subprocess.TimeoutExpired:pass
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':result['status'],'output':str(out),'error':result.get('error')},ensure_ascii=False))
    raise SystemExit(1 if result['status']=='failed' else 0)


if __name__=='__main__':main()
