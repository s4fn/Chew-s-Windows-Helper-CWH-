"""
main.py - Windows Utility Tool (CustomTkinter GUI)
Single entry point implementing:
- Dashboard (CPU/RAM)
- Processes (list + kill)
- Deep Cleanup (run/dry-run/preview)
- Preview (JSON dry-run preview)
- Logs (queue-driven, level filtering)
- Services (list/start/stop/restart)
- Network Info
- Disk Usage
- Utilities: open scripts folder, clear temp, schedule cleanup, export/import settings, run arbitrary PowerShell, test elevation, toggle theme
- Elevation flow: relaunch as admin and continue requested action
Dependencies:
- customtkinter
- psutil
- pillow (optional for icons)
"""
import os
import sys
import json
import threading
import time
import subprocess
import ctypes
import shutil
import psutil
import customtkinter as ctk
from tkinter import ttk, messagebox, scrolledtext, filedialog, simpledialog
from queue import Queue, Empty

APP_NAME = "Chew's Window Helper (CWH)"
SCRIPTS_DIR = "scripts"
CLEANUP_PS1 = "cleanup.ps1"
CLEANUP_EXE = "cleanup.exe"

# -------------------------
# Resource path & elevation
# -------------------------
def resource_path(relative_path: str) -> str:
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS  # type: ignore
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def relaunch_as_admin(extra_args: list):
    """
    Relaunch current executable/script as admin with extra_args (list of strings).
    Returns True if the ShellExecute call was performed (UAC shown).
    """
    try:
        exe = sys.executable
        if getattr(sys, "frozen", False):
            params = " ".join(['"%s"' % a for a in extra_args])
            ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        else:
            script = os.path.abspath(sys.argv[0])
            params = " ".join(['"%s"' % a for a in ([script] + extra_args)])
            ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return True
    except Exception:
        return False

def _creationflags_no_window():
    try:
        return subprocess.CREATE_NO_WINDOW
    except AttributeError:
        return 0

# -------------------------
# External command runners
# -------------------------
def run_powershell_stream_to_queue(script_path: str, args: list = None, out_queue: Queue = None, timeout: int = None):
    if args is None:
        args = []
    if out_queue is None:
        raise ValueError("out_queue required")
    cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path] + args
    creationflags = _creationflags_no_window()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=creationflags, bufsize=1)
    except FileNotFoundError:
        out_queue.put(("ERROR", "powershell.exe not found on PATH"))
        return 1
    try:
        for line in proc.stdout:
            out_queue.put(("INFO", line.rstrip("\n")))
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out_queue.put(("ERROR", "Process timed out"))
        raise
    return proc.returncode

def run_executable_stream_to_queue(exe_path: str, args: list = None, out_queue: Queue = None, timeout: int = None):
    if args is None:
        args = []
    if out_queue is None:
        raise ValueError("out_queue required")
    cmd = [exe_path] + args
    creationflags = _creationflags_no_window()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=creationflags, bufsize=1)
    except FileNotFoundError:
        out_queue.put(("ERROR", f"Executable not found: {exe_path}"))
        return 1
    try:
        for line in proc.stdout:
            out_queue.put(("INFO", line.rstrip("\n")))
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out_queue.put(("ERROR", "Process timed out"))
        raise
    return proc.returncode

def run_preview_json(script_or_exe: str, use_exe: bool, args: list = None, timeout: int = 30):
    if args is None:
        args = []
    cmd_args = args + ["--dry-run", "--json"]
    creationflags = _creationflags_no_window()
    if use_exe:
        cmd = [script_or_exe] + cmd_args
    else:
        cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_or_exe] + cmd_args
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=creationflags)
    stdout, stderr = proc.communicate(timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"Preview failed: exit {proc.returncode}\n{stderr}")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        # if script also emitted logs then JSON may be mixed; try to extract JSON block
        try:
            # attempt to find first '{' and last '}'
            start = stdout.find("{")
            end = stdout.rfind("}")
            if start != -1 and end != -1 and end > start:
                substr = stdout[start:end+1]
                return json.loads(substr)
        except Exception:
            pass
        raise RuntimeError(f"Failed to parse JSON preview output: {e}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")

# -------------------------
# App: queue-driven UI and many utilities
# -------------------------
class App(ctk.CTk):
    def __init__(self, argv):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.title(APP_NAME)
        self.geometry("1100x760")
        self.minsize(980, 640)
        self.argv = argv

        # queues
        self.log_queue = Queue()
        self.ui_queue = Queue()  # for arbitrary UI tasks if needed

        # UI top
        top_frame = ctk.CTkFrame(self, height=64)
        top_frame.pack(fill="x", side="top")
        ctk.CTkLabel(top_frame, text=APP_NAME, font=ctk.CTkFont(size=20, weight="bold")).pack(side="left", padx=16, pady=12)
        self.admin_label = ctk.CTkLabel(top_frame, text="")
        self.admin_label.pack(side="right", padx=16)
        self.update_admin_status()

        # main layout
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=12, pady=12)

        sidebar = ctk.CTkFrame(main_frame, width=220)
        sidebar.pack(side="left", fill="y", padx=(0,12), pady=6)

        self.content = ctk.CTkFrame(main_frame)
        self.content.pack(side="right", fill="both", expand=True, pady=6)

        # sidebar buttons
        ctk.CTkButton(sidebar, text="Dashboard", command=self.show_dashboard).pack(pady=(12,6), padx=12, fill="x")
        ctk.CTkButton(sidebar, text="Processes", command=self.show_processes).pack(pady=6, padx=12, fill="x")
        ctk.CTkButton(sidebar, text="Deep Cleanup", command=self.show_cleanup).pack(pady=6, padx=12, fill="x")
        ctk.CTkButton(sidebar, text="Preview", command=self.show_preview).pack(pady=6, padx=12, fill="x")
        ctk.CTkButton(sidebar, text="Services", command=self.show_services).pack(pady=6, padx=12, fill="x")
        ctk.CTkButton(sidebar, text="Network", command=self.show_network).pack(pady=6, padx=12, fill="x")
        ctk.CTkButton(sidebar, text="Disk", command=self.show_disk).pack(pady=6, padx=12, fill="x")
        ctk.CTkButton(sidebar, text="Logs", command=self.show_logs).pack(pady=6, padx=12, fill="x")

        # utilities area in sidebar
        ctk.CTkLabel(sidebar, text="Utilities", anchor="w").pack(padx=12, pady=(16,4), fill="x")
        ctk.CTkButton(sidebar, text="Open Scripts Folder", command=self.open_scripts_folder).pack(pady=4, padx=12, fill="x")
        ctk.CTkButton(sidebar, text="Clear User Temp", command=self.clear_user_temp).pack(pady=4, padx=12, fill="x")
        ctk.CTkButton(sidebar, text="Schedule Cleanup", command=self.schedule_cleanup_dialog).pack(pady=4, padx=12, fill="x")
        ctk.CTkButton(sidebar, text="Run PowerShell...", command=self.run_powershell_dialog).pack(pady=4, padx=12, fill="x")
        ctk.CTkButton(sidebar, text="Export Settings", command=self.export_settings).pack(pady=4, padx=12, fill="x")
        ctk.CTkButton(sidebar, text="Import Settings", command=self.import_settings).pack(pady=4, padx=12, fill="x")
        ctk.CTkButton(sidebar, text="Toggle Theme", command=self.toggle_theme).pack(pady=8, padx=12, fill="x")
        ctk.CTkButton(sidebar, text="Test Elevation", command=self.test_elevation).pack(pady=4, padx=12, fill="x")
        ctk.CTkButton(sidebar, text="Check for Updates", command=self.check_for_updates).pack(pady=4, padx=12, fill="x")

        # state
        self.logs = []  # archived logs
        self.logs_widget = None
        self.autoscroll = True
        self._stop_dashboard = False

        # Start by showing dashboard
        self.show_dashboard()

        # Start polling queues
        self.after(100, self._poll_queues)

        # Handle elevated-action args if present
        self.after(200, self._maybe_handle_startup_args)

    # ---------- UI helpers ----------
    def ui_call(self, func, *args, **kwargs):
        """Schedule func on main thread via after."""
        try:
            self.after(0, lambda: func(*args, **kwargs))
        except Exception:
            pass

    def update_admin_status(self):
        self.admin_label.configure(text="Administrator" if is_admin() else "Standard User (not elevated)")

    # Poll log_queue and ui_queue
    def _poll_queues(self):
        # process UI tasks if any
        try:
            while True:
                task = self.ui_queue.get_nowait()
                try:
                    func, a, kw = task
                    func(*a, **kw)
                except Exception:
                    pass
        except Empty:
            pass
        # process logs
        try:
            updated = False
            while True:
                level, text = self.log_queue.get_nowait()
                self._store_and_display_log(level, text)
                updated = True
        except Empty:
            pass
        # schedule next poll
        self.after(100, self._poll_queues)

    def _store_and_display_log(self, level: str, text: str):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {level.upper()}: {text}"
        self.logs.append(entry)
        # append to logs_widget if visible and filtering allows
        if self.logs_widget:
            try:
                cur = getattr(self, "level_filter_var", None)
                if (cur is None) or (cur.get() == "ALL") or (cur.get() == level.upper()):
                    # enable, insert, disable to keep read-only
                    try: self.logs_widget.config(state="normal")
                    except Exception: pass
                    self.logs_widget.insert("end", entry + "\n")
                    if getattr(self, "autoscroll_var", None) and self.autoscroll_var.get():
                        self.logs_widget.see("end")
                    try: self.logs_widget.config(state="disabled")
                    except Exception: pass
            except Exception:
                pass

    # central append_log for background threads
    def append_log(self, level: str, text: str):
        try:
            self.log_queue.put((level.upper(), text))
        except Exception:
            pass

    # ---------- Dashboard ----------
    def show_dashboard(self):
        self.clear_content()
        frame = self.content
        ctk.CTkLabel(frame, text="Dashboard", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="nw", padx=12, pady=(12,8))
        ctk.CTkLabel(frame, text="CPU Usage").pack(anchor="nw", padx=12)
        self.cpu_bar = ctk.CTkProgressBar(frame, width=800); self.cpu_bar.set(0); self.cpu_bar.pack(anchor="nw", padx=12, pady=6)
        ctk.CTkLabel(frame, text="Memory Usage").pack(anchor="nw", padx=12)
        self.ram_bar = ctk.CTkProgressBar(frame, width=800); self.ram_bar.set(0); self.ram_bar.pack(anchor="nw", padx=12, pady=6)
        stats = ctk.CTkFrame(frame); stats.pack(anchor="nw", padx=12, pady=12, fill="x")
        self.lbl_cpu = ctk.CTkLabel(stats, text="CPU: --%"); self.lbl_cpu.pack(side="left", padx=8)
        self.lbl_ram = ctk.CTkLabel(stats, text="RAM: --%"); self.lbl_ram.pack(side="left", padx=8)
        self.lbl_uptime = ctk.CTkLabel(stats, text="Uptime: --"); self.lbl_uptime.pack(side="left", padx=8)
        self._stop_dashboard = False
        self.after(500, self._update_dashboard)

    def _update_dashboard(self):
        if getattr(self, "_stop_dashboard", False):
            return
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            self.cpu_bar.set(cpu/100.0)
            self.ram_bar.set(mem.percent/100.0)
            self.lbl_cpu.configure(text=f"CPU: {cpu:.1f}%")
            self.lbl_ram.configure(text=f"RAM: {mem.percent:.1f}%")
            uptime_seconds = time.time() - psutil.boot_time()
            self.lbl_uptime.configure(text=f"Uptime: {_format_seconds(uptime_seconds)}")
        except Exception:
            pass
        finally:
            self.after(1000, self._update_dashboard)

    # ---------- Processes ----------
    def show_processes(self):
        self._stop_dashboard = True
        self.clear_content()
        frame = self.content
        ctk.CTkLabel(frame, text="Processes", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="nw", padx=12, pady=(12,8))
        top = ctk.CTkFrame(frame); top.pack(fill="x", padx=12, pady=(0,8))
        ctk.CTkButton(top, text="Refresh", command=self._refresh_process_list).pack(side="left", padx=(0,8))
        ctk.CTkButton(top, text="Force Kill Selected", fg_color="red", hover_color="#aa4444", command=self._kill_selected_process).pack(side="left")
        tree_frame = ctk.CTkFrame(frame); tree_frame.pack(fill="both", expand=True, padx=12, pady=(0,12))
        columns = ("pid","name","cpu","mem")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=24)
        tree.heading("pid", text="PID"); tree.heading("name", text="Name"); tree.heading("cpu", text="CPU %"); tree.heading("mem", text="Mem %")
        tree.column("pid", width=80, anchor="center"); tree.column("name", width=520, anchor="w"); tree.column("cpu", width=80, anchor="center"); tree.column("mem", width=80, anchor="center")
        tree.pack(fill="both", expand=True, side="left")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview); tree.configure(yscroll=scrollbar.set); scrollbar.pack(side="right", fill="y")
        self.process_tree = tree
        self._refresh_process_list()

    def _refresh_process_list(self):
        tree = self.process_tree
        for i in tree.get_children(): tree.delete(i)
        for proc in psutil.process_iter(['pid','name','cpu_percent','memory_percent']):
            try:
                info = proc.info
                pid = info.get('pid','')
                name = info.get('name','')
                cpu = info.get('cpu_percent', 0.0)
                mem = info.get('memory_percent', 0.0)
                tree.insert("", "end", values=(pid, name, f"{cpu:.1f}", f"{mem:.1f}"))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def _kill_selected_process(self):
        sel = self.process_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "No process selected.")
            return
        vals = self.process_tree.item(sel[0], "values")
        pid = int(vals[0]); name = vals[1]
        if not messagebox.askyesno("Confirm", f"Force kill {name} (PID {pid})?"): return
        def worker():
            try:
                p = psutil.Process(pid); p.kill(); time.sleep(0.2)
                self.append_log("INFO", f"Killed process {name} (PID {pid})")
                self.ui_call(self._refresh_process_list)
            except psutil.NoSuchProcess:
                self.append_log("WARN", "Process no longer exists.")
                self.ui_call(self._refresh_process_list)
            except psutil.AccessDenied:
                self.append_log("ERROR", "Access denied. Try running as Administrator.")
                self.ui_call(messagebox.showerror, APP_NAME, "Access denied. Try running the app as Administrator.")
            except Exception as e:
                self.append_log("ERROR", f"Failed to kill process: {e}")
                self.ui_call(messagebox.showerror, APP_NAME, f"Failed to kill process: {e}")
        threading.Thread(target=worker, daemon=True).start()

    # ---------- Cleanup ----------
    def show_cleanup(self):
        self._stop_dashboard = True
        self.clear_content()
        frame = self.content
        ctk.CTkLabel(frame, text="Deep Cleanup", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="nw", padx=12, pady=(12,8))
        info = "Clears Windows Update cache, Temp folders and Prefetch. Use Preview for Dry-Run JSON first."
        ctk.CTkLabel(frame, text=info, wraplength=800, justify="left").pack(anchor="nw", padx=12)
        top = ctk.CTkFrame(frame); top.pack(fill="x", padx=12, pady=(8,8))
        ctk.CTkButton(top, text="Run (silent)", fg_color="red", hover_color="#aa4444", command=lambda: self._run_cleanup(show_dialogs=False)).pack(side="left", padx=(0,8))
        ctk.CTkButton(top, text="Run (dialogs)", command=lambda: self._run_cleanup(show_dialogs=True)).pack(side="left")
        right = ctk.CTkFrame(frame); right.pack(fill="x", padx=12, pady=(8,8))
        self.dry_run_var = ctk.BooleanVar(value=False); ctk.CTkCheckBox(right, text="Dry-Run (no deletion)", variable=self.dry_run_var).pack(side="left", padx=(0,8))
        ctk.CTkLabel(right, text="LogLevel:").pack(side="left", padx=(12,4))
        self.loglevel_var = ctk.StringVar(value="INFO")
        ctk.CTkComboBox(right, values=["INFO","WARN","ERROR","ALL"], variable=self.loglevel_var).pack(side="left")
        self.cleanup_status = ctk.CTkLabel(frame, text="Status: Idle", anchor="w"); self.cleanup_status.pack(fill="x", padx=12, pady=8)

    def _run_cleanup(self, show_dialogs=True):
        exe_rel = os.path.join(SCRIPTS_DIR, CLEANUP_EXE); ps1_rel = os.path.join(SCRIPTS_DIR, CLEANUP_PS1)
        exe_path = resource_path(exe_rel); ps1_path = resource_path(ps1_rel)
        if os.path.exists(exe_path): use_exe = True; target = exe_path
        elif os.path.exists(ps1_path): use_exe = False; target = ps1_path
        else:
            messagebox.showerror(APP_NAME, f"No cleanup module found. Expected one of:\n - {exe_rel}\n - {ps1_rel}")
            return
        want_admin = not self.dry_run_var.get()
        if want_admin and not is_admin():
            if messagebox.askyesno("Admin required", "Full cleanup requires Administrator. Relaunch elevated?"):
                elevated_args = ["--elevated-action", "cleanup"]
                if self.dry_run_var.get(): elevated_args.append("--dry-run")
                if self.loglevel_var.get(): elevated_args += ["--loglevel", self.loglevel_var.get().lower()]
                if relaunch_as_admin(elevated_args):
                    self.append_log("INFO", "Relaunching elevated...")
                    self.destroy(); sys.exit(0)
                else:
                    messagebox.showerror(APP_NAME, "Failed to relaunch elevated.")
                    return
        args = []
        if self.dry_run_var.get(): args.append("--dry-run")
        lvl = self.loglevel_var.get().lower()
        if lvl != "all": args += ["--loglevel", lvl]
        # run in background and stream logs to queue
        def worker():
            self.append_log("INFO", f"Starting cleanup (dry={self.dry_run_var.get()}, level={lvl})")
            self.ui_call(self.cleanup_status.configure, text="Status: Running...")
            try:
                if use_exe:
                    rc = run_executable_stream_to_queue(target, args=args, out_queue=self.log_queue)
                else:
                    rc = run_powershell_stream_to_queue(target, args=args, out_queue=self.log_queue)
                status = "Completed successfully" if rc == 0 else f"Completed with code {rc}"
                self.append_log("INFO", f"Cleanup finished: {status}")
                self.ui_call(self.cleanup_status.configure, text=f"Status: {status}")
            except Exception as e:
                self.append_log("ERROR", f"Cleanup error: {e}")
                self.ui_call(self.cleanup_status.configure, text="Status: Error")
        threading.Thread(target=worker, daemon=True).start()

    # ---------- Preview (JSON Dry-run) ----------
    def show_preview(self):
        self._stop_dashboard = True
        self.clear_content()
        frame = self.content
        ctk.CTkLabel(frame, text="Preview (Dry-Run JSON)", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="nw", padx=12, pady=(12,8))
        ctk.CTkLabel(frame, text="Shows what would be removed. Uses module --dry-run --json.", wraplength=800, justify="left").pack(anchor="nw", padx=12)
        top = ctk.CTkFrame(frame); top.pack(fill="x", padx=12, pady=(8,8))
        ctk.CTkButton(top, text="Refresh Preview", command=self._refresh_preview).pack(side="left", padx=(0,8))
        self.preview_status = ctk.CTkLabel(frame, text="Status: Idle", anchor="w"); self.preview_status.pack(fill="x", padx=12, pady=8)
        tree_frame = ctk.CTkFrame(frame); tree_frame.pack(fill="both", expand=True, padx=12, pady=(0,12))
        tree = ttk.Treeview(tree_frame, columns=("type",), show="tree")
        tree.pack(fill="both", expand=True, side="left")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview); tree.configure(yscroll=scrollbar.set); scrollbar.pack(side="right", fill="y")
        self.preview_tree = tree
        self._refresh_preview()

    def _refresh_preview(self):
        exe_rel = os.path.join(SCRIPTS_DIR, CLEANUP_EXE); ps1_rel = os.path.join(SCRIPTS_DIR, CLEANUP_PS1)
        exe_path = resource_path(exe_rel); ps1_path = resource_path(ps1_rel)
        if os.path.exists(exe_path): use_exe = True; target = exe_path
        elif os.path.exists(ps1_path): use_exe = False; target = ps1_path
        else:
            messagebox.showerror(APP_NAME, f"No cleanup module found. Expected one of:\n - {exe_rel}\n - {ps1_rel}")
            return
        self.ui_call(self.preview_status.configure, text="Status: Running preview...")
        def worker():
            try:
                parsed = run_preview_json(target, use_exe, args=[], timeout=60)
                self.ui_call(self._populate_preview_tree, parsed)
                self.ui_call(self.preview_status.configure, text="Status: Preview loaded")
            except Exception as e:
                self.append_log("ERROR", f"Preview failed: {e}")
                self.ui_call(self.preview_status.configure, text="Status: Preview failed")
                self.ui_call(messagebox.showerror, APP_NAME, f"Preview failed: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _populate_preview_tree(self, parsed_json):
        tree = self.preview_tree
        try:
            tree.delete(*tree.get_children())
        except Exception:
            pass
        items = parsed_json.get("items", []) if isinstance(parsed_json, dict) else []
        # Insert full paths as hierarchical tree
        for it in items:
            path = it.get("path") if isinstance(it, dict) else str(it)
            typ = it.get("type", "file") if isinstance(it, dict) else "file"
            self._insert_path(tree, path, typ)

    def _insert_path(self, tree, path, typ):
        parts = path.strip(os.sep).split(os.sep)
        parent = ""
        accum = ""
        for i, p in enumerate(parts):
            accum = os.path.join(accum, p) if accum else p
            # find child
            found = None
            for child in tree.get_children(parent):
                if tree.item(child, "text") == p:
                    found = child
                    break
            if found:
                parent = found
                continue
            label = p + ("/" if (i == len(parts)-1 and typ == "dir") else "")
            new_id = tree.insert(parent, "end", text=p, values=(typ,))
            parent = new_id

    # ---------- Services ----------
    def show_services(self):
        self._stop_dashboard = True
        self.clear_content()
        frame = self.content
        ctk.CTkLabel(frame, text="Windows Services", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="nw", padx=12, pady=(12,8))
        top = ctk.CTkFrame(frame); top.pack(fill="x", padx=12, pady=(0,8))
        ctk.CTkButton(top, text="Refresh", command=self._refresh_services).pack(side="left", padx=(0,8))
        ctk.CTkButton(top, text="Start", command=lambda: self._service_action("start")).pack(side="left")
        ctk.CTkButton(top, text="Stop", command=lambda: self._service_action("stop")).pack(side="left", padx=(8,0))
        ctk.CTkButton(top, text="Restart", command=lambda: self._service_action("restart")).pack(side="left", padx=(8,0))
        tree_frame = ctk.CTkFrame(frame); tree_frame.pack(fill="both", expand=True, padx=12, pady=(0,12))
        cols = ("name","display","status")
        tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=24)
        tree.heading("name", text="Name"); tree.heading("display", text="Display Name"); tree.heading("status", text="Status")
        tree.column("name", width=260); tree.column("display", width=520); tree.column("status", width=120, anchor="center")
        tree.pack(fill="both", expand=True, side="left")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview); tree.configure(yscroll=scrollbar.set); scrollbar.pack(side="right", fill="y")
        self.services_tree = tree
        self._refresh_services()

    def _refresh_services(self):
        tree = self.services_tree
        for i in tree.get_children(): tree.delete(i)
        try:
            for s in psutil.win_service_iter():
                info = s.as_dict()
                tree.insert("", "end", values=(info.get("name"), info.get("display_name"), info.get("status")))
        except Exception as e:
            self.append_log("ERROR", f"Failed to list services: {e}")

    def _service_action(self, action):
        sel = self.services_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "No service selected.")
            return
        name = self.services_tree.item(sel[0], "values")[0]
        def worker():
            try:
                svc = psutil.win_service_get(name)
                s = svc.as_dict()
                if action == "start":
                    svc.start()
                    self.append_log("INFO", f"Started service {name}")
                elif action == "stop":
                    svc.stop()
                    self.append_log("INFO", f"Stopped service {name}")
                elif action == "restart":
                    svc.stop(); time.sleep(1); svc.start()
                    self.append_log("INFO", f"Restarted service {name}")
                time.sleep(0.5)
                self.ui_call(self._refresh_services)
            except Exception as e:
                self.append_log("ERROR", f"Service {action} failed: {e}")
                self.ui_call(messagebox.showerror, APP_NAME, f"Service {action} failed: {e}")
        threading.Thread(target=worker, daemon=True).start()

    # ---------- Network ----------
    def show_network(self):
        self._stop_dashboard = True
        self.clear_content()
        frame = self.content
        ctk.CTkLabel(frame, text="Network Interfaces", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="nw", padx=12, pady=(12,8))
        tree_frame = ctk.CTkFrame(frame); tree_frame.pack(fill="both", expand=True, padx=12, pady=(0,12))
        tree = ttk.Treeview(tree_frame, columns=("addr","family","netmask"), show="headings", height=24)
        tree.heading("addr", text="Address"); tree.heading("family", text="Family"); tree.heading("netmask", text="Netmask")
        tree.column("addr", width=420); tree.column("family", width=120); tree.column("netmask", width=240)
        tree.pack(fill="both", expand=True, side="left")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview); tree.configure(yscroll=scrollbar.set); scrollbar.pack(side="right", fill="y")
        self.network_tree = tree
        self._refresh_network()

    def _refresh_network(self):
        tree = self.network_tree
        for i in tree.get_children(): tree.delete(i)
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_io_counters(pernic=True)
            for ifname, lst in addrs.items():
                # add a header row
                tree.insert("", "end", values=(f"{ifname}", "", ""))
                for a in lst:
                    fam = str(a.family).split("'")[-1] if hasattr(a.family, 'name') else str(a.family)
                    tree.insert("", "end", values=(a.address, fam, a.netmask))
                io = stats.get(ifname)
                if io:
                    tree.insert("", "end", values=(f"TX: {io.bytes_sent} bytes", "", ""))
                    tree.insert("", "end", values=(f"RX: {io.bytes_recv} bytes", "", ""))
        except Exception as e:
            self.append_log("ERROR", f"Failed to get network info: {e}")

    # ---------- Disk ----------
    def show_disk(self):
        self._stop_dashboard = True
        self.clear_content()
        frame = self.content
        ctk.CTkLabel(frame, text="Disk Usage", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="nw", padx=12, pady=(12,8))
        tree_frame = ctk.CTkFrame(frame); tree_frame.pack(fill="both", expand=True, padx=12, pady=(0,12))
        tree = ttk.Treeview(tree_frame, columns=("total","used","free","percent"), show="headings", height=24)
        tree.heading("total", text="Total"); tree.heading("used", text="Used"); tree.heading("free", text="Free"); tree.heading("percent", text="Percent")
        tree.column("total", width=220); tree.column("used", width=220); tree.column("free", width=220); tree.column("percent", width=120, anchor="center")
        tree.pack(fill="both", expand=True, side="left")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview); tree.configure(yscroll=scrollbar.set); scrollbar.pack(side="right", fill="y")
        self.disk_tree = tree
        self._refresh_disk()

    def _refresh_disk(self):
        tree = self.disk_tree
        for i in tree.get_children(): tree.delete(i)
        try:
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    tree.insert("", "end", values=(part.device, _sizeof_fmt(usage.total), _sizeof_fmt(usage.used), f"{usage.percent}%"))
                except Exception:
                    continue
        except Exception as e:
            self.append_log("ERROR", f"Disk info failed: {e}")

    # ---------- Logs ----------
    def show_logs(self):
        self._stop_dashboard = True
        self.clear_content()
        frame = self.content
        ctk.CTkLabel(frame, text="Logs", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="nw", padx=12, pady=(12,8))
        toolbar = ctk.CTkFrame(frame); toolbar.pack(fill="x", padx=12, pady=(0,8))
        ctk.CTkButton(toolbar, text="Clear Logs", command=self._clear_logs).pack(side="left", padx=(0,8))
        ctk.CTkButton(toolbar, text="Save Logs...", command=self._save_logs).pack(side="left")
        ctk.CTkButton(toolbar, text="Copy Logs", command=self._copy_logs).pack(side="left", padx=(8,0))
        ctk.CTkLabel(toolbar, text="Filter Level:").pack(side="right", padx=(4,0))
        self.level_filter_var = ctk.StringVar(value="ALL")
        ctk.CTkComboBox(toolbar, values=["ALL","INFO","WARN","ERROR"], variable=self.level_filter_var, command=self._apply_level_filter).pack(side="right", padx=(4,8))
        self.autoscroll_var = ctk.BooleanVar(value=self.autoscroll)
        ctk.CTkCheckBox(toolbar, text="Auto-scroll", variable=self.autoscroll_var, command=self._toggle_autoscroll).pack(side="right", padx=(8,0))
        txt = scrolledtext.ScrolledText(frame, wrap="word", height=28, bg="#1f1f1f", fg="#e6e6e6", insertbackground="#e6e6e6", font=("Consolas",10))
        txt.pack(fill="both", expand=True, padx=12, pady=(0,12))
        self.logs_widget = txt
        # populate
        for l in self.logs:
            if self.level_filter_var.get() == "ALL" or f"] {self.level_filter_var.get()}:" in l:
                try:
                    txt.insert("end", l + "\n")
                except Exception:
                    pass
        txt.see("end")
        try:
            txt.config(state="disabled")
        except Exception:
            pass

    def _clear_logs(self):
        if messagebox.askyesno("Clear Logs", "Clear all logs?"):
            self.logs = []
            if self.logs_widget:
                try:
                    self.logs_widget.config(state="normal"); self.logs_widget.delete("1.0","end"); self.logs_widget.config(state="disabled")
                except Exception:
                    pass

    def _save_logs(self):
        path = filedialog.asksaveasfilename(defaultextension=".log", filetypes=[("Log files","*.log"),("All files","*.*")])
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(self.logs))
                messagebox.showinfo(APP_NAME, f"Logs saved to {path}")
            except Exception as e:
                messagebox.showerror(APP_NAME, f"Failed to save logs: {e}")

    def _copy_logs(self):
        try:
            text = "\n".join(self.logs)
            self.clipboard_clear(); self.clipboard_append(text)
            messagebox.showinfo(APP_NAME, "Logs copied to clipboard.")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Failed to copy logs: {e}")

    def _apply_level_filter(self, val=None):
        if self.logs_widget:
            try:
                cur = self.level_filter_var.get()
                self.logs_widget.config(state="normal"); self.logs_widget.delete("1.0","end")
                for l in self.logs:
                    if cur == "ALL" or f"] {cur}:" in l:
                        self.logs_widget.insert("end", l + "\n")
                if self.autoscroll_var.get(): self.logs_widget.see("end")
                self.logs_widget.config(state="disabled")
            except Exception:
                pass

    def _toggle_autoscroll(self):
        self.autoscroll = self.autoscroll_var.get()

    # ---------- Utilities (many) ----------
    def open_scripts_folder(self):
        folder = resource_path(SCRIPTS_DIR)
        os.makedirs(folder, exist_ok=True)
        try:
            subprocess.Popen(["explorer", folder])
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Failed to open folder: {e}")

    def clear_user_temp(self):
        temp = os.environ.get("TEMP") or os.environ.get("TMP")
        if not temp:
            messagebox.showerror(APP_NAME, "Could not find TEMP folder.")
            return
        if not messagebox.askyesno("Clear User Temp", f"Clear user temp folder: {temp}?"):
            return
        def worker():
            self.append_log("INFO", f"Clearing user temp: {temp}")
            try:
                for entry in os.listdir(temp):
                    path = os.path.join(temp, entry)
                    try:
                        if os.path.isfile(path) or os.path.islink(path):
                            os.unlink(path)
                        elif os.path.isdir(path):
                            shutil.rmtree(path, ignore_errors=True)
                    except Exception as e:
                        self.append_log("WARN", f"Skipped {path}: {e}")
                self.append_log("INFO", "User TEMP cleared.")
                self.ui_call(messagebox.showinfo, APP_NAME, "User TEMP cleared.")
            except Exception as e:
                self.append_log("ERROR", f"Error clearing TEMP: {e}")
                self.ui_call(messagebox.showerror, APP_NAME, f"Error clearing TEMP: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def schedule_cleanup_dialog(self):
        # Simple schedule dialog: run daily at HH:MM
        time_str = simpledialog.askstring("Schedule Cleanup", "Enter daily time (HH:MM, 24h) to schedule cleanup (or Cancel):", parent=self)
        if not time_str:
            return
        try:
            hour, minute = map(int, time_str.split(":"))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError
        except Exception:
            messagebox.showerror(APP_NAME, "Invalid time format.")
            return
        # build schtasks command (runs the installed exe; here assume current exe path)
        exe_path = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(sys.argv[0])
        taskname = "WinSysUtility_DeepCleanup"
        time_arg = f"{hour:02d}:{minute:02d}"
        cmd = ["schtasks", "/Create", "/SC", "DAILY", "/TN", taskname, "/TR", f'"{exe_path}" --elevated-action cleanup', "/ST", time_arg, "/F"]
        def worker():
            try:
                subprocess.run(" ".join(cmd), shell=True, check=True)
                self.append_log("INFO", f"Scheduled cleanup daily at {time_arg}")
                self.ui_call(messagebox.showinfo, APP_NAME, f"Scheduled cleanup daily at {time_arg}")
            except Exception as e:
                self.append_log("ERROR", f"Failed to schedule task: {e}")
                self.ui_call(messagebox.showerror, APP_NAME, f"Failed to schedule task: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def export_settings(self):
        settings = {
            "theme": ctk.get_appearance_mode(),
            "log_level": getattr(self, "loglevel_var", ctk.StringVar(value="INFO")).get() if hasattr(self, "loglevel_var") else "INFO",
            "dry_run_default": getattr(self, "dry_run_var", ctk.BooleanVar(value=False)).get() if hasattr(self, "dry_run_var") else False
        }
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")])
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(settings, f, indent=2)
                messagebox.showinfo(APP_NAME, f"Settings exported to {path}")
            except Exception as e:
                messagebox.showerror(APP_NAME, f"Failed to export settings: {e}")

    def import_settings(self):
        path = filedialog.askopenfilename(filetypes=[("JSON","*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                settings = json.load(f)
            theme = settings.get("theme")
            if theme:
                ctk.set_appearance_mode(theme)
            lvl = settings.get("log_level")
            if lvl and hasattr(self, "loglevel_var"):
                self.loglevel_var.set(lvl)
            dr = settings.get("dry_run_default")
            if dr is not None and hasattr(self, "dry_run_var"):
                self.dry_run_var.set(bool(dr))
            messagebox.showinfo(APP_NAME, "Settings imported.")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Failed to import settings: {e}")

    def toggle_theme(self):
        cur = ctk.get_appearance_mode()
        ctk.set_appearance_mode("light" if cur == "dark" else "dark")
        self.append_log("INFO", f"Toggled theme to {ctk.get_appearance_mode()}")

    def check_for_updates(self):
        # placeholder: log a check and simulate no updates
        self.append_log("INFO", "Checking for updates...")
        def worker():
            time.sleep(1.2)
            self.append_log("INFO", "No updates found (placeholder).")
            self.ui_call(messagebox.showinfo, APP_NAME, "No updates available (placeholder).")
        threading.Thread(target=worker, daemon=True).start()

    def run_powershell_dialog(self):
        cmd = simpledialog.askstring("Run PowerShell", "Enter PowerShell command(s) to run:", parent=self)
        if not cmd:
            return
        # write to a temp script file
        temp_script = os.path.join(os.environ.get("TEMP", "."), f"tmp_ps_{int(time.time())}.ps1")
        try:
            with open(temp_script, "w", encoding="utf-8") as f:
                f.write(cmd)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Failed to write temp script: {e}")
            return
        def worker():
            self.append_log("INFO", f"Running PowerShell temp script: {temp_script}")
            try:
                run_powershell_stream_to_queue(temp_script, args=[], out_queue=self.log_queue)
            except Exception as e:
                self.append_log("ERROR", f"PowerShell run failed: {e}")
            finally:
                try: os.remove(temp_script)
                except Exception: pass
        threading.Thread(target=worker, daemon=True).start()

    def test_elevation(self):
        if is_admin():
            messagebox.showinfo(APP_NAME, "Already running elevated.")
            return
        if messagebox.askyesno("Test Elevation", "Relaunch app as Administrator to test elevation?"):
            # Relaunch with a simple elevated-action that does nothing but confirm
            if relaunch_as_admin(["--elevated-action","test-elev"]):
                self.append_log("INFO", "Relaunching elevated for test...")
                self.destroy(); sys.exit(0)
            else:
                messagebox.showerror(APP_NAME, "Failed to relaunch elevated.")

    # ---------- Export/Import Helpers ----------
    # (already implemented above in export_settings / import_settings)

    # ---------- Startup handling for elevated actions ----------
    def _maybe_handle_startup_args(self):
        argv = self.argv
        if "--elevated-action" in argv:
            idx = argv.index("--elevated-action")
            if idx + 1 < len(argv):
                action = argv[idx+1]
                if not is_admin():
                    messagebox.showerror(APP_NAME, "Requested elevated action but process is not elevated.")
                    return
                if action == "cleanup":
                    # extract flags
                    self.dry_run_var = ctk.BooleanVar(value="--dry-run" in argv)
                    lvl = "info"
                    if "--loglevel" in argv:
                        i = argv.index("--loglevel")
                        if i+1 < len(argv):
                            lvl = argv[i+1]
                    self.loglevel_var = ctk.StringVar(value=lvl.upper())
                    self.show_cleanup()
                    # run cleanup automatically
                    self._run_cleanup_after_relaunch()
                elif action == "test-elev":
                    messagebox.showinfo(APP_NAME, "Elevated test: running as Administrator.")
                    self.append_log("INFO", "Elevated test completed.")

    def _run_cleanup_after_relaunch(self):
        # Called when app was relaunched elevated via elevated-action cleanup
        exe_rel = os.path.join(SCRIPTS_DIR, CLEANUP_EXE); ps1_rel = os.path.join(SCRIPTS_DIR, CLEANUP_PS1)
        exe_path = resource_path(exe_rel); ps1_path = resource_path(ps1_rel)
        if os.path.exists(exe_path): use_exe = True; target = exe_path
        elif os.path.exists(ps1_path): use_exe = False; target = ps1_path
        else:
            messagebox.showerror(APP_NAME, f"No cleanup module found. Expected one of:\n - {exe_rel}\n - {ps1_rel}")
            return
        args = []
        if getattr(self, "dry_run_var", ctk.BooleanVar(value=False)).get(): args.append("--dry-run")
        lvl = getattr(self, "loglevel_var", ctk.StringVar(value="INFO")).get().lower()
        if lvl != "all": args += ["--loglevel", lvl]
        def worker():
            self.append_log("INFO", f"(Elevated) Starting cleanup (dry={self.dry_run_var.get()}, level={lvl})")
            try:
                if use_exe:
                    run_executable_stream_to_queue(target, args=args, out_queue=self.log_queue)
                else:
                    run_powershell_stream_to_queue(target, args=args, out_queue=self.log_queue)
                self.append_log("INFO", "(Elevated) Cleanup finished.")
            except Exception as e:
                self.append_log("ERROR", f"(Elevated) Cleanup failed: {e}")
        threading.Thread(target=worker, daemon=True).start()

    # ---------- Misc ----------
    def clear_content(self):
        for w in self.content.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        self.logs_widget = None

# ---------- Utility functions ----------
def _format_seconds(sec: float) -> str:
    sec = int(sec)
    days, sec = divmod(sec, 86400)
    hours, sec = divmod(sec, 3600)
    minutes, sec = divmod(sec, 60)
    parts = []
    if days: parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    parts.append(f"{sec}s")
    return " ".join(parts)

def _sizeof_fmt(num, suffix="B"):
    for unit in ["", "K", "M", "G", "T", "P"]:
        if abs(num) < 1024.0:
            return f"{num:.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}E{suffix}"

# ---------- Run app ----------
if __name__ == "__main__":
    app = App(sys.argv[1:])
    app.mainloop()