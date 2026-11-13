"""Two-module Windows prototype, shared local person project, manual generation."""
from pathlib import Path
from copy import deepcopy
import argparse,json,tkinter as tk
from tkinter import ttk,filedialog,messagebox
from concurrent.futures import ThreadPoolExecutor
from identity_ui import IdentityTab
from identity_flow import IdentityProject
from intake_ui import IntakeTab
import intake_flow

class DesktopIntake(IntakeTab):
    def save_dialog(self,with_result):
        if with_result and self.result is None:
            self.status.set('请先等待本轮处理完成。');return
        self.intake_save(with_result)

    def intake_save(self,with_result=False):
        if not self.app.commit_draft():return
        if self.result:
            self.app.identity_tab.project.attach_intake(self.state,self.assets,self.result)
        self.app.identity_tab.save_project()

    def open_project(self):
        if not self.app.identity_tab.can_discard():return
        path=filedialog.askopenfilename(parent=self,filetypes=[('人物档案及旧建档','*.veylfit-person *.veylfit *.fitlogic')])
        if not path:return
        try:
            if Path(path).suffix.lower()=='.veylfit':
                state,photos=intake_flow.load_project(path)
                p=IdentityProject();p.attach_intake(state,photos)
                self.app.identity_tab.project=p;self.app.identity_tab.project_path=None
                self.app.identity_tab.refresh(True)
            else:
                self.app.identity_tab.project=IdentityProject.load(path)
                self.app.identity_tab.project_path=path;self.app.identity_tab.dirty=False
                self.app.identity_tab.refresh()
            self.app.show_intake()
        except Exception as e:messagebox.showerror('无法打开人物档案',str(e),parent=self)

class DesktopIdentity(IdentityTab):
    def build_sources(self):
        super().build_sources()
        # Those two buttons belong to the old engineering workbench.
        for w in self.source_page.winfo_children()[0].winfo_children(): w.destroy()

    def refresh(self,dirty=False):
        super().refresh(dirty)
        if hasattr(self.app,'intake'):
            self.app.bind_project()
            self.app.update_summary()

    def can_discard(self):
        if hasattr(self.app,'intake') and not self.app.commit_draft(): return False
        return super().can_discard()

    def save_project(self):
        if hasattr(self.app,'intake') and not self.app.commit_draft(): return False
        return super().save_project()

class DesktopApp:
    def __init__(self,root):
        self.root=root;self.busy=False;self.bound=None;self.intake_dirty=False;self.switching=False
        self.pool=ThreadPoolExecutor(max_workers=1)
        root.title('映衣间 · Veylfit');root.geometry('1180x900');root.minsize(1080,820)
        nav=ttk.Frame(root,padding=12);nav.pack(fill='x')
        ttk.Label(nav,text='映衣间',font=('Microsoft YaHei UI',20,'bold')).pack(side='left',padx=(0,25))
        ttk.Button(nav,text='① 人物建档',command=self.show_intake).pack(side='left',padx=5)
        ttk.Button(nav,text='面部与体型确认',command=lambda:self.show_identity('a')).pack(side='left',padx=5)
        ttk.Button(nav,text='② 试衣搭配',command=lambda:self.show_identity('b')).pack(side='left',padx=5)
        ttk.Button(nav,text='人物档案摘要',command=self.show_profile).pack(side='right')
        self.summary=tk.StringVar();ttk.Label(root,textvariable=self.summary,padding=(15,3)).pack(fill='x')
        self.status=tk.StringVar(value='生图继续手动导出素材包、生成后导回；不会自动上传。')
        ttk.Label(root,textvariable=self.status,padding=10).pack(side='bottom',fill='x')
        self.content=ttk.Frame(root);self.content.pack(fill='both',expand=True)
        self.identity_tab=DesktopIdentity(self.content,self)
        self.intake=DesktopIntake(self.content,app=self)
        self.identity_tab.steps.bind('<<NotebookTabChanged>>',self.page_changed,add=True)
        self.bind_project();self.show_intake();root.protocol('WM_DELETE_WINDOW',self.close)

    def bind_project(self):
        p=self.identity_tab.project
        if self.bound is p:return
        self.bound=p
        restored=p.restore_intake()
        self.intake.cancel_transition();self.intake.generation+=1;self.intake.result=None;self.intake.busy=False
        self.intake.state,self.intake.assets=restored if restored else (intake_flow.new_state(),{})
        # A saved result is regenerated only on request, never treated as current geometry.
        if self.intake.state['step']==8:self.intake.state['step']=0
        self.intake.render();self.intake_dirty=False

    def intake_changed(self):
        self.intake_dirty=True
        if hasattr(self,'identity_tab'):self.identity_tab.dirty=True

    def commit_draft(self):
        if self.intake.busy:
            self.status.set('正在处理建档照片，请完成后再保存或切换。');return False
        try:
            self.intake.capture()
            if self.intake_dirty:
                self.identity_tab.project.attach_intake(self.intake.state,self.intake.assets,self.intake.result)
                self.identity_tab.dirty=True;self.intake_dirty=False
            return True
        except (ValueError,OSError) as e:
            messagebox.showerror('请检查人物资料',str(e),parent=self.root);return False

    def accept_intake(self):
        self.intake.capture()
        self.identity_tab.project.attach_intake(self.intake.state,self.intake.assets,self.intake.result)
        self.intake_dirty=False;self.identity_tab.dirty=True
        self.show_identity('a');self.identity_tab.steps.select(self.identity_tab.source_page)
        self.status.set('基本资料、部位选择、补充尺寸和正侧照片已交接；请准备面部参考并确认人物。')

    def show_intake(self):
        if self.busy:return
        self.bind_project();self.identity_tab.pack_forget();self.intake.pack(fill='both',expand=True)
        self.update_summary()

    def show_identity(self,module):
        if self.busy or not self.commit_draft():return
        t=self.identity_tab;t.refresh()
        self.intake.pack_forget();t.pack(fill='both',expand=True)
        self.arrange(module)
        t.steps.select(t.tryon_page if module=='b' else t.source_page)

    def arrange(self,module):
        t=self.identity_tab;self.switching=True
        wanted=(t.tryon_page,t.results_page) if module=='b' else (t.source_page,t.calibration_page,t.review_page)
        for page in (t.source_page,t.calibration_page,t.review_page,t.tryon_page,t.results_page):
            t.steps.tab(page,state='normal' if page in wanted else 'hidden')
        self.switching=False;self.module=module

    def page_changed(self,event=None):
        if self.switching:return
        t=self.identity_tab;selected=t.steps.select()
        if not selected:return
        module='b' if selected in (str(t.tryon_page),str(t.results_page)) else 'a'
        if getattr(self,'module',None)!=module:self.arrange(module)

    def update_summary(self):
        p=self.identity_tab.project.profile_snapshot();b=p['basic']
        vals=[f"{b[k]:g}{unit}" for k,unit in (('height_cm','cm'),('weight_kg','kg'),('age_years','岁')) if b[k] is not None]
        self.summary.set('当前人物 '+p['profile_id'][:8]+' · 版本 '+str(p['revision'])+' · '+
                         (' / '.join(vals) or '历史档案：基本资料待补充')+' · '+('基准已确认' if p['status']=='ready' else '待完成人物确认'))

    def show_profile(self):
        if not self.commit_draft():return
        p=self.identity_tab.project.profile_snapshot();self.update_summary()
        win=tk.Toplevel(self.root);win.title('人物档案 · 只读摘要');win.geometry('760x620')
        text=tk.Text(win,wrap='word',font=('Microsoft YaHei UI',11));text.pack(fill='both',expand=True)
        b=p['basic'];lines=['档案编号：'+p['profile_id'],f"版本：{p['revision']}",
            '性别：'+{'male':'男性','female':'女性',None:'未记录'}.get(b['gender'],'未记录')]
        for k,label in (('height_cm','身高 cm'),('weight_kg','体重 kg'),('age_years','年龄')):lines.append(f"{label}：{b[k] if b[k] is not None else '未记录'}")
        lines+=['','补充尺寸（用户填写；是否应用取决于本轮处理结果）：']
        for k,label in intake_flow.MEASURES.items():
            m=p['measurements'][k];lines.append(label+'：'+(str(m['value'])+' cm · '+('已应用，模型 '+str(m['model_cm'])+' cm' if m['applied_to_model'] else '待处理 / 未核验') if m['value'] is not None else '未填写'))
        lines+=['','体型选项：'+json.dumps(p['shape_choices'],ensure_ascii=False),
            '参考素材：'+str(len(p['references']))+' 项','已确认人物角度：'+', '.join(p['confirmed_baselines']),
            '', '旧档案缺失资料保持未知；不从图片、文件名或体型猜测。',
            '试衣读取人物版本；衣物、配色与结果复核不会改变真实体型。']
        text.insert('1.0','\n'.join(lines));text.configure(state='disabled')

    def task(self,fn,callback,working):
        if self.busy:return
        self.busy=True;self.status.set(working);future=self.pool.submit(fn)
        def poll():
            if not future.done():self.root.after(80,poll);return
            self.busy=False
            try:callback(future.result())
            except Exception as e:messagebox.showerror('处理未完成',str(e),parent=self.root)
        self.root.after(80,poll)

    def close(self):
        if self.busy or self.intake.busy:
            self.status.set('请等待本机处理完成后关闭。');return
        if not self.identity_tab.can_discard():return
        self.pool.shutdown(wait=False);self.root.destroy()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--person',type=Path);parser.add_argument('--check-startup',action='store_true')
    parser.add_argument('--project',type=Path);parser.add_argument('--review-photo-fit',action='store_true')
    args=parser.parse_args();root=tk.Tk()
    if args.check_startup:root.withdraw()
    app=DesktopApp(root)
    if args.project:
        state,photos=intake_flow.load_project(args.project)
        p=IdentityProject();p.attach_intake(state,photos)
        app.identity_tab.project=p;app.identity_tab.refresh(True);app.show_intake()
        if args.review_photo_fit:
            intake_flow.validate_complete(app.intake.state,app.intake.assets)
            app.intake.state['step']=8;app.intake.render()
            if not args.check_startup:root.after(200,app.intake.process)
    if args.person:
        app.identity_tab.project=IdentityProject.load(args.person);app.identity_tab.project_path=args.person
        app.identity_tab.refresh();app.show_identity('b')
    if args.check_startup:
        root.update();print(json.dumps(dict(startup='ok',modules=2,profile=app.identity_tab.project.profile_snapshot()['revision'],jobs=len(app.identity_tab.project.state['tryon_jobs']))))
        app.pool.shutdown(wait=False);root.destroy()
    else:root.mainloop()

if __name__=='__main__':main()
