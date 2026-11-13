"""Original-photo marker review, no white-model preview."""
from copy import deepcopy
from io import BytesIO
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageTk
import photo_fit as pf

class PhotoReview(tk.Toplevel):
    def __init__(self,parent,photos,proposal,on_apply):
        super().__init__(parent);self.title('映衣间 · 检查照片校正');self.geometry('1010x790')
        self.cal=deepcopy(proposal);self.photos=photos;self.on_apply=on_apply;self.refs={};self.canvases={};self.scales={};self.variables={};self.dragging=None
        ttk.Label(self,text='拖动圆点，标出头顶、脚底，以及腹部、臀部、单侧大腿同一截面的两端。',padding=10).pack(anchor='w')
        ttk.Label(self,text='橙色＝腹部；蓝色＝臀部；绿色＝单腿。只标身体，不把手臂当躯干。宽松衣物仅作上限；遮挡就不采用。\n这是人工辅助校正：倾斜只做二维旋转，不能消除俯仰透视。发顶/鞋底会影响比例，请尽量选头皮位置和脚掌底。',padding=8).pack(anchor='w')
        columns=ttk.Frame(self);columns.pack(fill='both',expand=True)
        for col,role in enumerate(('front','side')):
            box=ttk.Frame(columns,padding=8);box.grid(row=0,column=col,sticky='nsew');columns.columnconfigure(col,weight=1)
            ttk.Label(box,text='正面' if role=='front' else '侧面',font=('Microsoft YaHei UI',13,'bold')).pack()
            view=self.cal['views'][role];im=Image.open(BytesIO(photos[role])).convert('RGB');im=im.resize(tuple(view['size_px']))
            self.refs[role+'original']=im;sc=min(460/im.width,470/im.height);self.scales[role]=sc
            canvas=tk.Canvas(box,width=round(im.width*sc),height=round(im.height*sc),highlightthickness=0);canvas.pack();self.canvases[role]=canvas
            canvas.bind('<Button-1>',lambda e,r=role:self.start(e,r));canvas.bind('<B1-Motion>',lambda e,r=role:self.move(e,r));canvas.bind('<ButtonRelease-1>',lambda e:self.end())
            self.variables[role]={}
            for key,(label,_) in pf.REGIONS.items():
                line=ttk.Frame(box);line.pack(fill='x',pady=3);ttk.Label(line,text=label,width=17).pack(side='left')
                var=tk.StringVar(value=pf.MODES[view['rows'][key]['mode']]);self.variables[role][key]=var
                ttk.Combobox(line,values=list(pf.MODES.values()),textvariable=var,state='readonly',width=24).pack(side='right')
            line=ttk.Frame(box);line.pack(fill='x');ttk.Label(line,text='画面倾斜角（±10°）').pack(side='left')
            var=tk.StringVar(value=str(view['roll_degrees']));self.variables[role]['roll']=var;ttk.Entry(line,textvariable=var,width=8).pack(side='right')
            self.draw(role)
        self.status=tk.StringVar();ttk.Label(self,textvariable=self.status,foreground='#aa4422',wraplength=950,padding=8).pack(anchor='w')
        footer=ttk.Frame(self,padding=8);footer.pack(fill='x');ttk.Button(footer,text='取消',command=self.destroy).pack(side='left');ttk.Button(footer,text='标记已检查，应用体型校正',command=self.apply).pack(side='right')
        self.transient(parent.winfo_toplevel());self.grab_set()

    def points(self,role):
        v=self.cal['views'][role]
        yield 'crown',v['crown'];yield 'ground',v['ground']
        for key,row in v['rows'].items():
            for endpoint in ('a','b'):yield (key,endpoint),row[endpoint]
    def start(self,event,role):
        sc=self.scales[role];key,p=min(self.points(role),key=lambda kv:(kv[1][0]*sc-event.x)**2+(kv[1][1]*sc-event.y)**2)
        if (p[0]*sc-event.x)**2+(p[1]*sc-event.y)**2<24**2:self.dragging=(role,key)
    def move(self,event,role):
        if not self.dragging or self.dragging[0]!=role:return
        key=self.dragging[1];v=self.cal['views'][role];sc=self.scales[role];w,h=v['size_px'];p=[max(0,min(w-1,event.x/sc)),max(0,min(h-1,event.y/sc))]
        if isinstance(key,str):v[key]=p
        else:v['rows'][key[0]][key[1]]=p
        self.cal['reviewed']=False;self.draw(role)
    def end(self):self.dragging=None
    def draw(self,role):
        im=pf.overlay(self.refs[role+'original'],self.cal['views'][role]);sc=self.scales[role];im=im.resize((round(im.width*sc),round(im.height*sc)))
        self.refs[role+'display']=ImageTk.PhotoImage(im);c=self.canvases[role];c.delete('all');c.create_image(0,0,anchor='nw',image=self.refs[role+'display'])
    def apply(self):
        try:
            for role,vs in self.variables.items():
                v=self.cal['views'][role];v['roll_degrees']=float(vs['roll'].get())
                for key in pf.REGIONS:v['rows'][key]['mode']=next(k for k,label in pf.MODES.items() if label==vs[key].get())
            self.cal['reviewed']=True;self.cal['reviewer']='user';pf.validate(self.cal,self.photos,self.cal['height_cm'])
            if not pf.observations(self.cal):raise ValueError('请至少采用一条清楚的轮廓，或取消保留基础体型。')
            self.on_apply(self.cal);self.destroy()
        except (ValueError,KeyError,TypeError) as error:self.status.set(str(error))
