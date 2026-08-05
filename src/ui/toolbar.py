from tkinter import ttk
from tkinter import BooleanVar


class Toolbar(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        self.build()

    def button(self, text, command):
        b = ttk.Button(self, text=text, command=command, style="Toolbar.TButton")
        b.pack(side="left", padx=3)
        return b

    def build(self):
        self.button("Open", self.app.open_archive)
        self.button("Extract", self.app.extract_all)
        self.button("Extract Selected", self.app.extract_selected)
        self.button("Repack", self.app.repack)
        self.button("Folder", self.app.open_extract_folder)

        ttk.Separator(self, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Checkbutton(
            self, text="Expand TIM Packs", variable=self.app.expand_tims
        ).pack(side="left", padx=5)
        ttk.Checkbutton(
            self, text="Expand Sample Banks", variable=self.app.expand_inst
        ).pack(side="left", padx=5)

        ttk.Separator(self, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(self, text="Names:").pack(side="left", padx=(4, 2))
        self.filelist_combo = ttk.Combobox(
            self,
            textvariable=self.app.filelist_var,
            values=self.app.filelist_choices,
            width=22,
            state="readonly",
        )
        self.filelist_combo.pack(side="left", padx=2)
        self.filelist_combo.bind("<<ComboboxSelected>>", self.app.on_filelist_changed)
        ttk.Button(self, text="Load list…", command=self.app.load_custom_filelist).pack(
            side="left", padx=2
        )