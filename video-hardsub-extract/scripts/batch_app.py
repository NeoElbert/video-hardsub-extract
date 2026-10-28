"""Batch queue and saved media library UI. No cloud model required."""
import argparse,json,os,queue,re,subprocess,sys,threading,time
from pathlib import Path
from library import Library,InstanceLock,storage_root,VIDEO_EXT
from runtime import configure
from setup_gpu import gpu_ready,gpu_python

LABELS={'pending':'待提取','running':'正在提取','importing':'正在保存视频','complete':'已保存','empty':'未检测到字幕','failed':'失败，可重试','deleting':'正在删除'}

class BatchApp:
    def __init__(self,window,workspace):
        import tkinter as tk
        from tkinter import ttk
        self.tk=tk;self.ttk=ttk;self.win=window;self.lib=Library(workspace)
        self.lock=InstanceLock(self.lib);self.lib.recover()
        self.busy=False;self.stop=threading.Event();self.messages=queue.Queue();self.started=0;self.current=''
        window.title('视频字幕工具 · 批量资料库');window.geometry('1120x760');window.minsize(960,660)
        style=ttk.Style();style.theme_use('clam');style.configure('.',font=('Microsoft YaHei UI',10))
        style.configure('TFrame',background='#f5f7fb');style.configure('TLabel',background='#f5f7fb',foreground='#203341')
        style.configure('Treeview',rowheight=30);style.configure('Accent.TButton',background='#157e64',foreground='white',padding=8)
        main=ttk.Frame(window,padding=18);main.pack(fill='both',expand=True)
        ttk.Label(main,text='视频字幕资料库',font=('Microsoft YaHei UI',20,'bold')).pack(anchor='w')
        ttk.Label(main,text='多选导入 · 自动保存视频副本、文字稿和字幕 · 关闭后仍可继续查看').pack(anchor='w',pady=(5,12))
        tools=ttk.Frame(main);tools.pack(fill='x')
        self.controls=[]
        for label,callback in [('导入多个视频',self.add_files),('导入文件夹',self.add_folder),('导入旧结果',self.add_result),('字幕范围',self.preview),('全选当前列表',self.select_visible)]:
            button=ttk.Button(tools,text=label,command=callback);button.pack(side='left',padx=(0,6));self.controls.append(button)
        self.query=tk.StringVar();entry=ttk.Entry(tools,textvariable=self.query,width=20);entry.pack(side='right')
        ttk.Label(tools,text='搜索名称 ').pack(side='right');self.query.trace_add('write',lambda *a:self.refresh())
        ttk.Label(main,text='新视频默认识别全画面，可能包含背景文字。可逐个预览并框选字幕范围，提高速度、减少干扰。',wraplength=1050).pack(anchor='w',pady=8)
        footer=ttk.Frame(main);footer.pack(side='bottom',fill='x')
        self.status=tk.StringVar(value='导入后点击“提取所选”，结果会自动保存。支持 Ctrl / Shift 多选。')
        ttk.Label(footer,textvariable=self.status,wraplength=1050).pack(anchor='w',pady=5)
        ttk.Label(footer,text='保存位置：'+str(self.lib.root),wraplength=1050).pack(anchor='w')
        self.bar=ttk.Progressbar(footer,mode='determinate');self.bar.pack(fill='x',pady=6)
        actions=ttk.Frame(main);actions.pack(side='bottom',fill='x',pady=8)
        for label,callback in [('提取所选',lambda:self.start(False)),('提取全部待处理',lambda:self.start(True)),('批量导出',self.export),('删除所选',self.delete)]:
            button=ttk.Button(actions,text=label,command=callback,style='Accent.TButton' if label=='提取所选' else 'TButton')
            button.pack(side='left',padx=(0,7));self.controls.append(button)
        self.pause=ttk.Button(actions,text='完成当前后暂停',command=self.pause_queue,state='disabled');self.pause.pack(side='left')
        self.force=tk.BooleanVar(value=False);ttk.Checkbutton(actions,text='强制重新识别',variable=self.force).pack(side='right')
        available=gpu_ready(self.lib.root);self.gpu=tk.BooleanVar(value=available)
        self.gpu_button=ttk.Checkbutton(actions,text='显卡加速' if available else '显卡未配置',variable=self.gpu,state='normal' if available else 'disabled')
        self.gpu_button.pack(side='right',padx=6)
        panes=ttk.Panedwindow(main,orient='horizontal');panes.pack(fill='both',expand=True,pady=8)
        left=ttk.Frame(panes);right=ttk.Frame(panes);panes.add(left,weight=1);panes.add(right,weight=1)
        self.table=ttk.Treeview(left,columns=('name','state','time'),show='headings',selectmode='extended',height=12)
        for name,label,width in [('name','视频名称',260),('state','状态',100),('time','处理秒数',80)]:
            self.table.heading(name,text=label);self.table.column(name,width=width,minwidth=60)
        sc=ttk.Scrollbar(left,command=self.table.yview);self.table.configure(yscrollcommand=sc.set)
        sc.pack(side='right',fill='y');self.table.pack(fill='both',expand=True)
        self.table.bind('<<TreeviewSelect>>',lambda e:self.show())
        self.table.bind('<Double-1>',lambda e:self.show())
        self.table.bind('<Control-a>',self.select_visible)
        self.heading=tk.StringVar(value='选择记录，按时间查看字幕与画面文字')
        ttk.Label(right,textvariable=self.heading,font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w',padx=10)
        note=ttk.Label(right,text='按时间逐条显示；位置/类型为候选，字体未确认。导出 TXT/SRT，可选视频。',wraplength=440)
        note.pack(side='bottom',anchor='w',padx=10,pady=8)
        row=ttk.Frame(right);row.pack(side='bottom',fill='x',padx=10)
        ttk.Button(row,text='复制全文',command=self.copy).pack(side='left')
        ttk.Button(row,text='播放保存的视频',command=self.play).pack(side='left',padx=6)
        frame=ttk.Frame(right);frame.pack(fill='both',expand=True,padx=(10,0),pady=8)
        self.text=tk.Text(frame,wrap='word',height=12,width=42,font=('Microsoft YaHei UI',12),padx=12,pady=10,spacing3=6,state='disabled',relief='flat')
        sb=ttk.Scrollbar(frame,command=self.text.yview);self.text.configure(yscrollcommand=sb.set)
        sb.pack(side='right',fill='y');self.text.pack(fill='both',expand=True)
        self.refresh();self.timer=window.after(200,self.poll);window.protocol('WM_DELETE_WINDOW',self.close)

    def selected(self):return list(self.table.selection())
    def select_visible(self,event=None):
        self.table.selection_set(self.table.get_children())
        return 'break'
    def notice(self,title,text):
        from tkinter import messagebox
        messagebox.showinfo(title,text,parent=self.win)
    def refresh(self):
        chosen=self.selected();query=self.query.get().casefold()
        rows=[r for r in self.lib.list() if query in r['title'].casefold()]
        ids={r['id'] for r in rows}
        for id in self.table.get_children():
            if id not in ids:self.table.delete(id)
        for r in rows:
            values=(r['title'],LABELS.get(r['state'],r['state']),f'{r["seconds"]:.1f}' if r['seconds'] is not None else '')
            if self.table.exists(r['id']):self.table.item(r['id'],values=values)
            else:self.table.insert('','end',iid=r['id'],values=values)
        self.table.selection_set([id for id in chosen if id in ids])
    def set_text(self,text):
        self.text.configure(state='normal');self.text.delete('1.0','end');self.text.insert('1.0',text);self.text.configure(state='disabled');self.text.yview_moveto(0)
    def show(self):
        ids=self.selected()
        if not ids:return
        row=self.lib.get(ids[0]);self.heading.set(row['title'])
        try:self.set_text(self.lib.text(ids[0]) or '未检测到字幕，请检查范围。')
        except (ValueError,OSError):self.set_text(row['error'] or '尚无可读取的结果，可以提取或重试。')
    def toggle(self,busy):
        self.busy=busy
        for widget in self.controls:widget.configure(state='disabled' if busy else 'normal')
        self.pause.configure(state='normal' if busy else 'disabled')
    def import_files(self,files):
        if not files:return
        self.toggle(True);self.status.set('正在保存视频副本，请稍候…')
        def work():
            good=[];errors=[]
            for file in files:
                try:good.append(self.lib.add(file))
                except Exception as exc:errors.append(Path(file).name+'：'+str(exc))
            self.messages.put(('imported',(good,errors)))
        threading.Thread(target=work,daemon=True).start()
    def add_files(self):
        from tkinter import filedialog
        self.import_files(filedialog.askopenfilenames(parent=self.win,title='选择多个视频',initialdir=self.lib.root,
            filetypes=[('视频','*.mp4 *.mkv *.mov *.webm *.avi *.flv *.m4v *.ts *.wmv')]))
    def add_folder(self):
        from tkinter import filedialog
        path=filedialog.askdirectory(parent=self.win,title='导入此文件夹中的视频（不含子文件夹）',initialdir=self.lib.root)
        if path:self.import_files(sorted(p for p in Path(path).iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT))
    def add_result(self):
        from tkinter import filedialog
        path=filedialog.askdirectory(parent=self.win,title='选择含文字稿、字幕和 run.json 的旧结果文件夹',initialdir=self.lib.root/'output/hardsub')
        if not path:return
        self.toggle(True)
        def work():
            try:self.messages.put(('imported',([self.lib.import_result(path)],[])))
            except Exception as exc:self.messages.put(('imported',([],[str(exc)])))
        threading.Thread(target=work,daemon=True).start()
    def preview(self):
        ids=self.selected()
        if not ids:self.notice('字幕范围','请先选中视频。');return
        # Reuse the tested native preview with a save-only action; no OCR runs.
        from local_app import App
        top=self.tk.Toplevel(self.win);app=App(top,self.lib.root)
        top.transient(self.win)
        app.path.set(str(self.lib.source(ids[0])));app.load_video(app.path.get());app.preset(self.lib.validate_roi(self.lib.get(ids[0])['roi']))
        app.pick_button.configure(state='disabled');app.path_entry.configure(state='disabled')
        app.set_text(f'调整左侧字幕框后，点击“保存到所选 {len(ids)} 个视频”。\n\n多个视频字幕位置不同，请分别选择后设置范围。')
        def save():
            try:
                app.apply_roi();self.lib.set_roi(ids,','.join(f'{v:g}' for v in app.roi));app.close();self.refresh()
            except Exception as exc:self.notice('范围未保存',str(exc))
        app.go.configure(text=f'保存到所选 {len(ids)} 个视频',command=save)
    def start(self,all_pending):
        ids=[r['id'] for r in reversed(self.lib.list()) if r['state'] in ('pending','failed')] if all_pending else self.selected()
        if not ids:self.notice('提取视频','请先导入或选择视频。');return
        self.toggle(True);self.stop.clear();self.started=time.monotonic();self.bar['value']=0;force=self.force.get();device='gpu:0' if self.gpu.get() else 'cpu'
        def work():
            done=0;failed=0
            for id in ids:
                if self.stop.is_set():break
                self.messages.put(('begin',(id,done,len(ids))))
                python=Path(sys.executable)
                if python.name.lower()=='pythonw.exe':python=python.with_name('python.exe')
                if device=='gpu:0':python=gpu_python(self.lib.root)
                cmd=[str(python),'-B','-u',str(Path(__file__).with_name('batch_worker.py')),'--workspace',str(self.lib.root),'--id',id,'--device',device]
                if force:cmd.append('--refresh')
                try:
                    proc=subprocess.Popen(cmd,cwd=self.lib.root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                    with (self.lib.folder(id)/'worker.log').open('w',encoding='utf-8') as log:
                        for line in proc.stdout:
                            log.write(line);self.messages.put(('progress',(done,len(ids),line)))
                    code=proc.wait()
                    if code:
                        failed+=1
                        if self.lib.get(id)['state']=='running':self.lib.set_state(id,'failed','进程意外退出，可重试。')
                except Exception as exc:failed+=1;self.lib.set_state(id,'failed',str(exc))
                done+=1;self.messages.put(('item_done',id))
            self.messages.put(('finished',(done,failed,len(ids))))
        threading.Thread(target=work,daemon=True).start()
    def pause_queue(self):self.stop.set();self.status.set('将在当前视频保存完成后暂停，其他视频保留。')
    def export(self):
        from tkinter import filedialog,messagebox
        ids=self.selected()
        if not ids:self.notice('批量导出','请先选择已有结果的视频。');return
        dest=filedialog.askdirectory(parent=self.win,title='选择数据盘导出文件夹',initialdir=self.lib.root)
        if not dest:return
        include=messagebox.askyesno('导出内容','同时导出已保存的视频副本吗？\n选“否”仅导出文字稿 TXT 和字幕 SRT。',parent=self.win)
        self.toggle(True)
        def work():
            try:self.messages.put(('exported',str(self.lib.export(ids,dest,include))))
            except Exception as exc:self.messages.put(('error',str(exc)))
        threading.Thread(target=work,daemon=True).start()
    def delete(self):
        from tkinter import messagebox
        ids=self.selected()
        if not ids:return
        if not messagebox.askyesno('永久删除所选记录',f'将删除 {len(ids)} 条记录及工具保存的视频副本、字幕、文字稿和本次缓存。\n\n不会删除最初导入的原视频，也不会删除已经导出的文件。此操作不可撤销。确定删除吗？',parent=self.win):return
        self.toggle(True)
        def work():
            errors=[]
            for id in ids:
                try:self.lib.delete(id)
                except Exception as exc:errors.append(str(exc))
            self.messages.put(('deleted',errors))
        threading.Thread(target=work,daemon=True).start()
    def copy(self):
        ids=self.selected()
        if not ids:return
        try:text=self.lib.text(ids[0])
        except Exception as exc:self.notice('尚无文字稿',str(exc));return
        self.win.clipboard_clear();self.win.clipboard_append(text);self.status.set('全文已复制。')
    def play(self):
        ids=self.selected()
        if ids:
            try:os.startfile(self.lib.source(ids[0]))
            except Exception as exc:self.notice('无法打开视频',str(exc))
    def poll(self):
        try:
            while True:
                kind,data=self.messages.get_nowait()
                if kind=='begin':
                    id,done,total=data;self.current=self.lib.get(id)['title'];self.status.set(f'正在提取 {done+1}/{total}：{self.current}');self.refresh()
                elif kind=='progress':
                    done,total,line=data;match=re.search(r'OCR ([\d.]+)/([\d.]+)s',line)
                    if match:
                        self.bar['value']=(done+float(match[1])/float(match[2]))/total*100
                        self.refresh()
                        self.status.set(f'正在提取 {done+1}/{total}：{self.current} · 已处理视频 {float(match[1]):.1f}/{float(match[2]):.1f} 秒 · 本轮已用 {time.monotonic()-self.started:.0f} 秒')
                elif kind=='item_done':self.refresh();self.table.selection_set(data);self.show()
                else:
                    self.toggle(False);self.refresh()
                    if kind=='imported':
                        good,errors=data;self.table.selection_set(good);self.show();self.status.set(f'已保存 {len(good)} 个视频。'+('；'.join(errors) if errors else '可以开始批量提取。'))
                    elif kind=='finished':
                        done,failed,total=data;self.bar['value']=done/total*100
                        self.status.set(f'本轮处理 {done}/{total} 个，失败 {failed} 个，用时 {time.monotonic()-self.started:.1f} 秒。结果均自动保存。')
                    elif kind=='exported':self.status.set('已导出：'+data);os.startfile(data)
                    elif kind=='deleted':self.set_text('');self.status.set('所选记录已删除。' if not data else '部分未删除：'+'；'.join(data))
                    elif kind=='error':self.notice('操作未完成',data)
        except queue.Empty:pass
        self.timer=self.win.after(200,self.poll)
    def close(self):
        if self.busy:self.notice('正在处理','可点击“完成当前后暂停”，待当前视频保存后关闭。');return
        self.win.after_cancel(self.timer);self.lock.close();self.win.destroy()

def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path);a=p.parse_args()
    import tkinter as tk
    from tkinter import filedialog,messagebox
    window=None
    try:root=storage_root(a.workspace);configure(root,quiet=True)
    except ValueError as exc:
        window=tk.Tk();window.withdraw()
        messagebox.showinfo('请选择保存位置',str(exc),parent=window)
        chosen=filedialog.askdirectory(parent=window,title='选择非系统盘的工具目录')
        if not chosen:window.destroy();return
        try:root=storage_root(chosen)
        except ValueError as err:messagebox.showerror('位置不可用',str(err),parent=window);window.destroy();return
    configure(root,quiet=True)
    if window is None:window=tk.Tk();window.withdraw()
    for name in ('Desktop','Documents','Downloads','Pictures','Videos'):(root/'tools/user'/name).mkdir(parents=True,exist_ok=True)
    try:BatchApp(window,root)
    except Exception as exc:messagebox.showerror('无法打开资料库',str(exc),parent=window);window.destroy();return
    window.deiconify();window.mainloop()

if __name__=='__main__':main()
