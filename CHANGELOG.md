# Changelog

## 6.7 — 2026-10-11

- Replaced the UI with an opaque vertical layout and fixed blue styling.
- Removed UI color customization, transparency, compact mode, and automatic updates. Updates are available manually through GitHub Releases.
- Preserved selected groups during refresh and rename; newly discovered groups remain unchecked.
- Improved validation and saving of settings, profiles, and per-game group names.
- Improved Favorites-only detection, duplicate-group handling, generation rescanning, and warnings when generated output needs updating.
- Improved backup and migration recovery, tray callbacks, native hotkey handling, and shutdown cleanup.
- Recovered valid Next/Previous selections when a regenerated group has fewer mods than a saved cycling position.
- Added 29 regression tests and documented source verification and Windows EXE builds.

NRMM remains required to prepare mods. Mod Cycler reads managed mod INIs and writes its own cycling files. After changing mods or favorites, regenerate the cycler INI and press F10 in-game.
