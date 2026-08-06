import sys

if __name__ == "__main__":
    if "--qt" in sys.argv or True:
        from gtarcexplorer.gui_qt import run
        run()
    else:
        from gtarcexplorer.gui import GTArcExplorer
        app = GTArcExplorer()
        app.mainloop()