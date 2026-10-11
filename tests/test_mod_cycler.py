"""Regression checks for Mod Cycler. Run with python -I -B -m unittest discover -s tests -v."""
import ctypes
import json
import math
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

if sys.platform != "win32":
    raise unittest.SkipTest("Mod Cycler uses Windows and Tkinter.")

import tkinter as tk

WORKSPACE = Path(__file__).resolve().parents[1]
SOURCE = WORKSPACE / "Mod_Cycler_v6_7.pyw"
APP = types.ModuleType("mod_cycler_test")
APP.__file__ = str(SOURCE)
exec(compile(SOURCE.read_text(encoding="utf-8-sig"), str(SOURCE), "exec"), APP.__dict__)
NATIVE_LISTENER = APP.GeneratorApp.listen_for_hotkey


class IniRunner:
    """Execute the generated command subset in memory, without a game or mod loader."""

    def __init__(self, text):
        self.sections = {}
        self.values = {}
        self.time = 0
        section = None
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith(";"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                self.sections[section] = []
            elif section:
                self.sections[section].append(line)
        for line in self.sections["Constants"]:
            self.assign(line.removeprefix("global persist ").removeprefix("global "))

    def evaluate(self, expression):
        expression = expression.replace("||", " or ").replace("&&", " and ")
        expression = re.sub(r"\$[A-Za-z0-9_\\]+", lambda m: "values[" + repr(m[0]) + "]", expression)
        return eval(expression, {"__builtins__": {}}, {"values": self.values, "time": self.time})

    def assign(self, line):
        name, expression = line.split("=", 1)
        self.values[name.strip()] = self.evaluate(expression.strip())

    def run(self, section):
        conditions = []
        for line in self.sections[section]:
            active = all(conditions)
            if line.startswith("if "):
                conditions.append(bool(self.evaluate(line[3:])) if active else False)
            elif line == "else":
                conditions[-1] = not conditions[-1]
            elif line == "endif":
                conditions.pop()
            elif active and line.startswith("run = "):
                self.run(line.removeprefix("run = ").strip())
            elif active and line.startswith("$"):
                self.assign(line)
        if conditions:
            raise AssertionError("Unbalanced generated INI conditionals")


class ModCyclerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".mod-cycler-tests-", dir=WORKSPACE)
        self.task_dir = Path(self.temporary.name).resolve()
        self.assertTrue(self.task_dir.is_relative_to(WORKSPACE))
        self.mods = self.task_dir / "Mods"
        (self.mods / "_MANAGED_").mkdir(parents=True)
        self.add_group(1, ["A", "B", "C"])
        self.add_group(2, ["D", "E"])
        self.config = self.task_dir / "AppData" / "config.json"
        self.config.parent.mkdir()
        self.config.write_text(json.dumps({"mods_path": str(self.mods), "ui_alpha": 0.15, "compact_ui": True}),
                               encoding="utf-8")
        self.patchers = [
            mock.patch.object(APP, "BASE", str(self.mods)),
            mock.patch.object(APP, "APPDATA_DIR", str(self.config.parent)),
            mock.patch.object(APP, "CONFIG_FILE", str(self.config)),
            mock.patch.object(APP.GeneratorApp, "setup_tray", lambda app: None),
            mock.patch.object(APP.GeneratorApp, "listen_for_hotkey", lambda app: None),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.dialogs = []
        for name in ("showinfo", "showwarning", "showerror"):
            patcher = mock.patch.object(APP.messagebox, name, side_effect=lambda *args, **kwargs: self.dialogs.append(args))
            patcher.start()
            self.patchers.append(patcher)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = APP.GeneratorApp(self.root, semaphore_handle=1)
        self.app.semaphore_handle = None
        self.app.hotkey_thread.join(timeout=1)
        self.root.update()

    def tearDown(self):
        try:
            if not self.app._closing:
                self.app.quit_app()
        finally:
            for patcher in reversed(self.patchers):
                patcher.stop()
            self.temporary.cleanup()

    def add_group(self, gid, names, slots=None, favorites=(), managed=None):
        group = (managed or self.mods / "_MANAGED_") / f"group_{gid}"
        for name, slot in zip(names, slots or range(1, len(names) + 1)):
            mod = group / name
            mod.mkdir(parents=True, exist_ok=True)
            (mod / "managed.ini").write_text(f"global $managed_slot_id = {slot}\n", encoding="utf-8")
            if name in favorites:
                (mod / "fav").touch()
        return group

    def select_only(self, *gids):
        for gid, variable in self.app.group_vars.items():
            variable.set(gid in gids)
        self.app.sync_master_var()

    def generate(self):
        self.app.generate_ini()
        path = Path(self.app.get_active_ini_path())
        self.assertTrue(path.is_file(), self.dialogs)
        return path.read_text(encoding="utf-8")

    def profile(self, data):
        self.app.profile_var.set("Test")
        path = Path(self.app.get_profile_path("Test"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_refresh_and_rename_preserve_selection(self):
        self.select_only(2)
        self.app.refresh_groups()
        self.assertFalse(self.app.group_vars[1].get())
        self.assertTrue(self.app.group_vars[2].get())
        with mock.patch.object(APP.simpledialog, "askstring", return_value="Renamed"):
            self.app.rename_group_ui(None, 1, "Old")
        self.assertFalse(self.app.group_vars[1].get())
        self.assertEqual(self.app.nicknames["1"], "Renamed")
        self.assertFalse(self.app.master_var.get())

    def test_new_groups_are_unselected_and_different_games_do_not_share_selection(self):
        self.select_only(2)
        self.add_group(9, ["NewA", "NewB"])
        self.app.refresh_groups()
        self.assertFalse(self.app.group_vars[9].get())
        other = self.task_dir / "OtherGame" / "Mods"
        managed = other / "_MANAGED_"
        managed.mkdir(parents=True)
        self.add_group(1, ["OtherA", "OtherB"], managed=managed)
        self.app.target_dir = str(other)
        self.app.use_target_nicknames()
        self.app.refresh_groups()
        self.assertEqual(set(self.app.group_vars), {1})
        self.assertTrue(self.app.group_vars[1].get())

    def test_master_checkbox_tracks_individual_controls_and_empty_inventory(self):
        button = next(w for w in self.app.group_widgets if isinstance(w, tk.Checkbutton) and w.cget("text").startswith("Group 1 "))
        button.invoke()
        self.assertFalse(self.app.master_var.get())
        button.invoke()
        self.assertTrue(self.app.master_var.get())
        self.app.group_vars.clear()
        self.app.sync_master_var()
        self.assertFalse(self.app.master_var.get())

    def test_config_invalid_roots_and_types_use_defaults(self):
        with mock.patch("builtins.print"):
            for bad in ([], None, "text", 12):
                self.config.write_text(json.dumps(bad), encoding="utf-8")
                config = self.app.load_config()
                self.assertEqual(config["keys"], APP.DEFAULT_KEYS)
            self.config.write_text(json.dumps({
                "mods_path": 3, "ui_alpha": {}, "keys": [],
                "favorite_only": "false", "compact_ui": {},
                "nicknames_by_path": {"bad": []}, "legacy_nicknames": [],
            }), encoding="utf-8")
            config = self.app.load_config()
        self.assertEqual(config["mods_path"], APP.BASE)
        self.assertNotIn("ui_alpha", config)
        self.assertFalse(config["favorite_only"])
        self.assertNotIn("compact_ui", config)
        self.assertEqual(config["nicknames_by_path"], {})

    def test_config_ignores_retired_options_and_validates_keybinds(self):
        for raw in (None, True, math.nan, math.inf, -10, 10, "0.5"):
            with self.subTest(alpha=raw):
                self.config.write_text(json.dumps({"ui_alpha": raw, "compact_ui": True,
                    "keys": {"next": "CTRL F5", "prev": "A\nB", "shuffle": {}, "unknown": "X"}}), encoding="utf-8")
                config = self.app.load_config()
                self.assertNotIn("ui_alpha", config)
                self.assertNotIn("compact_ui", config)
                self.assertEqual(config["keys"]["next"], "CTRL F5")
                self.assertEqual(config["keys"]["prev"], "PGDN")
                self.assertEqual(config["keys"]["shuffle"], "INSERT")
                self.assertNotIn("unknown", config["keys"])

    def test_atomic_writer_preserves_previous_file_on_failure(self):
        self.config.write_text('{"original": true}', encoding="utf-8")
        with mock.patch.object(APP.os, "replace", side_effect=OSError("Simulated replacement failure")):
            with self.assertRaises(OSError):
                APP.write_json_atomic(self.config, {"replacement": True})
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8")), {"original": True})
        self.assertFalse(list(self.config.parent.glob("*.tmp")))
        with self.assertRaises(ValueError):
            APP.write_json_atomic(self.config, {"invalid": math.nan})
        self.assertFalse(list(self.config.parent.glob("*.tmp")))
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8")), {"original": True})

    def test_config_save_is_atomic_and_removed_features_stay_removed(self):
        self.app.save_config()
        data = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertNotIn("ui_color", data)
        self.assertNotIn("ui_alpha", data)
        self.assertNotIn("compact_ui", data)
        self.assertFalse(list(self.config.parent.glob("*.tmp")))
        self.assertEqual(self.app.ui_color, "#007acc")
        self.assertFalse(hasattr(self.app, "update_btn"))
        self.assertFalse(hasattr(self.app, "theme_btn"))
        for name in ("ui_alpha", "alpha_scale", "compact_ui_var", "compact_ui_btn",
                     "update_alpha_from_scale", "toggle_compact_ui", "apply_compact_ui"):
            self.assertFalse(hasattr(self.app, name), name)
        self.assertEqual(float(self.root.attributes("-alpha")), 1.0)

    def test_vertical_layout_keeps_all_controls_visible_when_resized(self):
        self.root.deiconify()
        controls = [self.app.browse_btn, self.app.favorites_only_cb, self.app.interval_entry,
                    self.app.groups_lbl, self.app.master_cb, self.app.profile_combo,
                    self.app.save_profile_btn, self.app.support_btn, self.app.gen_btn,
                    *self.app.key_combos.values()]
        for width, height in (self.app.minimum_size, (680, 1000), (980, 900)):
            with self.subTest(size=(width, height)):
                self.root.geometry(f"{width}x{height}+30+30")
                self.root.update()
                left, top = self.root.winfo_rootx(), self.root.winfo_rooty()
                right, bottom = left + self.root.winfo_width(), top + self.root.winfo_height()
                for widget in controls:
                    self.assertTrue(widget.winfo_ismapped(), str(widget))
                    self.assertGreaterEqual(widget.winfo_rootx(), left)
                    self.assertGreaterEqual(widget.winfo_rooty(), top)
                    self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), right)
                    self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), bottom)
                self.assertTrue(all(int(w.grid_info()["column"]) == 0 for w in self.app.group_widgets))
                self.assertLess(self.app.canvas.winfo_rooty(), self.app.info_frame.winfo_rooty())
                self.assertLess(self.app.info_frame.winfo_rooty(), self.app.profile_frame.winfo_rooty())
                self.assertLess(self.app.profile_frame.winfo_rooty(), self.app.gen_btn.winfo_rooty())

    def test_legacy_names_migrate_once_without_overwriting_custom_names(self):
        key = self.app.get_path_key()
        self.app.nicknames_by_path = {key: {"1": "Current"}}
        self.app.legacy_nicknames = {"1": "Old", "2": "Legacy"}
        self.app.legacy_nickname_key = key
        self.app.use_target_nicknames()
        self.assertEqual(self.app.nicknames, {"1": "Current", "2": "Legacy"})
        self.assertEqual(self.app.legacy_nicknames, {})
        self.app.target_dir = str(self.task_dir / "Other")
        self.app.use_target_nicknames()
        self.assertEqual(self.app.nicknames, {})

    def test_invalid_profiles_do_not_partially_apply(self):
        before = (self.app.timer_var.get(), self.app.keys["next"].get(), self.app.favorite_only_var.get(),
                  {gid: var.get() for gid, var in self.app.group_vars.items()})
        for data in ([], {"interval": 0}, {"interval": True}, {"keys": []}, {"keys": {"next": "A\nB"}},
                     {"favorite_only": "false"}, {"selected_groups": "1"}, {"selected_groups": ["²"]}):
            with self.subTest(profile=data):
                self.profile(data)
                self.app.load_selected_profile()
                after = (self.app.timer_var.get(), self.app.keys["next"].get(), self.app.favorite_only_var.get(),
                         {gid: var.get() for gid, var in self.app.group_vars.items()})
                self.assertEqual(after, before)
        self.assertTrue(any(dialog[0] == "Profile Load Failed" for dialog in self.dialogs))

    def test_valid_profile_round_trip(self):
        self.select_only(2)
        self.app.timer_var.set("17")
        self.app.keys["next"].set("CTRL F5")
        self.app.favorite_only_var.set(True)
        self.profile(self.app.collect_profile_data("Test"))
        self.select_only(1)
        self.app.timer_var.set("99")
        self.app.load_selected_profile()
        self.assertEqual(self.app.timer_var.get(), "17")
        self.assertEqual(self.app.keys["next"].get(), "CTRL F5")
        self.assertTrue(self.app.favorite_only_var.get())
        self.assertFalse(self.app.group_vars[1].get())
        self.assertTrue(self.app.group_vars[2].get())
        self.assertFalse(self.app.master_var.get())

    def test_profile_filename_and_group_id_validation(self):
        for raw, expected in [("CON", "_CON"), ("NUL.txt", "_NUL.txt"), ("a/b:c", "a_b_c"), ("0x1f", "0x1f"), ("Default", "Default")]:
            self.assertEqual(self.app.safe_profile_name(raw), expected)
        for raw in ("²", True, -1, 1.5, [], None):
            self.assertIsNone(APP.parse_group_id(raw))
        self.assertEqual(APP.parse_group_id("001"), 1)

    def test_duplicate_ids_include_undersized_groups(self):
        managed = self.mods / "_MANAGED_"
        self.add_group(7, ["Only"], managed=managed / "a")
        duplicate = self.add_group(7, ["A", "B"], managed=managed / "b")
        self.app.refresh_groups()
        self.assertEqual(self.app.group_slot_counts[7], 1)
        self.assertNotIn(7, self.app.group_vars)
        self.assertIn(str(duplicate), self.app.duplicate_group_paths)

    def test_favorite_ids_are_authoritative_and_duplicates_are_skipped(self):
        self.add_group(7, ["A", "B", "C"], [2, 5, 5], ["A", "B", "C"])
        self.app.refresh_groups()
        self.assertEqual(self.app.group_favorite_slots[7], [2, 5])
        self.assertEqual(self.app.group_unresolved_favorites[7], ["C"])

    def test_generate_rescans_inventory_without_broadening_selection(self):
        self.select_only(2)
        self.add_group(9, ["A", "B"])
        (self.mods / "_MANAGED_" / "group_2" / "F").mkdir()
        text = self.generate()
        self.assertIn("$g2_slot", text)
        self.assertNotIn("$g1_slot", text)
        self.assertNotIn("$g9_slot", text)
        state = json.loads(Path(self.app.get_state_path()).read_text(encoding="utf-8"))
        self.assertEqual(state["groups"]["2"]["slots"], 3)
        self.assertIn("9", state["detected_groups"])
        self.assertFalse(self.app.group_vars[9].get())

    def test_snapshot_detects_replacement_missing_ini_and_manual_edits(self):
        self.generate()
        self.assertEqual(self.app.get_generation_warnings(), [])
        (self.mods / "_MANAGED_" / "group_1" / "A").rename(self.mods / "_MANAGED_" / "group_1" / "Replacement")
        self.app.refresh_groups()
        self.assertTrue(any("different mod folders" in w for w in self.app.get_generation_warnings()))
        active = Path(self.app.get_active_ini_path())
        active.write_text(active.read_text(encoding="utf-8") + "; manual edit\n", encoding="utf-8")
        self.assertTrue(any("changed outside" in w for w in self.app.get_generation_warnings()))
        active.unlink()
        self.assertTrue(any("is missing" in w for w in self.app.get_generation_warnings()))

    def test_invalid_snapshot_members_do_not_crash(self):
        path = Path(self.app.get_state_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        Path(self.app.get_active_ini_path()).write_text("; active\n", encoding="utf-8")
        for state in ([], {"groups": []}, {"groups": {"1": []}}, {"groups": {"1": {"slots": {}}}, "favorite_only": []}):
            path.write_text(json.dumps(state), encoding="utf-8")
            with mock.patch("builtins.print"):
                warnings = self.app.get_generation_warnings()
            self.assertTrue(warnings)

    def favorite_ini(self, favorites=("A", "B", "C")):
        self.add_group(7, ["A", "B", "C"], [2, 5, 9], favorites)
        self.app.refresh_groups()
        self.select_only(7)
        self.app.favorite_only_var.set(True)
        with mock.patch.object(APP.random, "shuffle", side_effect=lambda deck: deck.reverse()):
            return IniRunner(self.generate())

    def test_favorites_follow_visible_slot_after_shuffle(self):
        ini = self.favorite_ini()
        ini.run("CommandListShuffle")
        self.assertEqual(ini.values["$g7_slot"], 5)
        ini.run("CommandListNext")
        self.assertEqual(ini.values["$g7_slot"], 9)
        ini.run("CommandListPrev")
        self.assertEqual(ini.values["$g7_slot"], 5)
        ini.run("CommandListShuffle")
        self.assertEqual(ini.values["$g7_slot"], 2)
        ini.run("CommandListPrev")
        self.assertEqual(ini.values["$g7_slot"], 9)
        self.assertEqual(ini.values[r"$\modmanageragl\group_7\active_slot"], 9)

    def test_favorites_recover_from_stale_persistent_positions(self):
        ini = self.favorite_ini()
        ini.values["$g7_cycle_pos"] = 999
        ini.values["$g7_slot"] = 5
        ini.run("CommandListPrev")
        self.assertEqual(ini.values["$g7_slot"], 2)
        ini.values["$g7_slot"] = 42
        ini.run("CommandListNext")
        self.assertEqual(ini.values["$g7_slot"], 2)
        ini.values["$g7_slot"] = 42
        ini.run("CommandListPrev")
        self.assertEqual(ini.values["$g7_slot"], 9)

    def test_single_favorite_remains_selected(self):
        ini = self.favorite_ini(("B",))
        for section in ("CommandListNext", "CommandListPrev", "CommandListShuffle") * 3:
            ini.run(section)
            self.assertEqual(ini.values["$g7_slot"], 5)

    def test_normal_cycling_and_auto_modes_still_work(self):
        self.select_only(1)
        ini = IniRunner(self.generate())
        ini.values["$g1_slot"] = 3
        ini.run("CommandListNext")
        self.assertEqual(ini.values["$g1_slot"], 1)
        ini.run("CommandListPrev")
        self.assertEqual(ini.values["$g1_slot"], 3)
        ini.time = 10
        ini.run("CommandListToggleAuto")
        self.assertEqual(ini.values["$auto_enable"], 1)
        self.assertEqual(ini.values["$shuffle_auto_enable"], 0)
        self.assertEqual(ini.values["$g1_slot"], 1)
        ini.time = 130
        ini.run("Present")
        self.assertEqual(ini.values["$g1_slot"], 2)
        ini.run("CommandListToggleShuffleAuto")
        self.assertEqual(ini.values["$auto_enable"], 0)
        self.assertEqual(ini.values["$shuffle_auto_enable"], 1)
        ini.values["$last_cycle"] = 5000
        ini.time = 1
        ini.run("Present")
        self.assertEqual(ini.values["$last_cycle"], 1)

    def test_regeneration_recovers_after_group_shrinks(self):
        removed_names = ["D", "E", "F", "G", "H"]
        group = self.add_group(1, removed_names, slots=[4, 5, 6, 7, 8])
        managed_inis = {path: path.read_bytes() for path in group.rglob("*.ini")}
        self.select_only(1)
        old_ini = IniRunner(self.generate())
        for _ in range(8):
            if old_ini.values["$g1_slot"] == 8:
                break
            old_ini.run("CommandListNext")
        self.assertEqual(old_ini.values["$g1_slot"], 8)

        for name in removed_names:
            source = (group / name).resolve()
            destination = (self.task_dir / f"removed_{name}").resolve()
            self.assertTrue(source.is_relative_to(self.task_dir))
            self.assertTrue(destination.is_relative_to(self.task_dir))
            source.rename(destination)

        new_ini = IniRunner(self.generate())
        self.assertEqual(self.app.group_slot_counts[1], 3)
        # XXMI restores saved variables after loading the regenerated defaults.
        new_ini.values.update({name: value for name, value in old_ini.values.items()
                               if name in new_ini.values})
        self.assertEqual(new_ini.values["$g1_slot"], 8)
        new_ini.run("CommandListPrev")
        self.assertEqual(new_ini.values["$g1_slot"], 3)
        self.assertEqual(new_ini.values[r"$\modmanageragl\group_1\active_slot"], 3)
        new_ini.run("CommandListNext")
        self.assertEqual(new_ini.values["$g1_slot"], 1)
        for path, content in managed_inis.items():
            current_path = path if path.exists() else self.task_dir / f"removed_{path.parent.name}" / path.name
            self.assertEqual(current_path.read_bytes(), content)

    def test_normal_cycling_recovers_invalid_saved_selections(self):
        self.select_only(1)
        text = self.generate()
        for section, stale_slot, expected in (
            ("CommandListNext", 8, 1),
            ("CommandListNext", 0, 1),
            ("CommandListNext", -8, 1),
            ("CommandListPrev", 8, 3),
            ("CommandListPrev", 0, 3),
            ("CommandListPrev", -8, 3),
        ):
            with self.subTest(section=section, stale_slot=stale_slot):
                ini = IniRunner(text)
                ini.values["$g1_slot"] = stale_slot
                ini.run(section)
                self.assertEqual(ini.values["$g1_slot"], expected)
                self.assertEqual(ini.values[r"$\modmanageragl\group_1\active_slot"], expected)
                for _ in range(6):
                    ini.run(section)
                    self.assertIn(ini.values["$g1_slot"], (1, 2, 3))
                    self.assertEqual(ini.values[r"$\modmanageragl\group_1\active_slot"],
                                     ini.values["$g1_slot"])

    def test_write_failure_restores_legacy_root_ini(self):
        active = Path(self.app.get_active_ini_path())
        active.parent.mkdir(parents=True, exist_ok=True)
        active.write_text("; previous active\n", encoding="utf-8")
        legacy = Path(self.app.get_legacy_root_ini_path())
        legacy.write_text("; legacy root\n", encoding="utf-8")
        replace = APP.os.replace
        failed = False

        def fail_once(source, destination):
            nonlocal failed
            if str(destination) == str(active) and not failed:
                failed = True
                raise OSError("Simulated INI replacement failure")
            return replace(source, destination)

        with mock.patch.object(APP.os, "replace", side_effect=fail_once):
            self.app.generate_ini()
        self.assertTrue(failed)
        self.assertEqual(active.read_text(encoding="utf-8"), "; previous active\n")
        self.assertEqual(legacy.read_text(encoding="utf-8"), "; legacy root\n")
        self.assertFalse(Path(str(active) + ".tmp").exists())
        self.assertTrue(list(Path(self.app.get_backups_dir()).glob("*.bak")))

    def test_tray_callbacks_are_dispatched_on_tk_thread(self):
        calls = []
        with mock.patch.object(self.app, "show_window", side_effect=lambda: calls.append(threading.get_ident())):
            worker = threading.Thread(target=self.app.show_from_tray, args=(None, None))
            worker.start()
            worker.join(1)
            self.assertEqual(calls, [])
            self.app.process_ui_actions()
        self.assertEqual(calls, [threading.get_ident()])

    def test_shutdown_handles_listener_ending_during_message_setup(self):
        app = self.app
        calls = []

        class RacingPost:
            def __setattr__(self, name, value):
                if name == "argtypes":
                    app._hotkey_thread_id = None
                object.__setattr__(self, name, value)

            def __call__(self, identifier, message, wparam, lparam):
                calls.append(identifier)
                return 0  # The listener already exited.

        self.app._hotkey_thread_id = 1234
        user32 = types.SimpleNamespace(PostThreadMessageW=RacingPost())
        with mock.patch.object(APP.ctypes.windll, "user32", user32):
            self.app.quit_app()
        self.assertEqual(calls, [1234])
        self.assertTrue(self.app._closing)

    def test_hotkey_message_dispatch_and_owner_thread_cleanup(self):
        messages = APP.queue.Queue()
        messages.put((0x0312, 1))
        owners = []
        callbacks = []

        def get_message(pointer, hwnd, minimum, maximum):
            message, identifier = messages.get(timeout=3)
            pointer._obj.message = message
            pointer._obj.wParam = identifier
            return 0 if message == 0x0012 else 1

        def unregister(hwnd, identifier):
            owners.append(threading.get_ident())
            return 1

        user32 = types.SimpleNamespace(
            RegisterHotKey=mock.Mock(return_value=1),
            UnregisterHotKey=mock.Mock(side_effect=unregister),
            PeekMessageW=mock.Mock(return_value=0),
            GetMessageW=mock.Mock(side_effect=get_message),
            PostThreadMessageW=mock.Mock(side_effect=lambda tid, message, wparam, lparam: messages.put((message, wparam)) or 1),
        )
        kernel32 = types.SimpleNamespace(GetCurrentThreadId=mock.Mock(return_value=1234))
        with mock.patch.object(APP.ctypes.windll, "user32", user32), \
             mock.patch.object(APP.ctypes.windll, "kernel32", kernel32), \
             mock.patch.object(self.app, "toggle_from_hotkey", side_effect=lambda: callbacks.append(threading.get_ident())):
            self.app.hotkey_thread = threading.Thread(target=NATIVE_LISTENER, args=(self.app,), daemon=True)
            self.app.hotkey_thread.start()
            deadline = time.monotonic() + 3
            while not callbacks and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertEqual(callbacks, [threading.get_ident()])
            owner = self.app.hotkey_thread.ident
            self.app.quit_app()
            self.assertFalse(self.app.hotkey_thread.is_alive())
            self.assertEqual(owners, [owner])
            user32.PostThreadMessageW.assert_called_once_with(1234, 0x0012, 0, 0)
            self.assertIsNone(self.app._hotkey_thread_id)

    def test_native_hotkey_unregisters_on_its_owner_thread(self):
        user32 = ctypes.windll.user32
        modifiers, key = 0x4007, 0x87  # Ctrl+Alt+Shift+F24, avoiding the user's Alt+S.
        user32.RegisterHotKey.argtypes = [APP.wintypes.HWND, ctypes.c_int, APP.wintypes.UINT, APP.wintypes.UINT]
        user32.RegisterHotKey.restype = APP.wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [APP.wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = APP.wintypes.BOOL
        if not user32.RegisterHotKey(None, 70, modifiers, key):
            self.skipTest(f"Native hotkeys unavailable: Windows error {ctypes.windll.kernel32.GetLastError()}")
        self.assertTrue(user32.UnregisterHotKey(None, 70))
        unregister = user32.UnregisterHotKey
        owners = []
        callbacks = []

        def tracked_unregister(hwnd, identifier):
            owners.append(threading.get_ident())
            return unregister(hwnd, identifier)

        with mock.patch.object(APP, "HOTKEY_MODIFIERS", modifiers), mock.patch.object(APP, "HOTKEY_VK", key), \
             mock.patch.object(user32, "UnregisterHotKey", side_effect=tracked_unregister), \
             mock.patch.object(self.app, "toggle_from_hotkey", side_effect=lambda: callbacks.append(threading.get_ident())):
            self.app.hotkey_thread = threading.Thread(target=NATIVE_LISTENER, args=(self.app,), daemon=True)
            self.app.hotkey_thread.start()
            deadline = time.monotonic() + 3
            while self.app._hotkey_thread_id is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIsNotNone(self.app._hotkey_thread_id)
            user32.PostThreadMessageW.argtypes = [APP.wintypes.DWORD, APP.wintypes.UINT, APP.wintypes.WPARAM, APP.wintypes.LPARAM]
            user32.PostThreadMessageW.restype = APP.wintypes.BOOL
            self.assertTrue(user32.PostThreadMessageW(self.app._hotkey_thread_id, 0x0312, 1, 0))
            while not callbacks and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertEqual(callbacks, [threading.get_ident()])
            owner = self.app.hotkey_thread.ident
            self.app.quit_app()
            self.assertFalse(self.app.hotkey_thread.is_alive())
            self.assertEqual(owners, [owner])
        self.assertTrue(user32.RegisterHotKey(None, 71, modifiers, key))
        self.assertTrue(user32.UnregisterHotKey(None, 71))

    def test_copies_share_instance_name_for_shared_configuration(self):
        other = types.ModuleType("mod_cycler_other_copy")
        other.__file__ = str(self.task_dir / "DifferentInstall" / SOURCE.name)
        exec(compile(SOURCE.read_text(encoding="utf-8-sig"), str(SOURCE), "exec"), other.__dict__)
        self.assertNotEqual(other.BASE, str(SOURCE.parent))
        self.assertEqual(other.INSTANCE_NAME, APP.INSTANCE_NAME)


if __name__ == "__main__":
    unittest.main()
