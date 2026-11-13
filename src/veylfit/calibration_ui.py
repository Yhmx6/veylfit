"""Guided body -> front identity -> side identity -> frozen reference workflow."""
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from PIL import ImageTk

class CalibrationPanel(ttk.Frame):
    def __init__(self,parent,owner):
        super().__init__(parent,padding=12);self.owner=owner;self.photos=[];self.stage='body'
        self.heading=tk.StringVar();ttk.Label(self,textvariable=self.heading,font=('Microsoft YaHei UI',15,'bold')).pack(anchor='w')
        ttk.Label(self,text='① 确认体型 → ② 原照校准正脸 → ③ 原照校准侧脸 → ④ 固定后试衣\n生图仍手动进行；每阶段导出素材，生成后导回。换衣不重建人物。',padding=(0,8)).pack(anchor='w')
        self.message=tk.StringVar();ttk.Label(self,textvariable=self.message,wraplength=940).pack(anchor='w',pady=6)
        self.views=ttk.Frame(self);self.views.pack(fill='both',expand=True)
        self.buttons=ttk.Frame(self);self.buttons.pack(fill='x',pady=8)
        self.checks=ttk.Frame(self);self.checks.pack(fill='x')
        self.face=tk.BooleanVar();self.kept=tk.BooleanVar()
        self.confirm=ttk.Button(self,text='确认并继续',command=lambda:owner.guard(self.approve));self.confirm.pack(anchor='e',pady=8)

    def refresh(self):
        for box in (self.views,self.buttons,self.checks):
            for w in box.winfo_children():w.destroy()
        self.photos=[];self.face.set(False);self.kept.set(False);p=self.owner.project
        def button(text,fn):ttk.Button(self.buttons,text=text,command=lambda:self.owner.guard(fn)).pack(side='left',padx=4,pady=2)
        def show(key,label):
            box=ttk.Frame(self.views);box.pack(side='left',expand=True,fill='both');ttk.Label(box,text=label).pack()
            if key:
                im=p.image(key);im.thumbnail((310,330));photo=ImageTk.PhotoImage(im);self.photos.append(photo);ttk.Label(box,image=photo).pack()
            else:ttk.Label(box,text='等待导入',padding=30).pack()
        if not p.state['refs_approved']:
            self.heading.set('先准备本人原照及后台体型参考');self.message.set('到“素材准备”导入本人正脸、侧脸原照和后台体型参考，并确认来源。');self.confirm.configure(state='disabled')
            button('前往素材准备',lambda:self.owner.steps.select(self.owner.source_page));return
        c=p.calibration();self.stage='body' if not c['body']['approved'] else 'front' if not(c['front'] and c['front']['approved']) else 'side' if not(c['side'] and c['side']['approved']) else 'ready'
        self.heading.set({'body':'1 / 4 · 先确认体型','front':'2 / 4 · 校准正脸','side':'3 / 4 · 校准侧脸','ready':'4 / 4 · 已完成逐角度确认'}[self.stage])
        self.confirm.configure(state='normal',text='确认并继续')
        if self.stage=='body':
            self.message.set('先导入同一衣着、背景下的正面及正侧着装图，只判断体型。三张候选可作为备选，不必每次重新比较三张。')
            for angle,label in (('front','正面体型'),('side','正侧体型')):
                show(c['body']['views'].get(angle),label);button('导入'+label,lambda a=angle:self.import_body(a))
            button('导出体型参考生成包',lambda:self.export('body'))
            ttk.Checkbutton(self.checks,text='两张图的腹部、臀腿和整体比例接近本人，确认体型',variable=self.kept).pack(anchor='w')
        elif self.stage in ('front','side'):
            stage=self.stage;item=c[stage]
            self.message.set('原始照片是身份依据；只校正头脸，检查体型、衣物和背景是否被连带改变。'+('原始微侧脸不能提供全部90度轮廓，生成侧面仍需本人判断。' if stage=='side' else '先把这一张正脸做好，再进入侧脸。'))
            show(p.state['refs']['face_'+stage]['asset'],'原始面部参考');show(item['asset'] if item else c['body']['views'][stage],'校准结果' if item else '待校准体型图')
            button('导出本阶段校准包',lambda:self.export(stage));button('导入校准结果',lambda:self.import_result(stage))
            if stage=='side':button('退回正脸重新确认',lambda:p.approve_calibration('front',False,False))
            button('退回体型重新确认',lambda:p.approve_body_views(False))
            ttk.Checkbutton(self.checks,text='这一角度的脸像本人，确认',variable=self.face).pack(anchor='w')
            ttk.Checkbutton(self.checks,text='体型、衣物、姿势和背景没有明显变化',variable=self.kept).pack(anchor='w')
        else:
            self.message.set('已确认正面和正侧面。固定后，每次试衣使用对应角度的基准图；试衣结果不会自动替换基准。')
            show(c['front']['asset'],'已确认正面');show(c['side']['asset'],'已确认正侧面')
            button('重做正脸',lambda:p.approve_calibration('front',False,False));button('重做侧脸',lambda:p.approve_calibration('side',False,False));button('重做体型',lambda:p.approve_body_views(False))
            self.confirm.configure(text='固定基准并进入试衣')

    def import_body(self,angle):
        path=self.owner.choose_image()
        if path:self.owner.project.set_body_view(angle,path)
    def export(self,stage):
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.zip',initialfile='Veylfit-'+{'body':'体型','front':'正脸','side':'侧脸'}[stage]+'校准包.zip',filetypes=[('校准素材包','*.zip')])
        if path:self.owner.project.calibration_package(path,stage)
    def import_result(self,stage):
        path=self.owner.choose_image()
        if path and messagebox.askyesno('确认对应任务','这张图来自本阶段最近导出的校准素材，且是生成结果吗？',parent=self):self.owner.project.put_calibration_result(stage,path,True)
    def approve(self):
        p=self.owner.project
        if self.stage=='body':
            if not self.kept.get():raise ValueError('请先检查并确认两张图的体型。')
            p.approve_body_views(True)
        elif self.stage in ('front','side'):
            if not self.face.get() or not self.kept.get():raise ValueError('请分别确认脸部相似和体型/衣着/背景保持。')
            p.approve_calibration(self.stage,True,True)
        else:
            p.freeze_calibration('用户在本地流程依次确认体型、正脸、侧脸和画面保持。');self.owner.steps.select(self.owner.tryon_page)
