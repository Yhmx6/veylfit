"""Three-candidate selection UI for the existing Tk application."""
from io import BytesIO
from pathlib import Path
from copy import deepcopy
from zipfile import BadZipFile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import ImageTk
import face_engine as faces
from identity_flow import IdentityProject, ANGLE_LABELS
from tryon_ui import ResultsPanel, garment_metadata, crop_garment, garment_details
from fit_ui import fit_dialog


class IdentityTab(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,padding=8)
        self.app=app;self.project=IdentityProject();self.dirty=False;self.project_path=None
        self.current_bindings=set();self.photos=[]
        top=ttk.Frame(self);top.pack(fill='x')
        self.title=tk.StringVar(value='人物项目 · 尚未保存')
        ttk.Label(top,textvariable=self.title,font=('Microsoft YaHei UI',12,'bold')).pack(side='left')
        for title,fn in [('新建',self.new),('打开项目',self.open_project),('保存项目',self.save_project)]:
            ttk.Button(top,text=title,command=fn).pack(side='right',padx=3)
        ttk.Label(self,text='本地准备与确认 → 聊天生图 → 导回结果。这里不会自动上传照片或调用生图。',padding=(0,7)).pack(anchor='w')
        self.steps=ttk.Notebook(self);self.steps.pack(fill='both',expand=True)
        from calibration_ui import CalibrationPanel
        self.calibration_page=CalibrationPanel(self.steps,self)
        self.steps.add(self.calibration_page,text='逐步人物校准（推荐）')
        self.source_page=ttk.Frame(self.steps,padding=10)
        self.review_page=ttk.Frame(self.steps,padding=10)
        self.tryon_page=ttk.Frame(self.steps,padding=10)
        for page,title in [(self.source_page,'素材准备'),(self.review_page,'三候选比较（备选）'),(self.tryon_page,'继续试衣')]:
            self.steps.add(page,text=title)
        self.build_sources();self.build_review();self.build_tryon()
        self.results_page=ResultsPanel(self.steps,self)
        self.steps.add(self.results_page,text='试穿记录')
        self.note=tk.StringVar()
        ttk.Label(self,textvariable=self.note,wraplength=1000,padding=(0,7)).pack(fill='x')
        self.refresh()

    def guard(self,fn):
        if self.app.busy:return
        try:
            result=fn();self.refresh(True);return result
        except (ValueError,OSError,KeyError,BadZipFile) as e:
            self.refresh()
            messagebox.showerror('请检查',str(e),parent=self.winfo_toplevel())

    def choose_image(self):
        return filedialog.askopenfilename(parent=self.winfo_toplevel(),filetypes=[('照片','*.png *.jpg *.jpeg *.webp')])

    def build_sources(self):
        bar=ttk.Frame(self.source_page);bar.pack(fill='x')
        ttk.Button(bar,text='使用面部提取页已确认裁切',command=lambda:self.guard(self.use_current_faces)).pack(side='left')
        ttk.Button(bar,text='使用当前已生成白模',command=lambda:self.guard(self.use_current_body)).pack(side='left',padx=8)
        ttk.Label(self.source_page,text='导入本人正脸、侧脸原照或已确认裁切。体型参考后台使用，不向用户展示白模。',padding=(0,8)).pack(anchor='w')
        row=ttk.Frame(self.source_page);row.pack(fill='both',expand=True)
        self.ref_views={}
        for role,label in [('face_front','正脸原照'),('face_side','侧脸原照（可微侧）'),('body','后台体型参考')]:
            box=ttk.LabelFrame(row,text=label,padding=8);box.pack(side='left',fill='both',expand=True,padx=4)
            view=ttk.Label(box,anchor='center',text='尚未准备');view.pack(fill='both',expand=True)
            self.ref_views[role]=view
            ttk.Button(box,text='导入图片',command=lambda r=role:self.import_ref(r)).pack()
        self.refs_ok=tk.BooleanVar()
        ttk.Checkbutton(self.source_page,text='两张面部参考属于本人，白模和当前体型版本正确',variable=self.refs_ok,
            command=lambda:self.guard(lambda:self.project.approve_refs(self.refs_ok.get()))).pack(anchor='w',pady=8)
        ttk.Button(self.source_page,text='继续逐步校准 →',command=lambda:self.guard(self.begin_calibration)).pack(anchor='e',pady=4)
        ttk.Button(self.source_page,text='导出三候选生成包…',command=lambda:self.guard(self.export_batch)).pack(anchor='e')

    def begin_calibration(self):
        self.project.require_refs();self.steps.select(self.calibration_page)

    def build_review(self):
        reference=ttk.Frame(self.review_page);reference.pack(fill='x')
        ttk.Button(reference,text='对照原始面部参考',command=self.show_originals).pack(side='left')
        self.batch_label=tk.StringVar();ttk.Label(reference,textvariable=self.batch_label).pack(side='left',padx=10)
        ttk.Button(reference,text='都不像 · 新一批',command=lambda:self.guard(self.export_batch)).pack(side='right')
        row=ttk.Frame(self.review_page);row.pack(fill='both',expand=True,pady=8)
        self.cards=[]
        for i in range(3):
            box=ttk.LabelFrame(row,text=f'候选 {i+1}',padding=8);box.pack(side='left',fill='both',expand=True,padx=4)
            view=ttk.Label(box,anchor='center',text='等待导入完整人物图');view.pack(fill='both',expand=True)
            status=tk.StringVar();ttk.Label(box,textvariable=status,wraplength=240).pack(pady=4)
            ttk.Button(box,text='导入 / 替换全身图',command=lambda n=i:self.import_candidate(n)).pack(fill='x',pady=2)
            ttk.Button(box,text='调整脸部预览框',command=lambda n=i:self.edit_box(n)).pack(fill='x',pady=2)
            face=tk.BooleanVar()
            ttk.Checkbutton(box,text='脸部像我，确认',variable=face,
                command=lambda n=i,v=face:self.guard(lambda:self.project.approve(n,'face',v.get()))).pack(anchor='w')
            ttk.Button(box,text='查看全身并确认体型',command=lambda n=i:self.show_body(n)).pack(fill='x',pady=2)
            choose=ttk.Button(box,text='选定这张，继续试衣',command=lambda n=i:self.guard(lambda:self.select(n)))
            choose.pack(fill='x',pady=2)
            self.cards.append(dict(view=view,status=status,face=face,choose=choose))

    def build_tryon(self):
        from fit_advice import MODES
        mode_bar=ttk.Frame(self.tryon_page);mode_bar.pack(fill='x',pady=(0,5))
        ttk.Label(mode_bar,text='本次用途：').pack(side='left')
        self.tryon_mode=tk.StringVar(value=MODES['faithful'])
        self.mode_picker=ttk.Combobox(mode_bar,textvariable=self.tryon_mode,values=list(MODES.values()),state='readonly',width=20)
        self.mode_picker.pack(side='left',padx=8)
        self.mode_picker.bind('<<ComboboxSelected>>',lambda _:self.guard(lambda:self.project.set_tryon_mode(next(k for k,v in MODES.items() if v==self.tryon_mode.get()))))
        self.mode_note=tk.StringVar();ttk.Label(self.tryon_page,textvariable=self.mode_note,wraplength=900).pack(anchor='w')
        angle_bar=ttk.Frame(self.tryon_page);angle_bar.pack(fill='x')
        ttk.Label(angle_bar,text='固定底图角度：').pack(side='left')
        self.angle=tk.StringVar(value=ANGLE_LABELS['front'])
        self.angle_picker=ttk.Combobox(angle_bar,textvariable=self.angle,
            values=list(ANGLE_LABELS.values()),state='disabled',width=24)
        self.angle_picker.pack(side='left',padx=8)
        self.angle_picker.bind('<<ComboboxSelected>>',lambda _:self.guard(self.change_angle))
        self.selected_note=tk.StringVar()
        ttk.Label(self.tryon_page,textvariable=self.selected_note,wraplength=900).pack(anchor='w',pady=6)
        actions=ttk.Frame(self.tryon_page);actions.pack(side='bottom',fill='x')
        tools=ttk.Frame(actions);tools.pack(fill='x',pady=5)
        ttk.Button(tools,text='导入衣物参考…',command=self.import_garment).pack(side='left')
        self.garment_buttons=[]
        for label,fn in [('衣物资料…',garment_metadata),('裁切主图…',crop_garment),('背面 / 细节…',garment_details)]:
            button=ttk.Button(tools,text=label,command=lambda f=fn:f(self));button.pack(side='left',padx=4);self.garment_buttons.append(button)
        self.garment_note=tk.StringVar()
        ttk.Button(tools,text='视觉松量建议…',command=lambda:self.guard(lambda:fit_dialog(self))).pack(side='left',padx=4)
        self.fit_note=tk.StringVar()
        ttk.Label(actions,textvariable=self.fit_note,wraplength=820).pack(anchor='w')
        ttk.Label(actions,textvariable=self.garment_note,wraplength=820).pack(anchor='w')
        ttk.Label(actions,text='试衣包包含固定底图、真实面部、白模和衣物；导出后交给聊天生图。',wraplength=820).pack(anchor='w')
        self.tryon_button=ttk.Button(actions,text='导出试衣素材包…',command=lambda:self.guard(self.export_tryon))
        self.tryon_button.pack(anchor='e',pady=7)
        row=ttk.Frame(self.tryon_page);row.pack(fill='both',expand=True)
        self.person_view=ttk.Label(row,anchor='center',text='先选定人物');self.person_view.pack(side='left',fill='both',expand=True)
        self.garment_view=ttk.Label(row,anchor='center',text='导入衣物参考');self.garment_view.pack(side='left',fill='both',expand=True)

    def paint(self,widget,image,size):
        if image is None:widget.configure(image='');return
        image=image.copy();image.thumbnail(size)
        photo=ImageTk.PhotoImage(image);self.photos.append(photo)
        widget.configure(image=photo,text='')

    def refresh(self,dirty=False):
        self.dirty=self.dirty or dirty;self.photos=[]
        state=self.project.state
        self.title.set(('● ' if self.dirty else '')+'人物项目 · '+(Path(self.project_path).name if self.project_path else '尚未保存'))
        self.refs_ok.set(state['refs_approved'])
        for role,widget in self.ref_views.items():
            ref=state['refs'].get(role)
            if role=='body':
                widget.configure(image='',text='后台体型参考已准备' if ref else '尚未准备后台体型参考');continue
            self.paint(widget,self.project.image(ref['asset']) if ref else None,(230,220))
            if not ref:widget.configure(text='尚未准备')
        request=state['request']
        self.batch_label.set('批次 '+request['id'][:8]+' · 导入本批三张结果' if request else '先准备并导出生成包')
        for i,card in enumerate(self.cards):
            c=state['candidates'][i]
            self.paint(card['view'],self.project.image(c['asset']).crop(tuple(c['face_box'])) if c else None,(205,195))
            if not c:card['view'].configure(text='等待导入完整人物图')
            card['face'].set(bool(c and c['face_approved']))
            card['status'].set(('脸部已确认' if c['face_approved'] else '脸部待确认')+' · '+('体型已确认' if c['body_approved'] else '体型待确认') if c else '尚未导入')
            eligible=bool(c and all(state['candidates']) and c['face_approved'] and c['body_approved'])
            card['choose'].configure(state='normal' if eligible else 'disabled',text='已选定' if c and state['selected']==c['id'] else '选定这张，继续试衣')
        try:c=self.project.tryon_person()
        except ValueError:c=None
        fixed=bool(c and c['source']=='fixed_baseline')
        self.angle.set(ANGLE_LABELS[state.get('angle','front')])
        self.angle_picker.configure(state='readonly' if fixed else 'disabled',values=[ANGLE_LABELS[k] for k in state['baseline']['views']] if fixed else [])
        self.paint(self.person_view,self.project.image(c['asset']) if c else None,(230,290))
        if not c:self.person_view.configure(text='先选定人物')
        garment=state['garment'];self.paint(self.garment_view,self.project.image(garment) if garment else None,(300,290))
        info=state['garment_info']
        self.garment_note.set((info['name'][:40]+' · '+info['category']+' · 版本 '+str(info['revision'])+' · '+str(len(info['details']))+' 张细节图') if info else '先导入主图，再填写名称、品类或裁切。')
        from fit_advice import FITS,GOALS,COLORS,MODES
        mode=self.project.tryon_mode();self.tryon_mode.set(MODES[mode])
        self.mode_note.set('保留原色、款式与版型；尺寸未知时是外观近似预览。切换模式会清除当前建议。' if mode=='faithful' else '按目标推荐服装方案，不能标作原衣物实物还原。切换模式会清除当前建议。')
        try:
            advice=self.project.current_fit_advice()
            self.fit_note.set(GOALS[advice.get('goal','natural')]+' · '+FITS[advice['selected']]+' · '+COLORS[advice.get('color_policy','preserve')] if advice else '默认自然合身、保留原色；可在导出前选择想要的效果。')
        except ValueError:self.fit_note.set('松量建议已过期或未绑定模式，请按当前人物、衣物和用途重新设置。')
        for button in self.garment_buttons:button.configure(state='normal' if info else 'disabled')
        self.selected_note.set((c['baseline_label']+' · '+ANGLE_LABELS[c['angle']]+'。每次换衣均从此固定图出发，保留腹部厚度。')
            if fixed else ('已选定人物；后续试衣直接从此图及原始参考出发。' if c else '请先在人物建档中确认体型与面部。'))
        self.tryon_button.configure(state='normal' if c and garment else 'disabled')
        self.note.set('项目更改尚未保存。更换来源或候选会使相关确认失效。' if self.dirty else '项目保存在你选择的位置，包含真人照片；未自动上传。')
        self.results_page.refresh()
        self.calibration_page.refresh()

    def use_current_faces(self):
        tab=self.app.face_tab;tab.refresh()
        if tab.save_button.instate(['disabled']):raise ValueError('先在面部提取页完成两张裁切和同人确认。')
        self.project.set_refs({'face_'+r:faces.crop(p.photo,p.box) for r,p in tab.panels.items()},
            {'face_front':'当前面部提取页已确认裁切','face_side':'当前面部提取页已确认裁切'})
        self.current_bindings.update(('face_front','face_side'))

    def use_current_body(self):
        if not self.app.result:raise ValueError('请先生成白模，或导入已有白模预览图。')
        model=self.app.result[0]
        self.project.set_refs({'body':model.preview},{'body':{'source':'当前 MakeHuman 白模','measurements':model.measurements}})
        self.current_bindings.add('body')

    def upstream_changed(self,kind):
        roles={'body'} if kind=='body' else {'face_front','face_side'}
        bound=roles & self.current_bindings
        if bound:
            self.project.remove_refs(bound,'上游'+('白模输入' if kind=='body' else '面部裁切/确认')+'发生变化')
            self.current_bindings-=bound;self.refresh(True)

    def import_ref(self,role):
        if self.app.busy:return
        path=self.choose_image()
        if path:
            def run():
                self.project.set_refs({role:path});self.current_bindings.discard(role)
            self.guard(run)

    def export_batch(self):
        self.project.require_refs()
        if any(self.project.state['candidates']) and not messagebox.askyesno('开始新一批','当前候选和确认将归入历史，需要重新导入三张结果。继续？',parent=self.winfo_toplevel()):return
        path=filedialog.asksaveasfilename(defaultextension='.zip',initialfile='Veylfit-三候选生成包.zip',filetypes=[('生成素材包','*.zip')])
        if not path:return
        old=deepcopy(self.project.state)
        try:
            self.project.start_batch();self.project.generation_package(path)
        except Exception:
            self.project.state=old;raise
        self.steps.select(self.review_page)
        self.app.status.set('生成包已准备。请交给聊天生图生成三张，再导入当前批次。')

    def import_candidate(self,index):
        if self.app.busy:return
        try:self.project.require_batch()
        except ValueError as e:messagebox.showinfo('先准备素材',str(e));return
        path=self.choose_image()
        if not path:return
        if not messagebox.askyesno('确认候选来源','这是使用当前批次素材生成的完整单人全身图吗？替换会取消该候选确认及当前选择。',parent=self.winfo_toplevel()):return
        request_id=self.project.state['request']['id']
        def loaded(photo):
            if not self.project.state['request'] or self.project.state['request']['id']!=request_id:return
            def put():
                box=faces.suggested_crop(photo.candidates[0]['box'],photo.image.size) if len(photo.candidates)==1 else None
                self.project.put_candidate(index,photo.image,True,box)
                if len(photo.candidates)!=1:
                    self.app.status.set('脸部预览为临时范围，请调整预览框；如为多人图请替换。')
            self.guard(put)
        self.app.task(lambda:faces.load_photo(Path(path)),loaded,'正在本机准备候选脸部预览…')

    def select(self,index):
        self.project.select(index);self.steps.select(self.tryon_page)

    def show_originals(self):
        top=tk.Toplevel(self);top.title('真实面部参考');top.geometry('700x520');top.photos=[]
        for role in ('face_front','face_side'):
            ref=self.project.state['refs'].get(role)
            if ref:
                im=self.project.image(ref['asset']);im.thumbnail((330,440));ph=ImageTk.PhotoImage(im);top.photos.append(ph)
                ttk.Label(top,image=ph).pack(side='left',expand=True)

    def show_body(self,index):
        if self.app.busy:return
        try:c=self.project.candidate(index)
        except ValueError as e:messagebox.showinfo('先导入候选',str(e));return
        ident=c['id'];top=tk.Toplevel(self);top.title(f'候选 {index+1} · 全身体型确认');top.geometry('760x720');top.transient(self.winfo_toplevel());top.grab_set()
        ttk.Label(top,text='检查肩宽、腰腹、四肢和头身比例。该确认不代表厘米测量准确。',wraplength=700).pack(pady=8)
        views=ttk.Frame(top);views.pack(fill='both',expand=True);top.photos=[]
        for image in (self.project.image(c['asset']),):
            image.thumbnail((365,540));photo=ImageTk.PhotoImage(image);top.photos.append(photo)
            ttk.Label(views,image=photo).pack(side='left',expand=True)
        value=tk.BooleanVar(value=c['body_approved'])
        ttk.Checkbutton(top,text='这张图的全身体型可以接受',variable=value).pack(pady=8)
        def apply():
            if self.project.candidate(index)['id']==ident:
                self.project.approve(index,'body',value.get());self.refresh(True)
            top.destroy()
        ttk.Button(top,text='保存体型确认',command=lambda:self.guard(apply)).pack(pady=8)

    def edit_box(self,index):
        if self.app.busy:return
        try:c=self.project.candidate(index)
        except ValueError as e:messagebox.showinfo('先导入候选',str(e));return
        image=self.project.image(c['asset']);w,h=image.size;scale=min(620/w,560/h)
        top=tk.Toplevel(self);top.title('拖动框选完整头部，仅影响预览');top.transient(self.winfo_toplevel());top.grab_set()
        canvas=tk.Canvas(top,width=round(w*scale),height=round(h*scale));canvas.pack()
        top.photo=ImageTk.PhotoImage(image.resize((round(w*scale),round(h*scale))))
        canvas.create_image(0,0,anchor='nw',image=top.photo)
        box=list(c['face_box']);rect=canvas.create_rectangle(*[v*scale for v in box],outline='#00b4a0',width=2)
        start=[]
        def press(e):start[:]=[max(0,min(w,e.x/scale)),max(0,min(h,e.y/scale))]
        def drag(e):
            if not start:return
            x,y=max(0,min(w,e.x/scale)),max(0,min(h,e.y/scale))
            box[:]=[min(start[0],x),min(start[1],y),max(start[0],x),max(start[1],y)]
            canvas.coords(rect,*[v*scale for v in box])
        canvas.bind('<Button-1>',press);canvas.bind('<B1-Motion>',drag)
        def apply():self.project.set_box(index,box);top.destroy()
        ttk.Button(top,text='保存预览框（需重新确认脸部）',command=lambda:self.guard(apply)).pack(pady=8)

    def import_garment(self):
        if self.app.busy:return
        path=self.choose_image()
        if path:self.guard(lambda:self.project.set_garment(path,name=Path(path).stem[:100]))

    def export_tryon(self):
        person=self.project.tryon_person()
        name=('Veylfit-'+ANGLE_LABELS[person['angle']]+'-试衣包.zip') if person['source']=='fixed_baseline' else 'Veylfit-已选人物试衣包.zip'
        path=filedialog.asksaveasfilename(defaultextension='.zip',initialfile=name,filetypes=[('试衣包','*.zip')])
        if path:
            job_id=self.project.tryon_package(path)
            self.results_page.job_id=job_id;self.results_page.result_id=None
            self.app.status.set('试衣包已导出，任务 '+job_id[:8]+' 已记录。请保存项目；生成后到第 4 步导回结果。')

    def change_angle(self):
        angle=next(key for key,value in ANGLE_LABELS.items() if value==self.angle.get())
        self.project.set_angle(angle)

    def can_discard(self):
        if not self.dirty:return True
        answer=messagebox.askyesnocancel('保存人物项目','当前人物项目有未保存更改，是否先保存？',parent=self.winfo_toplevel())
        if answer is None:return False
        return self.save_project() if answer else True

    def save_project(self):
        if self.app.busy:return False
        path=filedialog.asksaveasfilename(defaultextension='.veylfit-person',initialfile='Veylfit-人物项目.veylfit-person',filetypes=[('映衣间人物项目','*.veylfit-person')])
        if not path:return False
        if Path(path).resolve().is_relative_to((Path(__file__).resolve().parent/'templates').resolve()):
            messagebox.showerror('请另存项目','固定人物模板作为固定基准保留，请使用其他文件名保存试衣项目。');return False
        try:self.project.save(path)
        except (OSError,ValueError) as e:messagebox.showerror('保存失败',str(e));return False
        self.project_path=path;self.dirty=False;self.refresh();return True

    def open_project(self):
        if self.app.busy or not self.can_discard():return
        path=filedialog.askopenfilename(filetypes=[('映衣间人物项目（含旧格式）','*.veylfit-person *.fitlogic')])
        if not path:return
        try:project=IdentityProject.load(path)
        except Exception as e:messagebox.showerror('无法打开项目',str(e));return
        self.project=project;self.project_path=path;self.dirty=False;self.current_bindings=set();self.refresh()
        if self.project.state.get('baseline_active'):self.steps.select(self.tryon_page)
        self.app.status.set('已载入项目内的素材快照和确认记录；不自动绑定当前其他页的输入。')

    def new(self):
        if self.app.busy or not self.can_discard():return
        self.project=IdentityProject();self.project_path=None;self.current_bindings=set();self.dirty=False;self.refresh();self.steps.select(self.source_page)
