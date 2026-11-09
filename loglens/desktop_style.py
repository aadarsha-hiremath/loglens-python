"""Desktop theme and small reusable Tk views."""

import tkinter as tk
from tkinter import font, ttk

from .parsing import LEVELS

LIGHT = ("#f3f5f8", "#ffffff", "#172a39", "#506471", "#086a68", "#d5dfe3", "#e0f1ef")
DARK = ("#182229", "#223039", "#edf3f5", "#b3c3ca", "#79d4ca", "#40515c", "#294943")


def apply_style(root: tk.Tk, theme: str, size: int) -> tuple[str, ...]:
    colors = DARK if theme == "Dark" else LIGHT
    bg, surface, ink, muted, accent, edge, selected = colors
    style = ttk.Style(root)
    style.theme_use("clam")
    family = font.nametofont("TkDefaultFont").actual("family")
    font.nametofont("TkDefaultFont").configure(size=size)
    root.configure(background=bg)
    style.configure(".", font=(family, size), background=bg, foreground=ink,
                    fieldbackground=surface, bordercolor=edge, lightcolor=edge, darkcolor=edge)
    style.configure("TLabel", background=bg)
    style.configure("Title.TLabel", font=(family, size + 9, "bold"))
    style.configure("Section.TLabel", font=(family, size + 2, "bold"))
    style.configure("Muted.TLabel", foreground=muted)
    style.configure("Tile.TFrame", background=surface)
    style.configure("Tile.TLabel", background=surface, foreground=muted)
    style.configure("Value.TLabel", background=surface, foreground=ink, font=(family, size + 6, "bold"))
    style.configure("TButton", background=surface, padding=(9, 4))
    style.map("TButton", background=[("active", selected)], foreground=[("disabled", muted)])
    style.configure("Accent.TButton", background=accent, foreground=bg)
    style.map("Accent.TButton", background=[("active", muted)], foreground=[("disabled", bg)])
    for widget in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(widget, foreground=ink, fieldbackground=surface, insertcolor=ink,
                        arrowcolor=ink, padding=3)
        style.map(widget, fieldbackground=[("readonly", surface)], foreground=[("readonly", ink)])
    root.option_add("*TCombobox*Listbox.background", surface)
    root.option_add("*TCombobox*Listbox.foreground", ink)
    style.configure("Treeview", background=surface, fieldbackground=surface, foreground=ink,
                    rowheight=max(24, font.nametofont("TkDefaultFont").metrics("linespace") + 8))
    style.map("Treeview", background=[("selected", selected)], foreground=[("selected", ink)])
    style.configure("Treeview.Heading", background=bg, foreground=muted, font=(family, size, "bold"))
    style.configure("TNotebook.Tab", padding=(15, 6))
    style.map("TNotebook.Tab", background=[("selected", surface)], foreground=[("selected", accent)])
    return colors


def scroll_table(parent, columns, headings, widths, height=5, horizontal=False):
    frame = ttk.Frame(parent)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=height)
    for column, heading, width in zip(columns, headings, widths):
        tree.heading(column, text=heading, anchor="w")
        tree.column(column, width=width, minwidth=50, stretch=column == columns[-1])
    tree.grid(row=0, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.grid(row=0, column=1, sticky="ns")
    if horizontal:
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(xscrollcommand=xscroll.set)
        xscroll.grid(row=1, column=0, sticky="ew")
    return frame, tree


def severity_chart(canvas, counts, colors):
    _, surface, ink, muted, accent, edge, _ = colors
    canvas.configure(bg=surface)
    canvas.delete("all")
    width = canvas.winfo_width()
    textfont = font.nametofont("TkDefaultFont")
    if width < 10:
        return
    maximum = max(counts.values(), default=0) or 1
    line = max(32, textfont.metrics("linespace") + 16)
    for i, level in enumerate(LEVELS):
        y = 8 + i * line
        count = counts.get(level, 0)
        canvas.create_text(12, y, anchor="nw", text=level, fill=muted, font=textfont)
        canvas.create_text(width - 12, y, anchor="ne", text=f"{count:,}", fill=ink, font=textfont)
        bottom = y + line - 7
        canvas.create_rectangle(12, bottom - 4, width - 12, bottom, fill=edge, width=0)
        if count:
            canvas.create_rectangle(12, bottom - 4, 12 + (width - 24) * count / maximum, bottom,
                                    fill=accent, width=0)
