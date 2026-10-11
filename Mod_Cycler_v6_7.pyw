import sys
import os
import re
import random
import threading
import ctypes
import shutil
from ctypes import wintypes
from datetime import datetime
import json
import hashlib
import queue
import tempfile
import webbrowser
import tkinter as tk
from tkinter import messagebox, ttk, filedialog, simpledialog
import pystray
from PIL import Image, ImageDraw, ImageTk

# PATH RESOLUTION
if getattr(sys, 'frozen', False):
    BASE = os.path.dirname(sys.executable)
else:
    BASE = os.path.dirname(os.path.abspath(__file__))

# APPDATA FOR INVISIBLE CONFIG STORAGE
APP_NAME = "Mod Cycler"
APP_ID = "ModCycler"
APP_VERSION = "6.7"
UI_COLOR = "#007acc"
UI_BG = "#202022"
UI_PANEL = "#242426"
UI_FIELD = "#303136"
UI_BORDER = "#53545a"
UI_TEXT = "#f2f2f3"
UI_MUTED = "#a7a8af"
SUPPORT_URL = "https://www.patreon.com/cw/Hitakumori"
APPDATA_DIR = os.path.join(os.getenv('APPDATA') or os.path.expanduser("~"), "NRMM_Mod_Cycler")
CONFIG_FILE = os.path.join(APPDATA_DIR, "config.json")
INSTANCE_HASH = hashlib.sha1(os.path.normcase(os.path.abspath(CONFIG_FILE)).encode("utf-8")).hexdigest()[:16]
INSTANCE_NAME = f"Local\\{APP_ID}_{INSTANCE_HASH}"
HOTKEY_MODIFIERS = 0x4001  # MOD_ALT | MOD_NOREPEAT
HOTKEY_VK = 0x53  # S
DEFAULT_KEYS = {"next": "PGUP", "prev": "PGDN", "shuffle": "INSERT", "auto": "CAPSLOCK", "auto_shuf": "END"}
CYCLER_DIR_NAME = "Mod Cycler"
ACTIVE_INI_NAME = "mod_cycler.ini"
PROFILES_DIR_NAME = "Profiles"
BACKUPS_DIR_NAME = "Backups"
STATE_FILE_NAME = "mod_cycler_state.json"
MODS_DIR_NAME = "Mods"
MANAGED_DIR_NAME = "_MANAGED_"
LEGACY_MANAGED_DIR_NAMES = (
    "V1_3_x_MANAGED-DO_NOT_EDIT_COPY_MOVE_CUT",
    "MANAGED-DO_NOT_EDIT_COPY_MOVE_CUT",
)

NAME_STOP_WORDS = {
    "animated", "animation", "author", "basic", "bikini", "black", "body",
    "bodysuit", "bottom", "by", "clothes", "costume", "default", "dress",
    "enhanced", "final", "fix", "fixed", "hair", "heavy", "high", "hot",
    "insiders", "lewd", "maid", "mega", "megattoggle", "mod", "mods", "new",
    "nude", "nsfw", "old", "outfit", "pack", "queen", "school", "sfw",
    "skin", "skins", "succubus", "swimsuit", "thicc", "toggle", "uniform",
    "version", "white", "with",
}

KNOWN_NAME_FIXES = {
    "kukishinobu": "Kuki Shinobu",
}

MANAGED_SLOT_ID_PATTERN = re.compile(
    r"^\s*global\s+\$managed_slot_id\s*=\s*(\d+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def read_json_object(path):
    with open(path, "r", encoding="utf-8-sig") as source:
        data = json.load(source)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object.")
    return data


def write_json_atomic(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary_path = ""
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=os.path.basename(path) + ".", suffix=".tmp", delete=False) as output:
            temporary_path = output.name
            json.dump(data, output, indent=2, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError as error:
                print(f"[Mod Cycler] Could not remove temporary JSON file: {error}")


def parse_group_id(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value >= 0 else None
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        try:
            return int(value.strip())
        except ValueError:
            pass
    return None


def clean_keybind(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value if value and not any(ord(char) < 32 or ord(char) == 127 for char in value) else ""


def clean_nicknames(values):
    if not isinstance(values, dict):
        return {}
    return {str(parse_group_id(gid)): name.strip() for gid, name in values.items()
            if parse_group_id(gid) is not None and isinstance(name, str) and name.strip()}


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_child_dir(parent, names):
    if not parent or not os.path.isdir(parent):
        return ""
    wanted = {name.casefold() for name in names}
    try:
        with os.scandir(parent) as entries:
            for entry in entries:
                if entry.is_dir() and entry.name.casefold() in wanted:
                    return os.path.normpath(entry.path)
    except OSError:
        return ""
    return ""


def resolve_mods_folder(path):
    if not path:
        return "", "", ""

    start = os.path.abspath(os.path.normpath(path))
    if not os.path.isdir(start):
        start = os.path.dirname(start)

    managed_name = MANAGED_DIR_NAME.casefold()
    legacy_names = {name.casefold() for name in LEGACY_MANAGED_DIR_NAMES}
    mods_fallback = ""
    legacy_fallback = ("", "")
    current = start
    visited = set()

    while current and current not in visited:
        visited.add(current)
        base_name = os.path.basename(current).casefold()
        parent = os.path.dirname(current)

        if base_name == MODS_DIR_NAME.casefold() and not mods_fallback:
            mods_fallback = current

        if base_name == managed_name and parent:
            return os.path.normpath(parent), os.path.normpath(current), ""

        if base_name in legacy_names and parent and not legacy_fallback[0]:
            legacy_fallback = (parent, current)

        managed_child = find_child_dir(current, (MANAGED_DIR_NAME,))
        if managed_child:
            return os.path.normpath(current), managed_child, ""

        legacy_child = find_child_dir(current, LEGACY_MANAGED_DIR_NAMES)
        if legacy_child and not legacy_fallback[0]:
            legacy_fallback = (current, legacy_child)

        mods_child = find_child_dir(current, (MODS_DIR_NAME,))
        if mods_child:
            if not mods_fallback:
                mods_fallback = mods_child
            managed_under_mods = find_child_dir(mods_child, (MANAGED_DIR_NAME,))
            if managed_under_mods:
                return os.path.normpath(mods_child), managed_under_mods, ""
            legacy_under_mods = find_child_dir(mods_child, LEGACY_MANAGED_DIR_NAMES)
            if legacy_under_mods and not legacy_fallback[0]:
                legacy_fallback = (mods_child, legacy_under_mods)

        if parent == current:
            break
        current = parent

    if legacy_fallback[0]:
        return os.path.normpath(legacy_fallback[0]), "", os.path.normpath(legacy_fallback[1])
    if mods_fallback:
        return os.path.normpath(mods_fallback), "", ""
    return os.path.normpath(start), "", ""


def find_managed_slot_id(mod_path):
    """Read NRMM's authoritative slot ID from a managed mod's generated ini."""
    try:
        for root_dir, dirs, files in os.walk(mod_path):
            dirs.sort(key=str.lower)
            for file_name in sorted(files, key=str.lower):
                if not file_name.lower().endswith(".ini"):
                    continue
                ini_path = os.path.join(root_dir, file_name)
                try:
                    with open(ini_path, "r", encoding="utf-8", errors="ignore") as ini_file:
                        match = MANAGED_SLOT_ID_PATTERN.search(ini_file.read())
                except OSError:
                    continue
                if match:
                    return int(match.group(1))
    except OSError:
        pass
    return None


# --- SINGLE INSTANCE CHECK ---
def focus_existing_window():
    """Best-effort restore/focus for the already-running app window."""
    user32 = ctypes.windll.user32
    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    matches = []

    def foreach_window(hwnd, lParam):
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, len(title))
        if title.value == APP_NAME:
            matches.append(hwnd)
            return False
        return True

    callback = enum_proc_type(foreach_window)
    user32.EnumWindows(callback, 0)

    if not matches:
        return False

    hwnd = matches[0]
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.ShowWindow(hwnd, 5)  # SW_SHOW
    user32.SetForegroundWindow(hwnd)
    return True


def check_single_instance():
    """Prevents more than one instance from running at the same time."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateSemaphoreW.argtypes = [wintypes.LPVOID, wintypes.LONG, wintypes.LONG, wintypes.LPCWSTR]
    kernel32.CreateSemaphoreW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    h_semaphore = kernel32.CreateSemaphoreW(None, 1, 1, INSTANCE_NAME)
    last_error = kernel32.GetLastError()
    if not h_semaphore:
        raise ctypes.WinError(last_error)

    if last_error == 183:  # ERROR_ALREADY_EXISTS
        focus_existing_window()
        if h_semaphore:
            kernel32.CloseHandle(h_semaphore)
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Error", "Another instance of Mod Cycler is already running.")
        root.destroy()
        sys.exit(0)

    return h_semaphore


def create_tray_icon(theme_color):
    image = Image.new('RGB', (64, 64), color=(30, 30, 30))
    dc = ImageDraw.Draw(image)
    dc.rectangle((16, 16, 48, 48), fill=theme_color)
    return image


class GeneratorApp:
    def __init__(self, root, semaphore_handle=None):
        self.root = root

        self.semaphore_handle = semaphore_handle or check_single_instance()

        self.root.title(APP_NAME)
        self.ui_scale = min(max(1.0, self.root.winfo_fpixels("1i") / 96.0),
                            max(0.7, (self.root.winfo_screenheight() - 80) / 1000))
        self.minimum_size = (self.ui_pixels(620), self.ui_pixels(850))
        self.root.minsize(*self.minimum_size)
        width = self.ui_pixels(680)
        height = min(self.ui_pixels(1000), self.root.winfo_screenheight() - 80)
        x = min(100, max(0, (self.root.winfo_screenwidth() - width) // 2))
        self.root.geometry(f"{width}x{height}+{x}+40")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=UI_BG)

        self.is_visible = True
        self._closing = False
        self._ui_thread_id = threading.get_ident()
        self._ui_actions = queue.Queue()
        self._hotkey_stop = threading.Event()
        self._hotkey_thread_id = None
        self._groups_path_key = None
        self.group_vars = {}
        self.group_widgets = []
        self.group_paths = {}  # gid -> absolute path, populated by refresh_groups
        self.group_slot_counts = {}
        self.group_favorite_slot_counts = {}
        self.group_favorite_slots = {}
        self.group_mod_names = {}
        self.group_unresolved_favorites = {}
        self.duplicate_group_paths = []
        self.master_var = tk.BooleanVar(value=True)

        # Load Config
        config_data = self.load_config()
        self.target_dir, self.managed_path, self.legacy_managed_path = resolve_mods_folder(config_data["mods_path"])
        self.ui_color = UI_COLOR
        self.nicknames_by_path = config_data.get("nicknames_by_path", {})
        self.legacy_nicknames = config_data.get("legacy_nicknames", {})
        self.nicknames = {}
        self.legacy_nickname_key = self.get_path_key()
        self._nicknames_migrated = False
        self.use_target_nicknames()


        self.key_options = [
            "PGUP", "PGDN", "INSERT", "DELETE", "HOME", "END",
            "UP", "DOWN", "LEFT", "RIGHT", "SPACE", "TAB", "ENTER",
            "ESCAPE", "BACKSPACE", "CAPSLOCK", "SCROLLLOCK", "PAUSE",
            "LBUTTON", "RBUTTON", "MBUTTON", "XBUTTON1", "XBUTTON2",
            "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
            "NUMPAD0", "NUMPAD1", "NUMPAD2", "NUMPAD3", "NUMPAD4",
            "NUMPAD5", "NUMPAD6", "NUMPAD7", "NUMPAD8", "NUMPAD9",
            "MULTIPLY", "ADD", "SUBTRACT", "DECIMAL", "DIVIDE",
            "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
            "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
            "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
            "`", "-", "=", "[", "]", "\\", ";", "'", ",", ".", "/"
        ]

        self.keys = {
            "next":      tk.StringVar(value=config_data["keys"]["next"]),
            "prev":      tk.StringVar(value=config_data["keys"]["prev"]),
            "shuffle":   tk.StringVar(value=config_data["keys"]["shuffle"]),
            "auto":      tk.StringVar(value=config_data["keys"]["auto"]),
            "auto_shuf": tk.StringVar(value=config_data["keys"]["auto_shuf"])
        }
        self.favorite_only_var = tk.BooleanVar(value=config_data.get("favorite_only", False))

        self.build_ui()
        self.start_x = self.start_y = self.start_w = self.start_h = 0
        self.x = self.y = 0
        self.refresh_groups()
        self.refresh_profile_list()

        self._ui_poll_id = self.root.after(100, self.process_ui_actions)
        self.setup_tray()
        self.hotkey_thread = threading.Thread(target=self.listen_for_hotkey, daemon=True)
        self.hotkey_thread.start()
        if self._nicknames_migrated:
            self.save_config()

    # -----------------------------------------------------------------------

    def ui_pixels(self, value):
        return max(1, round(value * self.ui_scale))

    def build_ui(self):
        root = self.root
        u = self.ui_pixels
        self.body_font = ("Segoe UI", -u(16))
        self.small_font = ("Segoe UI", -u(14))
        self.heading_font = ("Segoe UI", -u(19), "bold")
        self.checkbox_images = {bg: self.create_checkbox_images(bg) for bg in (UI_BG, UI_PANEL)}
        self.configure_ui_styles()
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(1, weight=1)

        # The title and its label both drag; window buttons still hide to tray.
        self.title_bar = tk.Frame(root, bg=self.ui_color, height=u(42))
        self.title_bar.grid(row=0, column=0, sticky="ew")
        self.title_bar.grid_propagate(False)
        self.title_bar.grid_columnconfigure(0, weight=1)
        self.title_bar.grid_rowconfigure(0, weight=1)
        self.title_lbl = tk.Label(self.title_bar, text=f"Mod Cycler v{APP_VERSION}",
                                  bg=self.ui_color, fg="white", font=("Segoe UI", -u(21)), anchor="w")
        self.title_lbl.grid(row=0, column=0, sticky="nsew", padx=u(20))
        for widget in (self.title_bar, self.title_lbl):
            widget.bind("<ButtonPress-1>", self.start_move)
            widget.bind("<B1-Motion>", self.do_move)
        self.min_btn = self.create_ui_button(self.title_bar, "—", self.hide_window)
        self.min_btn.grid(row=0, column=1, sticky="ns", ipadx=u(9))
        self.close_btn = self.create_ui_button(self.title_bar, "✕", self.hide_window)
        self.close_btn.grid(row=0, column=2, sticky="ns", ipadx=u(9))
        self.close_btn.configure(activebackground="#c42b36")

        self.content_frame = tk.Frame(root, bg=UI_BG)
        self.content_frame.grid(row=1, column=0, sticky="nsew", padx=u(22), pady=(u(16), u(18)))
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(5, weight=1, minsize=u(130))

        folder_frame = tk.Frame(self.content_frame, bg=UI_BG)
        folder_frame.grid(row=0, column=0, sticky="ew")
        folder_frame.grid_columnconfigure(0, weight=1)
        tk.Label(folder_frame, text="Mods Folder", bg=UI_BG, fg=UI_TEXT, font=self.body_font).grid(
            row=0, column=0, sticky="w", pady=(0, u(8)))
        path_field = tk.Frame(folder_frame, bg=UI_FIELD, highlightthickness=1, highlightbackground=UI_BORDER)
        path_field.grid(row=1, column=0, sticky="nsew", padx=(0, u(12)))
        self.path_lbl = tk.Label(path_field, text=self.truncate_path(self.target_dir),
                                  bg=UI_FIELD, fg=UI_TEXT, font=self.body_font, anchor="w")
        self.path_lbl.pack(fill="both", expand=True, padx=u(12), pady=u(8))
        self.browse_btn = self.create_ui_button(folder_frame, "BROWSE", self.browse_folder)
        self.browse_btn.grid(row=1, column=1, sticky="nsew", ipadx=u(12))

        cycle_frame = tk.Frame(self.content_frame, bg=UI_BG)
        cycle_frame.grid(row=1, column=0, sticky="ew", pady=(u(16), u(16)))
        tk.Label(cycle_frame, text="Interval (seconds)", bg=UI_BG, fg=UI_TEXT, font=self.body_font).grid(
            row=0, column=0, sticky="w")
        self.timer_var = tk.StringVar(value="120")
        self.interval_entry = tk.Entry(cycle_frame, textvariable=self.timer_var, width=6,
                                       bg=UI_FIELD, fg=UI_TEXT, insertbackground=UI_TEXT,
                                       font=self.body_font, relief="flat", highlightthickness=1,
                                       highlightbackground=UI_BORDER, highlightcolor=self.ui_color)
        self.interval_entry.grid(row=0, column=1, padx=(u(12), u(22)), ipady=u(8))
        self.favorites_only_cb = self.create_checkbox(
            cycle_frame, "Favorites only (NRMM fav files)", self.favorite_only_var, self.save_config, UI_BG,
            font=self.small_font)
        self.favorites_only_cb.grid(row=0, column=2, sticky="w")
        self.create_separator(self.content_frame, 2)

        groups_header = tk.Frame(self.content_frame, bg=UI_BG)
        groups_header.grid(row=3, column=0, sticky="ew", pady=(u(14), u(8)))
        self.groups_lbl = tk.Label(groups_header, text="Detected Groups", bg=UI_BG, fg=UI_TEXT,
                                    font=self.heading_font)
        self.groups_lbl.pack(side="left")
        tk.Label(groups_header, text="Right-click to rename", bg=UI_BG, fg=UI_MUTED,
                 font=self.small_font).pack(side="left", padx=u(14))
        self.master_cb = self.create_checkbox(self.content_frame, "Select All", self.master_var,
                                              self.toggle_all, UI_BG)
        self.master_cb.grid(row=4, column=0, sticky="w", pady=(0, u(8)))

        list_container = tk.Frame(self.content_frame, bg=UI_PANEL, highlightthickness=1,
                                   highlightbackground=UI_BORDER)
        list_container.grid(row=5, column=0, sticky="nsew")
        self.canvas = tk.Canvas(list_container, bg=UI_PANEL, highlightthickness=0, yscrollincrement=u(34))
        self.scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self.canvas.yview,
                                        style="Cycler.Vertical.TScrollbar")
        self.scroll_frame = tk.Frame(self.canvas, bg=UI_PANEL)
        self.scroll_frame.grid_columnconfigure(0, weight=1)
        self.groups_window = self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        self.scroll_frame.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.create_separator(self.content_frame, 6, pady=(u(16), u(12)))
        self.info_frame = tk.Frame(self.content_frame, bg=UI_BG)
        self.info_frame.grid(row=7, column=0, sticky="ew")
        for column in (1, 3):
            self.info_frame.grid_columnconfigure(column, weight=1, uniform="key_fields")
        tk.Label(self.info_frame, text="Keybinds", bg=UI_BG, fg=UI_TEXT, font=self.heading_font).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, u(6)))
        self.key_combos = {}
        self.create_keybind_row(self.info_frame, 1, "Next Mod", self.keys["next"], "Prev Mod", self.keys["prev"])
        self.create_keybind_row(self.info_frame, 2, "Shuffle", self.keys["shuffle"], "", None)
        self.create_keybind_row(self.info_frame, 3, "Auto-Cycle", self.keys["auto"], "Auto-Shuffle", self.keys["auto_shuf"])

        self.create_separator(self.content_frame, 8, pady=(u(12), u(12)))
        self.profile_frame = tk.Frame(self.content_frame, bg=UI_BG)
        self.profile_frame.grid(row=9, column=0, sticky="ew")
        self.profile_frame.grid_columnconfigure(1, weight=1)
        tk.Label(self.profile_frame, text="Profile", bg=UI_BG, fg=UI_TEXT, font=self.body_font).grid(
            row=0, column=0, padx=(0, u(16)))
        self.profile_var = tk.StringVar()
        self.profile_combo = ttk.Combobox(self.profile_frame, textvariable=self.profile_var, state="readonly",
                                           style="Cycler.TCombobox", font=self.body_font, width=18)
        self.profile_combo.bind("<<ComboboxSelected>>", self.load_selected_profile)
        self.profile_combo.grid(row=0, column=1, sticky="ew", padx=(0, u(12)))
        self.save_profile_btn = self.create_ui_button(self.profile_frame, "SAVE", self.save_current_profile)
        self.save_profile_btn.grid(row=0, column=2, sticky="ns", ipadx=u(12))

        self.footer_frame = tk.Frame(self.content_frame, bg=UI_BG)
        self.footer_frame.grid(row=10, column=0, sticky="ew", pady=(u(12), u(10)))
        self.support_btn = self.create_ui_button(self.footer_frame, "SUPPORT ME", self.open_support_page)
        self.support_btn.pack(side="right", ipadx=u(12))
        self.gen_btn = self.create_ui_button(self.content_frame, "GENERATE .INI", self.generate_ini)
        self.gen_btn.grid(row=11, column=0, sticky="ew", ipady=u(6))

        self.grip = tk.Canvas(root, width=u(14), height=u(14), bg=UI_BG,
                               highlightthickness=0, cursor="bottom_right_corner")
        self.grip.place(relx=1.0, rely=1.0, anchor="se")
        self.grip.bind("<ButtonPress-1>", self.start_resize)
        self.grip.bind("<B1-Motion>", self.do_resize)
        self.apply_ui_style()

    def configure_ui_styles(self):
        u = self.ui_pixels
        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")
        self.style.configure("Cycler.TCombobox", fieldbackground=UI_FIELD, background=UI_FIELD,
                             foreground=UI_TEXT, bordercolor=UI_BORDER, lightcolor=UI_BORDER,
                             darkcolor=UI_BORDER, arrowcolor=UI_TEXT, arrowsize=u(13),
                             padding=(u(8), u(7)))
        self.style.map("Cycler.TCombobox", fieldbackground=[("readonly", UI_FIELD), ("focus", UI_FIELD)],
                       foreground=[("readonly", UI_TEXT)], selectbackground=[("!disabled", UI_FIELD)],
                       selectforeground=[("!disabled", UI_TEXT)], bordercolor=[("focus", self.ui_color)])
        self.style.configure("Cycler.Vertical.TScrollbar", gripcount=0, background="#45464b",
                             troughcolor=UI_PANEL, bordercolor=UI_BORDER, arrowcolor=UI_MUTED,
                             lightcolor="#45464b", darkcolor="#45464b", arrowsize=u(16))
        self.style.map("Cycler.Vertical.TScrollbar", background=[("active", "#606168")])
        self.root.option_add("*TCombobox*Listbox.background", UI_FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", UI_TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", self.ui_color)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "white")
        self.root.option_add("*TCombobox*Listbox.font", self.body_font)

    def create_ui_button(self, parent, text, command):
        u = self.ui_pixels
        return tk.Button(parent, text=text, command=command, bg=self.ui_color, fg="white",
                         activebackground="#008be0", activeforeground="white", relief="flat", bd=0,
                         highlightthickness=1, highlightbackground="#168edf", highlightcolor="white",
                         font=("Segoe UI", -u(15), "bold"), cursor="hand2", padx=u(12), pady=u(8))

    def create_checkbox_images(self, bg):
        # Supersampling makes crisp ticks without external image assets.
        size, gap, factor = self.ui_pixels(22), self.ui_pixels(10), 4
        images = []
        for selected in (False, True):
            image = Image.new("RGB", ((size + gap) * factor, size * factor), bg)
            draw = ImageDraw.Draw(image)
            draw.rectangle((factor, factor, (size - 1) * factor, (size - 1) * factor),
                           fill=self.ui_color if selected else bg,
                           outline="#168edf" if selected else "#96979c", width=factor)
            if selected:
                draw.line([(size * 0.23 * factor, size * 0.51 * factor),
                           (size * 0.43 * factor, size * 0.72 * factor),
                           (size * 0.79 * factor, size * 0.30 * factor)],
                          fill="white", width=3 * factor, joint="curve")
            images.append(ImageTk.PhotoImage(image.resize((size + gap, size), Image.Resampling.LANCZOS),
                                             master=self.root))
        return tuple(images)

    def create_checkbox(self, parent, text, variable, command, bg, font=None):
        unchecked, checked = self.checkbox_images[bg]
        return tk.Checkbutton(parent, text=text, variable=variable, command=command,
                              image=unchecked, selectimage=checked, compound="left", indicatoron=False,
                              bg=bg, fg=UI_TEXT, selectcolor=bg, activebackground=bg,
                              activeforeground=UI_TEXT, font=font or self.body_font, anchor="w", justify="left",
                              relief="flat", offrelief="flat", overrelief="flat", bd=0, highlightthickness=1,
                              highlightbackground=bg, highlightcolor=self.ui_color,
                              padx=0, pady=self.ui_pixels(2), cursor="hand2")

    def create_separator(self, parent, row, pady=0):
        tk.Frame(parent, bg=UI_BORDER, height=1).grid(row=row, column=0, sticky="ew", pady=pady)

    def open_support_page(self):
        webbrowser.open(SUPPORT_URL)

    def apply_ui_style(self):
        self.gen_btn.configure(bg=self.ui_color, activebackground="#008be0", text="GENERATE .INI")
        self.grip.delete("all")
        for offset in (4, 9):
            self.grip.create_line(self.ui_pixels(offset), self.ui_pixels(14),
                                  self.ui_pixels(14), self.ui_pixels(offset), fill="#94959b", width=2)

    def rename_group_ui(self, event, gid, current_name):
        new_name = simpledialog.askstring("Rename Group", f"Enter nickname for Group {gid}:", initialvalue=current_name)
        if new_name is not None:
            new_name = new_name.strip()
            if new_name:
                self.nicknames[str(gid)] = new_name
            else:
                self.nicknames.pop(str(gid), None)
            self.save_config()
            self.refresh_groups()

    def get_path_key(self, path=None):
        normalized = os.path.normcase(os.path.normpath(path or self.target_dir))
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]

    def use_target_nicknames(self):
        self.nickname_key = self.get_path_key()
        self.nicknames = self.nicknames_by_path.setdefault(self.nickname_key, {})
        if self.legacy_nicknames and self.nickname_key == self.legacy_nickname_key:
            for gid, name in self.legacy_nicknames.items():
                self.nicknames.setdefault(gid, name)
            self.legacy_nicknames.clear()
            self._nicknames_migrated = True

    def create_keybind_row(self, parent, row, label1, var1, label2, var2):
        for column, label, variable in ((0, label1, var1), (2, label2, var2)):
            if variable is None:
                continue
            tk.Label(parent, text=label, bg=UI_BG, fg=UI_TEXT, font=self.body_font).grid(
                row=row, column=column, sticky="w",
                padx=(self.ui_pixels(24) if column == 2 else 0, self.ui_pixels(10)))
            combo = ttk.Combobox(parent, textvariable=variable, values=self.key_options, width=9,
                                  style="Cycler.TCombobox", font=self.small_font)
            combo.grid(row=row, column=column + 1, sticky="ew", pady=self.ui_pixels(4))
            key = next(name for name, value in self.keys.items() if value is variable)
            self.key_combos[key] = combo

    def on_canvas_resize(self, event):
        self.canvas.itemconfigure(self.groups_window, width=event.width)
        self.regrid_checkboxes()

    def refresh_group_layout(self):
        if hasattr(self, "canvas"):
            self.canvas.itemconfigure(self.groups_window, width=max(1, self.canvas.winfo_width()))
            self.regrid_checkboxes()

    def regrid_checkboxes(self):
        # Keep the chosen single-column layout even when the window is widened.
        canvas_width = self.canvas.winfo_width()
        if canvas_width <= 1:
            canvas_width = self.minimum_size[0] - self.ui_pixels(44)
        width = max(1, canvas_width - self.ui_pixels(64))
        for index, widget in enumerate(self.group_widgets):
            widget.grid(row=index, column=0, sticky="ew", padx=self.ui_pixels(12), pady=self.ui_pixels(2))
            widget.configure(wraplength=width)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def clear_generation_warning_labels(self):
        kept_widgets = []
        for widget in self.group_widgets:
            if getattr(widget, "is_generation_warning", False):
                widget.destroy()
            else:
                kept_widgets.append(widget)
        if len(kept_widgets) != len(self.group_widgets):
            self.group_widgets = kept_widgets
            self.regrid_checkboxes()

    def load_config(self):
        config = {
            "mods_path": BASE,
            "keys": DEFAULT_KEYS.copy(),
            "nicknames_by_path": {},
            "legacy_nicknames": {},
            "favorite_only": False,
        }
        if not os.path.exists(CONFIG_FILE):
            return config
        try:
            data = read_json_object(CONFIG_FILE)
        except (OSError, ValueError, UnicodeError) as error:
            print(f"[Mod Cycler] Failed to load config: {error}")
            return config

        mods_path = data.get("mods_path")
        if isinstance(mods_path, str) and mods_path.strip() and "\0" not in mods_path:
            config["mods_path"] = mods_path
        if isinstance(data.get("favorite_only"), bool):
            config["favorite_only"] = data["favorite_only"]
        keys = data.get("keys", {})
        if isinstance(keys, dict):
            for name in config["keys"]:
                value = clean_keybind(keys.get(name))
                if value:
                    config["keys"][name] = value
        names_by_path = data.get("nicknames_by_path", {})
        if isinstance(names_by_path, dict):
            config["nicknames_by_path"] = {
                key: clean_nicknames(names) for key, names in names_by_path.items()
                if isinstance(key, str) and isinstance(names, dict)
            }
        config["legacy_nicknames"] = clean_nicknames(data.get("legacy_nicknames", data.get("nicknames", {})))
        return config

    def save_config(self):
        try:
            self.nicknames_by_path[self.nickname_key] = self.nicknames
            write_json_atomic(CONFIG_FILE, {
                "mods_path": self.target_dir,
                "favorite_only": self.favorite_only_var.get(),
                "keys": {key: value.get() for key, value in self.keys.items()},
                "nicknames_by_path": self.nicknames_by_path,
                "legacy_nicknames": self.legacy_nicknames,
                "nicknames": {},
            })
        except (OSError, ValueError) as error:
            print(f"[Mod Cycler] Failed to save config: {error}")

    def truncate_path(self, path, max_len=52):
        return "..." + path[-(max_len - 3):] if len(path) > max_len else path

    def browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.target_dir)
        if folder:
            self.target_dir, self.managed_path, self.legacy_managed_path = resolve_mods_folder(folder)
            self.use_target_nicknames()
            self.path_lbl.config(text=self.truncate_path(self.target_dir))
            self.save_config()
            self.refresh_groups()
            self.refresh_profile_list()

    def start_resize(self, event):
        self.start_x, self.start_y = event.x_root, event.y_root
        self.start_w, self.start_h = self.root.winfo_width(), self.root.winfo_height()

    def do_resize(self, event):
        new_w = max(self.minimum_size[0], self.start_w + (event.x_root - self.start_x))
        new_h = max(self.minimum_size[1], self.start_h + (event.y_root - self.start_y))
        self.root.geometry(f"{new_w}x{new_h}")

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def toggle_all(self):
        for var in self.group_vars.values():
            var.set(self.master_var.get())

    def sync_master_var(self):
        self.master_var.set(bool(self.group_vars) and all(var.get() for var in self.group_vars.values()))

    def get_cycler_dir(self):
        return os.path.join(self.target_dir, CYCLER_DIR_NAME)

    def get_profiles_dir(self):
        return os.path.join(self.get_cycler_dir(), PROFILES_DIR_NAME)

    def get_backups_dir(self):
        return os.path.join(self.get_cycler_dir(), BACKUPS_DIR_NAME)

    def get_active_ini_path(self):
        return os.path.join(self.get_cycler_dir(), ACTIVE_INI_NAME)

    def get_state_path(self):
        return os.path.join(self.get_cycler_dir(), STATE_FILE_NAME)

    def get_legacy_root_ini_path(self):
        return os.path.join(self.target_dir, ACTIVE_INI_NAME)

    def refresh_target_dir(self):
        resolved_dir, managed_path, legacy_managed_path = resolve_mods_folder(self.target_dir)
        if resolved_dir and resolved_dir != self.target_dir:
            self.target_dir = resolved_dir
            self.use_target_nicknames()
            if hasattr(self, "path_lbl"):
                self.path_lbl.config(text=self.truncate_path(self.target_dir))
        self.managed_path = managed_path
        self.legacy_managed_path = legacy_managed_path
        return managed_path

    def load_generation_state(self):
        state_path = self.get_state_path()
        if not os.path.exists(state_path):
            return {}
        try:
            return read_json_object(state_path)
        except (OSError, ValueError, UnicodeError) as error:
            print(f"[Mod Cycler] Failed to load generation state: {error}")
            return {}

    def save_generation_state(self, final_groups):
        groups = {
            str(group["id"]): {
                "slots": int(group["slots"]),
                "all_slots": int(group.get("all_slots", group["slots"])),
                "favorite_slots": list(group.get("favorite_slots", [])),
                "mod_names": list(self.group_mod_names.get(group["id"], [])),
                "name": self.nicknames.get(str(group["id"]), ""),
            }
            for group in final_groups
        }
        detected_groups = {
            str(gid): {
                "slots": int(slots),
                "favorite_slots": list(self.group_favorite_slots.get(gid, [])),
                "mod_names": list(self.group_mod_names.get(gid, [])),
            }
            for gid, slots in self.group_slot_counts.items()
            if slots >= 2
        }
        write_json_atomic(self.get_state_path(), {
            "version": 2,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "active_ini": ACTIVE_INI_NAME,
            "ini_sha256": file_sha256(self.get_active_ini_path()),
            "favorite_only": self.favorite_only_var.get(),
            "groups": groups,
            "detected_groups": detected_groups,
        })

    def get_generation_warnings(self):
        state = self.load_generation_state()
        ini_path = self.get_active_ini_path()
        generated_groups = state.get("groups", {})
        if not isinstance(generated_groups, dict) or not generated_groups:
            return ["Cycler snapshot is missing or invalid; generate again."] if os.path.exists(ini_path) else []
        warnings = []
        if not os.path.isfile(ini_path):
            warnings.append("The generated mod_cycler.ini is missing.")
        elif isinstance(state.get("ini_sha256"), str):
            try:
                if file_sha256(ini_path) != state["ini_sha256"]:
                    warnings.append("The active mod_cycler.ini was changed outside Mod Cycler.")
            except OSError:
                warnings.append("The active mod_cycler.ini could not be read.")
        detected_at_generate = state.get("detected_groups", {})
        if not isinstance(detected_at_generate, dict):
            detected_at_generate = {}
        favorite_only = state.get("favorite_only", False)
        if not isinstance(favorite_only, bool):
            warnings.append("Cycler snapshot contains an invalid Favorites setting; generate again.")
            favorite_only = False

        generated_ids = {str(gid) for gid in generated_groups}
        previously_detected_ids = {str(gid) for gid in detected_at_generate}
        for gid in sorted(self.group_slot_counts):
            current_slots = self.group_slot_counts[gid]
            if current_slots < 2:
                continue
            current_effective_slots = self.group_favorite_slot_counts.get(gid, 0) if favorite_only else current_slots
            if current_effective_slots < (1 if favorite_only else 2):
                continue
            group_key = str(gid)
            generated = generated_groups.get(group_key)
            if generated is None:
                if group_key not in previously_detected_ids:
                    warnings.append(f"New Group {gid} is not in the generated cycler.")
                continue
            if not isinstance(generated, dict):
                warnings.append(f"Group {gid} has invalid snapshot data; generate again.")
                continue
            generated_slots = parse_group_id(generated.get("slots"))
            if generated_slots != current_effective_slots:
                warnings.append(
                    f"Group {gid} has {current_effective_slots} {'favorite(s)' if favorite_only else 'mods'}; "
                    f"generated cycler has {generated_slots if generated_slots is not None else 'invalid data'}."
                )
            elif favorite_only:
                if generated.get("favorite_slots", []) != self.group_favorite_slots.get(gid, []):
                    warnings.append(f"Group {gid} has different favorited mods than the generated cycler.")
            elif "mod_names" in generated and generated["mod_names"] != self.group_mod_names.get(gid, []):
                warnings.append(f"Group {gid} contains different mod folders than the generated cycler.")

        current_ids = {
            str(gid) for gid, count in self.group_slot_counts.items()
            if count >= 2 and (not favorite_only or self.group_favorite_slot_counts.get(gid, 0) >= 1)
        }
        missing_generated = generated_ids - current_ids
        if missing_generated:
            warnings.append(f"{len(missing_generated)} generated group(s) are no longer valid in _MANAGED_.")
        return warnings

    def safe_profile_name(self, name):
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(name or "")).strip(" .")
        if re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", safe_name.split(".")[0], re.IGNORECASE):
            safe_name = "_" + safe_name
        return safe_name[:80] or "Profile"

    def get_profile_path(self, name):
        return os.path.join(self.get_profiles_dir(), f"{self.safe_profile_name(name)}.json")

    def list_profile_names(self):
        profiles_dir = self.get_profiles_dir()
        if not os.path.isdir(profiles_dir):
            return []
        try:
            names = [os.path.splitext(filename)[0] for filename in os.listdir(profiles_dir)
                     if filename.lower().endswith(".json") and os.path.isfile(os.path.join(profiles_dir, filename))]
        except OSError as error:
            print(f"[Mod Cycler] Could not list profiles: {error}")
            return []
        return sorted(names, key=str.lower)

    def refresh_profile_list(self, select_name=None):
        if not hasattr(self, "profile_combo"):
            return
        names = self.list_profile_names()
        self.profile_combo["values"] = names
        current = select_name or self.profile_var.get()
        if current in names:
            self.profile_var.set(current)
        elif names:
            self.profile_var.set(names[0])
        else:
            self.profile_var.set("")

    def collect_profile_data(self, name):
        selected_groups = sorted(gid for gid, var in self.group_vars.items() if var.get())
        return {
            "version": 1,
            "name": name,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "interval": self.timer_var.get().strip(),
            "keys": {key: value.get().strip() for key, value in self.keys.items()},
            "selected_groups": selected_groups,
            "favorite_only": self.favorite_only_var.get(),
        }

    def save_current_profile(self):
        initial_name = self.profile_var.get() or "Default"
        name = simpledialog.askstring("Save Profile", "Profile name:", initialvalue=initial_name, parent=self.root)
        if not name:
            return
        profile_name = self.safe_profile_name(name)
        try:
            write_json_atomic(self.get_profile_path(profile_name), self.collect_profile_data(profile_name))
        except (OSError, ValueError) as error:
            messagebox.showerror("Profile Save Failed", f"Could not save profile:\n{error}")
            return
        self.refresh_profile_list(profile_name)
        messagebox.showinfo("Profile Saved", f"Saved profile:\n{profile_name}")

    def load_selected_profile(self, event=None):
        profile_name = self.profile_var.get()
        if not profile_name:
            return
        try:
            profile = read_json_object(self.get_profile_path(profile_name))
            interval = profile.get("interval")
            if interval is not None:
                if isinstance(interval, bool) or not re.fullmatch(r"[0-9]+", str(interval).strip()):
                    raise ValueError("Profile interval must be a positive integer.")
                interval = int(str(interval).strip())
                if interval < 1:
                    raise ValueError("Profile interval must be at least 1 second.")
            raw_keys = profile.get("keys", {})
            if not isinstance(raw_keys, dict):
                raise ValueError("Profile keys must be an object.")
            keys = {}
            for name in self.keys:
                if name in raw_keys:
                    value = clean_keybind(raw_keys[name])
                    if not value:
                        raise ValueError(f"Profile keybind '{name}' is invalid.")
                    keys[name] = value
            favorite_only = profile.get("favorite_only", False)
            if not isinstance(favorite_only, bool):
                raise ValueError("Profile Favorites setting must be true or false.")
            raw_groups = profile.get("selected_groups", [])
            if not isinstance(raw_groups, list):
                raise ValueError("Profile selected groups must be a list.")
            selected_groups = set()
            for raw_gid in raw_groups:
                gid = parse_group_id(raw_gid)
                if gid is None:
                    raise ValueError("Profile contains an invalid group ID.")
                selected_groups.add(gid)
        except (OSError, ValueError, UnicodeError) as error:
            messagebox.showerror("Profile Load Failed", f"Could not load profile:\n{error}")
            return

        self.refresh_groups()
        if interval is not None:
            self.timer_var.set(str(interval))
        for name, value in keys.items():
            self.keys[name].set(value)
        self.favorite_only_var.set(favorite_only)
        detected_groups = set(self.group_vars)
        for gid, var in self.group_vars.items():
            var.set(gid in selected_groups)
        self.sync_master_var()
        self.save_config()
        missing_groups = selected_groups - detected_groups
        if missing_groups:
            messagebox.showwarning(
                "Profile Partially Loaded",
                f"Loaded profile, but {len(missing_groups)} group(s) are not detected in the current Mods folder."
            )

    def next_backup_path(self, label):
        os.makedirs(self.get_backups_dir(), exist_ok=True)
        safe_label = re.sub(r"[^0-9A-Za-z_-]+", "_", label).strip("_") or "backup"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{timestamp}_{safe_label}.bak"
        backup_path = os.path.join(self.get_backups_dir(), base_name)
        suffix = 1
        while os.path.exists(backup_path):
            backup_path = os.path.join(self.get_backups_dir(), f"{timestamp}_{safe_label}_{suffix}.bak")
            suffix += 1
        return backup_path

    def backup_file(self, path, label, move=False):
        if not os.path.exists(path):
            return ""
        backup_path = self.next_backup_path(label)
        if move:
            os.replace(path, backup_path)
        else:
            shutil.copy2(path, backup_path)
        return backup_path

    def migrate_legacy_root_ini(self):
        legacy_path = self.get_legacy_root_ini_path()
        active_path = self.get_active_ini_path()
        if os.path.normcase(os.path.abspath(legacy_path)) == os.path.normcase(os.path.abspath(active_path)):
            return ""
        return self.backup_file(legacy_path, "root_mod_cycler", move=True)

    def format_display_name(self, token):
        fixed = KNOWN_NAME_FIXES.get(token.lower())
        if fixed:
            return fixed
        parts = re.findall(r"[a-zA-Z]+|\d+", token)
        if parts:
            return " ".join(part.capitalize() if part.isalpha() else part for part in parts)
        return token.strip().title()

    def name_tokens(self, raw_name):
        text = re.sub(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}", " ", raw_name)
        text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
        text = re.sub(r"[^0-9A-Za-z]+", " ", text)
        tokens = []
        for token in text.split():
            token = token.lower()
            token = re.sub(r"^\d+|\d+$", "", token)
            for suffix in ("mods", "mod", "skins", "skin"):
                if token.endswith(suffix) and len(token) > len(suffix) + 2:
                    token = token[:-len(suffix)]
                    break
            if len(token) < 3 or token in NAME_STOP_WORDS:
                continue
            tokens.append(token)
        return tokens

    def clean_name(self, raw_name):
        tokens = self.name_tokens(raw_name)
        if tokens:
            return self.format_display_name(tokens[0])
        text = re.sub(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}", " ", raw_name)
        text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
        text = re.sub(r"[_+\-.]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text.title() if text else "Unknown"

    def infer_group_name(self, slot_names):
        token_sets = []
        ordered_token_lists = []
        first_seen = {}
        for index, raw_name in enumerate(slot_names):
            tokens = self.name_tokens(raw_name)
            if not tokens:
                continue
            ordered_token_lists.append((index, tokens))
            unique_tokens = set(tokens)
            token_sets.append(unique_tokens)
            for token in unique_tokens:
                first_seen.setdefault(token, index)

        if not token_sets:
            return self.clean_name(slot_names[0]) if slot_names else "Unknown"

        scores = {}
        for tokens in token_sets:
            for token in tokens:
                scores[token] = scores.get(token, 0) + 1

        prefix_scores = {}
        prefix_first_seen = {}
        for index, tokens in enumerate(token_sets):
            prefixes = set()
            for token in tokens:
                for length in range(4, min(len(token), 16) + 1):
                    prefixes.add(token[:length])
            for prefix in prefixes:
                prefix_scores[prefix] = prefix_scores.get(prefix, 0) + 1
                prefix_first_seen.setdefault(prefix, index)

        candidates = []
        for token, score in scores.items():
            if score >= 2:
                candidates.append((score, len(token), -first_seen[token], token))
        for prefix, score in prefix_scores.items():
            if score >= 2:
                candidates.append((score, len(prefix), -prefix_first_seen[prefix], prefix))

        if candidates:
            _, _, _, token = max(candidates)
            return self.format_display_name(token)

        if ordered_token_lists:
            _, tokens = max(ordered_token_lists, key=lambda item: (len(item[1]), -item[0]))
            return " ".join(self.format_display_name(token) for token in tokens[:2])
        return "Unknown"

    def refresh_groups(self):
        managed_path = self.refresh_target_dir()
        path_key = self.get_path_key()
        same_target = self._groups_path_key == path_key
        previous_selection = {gid: var.get() for gid, var in self.group_vars.items()} if same_target else {}
        self._groups_path_key = path_key
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self.group_widgets.clear()
        self.group_paths.clear()
        self.group_slot_counts.clear()
        self.group_favorite_slot_counts.clear()
        self.group_favorite_slots.clear()
        self.group_mod_names.clear()
        self.group_unresolved_favorites.clear()
        self.duplicate_group_paths.clear()
        self.group_vars.clear()
        if not managed_path:
            if self.legacy_managed_path:
                legacy_name = os.path.basename(self.legacy_managed_path)
                text = (
                    f"Old NRMM folder found: {legacy_name}\n"
                    "Open NRMM and run Update Mod Data to migrate it to _MANAGED_."
                )
            else:
                text = "No _MANAGED_ folder found. Select Mods, the XXMI root, or an NRMM managed folder."
            lbl = tk.Label(self.scroll_frame, text=text, bg=UI_PANEL, fg="#ff7777", font=self.body_font,
                           wraplength=300, justify="left")
            self.group_widgets.append(lbl)
            self.regrid_checkboxes()
            self.sync_master_var()
            return

        group_folders = []
        seen_group_ids = set()
        # Deep scan: find group folders anywhere inside _MANAGED_
        for root_dir, dirs, _ in os.walk(managed_path):
            dirs.sort(key=str.lower)
            found_group_dirs = []
            for d in list(dirs):
                m = re.fullmatch(r"group[_]?(\d+)", d, re.IGNORECASE)
                if m:
                    found_group_dirs.append(d)
                    gid = int(m.group(1))
                    gpath = os.path.join(root_dir, d)
                    if gid in seen_group_ids:
                        self.duplicate_group_paths.append(gpath)
                        continue
                    seen_group_ids.add(gid)
                    try:
                        subs = [f for f in os.listdir(gpath) if os.path.isdir(os.path.join(gpath, f)) and not f.startswith("_")]
                        subs.sort()
                        self.group_paths[gid] = gpath
                        self.group_mod_names[gid] = subs
                        self.group_slot_counts[gid] = len(subs)
                        favorite_slots = []
                        unresolved_favorites = []
                        for mod_name in subs:
                            mod_path = os.path.join(gpath, mod_name)
                            if not os.path.isfile(os.path.join(mod_path, "fav")):
                                continue
                            slot_id = find_managed_slot_id(mod_path)
                            if slot_id is not None and slot_id not in favorite_slots:
                                favorite_slots.append(slot_id)
                            else:
                                unresolved_favorites.append(mod_name)
                        self.group_unresolved_favorites[gid] = unresolved_favorites
                        self.group_favorite_slots[gid] = favorite_slots
                        self.group_favorite_slot_counts[gid] = len(favorite_slots)
                        if len(subs) >= 2:
                            raw_name = self.infer_group_name(subs)
                            display_name = self.nicknames.get(str(gid), raw_name)
                            group_folders.append((gid, display_name))
                    except Exception as e:
                        print(f"[Mod Cycler] Could not read group folder '{d}': {e}")
                        continue
            for d in found_group_dirs:
                if d in dirs:
                    dirs.remove(d)

        generation_warnings = self.get_generation_warnings()
        if generation_warnings:
            preview = "\n".join(generation_warnings[:4])
            if len(generation_warnings) > 4:
                preview += f"\n+{len(generation_warnings) - 4} more cycler mismatch(es)."
            lbl = tk.Label(self.scroll_frame, text=f"Cycler out of date:\n{preview}",
                           bg=UI_PANEL, fg="#ffcc66", font=self.body_font,
                           wraplength=320, justify="left")
            lbl.is_generation_warning = True
            self.group_widgets.append(lbl)

        group_folders.sort()
        for gid, name in group_folders:
            var = tk.BooleanVar(value=previous_selection.get(gid, not same_target))
            self.group_vars[gid] = var
            cb = self.create_checkbox(self.scroll_frame, f"Group {gid} ({name})", var,
                                      self.sync_master_var, UI_PANEL)
            cb.bind("<Button-3>", lambda e, g=gid, n=name: self.rename_group_ui(e, g, n))
            self.group_widgets.append(cb)

        if not group_folders:
            lbl = tk.Label(self.scroll_frame, text="No valid group folders found.", bg=UI_PANEL, fg="#ff7777", font=self.body_font)
            self.group_widgets.append(lbl)

        if self.duplicate_group_paths:
            skipped = len(self.duplicate_group_paths)
            lbl = tk.Label(self.scroll_frame, text=f"{skipped} duplicate group ID(s) skipped.", bg=UI_PANEL, fg="#ffcc66", font=self.body_font)
            self.group_widgets.append(lbl)

        self.sync_master_var()
        self.regrid_checkboxes()

    def start_move(self, event):
        self.x, self.y = event.x, event.y

    def do_move(self, event):
        self.root.geometry(f"+{self.root.winfo_x() + (event.x - self.x)}+{self.root.winfo_y() + (event.y - self.y)}")

    def setup_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem('Show (Alt+S)', self.show_from_tray),
            pystray.MenuItem('Quit', self.quit_app)
        )
        self.tray_icon = pystray.Icon(APP_NAME, create_tray_icon(self.ui_color), APP_NAME, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def hide_window(self):
        self.is_visible = False
        self.root.withdraw()

    def show_window(self):
        if self._closing:
            return
        self.refresh_groups()
        self.refresh_profile_list()
        self.is_visible = True
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()

    def show_from_tray(self, icon, item):
        self.post_ui_action(self.show_window)

    def toggle_from_hotkey(self):
        if not self._closing:
            (self.hide_window if self.is_visible else self.show_window)()

    def post_ui_action(self, action):
        if not self._closing:
            self._ui_actions.put(action)

    def process_ui_actions(self):
        self._ui_poll_id = None
        while not self._closing:
            try:
                action = self._ui_actions.get_nowait()
            except queue.Empty:
                break
            action()
        if not self._closing:
            self._ui_poll_id = self.root.after(100, self.process_ui_actions)

    def quit_app(self, icon=None, item=None):
        if threading.get_ident() != self._ui_thread_id:
            self.post_ui_action(self.quit_app)
            return
        if self._closing:
            return
        self._closing = True
        self.save_config()
        self._hotkey_stop.set()
        hotkey_thread_id = self._hotkey_thread_id
        if hotkey_thread_id is not None:
            user32 = ctypes.windll.user32
            user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.PostThreadMessageW.restype = wintypes.BOOL
            user32.PostThreadMessageW(hotkey_thread_id, 0x0012, 0, 0)  # WM_QUIT
        if self.hotkey_thread.is_alive():
            self.hotkey_thread.join(timeout=1)
        if getattr(self, "tray_icon", None):
            self.tray_icon.stop()
        if self.semaphore_handle:
            ctypes.windll.kernel32.CloseHandle(self.semaphore_handle)
            self.semaphore_handle = None
        for callback_id in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback_id)
        self.root.destroy()

    def listen_for_hotkey(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL
        user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        user32.PeekMessageW.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # Create this thread's message queue.
        self._hotkey_thread_id = kernel32.GetCurrentThreadId()
        registered = False
        try:
            if self._hotkey_stop.is_set():
                return
            registered = bool(user32.RegisterHotKey(None, 1, HOTKEY_MODIFIERS, HOTKEY_VK))
            if not registered:
                error_code = kernel32.GetLastError()
                self.post_ui_action(lambda: messagebox.showwarning(
                    "Hotkey Unavailable",
                    f"Could not register Alt+S (Windows error {error_code}). Use the tray menu to show Mod Cycler.",
                    parent=self.root,
                ))
                return
            while not self._hotkey_stop.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                if msg.message == 0x0312 and msg.wParam == 1:
                    self.post_ui_action(self.toggle_from_hotkey)
        finally:
            if registered:
                user32.UnregisterHotKey(None, 1)
            self._hotkey_thread_id = None

    def generate_ini(self):
        self.save_config()
        try:
            timer_seconds = int(self.timer_var.get().strip())
        except ValueError:
            messagebox.showerror("Error", "Enter a valid number.")
            return

        if timer_seconds < 1:
            messagebox.showerror("Error", "Interval must be at least 1 second.")
            return

        key_values = {}
        for label, key_name in (
            ("Next Mod", "next"),
            ("Prev Mod", "prev"),
            ("Shuffle", "shuffle"),
            ("Auto-Cycle", "auto"),
            ("Auto-Shuffle", "auto_shuf"),
        ):
            value = self.keys[key_name].get().strip()
            if not value or "\n" in value or "\r" in value:
                messagebox.showerror("Error", f"{label} keybind is invalid.")
                return
            key_values[key_name] = value

        # Refresh the complete inventory before generating; retain existing selections.
        self.refresh_groups()
        final_groups = []
        groups_without_favorites = []
        unresolved_favorites = []
        for gid, var in self.group_vars.items():
            if not var.get():
                continue
            mods = self.group_mod_names.get(gid, [])
            favorite_slots = self.group_favorite_slots.get(gid, [])
            unresolved_favorites.extend((gid, name) for name in self.group_unresolved_favorites.get(gid, []))
            active_slots = favorite_slots if self.favorite_only_var.get() else list(range(1, len(mods) + 1))
            if active_slots and (self.favorite_only_var.get() or len(mods) >= 2):
                deck = active_slots[:]
                random.shuffle(deck)
                final_groups.append({
                    'id': gid,
                    'slots': len(active_slots),
                    'all_slots': len(mods),
                    'favorite_slots': favorite_slots,
                    'active_slots': active_slots,
                    'deck': deck,
                })
            elif self.favorite_only_var.get() and len(mods) >= 2:
                groups_without_favorites.append(gid)

        if not final_groups:
            message = "No selected groups contain favorited mods." if self.favorite_only_var.get() else "No valid groups selected."
            messagebox.showwarning("Warning", message)
            return

        ini_path = self.get_active_ini_path()
        tmp_path = ini_path + ".tmp"
        legacy_backup = ""
        previous_backup = ""
        state_warning = ""
        try:
            os.makedirs(self.get_cycler_dir(), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(f"; v{APP_VERSION}\nnamespace = mod_cycler_indie\\cycler\n\n[Constants]\n")
                f.write("global persist $auto_enable = 0\nglobal persist $shuffle_auto_enable = 0\nglobal persist $last_cycle = 0\n\n")
                for g in final_groups:
                    if self.favorite_only_var.get():
                        f.write(
                            f"global persist $g{g['id']}_cycle_pos = 0\n"
                            f"global persist $g{g['id']}_shuffle_pos = 0\n"
                            f"global persist $g{g['id']}_slot = {g['active_slots'][0]}\n"
                        )
                    else:
                        f.write(f"global persist $g{g['id']}_pos = 0\nglobal persist $g{g['id']}_slot = {g['deck'][0]}\n")

                f.write(f"\n[KeyNext]\nkey = {key_values['next']}\nrun = CommandListNext\n")
                f.write(f"[KeyPrev]\nkey = {key_values['prev']}\nrun = CommandListPrev\n")
                f.write(f"[KeyRandom]\nkey = {key_values['shuffle']}\nrun = CommandListShuffle\n")
                f.write(f"[KeyToggleAuto]\nkey = {key_values['auto']}\nrun = CommandListToggleAuto\n")
                f.write(f"[KeyToggleShuffleAuto]\nkey = {key_values['auto_shuf']}\nrun = CommandListToggleShuffleAuto\n")

                f.write("\n[CommandListToggleAuto]\n$auto_enable = 1 - $auto_enable\n$shuffle_auto_enable = 0\n")
                f.write("if $auto_enable == 1\n    $last_cycle = time\n    run = CommandListNext\nendif\n")

                f.write("\n[CommandListToggleShuffleAuto]\n$shuffle_auto_enable = 1 - $shuffle_auto_enable\n$auto_enable = 0\n")
                f.write("if $shuffle_auto_enable == 1\n    $last_cycle = time\n    run = CommandListShuffle\nendif\n")

                f.write("\n[CommandListNext]\n")
                for g in final_groups:
                    if self.favorite_only_var.get():
                        f.write(f"$g{g['id']}_cycle_pos = -1\n")
                        for pos, mod_id in enumerate(g['active_slots']):
                            f.write(f"if $g{g['id']}_slot == {mod_id}\n    $g{g['id']}_cycle_pos = {pos}\nendif\n")
                        f.write(f"$g{g['id']}_cycle_pos = ($g{g['id']}_cycle_pos + 1) % {g['slots']}\n")
                        for pos, mod_id in enumerate(g['active_slots']):
                            f.write(f"if $g{g['id']}_cycle_pos == {pos}\n    $g{g['id']}_slot = {mod_id}\nendif\n")
                    else:
                        # Saved selections can outlive mods removed before regeneration.
                        f.write(f"$g{g['id']}_slot = $g{g['id']}_slot + 1\n")
                        f.write(f"if $g{g['id']}_slot > {g['slots']} || $g{g['id']}_slot < 1\n    $g{g['id']}_slot = 1\nendif\n")
                    f.write(f"$\\modmanageragl\\group_{g['id']}\\active_slot = $g{g['id']}_slot\n")

                f.write("\n[CommandListPrev]\n")
                for g in final_groups:
                    if self.favorite_only_var.get():
                        f.write(f"$g{g['id']}_cycle_pos = 0\n")
                        for pos, mod_id in enumerate(g['active_slots']):
                            f.write(f"if $g{g['id']}_slot == {mod_id}\n    $g{g['id']}_cycle_pos = {pos}\nendif\n")
                        f.write(f"$g{g['id']}_cycle_pos = ($g{g['id']}_cycle_pos + {g['slots']} - 1) % {g['slots']}\n")
                        for pos, mod_id in enumerate(g['active_slots']):
                            f.write(f"if $g{g['id']}_cycle_pos == {pos}\n    $g{g['id']}_slot = {mod_id}\nendif\n")
                    else:
                        f.write(f"$g{g['id']}_slot = $g{g['id']}_slot - 1\n")
                        f.write(f"if $g{g['id']}_slot < 1 || $g{g['id']}_slot > {g['slots']}\n    $g{g['id']}_slot = {g['slots']}\nendif\n")
                    f.write(f"$\\modmanageragl\\group_{g['id']}\\active_slot = $g{g['id']}_slot\n")

                f.write("\n[CommandListShuffle]\n")
                for g in final_groups:
                    position_name = "shuffle_pos" if self.favorite_only_var.get() else "pos"
                    f.write(f"$g{g['id']}_{position_name} = ($g{g['id']}_{position_name} + 1) % {g['slots']}\n")
                    for pos, mod_id in enumerate(g['deck']):
                        f.write(f"if $g{g['id']}_{position_name} == {pos}\n    $g{g['id']}_slot = {mod_id}\n")
                        if self.favorite_only_var.get():
                            cycle_pos = g['active_slots'].index(mod_id)
                            f.write(f"    $g{g['id']}_cycle_pos = {cycle_pos}\n")
                        f.write("endif\n")
                    f.write(f"$\\modmanageragl\\group_{g['id']}\\active_slot = $g{g['id']}_slot\n\n")

                f.write(f"[Present]\nif $auto_enable == 1 || $shuffle_auto_enable == 1\n")
                f.write("    if time < $last_cycle\n        $last_cycle = time\n    endif\n")
                f.write(f"    if time - $last_cycle >= {timer_seconds}\n")
                f.write(f"        $last_cycle = time\n")
                f.write(f"        if $auto_enable == 1\n")
                f.write(f"            run = CommandListNext\n")
                f.write(f"        else\n")
                f.write(f"            run = CommandListShuffle\n")
                f.write(f"        endif\n")
                f.write(f"    endif\n")
                f.write(f"endif\n")
            previous_backup = self.backup_file(ini_path, "previous_mod_cycler", move=False)
            legacy_backup = self.migrate_legacy_root_ini()
            os.replace(tmp_path, ini_path)
            try:
                self.save_generation_state(final_groups)
                self.clear_generation_warning_labels()
            except (OSError, ValueError) as e:
                state_warning = f"\n\nCould not save cycler state snapshot:\n{e}"
        except OSError as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            if legacy_backup and not os.path.exists(self.get_legacy_root_ini_path()):
                try:
                    os.replace(legacy_backup, self.get_legacy_root_ini_path())
                except OSError as restore_error:
                    messagebox.showerror("Restore Failed", f"Old root INI is preserved at:\n{legacy_backup}\n\n{restore_error}")
            messagebox.showerror("Error", f"Failed to write mod_cycler.ini:\n{e}")
            return

        self.gen_btn.configure(bg="#2b6b3e", text="GENERATED .INI")
        self.root.after(300, self.reset_generate_ini_colors)
        details = f"Generated:\n{ini_path}\n\nPress F10 in-game."
        if previous_backup:
            details += "\n\nPrevious active ini was backed up."
        if legacy_backup:
            details += "\n\nOld root mod_cycler.ini was moved to backup."
        if state_warning:
            details += state_warning
        if self.favorite_only_var.get():
            details += "\n\nFavorites-only cycling is enabled."
            if groups_without_favorites:
                details += f"\nSkipped {len(groups_without_favorites)} selected group(s) with no favorited mods."
            if unresolved_favorites:
                details += f"\nSkipped {len(unresolved_favorites)} favorited mod(s) with missing or duplicate NRMM managed slot IDs."
        messagebox.showinfo("Success", details)

    def reset_generate_ini_colors(self):
        self.apply_ui_style()


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    semaphore_handle = check_single_instance()
    root = tk.Tk()
    app = GeneratorApp(root, semaphore_handle)
    root.protocol("WM_DELETE_WINDOW", app.quit_app)
    root.mainloop()
