from tkinter import ttk

from . import icons


class Toolbar(ttk.Frame):

    def __init__(self,parent,app):

        super().__init__(parent,padding=8)

        self.app = app

        self.build()

    def button(self,text,command):

        b = ttk.Button(self,text=text,command=command,style="Toolbar.TButton")

        b.pack(side="left",padx=3)

        return b
    
    def build(self):

        self.button(f"{icons.OPEN} Open",self.app.open_archive)

        self.button(f"{icons.EXTRACT} Extract",self.app.extract_all)

        self.button(f"{icons.REPACK} Repack",self.app.repack)

        self.button(f"{icons.FOLDER} Folder",self.app.open_extract_folder)

        ttk.Separator(self,orient="vertical").pack(side="left",fill="y",padx=8)

        ttk.Checkbutton(self,text="Expand TIM Packs",variable=self.app.expand_tims).pack(side="left",padx=5)

        ttk.Checkbutton(self,text="Expand Sample Banks",variable=self.app.expand_inst).pack(side="left",padx=5)