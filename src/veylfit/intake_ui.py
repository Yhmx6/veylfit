"""Local guided intake; no network and no user-facing white-model preview."""
from pathlib import Path
from copy import deepcopy
from io import BytesIO
from queue import Queue,Empty
from threading import Thread
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from PIL import Image,ImageTk
import intake_flow as flow
import shape_engine as shapes
import shape_artwork

PARTS=('family','arms','torso','legs','neck')
TITLES=('基本资料','整体体型','手臂','胸腹','臀腿','肩颈','补充尺寸','正侧照片','本轮结果')

class IntakeTab(ttk.Frame):
    def __init__(self,parent,app=None,autostart=False):
        super().__init__(parent,padding=22)
        self.app=app;self.state=flow.new_state();self.assets={};self.result=None
        self.generation=0;self.closed=False;self.transition=None;self.busy=False;self.queue=Queue()
        self.refs=[];self.buttons=[];self.fields={};self.suspend=False
        self.columnconfigure(0,weight=1);self.rowconfigure(2,weight=1)
        top=ttk.Frame(self);top.grid(row=0,column=0,sticky='ew')
        ttk.Label(top,text='映衣间 · 人物建档',font=('Microsoft YaHei UI',18,'bold')).pack(side='left')
        ttk.Button(top,text='打开档案',command=self.open_project).pack(side='right')
        ttk.Button(top,text='保存草稿',command=self.save_draft).pack(side='right',padx=8)
        self.progress=tk.StringVar();ttk.Label(self,textvariable=self.progress,font=('Microsoft YaHei UI',11)).grid(row=1,column=0,sticky='w',pady=(18,8))
        self.content=ttk.Frame(self);self.content.grid(row=2,column=0,sticky='nsew');self.content.columnconfigure(0,weight=1)
        footer=ttk.Frame(self);footer.grid(row=3,column=0,sticky='ew',pady=10)
        self.back_button=ttk.Button(footer,text='上一步',command=self.back);self.back_button.pack(side='left')
        self.status=tk.StringVar();ttk.Label(footer,textvariable=self.status,wraplength=600).pack(side='left',padx=14)
        self.next_button=ttk.Button(footer,text='下一步',command=self.next);self.next_button.pack(side='right')
        self.bind('<Destroy>',self.destroyed,add=True);self.poll_id=self.after(80,self.poll);self.render()

    @property
    def step(self):return self.state['step']

    def invalidate(self,*args):
        if self.suspend:return
        self.generation+=1;self.result=None;self.busy=False
        if self.app and hasattr(self.app,'intake_changed'):
            self.app.intake_changed()
        elif self.app and hasattr(self.app,'identity_tab'):
            target=self.app.identity_tab
            if 'intake_body' in target.current_bindings:
                target.project.remove_refs({'body'},'建档体型输入已变更');target.current_bindings.discard('intake_body');target.refresh(True)
        if self.step==8:self.next_button.configure(state='disabled')

    def cancel_transition(self):
        if self.transition:self.after_cancel(self.transition);self.transition=None

    def field(self,parent,key,value,row,label):
        ttk.Label(parent,text=label,font=('Microsoft YaHei UI',12)).grid(row=row,column=0,sticky='w',padx=(0,25),pady=8)
        var=tk.StringVar(value=value);self.fields[key]=var
        if key=='gender':
            widget=ttk.Combobox(parent,textvariable=var,values=('男性','女性'),state='readonly',width=20)
        else:widget=ttk.Entry(parent,textvariable=var,width=23)
        widget.grid(row=row,column=1,sticky='w');var.trace_add('write',self.invalidate)

    def render(self):
        for w in self.content.winfo_children():w.destroy()
        self.fields={};self.refs=[];self.buttons=[];self.suspend=True
        self.progress.set(f'{self.step+1} / 9 · {TITLES[self.step]}')
        self.back_button.configure(state='normal' if self.step else 'disabled')
        self.next_button.configure(text='下一步',state='normal');self.status.set('')
        title=ttk.Label(self.content,text=TITLES[self.step],font=('Microsoft YaHei UI',22,'bold'));title.grid(sticky='w',pady=(6,12))
        if self.step==0:
            form=ttk.Frame(self.content);form.grid(sticky='w',pady=8)
            b=self.state['basic']
            for row,(key,label) in enumerate((('gender','性别'),('height_cm','身高（cm）'),('weight_kg','体重（kg）'),('age_years','年龄（岁）'))):
                value={'male':'男性','female':'女性'}.get(b[key],'') if key=='gender' else b[key]
                self.field(form,key,value,row,label)
            self.note('请填写本人的资料。本轮先测试成年男模；女性资料可保存草稿。\n身高150–205cm、体重40–150kg，且BMI在17–36范围内。')
        elif 1<=self.step<=5:
            key=PARTS[self.step-1];self.note('选择最接近自己的外形，点击后自动进入下一步。')
            cards=ttk.Frame(self.content);cards.grid(sticky='ew',pady=8)
            for i in range(3):cards.columnconfigure(i,weight=1,uniform='card')
            if key=='family':options=[(k,v,shape_artwork.cards(k,(220,250))['torso',1]) for k,v in shapes.FAMILIES.items()]
            else:
                family=self.state['choices'].get('family')
                if family not in shapes.FAMILIES:raise ValueError('请先选择整体体型。')
                ims=shape_artwork.cards(family,(220,250));options=[(i,label,ims[key,i]) for i,label in enumerate(shapes.GROUPS[key][1])]
            for i,(value,label,im) in enumerate(options):
                photo=ImageTk.PhotoImage(im);self.refs.append(photo)
                button=tk.Button(cards,image=photo,text=label,compound='top',font=('Microsoft YaHei UI',12),pady=12,bd=1,
                    bg='#cfe2da' if self.state['choices'].get(key)==value else '#faf7f0',relief='flat',
                    command=lambda k=key,v=value:self.choose(k,v))
                button.grid(row=0,column=i,sticky='ew',padx=(0 if i==0 else 12,0));self.buttons.append(button)
            self.next_button.configure(state='disabled');self.note('示意图描述相对外形，不代表精确尺寸或肌肉量。')
        elif self.step==6:
            self.note('可只填知道的项目，也可以全部留空后继续。单位均为厘米。')
            form=ttk.Frame(self.content);form.grid(sticky='w')
            for row,(key,label) in enumerate(flow.MEASURES.items()):
                value=self.state['measurements'][key];self.field(form,key,'' if value is None else f'{value:g}',row,label)
            self.note('自然腰围与肚脐水平的腹围分开填写。肩宽为两肩峰间直线距离。\n腿内长按站立裆点到地面的垂直高度填写，不用裤子尺码代替。\n已填写项参与模型约束；未填写项保留估计。请按自然呼吸、无收腹状态测量。')
            self.next_button.configure(text='继续（可不填）')
        elif self.step==7:
            self.note('薄、合身、不塑形的衣物；正常站立，自然呼吸，完整露出头脚。\n手臂稍离身体；侧面尽量正侧，避免俯拍、仰拍。不要求脱衣。')
            cards=ttk.Frame(self.content);cards.grid(sticky='ew')
            for i,(role,label) in enumerate((('front','正面全身照'),('side','侧面全身照'))):
                cards.columnconfigure(i,weight=1,uniform='photo');box=ttk.Frame(cards);box.grid(row=0,column=i,padx=12)
                if role in self.assets:
                    im=Image.open(BytesIO(self.assets[role]));im.thumbnail((265,285));photo=ImageTk.PhotoImage(im);self.refs.append(photo)
                    ttk.Label(box,image=photo).pack()
                else:ttk.Label(box,text='尚未导入',width=32,anchor='center',padding=(0,100)).pack()
                ttk.Button(box,text='导入 / 更换'+label,command=lambda r=role:self.select_photo(r)).pack(pady=6)
            self.photo_check=tk.BooleanVar(value=self.state['photos_confirmed'])
            ttk.Checkbutton(self.content,text='已确认是同一人的近期正面与侧面照片，头脚完整，画面清晰。',variable=self.photo_check,command=self.photo_confirmation).grid(sticky='w',pady=10)
            self.next_button.configure(text='检查照片并继续')
        else:
            b=self.state['basic'];c=self.state['choices'];m=self.state['measurements']
            self.note(f"男性 · {b['height_cm']}cm · {b['weight_kg']}kg · {b['age_years']}岁")
            for key in PARTS:
                label=shapes.FAMILIES[c[key]] if key=='family' else shapes.GROUPS[key][0]+'：'+shapes.GROUPS[key][1][c[key]]
                ttk.Label(self.content,text=label,font=('Microsoft YaHei UI',12)).grid(sticky='w',pady=4)
            self.note(f"补充尺寸：已填{sum(v is not None for v in m.values())} / 6项 · 正侧照片：已导入")
            self.note('先检查照片标记，再用已填尺寸约束模型。宽松衣物仅作参考上限。\n填写尺寸与照片不一致时，以填写值为几何约束，并提示复核。脸和体型仍需本人确认。')
            self.retry_button=ttk.Button(self.content,text='重新检查',command=self.process);self.retry_button.grid(sticky='w',pady=8)
            ttk.Button(self.content,text='检查 / 修改照片校正标记',command=self.review_photos).grid(sticky='w',pady=5)
            ttk.Button(self.content,text='进入人物校准 →',command=self.continue_identity).grid(sticky='w',pady=5)
            ttk.Button(self.content,text='查看尺寸拟合结果',command=self.show_measurements).grid(sticky='w',pady=5)
            self.next_button.configure(text='保存本轮结果',state='normal' if self.result else 'disabled')
        self.suspend=False

    def note(self,text):ttk.Label(self.content,text=text,wraplength=890,foreground='#5d7067',font=('Microsoft YaHei UI',10)).grid(sticky='w',pady=7)

    def capture(self):
        if self.step==0:
            values={k:v.get().strip() for k,v in self.fields.items()};values['gender']={'男性':'male','女性':'female'}.get(values['gender'],'')
            if values['height_cm']!=self.state['basic']['height_cm']:self.state['photo_fit']=None
            self.state['basic']=values
        elif self.step==6:self.state['measurements']=flow.parse_measures({k:v.get() for k,v in self.fields.items()})
        elif self.step==7:self.state['photos_confirmed']=self.photo_check.get()

    def choose(self,key,value):
        if self.transition or not 1<=self.step<=5 or key!=PARTS[self.step-1]:return
        if key=='family' and self.state['choices'].get(key)!=value:self.state['choices']={}
        self.state['choices'][key]=value;self.invalidate()
        for button in self.buttons:button.configure(state='disabled')
        index=list(shapes.FAMILIES).index(value) if key=='family' else value
        self.buttons[index].configure(bg='#cfe2da');self.transition=self.after(260,self.advance)

    def advance(self):self.transition=None;self.state['step']+=1;self.render()

    def next(self):
        if self.busy or self.transition:return
        try:
            self.capture()
            if self.step==0:
                b=flow.basic_values(self.state)
                if b['gender']!='male' or b['age_years']<18:raise ValueError('本轮只开放成年男模测试，当前资料可以保存为草稿。')
            if self.step==7:
                flow.validate_complete(self.state,self.assets);self.state['step']=8;self.render();self.process();return
            if self.step==8:self.save_result();return
            if self.step in (0,6):self.advance()
        except (ValueError,OSError) as error:self.status.set(str(error))

    def back(self):
        try:self.capture()
        except ValueError as error:self.status.set(str(error));return
        self.cancel_transition();self.invalidate()
        if self.step:self.state['step']-=1;self.render()

    def photo_confirmation(self):
        self.state['photos_confirmed']=self.photo_check.get();self.invalidate()
        self.next_button.configure(state='normal')

    def set_photo(self,role,data):
        other='side' if role=='front' else 'front'
        if self.assets.get(other)==data:raise ValueError('两张照片相同，请分别选择正面和侧面。')
        self.assets[role]=data;self.state['photos_confirmed']=False;self.state['photo_fit']=None;self.invalidate();self.render()

    def review_photos(self):
        if self.busy or self.result is None:
            self.status.set('请先等待照片识别完成。');return
        from photo_fit_ui import PhotoReview
        PhotoReview(self,self.assets,self.result[1]['photo_fit_proposal'],self.apply_photo_fit)

    def apply_photo_fit(self,cal):
        self.state['photo_fit']=cal;self.process()

    def launch(self,kind,fn,role=None):
        self.invalidate();self.busy=True;generation=self.generation;self.next_button.configure(state='disabled')
        self.status.set('正在本机处理，请稍候…')
        def work():
            try:self.queue.put((generation,kind,role,fn(),None))
            except Exception as error:self.queue.put((generation,kind,role,None,str(error)))
        Thread(target=work,daemon=True).start()

    def select_photo(self,role):
        if self.busy:return
        path=filedialog.askopenfilename(parent=self,filetypes=[('照片','*.jpg *.jpeg *.png *.webp')])
        if path:self.launch('photo',lambda:flow.import_photo(path),role)

    def process(self):
        try:flow.validate_complete(self.state,self.assets)
        except ValueError as error:self.status.set(str(error));return
        state=deepcopy(self.state);photos=dict(self.assets)
        self.launch('process',lambda:flow.process(state,photos))

    def poll(self):
        if self.closed:return
        try:
            while True:
                generation,kind,role,value,error=self.queue.get_nowait()
                if generation!=self.generation:continue
                self.busy=False
                if error:
                    self.status.set('未完成：'+error)
                    if self.step==7:self.next_button.configure(state='normal')
                    continue
                if kind=='photo':
                    try:self.set_photo(role,value)
                    except ValueError as err:self.status.set(str(err));self.next_button.configure(state='normal')
                elif self.step==8 and value[1]['input_fingerprint']==flow.fingerprint(self.state,self.assets):
                    self.result=value;self.next_button.configure(state='normal');self.status.set('照片校正已应用，体型仍待本人确认。' if value[1]['photo_fit_applied'] else '识别完成。请点击检查照片校正标记；未检查前保存的仍是基础体型。')
        except Empty:pass
        self.poll_id=self.after(80,self.poll)

    def save_to(self,path,with_result=False):
        self.capture()
        if with_result and self.result is None:raise ValueError('请等待本轮处理完成。')
        flow.save_project(path,self.state,self.assets,self.result if with_result else None)

    def save_dialog(self,with_result):
        try:self.capture()
        except ValueError as error:self.status.set(str(error));return
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.veylfit',initialfile='人物建档.veylfit',filetypes=[('人物建档','*.veylfit')])
        if not path:return
        try:self.save_to(path,with_result);self.status.set('已保存到本机：'+Path(path).name)
        except Exception as error:messagebox.showerror('未保存',str(error),parent=self)

    def save_draft(self):self.save_dialog(False)
    def save_result(self):self.save_dialog(True)

    def continue_identity(self):
        if self.busy or self.result is None:
            messagebox.showinfo('先完成体型处理','请先完成本轮照片检查和体型处理。',parent=self);return
        try:
            from identity_flow import IdentityProject
            if self.app and hasattr(self.app,'accept_intake'):
                self.app.accept_intake();return
            p=IdentityProject();p.attach_intake(self.state,self.assets,self.result)
            if self.app:
                target=self.app.identity_tab
                if not target.can_discard():return
                target.project=p;target.project_path=None;target.current_bindings={'intake_body'};target.refresh(True)
                target.steps.select(target.source_page);self.app.tabs.select(target)
            else:
                path=filedialog.asksaveasfilename(parent=self,defaultextension='.veylfit-person',initialfile='待校准人物.veylfit-person',filetypes=[('人物校准项目','*.veylfit-person')])
                if not path:return
                p.save(path)
                import subprocess,sys
                subprocess.Popen([sys.executable,'-B',str(Path(__file__).with_name('app.py')),'--identity','--person',path],creationflags=subprocess.CREATE_NO_WINDOW)
            self.status.set('体型已交给人物校准，请继续准备本人正脸和侧脸原照。')
        except (OSError,ValueError) as error:messagebox.showerror('无法继续',str(error),parent=self)

    def show_measurements(self):
        if self.result is None:
            messagebox.showinfo('请先处理','请完成照片检查与体型处理后查看。',parent=self);return
        fit=self.result[0].report.get('measurement_fit')
        if not fit:
            messagebox.showinfo('未填写尺寸','本轮没有尺寸约束；模型来自体型选择和已确认照片。',parent=self);return
        lines=['项目：输入 / 模型 / 差值（cm）']
        for k,row in fit['rows'].items():
            if row['applied']:lines.append(f"{flow.MEASURES[k]}：{row['input_cm']:g} / {row['model_cm']:.2f} / {row['difference_cm']:+.2f}")
            else:lines.append(flow.MEASURES[k]+'：未填，保留估计')
        lines+=['','模型数值拟合不等于真人测量精度；测量位置采用模板对应点。']
        lines+=fit.get('warnings',[])
        messagebox.showinfo('尺寸拟合结果','\n'.join(lines),parent=self)

    def load_from(self,path):
        legacy=Path(path).suffix.lower()=='.zip'
        if legacy:
            s=shapes.load_settings(path);state=flow.new_state();state['basic'].update(gender='male',height_cm=f'{s.height_cm:g}',weight_kg=f'{s.weight_kg:g}')
            state['choices']={k:getattr(s,k) for k in shapes.GROUPS if k!='neck'}
            if s.body_family!='auto':state['choices']['family']=s.body_family
            photos={}
        else:state,photos=flow.load_project(path)
        self.cancel_transition();self.invalidate();self.state=state;self.assets=photos;self.render()
        if legacy:self.status.set('旧选择已作为草稿导入。请补年龄、照片并重选肩颈，旧微调不沿用。')

    def open_project(self):
        path=filedialog.askopenfilename(parent=self,filetypes=[('人物建档 / 旧体型选择','*.veylfit *.zip')])
        if not path:return
        try:self.load_from(path)
        except Exception as error:messagebox.showerror('无法打开',str(error),parent=self)

    def destroyed(self,event):
        if event.widget is self:
            self.closed=True;self.cancel_transition();self.after_cancel(self.poll_id)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--project',type=Path)
    parser.add_argument('--review-photo-fit',action='store_true')
    parser.add_argument('--check-startup',action='store_true');args=parser.parse_args()
    root=tk.Tk();root.title('映衣间 · 建档与照片校正 v5');root.geometry('1120x820');root.minsize(1020,790)
    tab=IntakeTab(root);tab.pack(fill='both',expand=True)
    if args.project:
        try:tab.load_from(args.project)
        except Exception as error:
            if args.check_startup:root.destroy();raise
            messagebox.showerror('无法打开档案',str(error),parent=root)
    if args.review_photo_fit and args.project:
        flow.validate_complete(tab.state,tab.assets);tab.state['step']=8;tab.render()
        if not args.check_startup:root.after(200,tab.process)
    if args.check_startup:
        import json
        root.withdraw();root.update()
        print(json.dumps({'startup':'ok','step':tab.step,'photo_count':len(tab.assets),
                          'choice_count':len(tab.state['choices']),'title':root.title()},ensure_ascii=True))
        root.destroy()
    else:root.mainloop()
