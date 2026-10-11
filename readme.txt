# Mod Cycler v6.7

Cycle mods in XXMI games without reloading between selections. NRMM prepares the mods; Mod Cycler reads the managed folders and INIs, then generates its own cycling INI.

If you want to support me: [🎮 Patreon](https://www.patreon.com/cw/Hitakumori)

## How to Use

**Prepare:** Install your mods and use NRMM to set up their managed groups. Mod Cycler requires NRMM-prepared mods in `_MANAGED_`; it does not prepare mods or edit their INIs.

**Download:** Get v6.7 from [GitHub Releases](https://github.com/Hitakumori/Mod-Cycler/releases/latest). Extract the ZIP and place `Mod_Cycler_v6.7.exe` anywhere you want, or download the standalone EXE. Python is not required for the executable. Settings are stored in `%APPDATA%\NRMM_Mod_Cycler`.

**Launch:** Open `Mod_Cycler_v6.7.exe`.

**Browse:** Select your game's `Mods` folder. Examples: `GIMI\Mods`, `SRMI\Mods`, `WWMI\Mods`, or `ZZMI\Mods`.

**Select:** Check the mod groups you want to cycle. Renaming or refreshing keeps your current selections. Newly discovered groups stay unchecked until you select them.

**Generate:** Click **GENERATE .INI** to create `Mod Cycler\mod_cycler.ini` in the selected `Mods` folder.

**Reload:** Press F10 in-game to reload XXMI/GIMI and apply the new ini.

**After mod changes:** Regenerate `mod_cycler.ini` and press F10 after adding, removing, regrouping, or changing favorites in NRMM. The generated INI represents the mod setup at generation time.

> 💡 After `mod_cycler.ini` is generated and reloaded in-game, Mod Cycler does not need to stay open. The generated ini handles cycling inside XXMI/GIMI.

## Favorites Only

Enable **Favorites only** below the interval control before generating to cycle only mods marked as favorites in NRMM. Mod Cycler detects NRMM's empty `fav` marker file in each managed mod folder.

Groups with no favorited mods are skipped. A group with one favorite stays on that mod while the other selected groups continue cycling.

## Generated INI Controls

All generated ini controls are rebindable in the app before pressing **GENERATE .INI**.

- **PGUP / PGDN:** Cycle forward and backward through the selected groups.
- **INSERT:** Step through a shuffled order for all selected groups. The order is randomized when you generate the ini.
- **CAPSLOCK:** Toggle Auto-Cycle.
- **END:** Toggle Auto-Shuffle.

## App Hotkey

**Alt + S:** Show or hide the Mod Cycler window while the app is running.

This hotkey is for the app UI only. It is not written into `mod_cycler.ini` and is not needed after you close Mod Cycler.

## UI & Customization

- **Layout:** An opaque vertical interface with a blue title bar, a scrollable single-column group list, and permanently visible keybind and profile controls. Resize it from the bottom-right corner.
- **Profiles:** Save and load selected groups, keybinds, interval, and Favorites only mode.
- **Group Names:** Right-click any detected group to rename it.
- **Reset Group Name:** Rename a group to a blank value to remove the custom name and return to automatic name detection.

## Group Detection Notes

Mod Cycler reads groups from the selected `Mods` folder's `_MANAGED_` directory.

- If multiple detected folders use the same group number, Mod Cycler skips the duplicates because the generated ini can only target one mod-manager group per ID.
- Custom group names are saved per selected `Mods` folder, so labels from GIMI, SRMI, WWMI, and ZZMI do not overwrite each other.
- Mod Cycler rescans when you show the window, browse, rename, load a profile, or generate. It does not continuously monitor the Mods folder.
- Warnings identify changed mod-folder lists, favorite slots, and missing or manually edited generated INIs. Generate again to update the cycler.
- Older saved group names migrate to the previously selected Mods folder without overwriting existing custom names.

## Manual Updates

Download new releases from [Hitakumori/Mod-Cycler on GitHub](https://github.com/Hitakumori/Mod-Cycler/releases). Close Mod Cycler before replacing its executable with the downloaded version.

## Source Verification

Use Windows and 64-bit Python 3.12 with Tcl/Tk installed. From the repository folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -I -B -W error::ResourceWarning -m unittest discover -s tests -v
.\.venv\Scripts\python.exe .\Mod_Cycler_v6_7.pyw
```

Tests use temporary Mods and configuration folders inside the repository. They cover selection, configuration, profiles, generated cycling commands, write-failure recovery, and hotkey cleanup. The native hotkey check skips when Windows denies registration. Generated INI commands are simulated; verification inside an XXMI game remains a separate check.

## Build the Windows EXE

After source verification, install the build requirements in the same environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean .\Mod_Cycler_v6.7.spec
```

The standalone executable is written to `dist\Mod_Cycler_v6.7.exe`. Test that executable before distributing it. The spec includes the icon, version resource, Tcl/Tk runtime, and Tkinter files. Build output, local settings, and game data are excluded by `.gitignore`.

See [CHANGELOG.md](CHANGELOG.md) for v6.7 changes.
