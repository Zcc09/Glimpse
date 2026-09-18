"""Glimpse setup wizard (Windows).

Self-contained Inno-Setup-style wizard: bundles the whole Glimpse app (PyInstaller
onedir payload) and walks through Welcome → Destination → Start Menu → Tasks →
Ready → Installing → Finish. Registers an Add/Remove Programs entry so it can be
uninstalled later (`Glimpse.exe --uninstall`).

Build (from the repo root):
  pyinstaller --noconfirm --clean glimpse.spec          # → dist/Glimpse/
  mkdir -p bundle && cp -r dist/Glimpse bundle/
  pyinstaller --noconfirm --clean glimpse-setup.spec    # → dist/Glimpse-Setup.exe

Automation:
  Glimpse-Setup.exe --silent --install-dir <path> --no-desktop-shortcut \
      --no-startmenu-shortcut --json
  Glimpse-Setup.exe --silent --uninstall
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes

APP_NAME = "Glimpse"
APP_VERSION_FALLBACK = "0.3.0"
PUBLISHER = "Glimpse"
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"
ICON_NAME = "glimpse.ico"
REQUIRED_MB = 500  # app + PySide6 runtime, unpacked

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --------------------------------------------------------------------------- helpers
def get_exe_version(path: str) -> str | None:
    try:
        size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(path, 0, size, buf):
            return None
        val = ctypes.c_void_p()
        vlen = wintypes.UINT()
        if not ctypes.windll.version.VerQueryValueW(buf, "\\", ctypes.byref(val), ctypes.byref(vlen)):
            return None
        fi = ctypes.cast(val, ctypes.POINTER(ctypes.c_ulong))
        ms, ls = fi[2], fi[3]
        return "%d.%d.%d" % ((ms >> 16) & 0xFFFF, ms & 0xFFFF, (ls >> 16) & 0xFFFF)
    except Exception:
        return None


def _powershell(script: str, timeout: int = 30) -> bool:
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
        )
        return True
    except Exception:
        return False


def create_shortcut(lnk_path: str, target: str, workdir: str, icon: str | None = None, args: str | None = None) -> bool:
    lnk_path = os.path.abspath(lnk_path)
    os.makedirs(os.path.dirname(lnk_path), exist_ok=True)
    icon_arg = ",0" if icon else ""
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$sc = $ws.CreateShortcut('%s'); "
        "$sc.TargetPath = '%s'; "
        "$sc.WorkingDirectory = '%s'; "
        "$sc.Arguments = '%s'; "
        "$sc.IconLocation = '%s%s'; "
        "$sc.Save();"
    ) % (lnk_path, target, workdir, args or "", icon or target, icon_arg)
    return _powershell(script)


def default_install_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Programs", APP_NAME)


def startmenu_dir(folder: str) -> str:
    return os.path.join(
        os.environ.get("APPDATA") or os.path.expanduser("~"),
        "Microsoft", "Windows", "Start Menu", "Programs", folder,
    )


def _bytes_text(mb: float) -> str:
    if mb >= 1024 * 1024:
        return "%.1f TB" % (mb / (1024.0 * 1024.0))
    if mb >= 1024:
        return "%.1f GB" % (mb / 1024.0)
    return "%.0f MB" % mb


def payload_mb(src: str) -> float:
    total = 0
    for root, _dirs, files in os.walk(src):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / (1024.0 * 1024.0)


def free_mb(path: str) -> float:
    try:
        while path and not os.path.isdir(path):
            path = os.path.dirname(path)
        import shutil as _sh

        return _sh.disk_usage(path).free / (1024.0 * 1024.0)
    except Exception:
        return 0.0


def _protected_reason(path: str) -> str | None:
    p = os.path.abspath(path).lower().rstrip("\\/")
    drive, tail = os.path.splitdrive(p)
    home = os.path.expanduser("~").lower().rstrip("\\/")
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("ProgramData"), os.environ.get("SystemRoot"),
                 os.environ.get("ProgramW6432")):
        if base:
            b = base.lower().rstrip("\\/")
            if p == b or p.startswith(b + "\\"):
                return (
                    f"Setup cannot install {APP_NAME} into a protected system folder:\n\n{path}\n\n"
                    f"Choose a folder inside your user profile instead — the default\n"
                    f"(%LOCALAPPDATA%\\Programs\\{APP_NAME}) needs no administrator rights."
                )
    if p == home:
        return f"Please choose a folder for {APP_NAME} rather than your profile root:\n\n{path}"
    if tail in ("", "\\", "/"):
        return f"Please choose a folder for {APP_NAME} rather than a drive root:\n\n{path}"
    return None


def detect_existing_install() -> tuple[str | None, str | None]:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            d = winreg.QueryValueEx(k, "InstallLocation")[0]
            v = winreg.QueryValueEx(k, "DisplayVersion")[0]
        if d and os.path.isfile(os.path.join(d, APP_NAME + ".exe")):
            return v, os.path.abspath(d)
    except Exception:
        pass
    cand = default_install_dir()
    if os.path.isfile(os.path.join(cand, APP_NAME + ".exe")):
        ver = None
        try:
            with open(os.path.join(cand, "install.json"), encoding="utf-8") as f:
                ver = (json.load(f) or {}).get("app_version")
        except Exception:
            ver = get_exe_version(os.path.join(cand, APP_NAME + ".exe"))
        return ver, os.path.abspath(cand)
    return None, None


def resolve_payload() -> tuple[str, str, str]:
    """(payload dir containing Glimpse.exe, .ico path, .png path for the wizard header).

    In a source run both bundle/ and dist/ can hold a payload; the *newest* Glimpse.exe
    wins, so a stale bundle/ can never silently ship an old build (it did once).
    """
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        options = [os.path.join(root, name) for name in ("bundle", "dist")]
        have = [b for b in options if os.path.isfile(os.path.join(b, APP_NAME, f"{APP_NAME}.exe"))]
        if have:
            base = max(have, key=lambda b: os.path.getmtime(os.path.join(b, APP_NAME, f"{APP_NAME}.exe")))
            if len(have) > 1:
                print(f"setup: payload candidates {have} → using {base} (newest {APP_NAME}.exe)")
        else:
            base = options[0]
    src = os.path.join(base, APP_NAME)
    icon = os.path.join(base, ICON_NAME)
    if not os.path.isfile(icon):
        icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", ICON_NAME)
    png = os.path.join(base, "glimpse_512.png")
    if not os.path.isfile(png):
        png = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "glimpse_512.png")
    return os.path.normpath(src), os.path.normpath(icon), os.path.normpath(png)


def _close_running() -> None:
    try:
        subprocess.run(["taskkill", "/F", "/IM", APP_NAME + ".exe"], capture_output=True, creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def _copy_tree(src: str, dst: str, progress=None, skip=()) -> bool:
    if not os.path.isdir(src):
        return False
    os.makedirs(dst, exist_ok=True)
    names = [n for n in os.listdir(src) if n not in skip]
    total = max(len(names), 1)
    for i, name in enumerate(names):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
        if progress:
            progress(i + 1, total)
    return True


# --------------------------------------------------------------------------- install
class Options:
    def __init__(self):
        self.install_dir = default_install_dir()
        self.install_dir_explicit = False
        self.desktop_shortcut = True
        self.startmenu_folder = APP_NAME  # None = don't create one
        self.uninstall_shortcut = True
        self.launch = False
        self.silent = False
        self.as_json = False
        self.uninstall = False
        self.selftest = False
        self.selftest_out = None

    def describe(self) -> str:
        return (
            f"Destination: {self.install_dir}\n"
            f"Desktop icon: {'yes' if self.desktop_shortcut else 'no'}\n"
            f"Start Menu folder: {self.startmenu_folder or '(none)'}\n"
            f"Uninstall shortcut: {'yes' if self.uninstall_shortcut else 'no'}"
        )


def parse_options(argv: list[str]) -> Options:
    o = Options()
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--silent":
            o.silent = True
        elif a == "--json":
            o.as_json = True
        elif a == "--launch":
            o.launch = True
        elif a == "--uninstall":
            o.uninstall = True
        elif a == "--install-dir" and i + 1 < len(argv):
            i += 1
            o.install_dir = argv[i]
            o.install_dir_explicit = True
        elif a == "--no-desktop-shortcut":
            o.desktop_shortcut = False
        elif a == "--no-startmenu-shortcut":
            o.startmenu_folder = None
        elif a == "--no-uninstall-shortcut":
            o.uninstall_shortcut = False
        elif a == "--startmenu-folder" and i + 1 < len(argv):
            i += 1
            o.startmenu_folder = argv[i]
        elif a == "--selftest":
            o.selftest = True
        elif a == "--selftest-out" and i + 1 < len(argv):
            i += 1
            o.selftest_out = argv[i]
        i += 1
    return o


def make_shortcuts(app_exe: str, install_dir: str, icon: str, opts: Options) -> list[str]:
    made: list[str] = []
    if opts.desktop_shortcut:
        lnk = os.path.join(os.path.expanduser("~"), "Desktop", APP_NAME + ".lnk")
        if create_shortcut(lnk, app_exe, install_dir, icon=icon):
            made.append("desktop")
    if opts.startmenu_folder:
        sm = startmenu_dir(opts.startmenu_folder)
        if create_shortcut(os.path.join(sm, APP_NAME + ".lnk"), app_exe, install_dir, icon=icon):
            made.append("startmenu")
        if opts.uninstall_shortcut:
            if create_shortcut(os.path.join(sm, f"Uninstall {APP_NAME}.lnk"), app_exe, install_dir,
                               icon=icon, args="--uninstall"):
                made.append("startmenu-uninstall")
    return made


def register_uninstall(install_dir: str, app_exe: str, version: str) -> bool:
    try:
        import winreg

        q = f'"{app_exe}"'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            for name, value in (
                ("DisplayName", APP_NAME),
                ("DisplayVersion", version),
                ("Publisher", PUBLISHER),
                ("InstallLocation", install_dir),
                ("DisplayIcon", q),
                ("UninstallString", q + " --uninstall"),
                ("QuietUninstallString", q + " --uninstall --silent"),
            ):
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        return True
    except Exception:
        return False


def do_install(opts: Options, src: str, icon: str, progress=None) -> dict:
    """Copy the payload, make shortcuts, register the uninstaller. Returns state."""
    version = get_exe_version(os.path.join(src, APP_NAME + ".exe")) or APP_VERSION_FALLBACK
    done = {"ok": False, "install_dir": opts.install_dir, "version": version, "shortcuts": []}

    if not os.path.isfile(os.path.join(src, APP_NAME + ".exe")):
        done["error"] = f"payload missing: {src}"
        return done

    _close_running()
    _copy_tree(src, opts.install_dir, progress=progress)
    app_exe = os.path.join(opts.install_dir, APP_NAME + ".exe")

    with open(os.path.join(opts.install_dir, "install.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "app": APP_NAME,
                "app_version": version,
                "startmenu_folder": opts.startmenu_folder or "",
                "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "desktop_shortcut": bool(opts.desktop_shortcut),
            },
            f, indent=2,
        )

    done["shortcuts"] = make_shortcuts(app_exe, opts.install_dir, icon, opts)
    done["uninstall_registered"] = register_uninstall(opts.install_dir, app_exe, version)
    done["ok"] = True
    return done


def _cli_main(opts: Options) -> int:
    src, icon, _png = resolve_payload()
    if opts.uninstall:
        exe = os.path.join(default_install_dir(), APP_NAME + ".exe")
        if not os.path.isfile(exe):
            v, d = detect_existing_install()
            exe = os.path.join(d, APP_NAME + ".exe") if d else exe
        if os.path.isfile(exe):
            subprocess.run([exe, "--uninstall", "--silent"] if opts.silent else [exe, "--uninstall"])
            return 0
        print(f"{APP_NAME} is not installed.")
        return 1
    if not opts.install_dir_explicit:
        # an update (the in-app updater runs this silently) must land in the same
        # folder the user originally chose, never a second copy in the default one
        _ver, prev_dir = detect_existing_install()
        if prev_dir:
            opts.install_dir = prev_dir
    problem = _protected_reason(opts.install_dir)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    need = payload_mb(src)
    if free_mb(opts.install_dir) < need + 100:
        print(f"not enough disk space in {opts.install_dir}", file=sys.stderr)
        return 3
    state = do_install(opts, src, icon)
    if opts.as_json:
        print(json.dumps(state))
    else:
        print(f"{APP_NAME} {state.get('version')} installed to {state.get('install_dir')}")
        print("shortcuts:", ", ".join(state.get("shortcuts") or []) or "(none)")
    if state.get("ok") and opts.launch:
        subprocess.Popen([os.path.join(opts.install_dir, APP_NAME + ".exe")], cwd=opts.install_dir)
    return 0 if state.get("ok") else 4


# --------------------------------------------------------------------------- wizard
def _gui_main(opts: Options) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f"Setup - {APP_NAME} {APP_VERSION_FALLBACK}")
    root.resizable(False, False)

    src, icon_path, png_path = resolve_payload()
    if not os.path.isfile(os.path.join(src, APP_NAME + ".exe")):
        messagebox.showerror("Setup", f"The installer payload is missing ({src}).")
        return 2
    version = get_exe_version(os.path.join(src, APP_NAME + ".exe")) or APP_VERSION_FALLBACK
    root.title(f"Setup - {APP_NAME} {version}")
    if os.path.isfile(icon_path):
        try:
            root.iconbitmap(icon_path)
        except Exception:
            pass

    need_mb = payload_mb(src)
    prev_ver, prev_dir = detect_existing_install()
    if prev_dir:
        opts.install_dir = prev_dir

    BG, BODY, FOOT = "#f0f0f0", "#ffffff", "#f0f0f0"
    style = ttk.Style()
    for name, bg in (("Body.TLabel", BODY), ("Body.TCheckbutton", BODY)):
        style.configure(name, background=bg)
        try:
            style.map(name, background=[("active", bg), ("disabled", bg)])
        except Exception:
            pass
    style.configure("Body.TLabelframe", background=BODY)
    style.configure("Body.TLabelframe.Label", background=BODY)

    W = 560
    container = tk.Frame(root, bg=BODY)

    # footer FIRST so a tall page can never push the buttons off-window
    footer = tk.Frame(root, bg=FOOT)
    footer.pack(side="bottom", fill="x")
    tk.Frame(root, bg="#d0d0d0", height=1).pack(side="bottom", fill="x")
    btn_cancel = ttk.Button(footer, text="Cancel", command=lambda: on_cancel())
    btn_cancel.pack(side="right", padx=(6, 12), pady=10)
    btn_next = ttk.Button(footer, text="Next >", command=lambda: on_next())
    btn_next.pack(side="right", padx=6, pady=10)
    btn_back = ttk.Button(footer, text="< Back", command=lambda: on_back(), state="disabled")
    btn_back.pack(side="right", padx=6, pady=10)

    head = tk.Frame(root, bg=BG)
    head.pack(side="top", fill="x")
    head_inner = tk.Frame(head, bg=BG)
    head_inner.pack(fill="x", padx=14, pady=12)
    head_icon = tk.Label(head_inner, bg=BG)
    head_icon.pack(side="left", padx=(0, 12))
    head_text = tk.Frame(head_inner, bg=BG)
    head_text.pack(side="left", fill="x", expand=True)
    head_title = tk.Label(head_text, text="", bg=BG, font=("Segoe UI", 11, "bold"), anchor="w")
    head_title.pack(fill="x")
    head_desc = tk.Label(head_text, text="", bg=BG, fg="#444444", anchor="w", justify="left")
    head_desc.pack(fill="x")
    tk.Frame(root, bg="#d0d0d0", height=1).pack(side="top", fill="x")

    container.pack(side="top", fill="both", expand=True)

    if os.path.isfile(png_path):
        try:
            img = tk.PhotoImage(file=png_path)
            img = img.subsample(max(1, img.width() // 32))
            head_icon.configure(image=img)
            head_icon.image = img
        except Exception:
            pass

    pages: dict[str, tk.Frame] = {}

    def page(name: str, title: str, desc: str) -> tk.Frame:
        f = tk.Frame(container, bg=BODY)
        pages[name] = f
        f.title, f.desc = title, desc  # type: ignore[attr-defined]
        return f

    # ------------------------------------------------------------ welcome
    p_welcome = page("welcome", f"Welcome to the {APP_NAME} Setup Wizard",
                     f"This will install {APP_NAME} {version} on your computer.")
    tk.Label(p_welcome, bg=BODY, justify="left", anchor="w",
             text=(f"It is recommended that you close all other applications before continuing.\n\n"
                   "Click Next to continue, or Cancel to exit Setup.")).pack(fill="x", padx=18, pady=18)
    if prev_dir:
        tk.Label(p_welcome, bg=BODY, fg="#0a5", justify="left", anchor="w",
                 text=f"An existing installation was found ({prev_ver or 'unknown version'} in {prev_dir}) and will be updated in place.").pack(fill="x", padx=18)

    # ------------------------------------------------------------ destination
    p_dest = page("dest", "Select Destination Location",
                  f"Where should {APP_NAME} be installed?")
    row = tk.Frame(p_dest, bg=BODY)
    row.pack(fill="x", padx=18, pady=(18, 4))
    dest_var = tk.StringVar(value=opts.install_dir)
    dest_entry = ttk.Entry(row, textvariable=dest_var, width=48)
    dest_entry.pack(side="left", fill="x", expand=True)

    def browse():
        d = filedialog.askdirectory(initialdir=dest_var.get() or os.path.expanduser("~"))
        if d:
            dest_var.set(os.path.normpath(d))
            update_space()

    ttk.Button(row, text="Browse...", command=browse).pack(side="left", padx=(8, 0))
    space_label = tk.Label(p_dest, bg=BODY, anchor="w", justify="left")
    space_label.pack(fill="x", padx=18, pady=(2, 12))

    def update_space():
        d = dest_var.get()
        space_label.configure(
            text=f"Space required: {_bytes_text(need_mb)}\nSpace available: {_bytes_text(free_mb(d))}"
        )

    update_space()

    # ------------------------------------------------------------ start menu
    p_sm = page("startmenu", "Select Start Menu Folder",
                f"Where should Setup place {APP_NAME}'s shortcuts?")
    sm_row = tk.Frame(p_sm, bg=BODY)
    sm_row.pack(fill="x", padx=18, pady=(18, 6))
    sm_var = tk.StringVar(value=opts.startmenu_folder or APP_NAME)
    sm_entry = ttk.Entry(sm_row, textvariable=sm_var, width=46)
    sm_entry.pack(side="left", fill="x", expand=True)
    no_sm = tk.BooleanVar(value=opts.startmenu_folder is None)
    ttk.Checkbutton(p_sm, text="Don't create a Start Menu folder", variable=no_sm,
                    style="Body.TCheckbutton",
                    command=lambda: sm_entry.configure(state="disabled" if no_sm.get() else "normal")).pack(anchor="w", padx=18, pady=(4, 12))
    if no_sm.get():
        sm_entry.configure(state="disabled")

    # ------------------------------------------------------------ tasks
    p_tasks = page("tasks", "Select Additional Tasks",
                   "Which additional tasks should be performed?")
    desktop_var = tk.BooleanVar(value=opts.desktop_shortcut)
    ttk.Checkbutton(p_tasks, text="Create a desktop icon", variable=desktop_var,
                    style="Body.TCheckbutton").pack(anchor="w", padx=18, pady=(16, 4))
    uninst_var = tk.BooleanVar(value=opts.uninstall_shortcut)
    ttk.Checkbutton(p_tasks, text="Add an uninstall shortcut to the Start Menu folder",
                    variable=uninst_var, style="Body.TCheckbutton").pack(anchor="w", padx=18, pady=4)
    tk.Label(p_tasks, bg=BODY, fg="#666666", anchor="w", justify="left",
             text=f"{APP_NAME} adds a tray icon and global hotkeys (Ctrl+Alt+L to capture).").pack(fill="x", padx=18, pady=(14, 12))

    # ------------------------------------------------------------ ready
    p_ready = page("ready", "Ready to Install",
                   f"Setup is now ready to begin installing {APP_NAME} on your computer.")
    ready_text = tk.Label(p_ready, bg=BODY, justify="left", anchor="w")
    ready_text.pack(fill="x", padx=18, pady=18)

    def fill_ready():
        folder = sm_var.get() if not no_sm.get() else None
        ready_text.configure(text=(
            f"Destination location:\n    {dest_var.get()}\n\n"
            f"Start Menu folder:\n    {folder or '(none)'}\n\n"
            f"Additional tasks:\n"
            f"    Desktop icon: {'yes' if desktop_var.get() else 'no'}\n"
            f"    Uninstall shortcut: {'yes' if uninst_var.get() else 'no'}\n\n"
            "Click Install to begin."
        ))

    # ------------------------------------------------------------ installing
    p_inst = page("installing", "Installing", f"Please wait while {APP_NAME} is being installed.")
    prog = ttk.Progressbar(p_inst, mode="determinate", maximum=100)
    prog.pack(fill="x", padx=18, pady=(24, 6))
    inst_status = tk.Label(p_inst, bg=BODY, anchor="w")
    inst_status.pack(fill="x", padx=18, pady=(0, 8))
    log_box = tk.Text(p_inst, height=7, wrap="word", relief="solid", borderwidth=1, background="#fafafa")
    log_box.pack(fill="both", expand=True, padx=18, pady=(0, 16))
    log_box.configure(state="disabled")

    # ------------------------------------------------------------ finish
    p_fin = page("finish", f"Completing the {APP_NAME} Setup Wizard",
                 f"{APP_NAME} has been installed on your computer.")
    fin_text = tk.Label(p_fin, bg=BODY, justify="left", anchor="w")
    fin_text.pack(fill="x", padx=18, pady=(16, 6))
    launch_var = tk.BooleanVar(value=True)
    launch_check = ttk.Checkbutton(p_fin, text=f"Launch {APP_NAME}", variable=launch_var, style="Body.TCheckbutton")
    launch_check.pack(anchor="w", padx=18, pady=(4, 12))
    tk.Label(p_fin, bg=BODY, fg="#666666", anchor="w", justify="left",
             text="Click Finish to close Setup.").pack(fill="x", padx=18)

    order = ["welcome", "dest", "startmenu", "tasks", "ready", "installing", "finish"]
    state = {"idx": 0, "installing": False, "result": None, "after_id": None}

    def log(line: str):
        log_box.configure(state="normal")
        log_box.insert("end", line + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")

    def show(idx: int):
        state["idx"] = idx
        for f in pages.values():
            f.pack_forget()
        name = order[idx]
        f = pages[name]
        f.pack(fill="both", expand=True)
        head_title.configure(text=getattr(f, "title"))
        head_desc.configure(text=getattr(f, "desc"))
        if name == "ready":
            fill_ready()
        btn_back.configure(state="disabled" if idx == 0 or state["installing"] else "normal")
        btn_next.configure(text="Install" if name == "ready" else "Next >")
        if name == "finish":
            btn_next.configure(text="Finish")
            btn_back.configure(state="disabled")
            btn_cancel.configure(state="disabled")
        else:
            btn_cancel.configure(state="normal")

    def on_next():
        name = order[state["idx"]]
        if name == "dest":
            problem = _protected_reason(dest_var.get())
            if problem:
                messagebox.showwarning("Setup", problem)
                return
            if free_mb(dest_var.get()) < need_mb + 100:
                messagebox.showwarning("Setup", f"Not enough disk space in {dest_var.get()}.\n\nNeeded: {_bytes_text(need_mb)}")
                return
            opts.install_dir = dest_var.get()
        if name == "startmenu":
            opts.startmenu_folder = None if no_sm.get() else (sm_var.get().strip() or APP_NAME)
        if name == "tasks":
            opts.desktop_shortcut = desktop_var.get()
            opts.uninstall_shortcut = uninst_var.get()
        if name == "ready":
            start_install()
            return
        if name == "finish":
            if launch_var.get():
                try:
                    subprocess.Popen([os.path.join(opts.install_dir, APP_NAME + ".exe")], cwd=opts.install_dir)
                except Exception:
                    pass
            root.destroy()
            return
        if name == "installing":
            return
        show(state["idx"] + 1)

    def on_back():
        if not state["installing"] and state["idx"] > 0:
            show(state["idx"] - 1)

    def on_cancel():
        if state["installing"]:
            return
        root.destroy()

    root.bind("<Return>", lambda _e: on_next() if str(btn_next["state"]) != "disabled" else None)
    root.bind("<Escape>", lambda _e: on_cancel())

    progress_q: list = []

    def start_install():
        state["installing"] = True
        btn_next.configure(state="disabled")
        btn_back.configure(state="disabled")
        show(order.index("installing"))
        log(f"Installing {APP_NAME} {version} to {opts.install_dir}")
        opts.launch = False

        def worker():
            def progress(i, total):
                progress_q.append(("progress", int(i * 100 / max(total, 1))))
            try:
                result = do_install(opts, src, icon_path, progress=progress)
            except Exception as e:  # noqa: BLE001
                result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            progress_q.append(("done", result))

        threading.Thread(target=worker, daemon=True, name="glimpse-setup").start()
        state["after_id"] = root.after(100, poll)

    def poll():
        """Single-timer progress pump (cancel/re-arm, never two timers)."""
        state["after_id"] = None
        while progress_q:
            kind, payload = progress_q.pop(0)
            if kind == "progress":
                prog.configure(value=payload)
            else:
                finish_install(payload)
                return
        if state["installing"]:
            state["after_id"] = root.after(100, poll)

    def finish_install(result: dict):
        state["installing"] = False
        state["result"] = result
        if state["after_id"] is not None:
            try:
                root.after_cancel(state["after_id"])
            except Exception:
                pass
            state["after_id"] = None
        if not result.get("ok"):
            log("Installation failed: " + str(result.get("error") or "unknown error"))
            messagebox.showerror("Setup", f"Installation failed.\n\n{result.get('error') or 'unknown error'}")
            show(order.index("ready"))
            return
        prog.configure(value=100)
        for name in ("application files", "Start Menu entries", "uninstaller registration"):
            log("Created: " + name)
        log(f"Shortcuts: {', '.join(result.get('shortcuts') or []) or '(none)'}")
        log("Installation complete.")
        fin_text.configure(text=(
            f"{APP_NAME} {result.get('version')} has been installed in:\n    {result.get('install_dir')}\n\n"
            f"Global hotkeys: Ctrl+Alt+L capture, Ctrl+Alt+T translate, "
            f"Ctrl+Alt+S visual search, Ctrl+Alt+M song ID.\n\n"
            f"You can uninstall {APP_NAME} from Settings → Apps, or from the Start Menu folder."
        ))
        show(order.index("finish"))

    # measure every page and size the window to the tallest one
    MIN_H = 320
    need_h = MIN_H
    root.update_idletasks()
    chrome = head.winfo_reqheight() + footer.winfo_reqheight() + 6
    for f in pages.values():
        f.pack(fill="both", expand=True)
        root.update_idletasks()
        need_h = max(need_h, f.winfo_reqheight() + chrome)
        f.pack_forget()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry("%dx%d+%d+%d" % (W, need_h, (sw - W) // 2, max(40, (sh - need_h) // 3)))

    show(0)

    if opts.selftest:
        _run_wizard_selftest(
            root=root, opts=opts, order=order, state=state, report_out=opts.selftest_out,
            show=show, btn_next=btn_next, btn_back=btn_back, btn_cancel=btn_cancel,
            dest_var=dest_var, no_sm=no_sm, desktop_var=desktop_var, uninst_var=uninst_var,
            messagebox=messagebox, version=version, page_lookup=lambda name: getattr(pages[name], "title"),
        )

    root.mainloop()
    return 0


def _run_wizard_selftest(*, root, opts, order, state, report_out, show, btn_next, btn_back,
                         btn_cancel, dest_var, no_sm, desktop_var, uninst_var, messagebox,
                         version, page_lookup) -> None:
    """Walk the real wizard through every page (the same calls the buttons make).

    Writes a JSON report: page order, whether the footer stayed on-screen on every
    page, whether the install actually landed, and any modal that tried to appear.
    """
    import tempfile as _tempfile
    import time as _time

    report: dict = {"pages": [], "footer_ok": True, "modals": [], "install": None,
                    "install_dir": None, "payload_version": version}

    def _recorder(kind):
        def fn(*a, **k):
            report["modals"].append([kind, str(a)[:200]])
            return kind in ("askyesno", "askokcancel", "askretrycancel")
        return fn

    for _name in ("showerror", "showwarning", "showinfo", "askyesno", "askokcancel", "askretrycancel"):
        if hasattr(messagebox, _name):
            setattr(messagebox, _name, _recorder(_name))

    target_dir = os.path.join(_tempfile.mkdtemp(prefix="glimpse-wizard-"), APP_NAME)
    report["install_dir"] = target_dir
    dest_var.set(target_dir)
    no_sm.set(True)          # never touch the user's Start Menu / Desktop during a self test
    desktop_var.set(False)
    uninst_var.set(False)

    def footer_visible() -> bool:
        root.update_idletasks()
        bottom = root.winfo_rooty() + root.winfo_height()
        for b in (btn_back, btn_next, btn_cancel):
            try:
                if b.winfo_ismapped() and (b.winfo_rooty() + b.winfo_height()) > bottom:
                    return False
            except Exception:
                return False
        return True

    def walk(wait: float = 0.4) -> None:
        root.update()
        _time.sleep(wait)
        root.update()
        name = order[state["idx"]]
        ok = footer_visible()
        report["pages"].append({"page": name, "title": page_lookup(name), "footer_ok": ok})
        if not ok:
            report["footer_ok"] = False
        if name in ("welcome", "dest", "startmenu", "tasks", "ready"):
            btn_next.invoke()
            walk(wait)
        elif name == "installing":
            deadline = _time.time() + 180
            while _time.time() < deadline and state["idx"] != order.index("finish"):
                root.update()
                _time.sleep(0.1)
            report["install"] = dict(state.get("result") or {}) or None
            walk(0.2)
        # 'finish' ends the walk

    def run():
        try:
            walk()
        except Exception as e:  # noqa: BLE001
            report["error"] = f"{type(e).__name__}: {e}"
        finally:
            if report_out:
                try:
                    with open(report_out, "w", encoding="utf-8") as f:
                        json.dump(report, f, indent=2)
                except Exception:
                    pass
            try:
                root.destroy()
            except Exception:
                pass

    root.after(600, run)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    opts = parse_options(argv)
    if opts.silent or opts.as_json or opts.uninstall:
        return _cli_main(opts)
    if not os.environ.get("DISPLAY") and os.name != "nt":
        return _cli_main(opts)
    try:
        return _gui_main(opts)
    except Exception as e:  # noqa: BLE001
        if opts.as_json:
            print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
            return 4
        raise


if __name__ == "__main__":
    raise SystemExit(main())
