from tkinter import ttk 

THEME = "clam"

def apply_theme(root):
    style = ttk.Style(root)
    if THEME in style.theme_names():
        style.theme_use(THEME)
    return style