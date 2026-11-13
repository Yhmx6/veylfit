"""Garment tools and manual try-on result review; all images stay local."""
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from pathlib import Path
from PIL import ImageTk
from garment_workflow import CATEGORIES,REVIEW_LABELS,STATUS_LABELS
from identity_flow import ANGLE_LABELS,atomic_write

def garment_metadata(tab):
    try:info=tab.project.garment_info()
    except ValueError as e:messagebox.showinfo('先导入衣物',str(e));return
    ident=info['id'];top=tk.Toplevel(tab);top.title('衣物资料');top.geometry('540x280');top.transient(tab);top.grab_set()
    frame=ttk.Frame(top,padding=16);frame.pack(fill='both',expand=True)
    name=tk.StringVar(value=info['name']);category=tk.StringVar(value=info['category']);notes=tk.StringVar(value=info['notes'])
    for label,var in [('名称',name),('说明（如需保留的图案、口袋）',notes)]:
        ttk.Label(frame,text=label).pack(anchor='w');ttk.Entry(frame,textvariable=var).pack(fill='x',pady=5)
    ttk.Label(frame,text='品类').pack(anchor='w')
    ttk.Combobox(frame,textvariable=category,values=CATEGORIES,state='readonly').pack(fill='x',pady=5)
    def save():
        if tab.project.garment_info()['id']!=ident:raise ValueError('衣物已变化，请重新打开资料。')
        tab.project.edit_garment(name.get(),category.get(),notes.get());top.destroy()
    ttk.Button(frame,text='保存资料',command=lambda:tab.guard(save)).pack(anchor='e',pady=8)

def crop_garment(tab):
    try:info=tab.project.garment_info()
    except ValueError as e:messagebox.showinfo('先导入衣物',str(e));return
    ident=info['id'];im=tab.project.image(info['original_asset']);w,h=im.size;scale=min(620/w,460/h,1)
    top=tk.Toplevel(tab);top.title('从原图框选衣物');top.transient(tab);top.grab_set()
    ttk.Label(top,text='拖动框选完整衣物；原始图片保留，随时可恢复。').pack(pady=8)
    canvas=tk.Canvas(top,width=round(w*scale),height=round(h*scale));canvas.pack()
    top.photo=ImageTk.PhotoImage(im.resize((round(w*scale),round(h*scale))))
    canvas.create_image(0,0,anchor='nw',image=top.photo)
    box=list(info['crop'] or (0,0,w,h));start=[]
    rect=canvas.create_rectangle(*[v*scale for v in box],outline='#00aa90',width=2)
    def press(e):start[:]=[max(0,min(w,e.x/scale)),max(0,min(h,e.y/scale))]
    def drag(e):
        if not start:return
        x,y=max(0,min(w,e.x/scale)),max(0,min(h,e.y/scale))
        box[:]=[min(start[0],x),min(start[1],y),max(start[0],x),max(start[1],y)]
        canvas.coords(rect,*[v*scale for v in box])
    canvas.bind('<Button-1>',press);canvas.bind('<B1-Motion>',drag)
    def apply(value):
        if tab.project.garment_info()['id']!=ident:raise ValueError('衣物已变化。')
        tab.project.crop_garment(value);top.destroy()
    bar=ttk.Frame(top);bar.pack(fill='x',pady=8)
    ttk.Button(bar,text='恢复完整原图',command=lambda:tab.guard(lambda:apply(None))).pack(side='left')
    ttk.Button(bar,text='保存裁切',command=lambda:tab.guard(lambda:apply(box))).pack(side='right')

def garment_details(tab):
    try:info=tab.project.garment_info()
    except ValueError as e:messagebox.showinfo('先导入衣物',str(e));return
    ident=info['id'];top=tk.Toplevel(tab);top.title('背面与细节参考');top.geometry('600x480');top.transient(tab);top.grab_set()
    ttk.Label(top,text='最多三张，同一件衣物的背面、领口或图案等；修改会立即保存在当前项目。').pack(pady=8)
    listing=tk.Listbox(top,height=3,exportselection=False);listing.pack(fill='x',padx=12)
    view=ttk.Label(top,anchor='center');view.pack(fill='both',expand=True)
    def refresh():
        listing.delete(0,'end')
        for i,key in enumerate(tab.project.garment_info()['details']):listing.insert('end','参考 '+str(i+1))
        view.configure(image='');top.photo=None
    def show(_=None):
        sel=listing.curselection()
        if not sel:return
        im=tab.project.image(tab.project.garment_info()['details'][sel[0]]);im.thumbnail((500,280))
        top.photo=ImageTk.PhotoImage(im);view.configure(image=top.photo)
    listing.bind('<<ListboxSelect>>',show)
    def run(fn):
        def change():
            if tab.project.garment_info()['id']!=ident:raise ValueError('衣物已变化。')
            fn();refresh()
        tab.guard(change)
    def add():
        path=filedialog.askopenfilename(parent=top,filetypes=[('照片','*.png *.jpg *.jpeg *.webp')])
        if path:run(lambda:tab.project.add_garment_detail(path))
    def remove():
        sel=listing.curselection()
        if sel:run(lambda:tab.project.remove_garment_detail(sel[0]))
    bar=ttk.Frame(top);bar.pack(fill='x',padx=12,pady=10)
    ttk.Button(bar,text='添加细节照片',command=add).pack(side='left')
    ttk.Button(bar,text='移除选中参考',command=remove).pack(side='left',padx=8)
    refresh()

class ResultsPanel(ttk.Frame):
    def __init__(self,parent,tab):
        super().__init__(parent,padding=8);self.tab=tab;self.job_id=None;self.result_id=None;self.photos=[];self.job_ids=[];self.result_ids=[]
        ttk.Label(self,text='选择导出任务，再导入对应生成图。历史记录使用导出时的素材，不随当前衣物或角度改变。',wraplength=860).pack(anchor='w')
        bar=ttk.Frame(self);bar.pack(fill='x',pady=6)
        self.jobs=ttk.Combobox(bar,state='readonly',width=78);self.jobs.pack(side='left',fill='x',expand=True)
        self.jobs.bind('<<ComboboxSelected>>',self.choose_job)
        self.import_button=ttk.Button(bar,text='导入试穿结果…',command=self.import_result);self.import_button.pack(side='right',padx=6)
        bar2=ttk.Frame(self);bar2.pack(fill='x')
        self.results=ttk.Combobox(bar2,state='readonly',width=60);self.results.pack(side='left',fill='x',expand=True)
        self.results.bind('<<ComboboxSelected>>',self.choose_result)
        self.enlarge=ttk.Button(bar2,text='放大对照',command=self.show_large);self.enlarge.pack(side='right',padx=6)
        footer=ttk.Frame(self);footer.pack(side='bottom',fill='x',pady=4)
        row=ttk.Frame(footer);row.pack(fill='x')
        self.review={};self.review_widgets=[]
        for key,title in [('face','脸部'),('body','体型'),('garment','衣物细节')]:
            ttk.Label(row,text=title).pack(side='left',padx=4)
            var=tk.StringVar(value='待检查');self.review[key]=var
            cb=ttk.Combobox(row,textvariable=var,values=list(REVIEW_LABELS.values()),state='readonly',width=9)
            cb.pack(side='left');cb.bind('<<ComboboxSelected>>',lambda _:self.commit_review());self.review_widgets.append(cb)
        self.save_image=ttk.Button(row,text='另存结果图片',command=self.export_image);self.save_image.pack(side='right')
        row=ttk.Frame(footer);row.pack(fill='x',pady=5)
        ttk.Label(row,text='备注').pack(side='left')
        self.note=tk.StringVar();self.note_entry=ttk.Entry(row,textvariable=self.note);self.note_entry.pack(side='left',fill='x',expand=True,padx=6)
        self.note.trace_add('write',self.note_changed)
        ttk.Label(footer,text='验收与备注自动记入当前项目；关闭前请保存项目。三项通过才标为已接受。',wraplength=850).pack(anchor='w')
        self.status=tk.StringVar();ttk.Label(self,textvariable=self.status,wraplength=860).pack(anchor='w',pady=5)
        preview=ttk.Frame(self);preview.pack(fill='both',expand=True)
        self.views=[]
        for label in ('当次人物底图','当次衣物主图','试穿结果'):
            box=ttk.LabelFrame(preview,text=label);box.pack(side='left',fill='both',expand=True,padx=3)
            view=ttk.Label(box,anchor='center');view.pack(fill='both',expand=True);self.views.append(view)
        self.updating=False

    def get_job(self):return self.tab.project.tryon_job(self.job_id)
    def get_result(self):return self.tab.project.tryon_result(self.job_id,self.result_id)

    def refresh(self):
        self.updating=True
        try:
            jobs=self.tab.project.state['tryon_jobs'];self.job_ids=[j['id'] for j in jobs]
            labels=[]
            for j in jobs:
                person=j['person_source'];angle=ANGLE_LABELS.get(person.get('angle'),'原候选姿势')
                labels.append(j['id'][:8]+' · '+j['garment_info']['name'][:24]+' · '+angle+' · '+str(len(j['results']))+' 张结果')
            self.jobs.configure(values=labels)
            if self.job_id not in self.job_ids:self.job_id=self.job_ids[-1] if self.job_ids else None
            if self.job_id:self.jobs.current(self.job_ids.index(self.job_id))
            else:self.jobs.set('先在第 3 步导出试衣素材包')
            job=self.get_job() if self.job_id else None
            results=job['results'] if job else [];self.result_ids=[r['id'] for r in results]
            if self.result_id not in self.result_ids:self.result_id=self.result_ids[-1] if self.result_ids else None
            self.results.configure(values=[str(i+1)+' · '+STATUS_LABELS[r['status']]+' · '+r['id'][:8] for i,r in enumerate(results)])
            if self.result_id:self.results.current(self.result_ids.index(self.result_id))
            else:self.results.set('本任务尚未导入结果')
            result=self.get_result() if self.result_id else None
            self.import_button.configure(state='normal' if job else 'disabled')
            self.enlarge.configure(state='normal' if job else 'disabled')
            self.save_image.configure(state='normal' if result else 'disabled')
            for key,var in self.review.items():var.set(REVIEW_LABELS[result['review'][key]] if result else '待检查')
            for w in self.review_widgets:w.configure(state='readonly' if result else 'disabled')
            self.note.set(result['note'] if result else '');self.note_entry.configure(state='normal' if result else 'disabled')
            if job:
                from fit_advice import MODES
                label=job['person_source'].get('baseline_label','已确认候选')
                self.status.set(MODES.get(job.get('mode'),'历史任务（未区分模式）')+' · '+label+' · 衣物版本 '+str(job['garment_info']['revision'])+' · '+(STATUS_LABELS[result['status']] if result else '等待导回生成图'))
            else:self.status.set('每次导出会创建独立记录，保存项目后可跨次继续。')
            keys=[job['asset_hashes']['person.png'] if job else None,job['asset_hashes']['garment.png'] if job else None,result['asset'] if result else None]
            self.photos=[]
            for view,key in zip(self.views,keys):
                if key:
                    im=self.tab.project.image(key);im.thumbnail((245,255));ph=ImageTk.PhotoImage(im);self.photos.append(ph);view.configure(image=ph,text='')
                else:view.configure(image='',text='暂无图片')
        finally:self.updating=False

    def choose_job(self,_=None):
        index=self.jobs.current()
        if index>=0:self.job_id=self.job_ids[index];self.result_id=None;self.refresh()
    def choose_result(self,_=None):
        index=self.results.current()
        if index>=0:self.result_id=self.result_ids[index];self.refresh()

    def import_result(self):
        if self.tab.app.busy or not self.job_id:return
        job=self.get_job();ident=job['id']
        path=self.tab.choose_image()
        if not path:return
        angle=ANGLE_LABELS.get(job['person_source'].get('angle'),'原候选姿势')
        if not messagebox.askyesno('核对试衣任务','结果是否来自任务 '+ident[:8]+'？\n衣物：'+job['garment_info']['name']+'\n角度：'+angle+'\n程序不会自动验证生成图来源。',parent=self):return
        def run():self.result_id=self.tab.project.import_tryon_result(ident,path,True)
        self.tab.guard(run)

    def commit_review(self):
        if self.updating or not self.result_id:return
        review={k:next(code for code,label in REVIEW_LABELS.items() if label==v.get()) for k,v in self.review.items()}
        self.tab.guard(lambda:self.tab.project.review_tryon_result(self.job_id,self.result_id,review,self.note.get()))

    def note_changed(self,*_):
        if self.updating or not self.result_id:return
        value=self.note.get()
        if len(value)>2000:
            self.updating=True;self.note.set(value[:2000]);self.updating=False;value=value[:2000]
        result=self.get_result()
        # Avoid full refresh while typing so the entry cursor remains stable.
        self.tab.project.review_tryon_result(self.job_id,self.result_id,result['review'],value)
        self.tab.dirty=True;self.tab.note.set('试穿备注已记录，请保存项目。')

    def show_large(self):
        if not self.job_id:return
        job=self.get_job();result=self.get_result() if self.result_id else None
        top=tk.Toplevel(self);top.title('当次底图 / 衣物 / 试穿结果');top.geometry('1080x670');top.photos=[]
        for title,key in [('人物底图',job['asset_hashes']['person.png']),('衣物主图',job['asset_hashes']['garment.png']),('试穿结果',result['asset'] if result else None)]:
            box=ttk.LabelFrame(top,text=title);box.pack(side='left',expand=True,fill='both')
            if key:
                im=self.tab.project.image(key);im.thumbnail((350,600));ph=ImageTk.PhotoImage(im);top.photos.append(ph);ttk.Label(box,image=ph).pack(expand=True)

    def export_image(self):
        if not self.result_id:return
        path=filedialog.asksaveasfilename(defaultextension='.png',initialfile='试穿结果-'+self.result_id[:8]+'.png',filetypes=[('PNG图片','*.png')])
        if path:self.tab.guard(lambda:atomic_write(path,self.tab.project.assets[self.get_result()['asset']]))
