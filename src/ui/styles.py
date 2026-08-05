from tkinter import ttk


ACCENT = "#3b82f6"

BACKGROUND = "#202124"

PANEL = "#2b2d31"

TEXT = "#ffffff"

SUBTEXT = "#b8b8b8"

TREE_BG = "#252526"

TREE_SELECTED = "#0e639c"


def setup_styles(style):

    style.configure(
        ".",
        font=("Segoe UI",10)
    )

    style.configure(
        "Header.TLabel",
        font=("Segoe UI",22,"bold")
    )

    style.configure(
        "SubHeader.TLabel",
        font=("Segoe UI",10),
        foreground=SUBTEXT
    )

    style.configure(
        "Section.TLabel",
        font=("Segoe UI",11,"bold")
    )

    style.configure(
        "Toolbar.TButton",
        padding=8
    )

    style.configure(
        "Accent.TButton",
        padding=10
    )

    style.configure(
        "Card.TFrame",
        relief="flat",
        borderwidth=1
    )

    style.configure(
        "Status.TLabel",
        font=("Segoe UI",9)
    )

    style.configure(
        "Treeview",
        rowheight=28,
        font=("Segoe UI",10)
    )

    style.configure(
        "Treeview.Heading",
        font=("Segoe UI",10,"bold")
    )

    style.map(
        "Treeview",
        background=[
            ("selected",TREE_SELECTED)
        ]
    )

    style.configure(
        "TNotebook.Tab",
        padding=(18,8)
    )