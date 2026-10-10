# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shortens the operator calls shown in the Info editor.

The Info editor prints every operator argument, most of them defaults
(snapping, proportional editing, orientation matrices ...).
Only the arguments that tell what was done are kept.
No ``bpy`` import, so this can be tested outside of Blender.
"""

__all__ = (
    "op_call_compact",
    "op_idname",
)

import re

# Arguments that are dropped whatever their value.
_NOISE_KEYS = frozenset((
    "align",
    "constraint_axis",
    "correct_uv",
    "enter_editmode",
    "falloff",
    "mesh_select_mode_init",
    # Mirror state of the transform (set after adjusting an operator), not mirror editing.
    "mirror",
    "object_index",
    "orient_matrix",
    "orient_matrix_type",
    "proportional_edit_falloff",
    "proportional_size",
    "release_confirm",
    "snap_elements",
    "snap_point",
    "snap_target",
    "use_accurate",
    "use_dissolve_ortho_edges",
    "use_normal_flip",
    "use_proportional_connected",
    "use_proportional_projected",
    "use_snap_edit",
    "use_snap_nonedit",
    "use_snap_project",
    "use_snap_selectable",
    "use_snap_self",
))

# Arguments that are dropped when they have this (default) value.
_DEFAULTS = {
    "flipped": "False",
    "location": "(0, 0, 0)",
    "offset_pct": "0",
    "orient_type": "'GLOBAL'",
    "rotation": "(0, 0, 0)",
    "scale": "(1, 1, 1)",
    "single_side": "False",
    "smoothness": "0",
    "snap": "False",
    "use_clamp": "True",
    "use_even": "False",
    "use_even_offset": "False",
    "use_proportional_edit": "False",
}

_OP_CALL_RE = re.compile(r"^bpy\.ops\.(\w+\.\w+)\((.*)\)$", re.DOTALL)


def op_idname(message: str) -> str | None:
    """
    Return ``"mesh.bevel"`` for ``"bpy.ops.mesh.bevel(...)"``, None when the message isn't an operator call.
    """
    match = _OP_CALL_RE.match(message)
    return match.group(1) if match else None


def _split_top_level(text: str) -> list[str]:
    """
    Split on commas that aren't inside brackets or quotes.
    """
    parts = []
    depth = 0
    quote = ""
    start = 0
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _keep(key: str, value: str) -> bool:
    if key in _NOISE_KEYS:
        return False
    return _DEFAULTS.get(key) != value


def _macro_compact(value: str) -> str:
    """
    Compact the ``{"key":value, ...}`` arguments of a macro operator step.
    """
    items = []
    for item in _split_top_level(value[1:-1]):
        key, sep, val = item.partition(":")
        key = key.strip().strip("\"'")
        if sep and _keep(key, val.strip()):
            items.append("{:s}={:s}".format(key, val.strip()))
    return "{" + ", ".join(items) + "}" if items else ""


def op_call_compact(message: str) -> str:
    """
    Return the operator call with only the meaningful arguments,
    ``message`` is returned unchanged when it isn't an operator call.
    """
    match = _OP_CALL_RE.match(message)
    if match is None:
        return message
    idname, args_text = match.groups()
    args = []
    for arg in _split_top_level(args_text):
        key, sep, value = arg.partition("=")
        if not sep:
            args.append(arg)
            continue
        key = key.strip()
        value = value.strip()
        # Macro operators pass each step's arguments as a dict, e.g. ``MESH_OT_loopcut={...}``.
        if "_OT_" in key and value.startswith("{"):
            value = _macro_compact(value)
            if value:
                args.append("{:s}={:s}".format(key, value))
        elif _keep(key, value):
            args.append("{:s}={:s}".format(key, value))
    return "{:s}({:s})".format(idname, ", ".join(args))
