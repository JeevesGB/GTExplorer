from tkinter import *
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText


class PreviewPanel(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent, padding=10)
        self.preview_image = None
        self.build()

    def build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = ttk.Frame(self)
        header.grid(row=0,column=0,sticky="ew",pady=(0,10))
        header.columnconfigure(0, weight=1)
        self.filename = ttk.Label(header,text="No file selected",style="Section.TLabel")
        self.filename.grid(row=0,column=0,sticky="w")
        self.filesize = ttk.Label(header,text="")
        self.filesize.grid(row=0,column=1,sticky="e")
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1,column=0,sticky="nsew")
        self.build_summary()
        self.build_preview()
        self.build_hex()

    def build_summary(self):
        page = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(page,text="Summary")
        page.columnconfigure(1, weight=1)
        self.labels = {}
        fields = [
            "Type",
            "Extension",
            "Size",
            "Compressed",
            "Palette",
            "Resolution",
            "Vertices",
            "Colours"
        ]
        for row, field in enumerate(fields):
            ttk.Label(page,text=field + ":",width=15,anchor="w",font=("Segoe UI",10,"bold")).grid(row=row,column=0,sticky="nw",pady=4)
            value = ttk.Label(page,text="-",anchor="w",justify=LEFT)
            value.grid(row=row,column=1,sticky="ew",pady=4)
            self.labels[field] = value


    def build_preview(self):
        page = ttk.Frame(self.notebook)
        self.notebook.add(page,text="Preview")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=3)
        page.rowconfigure(1, weight=2)
        self.image_canvas = Canvas(page,background="#222",highlightthickness=0)
        self.image_canvas.grid(row=0,column=0,sticky="nsew")
        self.text = ScrolledText(page,wrap="none",font=("Consolas",10))
        self.text.grid(row=1,column=0,sticky="nsew")


    def build_hex(self):
        page = ttk.Frame(self.notebook)
        self.notebook.add(page,text="Hex")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        self.hex = ScrolledText(page,wrap="none",font=("Consolas",10))
        self.hex.grid(row=0,column=0,sticky="nsew")


    def clear(self):

        self.filename.config(text="No file selected")
        self.filesize.config(text="")
        for label in self.labels.values():
            label.config(text="-")
        self.text.delete("1.0",END)
        self.hex.delete("1.0",END)
        self.image_canvas.delete("all")


    def set_title(self,filename,size):
        self.filename.config(text=filename)
        self.filesize.config(text=f"{size:,} bytes")


    def set_metadata(self,**kwargs):
        for key, value in kwargs.items():
            if key in self.labels:
                self.labels[key].config(text=value)


    def set_preview_text(self,text):
        self.text.delete("1.0",END)
        self.text.insert(END,text)


    def set_hex(self,text):
        self.hex.delete("1.0",END)
        self.hex.insert(END,text)


    def set_image(self,photo):
        self.preview_image = photo
        self.image_canvas.delete("all")
        if photo is None:
            self.image_canvas.create_text(
                200,
                100,
                text="No Preview",
                fill="white",
                font=("Segoe UI",12)
            )
            return
        w = photo.width()
        h = photo.height()
        cw = max(self.image_canvas.winfo_width(),1)
        ch = max(self.image_canvas.winfo_height(),1)
        x = max((cw - w)//2,0)
        y = max((ch - h)//2,0)
        self.image_canvas.create_image(x,y,image=photo,anchor="nw")
