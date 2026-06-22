"""Paper Reviewer — Tkinter desktop app.

Two tabs:
  1. Reviewer  — pick a master Excel, drop in PDF/DOCX files, click Start.
  2. Settings  — configure Groq / Ollama / OpenRouter providers, multiple API keys
                 each, toggle which are enabled, set order, test connectivity.
"""

from __future__ import annotations

import os
import queue
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import (
    Tk, Toplevel, StringVar, BooleanVar, filedialog, messagebox, END,
)
from tkinter import ttk

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES  # type: ignore
    _DND_AVAILABLE = True
except Exception:
    _DND_AVAILABLE = False

from . import excel_io, extractor, reviewer
from .providers import (
    ProviderManager, GroqProvider, OllamaProvider, OpenRouterProvider, ProviderError,
    CONFIG_PATH,
)


SUPPORTED_EXT = (".pdf", ".docx")
CMT_EXT = (".xlsx", ".xls")
FORCE_REJECT_OPTIONS = ["(none)", "AI plagiarism", "Normal plagiarism", "No novelty"]
FORCE_REASON_MAP = {
    "AI plagiarism": "ai",
    "Normal plagiarism": "plag",
    "No novelty": "novelty",
}


@dataclass
class PaperEntry:
    path: str
    paper_id: str = ""
    force_reject: str = "(none)"
    status: str = "Pending"
    opinion: str = ""
    review: str = ""


class App:
    def __init__(self, root: Tk):
        self.root = root
        root.title("Paper Reviewer — ICCCNet")
        root.geometry("1100x720")

        self.manager = ProviderManager.load()
        self.papers: list[PaperEntry] = []
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.excel_path = StringVar(value=str(Path.cwd() / "reviews_output.xlsx"))
        self.cmt_path = StringVar(value="")
        self.cmt_metadata: dict[str, dict] = {}
        self.preview_enabled = BooleanVar(value=True)
        self._cancel_all = False

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_review = ttk.Frame(nb)
        self.tab_settings = ttk.Frame(nb)
        nb.add(self.tab_review, text="  Reviewer  ")
        nb.add(self.tab_settings, text="  Settings  ")

        self._build_review_tab(self.tab_review)
        self._build_settings_tab(self.tab_settings)

        self.root.after(150, self._drain_log_queue)

    # ---------------- Reviewer tab ----------------

    def _build_review_tab(self, parent):
        top = ttk.LabelFrame(parent, text="Output Excel (master file)")
        top.pack(fill="x", padx=4, pady=4)
        ttk.Entry(top, textvariable=self.excel_path).pack(side="left", fill="x", expand=True, padx=4, pady=4)
        ttk.Button(top, text="Browse...", command=self._browse_excel).pack(side="left", padx=2, pady=4)
        ttk.Button(top, text="New File...", command=self._new_excel).pack(side="left", padx=2, pady=4)

        cmt = ttk.LabelFrame(parent, text="CMT metadata source (optional) — auto-fills author columns by Paper ID")
        cmt.pack(fill="x", padx=4, pady=4)
        ttk.Entry(cmt, textvariable=self.cmt_path).pack(side="left", fill="x", expand=True, padx=4, pady=4)
        ttk.Button(cmt, text="Load CMT Excel...", command=self._load_cmt).pack(side="left", padx=2, pady=4)
        ttk.Button(cmt, text="Clear", command=self._clear_cmt).pack(side="left", padx=2, pady=4)
        self.cmt_status = ttk.Label(cmt, text="No CMT metadata loaded.", foreground="#666")
        self.cmt_status.pack(side="left", padx=8, pady=4)

        files = ttk.LabelFrame(parent, text="Papers to review")
        files.pack(fill="both", expand=True, padx=4, pady=4)

        btns = ttk.Frame(files)
        btns.pack(fill="x", padx=4, pady=4)
        ttk.Button(btns, text="Add Files...", command=self._add_files).pack(side="left", padx=2)
        ttk.Button(btns, text="Add Folder...", command=self._add_folder).pack(side="left", padx=2)
        ttk.Button(btns, text="Remove Selected", command=self._remove_selected).pack(side="left", padx=2)
        ttk.Button(btns, text="Clear All", command=self._clear_all).pack(side="left", padx=2)
        ttk.Separator(btns, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Checkbutton(btns, text="Preview each review before saving", variable=self.preview_enabled).pack(side="left", padx=6)
        ttk.Separator(btns, orient="vertical").pack(side="left", fill="y", padx=8)
        self.start_btn = ttk.Button(btns, text="Start Review", command=self._start_review)
        self.start_btn.pack(side="left", padx=2)
        dnd_hint = "Tip: you can also drag files here." if _DND_AVAILABLE else "(install tkinterdnd2 to enable drag-and-drop)"
        ttk.Label(btns, text=dnd_hint, foreground="#888").pack(side="right", padx=8)

        cols = ("file", "paper_id", "force_reject", "status", "opinion")
        self.tree = ttk.Treeview(files, columns=cols, show="headings", selectmode="extended")
        for c, w in zip(cols, (380, 90, 150, 110, 130)):
            self.tree.heading(c, text=c.replace("_", " ").title())
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        if _DND_AVAILABLE:
            try:
                self.tree.drop_target_register(DND_FILES)
                self.tree.dnd_bind("<<Drop>>", self._on_drop)
            except Exception as e:
                self._log(f"[warn] drag-drop init failed: {e}")

        edit = ttk.LabelFrame(parent, text="Edit selected paper")
        edit.pack(fill="x", padx=4, pady=4)
        ttk.Label(edit, text="Paper ID:").grid(row=0, column=0, padx=4, pady=4, sticky="w")
        self.edit_id = StringVar()
        ttk.Entry(edit, textvariable=self.edit_id, width=14).grid(row=0, column=1, padx=4, pady=4, sticky="w")
        ttk.Label(edit, text="Force Reject as:").grid(row=0, column=2, padx=10, pady=4, sticky="w")
        self.edit_reject = StringVar(value="(none)")
        ttk.Combobox(edit, textvariable=self.edit_reject, values=FORCE_REJECT_OPTIONS, state="readonly", width=22).grid(row=0, column=3, padx=4, pady=4, sticky="w")
        ttk.Button(edit, text="Apply", command=self._apply_edit).grid(row=0, column=4, padx=4, pady=4)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        prog = ttk.Frame(parent)
        prog.pack(fill="x", padx=4, pady=4)
        self.progress = ttk.Progressbar(prog, mode="determinate")
        self.progress.pack(fill="x", side="left", expand=True, padx=4)
        self.progress_label = ttk.Label(prog, text="Idle", width=24)
        self.progress_label.pack(side="left", padx=4)

        logf = ttk.LabelFrame(parent, text="Log")
        logf.pack(fill="both", expand=False, padx=4, pady=4)
        from tkinter import Text, Scrollbar
        self.log_text = Text(logf, height=8, wrap="word")
        sb = Scrollbar(logf, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

    def _browse_excel(self):
        path = filedialog.askopenfilename(
            title="Select master Excel file",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
        )
        if path:
            self.excel_path.set(path)

    def _new_excel(self):
        path = filedialog.asksaveasfilename(
            title="Create new master Excel file",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
        )
        if path:
            wb, _ = excel_io.ensure_workbook(path)
            excel_io.save(wb, path)
            self.excel_path.set(path)
            self._log(f"Created new Excel: {path}")

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select PDF or DOCX papers",
            filetypes=[("Papers", "*.pdf *.docx"), ("PDF", "*.pdf"), ("Word", "*.docx"), ("All", "*.*")],
        )
        for p in paths:
            self._add_paper(p)

    def _add_folder(self):
        folder = filedialog.askdirectory(title="Select folder containing papers")
        if not folder:
            return
        for p in Path(folder).iterdir():
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXT:
                self._add_paper(str(p))

    def _add_paper(self, path: str):
        if any(e.path == path for e in self.papers):
            return
        pid = extractor.extract_paper_id(Path(path).name) or ""
        entry = PaperEntry(path=path, paper_id=pid)
        self.papers.append(entry)
        self.tree.insert(
            "", END, iid=str(id(entry)),
            values=(Path(path).name, pid, "(none)", "Pending", ""),
        )

    def _remove_selected(self):
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.papers = [p for p in self.papers if str(id(p)) != iid]

    def _clear_all(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.papers = []

    def _load_cmt(self):
        path = filedialog.askopenfilename(
            title="Select CMT export Excel (xlsx or xml-format xls)",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            md = excel_io.load_cmt_metadata(path)
        except Exception as e:
            messagebox.showerror("Could not load CMT file", str(e))
            return
        self.cmt_metadata = md
        self.cmt_path.set(path)
        self.cmt_status.config(text=f"Loaded {len(md)} papers from CMT metadata.", foreground="#0a7")
        self._log(f"Loaded CMT metadata: {len(md)} papers from {path}")

    def _clear_cmt(self):
        self.cmt_metadata = {}
        self.cmt_path.set("")
        self.cmt_status.config(text="No CMT metadata loaded.", foreground="#666")

    def _on_drop(self, event):
        # event.data is a string of paths, possibly wrapped in {} for spaces
        try:
            paths = self.root.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]
        added = 0
        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                for child in p.iterdir():
                    if child.is_file() and child.suffix.lower() in SUPPORTED_EXT:
                        self._add_paper(str(child))
                        added += 1
            elif p.is_file() and p.suffix.lower() in SUPPORTED_EXT:
                self._add_paper(str(p))
                added += 1
        if added:
            self._log(f"Drag-drop: added {added} file(s).")

    def _selected_entry(self) -> PaperEntry | None:
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        for p in self.papers:
            if str(id(p)) == iid:
                return p
        return None

    def _on_tree_select(self, _ev=None):
        e = self._selected_entry()
        if e is None:
            return
        self.edit_id.set(e.paper_id)
        self.edit_reject.set(e.force_reject)

    def _on_tree_double_click(self, _ev=None):
        # double-click cycles the force-reject option (quick toggle)
        e = self._selected_entry()
        if e is None:
            return
        cur = FORCE_REJECT_OPTIONS.index(e.force_reject)
        e.force_reject = FORCE_REJECT_OPTIONS[(cur + 1) % len(FORCE_REJECT_OPTIONS)]
        self._refresh_row(e)
        self._on_tree_select()

    def _apply_edit(self):
        e = self._selected_entry()
        if e is None:
            return
        e.paper_id = self.edit_id.get().strip()
        e.force_reject = self.edit_reject.get()
        self._refresh_row(e)

    def _refresh_row(self, e: PaperEntry):
        self.tree.item(
            str(id(e)),
            values=(Path(e.path).name, e.paper_id, e.force_reject, e.status, e.opinion),
        )

    # ---------------- Review worker ----------------

    def _start_review(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Already running", "A review is already in progress.")
            return
        if not self.papers:
            messagebox.showwarning("No papers", "Add some PDF or DOCX files first.")
            return
        if not self.manager.working_provider():
            messagebox.showerror(
                "No provider",
                "No API provider is enabled and working.\n\n"
                "Go to the Settings tab, enable Groq / Ollama / OpenRouter, "
                "add an API key (or start Ollama), and click Test.",
            )
            return
        self.start_btn.config(state="disabled")
        self.progress["maximum"] = len(self.papers)
        self.progress["value"] = 0
        self.worker = threading.Thread(target=self._run_review, daemon=True)
        self.worker.start()

    def _run_review(self):
        try:
            wb, sheet = excel_io.ensure_workbook(self.excel_path.get())
        except Exception as e:
            self._log(f"[ERROR] Could not open Excel: {e}")
            self.root.after(0, lambda: self.start_btn.config(state="normal"))
            return

        self._cancel_all = False

        for i, entry in enumerate(self.papers, 1):
            if self._cancel_all:
                self._log("Cancelled by user.")
                break
            try:
                entry.status = "Reading..."
                self.root.after(0, self._refresh_row, entry)
                self.root.after(0, lambda i=i: self.progress_label.config(text=f"Paper {i}/{len(self.papers)}"))

                text = extractor.extract_text(entry.path)
                title_hint = extractor.guess_title(text)
                page_count = extractor.count_pages(entry.path)
                sections = extractor.detect_sections(text, path=entry.path)

                # Pull CMT metadata if available
                meta = self.cmt_metadata.get(entry.paper_id, {}) if entry.paper_id else {}
                # Prefer CMT title over the guessed one
                title_for_row = meta.get("paper_title") or title_hint

                entry.status = "Reviewing..."
                self.root.after(0, self._refresh_row, entry)

                reason = FORCE_REASON_MAP.get(entry.force_reject)
                result = reviewer.review_paper(
                    self.manager, text,
                    title_hint=title_for_row,
                    force_reject_reason=reason,
                    page_count=page_count,
                    sections=sections,
                )
                entry.review = result.review
                entry.opinion = result.opinion
                self._log(f"[{entry.paper_id or Path(entry.path).name}] {result.opinion}  (via {result.provider})")

                # Optional preview dialog before save
                if self.preview_enabled.get():
                    action, edited_review, edited_opinion = self._await_preview(entry, title_for_row)
                    if action == "cancel_all":
                        self._cancel_all = True
                        entry.status = "Cancelled"
                        self.root.after(0, self._refresh_row, entry)
                        break
                    if action == "skip":
                        entry.status = "Skipped"
                        self.root.after(0, self._refresh_row, entry)
                        continue
                    entry.review = edited_review
                    entry.opinion = edited_opinion

                row = {
                    "paper_id": entry.paper_id,
                    "paper_title": title_for_row,
                    "primary_name": meta.get("primary_name", ""),
                    "primary_email": meta.get("primary_email", ""),
                    "authors": meta.get("authors", ""),
                    "author_names": meta.get("author_names", ""),
                    "author_emails": meta.get("author_emails", ""),
                    "review": entry.review,
                    "opinion": entry.opinion,
                }
                excel_io.append_row(wb, sheet, row)
                excel_io.save(wb, self.excel_path.get())
                entry.status = "Done"

            except Exception as e:
                entry.status = "Error"
                entry.opinion = ""
                self._log(f"[ERROR] {Path(entry.path).name}: {e}")
                traceback.print_exc()
            finally:
                self.root.after(0, self._refresh_row, entry)
                self.root.after(0, lambda i=i: self.progress.configure(value=i))

        self._log(f"Done. Excel saved to: {self.excel_path.get()}")
        self.root.after(0, lambda: self.progress_label.config(text="Idle"))
        self.root.after(0, lambda: self.start_btn.config(state="normal"))

    def _await_preview(self, entry: "PaperEntry", title: str) -> tuple[str, str, str]:
        """Run the preview dialog on the main thread; block worker until user acts.

        Returns (action, review, opinion). action in {'accept', 'skip', 'cancel_all'}.
        """
        done = threading.Event()
        result = {"action": "accept", "review": entry.review, "opinion": entry.opinion}

        def open_dialog():
            PreviewDialog(self.root, entry, title, result, done)

        self.root.after(0, open_dialog)
        done.wait()
        return result["action"], result["review"], result["opinion"]

    # ---------------- Logging ----------------

    def _log(self, msg: str):
        self.log_queue.put(msg)

    def _drain_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.insert(END, msg + "\n")
                self.log_text.see(END)
        except queue.Empty:
            pass
        self.root.after(150, self._drain_log_queue)

    # ---------------- Settings tab ----------------

    def _build_settings_tab(self, parent):
        info = ttk.Label(
            parent,
            text=(
                "Enable one or more providers. The app tries them in order from top to bottom.\n"
                "Groq is free with rate limits (sign up at console.groq.com). "
                "Ollama runs locally (install from ollama.com). "
                "OpenRouter offers free models (openrouter.ai).\n"
                "Multiple API keys per provider are rotated automatically; "
                "if one fails or hits its quota, the next is tried."
            ),
            wraplength=1040, justify="left",
        )
        info.pack(fill="x", padx=8, pady=6)

        self.provider_widgets = {}
        for name in ["groq", "ollama", "openrouter"]:
            self._build_provider_section(parent, name)

        bottom = ttk.Frame(parent)
        bottom.pack(fill="x", padx=8, pady=8)
        self.auto_fallback_var = BooleanVar(value=self.manager.auto_fallback)
        ttk.Checkbutton(
            bottom, text="Auto-fallback to next provider on failure",
            variable=self.auto_fallback_var,
        ).pack(side="left", padx=4)
        ttk.Button(bottom, text="Save Settings", command=self._save_settings).pack(side="right", padx=4)
        ttk.Button(bottom, text="Test All Enabled", command=self._test_all).pack(side="right", padx=4)

    def _build_provider_section(self, parent, name: str):
        prov = self.manager.providers[name]
        frame = ttk.LabelFrame(parent, text=name.capitalize())
        frame.pack(fill="x", padx=8, pady=4)

        enabled_var = BooleanVar(value=prov.enabled)
        ttk.Checkbutton(frame, text="Enabled", variable=enabled_var).grid(row=0, column=0, padx=6, pady=4, sticky="w")

        ttk.Label(frame, text="Model:").grid(row=0, column=1, padx=6, pady=4, sticky="e")
        model_var = StringVar(value=prov.model)
        ttk.Entry(frame, textvariable=model_var, width=42).grid(row=0, column=2, padx=4, pady=4, sticky="w")

        ttk.Button(frame, text="Test", command=lambda n=name: self._test_provider(n)).grid(row=0, column=3, padx=6, pady=4)

        keys_var = None
        baseurl_var = None
        if isinstance(prov, (GroqProvider, OpenRouterProvider)):
            ttk.Label(frame, text="API keys (one per line):").grid(row=1, column=0, padx=6, pady=4, sticky="nw")
            from tkinter import Text, Scrollbar
            keys_text = Text(frame, height=5, width=72, wrap="none")
            keys_text.grid(row=1, column=1, columnspan=3, padx=4, pady=4, sticky="we")
            keys_text.insert(END, "\n".join(prov.api_keys))
            keys_var = keys_text
        elif isinstance(prov, OllamaProvider):
            ttk.Label(frame, text="Base URL:").grid(row=1, column=1, padx=6, pady=4, sticky="e")
            baseurl_var = StringVar(value=prov.base_url)
            ttk.Entry(frame, textvariable=baseurl_var, width=42).grid(row=1, column=2, padx=4, pady=4, sticky="w")
            ttk.Label(
                frame,
                text="(install ollama, then run e.g.  ollama pull llama3.1)",
                foreground="#666",
            ).grid(row=2, column=1, columnspan=3, padx=6, pady=2, sticky="w")

        status_var = StringVar(value="")
        ttk.Label(frame, textvariable=status_var, foreground="#0a7").grid(row=3, column=0, columnspan=4, padx=6, pady=2, sticky="w")

        self.provider_widgets[name] = {
            "enabled": enabled_var,
            "model": model_var,
            "keys_text": keys_var,
            "base_url": baseurl_var,
            "status": status_var,
        }

    def _gather_settings(self):
        """Read GUI widgets back into the providers."""
        for name, w in self.provider_widgets.items():
            prov = self.manager.providers[name]
            prov.enabled = bool(w["enabled"].get())
            prov.model = w["model"].get().strip() or prov.model
            if isinstance(prov, (GroqProvider, OpenRouterProvider)):
                raw = w["keys_text"].get("1.0", END).strip()
                prov.api_keys = [k.strip() for k in raw.splitlines() if k.strip()]
                prov._key_cycle = None
            elif isinstance(prov, OllamaProvider):
                prov.base_url = w["base_url"].get().strip() or prov.base_url
        self.manager.auto_fallback = bool(self.auto_fallback_var.get())

    def _save_settings(self):
        self._gather_settings()
        self.manager.save()
        messagebox.showinfo("Saved", f"Settings saved to:\n{CONFIG_PATH}")

    def _test_provider(self, name: str):
        self._gather_settings()
        prov = self.manager.providers[name]
        self.provider_widgets[name]["status"].set("Testing...")
        self.root.update_idletasks()
        ok, msg = prov.test()
        if ok:
            self.provider_widgets[name]["status"].set(f"OK: {msg.strip()[:120]}")
        else:
            self.provider_widgets[name]["status"].set(f"FAIL: {msg.strip()[:160]}")

    def _test_all(self):
        self._gather_settings()
        for name in ["groq", "ollama", "openrouter"]:
            if self.manager.providers[name].enabled:
                self._test_provider(name)


class PreviewDialog:
    """Modal dialog: review the LLM output, edit it, then accept / skip / cancel-all."""

    def __init__(self, parent, entry: "PaperEntry", title: str, result: dict, done: threading.Event):
        self.result = result
        self.done = done
        self.win = Toplevel(parent)
        self.win.title(f"Preview — {Path(entry.path).name}")
        self.win.geometry("820x560")
        self.win.transient(parent)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        info = ttk.Frame(self.win)
        info.pack(fill="x", padx=10, pady=8)
        ttk.Label(info, text=f"Paper ID: {entry.paper_id or '(none)'}", font=("Arial", 10, "bold")).pack(anchor="w")
        ttk.Label(info, text=f"File: {entry.path}", foreground="#666").pack(anchor="w")
        ttk.Label(info, text=f"Title: {title or '(unknown)'}", wraplength=780, foreground="#444").pack(anchor="w", pady=(2, 0))

        ttk.Label(self.win, text="Review (editable):").pack(anchor="w", padx=10, pady=(8, 0))
        from tkinter import Text, Scrollbar
        text_frame = ttk.Frame(self.win)
        text_frame.pack(fill="both", expand=True, padx=10, pady=4)
        self.review_text = Text(text_frame, wrap="word", height=14)
        sb = Scrollbar(text_frame, command=self.review_text.yview)
        self.review_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.review_text.pack(fill="both", expand=True)
        self.review_text.insert("1.0", entry.review)

        opin = ttk.Frame(self.win)
        opin.pack(fill="x", padx=10, pady=6)
        ttk.Label(opin, text="Opinion:").pack(side="left")
        self.opinion_var = StringVar(value=entry.opinion)
        opts = ["Reject", "Springer", "Elsevier", "Adroid", "May be springer"]
        if entry.opinion and entry.opinion not in opts:
            opts.append(entry.opinion)
        ttk.Combobox(opin, textvariable=self.opinion_var, values=opts, state="readonly", width=20).pack(side="left", padx=8)
        ttk.Label(opin, text=f"  (LLM provider used to fill this, you can change.)", foreground="#888").pack(side="left")

        btns = ttk.Frame(self.win)
        btns.pack(fill="x", padx=10, pady=10)
        ttk.Button(btns, text="Accept and Save", command=lambda: self._finish("accept")).pack(side="right", padx=4)
        ttk.Button(btns, text="Skip this paper", command=lambda: self._finish("skip")).pack(side="right", padx=4)
        ttk.Button(btns, text="Cancel all remaining", command=lambda: self._finish("cancel_all")).pack(side="left", padx=4)

    def _finish(self, action: str):
        self.result["action"] = action
        self.result["review"] = self.review_text.get("1.0", END).strip()
        self.result["opinion"] = self.opinion_var.get().strip()
        try:
            self.win.grab_release()
        except Exception:
            pass
        self.win.destroy()
        self.done.set()

    def _on_close(self):
        # closing the X is treated as 'skip'
        self._finish("skip")


def main():
    if _DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = Tk()
    try:
        style = ttk.Style()
        style.theme_use("clam")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
