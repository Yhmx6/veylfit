import json
import tkinter as tk
from tkinter import ttk,filedialog
from fit_advice import FITS,GOALS,COLORS,MODES,validate

def fit_dialog(tab):
    p=tab.project;p.tryon_person();p.garment_info()
    try:old=p.current_fit_advice()
    except ValueError:old=None
    old=old or {};top=tk.Toplevel(tab);top.title('想要的效果与服装表现');top.geometry('660x600');top.transient(tab);top.grab_set()
    box=ttk.Frame(top,padding=16);box.pack(fill='both',expand=True)
    faithful=p.tryon_mode()=='faithful'
    ttk.Label(box,text=MODES[p.tryon_mode()]+('：保留实物原色和版型；效果/松量仅作评价期待，不能改造衣服。' if faithful else '：按用户目标提出服装方案；不是实物还原。')+'\n本地程序不自动调用AI；未知尺寸不保证实际合身。',wraplength=620).pack(anchor='w',pady=8)
    goal=tk.StringVar(value=GOALS[old.get('goal','natural')]);detail=tk.StringVar(value=old.get('goal_detail',''));color=tk.StringVar(value=COLORS[old.get('color_policy','preserve')])
    ttk.Label(box,text='想要什么效果？未选择时按自然合身处理').pack(anchor='w')
    ttk.Combobox(box,textvariable=goal,values=list(GOALS.values()),state='readonly').pack(fill='x')
    ttk.Entry(box,textvariable=detail).pack(fill='x',pady=4)
    ttk.Label(box,text='配色（导入真实衣物时默认保留原色）').pack(anchor='w')
    color_box=ttk.Combobox(box,textvariable=color,values=list(COLORS.values()),state='disabled' if faithful else 'readonly');color_box.pack(fill='x')
    if faithful:color.set(COLORS['preserve'])
    ttk.Label(box,text='松量偏好（实物模式不据此改宽衣服）' if faithful else '目标服装松量').pack(anchor='w',pady=(8,0))
    def preferences():return dict(goal=next(k for k,v in GOALS.items() if v==goal.get()),goal_detail=detail.get().strip(),color_policy=next(k for k,v in COLORS.items() if v==color.get()))
    chosen=tk.StringVar(value=FITS.get(old.get('selected'),'常规'))
    ttk.Combobox(box,textvariable=chosen,values=list(FITS.values()),state='readonly').pack(fill='x')
    fields={}
    for key,label in (('reason','选择理由'),('construction','可见衣物特征与未知项（本模式不执行改版要求）' if faithful else '衣物表现要求（肩袖、腰腹松量、下摆、内搭及开合）')):
        ttk.Label(box,text=label).pack(anchor='w',pady=(8,0));w=tk.Text(box,height=4,wrap='word');w.insert('1.0',old.get(key,''));w.pack(fill='x');fields[key]=w
    def save():
        selected=next(k for k,v in FITS.items() if v==chosen.get())
        reason=fields['reason'].get('1.0','end').strip();construction=fields['construction'].get('1.0','end').strip()
        source=old.get('source','user_preference') if reason==old.get('reason') and construction==old.get('construction') else 'user_preference'
        prefs=preferences()
        if any(prefs[k]!=old.get(k,{'goal':'natural','goal_detail':'','color_policy':'preserve'}[k]) for k in prefs):source='user_preference'
        p.set_fit_advice(old.get('recommended',selected),reason,construction,source,selected,**prefs);top.destroy()
    def load():
        path=filedialog.askopenfilename(parent=top,filetypes=[('AI松量建议','*.json')])
        if not path:return
        from pathlib import Path
        raw=Path(path).read_bytes()
        if len(raw)>16000:raise ValueError('建议文件过大。')
        try:advice=json.loads(raw)
        except (ValueError,UnicodeError):raise ValueError('建议文件不是有效JSON。')
        if advice is None:raise ValueError('建议内容为空。')
        validate(advice,p.tryon_person(),p.garment_info(),p.tryon_mode())
        if any(advice.get(k,{'goal':'natural','goal_detail':'','color_policy':'preserve'}[k])!=v for k,v in preferences().items()):raise ValueError('AI建议与当前选择的效果或配色不一致，请重新导出判断包。')
        p.state['fit_advice']=advice;p.event('fit_advice_imported',advice=advice);top.destroy()
    def export():
        path=filedialog.asksaveasfilename(parent=top,defaultextension='.zip',initialfile='视觉松量判断包.zip',filetypes=[('松量判断素材','*.zip')])
        if path:p.fit_analysis_package(path,**preferences())
    row=ttk.Frame(box);row.pack(fill='x',pady=10)
    ttk.Button(row,text='导出AI判断包',command=lambda:tab.guard(export)).pack(side='left',padx=4)
    ttk.Button(row,text='导入AI建议',command=lambda:tab.guard(load)).pack(side='left')
    ttk.Button(row,text='保存到生图流程',command=lambda:tab.guard(save)).pack(side='right')
