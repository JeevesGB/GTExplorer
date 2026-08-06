def diff_sizes(self):
    if not self.arc.files:
        QMessageBox.warning(self, "No archive", "Open an archive first")
        return

    folder = self.extract_dir
    if not folder or not Path(folder).is_dir():
        folder = QFileDialog.getExistingDirectory(self, "Select extract folder to compare")
        if not folder:
            return
        folder = Path(folder)

    rows = []  

    for f in self.arc.files:
        idx = f["index"]
        if f.get("real_name"):
            name = Path(f["real_name"]).name
        else:
            name = f"{f['label']}{f['ext']}"

        disk_path = folder / name
        if not disk_path.exists():
            alt = folder / f"{idx:03d}_{name}"
            if alt.exists():
                disk_path = alt

        arc_size = f.get("decomp_size") or 0
        if f.get("data") is not None:
            arc_size = len(f["data"])

        if disk_path.exists():
            disk_size = disk_path.stat().st_size
            delta = disk_size - arc_size
            if delta == 0:
                status = "same"
            elif delta > 0:
                status = "larger"
            else:
                status = "smaller"
        else:
            disk_size = None
            delta = None
            status = "missing"

        rows.append((idx, name, arc_size, disk_size, delta, status))

    self._show_diff_dialog(rows, str(folder))


def _show_diff_dialog(self, rows, folder_path: str):
    from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QDialogButtonBox

    dlg = QDialog(self)
    dlg.setWindowTitle("Size diff – Archive vs Folder")
    dlg.resize(780, 520)
    layout = QVBoxLayout(dlg)

    layout.addWidget(QLabel(f"Folder: {folder_path}"))

    table = QTableWidget()
    table.setColumnCount(6)
    table.setHorizontalHeaderLabels(["#", "Name", "Archive", "Disk", "Δ", "Status"])
    table.setRowCount(len(rows))
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    changed = 0
    for r, (idx, name, arc_sz, disk_sz, delta, status) in enumerate(rows):
        table.setItem(r, 0, QTableWidgetItem(str(idx)))
        table.setItem(r, 1, QTableWidgetItem(name))
        table.setItem(r, 2, QTableWidgetItem(f"{arc_sz:,}" if arc_sz is not None else "—"))
        table.setItem(r, 3, QTableWidgetItem(f"{disk_sz:,}" if disk_sz is not None else "—"))
        table.setItem(r, 4, QTableWidgetItem(f"{delta:+,}" if delta is not None else "—"))
        table.setItem(r, 5, QTableWidgetItem(status))

        # colour cell
        item = table.item(r, 5)
        if status == "same":
            item.setForeground(QColor("#7dcea0"))
        elif status == "larger":
            item.setForeground(QColor("#f5b041"))
            changed += 1
        elif status == "smaller":
            item.setForeground(QColor("#5dade2"))
            changed += 1
        else:  # missing
            item.setForeground(QColor("#e74c3c"))
            changed += 1

    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)
    layout.addWidget(table)

    summary = QLabel(f"{changed} difference(s)  •  {len(rows)} file(s) total")
    layout.addWidget(summary)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dlg.reject)
    buttons.accepted.connect(dlg.accept)
    layout.addWidget(buttons)

    dlg.exec()