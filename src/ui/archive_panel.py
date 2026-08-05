from tkinter import *
from tkinter import ttk


class ArchivePanel(ttk.Frame):

    columns = (
        "index",
        "name",
        "type",
        "extension",
        "size",
        "compressed"
    )

    def __init__(self, parent, app):
        super().__init__(parent, padding=12)
        self.app = app
        self.search_var = StringVar()
        self._all_rows = []
        self.build()

    def build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        title = ttk.Label(
            self,
            text="Archive Contents",
            style="Section.TLabel"
        )
        title.grid(
            row=0,
            column=0,
            sticky="w"
        )
        self.search = ttk.Entry(
            self,
            textvariable=self.search_var
        )
        self.search.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(8, 8)
        )

        self.search.bind(
            "<KeyRelease>",
            self.filter_rows
        )

        container = ttk.Frame(self)

        container.grid(
            row=2,
            column=0,
            sticky="nsew"
        )

        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            container,
            columns=self.columns,
            show="headings",
            selectmode="extended"
        )

        self.tree.heading(
            "index",
            text="#",
            command=lambda: self.sort("index", int)
        )

        self.tree.heading(
            "name",
            text="Name",
            command=lambda: self.sort("name", str)
        )

        self.tree.heading(
            "type",
            text="Type",
            command=lambda: self.sort("type", str)
        )

        self.tree.heading(
            "extension",
            text="Ext",
            command=lambda: self.sort("extension", str)
        )

        self.tree.heading(
            "size",
            text="Size",
            command=lambda: self.sort("size", int)
        )

        self.tree.heading(
            "compressed",
            text="Compressed",
            command=lambda: self.sort("compressed", int)
        )

        self.tree.column(
            "index",
            width=55,
            anchor=CENTER
        )

        self.tree.column(
            "name",
            width=250
        )

        self.tree.column(
            "type",
            width=160
        )

        self.tree.column(
            "extension",
            width=70,
            anchor=CENTER
        )

        self.tree.column(
            "size",
            width=90,
            anchor=E
        )

        self.tree.column(
            "compressed",
            width=110,
            anchor=E
        )

        vs = ttk.Scrollbar(
            container,
            orient="vertical",
            command=self.tree.yview
        )

        hs = ttk.Scrollbar(
            container,
            orient="horizontal",
            command=self.tree.xview
        )

        self.tree.configure(
            yscrollcommand=vs.set,
            xscrollcommand=hs.set
        )

        self.tree.grid(
            row=0,
            column=0,
            sticky="nsew"
        )

        vs.grid(
            row=0,
            column=1,
            sticky="ns"
        )

        hs.grid(
            row=1,
            column=0,
            sticky="ew"
        )

        self.tree.bind(
            "<<TreeviewSelect>>",
            self.on_select
        )

        self.menu = Menu(
            self,
            tearoff=False
        )

        self.menu.add_command(
            label="Preview",
            command=self.preview_selected
        )

        self.menu.add_separator()

        self.menu.add_command(
            label="Extract Selected",
            command=self.extract_selected
        )

        self.menu.add_separator()

        self.menu.add_command(
            label="Copy Name",
            command=self.copy_name
        )

        self.tree.bind(
            "<Button-3>",
            self.popup
        )

    def populate(self, rows):

        self.tree.delete(
            *self.tree.get_children()
        )

        self._all_rows = list(rows)

        for row in rows:

            self.tree.insert(
                "",
                END,
                iid=str(row["index"]),
                values=(
                    row["index"],
                    row["name"],
                    row["type"],
                    row["extension"],
                    row["size"],
                    row["compressed"]
                )
            )

    def selected_indices(self):

        return [
            int(i)
            for i in self.tree.selection()
        ]

    def selected_row(self):

        ids = self.selected_indices()

        if not ids:
            return None

        idx = ids[0]

        for row in self._all_rows:

            if row["index"] == idx:

                return row

        return None

    def filter_rows(self, event=None):

        text = self.search_var.get().lower()

        self.tree.delete(
            *self.tree.get_children()
        )

        for row in self._all_rows:

            if (
                text in row["name"].lower()
                or
                text in row["type"].lower()
                or
                text in row["extension"].lower()
            ):

                self.tree.insert(
                    "",
                    END,
                    iid=str(row["index"]),
                    values=(
                        row["index"],
                        row["name"],
                        row["type"],
                        row["extension"],
                        row["size"],
                        row["compressed"]
                    )
                )

    def sort(self, column, cast):

        rows = []

        for child in self.tree.get_children():

            value = self.tree.set(
                child,
                column
            )

            try:
                value = cast(value)

            except Exception:
                pass

            rows.append(
                (
                    value,
                    child
                )
            )

        rows.sort()

        for index, (_, item) in enumerate(rows):

            self.tree.move(
                item,
                "",
                index
            )

    def popup(self, event):

        item = self.tree.identify_row(
            event.y
        )

        if item:

            self.tree.selection_set(item)

            self.menu.post(
                event.x_root,
                event.y_root
            )

    def preview_selected(self):

        ids = self.selected_indices()

        if ids:

            self.app.show_preview(
                ids[0]
            )

    def extract_selected(self):

        self.app.extract_selected()

    def copy_name(self):

        row = self.selected_row()

        if row is None:
            return

        self.clipboard_clear()

        self.clipboard_append(
            row["name"]
        )

    def on_select(self, event=None):

        ids = self.selected_indices()

        if ids:

            self.app.show_preview(
                ids[0]
            )

    def clear(self):

        self.tree.delete(
            *self.tree.get_children()
        )

        self._all_rows.clear()

        self.search_var.set("")