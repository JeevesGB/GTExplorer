from tkinter import *
from tkinter import ttk


class AssetViewer(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.photo = None
        self.dragging = False
        self.last_x = 0
        self.last_y = 0
        self.build()

    def build(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self.build_toolbar()
        self.build_texture_list()
        self.build_canvas()

    def build_toolbar(self):
        bar = ttk.Frame(self, padding=8)
        bar.grid(row=0,column=0,columnspan=2,sticky="ew")
        ttk.Button(bar,text="Fit",command=self.fit).pack(side=LEFT)
        ttk.Button(bar,text="100%",command=self.reset).pack(side=LEFT,padx=3)
        ttk.Button(bar,text="＋",command=lambda:self.zoom(1.25)).pack(side=LEFT,padx=3)
        ttk.Button(bar,text="－",command=lambda:self.zoom(.80)).pack(side=LEFT,padx=3)
        ttk.Separator(bar,orient="vertical").pack(side=LEFT,fill=Y,padx=10)
        ttk.Label(bar,text="Palette").pack(side=LEFT)
        self.palette = ttk.Combobox(bar,width=6,state="readonly")
        self.palette.pack(side=LEFT,padx=5)
        self.palette.bind("<<ComboboxSelected>>",self.palette_changed)
        ttk.Label(bar,text="CLUT").pack(side=LEFT,padx=(15,0))
        self.clut = ttk.Combobox(bar,width=6,state="readonly")
        self.clut.pack(side=LEFT,padx=5)
        self.clut.bind("<<ComboboxSelected>>",self.clut_changed)
        self.zoom_label = ttk.Label(bar,text="100%")
        self.zoom_label.pack(side=RIGHT)

    def build_texture_list(self):
        left = ttk.Frame(self)
        left.grid(row=1,column=0,sticky="ns")
        ttk.Label(left,text="Textures",font=("Segoe UI",10,"bold")).pack(anchor="w",padx=8,pady=(8,4))
        self.texture_tree = ttk.Treeview(left,columns=("size",),show="tree headings",selectmode="browse",height=30)
        self.texture_tree.heading("#0",text="Texture")
        self.texture_tree.heading("size",text="Size")
        self.texture_tree.column("#0",width=170)
        self.texture_tree.column("size",width=70,anchor=E)
        scroll = ttk.Scrollbar(left,command=self.texture_tree.yview)
        self.texture_tree.configure(yscrollcommand=scroll.set)
        self.texture_tree.pack(side=LEFT,fill=BOTH,expand=True)
        scroll.pack(side=RIGHT,fill=Y)
        self.texture_tree.bind("<<TreeviewSelect>>",self.texture_selected)

    def build_canvas(self):
        right = ttk.Frame(self)
        right.grid(row=1,column=1,sticky="nsew")
        right.columnconfigure(0,weight=1)
        right.rowconfigure(0,weight=1)
        self.canvas = Canvas(right,bg="#242424",highlightthickness=0)
        self.canvas.grid(row=0,column=0,sticky="nsew")
        h = ttk.Scrollbar(right,orient="horizontal",command=self.canvas.xview)
        h.grid(row=1,column=0,sticky="ew")
        v = ttk.Scrollbar(right,orient="vertical",command=self.canvas.yview)
        v.grid(row=0,column=1,sticky="ns")
        self.canvas.configure(xscrollcommand=h.set,yscrollcommand=v.set)
        self.canvas.bind("<MouseWheel>",self.mousewheel)
        self.canvas.bind("<ButtonPress-2>",self.pan_start)
        self.canvas.bind("<B2-Motion>",self.pan_move)
        self.canvas.bind("<ButtonPress-1>",self.rotate_start)
        self.canvas.bind("<B1-Motion>",self.rotate_move)

    def set_image(self, photo):
        self.photo = photo
        self.redraw()

    def redraw(self):
        self.canvas.delete("all")
        if self.photo is None:
            self.canvas.create_text(300,200,text="No Preview",fill="white",font=("Segoe UI",14))
            return
        self.canvas.create_image(self.offset_x,self.offset_y,image=self.photo,anchor="nw")
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def populate_textures(self, textures):
        self.texture_tree.delete(*self.texture_tree.get_children())
        for i,item in enumerate(textures):
            self.texture_tree.insert("",END,iid=str(i),text=item["name"],values=(item["size"],))

    def texture_selected(self,event=None):
        sel=self.texture_tree.selection()
        if not sel:
            return
        self.app.viewer_texture_selected(int(sel[0]))

    def palette_changed(self,event=None):
        if hasattr(self.app,"viewer_palette_changed"):
            self.app.viewer_palette_changed(self.palette.current())

    def clut_changed(self,event=None):
        if hasattr(self.app,"viewer_clut_changed"):
            self.app.viewer_clut_changed(self.clut.current())

    def set_palette_count(self,count):
        self.palette["values"]=list(range(count))
        if count:
            self.palette.current(0)

    def set_clut_count(self,count):
        self.clut["values"]=list(range(count))
        if count:
            self.clut.current(0)

    def zoom(self,factor):
        self.scale*=factor
        self.zoom_label.configure(text=f"{int(self.scale*100)}%")
        if hasattr(self.app,"viewer_zoom_changed"):
            self.app.viewer_zoom_changed(self.scale)

    def fit(self):
        self.scale=1
        self.zoom_label.configure(text="Fit")
        if hasattr(self.app,"viewer_fit"):
            self.app.viewer_fit()

    def reset(self):
        self.scale=1
        self.offset_x=0
        self.offset_y=0
        self.zoom_label.configure(text="100%")
        if hasattr(self.app,"viewer_reset"):
            self.app.viewer_reset()

    def mousewheel(self,event):
        if event.delta>0:
            self.zoom(1.1)
        else:
            self.zoom(.9)

    def pan_start(self,event):
        self.canvas.scan_mark(event.x,event.y)

    def pan_move(self,event):
        self.canvas.scan_dragto(event.x,event.y,gain=1)

    def rotate_start(self,event):
        self.last_x=event.x
        self.last_y=event.y

    def rotate_move(self,event):
        dx=event.x-self.last_x
        dy=event.y-self.last_y
        self.last_x=event.x
        self.last_y=event.y
        if hasattr(self.app,"viewer_rotate"):
            self.app.viewer_rotate(dx,dy)