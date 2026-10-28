"""Local native video import, subtitle-region preview, OCR and full-text reader.

No network server or cloud formatting service. Uses exactly the same job/OCR
entry as the Skill. Only the first model download needs network for local files.
"""
from __future__ import annotations
import argparse,json,os,queue,re,threading,time
from pathlib import Path
from runtime import configure


class App:
    def __init__(self, root, workspace):
        import tkinter as tk
        from tkinter import ttk
        self.tk=tk;self.ttk=ttk;self.root=root;self.workspace=workspace
        self.messages=queue.Queue();self.busy=False;self.report=None
        self.started=0;self.duration=0;self.image=None;self.video=None;self.rect=None
        self.roi=[0.,0.,1.,1.];self.box=None
        root.title('视频字幕工具 · 本地版')
        root.geometry('1080x780');root.minsize(950,700)
        style=ttk.Style();style.theme_use('clam')
        style.configure('.',font=('Microsoft YaHei UI',10),background='#f5f7fb')
        style.configure('TFrame',background='#f5f7fb')
        style.configure('TLabel',background='#f5f7fb',foreground='#203341')
        style.configure('Title.TLabel',font=('Microsoft YaHei UI',20,'bold'))
        style.configure('Go.TButton',font=('Microsoft YaHei UI',12,'bold'),padding=(14,9),background='#157e64',foreground='white')
        main=ttk.Frame(root,padding=20);main.pack(fill='both',expand=True)
        ttk.Label(main,text='视频字幕提取',style='Title.TLabel').pack(anchor='w')
        ttk.Label(main,text='导入视频，确认字幕范围，生成可复制的全文与带时间轴的字幕。').pack(anchor='w',pady=(5,14))
        top=ttk.Frame(main);top.pack(fill='x')
        self.path=tk.StringVar()
        self.path_entry=ttk.Entry(top,textvariable=self.path);self.path_entry.pack(side='left',fill='x',expand=True)
        self.pick_button=ttk.Button(top,text='导入视频',command=self.pick);self.pick_button.pack(side='left',padx=(8,0))
        body=ttk.Panedwindow(main,orient='horizontal');body.pack(fill='both',expand=True,pady=14)
        left=ttk.Frame(body,width=400);right=ttk.Frame(body);body.add(left,weight=2);body.add(right,weight=3)
        ttk.Label(left,text='字幕范围预览 · 在画面上拖动选框').pack(anchor='w')
        self.canvas=tk.Canvas(left,width=395,height=250,bg='#17222c',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True,pady=(8,6))
        self.canvas.bind('<Configure>',lambda e:self.render())
        self.canvas.bind('<ButtonPress-1>',self.drag_start)
        self.canvas.bind('<B1-Motion>',self.drag_move)
        self.canvas.bind('<ButtonRelease-1>',self.drag_end)
        self.slider=ttk.Scale(left,from_=0,to=100,command=self.seek);self.slider.pack(fill='x')
        choices=ttk.Frame(left);choices.pack(fill='x',pady=8)
        ttk.Button(choices,text='底部字幕',command=lambda:self.preset([0,.65,1,1])).pack(side='left')
        ttk.Button(choices,text='全画面',command=lambda:self.preset([0,0,1,1])).pack(side='left',padx=6)
        self.roi_text=tk.StringVar(value='0,0,1,1')
        self.roi_entry=ttk.Entry(left,textvariable=self.roi_text);self.roi_entry.pack(fill='x')
        self.roi_entry.bind('<Return>',lambda e:self.apply_roi())
        ttk.Label(left,text='范围外的字幕不会识别；可拖动进度条检查不同画面。',wraplength=380).pack(anchor='w',pady=6)
        self.refresh=tk.BooleanVar(value=False)
        ttk.Checkbutton(left,text='重新识别（不复用已有结果）',variable=self.refresh).pack(anchor='w')
        ttk.Label(right,text='完整文字稿',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w',padx=(12,0))
        holder=ttk.Frame(right);holder.pack(fill='both',expand=True,padx=(12,0),pady=8)
        self.text=tk.Text(holder,wrap='word',height=10,width=42,font=('Microsoft YaHei UI',12),padx=16,pady=12,
                          spacing1=3,spacing3=6,relief='flat',bg='#ffffff',state='disabled')
        sb=ttk.Scrollbar(holder,command=self.text.yview);self.text.configure(yscrollcommand=sb.set)
        sb.pack(side='right',fill='y');self.text.pack(fill='both',expand=True)
        links=ttk.Frame(right);links.pack(fill='x',padx=(12,0))
        self.copy_button=ttk.Button(links,text='复制全文',command=self.copy,state='disabled');self.copy_button.pack(side='left')
        self.save_button=ttk.Button(links,text='文字稿和字幕',command=self.open_output,state='disabled');self.save_button.pack(side='left',padx=8)
        ttk.Label(right,text='自动去重分段，未进行视觉精校。标点可再交给 WorkBuddy 整理。',wraplength=520).pack(anchor='w',padx=(12,0),pady=8)
        bottom=ttk.Frame(main);bottom.pack(fill='x',side='bottom',before=body)
        self.go=ttk.Button(bottom,text='开始提取',style='Go.TButton',command=self.start);self.go.pack(side='right')
        self.status=tk.StringVar(value='请选择视频。默认使用完整 server 模型、每秒 3 帧。')
        ttk.Label(bottom,textvariable=self.status,wraplength=780).pack(side='left',anchor='w')
        self.bar=ttk.Progressbar(main,mode='determinate');self.bar.pack(fill='x',side='bottom',before=body,pady=(10,0))
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.timer=root.after(150,self.poll)

    def set_text(self,text):
        self.text.configure(state='normal');self.text.delete('1.0','end');self.text.insert('1.0',text);self.text.configure(state='disabled');self.text.yview_moveto(0)

    def pick(self):
        from tkinter import filedialog,messagebox
        filename=filedialog.askopenfilename(parent=self.root,title='导入本地视频',initialdir=self.workspace,
            filetypes=[('视频','*.mp4 *.mkv *.mov *.webm *.avi *.flv *.m4v *.ts *.wmv'),('所有文件','*.*')])
        if filename:
            self.path.set(filename)
            try:self.load_video(filename)
            except Exception as exc:messagebox.showerror('无法预览',str(exc),parent=self.root)

    def load_video(self,filename):
        import cv2
        cap=cv2.VideoCapture(str(filename))
        fps=cap.get(cv2.CAP_PROP_FPS);frames=cap.get(cv2.CAP_PROP_FRAME_COUNT)
        self.duration=frames/fps if fps else 0;cap.release()
        if self.duration<=0:raise ValueError('无法读取视频时长，请检查文件是否完整。')
        self.video=Path(filename);self.slider.configure(to=max(0,self.duration-.1))
        self.slider.set(min(3,self.duration/2));self.seek(str(min(3,self.duration/2)))
        self.status.set(f'视频 {self.duration:.1f} 秒。请确认选框包含整段视频的字幕。')

    def seek(self,value):
        if not self.video or self.busy:return
        import cv2
        from PIL import Image
        cap=cv2.VideoCapture(str(self.video));cap.set(cv2.CAP_PROP_POS_MSEC,float(value)*1000)
        ok,frame=cap.read();cap.release()
        if ok:self.image=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB));self.render()

    def render(self):
        if self.image is None:return
        from PIL import ImageTk
        w=max(self.canvas.winfo_width(),2);h=max(self.canvas.winfo_height(),2)
        scale=min(w/self.image.width,h/self.image.height)
        iw=max(1,int(self.image.width*scale));ih=max(1,int(self.image.height*scale))
        self.photo=ImageTk.PhotoImage(self.image.resize((iw,ih)))
        x=(w-iw)/2;y=(h-ih)/2;self.box=(x,y,iw,ih)
        self.canvas.delete('all');self.canvas.create_image(x,y,anchor='nw',image=self.photo)
        a,b,c,d=self.roi
        self.canvas.create_rectangle(x+a*iw,y+b*ih,x+c*iw,y+d*ih,outline='#36e9a8',width=3)

    def point(self,event):
        x,y,w,h=self.box
        return max(0,min(1,(event.x-x)/w)),max(0,min(1,(event.y-y)/h))

    def drag_start(self,event):
        if self.box and not self.busy:self.rect=self.point(event)

    def drag_move(self,event):
        if self.rect and not self.busy:
            a,b=self.rect;c,d=self.point(event)
            self.roi=[min(a,c),min(b,d),max(a,c),max(b,d)];self.render()

    def drag_end(self,event):
        if self.rect:
            self.drag_move(event);self.rect=None
            self.roi_text.set(','.join(f'{x:.4f}' for x in self.roi))

    def preset(self,value):
        if self.busy:return
        self.roi=list(value);self.roi_text.set(','.join(str(x) for x in value));self.render()

    def apply_roi(self):
        roi=[float(s) for s in self.roi_text.get().split(',')]
        if len(roi)!=4 or not (0<=roi[0]<roi[2]<=1 and 0<=roi[1]<roi[3]<=1):
            raise ValueError('字幕范围应为 0 到 1 的四个比例，例如 0,0.65,1,1。')
        self.roi=roi;self.render()

    def start(self):
        from tkinter import messagebox
        if self.busy:return
        try:
            filename=Path(self.path.get()).resolve(strict=True)
            if not filename.is_file():raise ValueError('请选择一个视频文件。')
            if self.video!=filename:self.load_video(filename)
            self.apply_roi()
        except Exception as exc:
            messagebox.showerror('请检查输入',str(exc),parent=self.root);return
        self.busy=True;self.report=None;self.started=time.monotonic();self.bar['value']=0
        for control in (self.go,self.pick_button,self.path_entry,self.roi_entry,self.copy_button,self.save_button):
            control.configure(state='disabled')
        self.set_text('正在提取。完成后会在这里直接显示全文。')
        options=['--roi',','.join(f'{v:g}' for v in self.roi),'--mode','server','--sample-fps','3','--device','cpu']
        if self.refresh.get():options.append('--refresh')
        def work():
            try:
                from job import run_job
                report=run_job(filename,self.workspace,options,lambda line:self.messages.put(('progress',line)))
                self.messages.put(('done',report))
            except Exception as exc:self.messages.put(('error',str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def poll(self):
        if self.busy:self.status.set(f'正在提取，已用 {time.monotonic()-self.started:.0f} 秒。保留原模型与采样率。')
        try:
            while True:
                kind,data=self.messages.get_nowait()
                if kind=='progress':
                    match=re.search(r'OCR ([\d.]+)/([\d.]+)s',data)
                    if match:self.bar['value']=min(99,float(match[1])/float(match[2])*100)
                else:
                    self.busy=False
                    for control in (self.go,self.pick_button,self.path_entry,self.roi_entry):control.configure(state='normal')
                    if kind=='error':self.status.set('提取失败：'+data);self.set_text('未生成有效结果。请检查视频和字幕范围。')
                    else:
                        self.report=data;self.bar['value']=100
                        out=Path(data['result']['output']);text=Path(data['result']['files']['txt']).read_text(encoding='utf-8-sig')
                        self.set_text(text if text.strip() else '未检测到字幕。请检查视频是否有画面字幕、选框是否包含字幕。')
                        self.copy_button.configure(state='normal');self.save_button.configure(state='normal')
                        elapsed=round(time.monotonic()-self.started,3)
                        status='复用识别缓存' if data['result']['cache']['hit'] else '完整识别'
                        self.status.set(f'完成 · {elapsed:.1f} 秒 · {status} · 已展示全文，文字稿和字幕已保存。')
                        (out/'local-ui.json').write_text(json.dumps(dict(status='displayed',click_to_display_seconds=elapsed,
                            characters=len(text),paragraphs=len(text.strip().split('\n\n'))),ensure_ascii=False,indent=2),encoding='utf-8')
        except queue.Empty:pass
        self.timer=self.root.after(150,self.poll)

    def copy(self):
        self.root.clipboard_clear();self.root.clipboard_append(self.text.get('1.0','end-1c'))
        self.status.set('全文已复制。')

    def open_output(self):
        if self.report:
            # Only user-facing files go in this folder. Internal evidence stays
            # in the original run directory and is never opened automatically.
            import shutil
            out=Path(self.report['result']['output']);public=out/'交付文件';public.mkdir(exist_ok=True)
            for name in ('文字稿.txt','字幕.srt'):shutil.copy2(out/name,public/name)
            os.startfile(public)

    def close(self):
        from tkinter import messagebox
        if self.busy:
            messagebox.showinfo('正在提取','请等待当前视频完成后再关闭窗口。',parent=self.root);return
        self.root.after_cancel(self.timer);self.root.destroy()


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',required=True,type=Path)
    root=configure(p.parse_args().workspace,quiet=True)
    # Windows file pickers enumerate these directories under USERPROFILE even
    # when initialdir is explicit. Keep them inside the isolated task profile.
    for name in ('Desktop','Documents','Downloads','Pictures','Videos'):
        (root/'tools/user'/name).mkdir(parents=True,exist_ok=True)
    import tkinter as tk
    window=tk.Tk();App(window,root);window.mainloop()


if __name__=='__main__':main()
