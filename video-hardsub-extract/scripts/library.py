"""Persistent, workspace-owned media library; never deletes original imports."""
from __future__ import annotations
import hashlib,json,os,re,shutil,sqlite3,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from contextlib import contextmanager

VIDEO_EXT={'.mp4','.mkv','.mov','.webm','.avi','.flv','.ts','.wmv','.m4v'}
DEFAULT_WORKSPACE=Path('D:/视频字幕工具')

def storage_root(path=None):
    root=Path(path) if path is not None else DEFAULT_WORKSPACE
    if os.name=='nt':
        if not root.is_absolute():raise ValueError('请选择非系统盘的完整目录。')
        if root.drive.upper()==os.environ.get('SystemDrive','C:').upper():
            raise ValueError('工具、缓存和结果不能保存在系统盘，请选择 D 盘或其他数据盘。')
        if not Path(root.anchor).exists():raise ValueError('所选磁盘不存在。请选择可用的数据盘；不会自动改存 C 盘。')
    root=root.resolve()
    if os.name=='nt' and root.drive.upper()==os.environ.get('SystemDrive','C:').upper():
        raise ValueError('此目录实际指向系统盘，请选择数据盘目录。')
    if root==Path(root.anchor):raise ValueError('请选择磁盘内的文件夹，不能使用磁盘根目录。')
    return root

def now():return datetime.now(timezone.utc).isoformat()

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

class Library:
    def __init__(self,workspace):
        self.root=storage_root(workspace);self.base=self.root/'library';self.items=self.base/'items'
        if not self.items.resolve().is_relative_to(self.root):raise ValueError('资料库链接越出工作目录')
        self.items.mkdir(parents=True,exist_ok=True);self.db=self.base/'index.sqlite3'
        with self.connect() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, original TEXT NOT NULL,
                source TEXT NOT NULL, created TEXT NOT NULL, state TEXT NOT NULL,
                roi TEXT NOT NULL, result TEXT, seconds REAL, error TEXT, sha256 TEXT)''')

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.db,timeout=30);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    def folder(self,id):
        if not re.fullmatch('[0-9a-f]{32}',id):raise ValueError('无效记录编号')
        expected=self.items/id;actual=expected.resolve()
        if expected.is_symlink() or actual.parent!=self.items.resolve():raise ValueError('记录路径越界')
        return actual

    def get(self,id):
        self.folder(id)
        with self.connect() as c:row=c.execute('SELECT * FROM items WHERE id=?',(id,)).fetchone()
        if not row:raise ValueError('记录不存在')
        return dict(row)

    def list(self):
        with self.connect() as c:return [dict(r) for r in c.execute('SELECT * FROM items ORDER BY created DESC,id')]

    def add(self,filename,roi='0,0,1,1'):
        source=Path(filename).resolve(strict=True)
        if not source.is_file() or source.suffix.lower() not in VIDEO_EXT:raise ValueError('不支持的视频文件')
        self.validate_roi(roi)
        id=uuid.uuid4().hex;folder=self.folder(id);folder.mkdir()
        target=folder/('原视频'+source.suffix.lower())
        with self.connect() as c:
            c.execute('INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (id,source.stem,str(source),target.name,now(),'importing',roi,None,None,None,None))
        try:
            # Copy once; original remains untouched. Compare bytes through hashes
            # before publishing an import as ready for processing.
            shutil.copy2(source,target)
            digest=sha(target)
            if source.stat().st_size!=target.stat().st_size or sha(source)!=digest:
                raise ValueError('视频复制校验失败，请重新导入')
            with self.connect() as c:c.execute('UPDATE items SET state=?,sha256=? WHERE id=?',('pending',digest,id))
        except Exception as exc:
            self.set_state(id,'failed',str(exc));raise
        return id

    @staticmethod
    def validate_roi(roi):
        values=[float(x) for x in roi.split(',')]
        if len(values)!=4 or not(0<=values[0]<values[2]<=1 and 0<=values[1]<values[3]<=1):raise ValueError('字幕范围无效')
        return values

    def set_roi(self,ids,roi):
        self.validate_roi(roi)
        with self.connect() as c:
            for id in ids:
                row=self.get(id)
                if row['state'] in ('running','importing','deleting'):raise ValueError('正在处理的记录不能修改范围')
                c.execute('UPDATE items SET roi=?,state=?,error=NULL WHERE id=?',(roi,'pending',id))

    def set_state(self,id,state,error=None):
        self.folder(id)
        with self.connect() as c:c.execute('UPDATE items SET state=?,error=? WHERE id=?',(state,error,id))

    def recover(self):
        # Called only after acquiring the single-instance library lock.
        with self.connect() as c:
            c.execute("UPDATE items SET state='failed',error='上次运行中断，原文件和已保存结果保留，可重试。' WHERE state IN ('running','importing','deleting')")

    def source(self,id):
        row=self.get(id);folder=self.folder(id);p=(folder/row['source']).resolve(strict=True)
        if p.parent!=folder:raise ValueError('源文件路径越界')
        return p

    def result(self,id):
        row=self.get(id)
        if not row['result']:raise ValueError('此视频尚未生成结果')
        folder=self.folder(id);out=(folder/row['result']).resolve(strict=True)
        if not out.is_relative_to(folder) or out==folder:raise ValueError('结果路径越界')
        return out

    def finish(self,id,report):
        folder=self.folder(id);out=Path(report['result']['output']).resolve(strict=True)
        if not out.is_relative_to(folder):raise ValueError('结果不属于该视频')
        for filename in ('文字稿.txt','字幕.srt'):
            if not (out/filename).is_file():raise ValueError('结果文件不完整')
        state='empty' if report['result']['status']=='no_text_detected' else 'complete'
        with self.connect() as c:c.execute('UPDATE items SET state=?,result=?,seconds=?,error=NULL WHERE id=?',
            (state,out.relative_to(folder).as_posix(),report['wall_seconds'],id))

    def text(self,id):
        out=self.result(id)
        if (out/'timeline.json').exists():return (out/'文字稿.txt').read_text(encoding='utf-8-sig')
        p=out/'文字稿-阅读版.txt'
        return (p if p.exists() else out/'文字稿.txt').read_text(encoding='utf-8-sig')

    def export(self,ids,destination,include_video=False):
        dest=storage_root(destination)
        if dest.is_relative_to(self.base):raise ValueError('导出目录不能位于内部资料库中')
        # Preflight prevents half-export caused by selecting unfinished records.
        rows=[(self.get(id),self.result(id)) for id in ids]
        batch=dest/('字幕导出-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]);batch.mkdir(parents=True)
        for row,out in rows:
            title=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',row['title']).strip(' .')[:90] or '视频'
            folder=batch/(title+'_'+row['id'][:8]);folder.mkdir()
            txt=out/'文字稿-阅读版.txt'
            shutil.copy2(txt if txt.exists() and not (out/'timeline.json').exists() else out/'文字稿.txt',folder/'文字稿.txt')
            shutil.copy2(out/'字幕.srt',folder/'字幕.srt')
            if include_video:shutil.copy2(self.source(row['id']),folder/('原视频'+self.source(row['id']).suffix))
        return batch

    def delete(self,id):
        row=self.get(id)
        if row['state'] in ('running','importing'):raise ValueError('正在处理，不能删除')
        folder=self.folder(id)
        # Refuse junction/symlink traversal, including descendants. Do not use
        # paths read from the database as deletion targets.
        if folder.exists():
            for current,dirs,files in os.walk(folder,followlinks=False):
                for name in dirs+files:
                    p=Path(current)/name
                    if p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()):
                        raise ValueError('记录中含链接目录，停止删除')
            if folder.resolve().parent!=self.items.resolve():raise ValueError('删除范围越界')
        self.set_state(id,'deleting')
        try:
            if folder.exists():shutil.rmtree(folder)
            with self.connect() as c:c.execute('DELETE FROM items WHERE id=?',(id,))
        except Exception as exc:
            self.set_state(id,'failed','删除未完成：'+str(exc));raise

    def import_result(self,run):
        out=Path(run).resolve(strict=True)
        metadata=json.loads((out/'run.json').read_text(encoding='utf-8-sig'))
        for name in ('字幕.srt','文字稿.txt'):
            if not (out/name).exists():raise ValueError('旧结果缺少文字稿或字幕')
        id=self.add(metadata['source'],','.join(str(v) for v in metadata['roi']))
        try:
            target=self.folder(id)/'imported-result';target.mkdir()
            for name in ('文字稿.txt','文字稿-阅读版.txt','原始文字稿.txt','字幕.srt','run.json','cues.json','readable.json','timeline.json','frames.jsonl','frames.jsonl.gz'):
                p=out/name
                if p.is_symlink():raise ValueError('旧结果包含链接文件，请先核实')
                if p.is_file():shutil.copy2(p,target/name)
            self.finish(id,dict(result=dict(output=str(target),status=metadata['status']),wall_seconds=metadata.get('seconds',0)))
        except Exception as exc:
            self.set_state(id,'failed','旧结果导入未完成：'+str(exc));raise
        return id


class InstanceLock:
    def __init__(self,library):
        self.file=(library.base/'app.lock').open('a+b');self.file.seek(0);self.file.write(b'1');self.file.flush();self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();raise RuntimeError('此资料库已在另一个窗口打开，请使用已有窗口。')
    def close(self):self.file.close()
