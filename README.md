# Session Recorder

**English** | [한국어](README.ko.md)

[![Blender 5.1+](https://img.shields.io/badge/Blender-5.1%2B-E87D0D?logo=blender&logoColor=white)](https://www.blender.org/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue)](LICENSE)

A Blender extension (5.1+) that **records what you do, in order**, to a log next to the `.blend` file.
It runs on its own inside Blender, no other add-on or external program needed.

## Why

Writing study notes after following a tutorial or modeling on your own means taking screenshots again
and scrubbing back through the video to remember what you did and in which order.
This extension keeps the actions with their values, your notes and screenshots in one file while you work,
so the notes can be written from that record later (by you, or by handing it to an AI tool).

## What is recorded

| Event `ev` | Content | Source |
|---|---|---|
| `session_start` / `session_end` | Recording started (`title`) / stopped (`comment`, `reason`, number of actions `ops`, `minutes`) | Start/Stop buttons |
| `op` | The operator and its **values** (`mesh.bevel(offset=0.03, segments=2)`), default arguments left out | Info editor reports |
| `prop` | A value changed in a panel (`bpy.context.object.modifiers["Bevel"].width = 0.02`) | Info editor reports |
| `undo` / `redo` | `Ctrl+Z` / `Ctrl+Shift+Z`, repeats merged with a count `n` | undo/redo handlers |
| `error` | Warnings and errors (hints of where you got stuck) | Info editor reports |
| `info` | Other messages | Info editor reports |
| `save` | Save with statistics (object count, vertices/faces, modifier stack per mesh) | save handler |
| `shot` | 3D viewport screenshot (`shots/0007.png`) and why: `start`, `stop`, `save`, `mode`, `ops`, `note` | timer |
| `note` | A note added with `Ctrl+Alt+N` | operator |
| `log_created` / `continued_from` | Log created / path of the log before "Save As" | save handler |

Common fields: `t` (local time), `mode` (mode right after the action), `obj` (active object).
Repeated clicks such as picking edge loops are merged into one line with `n` (count) and `t_end`.

```jsonl
{"t":"2026-10-10T19:12:30","ev":"op","op":"mesh.loopcut_slide","msg":"mesh.loopcut_slide(MESH_OT_loopcut={number_cuts=3, edge_index=5})","mode":"EDIT_MESH","obj":"Muzzle"}
{"t":"2026-10-10T19:13:09","ev":"op","op":"mesh.loop_select","msg":"mesh.loop_select(...)","mode":"EDIT_MESH","obj":"Muzzle","n":16,"t_end":"2026-10-10T19:13:39"}
{"t":"2026-10-10T19:13:50","ev":"op","op":"mesh.bevel","msg":"mesh.bevel(offset=0.0304854, segments=2, affect='EDGES')","mode":"EDIT_MESH","obj":"Muzzle"}
{"t":"2026-10-10T19:14:01","ev":"save","file":"muzzle.blend","stats":{"objects":3,"verts":412,"faces":398,"meshes":[...]}}
{"t":"2026-10-10T19:14:01","ev":"shot","file":"shots/0003.png","why":"save"}
```

## Where the files go

```
muzzle_modeling.blend
muzzle_modeling_history/
├── log.jsonl      # append only, one line per event (one file for all sessions)
└── shots/0001.png …
```

- Close Blender and come back days later, recording continues in the same `log.jsonl`. One recording is the span from `session_start` to `session_end`.
- Opening another file or quitting Blender while recording ends the session (`reason`: `file`, `exit`). Press Start again to continue.
- For a file that was never saved, events are kept in memory and written **on the first save**. Closing without saving keeps them in the extension's own folder (`extensions/.user/user_default/session_recorder/unsaved/`).
- The first save adds a custom property `session_recorder_id` to the scene, so a log can be followed after "Save As" under another name.

## Installation

1. Download `session_recorder-<version>.zip` from [Releases](https://github.com/bada0817/blender-session-recorder/releases), or build it with the command under "Development".
2. In Blender: **Edit → Preferences → Get Extensions → ⌄ (top right) → Install from Disk…** and pick the zip.

## Usage

Recording is done from the **Recorder tab of the 3D viewport sidebar (N)**.
Starting and stopping are buttons only, so a stray key press can't turn recording on or off.

1. **Start Recording** → title (optional, e.g. the tutorial name) → **Start**
2. Work. The status bar shows `REC <number of actions>`.
3. Any time: **`Ctrl+Alt+N`** or the **Add Note** button for a note (why you did something, what went wrong, a tutorial timestamp …). A screenshot is taken with it.
4. **Stop Recording** → comment about the session (optional) → **Stop**

- **Settings** sub-panel (same as the add-on preferences): the current note shortcut (changed in Preferences → Add-ons only), start automatically (off by default), record view changes, status bar display, check interval (0.25 s), screenshot triggers (on save, on mode change, every N actions, minimum gap 60 s).
- **Open History Folder**: opens the log folder of the current file.

## Limitations

- Viewport navigation and some clicks the Info editor doesn't show are not recorded.
- `mode`/`obj` are read on each check, switching mode right after an action can record the next mode.
- Adjusting an operator in the bottom-left panel (F9) makes Blender undo it and run it again with the new values. Both are merged into one line with the **final values** and `adjusted` (number of adjustments). The same goes for repeated changes of one property (`prop`).
- Running the same operator again within 1 s of `Ctrl+Z` can be merged as an adjustment.
- Screenshots that show nothing new, and saves without changes within 5 s, are skipped. Save screenshots respect the minimum gap (60 s), start, stop and notes always take one.
- Screenshots are PNG (a few hundred KB each), shrink them when using them in documents.

## Development

```sh
python3 -m unittest discover -s tests   # tests for compact.py (no Blender needed)
blender --command extension build --source-dir . --output-dir /tmp
```

License: GPL-3.0-or-later
