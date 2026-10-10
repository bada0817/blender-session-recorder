# SPDX-License-Identifier: GPL-3.0-or-later

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compact import op_call_compact, op_idname  # noqa: E402


class TestCompact(unittest.TestCase):

    def test_idname(self):
        self.assertEqual(op_idname("bpy.ops.mesh.bevel(offset=1)"), "mesh.bevel")
        self.assertIsNone(op_idname("Saved \"a.blend\""))

    def test_not_an_operator(self):
        self.assertEqual(op_call_compact("bpy.context.object.name = 'A'"), "bpy.context.object.name = 'A'")

    def test_transform_defaults_dropped(self):
        msg = (
            "bpy.ops.transform.rotate(value=3.75246, orient_axis='X', orient_type='GLOBAL', "
            "orient_matrix=((1, 0, 0), (0, 1, 0), (0, 0, 1)), orient_matrix_type='GLOBAL', "
            "constraint_axis=(True, False, False), mirror=False, use_proportional_edit=False, "
            "snap=False, snap_elements={'INCREMENT'}, use_snap_self=True)"
        )
        self.assertEqual(op_call_compact(msg), "transform.rotate(value=3.75246, orient_axis='X')")

    def test_non_default_kept(self):
        msg = "bpy.ops.transform.translate(value=(0, 0, 1), mirror=True, orient_type='LOCAL')"
        self.assertEqual(op_call_compact(msg), "transform.translate(value=(0, 0, 1), mirror=True, orient_type='LOCAL')")

    def test_macro(self):
        msg = (
            "bpy.ops.mesh.loopcut_slide(MESH_OT_loopcut={\"number_cuts\":3, \"smoothness\":0, "
            "\"falloff\":'INVERSE_SQUARE', \"object_index\":0, \"edge_index\":5}, "
            "TRANSFORM_OT_edge_slide={\"value\":0, \"single_side\":False, \"use_clamp\":True})"
        )
        self.assertEqual(
            op_call_compact(msg),
            "mesh.loopcut_slide(MESH_OT_loopcut={number_cuts=3, edge_index=5}, TRANSFORM_OT_edge_slide={value=0})",
        )

    def test_macro_all_defaults_dropped(self):
        msg = "bpy.ops.mesh.extrude_region_move(MESH_OT_extrude_region={\"use_normal_flip\":False}, TRANSFORM_OT_translate={\"value\":(0, 0, 1)})"
        self.assertEqual(op_call_compact(msg), "mesh.extrude_region_move(TRANSFORM_OT_translate={value=(0, 0, 1)})")

    def test_quoted_comma(self):
        msg = "bpy.ops.object.rename(name='a, b', mirror=False)"
        self.assertEqual(op_call_compact(msg), "object.rename(name='a, b')")


if __name__ == "__main__":
    unittest.main()
