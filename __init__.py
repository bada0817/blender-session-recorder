# SPDX-License-Identifier: GPL-3.0-or-later

"""
Records what you do in Blender to a log next to the .blend file.

The Info editor reports (``WindowManager.reports``) are read on a timer and new ones are appended
to ``<blend name>_history/log.jsonl``, together with undo/redo, saves, notes and viewport screenshots.
Runs on its own, the MCP add-on isn't needed.
"""

__all__ = (
    "register",
    "unregister",
)

import hashlib
import json
import os
import re
import time
import uuid

import bpy  # pylint: disable=import-error
from bpy.app.handlers import persistent  # pylint: disable=import-error
from bpy.props import (  # pylint: disable=import-error
    BoolProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)

from .compact import (
    op_call_compact,
    op_idname,
)

LOG_NAME = "log.jsonl"
SHOTS_DIR = "shots"
# Scene custom property, so a log can be followed when the file is saved under another name.
ID_KEY = "session_recorder_id"

# Clicks that are merged into one line with a count, e.g. picking 16 edge loops.
_COLLAPSE_OPS = frozenset((
    "mesh.edgering_select",
    "mesh.loop_select",
    "mesh.select_linked_pick",
    "mesh.shortest_path_pick",
    "outliner.item_activate",
    "view3d.select",
    "view3d.select_box",
    "view3d.select_circle",
    "view3d.select_lasso",
))
# Seconds without a change before held events (merged clicks, undo ...) are written.
_HELD_TIMEOUT = 3.0
# Seconds between the undo step and the new run of an operator adjusted with F9 (both arrive in one check).
_ADJUST_TIMEOUT = 1.0
# Seconds in which a save without changes is not written again.
_SAVE_REPEAT_TIMEOUT = 5.0

# Property changes that are about the editor view, not the work.
_VIEW_PROPERTY_RE = re.compile(
    r"^bpy\.context\.(space_data|area|region)\."
    r"|^bpy\.data\.window_managers\["
    r"|^bpy\.data\.screens\["
)
# Property paths Blender can't resolve are printed empty, e.g. ``bpy.context. = True``.
_EMPTY_PROPERTY_RE = re.compile(r"^bpy\.\w+\.\s*=|\]\.\s*=")


def _prefs():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# -----------------------------------------------------------------------------
# Log File


class _State:
    __slots__ = (
        "last_uid",
        "log_dir",
        "events_pending",
        "held",
        "held_time",
        "session_open",
        "mode",
        "ops_since_shot",
        "shot_time",
        "shot_count",
        "shot_last",
        "save_time",
        "save_stats",
        "op_count",
        "start_time",
        "start_clock",
        "title",
    )

    def __init__(self):
        self.last_uid = 0
        # Folder of the current log, None while the file has never been saved.
        self.log_dir: str | None = None
        # Events of an unsaved file, written on its first save.
        self.events_pending: list[dict] = []
        # Events that may still change: a click counting repeats, an operator that may be
        # adjusted from the "Adjust Last Operation" panel and the undo step that comes with it.
        self.held: list[dict] = []
        self.held_time = 0.0
        self.session_open = False
        self.mode = ""
        self.ops_since_shot = 0
        self.shot_time = 0.0
        self.shot_count = 0
        # Name and content hash of the last screenshot, to skip identical ones.
        self.shot_last: tuple[str, str] | None = None
        self.save_time = 0.0
        self.save_stats: dict | None = None
        self.op_count = 0
        self.start_time = 0.0
        self.start_clock = ""
        self.title = ""


_state = _State()

# Upper limit for events kept in memory while the file is unsaved.
_PENDING_MAX = 20000


def _log_dir_from_blend(filepath: str) -> str:
    directory, name = os.path.split(filepath)
    return os.path.join(directory, os.path.splitext(name)[0] + "_history")


def _write(event: dict) -> None:
    if _state.log_dir is None:
        if len(_state.events_pending) < _PENDING_MAX:
            _state.events_pending.append(event)
        return
    try:
        with open(os.path.join(_state.log_dir, LOG_NAME), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as ex:
        print("Session Recorder: failed to write log:", ex)


def _held_flush() -> None:
    for event in _state.held:
        _write(event)
    _state.held.clear()


def _emit(event: dict) -> None:
    """
    Write an event, merging repeated clicks, repeated undo/redo
    and changes made in the "Adjust Last Operation" panel (F9).
    """
    held = _state.held
    now = time.monotonic()
    ev = event["ev"]
    op = event.get("op")
    last = held[-1] if held else None
    if ev in {"undo", "redo"}:
        if last is not None and last["ev"] == ev:
            last["n"] += 1
            last["t_end"] = event["t"]
        elif ev == "undo" and last is not None and last["ev"] == "op" and last.get("n") is None:
            # Might be the undo step of an adjustment, decided by the next event.
            held.append({**event, "n": 1})
        else:
            _held_flush()
            held.append({**event, "n": 1})
    elif ev == "op":
        if (
                len(held) == 2 and
                held[0]["ev"] == "op" and held[0]["op"] == op and
                held[1]["ev"] == "undo" and held[1]["n"] == 1 and
                now - _state.held_time < _ADJUST_TIMEOUT
        ):
            # Adjusting the last operation undoes it and runs it again with the new values.
            held.pop()
            held[0]["msg"] = event["msg"]
            held[0]["adjusted"] = held[0].get("adjusted", 0) + 1
            held[0]["t_end"] = event["t"]
        elif op in _COLLAPSE_OPS and last is not None and last.get("op") == op:
            last["n"] += 1
            last["t_end"] = event["t"]
        else:
            _held_flush()
            if op in _COLLAPSE_OPS:
                # The arguments of a single click (edge index ...) mean nothing on their own.
                event = {**event, "msg": op + "(...)", "n": 1}
            held.append(event)
    elif ev == "prop":
        path = event["msg"].partition(" = ")[0]
        if last is not None and last["ev"] == "prop" and last["msg"].partition(" = ")[0] == path:
            # Dragging or retyping the same value, keep the final one.
            last["msg"] = event["msg"]
            last["adjusted"] = last.get("adjusted", 0) + 1
            last["t_end"] = event["t"]
        else:
            _held_flush()
            held.append(event)
    else:
        _held_flush()
        _write(event)
        return
    _state.held_time = now


def _log_open(filepath: str) -> None:
    """
    Start writing to the log of ``filepath``, creating it when needed.
    """
    log_dir = _log_dir_from_blend(filepath)
    os.makedirs(os.path.join(log_dir, SHOTS_DIR), exist_ok=True)
    is_new = not os.path.exists(os.path.join(log_dir, LOG_NAME))
    _state.log_dir = log_dir
    _state.shot_last = None
    _state.shot_count = len([f for f in os.listdir(os.path.join(log_dir, SHOTS_DIR)) if f.endswith(".png")])
    if is_new:
        _write({"t": _now(), "ev": "log_created", "file": filepath, "id": _file_id()})


def _file_id() -> str | None:
    scene = bpy.data.scenes[0] if bpy.data.scenes else None
    return scene.get(ID_KEY) if scene is not None else None


def _session_begin(title: str = "") -> None:
    if _state.session_open:
        return
    _state.session_open = True
    _state.mode = ""
    _state.op_count = 0
    _state.start_time = time.monotonic()
    _state.start_clock = time.strftime("%H:%M")
    _state.title = title
    reports = bpy.context.window_manager.reports
    # Reports from before the session are skipped.
    _state.last_uid = reports[-1].session_uid if len(reports) else 0
    filepath = bpy.data.filepath
    _state.log_dir = None
    if filepath:
        _log_open(filepath)
    event = {
        "t": _now(),
        "ev": "session_start",
        "file": filepath or None,
        "id": _file_id(),
        "blender": bpy.app.version_string,
    }
    if title:
        event["title"] = title
    _emit(event)
    _ui_redraw()


def _session_end(reason: str, comment: str = "") -> None:
    """
    :arg reason: ``"stop"`` (stopped by the user), ``"file"`` (another file was opened),
       ``"exit"`` (Blender quit) or ``"disabled"`` (add-on disabled or updated).
    """
    if not _state.session_open:
        return
    _poll_reports()
    event = {
        "t": _now(),
        "ev": "session_end",
        "reason": reason,
        "ops": _state.op_count,
        "minutes": round((time.monotonic() - _state.start_time) / 60.0, 1),
    }
    if comment:
        event["comment"] = comment
    _emit(event)
    _held_flush()
    if _state.log_dir is None and len(_state.events_pending) > 1:
        # Never saved, keep the events in the add-on's own folder.
        try:
            directory = bpy.utils.extension_path_user(__package__, path="unsaved", create=True)
            filepath = os.path.join(directory, time.strftime("%Y%m%d-%H%M%S") + ".jsonl")
            with open(filepath, "w", encoding="utf-8") as fh:
                for event in _state.events_pending:
                    fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except (OSError, ValueError) as ex:
            print("Session Recorder: failed to keep unsaved log:", ex)
    _state.events_pending.clear()
    _state.session_open = False
    _ui_redraw()


def _ui_redraw() -> None:
    """
    Redraw the status bar and the sidebar panel, they don't update on their own.
    """
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type in {"STATUSBAR", "VIEW_3D"}:
                area.tag_redraw()


# -----------------------------------------------------------------------------
# Reports


def _report_to_event(report_type: str, message: str, prefs) -> dict | None:
    context = bpy.context
    event = {"t": _now()}
    if report_type == "OPERATOR":
        event["ev"] = "op"
        event["op"] = op_idname(message)
        event["msg"] = op_call_compact(message)
    elif report_type == "PROPERTY":
        if _EMPTY_PROPERTY_RE.search(message):
            return None
        if _VIEW_PROPERTY_RE.search(message) and not (prefs and prefs.record_view_changes):
            return None
        event["ev"] = "prop"
        event["msg"] = message
    elif report_type == "INFO":
        # Saves are written by the save handler, with more detail.
        if message.startswith("Saved \""):
            return None
        event["ev"] = "info"
        event["msg"] = message
    elif report_type.startswith("ERROR") or report_type == "WARNING":
        event["ev"] = "error"
        event["level"] = report_type
        event["msg"] = message
    else:
        return None
    event["mode"] = context.mode
    obj = context.view_layer.objects.active if context.view_layer else None
    event["obj"] = obj.name if obj else None
    return event


def _poll_reports() -> int:
    """
    Write the reports added since the last call, return the number of operators.
    """
    reports = bpy.context.window_manager.reports
    if not len(reports):
        return 0
    if reports[-1].session_uid < _state.last_uid:
        # The report list was replaced (e.g. by loading a file with its UI), start over from here.
        _state.last_uid = reports[-1].session_uid
        return 0
    new = []
    for i in range(len(reports) - 1, -1, -1):
        report = reports[i]
        if report.session_uid <= _state.last_uid:
            break
        new.append((report.type, report.message))
    if not new:
        return 0
    _state.last_uid = reports[-1].session_uid
    prefs = _prefs()
    ops = 0
    for report_type, message in reversed(new):
        event = _report_to_event(report_type, message, prefs)
        if event is None:
            continue
        if event["ev"] == "op":
            ops += 1
        _emit(event)
    _state.op_count += ops
    return ops


# -----------------------------------------------------------------------------
# Screenshots


def _view3d_largest():
    best = None
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            if best is None or area.width * area.height > best[1].width * best[1].height:
                best = (window, area)
    return best


def _shot(reason: str) -> None:
    if _state.log_dir is None:
        return
    found = _view3d_largest()
    if found is None:
        return
    window, area = found
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    _state.shot_count += 1
    name = "{:04d}.png".format(_state.shot_count)
    filepath = os.path.join(_state.log_dir, SHOTS_DIR, name)
    try:
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.screen.screenshot_area(filepath=filepath, check_existing=False)
    except (RuntimeError, TypeError) as ex:
        print("Session Recorder: screenshot failed:", ex)
        _state.shot_count -= 1
        return
    _state.shot_time = time.monotonic()
    _state.ops_since_shot = 0
    try:
        with open(filepath, "rb") as fh:
            digest = hashlib.sha1(fh.read()).hexdigest()
    except OSError:
        return
    if _state.shot_last is not None and _state.shot_last[1] == digest:
        # Nothing changed on screen, point to the existing screenshot instead.
        os.remove(filepath)
        _state.shot_count -= 1
        if reason != "note":
            return
        name = _state.shot_last[0]
    _state.shot_last = (name, digest)
    _emit({"t": _now(), "ev": "shot", "file": SHOTS_DIR + "/" + name, "why": reason})


def _shot_deferred(reason: str) -> None:
    # Handlers and dialogs aren't a good place for operators, take the screenshot from a timer.
    bpy.app.timers.register(lambda: _shot(reason), first_interval=0.2)


def _shot_auto(mode_changed: bool, prefs) -> None:
    if time.monotonic() - _state.shot_time < prefs.shot_min_interval:
        return
    if mode_changed and prefs.shot_on_mode_change:
        _shot("mode")
    elif prefs.shot_every_ops and _state.ops_since_shot >= prefs.shot_every_ops:
        _shot("ops")


# -----------------------------------------------------------------------------
# Timer


def _tick() -> float:
    prefs = _prefs()
    if prefs is None:
        return None  # Add-on disabled.
    interval = prefs.poll_interval
    if not _state.session_open:
        return interval
    try:
        ops = _poll_reports()
        _state.ops_since_shot += ops
        if ops:
            _ui_redraw()
        # Write merged clicks and undo/redo once they stop repeating. A single operator or property
        # change stays held until the next event, it can still be adjusted (F9) at any time.
        if (
                any("n" in event for event in _state.held) and
                time.monotonic() - _state.held_time > _HELD_TIMEOUT
        ):
            _held_flush()
        mode = bpy.context.mode
        mode_changed = bool(_state.mode) and mode != _state.mode
        _state.mode = mode
        if mode_changed or ops:
            _shot_auto(mode_changed, prefs)
    except Exception as ex:  # pylint: disable=broad-except
        # Keep the timer alive, a single failure must not stop the recording.
        print("Session Recorder: error:", ex)
    return interval


def _auto_start() -> None:
    prefs = _prefs()
    if prefs is not None and prefs.auto_start:
        _session_begin()
    return None


# -----------------------------------------------------------------------------
# Handlers


@persistent
def _on_load_pre(*_args) -> None:
    _session_end("file")


@persistent
def _on_load_post(*_args) -> None:
    _auto_start()


@persistent
def _on_save_pre(*_args) -> None:
    scene = bpy.data.scenes[0] if bpy.data.scenes else None
    if scene is not None and ID_KEY not in scene:
        scene[ID_KEY] = uuid.uuid4().hex


@persistent
def _on_save_post(*_args) -> None:
    if not _state.session_open:
        return
    filepath = bpy.data.filepath
    _poll_reports()
    _held_flush()
    log_dir_new = _log_dir_from_blend(filepath)
    if _state.log_dir != log_dir_new:
        # First save, or "Save As" under a new name.
        log_dir_old = _state.log_dir
        pending = list(_state.events_pending)
        _state.events_pending.clear()
        _log_open(filepath)
        if log_dir_old is not None:
            _write({"t": _now(), "ev": "continued_from", "log": os.path.join(log_dir_old, LOG_NAME)})
        for event in pending:
            _write(event)
    stats = _stats()
    now = time.monotonic()
    if stats == _state.save_stats and now - _state.save_time < _SAVE_REPEAT_TIMEOUT:
        # The same save again (e.g. Ctrl+S pressed twice).
        return
    _state.save_time = now
    _state.save_stats = stats
    _write({"t": _now(), "ev": "save", "file": os.path.basename(filepath), "id": _file_id(), "stats": stats})
    prefs = _prefs()
    if prefs and prefs.shot_on_save and now - _state.shot_time >= prefs.shot_min_interval:
        _shot_deferred("save")


@persistent
def _on_undo_post(*_args) -> None:
    if _state.session_open:
        _poll_reports()
        _emit({"t": _now(), "ev": "undo", "mode": bpy.context.mode})


@persistent
def _on_redo_post(*_args) -> None:
    if _state.session_open:
        _poll_reports()
        _emit({"t": _now(), "ev": "redo", "mode": bpy.context.mode})


@persistent
def _on_exit_pre(*_args) -> None:
    _session_end("exit")


def _stats() -> dict:
    """
    Mesh sizes and modifier stacks, to follow how the model grows.
    """
    objects = []
    verts = faces = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        verts += len(mesh.vertices)
        faces += len(mesh.polygons)
        if len(objects) < 40:
            objects.append({
                "name": obj.name,
                "verts": len(mesh.vertices),
                "faces": len(mesh.polygons),
                "mods": [mod.type for mod in obj.modifiers],
            })
    return {"objects": len(bpy.data.objects), "verts": verts, "faces": faces, "meshes": objects}


_handlers = (
    (bpy.app.handlers.load_pre, _on_load_pre),
    (bpy.app.handlers.load_post, _on_load_post),
    (bpy.app.handlers.save_pre, _on_save_pre),
    (bpy.app.handlers.save_post, _on_save_post),
    (bpy.app.handlers.undo_post, _on_undo_post),
    (bpy.app.handlers.redo_post, _on_redo_post),
    (bpy.app.handlers.exit_pre, _on_exit_pre),
)


# -----------------------------------------------------------------------------
# Operators


class SESSION_RECORDER_OT_start(bpy.types.Operator):
    """Start writing what you do to the log next to the .blend file"""

    bl_idname = "session_recorder.start"
    bl_label = "Start Recording"

    title: StringProperty(  # type: ignore[valid-type]
        name="Title",
        description="What this session is about (optional), e.g. the tutorial name",
    )

    @classmethod
    def poll(cls, _context):
        return not _state.session_open

    def invoke(self, context, _event):
        self.title = ""
        return context.window_manager.invoke_props_dialog(
            self, width=420, title="Start Recording", confirm_text="Start",
        )

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "title")
        if not bpy.data.filepath:
            layout.label(text="File not saved yet, the log is written on the first save", icon="INFO")

    def execute(self, _context):
        _session_begin(self.title.strip())
        _shot_deferred("start")
        return {"FINISHED"}


class SESSION_RECORDER_OT_stop(bpy.types.Operator):
    """Stop recording, with a comment about the session"""

    bl_idname = "session_recorder.stop"
    bl_label = "Stop Recording"

    comment: StringProperty(  # type: ignore[valid-type]
        name="Comment",
        description="How the session went, what to try next ... (optional)",
    )

    @classmethod
    def poll(cls, _context):
        return _state.session_open

    def invoke(self, context, _event):
        self.comment = ""
        return context.window_manager.invoke_props_dialog(
            self, width=480, title="Stop Recording", confirm_text="Stop",
        )

    def draw(self, _context):
        layout = self.layout
        minutes = (time.monotonic() - _state.start_time) / 60.0
        layout.label(
            text="{:d} actions in {:.0f} min, since {:s}".format(_state.op_count, minutes, _state.start_clock),
            icon="REC",
        )
        layout.prop(self, "comment")
        if _state.log_dir is None:
            layout.label(text="File not saved, the log is kept in the add-on folder", icon="ERROR")

    def execute(self, _context):
        comment = self.comment.strip()

        # Take the last screenshot once the dialog is closed, then end the session.
        def stop():
            _shot("stop")
            _session_end("stop", comment)

        bpy.app.timers.register(stop, first_interval=0.2)
        return {"FINISHED"}


class SESSION_RECORDER_OT_note(bpy.types.Operator):
    """Write a note to the session log, with a screenshot of the 3D viewport"""

    bl_idname = "session_recorder.note"
    bl_label = "Add Note"

    text: StringProperty(  # type: ignore[valid-type]
        name="Note",
        description="Why you did something, what went wrong, a tutorial timestamp ...",
    )

    @classmethod
    def poll(cls, _context):
        return _state.session_open

    def invoke(self, context, _event):
        self.text = ""
        return context.window_manager.invoke_props_dialog(self, width=480, title="Add Note", confirm_text="Add")

    def execute(self, _context):
        if not self.text.strip():
            return {"CANCELLED"}
        _poll_reports()
        _emit({"t": _now(), "ev": "note", "text": self.text.strip(), "mode": bpy.context.mode})
        if _state.log_dir is not None:
            _shot_deferred("note")
        else:
            self.report({"INFO"}, "Note kept, it's written to the log when the file is saved")
        return {"FINISHED"}


class SESSION_RECORDER_OT_open_folder(bpy.types.Operator):
    """Open the folder with the log and screenshots of this file"""

    bl_idname = "session_recorder.open_folder"
    bl_label = "Open History Folder"

    @classmethod
    def poll(cls, _context):
        return bool(bpy.data.filepath)

    def execute(self, _context):
        log_dir = _log_dir_from_blend(bpy.data.filepath)
        if not os.path.isdir(log_dir):
            self.report({"WARNING"}, "No recording for this file yet")
            return {"CANCELLED"}
        bpy.ops.wm.path_open(filepath=log_dir)
        return {"FINISHED"}


# -----------------------------------------------------------------------------
# Status Bar


def _statusbar_draw(self, _context) -> None:
    prefs = _prefs()
    if prefs is None or not prefs.show_status or not _state.session_open:
        return
    text = "REC {:d}".format(_state.op_count)
    if _state.log_dir is None:
        text += " (not saved yet)"
    self.layout.label(text=text, icon="REC")


# -----------------------------------------------------------------------------
# Sidebar Panel


class VIEW3D_PT_session_recorder(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Recorder"
    bl_label = "Session Recorder"

    def draw(self, _context):
        layout = self.layout
        if not _state.session_open:
            col = layout.column()
            col.scale_y = 1.5
            col.operator(SESSION_RECORDER_OT_start.bl_idname, icon="REC")
            if not bpy.data.filepath:
                layout.label(text="Save the file to keep the log next to it", icon="INFO")
        else:
            box = layout.box()
            col = box.column(align=True)
            col.label(text="Recording since " + _state.start_clock, icon="REC")
            if _state.title:
                col.label(text=_state.title)
            col.label(text="{:d} actions".format(_state.op_count))
            if _state.log_dir is None:
                col.label(text="Not saved yet, saved on first save", icon="INFO")

            row = layout.row()
            row.operator(SESSION_RECORDER_OT_note.bl_idname, icon="TEXT")
            shortcut = _keymap_note_find()
            if shortcut is not None and shortcut.active:
                row.label(text=shortcut.to_string())

            col = layout.column()
            col.scale_y = 1.2
            col.operator(SESSION_RECORDER_OT_stop.bl_idname, icon="X")

        layout.operator(SESSION_RECORDER_OT_open_folder.bl_idname, icon="FILE_FOLDER")


class VIEW3D_PT_session_recorder_settings(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Recorder"
    bl_label = "Settings"
    bl_parent_id = "VIEW3D_PT_session_recorder"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        prefs = _prefs()
        if prefs is not None:
            _prefs_draw(prefs, context, self.layout)


# -----------------------------------------------------------------------------
# Preferences


class _SessionRecorderPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    auto_start: BoolProperty(  # type: ignore[valid-type]
        name="Start Automatically",
        description="Start recording whenever a file is opened, instead of with the Start button",
        default=False,
    )
    poll_interval: FloatProperty(  # type: ignore[valid-type]
        name="Check Interval",
        description="Seconds between checks for new actions, shorter gives a more exact mode and time",
        default=0.25,
        min=0.1,
        max=5.0,
        subtype="TIME_ABSOLUTE",
        unit="TIME_ABSOLUTE",
    )
    shot_on_save: BoolProperty(  # type: ignore[valid-type]
        name="On Save",
        description="Take a screenshot of the 3D viewport on every save",
        default=True,
    )
    shot_on_mode_change: BoolProperty(  # type: ignore[valid-type]
        name="On Mode Change",
        description="Take a screenshot when switching between Object, Edit, Sculpt ... mode",
        default=True,
    )
    shot_every_ops: IntProperty(  # type: ignore[valid-type]
        name="Every N Actions",
        description="Take a screenshot after this many actions (0 to disable)",
        default=30,
        min=0,
        max=1000,
    )
    shot_min_interval: FloatProperty(  # type: ignore[valid-type]
        name="Minimum Gap",
        description="Seconds between automatic screenshots, also on save (start, stop and notes always take one)",
        default=60.0,
        min=0.0,
        max=3600.0,
        subtype="TIME_ABSOLUTE",
        unit="TIME_ABSOLUTE",
    )
    record_view_changes: BoolProperty(  # type: ignore[valid-type]
        name="Record View Changes",
        description="Also record editor settings such as shading type and overlays",
        default=False,
    )
    show_status: BoolProperty(  # type: ignore[valid-type]
        name="Show in Status Bar",
        description="Show \"REC\" and the number of actions in the status bar while recording",
        default=True,
    )

    def draw(self, context):
        _prefs_draw(self, context, self.layout)


def _prefs_draw(prefs, context, layout) -> None:
    """
    Shared by the add-on preferences and the sidebar "Settings" panel.
    """
    layout.use_property_split = True
    layout.use_property_decorate = False

    layout.label(text="Note Shortcut:")
    _keymap_draw(context, layout)

    col = layout.column(heading="Recording")
    col.prop(prefs, "auto_start")
    col.prop(prefs, "record_view_changes")
    col.prop(prefs, "show_status")
    col.prop(prefs, "poll_interval")

    col = layout.column(heading="Screenshots")
    col.prop(prefs, "shot_on_save")
    col.prop(prefs, "shot_on_mode_change")
    col.prop(prefs, "shot_every_ops")
    col.prop(prefs, "shot_min_interval")


# -----------------------------------------------------------------------------
# Keymap

_keymap_items: list[tuple[bpy.types.KeyMap, bpy.types.KeyMapItem]] = []


def _keymap_register() -> None:
    # The add-on key configuration is None in background mode.
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.new(name="Window", space_type="EMPTY")
    kmi = km.keymap_items.new(SESSION_RECORDER_OT_note.bl_idname, "N", "PRESS", ctrl=True, alt=True)
    _keymap_items.append((km, kmi))


def _keymap_note_find():
    """
    Return the note shortcut of the user key configuration (where changes are stored), or None.
    """
    kc = bpy.context.window_manager.keyconfigs.user
    km = kc.keymaps.get("Window")
    if km is None:
        return None
    return next((item for item in km.keymap_items if item.idname == SESSION_RECORDER_OT_note.bl_idname), None)


def _keymap_draw(context: bpy.types.Context, layout: bpy.types.UILayout) -> None:
    import rna_keymap_ui  # pylint: disable=import-error

    kmi = _keymap_note_find()
    if kmi is None:
        layout.label(text="Shortcut not found, re-enable the add-on to restore it", icon="ERROR")
        return
    kc = context.window_manager.keyconfigs.user
    rna_keymap_ui.draw_kmi([], kc, kc.keymaps["Window"], kmi, layout, 0)


def _keymap_unregister() -> None:
    for km, kmi in _keymap_items:
        km.keymap_items.remove(kmi)
    _keymap_items.clear()


# -----------------------------------------------------------------------------
# Registration

_classes = (
    _SessionRecorderPreferences,
    SESSION_RECORDER_OT_start,
    SESSION_RECORDER_OT_stop,
    SESSION_RECORDER_OT_note,
    SESSION_RECORDER_OT_open_folder,
    VIEW3D_PT_session_recorder,
    VIEW3D_PT_session_recorder_settings,
)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)
    for handler_list, fn in _handlers:
        handler_list.append(fn)
    _keymap_register()
    bpy.types.STATUSBAR_HT_header.append(_statusbar_draw)
    bpy.app.timers.register(_tick, first_interval=0.5, persistent=True)
    # With "Start Automatically", the "load_post" handler starts recording at startup,
    # when the add-on is enabled later on there is no file load, so check from a timer.
    bpy.app.timers.register(_auto_start, first_interval=0.3)


def unregister() -> None:
    _session_end("disabled")
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    if bpy.app.timers.is_registered(_auto_start):
        bpy.app.timers.unregister(_auto_start)
    bpy.types.STATUSBAR_HT_header.remove(_statusbar_draw)
    _keymap_unregister()
    for handler_list, fn in _handlers:
        if fn in handler_list:
            handler_list.remove(fn)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
