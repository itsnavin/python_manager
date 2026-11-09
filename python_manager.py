#!/usr/bin/env python3
"""
python_manager.py - GUI Python version and module installer for Linux
Supports Ubuntu/Debian (apt + deadsnakes PPA) on x86-64 and ARM.
Requires: python3-tk
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog
import subprocess
import threading
import shutil
import sys
import os
import re
import platform

APP_NAME = "Python Manager"
APP_VERSION = "1.0.1"
GITHUB = "https://github.com/itsnavin"

# ── Python versions offered in the UI ────────────────────────────────────────
# Availability on the running distro is probed at start-up via apt-cache.
PYTHON_VERSIONS = ["3.10", "3.11", "3.12", "3.13", "3.14"]

# Ubuntu series supported by the deadsnakes PPA (it ships Python 3.7+ for these;
# the one version Ubuntu itself provides comes from the main archive instead).
# Interim releases (24.10, 25.04, 25.10 ...) are NOT supported by deadsnakes.
DEADSNAKES_SERIES = {"jammy", "noble", "resolute"}


def read_os_release():
    info = {}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if "=" in line:
                    k, v = line.rstrip().split("=", 1)
                    info[k] = v.strip('"')
    except FileNotFoundError:
        pass
    return info


def clean_env():
    """Environment for child processes.  A PyInstaller one-file binary sets
    LD_LIBRARY_PATH to its private extract dir, which can break apt / system
    python; restore the original value."""
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        orig = env.get("LD_LIBRARY_PATH_ORIG")
        if orig is not None:
            env["LD_LIBRARY_PATH"] = orig
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env


def target_user():
    """(name, home) of the real desktop user, even if the app runs via sudo."""
    import pwd
    name = os.environ.get("SUDO_USER") if os.geteuid() == 0 else None
    pw = pwd.getpwnam(name) if name else pwd.getpwuid(os.getuid())
    return pw.pw_name, pw.pw_dir


def parse_module_names(text):
    """Split free-text module input on commas/whitespace; keep pip specifiers."""
    return [t for t in re.split(r"[,\s]+", text.strip()) if t]

# ── Module catalogue (name shown in UI : pip package name) ────────────────────
MODULES = {
    "Data Science": {
        "NumPy":        "numpy",
        "Pandas":       "pandas",
        "Matplotlib":   "matplotlib",
        "SciPy":        "scipy",
        "Seaborn":      "seaborn",
        "Plotly":       "plotly",
        "statsmodels":  "statsmodels",
        "xarray":       "xarray",
        "Polars":       "polars",
    },
    "Machine Learning / AI": {
        "scikit-learn":  "scikit-learn",
        "TensorFlow":    "tensorflow",
        "PyTorch":       "torch",
        "Transformers":  "transformers",
        "LightGBM":      "lightgbm",
        "XGBoost":       "xgboost",
        "CatBoost":      "catboost",
        "ONNX":          "onnx",
    },
    "Web / HTTP": {
        "Requests":        "requests",
        "HTTPX":           "httpx",
        "aiohttp":         "aiohttp",
        "Flask":           "flask",
        "Django":          "django",
        "FastAPI":         "fastapi",
        "Uvicorn":         "uvicorn",
        "BeautifulSoup4":  "beautifulsoup4",
        "Scrapy":          "scrapy",
        "Starlette":       "starlette",
    },
    "Database": {
        "SQLAlchemy":        "sqlalchemy",
        "PyMySQL":           "pymysql",
        "psycopg2":          "psycopg2-binary",
        "PyMongo":           "pymongo",
        "Redis-py":          "redis",
        "Motor (async Mongo)": "motor",
        "Alembic":           "alembic",
    },
    "Utilities": {
        "Pillow":          "pillow",
        "python-dotenv":   "python-dotenv",
        "Pydantic":        "pydantic",
        "Click":           "click",
        "Rich":            "rich",
        "Loguru":          "loguru",
        "pytest":          "pytest",
        "Black":           "black",
        "Flake8":          "flake8",
        "mypy":            "mypy",
        "tqdm":            "tqdm",
        "Typer":           "typer",
        "Cryptography":    "cryptography",
        "paramiko":        "paramiko",
    },
    "IoT / Hardware": {
        "RPi.GPIO":          "RPi.GPIO",
        "gpiozero":          "gpiozero",
        "smbus2":            "smbus2",
        "pyserial":          "pyserial",
        "spidev":            "spidev",
        "pigpio":            "pigpio",
        "Adafruit Blinka":   "adafruit-blinka",
    },
    "Data Formats": {
        "openpyxl":     "openpyxl",
        "PyYAML":       "pyyaml",
        "LXML":         "lxml",
        "jsonschema":   "jsonschema",
        "TOML":         "toml",
        "Arrow":        "arrow",
        "msgpack":      "msgpack",
    },
}

# ── Colour scheme ─────────────────────────────────────────────────────────────
DARK_BG   = "#1e1e2e"
PANEL_BG  = "#2a2a3e"
ACCENT    = "#7c6af7"
ACCENT2   = "#5a9fd4"
FG        = "#cdd6f4"
FG_DIM    = "#6c7086"
FG_HEAD   = "#f5c2e7"
SUCCESS   = "#a6e3a1"
ERROR     = "#f38ba8"
WARN      = "#fab387"
BTN_FG    = "#ffffff"
SEL_BG    = "#3e3e5e"


class PythonManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("960x720")
        self.minsize(820, 600)
        self.configure(bg=DARK_BG)
        self._sudo_password = None
        self._installing = False

        # State vars
        self.selected_version = tk.StringVar(value=PYTHON_VERSIONS[-2])  # default to 3.13
        self.set_default_var = tk.BooleanVar(value=True)
        self.also_pip_var   = tk.BooleanVar(value=True)
        self.search_var     = tk.StringVar()
        self.custom_mods_var = tk.StringVar()
        self.search_var.trace_add("write", self._filter_modules)

        # {pip_package: BooleanVar}
        self.module_vars: dict[str, tk.BooleanVar] = {}

        self._build_ui()
        self._populate_modules()
        self._detect_system()

    # ── UI build ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=ACCENT, height=4)
        hdr.pack(fill="x")

        title_frame = tk.Frame(self, bg=DARK_BG, pady=10)
        title_frame.pack(fill="x", padx=20)
        tk.Label(title_frame, text="🐍 " + APP_NAME, font=("sans-serif", 18, "bold"),
                 bg=DARK_BG, fg=ACCENT).pack(side="left")
        self._sys_label = tk.Label(title_frame, text="detecting system…",
                                   font=("monospace", 10), bg=DARK_BG, fg=FG_DIM)
        self._sys_label.pack(side="right")

        # Main two-column body
        body = tk.Frame(self, bg=DARK_BG)
        body.pack(fill="both", expand=True, padx=16, pady=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_version_panel(body)
        self._build_module_panel(body)

        # Options bar
        opts = tk.Frame(self, bg=PANEL_BG, pady=8)
        opts.pack(fill="x", padx=16, pady=(0, 6))

        tk.Checkbutton(opts, text="Ask to set as default python  (update-alternatives)",
                       variable=self.set_default_var,
                       bg=PANEL_BG, fg=FG, selectcolor=PANEL_BG,
                       activebackground=PANEL_BG, activeforeground=FG,
                       font=("sans-serif", 10)).pack(side="left", padx=12)

        tk.Checkbutton(opts, text="Also install pip + venv",
                       variable=self.also_pip_var,
                       bg=PANEL_BG, fg=FG, selectcolor=PANEL_BG,
                       activebackground=PANEL_BG, activeforeground=FG,
                       font=("sans-serif", 10)).pack(side="left", padx=12)

        self.install_btn = tk.Button(
            opts, text="  Install  ", font=("sans-serif", 11, "bold"),
            bg=ACCENT, fg=BTN_FG, activebackground="#6355cc", activeforeground=BTN_FG,
            relief="flat", padx=18, pady=5, cursor="hand2",
            command=self._start_install)
        self.install_btn.pack(side="right", padx=12)

        # Log area
        log_hdr = tk.Frame(self, bg=DARK_BG)
        log_hdr.pack(fill="x", padx=16)
        tk.Label(log_hdr, text="Output", font=("sans-serif", 9, "bold"),
                 bg=DARK_BG, fg=FG_DIM).pack(side="left")
        tk.Button(log_hdr, text="Clear", font=("sans-serif", 8),
                  bg=DARK_BG, fg=FG_DIM, relief="flat", cursor="hand2",
                  command=lambda: self._log_clear()).pack(side="right")

        self.log = scrolledtext.ScrolledText(
            self, height=9, state="disabled",
            bg="#11111b", fg=FG, insertbackground=FG,
            font=("monospace", 9), relief="flat",
            padx=10, pady=8)
        self.log.pack(fill="x", padx=16, pady=(2, 10))
        self.log.tag_config("ok",   foreground=SUCCESS)
        self.log.tag_config("err",  foreground=ERROR)
        self.log.tag_config("warn", foreground=WARN)
        self.log.tag_config("hd",   foreground=FG_HEAD)
        self.log.tag_config("dim",  foreground=FG_DIM)

    def _build_version_panel(self, parent):
        pane = tk.Frame(parent, bg=PANEL_BG, padx=16, pady=12,
                        relief="flat", bd=0)
        pane.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=4)

        tk.Label(pane, text="Python Version", font=("sans-serif", 11, "bold"),
                 bg=PANEL_BG, fg=FG_HEAD).pack(anchor="w", pady=(0, 10))

        for v in PYTHON_VERSIONS:
            row = tk.Frame(pane, bg=PANEL_BG)
            row.pack(fill="x", pady=2)
            rb = tk.Radiobutton(
                row, text=f"Python {v}", variable=self.selected_version, value=v,
                bg=PANEL_BG, fg=FG, selectcolor=SEL_BG,
                activebackground=PANEL_BG, activeforeground=FG,
                font=("monospace", 11), cursor="hand2",
                command=self._on_version_change)
            rb.pack(side="left")
            self._make_version_label(row, v)

        # currently installed marker
        tk.Frame(pane, bg=FG_DIM, height=1).pack(fill="x", pady=12)
        tk.Label(pane, text="Installed", font=("sans-serif", 9, "bold"),
                 bg=PANEL_BG, fg=FG_DIM).pack(anchor="w")
        self._inst_label = tk.Label(pane, text="checking…",
                                    font=("monospace", 9), bg=PANEL_BG, fg=FG_DIM,
                                    justify="left", wraplength=140)
        self._inst_label.pack(anchor="w", pady=(4, 0))

    def _make_version_label(self, row, ver):
        """Add a small badge if the version is already installed."""
        try:
            r = subprocess.run([f"python{ver}", "--version"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                tk.Label(row, text="✔ installed", font=("sans-serif", 8),
                         bg=PANEL_BG, fg=SUCCESS).pack(side="right", padx=4)
        except FileNotFoundError:
            pass

    def _build_module_panel(self, parent):
        right = tk.Frame(parent, bg=DARK_BG)
        right.grid(row=0, column=1, sticky="nsew", pady=4)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # Search bar
        srch = tk.Frame(right, bg=PANEL_BG, pady=4, padx=8)
        srch.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        srch.columnconfigure(1, weight=1)
        tk.Label(srch, text="🔍", bg=PANEL_BG, fg=FG_DIM,
                 font=("sans-serif", 11)).grid(row=0, column=0, padx=(4, 2))
        tk.Entry(srch, textvariable=self.search_var,
                 bg=PANEL_BG, fg=FG, insertbackground=FG,
                 relief="flat", font=("sans-serif", 10)).grid(
                 row=0, column=1, sticky="ew", padx=4)
        btn_row = tk.Frame(srch, bg=PANEL_BG)
        btn_row.grid(row=0, column=2)
        tk.Button(btn_row, text="All", font=("sans-serif", 8),
                  bg=ACCENT, fg=BTN_FG, relief="flat", cursor="hand2",
                  command=self._select_all).pack(side="left", padx=2)
        tk.Button(btn_row, text="None", font=("sans-serif", 8),
                  bg=PANEL_BG, fg=FG_DIM, relief="flat", cursor="hand2",
                  command=self._select_none).pack(side="left", padx=2)

        # Scrollable module canvas
        canvas_frame = tk.Frame(right, bg=DARK_BG, relief="flat")
        canvas_frame.grid(row=1, column=0, sticky="nsew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(canvas_frame, bg=DARK_BG,
                                highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(canvas_frame, orient="vertical",
                            command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self.module_frame = tk.Frame(self.canvas, bg=DARK_BG)
        self._canvas_window = self.canvas.create_window(
            (0, 0), window=self.module_frame, anchor="nw")

        self.module_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>",   self._on_mousewheel)
        self.canvas.bind_all("<Button-4>",     self._on_mousewheel)
        self.canvas.bind_all("<Button-5>",     self._on_mousewheel)

        # Selection counter
        self._sel_label = tk.Label(right, text="0 modules selected",
                                   font=("sans-serif", 9), bg=DARK_BG, fg=FG_DIM)
        self._sel_label.grid(row=2, column=0, sticky="w", padx=4, pady=2)

        # Custom module input (any pip package not in the list)
        cust = tk.Frame(right, bg=PANEL_BG, pady=4, padx=8)
        cust.grid(row=3, column=0, sticky="ew", pady=(2, 0))
        cust.columnconfigure(1, weight=1)
        tk.Label(cust, text="Other modules:", bg=PANEL_BG, fg=FG_HEAD,
                 font=("sans-serif", 9, "bold")).grid(row=0, column=0, padx=(2, 6))
        tk.Entry(cust, textvariable=self.custom_mods_var,
                 bg="#11111b", fg=FG, insertbackground=FG, relief="flat",
                 font=("monospace", 10)).grid(row=0, column=1, sticky="ew", ipady=3)
        tk.Label(cust, text="e.g.  opencv-python, flask==3.0  pyqt5",
                 bg=PANEL_BG, fg=FG_DIM, font=("sans-serif", 8)).grid(
                 row=1, column=1, sticky="w")
        self.custom_mods_var.trace_add("write",
                                       lambda *_: self._update_sel_count())

    # ── Module list population ────────────────────────────────────────────────
    def _populate_modules(self, filter_text=""):
        for w in self.module_frame.winfo_children():
            w.destroy()
        ft = filter_text.lower()

        for category, pkgs in MODULES.items():
            matching = {label: pkg for label, pkg in pkgs.items()
                        if not ft or ft in label.lower() or ft in pkg.lower()}
            if not matching:
                continue

            cat_row = tk.Frame(self.module_frame, bg=DARK_BG)
            cat_row.pack(fill="x", padx=8, pady=(10, 2))
            tk.Label(cat_row, text=category, font=("sans-serif", 10, "bold"),
                     bg=DARK_BG, fg=FG_HEAD).pack(side="left")
            tk.Frame(cat_row, bg=FG_DIM, height=1).pack(
                side="left", fill="x", expand=True, padx=(8, 0))

            cols = 2
            grid = tk.Frame(self.module_frame, bg=DARK_BG)
            grid.pack(fill="x", padx=8)
            for i, (label, pkg) in enumerate(matching.items()):
                if pkg not in self.module_vars:
                    self.module_vars[pkg] = tk.BooleanVar(value=False)
                cb = tk.Checkbutton(
                    grid, text=label, variable=self.module_vars[pkg],
                    bg=DARK_BG, fg=FG, selectcolor=SEL_BG,
                    activebackground=DARK_BG, activeforeground=FG,
                    font=("sans-serif", 10), cursor="hand2",
                    command=self._update_sel_count,
                    anchor="w")
                cb.grid(row=i // cols, column=i % cols, sticky="w", padx=4, pady=1)
            for c in range(cols):
                grid.columnconfigure(c, weight=1)

        self.module_frame.update_idletasks()
        self._update_sel_count()

    def _filter_modules(self, *_):
        self._populate_modules(self.search_var.get())

    def _select_all(self):
        for v in self.module_vars.values():
            v.set(True)
        self._update_sel_count()

    def _select_none(self):
        for v in self.module_vars.values():
            v.set(False)
        self._update_sel_count()

    def _update_sel_count(self):
        n = sum(1 for v in self.module_vars.values() if v.get())
        if hasattr(self, "custom_mods_var"):
            n += len(parse_module_names(self.custom_mods_var.get()))
        self._sel_label.config(text=f"{n} module{'s' if n != 1 else ''} selected")

    # ── Canvas scroll helpers ─────────────────────────────────────────────────
    def _on_frame_configure(self, _):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self._canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        if event.num == 4 or event.delta > 0:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0:
            self.canvas.yview_scroll(1, "units")

    # ── System detection ─────────────────────────────────────────────────────
    def _detect_system(self):
        def probe():
            arch = platform.machine()
            distro = "unknown"
            try:
                with open("/etc/os-release") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            distro = line.split("=", 1)[1].strip().strip('"')
                            break
            except FileNotFoundError:
                pass
            installed = []
            for v in PYTHON_VERSIONS:
                if shutil.which(f"python{v}"):
                    installed.append(v)
            self.after(0, lambda: self._sys_label.config(
                text=f"{distro}  |  {arch}"))
            self.after(0, lambda: self._inst_label.config(
                text="\n".join(installed) if installed else "none detected"))

        threading.Thread(target=probe, daemon=True).start()

    def _on_version_change(self):
        pass  # badge already shown at startup

    # ── Logging ───────────────────────────────────────────────────────────────
    def _log(self, msg, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n", tag or "")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _log_clear(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ── Sudo password dialog ──────────────────────────────────────────────────
    def _ask_sudo_password(self):
        dlg = tk.Toplevel(self)
        dlg.title("Authentication required")
        dlg.configure(bg=DARK_BG)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.geometry("360x180")
        result = {"pw": None}

        tk.Label(dlg, text="🔒  sudo password required",
                 font=("sans-serif", 12, "bold"),
                 bg=DARK_BG, fg=FG_HEAD).pack(pady=(20, 4))
        tk.Label(dlg, text="Enter your password to allow installation:",
                 bg=DARK_BG, fg=FG, font=("sans-serif", 9)).pack()

        entry = tk.Entry(dlg, show="●", bg=PANEL_BG, fg=FG,
                         insertbackground=FG, font=("monospace", 11),
                         relief="flat", width=28)
        entry.pack(pady=10)
        entry.focus_set()

        def ok(_=None):
            result["pw"] = entry.get()
            dlg.destroy()

        def cancel():
            dlg.destroy()

        btns = tk.Frame(dlg, bg=DARK_BG)
        btns.pack()
        tk.Button(btns, text="OK", width=8, bg=ACCENT, fg=BTN_FG,
                  relief="flat", command=ok).pack(side="left", padx=4)
        tk.Button(btns, text="Cancel", width=8, bg=PANEL_BG, fg=FG,
                  relief="flat", command=cancel).pack(side="left", padx=4)
        entry.bind("<Return>", ok)
        dlg.wait_window()
        return result["pw"]

    # ── subprocess helper: stream lines into log ──────────────────────────────
    def _run_stream(self, cmd, use_sudo=True, check_rc=True):
        """Run a command, streaming output to the log. Returns returncode."""
        if use_sudo:
            full_cmd = ["sudo", "-S", "-p", "", "--"] + cmd
        elif os.geteuid() == 0 and os.environ.get("SUDO_USER"):
            # App was started with sudo: never let pip etc. run as root
            full_cmd = ["sudo", "-u", os.environ["SUDO_USER"], "-H", "--"] + cmd
        else:
            full_cmd = cmd

        self._log(f"$ {' '.join(cmd)}", "dim")
        try:
            proc = subprocess.Popen(
                full_cmd,
                stdin=subprocess.PIPE if use_sudo else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, bufsize=1, env=clean_env())

            if use_sudo:
                if self._sudo_password is not None:
                    proc.stdin.write(self._sudo_password + "\n")
                    proc.stdin.flush()
                proc.stdin.close()

            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                tag = None
                ll = line.lower()
                if any(w in ll for w in ("error", "failed", "unable", "cannot")):
                    tag = "err"
                elif any(w in ll for w in ("warning", "warn")):
                    tag = "warn"
                self._log(line, tag)
            proc.wait()
        except FileNotFoundError as e:
            self._log(f"Command not found: {e}", "err")
            return 127
        except OSError as e:          # e.g. PermissionError
            self._log(f"Cannot run {cmd[0]}: {e}", "err")
            return 126
        return proc.returncode

    # ── Validation helpers ────────────────────────────────────────────────────
    def _test_sudo(self):
        """Return True if stored sudo password is valid (or user is root)."""
        if os.geteuid() == 0:
            return True
        rc = subprocess.run(
            ["sudo", "-S", "-p", "", "true"],
            input=(self._sudo_password or "") + "\n",
            capture_output=True, text=True).returncode
        return rc == 0

    def _detect_distro_family(self):
        """Return 'debian' or 'other'."""
        if shutil.which("apt-get"):
            return "debian"
        return "other"

    # ── Main install flow ─────────────────────────────────────────────────────
    def _start_install(self):
        if self._installing:
            return
        version = self.selected_version.get()
        modules = [pkg for pkg, v in self.module_vars.items() if v.get()]
        for m in parse_module_names(self.custom_mods_var.get()):
            if m not in modules:
                modules.append(m)

        if not messagebox.askyesno(
                "Confirm installation",
                f"Install Python {version}" +
                (f" and {len(modules)} module(s)" if modules else "") + "?"):
            return

        # Ask for sudo password once
        if os.geteuid() != 0:
            pw = self._ask_sudo_password()
            if pw is None:
                return
            self._sudo_password = pw
            if not self._test_sudo():
                messagebox.showerror("Authentication failed",
                                     "Incorrect password. Please try again.")
                self._sudo_password = None
                return

        self._installing = True
        self._home_fixed = False
        self.install_btn.config(state="disabled", text=" Installing… ")
        self._log_clear()

        t = threading.Thread(
            target=self._install_worker,
            args=(version, modules, self.set_default_var.get(),
                  self.also_pip_var.get()),
            daemon=True)
        t.start()

    def _install_worker(self, version, modules, set_default, also_pip):
        ok = True
        try:
            family = self._detect_distro_family()
            if family == "debian":
                ok = self._install_python_debian(version, also_pip)
            else:
                ok = self._install_python_other(version)

            if ok and set_default:
                choice = self._ask_default_from_worker(version)
                if choice == "both":
                    self._set_default(version, ("python", "python3"))
                elif choice == "python":
                    self._set_default(version, ("python",))
                else:
                    self.after(0, lambda: self._log(
                        "Skipped update-alternatives (user choice).", "dim"))

            if ok and also_pip and family != "debian":
                self._install_pip(version)
            if ok and modules:
                self._fix_home_ownership()
                self._install_modules(version, modules)

        except Exception as e:
            self.after(0, lambda: self._log(f"Unexpected error: {e}", "err"))
            ok = False
        finally:
            tag = "ok" if ok else "err"
            msg = "✔  All done!" if ok else "✘  Installation finished with errors."
            self.after(0, lambda: self._log(msg, tag))
            self.after(0, lambda: self.install_btn.config(
                state="normal", text="  Install  "))
            self._installing = False
            self.after(0, self._refresh_badges)

    def _ask_default_from_worker(self, version):
        """Ask (on the Tk main thread) whether to make this the default python."""
        result = {}
        done = threading.Event()

        def ask():
            ans = messagebox.askyesnocancel(
                "Set default Python?",
                f"Python {version} is installed.\n\n"
                f"Make it the default via update-alternatives?\n\n"
                f"  YES    → /usr/bin/python AND /usr/bin/python3\n"
                f"  NO     → only /usr/bin/python (safer)\n"
                f"  CANCEL → don't change anything\n\n"
                f"⚠ Changing python3 can break apt and other system tools "
                f"on Debian / Ubuntu / Raspberry Pi OS.",
                icon="warning", parent=self)
            result["v"] = {True: "both", False: "python"}.get(ans, "skip")
            done.set()

        self.after(0, ask)
        done.wait()
        return result["v"]

    # ── Debian/Ubuntu install ─────────────────────────────────────────────────
    def _install_python_debian(self, version, also_pip):  # noqa: C901
        self._log(f"\n── Installing Python {version} ──", "hd")


        # Detect Ubuntu (needs deadsnakes) vs Debian/Raspberry Pi OS (direct apt)
        is_ubuntu = False
        try:
            with open("/etc/os-release") as f:
                content = f.read().lower()
                is_ubuntu = "ubuntu" in content
        except FileNotFoundError:
            pass

        # Step 1: Check if the version is already in apt
        r0 = subprocess.run(["apt-cache", "policy", f"python{version}"],
                            capture_output=True, text=True)
        in_apt = ("Candidate:" in r0.stdout and "(none)" not in r0.stdout)

        if not in_apt:
            if is_ubuntu:
                # Not in apt yet → add deadsnakes PPA and retry
                self._log(
                    f"Python {version} not found in apt — adding "
                    f"deadsnakes PPA…", "dim")
                self._run_stream(
                    ["apt-get", "install", "-y", "software-properties-common"],
                    use_sudo=True)
                self._run_stream(
                    ["add-apt-repository", "-y", "ppa:deadsnakes/ppa"],
                    use_sudo=True)
                self._run_stream(["apt-get", "update", "-q"], use_sudo=True)
                r1 = subprocess.run(["apt-cache", "policy", f"python{version}"],
                                    capture_output=True, text=True)
                if "Candidate:" not in r1.stdout or "(none)" in r1.stdout:
                    self._log(
                        f"✘  Python {version} is not available from deadsnakes\n"
                        f"   on this Ubuntu release.\n"
                        f"   deadsnakes supports 22.04 / 24.04 / 26.04 LTS only.\n"
                        f"   Try Python 3.12 (ships with Ubuntu 24.04).",
                        "err")
                    return False
            else:
                # Non-Ubuntu: no PPA available → try pyenv
                self._log(
                    f"Python {version} is not in apt on this distro.\n"
                    f"Trying pyenv fallback…", "warn")
                return self._install_python_other(version)
        else:
            # Already in apt → just update lists
            self._run_stream(["apt-get", "update", "-q"], use_sudo=True)

        pkgs = [f"python{version}"]
        if also_pip:
            pkgs += [f"python{version}-venv", f"python{version}-dev"]
            # pip via get-pip.py because python3.X-pip may not exist
        rc = self._run_stream(["apt-get", "install", "-y"] + pkgs, use_sudo=True)
        if rc != 0:
            self._log(f"apt-get install failed (rc={rc})", "err")
            return False

        if also_pip:
            self._install_pip(version)

        return True

    # ── Interpreter / pip helpers ─────────────────────────────────────────────
    def _python_exe(self, version):
        """Exact interpreter for the chosen version: the apt one first, never a
        random pyenv/conda shim that happens to be first on PATH."""
        for cand in (f"/usr/bin/python{version}", f"/usr/local/bin/python{version}"):
            if os.path.exists(cand):
                return cand
        pyenv_root = os.environ.get("PYENV_ROOT",
                                    os.path.join(target_user()[1], ".pyenv"))
        vers = os.path.join(pyenv_root, "versions")
        if os.path.isdir(vers):
            for d in sorted(os.listdir(vers), reverse=True):
                exe = os.path.join(vers, d, "bin", f"python{version}")
                if d.startswith(version + ".") and os.path.exists(exe):
                    return exe
        return shutil.which(f"python{version}") or f"python{version}"

    def _pip_flags(self, py_exe):
        """--user for system interpreters (prefix not writable by the user);
        --break-system-packages only where PEP 668 is in force."""
        r = subprocess.run(
            [py_exe, "-c",
             "import sys,sysconfig,os;"
             "print(sys.prefix);"
             "print(os.path.exists(os.path.join(sysconfig.get_path('stdlib'),"
             "'EXTERNALLY-MANAGED')))"],
            capture_output=True, text=True, env=clean_env())
        if r.returncode != 0:
            return ["--user"]
        prefix, managed = r.stdout.split()[:2]
        flags = []
        if not os.access(prefix, os.W_OK) or os.geteuid() == 0:
            flags.append("--user")
        if managed == "True":
            flags.append("--break-system-packages")
        return flags

    def _fix_home_ownership(self):
        """Older versions ran pip with sudo and left root-owned files in the
        user's home (~/.cache/pip, ~/.local).  Give them back to the user."""
        if getattr(self, "_home_fixed", False):
            return
        self._home_fixed = True
        import pwd
        user, home = target_user()
        uid = pwd.getpwnam(user).pw_uid

        def has_foreign(top):
            for root, dirs, files in os.walk(top):
                for n in [root] + [os.path.join(root, f) for f in dirs + files]:
                    try:
                        if os.lstat(n).st_uid != uid:
                            return True
                    except OSError:
                        pass
            return False

        bad = [os.path.join(home, sub) for sub in (".cache/pip", ".local")
               if os.path.exists(os.path.join(home, sub))
               and has_foreign(os.path.join(home, sub))]
        if bad:
            self._log("Fixing root-owned files left in your home folder…", "warn")
            self._run_stream(["chown", "-R", f"{user}:", *bad], use_sudo=True)

    def _install_pip(self, version):
        """Bootstrap pip for the chosen interpreter as the normal user
        (into ~/.local) – never as root, so no root-owned files appear."""
        self._log(f"\nBootstrapping pip for Python {version}…", "hd")
        self._fix_home_ownership()
        py_exe = self._python_exe(version)
        if subprocess.run([py_exe, "-m", "pip", "--version"],
                          capture_output=True, env=clean_env()).returncode == 0:
            self._log("pip already available.", "dim")
            return
        import urllib.request, tempfile
        fd, tmp = tempfile.mkstemp(suffix="-get-pip.py")
        os.close(fd)
        try:
            url = "https://bootstrap.pypa.io/get-pip.py"
            self._log(f"Downloading {url}…", "dim")
            urllib.request.urlretrieve(url, tmp)
            os.chmod(tmp, 0o644)          # readable when we drop to SUDO_USER
            rc = self._run_stream([py_exe, tmp, "--quiet",
                                   *self._pip_flags(py_exe)], use_sudo=False)
            if rc != 0:
                self._log("pip bootstrap failed.", "warn")
        except Exception as e:
            self._log(f"Could not download get-pip.py: {e}", "warn")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # ── Non-debian install (pyenv fallback) ───────────────────────────────────
    def _install_python_other(self, version):
        self._log("Non-Debian system detected. Trying pyenv…", "warn")
        if not shutil.which("pyenv"):
            self._log("pyenv not found. Install pyenv first:\n"
                      "  curl https://pyenv.run | bash\n"
                      "then re-run this installer.", "err")
            return False
        rc = self._run_stream(["pyenv", "install", "--skip-existing", version],
                              use_sudo=False)
        return rc == 0

    # ── update-alternatives ───────────────────────────────────────────────────
    def _set_default(self, version, links=("python", "python3")):
        self._log(f"\n── Setting Python {version} as default ──", "hd")
        py_bin = f"/usr/bin/python{version}"
        if not os.path.exists(py_bin):
            # Try to find it
            found = shutil.which(f"python{version}")
            if not found:
                self._log(f"python{version} binary not found; skipping update-alternatives.", "warn")
                return
            py_bin = found

        priority = int(version.replace(".", ""))  # e.g. 311 for 3.11

        for sym in links:
            self._run_stream(
                ["update-alternatives", "--install",
                 f"/usr/bin/{sym}", sym, py_bin, str(priority)],
                use_sudo=True)
            self._run_stream(
                ["update-alternatives", "--set", sym, py_bin],
                use_sudo=True)

        # Also link pip / pip3 if present
        pip_bin = f"/usr/bin/pip{version}"
        if os.path.exists(pip_bin):
            pips = ("pip", "pip3") if "python3" in links else ("pip",)
            for sym in pips:
                self._run_stream(
                    ["update-alternatives", "--install",
                     f"/usr/bin/{sym}", sym, pip_bin, str(priority)],
                    use_sudo=True)
                self._run_stream(
                    ["update-alternatives", "--set", sym, pip_bin],
                    use_sudo=True)

        self._log("Default Python updated.", "ok")

    # ── pip module install ────────────────────────────────────────────────────
    def _install_modules(self, version, modules):
        self._log(f"\n── Installing {len(modules)} module(s) with pip ──", "hd")
        py_exe = self._python_exe(version)
        self._log(f"Using interpreter: {py_exe}", "dim")
        flags = self._pip_flags(py_exe)
        rc = self._run_stream(
            [py_exe, "-m", "pip", "install", "--upgrade", *flags] + modules,
            use_sudo=False)
        if rc != 0:
            self._log("Some modules failed to install (see above).", "warn")
        elif "--user" in flags:
            self._log(f"Modules installed to {target_user()[1]}/.local "
                      f"(make sure ~/.local/bin is on your PATH).", "ok")

    # ── Refresh installed badges after install ────────────────────────────────
    def _refresh_badges(self):
        # Easiest: re-detect and update installed label
        installed = [v for v in PYTHON_VERSIONS if shutil.which(f"python{v}")]
        self._inst_label.config(
            text="\n".join(installed) if installed else "none detected")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("-v", "--version"):
        print(f"python_manager {APP_VERSION}")
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        app = PythonManagerApp()
        app.update()
        app.destroy()
        print("self-test OK")
        sys.exit(0)
    app = PythonManagerApp()
    app.mainloop()
