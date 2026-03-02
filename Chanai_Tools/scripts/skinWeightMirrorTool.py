# -*- coding: utf-8 -*-
import io

"""Maya skin weight mirror tool (partial selection).



Bundled with ADV Fast Select.



Usage in Maya Script Editor (Python):

    import skinWeightMirrorTool as swm

    swm.show()

"""




import math

import re

import os

import json

try:
    from typing import Dict, List, Tuple
except Exception:
    # Maya 2020 (Python 2.7) may not ship typing.
    Dict = List = Tuple = object

from contextlib import contextmanager



import maya.cmds as cmds

import maya.mel as mel



try:

    import maya.api.OpenMaya as om2

    import maya.api.OpenMayaAnim as oma2

except Exception:

    om2 = None

    oma2 = None



try:

    import maya.utils as mutils

except Exception:

    mutils = None





# Qt (PySide2/6) optional UI

try:

    from PySide2 import QtCore, QtWidgets

    from shiboken2 import wrapInstance

except ImportError:

    try:

        from PySide6 import QtCore, QtWidgets

        from shiboken6 import wrapInstance

    except ImportError:

        QtCore = None

        QtWidgets = None

        wrapInstance = None



try:

    import maya.OpenMayaUI as omui

except Exception:

    omui = None





def _swm_make_double_spinbox():

    """Create a QDoubleSpinBox that displays without unnecessary trailing zeros."""

    if QtWidgets is None:

        return None



    try:

        class _SwmTrimDoubleSpinBox(QtWidgets.QDoubleSpinBox):

            def textFromValue(self, value):

                # Base class always pads to `decimals()`. Trim for cleaner UI: 0.010 -> 0.01

                try:

                    s = super(_SwmTrimDoubleSpinBox, self).textFromValue(value)

                except Exception:

                    s = ("%.*f" % (int(self.decimals()), float(value)))

                try:

                    dp = self.locale().decimalPoint()

                except Exception:

                    dp = "."

                if dp in s:

                    s = s.rstrip("0").rstrip(dp)

                return s



        return _SwmTrimDoubleSpinBox()

    except Exception:

        # Fallback to a normal spinbox if subclassing fails in a given Maya/Qt build.

        return QtWidgets.QDoubleSpinBox()





WINDOW_NAME = "chanaiToolsSkinWeightMirrorUI"



# Visible marker to confirm which version is loaded in Maya.

_SWM_QT_BUILD = "2026-02-11a"



# When user clicks an influence in our UI list, we cache it so weight edit

# operations (add/sub/smooth) still work even if Maya paint context isn't active.

_LAST_UI_SELECTED_INFLUENCE = [""]





# ---------------- Joint transfer (export/import) ----------------



_JT_DEFAULT_FILENAME = "chanai_tools_joint_transfer.json"





def _jt_default_path()       :

    try:

        base = cmds.internalVar(userAppDir=True) or ""

    except Exception:

        base = ""

    if not base:

        base = os.path.expanduser("~")

    return os.path.join(base, _JT_DEFAULT_FILENAME)





def _jt_file_dialog_save(start_path     )              :

    try:

        res = cmds.fileDialog2(

            fileMode=0,

            caption=u"Export Joint Data (JSON)",

            startingDirectory=os.path.dirname(start_path),

            fileFilter=u"JSON Files (*.json)",

        )

        return res[0] if res else None

    except Exception:

        return None





def _jt_file_dialog_open(start_path     )              :

    try:

        res = cmds.fileDialog2(

            fileMode=1,

            caption=u"Import Joint Data (JSON)",

            startingDirectory=os.path.dirname(start_path),

            fileFilter=u"JSON Files (*.json)",

        )

        return res[0] if res else None

    except Exception:

        return None





def _jt_is_joint(n     )        :

    try:

        return cmds.nodeType(n) == "joint"

    except Exception:

        return False





def _jt_long(n     )       :

    try:

        return (cmds.ls(n, l=True) or [n])[0]

    except Exception:

        return n





def _jt_leaf(n     )       :

    return str(n).split("|")[-1]





def _jt_gather_selected_roots()             :

    sel = cmds.ls(sl=True, l=True) or []

    joints = [s for s in sel if _jt_is_joint(s)]

    if not joints:

        return []

    roots = []

    seen = set()

    for j in joints:

        r = j

        try:

            while True:

                p = cmds.listRelatives(r, p=True, f=True) or []

                if not p or not _jt_is_joint(p[0]):

                    break

                r = p[0]

        except Exception:

            pass

        r = _jt_long(r)

        if r in seen:

            continue

        seen.add(r)

        roots.append(r)

    return roots





def _jt_walk_desc_joints(root     )             :

    out = [_jt_long(root)]

    kids = cmds.listRelatives(root, ad=True, f=True) or []

    kids = list(reversed(kids))  # parent-first

    for k in kids:

        if _jt_is_joint(k):

            out.append(_jt_long(k))

    seen = set()

    uniq = []

    for j in out:

        if j in seen:

            continue

        seen.add(j)

        uniq.append(j)

    return uniq





def _jt_get_world_matrix(node     )               :

    try:

        m = cmds.xform(node, q=True, ws=True, m=True)

        return [float(x) for x in (m or [])]

    except Exception:

        return []





def _jt_safe_get_attr(node     , attr     , default=None):

    try:

        return cmds.getAttr(node + "." + attr)

    except Exception:

        return default





def _jt_safe_get_attr3(node     , attr     , default=(0.0, 0.0, 0.0)):

    v = _jt_safe_get_attr(node, attr, default=None)

    try:

        if isinstance(v, (list, tuple)) and v and isinstance(v[0], (list, tuple)):

            v = v[0]

        if isinstance(v, (list, tuple)) and len(v) >= 3:

            return (float(v[0]), float(v[1]), float(v[2]))

    except Exception:

        pass

    return tuple(default)





def _jt_unique_name(base     )       :

    if not base:

        base = "joint"

    if not cmds.objExists(base):

        return base

    i = 1

    while True:

        cand = "%s_%d" % (base, i)

        if not cmds.objExists(cand):

            return cand

        i += 1





def export_selected_joints_json(path             = None)              :

    """Export selected joints (roots + descendants) to JSON."""

    roots = _jt_gather_selected_roots()

    if not roots:

        cmds.warning(u"请先选择骨骼(joint)。建议选择骨架根骨。")

        return None



    all_joints            = []

    for r in roots:

        all_joints.extend(_jt_walk_desc_joints(r))

    export_set = set(all_joints)



    joints_data = []

    for j in all_joints:

        parent = None

        try:

            p = cmds.listRelatives(j, p=True, f=True) or []

            if p and _jt_is_joint(p[0]) and (p[0] in export_set):

                parent = _jt_long(p[0])

        except Exception:

            parent = None



        joints_data.append(

            {

                "name": _jt_leaf(j),

                "long": _jt_long(j),

                "parentLong": parent,

                "rotateOrder": int(_jt_safe_get_attr(j, "rotateOrder", 0) or 0),

                "jointOrient": list(_jt_safe_get_attr3(j, "jointOrient")),

                "rotateAxis": list(_jt_safe_get_attr3(j, "rotateAxis")),

                "segmentScaleCompensate": int(_jt_safe_get_attr(j, "segmentScaleCompensate", 1) or 0),

                "radius": float((_jt_safe_get_attr(j, "radius", 1.0) or 1.0)),

                "preferredAngle": list(_jt_safe_get_attr3(j, "preferredAngle")),

                "worldMatrix": _jt_get_world_matrix(j),

            }

        )



    payload = {

        "version": 1,

        "scene": str(cmds.file(q=True, sn=True) or ""),

        "roots": [_jt_long(r) for r in roots],

        "joints": joints_data,

    }



    if not path:

        start = _jt_default_path()

        picked = _jt_file_dialog_save(start)

        if not picked:

            return None

        path = picked



    try:

        folder = os.path.dirname(path)

        if folder and not os.path.isdir(folder):

            os.makedirs(folder)

    except Exception:

        pass



    try:

        try:
            with io.open(path, 'w', encoding='utf-8') as f:
    
                json.dump(payload, f, ensure_ascii=False, indent=2)
    
        except TypeError:
            with open(path, 'w') as f:
    
                json.dump(payload, f, ensure_ascii=False, indent=2)
    
    except Exception as e:

        cmds.warning(u"导出失败: %s" % str(e))

        return None



    try:

        cmds.inViewMessage(amg=u"<hl>导出骨骼完成</hl>: %s" % path.replace('\\', '/'), pos="midCenter", fade=True)

    except Exception:

        pass

    return path





def import_joints_json(path             = None, select_new_roots       = True)             :

    """Import joints from JSON and rebuild hierarchy + world transforms."""

    if not path:

        start = _jt_default_path()

        picked = _jt_file_dialog_open(start)

        if not picked:

            return []

        path = picked



    if not os.path.isfile(path):

        cmds.warning(u"文件不存在: %s" % path)

        return []



    try:

        try:
            with io.open(path, 'r', encoding='utf-8') as f:
    
                payload = json.load(f)
    
        except TypeError:
            with open(path, 'r') as f:
    
                payload = json.load(f)
    
    except Exception as e:

        cmds.warning(u"读取失败: %s" % str(e))

        return []



    joints = payload.get("joints") or []

    if not joints:

        cmds.warning(u"文件里没有 joints 数据。")

        return []



    # Create all joints first. Store stable short names (long paths change after parenting).

    long_to_new                 = {}

    for jd in joints:

        old_long = str(jd.get("long") or "")

        base = str(jd.get("name") or _jt_leaf(old_long) or "joint")

        new_name = _jt_unique_name(base)

        j = None

        try:

            j = cmds.createNode("joint", name=new_name)

        except Exception:

            try:

                cmds.select(clear=True)

                j = cmds.joint(name=new_name)

            except Exception as e:

                cmds.warning(u"创建 joint 失败: %s" % str(e))

                continue



        long_to_new[old_long] = str(j)



        # attrs not depending on parenting

        try:

            cmds.setAttr(j + ".rotateOrder", int(jd.get("rotateOrder", 0) or 0))

        except Exception:

            pass

        try:

            jo = jd.get("jointOrient") or [0.0, 0.0, 0.0]

            cmds.setAttr(j + ".jointOrientX", float(jo[0]))

            cmds.setAttr(j + ".jointOrientY", float(jo[1]))

            cmds.setAttr(j + ".jointOrientZ", float(jo[2]))

        except Exception:

            pass

        try:

            ra = jd.get("rotateAxis") or [0.0, 0.0, 0.0]

            cmds.setAttr(j + ".rotateAxisX", float(ra[0]))

            cmds.setAttr(j + ".rotateAxisY", float(ra[1]))

            cmds.setAttr(j + ".rotateAxisZ", float(ra[2]))

        except Exception:

            pass

        try:

            cmds.setAttr(j + ".segmentScaleCompensate", int(jd.get("segmentScaleCompensate", 1) or 0))

        except Exception:

            pass

        try:

            cmds.setAttr(j + ".radius", float(jd.get("radius", 1.0) or 1.0))

        except Exception:

            pass



    # Parent according to original hierarchy

    for jd in joints:

        old_long = str(jd.get("long") or "")

        child_new = long_to_new.get(old_long)

        if not child_new:

            continue

        parent_old = jd.get("parentLong")

        if not parent_old:

            continue

        parent_new = long_to_new.get(str(parent_old))

        if not parent_new:

            continue

        try:

            cmds.parent(child_new, parent_new)

        except Exception:

            pass



    # Apply world matrices

    for jd in joints:

        old_long = str(jd.get("long") or "")

        new_j = long_to_new.get(old_long)

        if not new_j:

            continue

        m = jd.get("worldMatrix") or []

        if isinstance(m, list) and len(m) == 16:

            try:

                cmds.xform(new_j, ws=True, m=m)

            except Exception:

                pass

        try:

            pa = jd.get("preferredAngle") or [0.0, 0.0, 0.0]

            cmds.setAttr(new_j + ".preferredAngleX", float(pa[0]))

            cmds.setAttr(new_j + ".preferredAngleY", float(pa[1]))

            cmds.setAttr(new_j + ".preferredAngleZ", float(pa[2]))

        except Exception:

            pass



    new_roots = []

    for jd in joints:

        if jd.get("parentLong"):

            continue

        old_long = str(jd.get("long") or "")

        new_j = long_to_new.get(old_long)

        if new_j:

            new_roots.append(new_j)



    if select_new_roots and new_roots:

        try:

            cmds.select(new_roots, r=True)

        except Exception:

            pass



    try:

        cmds.inViewMessage(amg=u"<hl>导入骨骼完成</hl>: %d joints" % len(long_to_new), pos="midCenter", fade=True)

    except Exception:

        pass

    return new_roots





def _get_skin_cluster(mesh     )              :

    history = cmds.listHistory(mesh, pdo=True) or []

    skins = cmds.ls(history, type="skinCluster") or []

    return skins[0] if skins else None





def _om_dagpath(node     ):

    sel = om2.MSelectionList()

    sel.add(node)

    return sel.getDagPath(0)





def _om_depend_node(node     ):

    sel = om2.MSelectionList()

    sel.add(node)

    return sel.getDependNode(0)





def _om_skin_fn(skin     ):

    return oma2.MFnSkinCluster(_om_depend_node(skin))





def _get_mesh_from_selection()              :

    sel = cmds.ls(sl=True, long=True) or []

    if not sel:

        return None

    # Prefer component selection

    comp = sel[0]

    if ".vtx[" in comp:

        return comp.split(".vtx[")[0]

    return sel[0]





def _get_mesh_name_variants(mesh     )                  :

    mesh_long = (cmds.ls(mesh, long=True) or [mesh])[0]

    mesh_short = mesh_long.split("|")[-1]

    shape_long = ""

    shape_short = ""

    if cmds.nodeType(mesh_long) != "mesh":

        shapes = cmds.listRelatives(mesh_long, s=True, f=True) or []

        if shapes:

            shape_long = shapes[0]

            shape_short = shape_long.split("|")[-1]

    else:

        shape_long = mesh_long

        shape_short = mesh_short



    return {

        "mesh_long": mesh_long,

        "mesh_short": mesh_short,

        "shape_long": shape_long,

        "shape_short": shape_short,

    }





def _get_selected_vertices(mesh     )             :

    sel = cmds.ls(sl=True, fl=True, long=True) or []

    names = _get_mesh_name_variants(mesh)

    verts = []

    for s in sel:

        if ".vtx[" not in s:

            continue

        base = s.split(".vtx[")[0]

        base_short = base.split("|")[-1]

        if (

            base == names["mesh_long"]

            or base_short == names["mesh_short"]

            or base == names["shape_long"]

            or base_short == names["shape_short"]

        ):

            verts.append(s)

    result = []

    for v in verts:

        idx = int(v.split("[")[-1].rstrip("]"))

        result.append(idx)

    return sorted(set(result))





def _get_all_vertices(mesh     )             :

    count = cmds.polyEvaluate(mesh, v=True)

    return list(range(count))





def _get_mesh_shape(mesh     )       :

    if not mesh:

        return ""

    try:

        if cmds.nodeType(mesh) == "mesh":

            return mesh

    except Exception:

        pass

    try:

        shapes = cmds.listRelatives(mesh, s=True, ni=True, f=True) or []

    except Exception:

        shapes = []

    for s in shapes:

        try:

            if cmds.nodeType(s) == "mesh":

                return s

        except Exception:

            continue

    return ""





def _get_vertex_pos(mesh     , vid     )                              :

    pos = cmds.xform("{}.vtx[{}]".format(mesh, vid), q=True, ws=True, t=True)

    return float(pos[0]), float(pos[1]), float(pos[2])





def _mirror_pos(pos                            , axis     )                              :

    x, y, z = pos

    if axis == "X":

        return -x, y, z

    if axis == "Y":

        return x, -y, z

    return x, y, -z





def _distance(a                            , b                            )         :

    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)





# Many production meshes have unwelded border/seam vertices: multiple vertex IDs can

# share the exact same world position. If we only mirror to the single "closest" vertex,

# the other coincident vertices at that position will not receive mirrored weights.

_COINCIDENT_POS_TOL = 1.0e-6





def _pos_key(pos                            , tol        = _COINCIDENT_POS_TOL)                        :

    """Quantize a world-space point into a stable hash key."""

    if tol <= 0.0:

        tol = _COINCIDENT_POS_TOL

    return (

        int(round(pos[0] / tol)),

        int(round(pos[1] / tol)),

        int(round(pos[2] / tol)),

    )





def _build_vertex_kd(mesh     , vertices           )                                                :

    data = []

    for vid in vertices:

        data.append((vid, _get_vertex_pos(mesh, vid)))

    return data





def _find_closest_vertex(kd                                              , target_pos)       :

    best_vid = -1

    best_dist = 1e20

    for vid, pos in kd:

        d = _distance(pos, target_pos)

        if d < best_dist:

            best_dist = d

            best_vid = vid

    return best_vid





def _get_influences(skin     )             :

    infl = cmds.skinCluster(skin, q=True, inf=True) or []

    return infl





def _get_vertex_weights(skin     , mesh     , vid     , infl           )                    :

    weights = cmds.skinPercent(skin, "{}.vtx[{}]".format(mesh, vid), q=True, v=True)

    return {infl[i]: float(weights[i]) for i in range(len(infl))}





def _set_vertex_weights(skin     , mesh     , vid     , weights                  ):

    tv = [(j, w) for j, w in weights.items()]

    cmds.skinPercent(skin, "{}.vtx[{}]".format(mesh, vid), tv=tv, normalize=True)





@contextmanager

def _relax_skincluster_limits(skin     , min_influences      = 4):

    """Temporarily relax skinCluster limits to avoid pruning ties.



    If maintainMaxInfluences is ON and maxInfluences is small (e.g. 1), Maya will

    collapse weights like A=0.5,B=0.5 into A=1 or B=1 (tie-breaking can look random).

    """

    old = {}

    changed = False

    try:

        if not skin:

            yield

            return



        # Attributes can be locked/nonexistent depending on Maya version.

        for a in ("maintainMaxInfluences", "maxInfluences"):

            try:

                old[a] = cmds.getAttr("{}.{}".format(skin, a))

            except Exception:

                old[a] = None



        try:

            # Disable enforcement during paste.

            if old.get("maintainMaxInfluences") is not None:

                cmds.setAttr("{}.maintainMaxInfluences".format(skin), 0)

                changed = True

        except Exception:

            pass



        try:

            if old.get("maxInfluences") is not None:

                cur = int(old.get("maxInfluences") or 0)

                want = max(cur, int(min_influences))

                if want != cur:

                    cmds.setAttr("{}.maxInfluences".format(skin), want)

                    changed = True

        except Exception:

            pass



        yield

    finally:

        if changed:

            # Restore original values.

            try:

                if old.get("maxInfluences") is not None:

                    cmds.setAttr("{}.maxInfluences".format(skin), int(old["maxInfluences"]))

            except Exception:

                pass

            try:

                if old.get("maintainMaxInfluences") is not None:

                    cmds.setAttr("{}.maintainMaxInfluences".format(skin), int(old["maintainMaxInfluences"]))

            except Exception:

                pass





def _resolve_influence_for_skin(skin     , influence_name     )       :

    if not skin or not influence_name:

        return ""

    infl = cmds.skinCluster(skin, q=True, inf=True) or []

    if influence_name in infl:

        return influence_name



    leaf = influence_name.split("|")[-1]

    matches = []

    for j in infl:

        if j.split("|")[-1] == leaf:

            matches.append(j)

    if len(matches) == 1:

        return matches[0]

    return ""





def _get_current_paint_influence()       :

    try:

        ctx = cmds.currentCtx() or ""

    except Exception:

        ctx = ""

    if not ctx:

        return ""

    try:

        ctype = cmds.contextInfo(ctx, q=True, c=True) or ""

    except Exception:

        ctype = ""

    if ctype not in ("artAttrSkin", "artAttrSkinPaintCtx"):

        return ""

    try:

        return cmds.artAttrSkinPaintCtx(ctx, q=True, influence=True) or ""

    except Exception:

        return ""





def _skincluster_influence_name(skin_cluster     , influence_full     )       :

    if not skin_cluster or not influence_full:

        return ""



    try:

        infs = cmds.skinCluster(skin_cluster, q=True, inf=True) or []

    except Exception:

        infs = []



    for n in infs:

        try:

            for lp in cmds.ls(n, l=True) or []:

                if lp == influence_full:

                    return n

        except Exception:

            pass



    leaf = influence_full.split("|")[-1]

    matches = []

    for n in infs:

        try:

            for lp in cmds.ls(n, l=True) or []:

                if lp.split("|")[-1] == leaf:

                    matches.append(n)

        except Exception:

            pass



    if len(matches) == 1:

        return matches[0]

    return ""





def _focus_paint_influence(skin_cluster     , influence_full     )        :

    if not influence_full:

        return False



    infl = _skincluster_influence_name(skin_cluster, influence_full) or influence_full



    def _get_ctx():

        try:

            ctx = cmds.currentCtx() or ""

        except Exception:

            ctx = ""

        try:

            ctype = cmds.contextInfo(ctx, q=True, c=True) if ctx else ""

        except Exception:

            ctype = ""

        return ctx, ctype



    ctx, ctype = _get_ctx()

    activated_tool = False

    if ctype not in ("artAttrSkin", "artAttrSkinPaintCtx"):

        try:

            cmds.ArtPaintSkinWeightsTool()

            activated_tool = True

        except Exception:

            try:

                mel.eval("ArtPaintSkinWeightsTool")

                activated_tool = True

            except Exception:

                activated_tool = False

        ctx, ctype = _get_ctx()



    def _apply_influence():

        ctx2, ctype2 = _get_ctx()

        if not ctx2 or ctype2 not in ("artAttrSkin", "artAttrSkinPaintCtx"):

            return False

        try:

            safe = infl.replace('"', '\\"')

            try:

                mel.eval('artSkinSelectInfluence "artAttrSkinPaintCtx" "%s";' % safe)

            except Exception:

                mel.eval('source "artAttrSkinCallback.mel";')

                mel.eval('artSkinSelectInfluence "artAttrSkinPaintCtx" "%s";' % safe)

        except Exception:

            try:

                cmds.artAttrSkinPaintCtx(ctx2, e=True, influence=infl)

            except Exception:

                return False

        return True



    if not activated_tool:

        _apply_influence()



    try:

        import maya.utils as mutils



        mutils.executeDeferred(_apply_influence)

    except Exception:

        pass

    return True





def _get_paint_ctx():

    try:

        ctx = cmds.currentCtx() or ""

    except Exception:

        ctx = ""

    try:

        ctype = cmds.contextInfo(ctx, q=True, c=True) if ctx else ""

    except Exception:

        ctype = ""

    return ctx, ctype





def _set_paint_select_mode(select_mode      ):

    ctx, ctype = _get_paint_ctx()

    if ctype not in ("artAttrSkin", "artAttrSkinPaintCtx"):

        try:

            cmds.ArtPaintSkinWeightsTool()

        except Exception:

            try:

                mel.eval("ArtPaintSkinWeightsTool")

            except Exception:

                cmds.warning(u"无法进入绘制蒙皮权重工具。")

                return

        ctx, ctype = _get_paint_ctx()



    if ctype not in ("artAttrSkin", "artAttrSkinPaintCtx"):

        cmds.warning(u"无法进入绘制蒙皮权重工具。")

        return



    # Prefer MEL callbacks used by Maya's own tool UI

    try:

        mel.eval('source "artAttrSkinCallback.mel";')

        if select_mode:

            mel.eval('if (`exists "artSkinSelectTool"`) artSkinSelectTool;')

            mel.eval('if (`exists "artAttrSkinSelectTool"`) artAttrSkinSelectTool;')

        else:

            mel.eval('if (`exists "artSkinPaintTool"`) artSkinPaintTool;')

            mel.eval('if (`exists "artAttrSkinPaintTool"`) artAttrSkinPaintTool;')

        return

    except Exception:

        pass



    mode_val = "select" if select_mode else "paint"

    try:

        cmds.artAttrSkinPaintCtx(ctx, e=True, skinPaintMode=mode_val)

        return

    except Exception:

        pass



    try:

        cmds.artAttrSkinPaintCtx(ctx, e=True, skinPaintMode=(1 if select_mode else 0))

        return

    except Exception:

        pass



    try:

        cmds.artAttrSkinPaintCtx(ctx, e=True, paintMode=(1 if select_mode else 0))

        return

    except Exception:

        pass



    try:

        cmds.artAttrSkinPaintCtx(ctx, e=True, paintMode=(1 if select_mode else 0))

        return

    except Exception:

        cmds.warning(u"无法切换绘制模式/选择模式。")





def mirror_influence_weights(

    axis     ,

    direction     ,

    tolerance       ,

    use_selection      ,

    ignore_side_filter      ,

):

    mesh = _get_mesh_from_selection()

    if not mesh:

        cmds.warning(u"请先选择一个模型或顶点。")

        return



    if use_selection:

        verts = _get_selected_vertices(mesh)

        if not verts:

            cmds.warning(u"请先选择一侧顶点。")

            return



    skin = _get_skin_cluster(mesh)

    if not skin:

        cmds.warning(u"选中模型没有skinCluster。")

        return



    influence = _get_current_paint_influence()

    influence = _resolve_influence_for_skin(skin, influence)

    if not influence:

        cmds.warning(u"未获取到当前绘制影响骨骼，请先进入蒙皮绘制并选择影响骨骼。")

        return



    pairs = _match_vertices_by_side(

        mesh, axis, direction, tolerance, use_selection, ignore_side_filter

    )

    if not pairs and not ignore_side_filter:

        pairs = _match_vertices_by_side(mesh, axis, direction, tolerance, use_selection, True)

    if not pairs:

        cmds.warning(u"没有找到可镜像的顶点对。")

        return



    infl = _get_influences(skin)



    # Mirror to the target influence. If we can't find a mirror by name/position,

    # fall back to the original influence (user expectation: don't mis-assign).

    target_influence = _mirror_influence_name(influence, infl, axis, tolerance)

    if not target_influence:

        target_influence = influence



    cmds.undoInfo(openChunk=True)

    try:

        for src, dst in pairs:

            weights = _get_vertex_weights(skin, mesh, src, infl)

            src_w = weights.get(influence, 0.0)

            cmds.skinPercent(

                skin,

                "{}.vtx[{}]".format(mesh, dst),

                transformValue=[(target_influence, src_w)],

                normalize=True,

            )

    finally:

        cmds.undoInfo(closeChunk=True)



    cmds.inViewMessage(

        amg=u"镜像骨骼权重完成: {} 个顶点".format(len(pairs)), pos="midCenter", fade=True

    )





def select_mirror_influence(axis      = "X", side_threshold        = 0.001):

    mesh = _get_mesh_from_selection()

    if not mesh:

        cmds.warning(u"请先选择一个模型或顶点。")

        return



    skin = _get_skin_cluster(mesh)

    if not skin:

        cmds.warning(u"选中模型没有skinCluster。")

        return



    influence = _get_current_paint_influence()

    influence = _resolve_influence_for_skin(skin, influence)

    if not influence:

        cmds.warning(u"未获取到当前绘制影响骨骼。")

        return



    infl = _get_influences(skin)

    mirror_name = _mirror_influence_name(influence, infl, axis, side_threshold)

    mirror_name = _resolve_influence_for_skin(skin, mirror_name)

    if not mirror_name:

        cmds.warning(u"未找到镜像骨骼影响物(名称/位置都未匹配)。")

        return



    influence_full = (cmds.ls(mirror_name, l=True) or [mirror_name])[0]

    if not _focus_paint_influence(skin, influence_full):

        cmds.warning(u"无法切换到绘制蒙皮权重工具。")





def _get_connected_vertices(mesh     , vid     )             :

    comp = "{}.vtx[{}]".format(mesh, vid)

    edges = cmds.polyListComponentConversion(comp, toEdge=True) or []

    verts = cmds.polyListComponentConversion(edges, toVertex=True) or []

    verts = cmds.ls(verts, fl=True) or []



    # Accept both transform/shape + long/short names.

    try:

        names = _get_mesh_name_variants(mesh)

        ok_bases = {

            names.get("mesh_long", ""),

            names.get("mesh_short", ""),

            names.get("shape_long", ""),

            names.get("shape_short", ""),

        }

        ok_bases = {b for b in ok_bases if b}

    except Exception:

        ok_bases = set([mesh]) if mesh else set()



    result = []

    for v in verts:

        if ".vtx[" not in v:

            continue

        base = v.split(".vtx[")[0]

        base_short = base.split("|")[-1]

        if ok_bases:

            if (base not in ok_bases) and (base_short not in ok_bases):

                continue

        idx = int(v.split("[")[-1].rstrip("]"))

        if idx != vid:

            result.append(idx)

    return sorted(set(result))





def _edit_influence_weights(mode     , step       ):

    mesh = _get_mesh_from_selection()

    if not mesh:

        cmds.warning(u"请先选择一个模型或顶点。")

        return



    skin = _get_skin_cluster(mesh)

    if not skin:

        cmds.warning(u"选中模型没有skinCluster。")

        return



    influence = _get_current_paint_influence()

    if not influence:

        try:

            influence = _LAST_UI_SELECTED_INFLUENCE[0] or ""

        except Exception:

            influence = ""

    influence = _resolve_influence_for_skin(skin, influence)

    if not influence:

        cmds.warning(u"未获取到影响骨骼：请进入蒙皮绘制并选择影响骨骼，或在列表中点击一个影响骨骼。")

        try:

            cmds.inViewMessage(amg=u"<hl>未获取到影响骨骼</hl>", pos="topCenter", fade=True)

        except Exception:

            pass

        return



    verts = _get_selected_vertices(mesh)

    if not verts:

        cmds.warning(u"请先选择顶点。")

        return



    step = max(0.0, float(step))

    if step <= 0.0:

        cmds.warning(u"步进必须大于0。")

        return



    infl = _get_influences(skin)



    changed = 0

    no_neighbor = 0



    cmds.undoInfo(openChunk=True)

    try:

        for vid in verts:

            weights = _get_vertex_weights(skin, mesh, vid, infl)

            cur = weights.get(influence, 0.0)

            if mode == "add":

                new_val = min(1.0, cur + step)

            elif mode == "sub":

                new_val = max(0.0, cur - step)

            elif mode == "smooth":

                neighbors = _get_connected_vertices(mesh, vid)

                if not neighbors:

                    no_neighbor += 1

                    continue

                total = 0.0

                for nv in neighbors:

                    n_weights = _get_vertex_weights(skin, mesh, nv, infl)

                    total += n_weights.get(influence, 0.0)

                avg = total / float(len(neighbors))

                strength = min(1.0, step)

                new_val = cur + (avg - cur) * strength

            else:

                continue



            # Skip if effectively unchanged (reduces no-op calls).

            try:

                if abs(float(new_val) - float(cur)) < 1e-8:

                    continue

            except Exception:

                pass



            cmds.skinPercent(

                skin,

                "{}.vtx[{}]".format(mesh, vid),

                transformValue=[(influence, new_val)],

                normalize=True,

            )

            changed += 1

    finally:

        cmds.undoInfo(closeChunk=True)



    if mode == "smooth":

        if changed == 0:

            if no_neighbor == len(verts):

                cmds.warning(u"平滑无效果：未能获取邻接顶点（可能是 shape/transform 名称不一致或选择不在同一模型上）。")

            else:

                cmds.warning(u"平滑无效果：权重没有变化（可能已经很平滑/邻域平均等于当前值）。")

        else:

            try:

                cmds.inViewMessage(amg=u"平滑完成: {} 个顶点".format(changed), pos="topCenter", fade=True)

            except Exception:

                pass





def _set_influence_weight(value       ):

    """Set the active influence's weight to an absolute value for selected vertices.



    This is the behavior the preset buttons (0..1) use: direct influence amount,

    not incremental stepping.

    """

    mesh = _get_mesh_from_selection()

    if not mesh:

        cmds.warning(u"请先选择一个模型或顶点。")

        return



    skin = _get_skin_cluster(mesh)

    if not skin:

        cmds.warning(u"选中模型没有skinCluster。")

        return



    influence = _get_current_paint_influence()

    if not influence:

        try:

            influence = _LAST_UI_SELECTED_INFLUENCE[0] or ""

        except Exception:

            influence = ""

    influence = _resolve_influence_for_skin(skin, influence)

    if not influence:

        cmds.warning(u"未获取到影响骨骼：请进入蒙皮绘制并选择影响骨骼，或在列表中点击一个影响骨骼。")

        try:

            cmds.inViewMessage(amg=u"<hl>未获取到影响骨骼</hl>", pos="topCenter", fade=True)

        except Exception:

            pass

        return



    verts = _get_selected_vertices(mesh)

    if not verts:

        cmds.warning(u"请先选择顶点。")

        return



    try:

        v = float(value)

    except Exception:

        v = 0.0

    v = max(0.0, min(1.0, v))



    infl = _get_influences(skin)

    if not infl:

        cmds.warning(u"skinCluster没有影响对象。")

        return



    changed = 0

    cmds.undoInfo(openChunk=True)

    try:

        with _relax_skincluster_limits(skin, min_influences=max(4, len(infl))):

            for vid in verts:

                weights = _get_vertex_weights(skin, mesh, int(vid), infl)

                # Preserve the relative distribution of other influences.

                other_sum = 0.0

                for j, w in weights.items():

                    if j == influence:

                        continue

                    other_sum += float(w)



                weights[influence] = v

                if other_sum > 1.0e-12:

                    scale = (1.0 - v) / other_sum

                    for j in list(weights.keys()):

                        if j == influence:

                            continue

                        weights[j] = max(0.0, min(1.0, float(weights.get(j, 0.0)) * scale))

                else:

                    # No other weights: put remainder onto the first non-target influence (if any)

                    # so the vertex doesn't normalize back to 1.0 unexpectedly.

                    remainder = 1.0 - v

                    for j in infl:

                        if j != influence:

                            weights[j] = remainder

                            break



                _set_vertex_weights(skin, mesh, int(vid), weights)

                changed += 1

    finally:

        cmds.undoInfo(closeChunk=True)



    if changed:

        try:

            cmds.inViewMessage(amg=u"设置权重: <hl>{}</hl> = {:g}  ({} 个顶点)".format(influence, v, changed), pos="topCenter", fade=True)

        except Exception:

            pass





_VERTEX_WEIGHT_CLIPBOARD = None  # type: Dict[str, Dict[str, float]] | None



# Transfer clipboard (for "获取转移权重" -> "剪切顶点权重")

# Stores only one influence's weights (source) for selected vertices.

_TRANSFER_WEIGHT_CLIPBOARD = None  # type: Dict[str, object] | None



# Partial transfer clipboard: copy weights for selected vertices from a source mesh,

# then paste onto selected vertices on another mesh.

_PARTIAL_TRANSFER_CLIPBOARD = None  # type: Dict[str, object] | None





def copy_vertex_weights():

    """Copy full vertex weight dictionary from the first selected vertex."""

    global _VERTEX_WEIGHT_CLIPBOARD



    mesh = _get_mesh_from_selection()

    if not mesh:

        cmds.warning(u"请先选择一个模型或顶点。")

        return



    skin = _get_skin_cluster(mesh)

    if not skin:

        cmds.warning(u"选中模型没有skinCluster。")

        return



    verts = _get_selected_vertices(mesh)

    if not verts:

        cmds.warning(u"请先选择顶点。")

        return



    src = int(verts[0])

    infl = _get_influences(skin)

    if not infl:

        cmds.warning(u"skinCluster没有影响对象。")

        return



    weights = _get_vertex_weights(skin, mesh, src, infl)

    # Store by influence name; paste will try exact match then leaf-name match.

    _VERTEX_WEIGHT_CLIPBOARD = {

        'weights': dict(weights),

    }

    try:

        cmds.inViewMessage(amg=u"已复制顶点权重: vtx[{}]".format(src), pos="topCenter", fade=True)

    except Exception:

        pass





def paste_vertex_weights():

    """Paste previously copied vertex weights onto all selected vertices."""

    global _VERTEX_WEIGHT_CLIPBOARD



    if not _VERTEX_WEIGHT_CLIPBOARD or not isinstance(_VERTEX_WEIGHT_CLIPBOARD, dict):

        cmds.warning(u"没有可粘贴的权重，请先点击“Copy”。")

        return



    src_weights = _VERTEX_WEIGHT_CLIPBOARD.get('weights') or {}

    if not src_weights:

        cmds.warning(u"复制缓存为空，请重新复制一次。")

        return



    mesh = _get_mesh_from_selection()

    if not mesh:

        cmds.warning(u"请先选择一个模型或顶点。")

        return



    skin = _get_skin_cluster(mesh)

    if not skin:

        cmds.warning(u"选中模型没有skinCluster。")

        return



    verts = _get_selected_vertices(mesh)

    if not verts:

        cmds.warning(u"请先选择顶点。")

        return



    infl = _get_influences(skin)

    if not infl:

        cmds.warning(u"skinCluster没有影响对象。")

        return



    # Build a leaf-name index for best-effort remap across different paths.

    leaf_map = {}

    try:

        for j, w in src_weights.items():

            leaf = str(j).split('|')[-1]

            leaf_map.setdefault(leaf, []).append((j, float(w)))

    except Exception:

        leaf_map = {}



    matched = set()



    def _weight_for_target_joint(jnt):

        if jnt in src_weights:

            matched.add(str(jnt))

            try:

                return float(src_weights.get(jnt, 0.0))

            except Exception:

                return 0.0

        leaf = str(jnt).split('|')[-1]

        hits = leaf_map.get(leaf) or []

        if len(hits) == 1:

            matched.add(str(jnt))

            return float(hits[0][1])

        return 0.0



    # Set all influences (missing ones become 0) for deterministic paste.

    tv = [(j, _weight_for_target_joint(j)) for j in infl]

    if not matched:

        cmds.warning(u"粘贴失败：目标 skin 的影响骨骼与复制源不匹配（没有任何可匹配的骨骼名）。")

        return



    if len(matched) < len(infl):

        try:

            cmds.warning("注意：仅匹配到 %d/%d 个影响骨骼，将按匹配结果粘贴并重新归一化。" % (len(matched), len(infl)))

        except Exception:

            pass



    cmds.undoInfo(openChunk=True)

    try:

        # Make sure skinCluster doesn't collapse a tie (0.5/0.5) into 1.0 due to limits.

        with _relax_skincluster_limits(skin, min_influences=max(4, len(infl))):

            for vid in verts:

                cmds.skinPercent(

                    skin,

                    "{}.vtx[{}]".format(mesh, int(vid)),

                    transformValue=tv,

                    normalize=True,

                )

    finally:

        cmds.undoInfo(closeChunk=True)



    try:

        cmds.inViewMessage(amg=u"已粘贴顶点权重: {} 个顶点".format(len(verts)), pos="topCenter", fade=True)

    except Exception:

        pass





def get_transfer_vertex_weights():

    """Capture per-vertex weights for current paint influence (source).



    This is used by the 2-step workflow:

        1) 获取权重: capture source influence + selected vertices' source weights

        2) 剪切权重: move captured amount from source -> target (UI-selected)

    """

    global _TRANSFER_WEIGHT_CLIPBOARD



    mesh = _get_mesh_from_selection()

    if not mesh:

        cmds.warning(u"请先选择一个模型或顶点。")

        return



    skin = _get_skin_cluster(mesh)

    if not skin:

        cmds.warning(u"选中模型没有skinCluster。")

        return



    source_influence = _get_current_paint_influence()

    source_influence = _resolve_influence_for_skin(skin, source_influence)

    if not source_influence:

        cmds.warning(u"未获取到源影响骨骼：请进入蒙皮绘制并选择源影响骨骼。")

        return



    verts = _get_selected_vertices(mesh)

    if not verts:

        cmds.warning(u"请先选择顶点。")

        return



    infl = _get_influences(skin)

    if not infl:

        cmds.warning(u"skinCluster没有影响对象。")

        return



    w_by_vid                   = {}

    for vid in verts:

        try:

            w = _get_vertex_weights(skin, mesh, int(vid), infl)

            w_by_vid[int(vid)] = float(w.get(source_influence, 0.0) or 0.0)

        except Exception:

            continue



    if not w_by_vid:

        cmds.warning(u"获取失败：未读取到任何顶点权重。")

        return



    _TRANSFER_WEIGHT_CLIPBOARD = {

        'mesh_long': (cmds.ls(mesh, l=True) or [mesh])[0],

        'skin': str(skin),

        'source_influence': str(source_influence),

        'vids': sorted(w_by_vid.keys()),

        'weights_by_vid': w_by_vid,

    }



    try:

        cmds.inViewMessage(

            amg=u"已获取权重: <hl>{}</hl>  ({} 个顶点)".format(source_influence, len(w_by_vid)),

            pos="topCenter",

            fade=True,

        )

    except Exception:

        pass





def cut_vertex_weights_to_paint_influence():

    """Cut (move) captured weights from source -> target.



    - Source influence: stored by "获取权重" (from Paint Skin Weights).

        - Target influence: current Paint Skin Weights influence (preferred).

            If paint influence can't be detected, falls back to last UI-clicked influence.

    """

    global _TRANSFER_WEIGHT_CLIPBOARD



    if not _TRANSFER_WEIGHT_CLIPBOARD or not isinstance(_TRANSFER_WEIGHT_CLIPBOARD, dict):

        cmds.warning(u"没有可剪切的权重：请先点击“获取权重”。")

        return



    mesh = _get_mesh_from_selection()

    if not mesh:

        # If nothing is selected, fall back to the captured mesh.

        try:

            mesh = str(_TRANSFER_WEIGHT_CLIPBOARD.get('mesh_long') or '')

        except Exception:

            mesh = ''

        if not mesh:

            cmds.warning(u"请先选择一个模型或顶点。")

            return



    skin = _get_skin_cluster(mesh)

    if not skin:

        cmds.warning(u"选中模型没有skinCluster。")

        return



    try:

        source_influence = str(_TRANSFER_WEIGHT_CLIPBOARD.get('source_influence') or '')

    except Exception:

        source_influence = ''

    source_influence = _resolve_influence_for_skin(skin, source_influence)

    if not source_influence:

        cmds.warning(u"缓存中未找到源影响骨骼：请重新点击“获取权重”。")

        return



    # Target: prefer current paint influence (Tool Settings selection), so users can

    # cut into an influence even if its weight is currently 0 and therefore not

    # listed in our aggregated UI list.

    target_influence = _get_current_paint_influence()

    target_influence = _resolve_influence_for_skin(skin, target_influence)



    # Fallback: last clicked influence in our UI list.

    if not target_influence:

        try:

            target_influence = str(_LAST_UI_SELECTED_INFLUENCE[0] or "")

        except Exception:

            target_influence = ""

        target_influence = _resolve_influence_for_skin(skin, target_influence)



    # Fallback: selected joint in scene.

    if not target_influence:

        try:

            sel_joints = cmds.ls(sl=True, type="joint") or []

        except Exception:

            sel_joints = []

        if sel_joints:

            cand = (cmds.ls(sel_joints[0], l=True) or [sel_joints[0]])[0]

            target_influence = _resolve_influence_for_skin(skin, cand) or _resolve_influence_for_skin(skin, sel_joints[0])



    if not target_influence:

        cmds.warning(u"未获取到目标影响骨骼：请在 Paint Skin Weights 工具中切换到目标影响骨骼(或在列表中点击目标骨骼)。")

        return



    if source_influence == target_influence:

        cmds.warning(u"源影响骨骼与目标影响骨骼相同，无需剪切。")

        return



    # Prefer current selection; otherwise use captured vertices.

    verts = _get_selected_vertices(mesh)

    if not verts:

        try:

            verts = list(_TRANSFER_WEIGHT_CLIPBOARD.get('vids') or [])

        except Exception:

            verts = []

    if not verts:

        cmds.warning(u"请先选择顶点，或先点击“获取权重”。")

        return



    infl = _get_influences(skin)

    if not infl:

        cmds.warning(u"skinCluster没有影响对象。")

        return



    w_by_vid = _TRANSFER_WEIGHT_CLIPBOARD.get('weights_by_vid') or {}

    moved = 0

    moved_sum = 0.0



    cmds.undoInfo(openChunk=True)

    try:

        # Be defensive about skinCluster influence limits.

        with _relax_skincluster_limits(skin, min_influences=max(4, len(infl))):

            for vid in verts:

                w = _get_vertex_weights(skin, mesh, int(vid), infl)

                cap = 0.0

                try:

                    cap = float(w_by_vid.get(int(vid), 0.0) or 0.0)

                except Exception:

                    cap = 0.0

                if cap <= 0.0:

                    continue



                cur_src = float(w.get(source_influence, 0.0) or 0.0)

                if cur_src <= 0.0:

                    continue

                move_amt = min(cap, cur_src)

                if move_amt <= 0.0:

                    continue

                dst_w = float(w.get(target_influence, 0.0) or 0.0)

                w[target_influence] = dst_w + move_amt

                w[source_influence] = max(0.0, cur_src - move_amt)



                tv = [(j, float(w.get(j, 0.0) or 0.0)) for j in infl]

                cmds.skinPercent(

                    skin,

                    "{}.vtx[{}]".format(mesh, int(vid)),

                    transformValue=tv,

                    normalize=True,

                )

                moved += 1

                moved_sum += move_amt

    finally:

        cmds.undoInfo(closeChunk=True)



    try:

        cmds.inViewMessage(

            amg=(

                "已剪切权重: <hl>{}</hl> -> <hl>{}</hl>  "

                "({} 个顶点, Σ={:.4f})".format(source_influence, target_influence, moved, moved_sum)

            ),

            pos="topCenter",

            fade=True,

        )

    except Exception:

        pass





def show_full_model():

    """Show hidden polygon faces and unhide selected mesh objects.



    - Faces hidden via Poly Hide (polyHide) are restored via polyShowHidden.

    - Objects hidden via visibility are turned back on.

    """

    sel = cmds.ls(sl=True, l=True) or []

    if not sel:

        cmds.warning(u"请先选择模型(或模型组件)。")

        return



    # Normalize selection items to DAG objects (strip components).

    bases = []

    for s in sel:

        try:

            bases.append(str(s).split('.', 1)[0])

        except Exception:

            bases.append(str(s))



    # Collect mesh transforms.

    mesh_transforms = []

    seen = set()

    for o in bases:

        if not o or o in seen:

            continue

        seen.add(o)

        if not cmds.objExists(o):

            continue



        try:

            if cmds.nodeType(o) == 'mesh':

                parents = cmds.listRelatives(o, p=True, f=True) or []

                for p in parents:

                    if p and p not in mesh_transforms:

                        mesh_transforms.append(p)

                continue

        except Exception:

            pass



        try:

            shapes = cmds.listRelatives(o, s=True, ni=True, f=True) or []

        except Exception:

            shapes = []

        has_mesh = False

        for sh in shapes:

            try:

                if cmds.nodeType(sh) == 'mesh':

                    has_mesh = True

                    break

            except Exception:

                continue

        if has_mesh and o not in mesh_transforms:

            mesh_transforms.append(o)



    if not mesh_transforms:

        cmds.warning(u"未找到可处理的 mesh：请选中模型(Transform)或模型组件。")

        return



    old_sel = cmds.ls(sl=True, l=True) or []

    cmds.undoInfo(openChunk=True)

    try:

        for t in mesh_transforms:

            # Ensure transform itself is visible.

            try:

                if cmds.attributeQuery('visibility', n=t, exists=True):

                    cmds.setAttr(t + '.visibility', 1)

            except Exception:

                pass



            # Unhide any hidden nodes under this transform.

            try:

                cmds.showHidden(t)

            except Exception:

                pass



            # Restore faces hidden by polyHide.

            try:

                cmds.polyShowHidden(t)

            except Exception:

                # Some Maya versions are picky about args; fall back to selection-based call.

                try:

                    cmds.select(t, r=True)

                    cmds.polyShowHidden()

                except Exception:

                    pass

    finally:

        try:

            if old_sel:

                cmds.select(old_sel, r=True)

            else:

                cmds.select(clear=True)

        except Exception:

            pass

        cmds.undoInfo(closeChunk=True)



    try:

        cmds.inViewMessage(amg=u"已显示完整模型: {} 个对象".format(len(mesh_transforms)), pos="topCenter", fade=True)

    except Exception:

        pass





def _build_leaf_weight_map(weights                  )                                      :

    """Index weights by leaf name for best-effort remap across namespaces/paths."""

    leaf_map                                     = {}

    try:

        for j, w in (weights or {}).items():

            leaf = str(j).split('|')[-1]

            leaf_map.setdefault(leaf, []).append((str(j), float(w)))

    except Exception:

        leaf_map = {}

    return leaf_map





def _remap_weights_to_influences(src_weights                  , target_influences           )                                       :

    """Return transformValue list for target influences and matched count."""

    if not src_weights:

        return [], 0

    leaf_map = _build_leaf_weight_map(src_weights)

    matched_ref = [0]



    def _w_for(jnt     )         :

        if jnt in src_weights:

            matched_ref[0] += 1

            try:

                return float(src_weights.get(jnt, 0.0))

            except Exception:

                return 0.0

        leaf = str(jnt).split('|')[-1]

        hits = leaf_map.get(leaf) or []

        if len(hits) == 1:

            matched_ref[0] += 1

            return float(hits[0][1])

        return 0.0



    tv = [(j, _w_for(j)) for j in (target_influences or [])]

    return tv, int(matched_ref[0])





def copy_model_weights():

    """Copy weights for all selected vertices on the source mesh (for later paste)."""

    global _PARTIAL_TRANSFER_CLIPBOARD



    mesh = _get_mesh_from_selection()

    if not mesh:

        cmds.warning(u"请先选择源模型的顶点。")

        return



    skin = _get_skin_cluster(mesh)

    if not skin:

        cmds.warning(u"选中模型没有skinCluster。")

        return



    vids = _get_selected_vertices(mesh)

    if not vids:

        cmds.warning(u"请先选择要拷贝的大腿顶点（支持部分点）。")

        return



    infl = _get_influences(skin)

    if not infl:

        cmds.warning(u"skinCluster没有影响对象。")

        return



    weights_by_vid                              = {}

    for vid in vids:

        try:

            weights_by_vid[int(vid)] = _get_vertex_weights(skin, mesh, int(vid), infl)

        except Exception:

            continue



    if not weights_by_vid:

        cmds.warning(u"拷贝失败：未读取到任何顶点权重。")

        return



    _PARTIAL_TRANSFER_CLIPBOARD = {

        'source_mesh': (cmds.ls(mesh, long=True) or [mesh])[0],

        'source_skin': str(skin),

        'vids': list(sorted(weights_by_vid.keys())),

        'weights_by_vid': weights_by_vid,

    }



    try:

        cmds.inViewMessage(amg=u"已拷贝模型权重(选点): {} 个顶点".format(len(weights_by_vid)), pos="topCenter", fade=True)

    except Exception:

        pass





def paste_model_weights(match_by_vertex_id       = True):

    """Paste previously copied per-vertex weights onto selected vertices on the target mesh.



    match_by_vertex_id:

        - True: paste by vertex id (best when meshes share identical topology / vertex order)

        - False: paste by selection order (sorted ids) from source to target

    """

    global _PARTIAL_TRANSFER_CLIPBOARD



    if not _PARTIAL_TRANSFER_CLIPBOARD or not isinstance(_PARTIAL_TRANSFER_CLIPBOARD, dict):

        cmds.warning(u"没有可粘贴的权重，请先点击“拷贝模型权重”。")

        return



    src_weights_by_vid = _PARTIAL_TRANSFER_CLIPBOARD.get('weights_by_vid') or {}

    src_vids = _PARTIAL_TRANSFER_CLIPBOARD.get('vids') or []

    if not src_weights_by_vid or not src_vids:

        cmds.warning(u"复制缓存为空，请重新拷贝一次。")

        return



    mesh = _get_mesh_from_selection()

    if not mesh:

        cmds.warning(u"请先选择目标模型的顶点。")

        return



    skin = _get_skin_cluster(mesh)

    if not skin:

        cmds.warning(u"目标模型没有skinCluster。")

        return



    dst_vids = _get_selected_vertices(mesh)

    if not dst_vids:

        cmds.warning(u"请先选择要粘贴的目标顶点（支持部分点）。")

        return



    infl = _get_influences(skin)

    if not infl:

        cmds.warning(u"目标 skinCluster 没有影响对象。")

        return



    # Build mapping list: dst_vid -> src_weight_dict

    pairs                                     = []

    missing = 0

    if match_by_vertex_id:

        for dv in dst_vids:

            w = src_weights_by_vid.get(int(dv))

            if not w:

                missing += 1

                continue

            pairs.append((int(dv), w))

        if not pairs:

            cmds.warning(u"粘贴失败：按顶点ID匹配时，没有找到任何可对应的顶点。请确认两模型拓扑/点号一致，或改用按顺序粘贴。")

            return

    else:

        # By order (sorted ids). Use the source vids list order.

        src_list = [src_weights_by_vid.get(int(v)) for v in src_vids]

        src_list = [w for w in src_list if w]

        n = min(len(dst_vids), len(src_list))

        if n <= 0:

            cmds.warning(u"粘贴失败：源/目标顶点数量为空。")

            return

        if len(dst_vids) != len(src_list):

            cmds.warning("注意：源/目标顶点数量不一致，将按顺序粘贴前 %d 个顶点。" % int(n))

        for i in range(n):

            pairs.append((int(dst_vids[i]), src_list[i]))



    cmds.undoInfo(openChunk=True)

    applied = 0

    try:

        with _relax_skincluster_limits(skin, min_influences=max(4, len(infl))):

            for dv, sw in pairs:

                tv, matched = _remap_weights_to_influences(sw, infl)

                if matched <= 0:

                    # No influence matched at all -> skip this vertex.

                    continue

                cmds.skinPercent(

                    skin,

                    "{}.vtx[{}]".format(mesh, int(dv)),

                    transformValue=tv,

                    normalize=True,

                )

                applied += 1

    finally:

        cmds.undoInfo(closeChunk=True)



    if applied <= 0:

        cmds.warning(u"粘贴失败：目标 skin 的影响骨骼与复制源不匹配（没有任何可匹配的骨骼名）。")

        return



    if match_by_vertex_id and missing:

        try:

            cmds.warning("注意：有 %d 个目标顶点在复制缓存中不存在，已跳过。" % int(missing))

        except Exception:

            pass



    try:

        cmds.inViewMessage(amg=u"已粘贴模型权重(选点): {} 个顶点".format(applied), pos="topCenter", fade=True)

    except Exception:

        pass





_LR_PATTERNS = [

    (re.compile(r"(^|[\W_])L($|[\W_])"), "R"),

    (re.compile(r"(^|[\W_])R($|[\W_])"), "L"),

    (re.compile(r"(^|[\W_])Left($|[\W_])", re.IGNORECASE), "Right"),

    (re.compile(r"(^|[\W_])Right($|[\W_])", re.IGNORECASE), "Left"),

]





def _swap_lr_name(name     )       :

    result = name

    for pat, repl in _LR_PATTERNS:

        def _repl(match):

            pre = match.group(1)

            post = match.group(2)

            # keep original case style where possible

            if match.group(0).strip("_").lower() == "l":

                core = "R"

            elif match.group(0).strip("_").lower() == "r":

                core = "L"

            else:

                core = repl

            return "{}{}{}".format(pre, core, post)



        new_result = pat.sub(_repl, result)

        if new_result != result:

            return new_result

    return result





def _remap_weights_lr(weights                  , infl           )                    :

    mapped = {}

    infl_set = set(infl)

    for jnt, w in weights.items():

        target = _swap_lr_name(jnt)

        if target in infl_set:

            mapped[target] = w

        else:

            mapped[jnt] = w

    return mapped





def _suggest_joint_pos_tol(side_threshold       )         :

    """Heuristic tolerance for joint positional mirror matching.



    UI "侧向阈值" is for vertex side filtering (often tiny like 0.001). For joints,

    we allow a slightly larger tolerance so rigs with minor asymmetry still match.

    """

    try:

        v = float(side_threshold)

    except Exception:

        v = 0.001

    return max(0.001, abs(v) * 10.0)





def _node_world_pos(node     )                                     :

    try:

        p = cmds.xform(node, q=True, ws=True, t=True)

        return float(p[0]), float(p[1]), float(p[2])

    except Exception:

        return None





def _find_mirror_influence_by_pos(

    source_influence     ,

    influences           ,

    axis     ,

    pos_tol       ,

    _pos_cache                                               = None,

)       :

    """Best-effort mirror influence lookup by mirrored world-space position."""

    if not source_influence or not influences:

        return ""



    if _pos_cache is None:

        _pos_cache = {}



    src_pos = _pos_cache.get(source_influence)

    if src_pos is None:

        src_pos = _node_world_pos(source_influence)

        if src_pos is None:

            return ""

        _pos_cache[source_influence] = src_pos



    # If the joint is already close to the mirror plane, treat it as center.

    axis_idx = 0 if axis == "X" else (1 if axis == "Y" else 2)

    if abs(src_pos[axis_idx]) <= max(1.0e-8, float(pos_tol)):

        return source_influence



    target_pos = _mirror_pos(src_pos, axis)

    best = ""

    best_d2 = 1.0e30



    for j in influences:

        if not j:

            continue

        jp = _pos_cache.get(j)

        if jp is None:

            jp = _node_world_pos(j)

            if jp is None:

                continue

            _pos_cache[j] = jp

        dx = jp[0] - target_pos[0]

        dy = jp[1] - target_pos[1]

        dz = jp[2] - target_pos[2]

        d2 = dx * dx + dy * dy + dz * dz

        if d2 < best_d2:

            best_d2 = d2

            best = j



    try:

        if best and math.sqrt(best_d2) <= float(pos_tol):

            return best

    except Exception:

        pass

    return ""





def _mirror_influence_name(

    influence     ,

    influences           ,

    axis     ,

    side_threshold       ,

)       :

    """Return mirror influence using name swap first, then positional fallback."""

    infl_set = set(influences or [])

    target = _swap_lr_name(influence)

    if target in infl_set:

        return target



    pos_tol = _suggest_joint_pos_tol(side_threshold)

    return _find_mirror_influence_by_pos(influence, influences, axis, pos_tol)





def _remap_weights_mirror(

    weights                  ,

    influences           ,

    axis     ,

    side_threshold       ,

)                    :

    """Remap vertex weights to mirrored influences.



    Mapping order per influence:

        1) swap L/R name patterns

        2) if not found, find closest mirrored-position joint

        3) if still not found, keep original influence

    """

    if not weights:

        return {}



    infl = influences or []

    infl_set = set(infl)

    pos_tol = _suggest_joint_pos_tol(side_threshold)

    pos_cache                                        = {}

    mapped                   = {}



    for jnt, w in (weights or {}).items():

        target = _swap_lr_name(jnt)

        if target not in infl_set:

            target = _find_mirror_influence_by_pos(jnt, infl, axis, pos_tol, pos_cache) or jnt

        mapped[target] = float(mapped.get(target, 0.0)) + float(w)

    return mapped





def _match_vertices_by_side(

    mesh     ,

    axis     ,

    direction     ,

    tolerance       ,

    use_selection      ,

    ignore_side_filter      ,

)                         :

    all_verts = _get_all_vertices(mesh)

    src_verts = _get_selected_vertices(mesh) if use_selection else all_verts



    # Filter source vertices by side

    filtered_src = []

    for vid in src_verts:

        x, y, z = _get_vertex_pos(mesh, vid)

        axis_val = {"X": x, "Y": y, "Z": z}[axis]

        if ignore_side_filter:

            filtered_src.append(vid)

        else:

            if direction == "L->R":

                if axis_val >= tolerance:

                    filtered_src.append(vid)

            else:

                if axis_val <= -tolerance:

                    filtered_src.append(vid)



    # Build target search list (opposite side or full mesh)

    target_verts = []

    for vid in all_verts:

        if ignore_side_filter:

            target_verts.append(vid)

            continue

        x, y, z = _get_vertex_pos(mesh, vid)

        axis_val = {"X": x, "Y": y, "Z": z}[axis]

        if direction == "L->R":

            if axis_val <= -tolerance:

                target_verts.append(vid)

        else:

            if axis_val >= tolerance:

                target_verts.append(vid)



    kd = _build_vertex_kd(mesh, target_verts)



    # Build coincident-vertex groups on the target side (unwelded seams).

    # key -> [vid, vid, ...]

    target_groups                                        = {}

    vid_to_key                                  = {}

    for vid, pos in kd:

        k = _pos_key(pos)

        vid_to_key[vid] = k

        target_groups.setdefault(k, []).append(vid)



    pairs                        = []

    for src in filtered_src:

        src_pos = _get_vertex_pos(mesh, src)

        mirrored = _mirror_pos(src_pos, axis)

        dst = _find_closest_vertex(kd, mirrored)

        if dst != -1:

            k = vid_to_key.get(dst)

            if k is not None:

                for d2 in target_groups.get(k, [dst]):

                    pairs.append((src, d2))

            else:

                pairs.append((src, dst))



    # Deduplicate while keeping deterministic order.

    seen = set()

    out                        = []

    for p in pairs:

        if p in seen:

            continue

        seen.add(p)

        out.append(p)

    return out





def mirror_skin_weights(

    axis      = "X",

    direction      = "L->R",

    tolerance        = 0.001,

    use_selection       = True,

    ignore_side_filter       = False,

    swap_lr_influences       = True,

):

    mesh = _get_mesh_from_selection()

    if not mesh:

        cmds.warning(u"请先选择一个模型或顶点。")

        return



    skin = _get_skin_cluster(mesh)

    if not skin:

        cmds.warning(u"选中模型没有skinCluster。")

        return



    infl = _get_influences(skin)

    if not infl:

        cmds.warning(u"skinCluster没有影响对象。")

        return



    pairs = _match_vertices_by_side(

        mesh, axis, direction, tolerance, use_selection, ignore_side_filter

    )

    if not pairs and not ignore_side_filter:

        pairs = _match_vertices_by_side(mesh, axis, direction, tolerance, use_selection, True)

    if not pairs:

        cmds.warning(u"没有找到可镜像的顶点对。")

        return



    cmds.undoInfo(openChunk=True)

    try:

        for src, dst in pairs:

            weights = _get_vertex_weights(skin, mesh, src, infl)

            if swap_lr_influences:

                weights = _remap_weights_mirror(weights, infl, axis, tolerance)

            _set_vertex_weights(skin, mesh, dst, weights)

    finally:

        cmds.undoInfo(closeChunk=True)



    cmds.inViewMessage(

        amg=u"镜像完成: {} 个顶点".format(len(pairs)), pos="midCenter", fade=True

    )





def select_mirror_vertices(

    axis      = "X",

    direction      = "L->R",

    tolerance        = 0.001,

    use_selection       = True,

    ignore_side_filter       = False,

):

    mesh = _get_mesh_from_selection()

    if not mesh:

        cmds.warning(u"请先选择一个模型或顶点。")

        return



    pairs = _match_vertices_by_side(

        mesh, axis, direction, tolerance, use_selection, ignore_side_filter

    )

    if not pairs and not ignore_side_filter:

        pairs = _match_vertices_by_side(mesh, axis, direction, tolerance, use_selection, True)

    if not pairs:

        cmds.warning(u"没有找到可镜像的顶点对。")

        return



    dst_verts = ["{}.vtx[{}]".format(mesh, dst) for _, dst in pairs]

    cmds.select(dst_verts, r=True)

    cmds.inViewMessage(

        amg=u"已选中镜像顶点: {} 个".format(len(dst_verts)), pos="midCenter", fade=True

    )





def show():

    if cmds.window(WINDOW_NAME, exists=True):

        cmds.deleteUI(WINDOW_NAME)



    cmds.window(WINDOW_NAME, title="蒙皮权重镜像", widthHeight=(460, 320))

    cmds.columnLayout(adjustableColumn=True, rowSpacing=8)



    cmds.text(label="选择一侧顶点后执行镜像", align="left")



    cmds.separator(style="in")



    axis_menu = cmds.optionMenu(label="镜像轴", width=300)

    cmds.menuItem(label="X")

    cmds.menuItem(label="Y")

    cmds.menuItem(label="Z")



    dir_menu = cmds.optionMenu(label="方向", width=300)

    cmds.menuItem(label="L->R")

    cmds.menuItem(label="R->L")



    tol_field = cmds.floatFieldGrp(

        label="侧向阈值", numberOfFields=1, value1=0.001, precision=4, width=300

    )



    use_sel = cmds.checkBox(label="仅使用选择顶点", value=True)

    ignore_side = cmds.checkBox(label="忽略方向过滤(全模型匹配)", value=False)

    swap_lr = cmds.checkBox(label="镜像骨骼L/R名称", value=True)



    cmds.separator(style="in")

    cmds.frameLayout(label="选中顶点影响骨骼", collapsable=False, width=300)

    infl_list = cmds.textScrollList(numberOfRows=8, allowMultiSelection=False)

    cmds.setParent("..")



    infl_label_map = {}

    last_influence_name = [""]



    def _refresh_influence_list_fast():

        """Fast refresh using OpenMaya getWeights (avoids per-vertex skinPercent calls)."""

        cmds.textScrollList(infl_list, e=True, removeAll=True)

        infl_label_map.clear()



        mesh = _get_mesh_from_selection()

        if not mesh:

            return

        skin = _get_skin_cluster(mesh)

        if not skin:

            return



        verts = _get_selected_vertices(mesh)

        if not verts:

            return



        # Safety cap to keep UI responsive if user selects huge ranges.

        cap = 800

        if len(verts) > cap:

            verts = verts[:cap]



        if om2 is None or oma2 is None:

            # Fallback to slow method if API isn't available.

            return _refresh_influence_list_slow(mesh, skin, verts)



        shape = _get_mesh_shape(mesh)

        if not shape:

            return



        try:

            fn_skin = _om_skin_fn(skin)

            mesh_dag = _om_dagpath(shape)

            inf_paths = fn_skin.influenceObjects() or []

            inf_full = [p.fullPathName() for p in inf_paths]

            full_to_index = {n: i for i, n in enumerate(inf_full)}



            # Map cmds influence list (skinCluster -q -inf) to OpenMaya indices.

            infl_cmds = cmds.skinCluster(skin, q=True, inf=True) or []

            idx_map = {}

            for j in infl_cmds:

                lp = (cmds.ls(j, l=True) or [j])[0]

                ii = full_to_index.get(lp)

                if ii is None:

                    leaf = lp.split("|")[-1]

                    # leaf match (best-effort)

                    hits = [k for k, n in enumerate(inf_full) if n.split("|")[-1] == leaf]

                    if len(hits) == 1:

                        ii = hits[0]

                if ii is not None:

                    idx_map[j] = int(ii)



            if not idx_map:

                return



            comp_fn = om2.MFnSingleIndexedComponent()

            comp_obj = comp_fn.create(om2.MFn.kMeshVertComponent)

            comp_fn.addElements([int(v) for v in verts])



            weights, inf_count = fn_skin.getWeights(mesh_dag, comp_obj)

            inf_count = int(inf_count)

            vcount = int(len(verts))



            total = {j: 0.0 for j in idx_map.keys()}

            for vi in range(vcount):

                off = vi * inf_count

                for j, ii in idx_map.items():

                    total[j] += float(weights[off + ii])



            # Always include current/last-picked influence even if its average is 0,

            # so users can click an influence that has no weight yet on selection.

            pinned = []

            try:

                cur = _resolve_influence_for_skin(skin, _get_current_paint_influence())

            except Exception:

                cur = ""

            try:

                ui = _resolve_influence_for_skin(skin, str(_LAST_UI_SELECTED_INFLUENCE[0] or ""))

            except Exception:

                ui = ""

            for _p in (cur, ui):

                if _p and (_p not in pinned):

                    pinned.append(_p)



            items = []

            for j, sum_w in total.items():

                avg = sum_w / float(vcount)

                if (avg > 0.0001) or (j in pinned):

                    label = "{}  ({:.4f})".format(j, avg)

                    infl_label_map[label] = j

                    items.append(label)

            if items:

                cmds.textScrollList(infl_list, e=True, append=sorted(items))

        except Exception:

            # If anything fails, fall back.

            return _refresh_influence_list_slow(mesh, skin, verts)



    def _refresh_influence_list_slow(mesh     , skin     , verts           ):

        infl = _get_influences(skin)

        if not infl:

            return

        total = {j: 0.0 for j in infl}

        for vid in verts:

            weights = _get_vertex_weights(skin, mesh, vid, infl)

            for jnt, w in weights.items():

                total[jnt] += w

        count = float(len(verts))

        pinned = []

        try:

            cur = _resolve_influence_for_skin(skin, _get_current_paint_influence())

        except Exception:

            cur = ""

        try:

            ui = _resolve_influence_for_skin(skin, str(_LAST_UI_SELECTED_INFLUENCE[0] or ""))

        except Exception:

            ui = ""

        for _p in (cur, ui):

            if _p and (_p not in pinned):

                pinned.append(_p)



        items = []

        for jnt, sum_w in total.items():

            avg_w = sum_w / count

            if (avg_w > 0.0001) or (jnt in pinned):

                label = "{}  ({:.4f})".format(jnt, avg_w)

                infl_label_map[label] = jnt

                items.append(label)

        if items:

            cmds.textScrollList(infl_list, e=True, append=sorted(items))



    def _refresh_influence_list(*_):

        _refresh_influence_list_fast()



    def _on_infl_select(*_):

        sel = cmds.textScrollList(infl_list, q=True, si=True) or []

        if not sel:

            return

        influence = infl_label_map.get(sel[0], sel[0])

        try:

            _LAST_UI_SELECTED_INFLUENCE[0] = str(influence or '')

        except Exception:

            pass

        mesh = _get_mesh_from_selection()

        if not mesh:

            cmds.warning(u"请先选择模型或顶点。")

            return

        skin = _get_skin_cluster(mesh)

        if not skin:

            cmds.warning(u"选中模型没有skinCluster。")

            return

        influence_full = (cmds.ls(influence, l=True) or [influence])[0]

        last_influence_name[0] = influence

        if not _focus_paint_influence(skin, influence_full):

            cmds.warning(u"无法切换到绘制蒙皮权重工具。")



    cmds.textScrollList(infl_list, e=True, selectCommand=_on_infl_select)



    refresh_scheduled = [False]



    def _schedule_refresh(*_):

        if refresh_scheduled[0]:

            return

        refresh_scheduled[0] = True



        def _do():

            refresh_scheduled[0] = False

            _refresh_influence_list()



        if mutils:

            mutils.executeDeferred(_do)

        else:

            cmds.evalDeferred(_do)



    cmds.scriptJob(event=["SelectionChanged", _schedule_refresh], parent=WINDOW_NAME)



    def _on_mirror(*_):

        axis = cmds.optionMenu(axis_menu, q=True, value=True)

        direction = cmds.optionMenu(dir_menu, q=True, value=True)

        tolerance = cmds.floatFieldGrp(tol_field, q=True, value1=True)

        use_selection = cmds.checkBox(use_sel, q=True, value=True)

        ignore_side_filter = cmds.checkBox(ignore_side, q=True, value=True)

        swap_lr_influences = cmds.checkBox(swap_lr, q=True, value=True)

        mirror_skin_weights(

            axis,

            direction,

            tolerance,

            use_selection,

            ignore_side_filter,

            swap_lr_influences,

        )

        _refresh_influence_list()



    def _on_select_mirror(*_):

        axis = cmds.optionMenu(axis_menu, q=True, value=True)

        direction = cmds.optionMenu(dir_menu, q=True, value=True)

        tolerance = cmds.floatFieldGrp(tol_field, q=True, value1=True)

        use_selection = cmds.checkBox(use_sel, q=True, value=True)

        ignore_side_filter = cmds.checkBox(ignore_side, q=True, value=True)

        select_mirror_vertices(axis, direction, tolerance, use_selection, ignore_side_filter)

        _refresh_influence_list()



    def _on_show_full_model(*_):

        show_full_model()

        _refresh_influence_list()



    cmds.rowLayout(

        numberOfColumns=3,

        adjustableColumn=3,

        columnAttach=[(1, "both", 0), (2, "both", 0), (3, "both", 0)],

    )

    cmds.button(label="镜像权重", height=32, command=_on_mirror)

    cmds.button(label="选中镜像顶点", height=32, command=_on_select_mirror)

    cmds.button(label="显示完整模型", height=32, command=_on_show_full_model)

    cmds.setParent("..")



    def _on_mirror_influence(*_):

        mirror_influence_weights(

            cmds.optionMenu(axis_menu, q=True, value=True),

            cmds.optionMenu(dir_menu, q=True, value=True),

            cmds.floatFieldGrp(tol_field, q=True, value1=True),

            cmds.checkBox(use_sel, q=True, value=True),

            cmds.checkBox(ignore_side, q=True, value=True),

        )

        _refresh_influence_list()



    def _on_select_mirror_influence(*_):

        select_mirror_influence(

            cmds.optionMenu(axis_menu, q=True, value=True),

            cmds.floatFieldGrp(tol_field, q=True, value1=True),

        )

        _refresh_influence_list()



    cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnAttach=[(1, "both", 0), (2, "both", 0)])

    cmds.button(label="镜像骨骼权重", height=28, command=_on_mirror_influence)

    cmds.button(label="选中镜像骨骼", height=28, command=_on_select_mirror_influence)

    cmds.setParent("..")



    # Preset absolute weights for the active influence.

    cmds.rowLayout(

        numberOfColumns=7,

        adjustableColumn=7,

        columnAttach=[(1, "both", 0), (2, "both", 0), (3, "both", 0), (4, "both", 0), (5, "both", 0), (6, "both", 0), (7, "both", 0)],

    )

    for _v in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0):

        cmds.button(label=str(_v).rstrip('0').rstrip('.') if _v not in (0.25, 0.75) else str(_v), height=22, command=lambda _a=None, __v=_v: (_set_influence_weight(__v), _refresh_influence_list()))

    cmds.setParent("..")



    cmds.rowLayout(

        numberOfColumns=5,

        adjustableColumn=3,

        columnWidth5=(70, 70, 95, 35, 90),

        columnAttach=[(1, "both", 0), (2, "both", 0), (3, "both", 0), (4, "both", 0), (5, "both", 0)],

    )

    step_field = None



    def _on_weight_edit(mode):

        _edit_influence_weights(mode, cmds.floatField(step_field, q=True, value=True))

        _refresh_influence_list()



    # Order: buttons first, then step label + value field (so the row aligns left).

    cmds.button(label="+", width=70, height=28, command=lambda *_: _on_weight_edit("add"))

    cmds.button(label="-", width=70, height=28, command=lambda *_: _on_weight_edit("sub"))

    cmds.button(label="平滑权重", height=28, command=lambda *_: _on_weight_edit("smooth"))

    cmds.text(label="步进")

    step_field = cmds.floatField(value=0.001, precision=3, step=0.001, width=80)

    cmds.setParent("..")



    # Vertex weight clipboard / transfer

    cmds.rowLayout(numberOfColumns=4, adjustableColumn=4, columnAttach=[(1, "both", 0), (2, "both", 0), (3, "both", 0), (4, "both", 0)])

    cmds.button(label="Copy", height=26, command=lambda *_: (copy_vertex_weights(), _refresh_influence_list()))

    cmds.button(label="paste", height=26, command=lambda *_: (paste_vertex_weights(), _refresh_influence_list()))

    cmds.button(label="获取权重", height=26, command=lambda *_: (get_transfer_vertex_weights(), _refresh_influence_list()))

    cmds.button(label="剪切权重", height=26, command=lambda *_: (cut_vertex_weights_to_paint_influence(), _refresh_influence_list()))

    cmds.setParent("..")



    # Partial transfer across meshes: copy/paste selected vertices weights.

    cmds.separator(style="none", height=6)

    match_by_id_cb = cmds.checkBox(label="粘贴按顶点ID匹配(同拓扑)", value=True)



    cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnAttach=[(1, "both", 0), (2, "both", 0)])

    cmds.button(label="拷贝模型权重", height=26, command=lambda *_: (copy_model_weights(), _refresh_influence_list()))

    cmds.button(

        label="粘贴模型权重",

        height=26,

        command=lambda *_: (paste_model_weights(bool(cmds.checkBox(match_by_id_cb, q=True, value=True))), _refresh_influence_list()),

    )

    cmds.setParent("..")



    # Joint transfer helpers (export/import) under model weight copy/paste.

    cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnAttach=[(1, "both", 0), (2, "both", 0)])

    cmds.button(label=u"导出骨骼信息", height=26, command=lambda *_: export_selected_joints_json())

    cmds.button(label=u"导入骨骼信息", height=26, command=lambda *_: import_joints_json())

    cmds.setParent("..")



    cmds.separator(style="in")

    cmds.text(label="提示: 使用模型居中对称坐标。", align="left")



    cmds.showWindow(WINDOW_NAME)

    _refresh_influence_list()





def _qt_maya_main_window():

    if QtWidgets is None or wrapInstance is None or omui is None:

        return None

    try:

        ptr = omui.MQtUtil.mainWindow()

        if ptr is None:

            return None

        return wrapInstance(int(ptr), QtWidgets.QWidget)

    except Exception:

        return None





def _swm_get_adv_bg_hex(default      = "#2D3035")       :

    """Query ADV's Qt theme background color so this dialog matches ADV exactly."""

    try:

        import sys



        for m in list(sys.modules.values()):

            if m is None:

                continue

            get_bg = getattr(m, '_adv_qstyle_get_bg_color', None)

            rgb_to_hex = getattr(m, '_adv_qstyle_rgb_to_hex', None)

            if callable(get_bg) and callable(rgb_to_hex):

                try:

                    return str(rgb_to_hex(get_bg()) or default)

                except Exception:

                    continue

    except Exception:

        pass

    return str(default)





def _swm_apply_bg_palette(widget, bg_hex     )        :

    """Force container widgets to paint with a uniform background (fixes stray grey panels)."""

    if widget is None:

        return

    try:

        try:

            from PySide2 import QtGui  # type: ignore

        except ImportError:

            from PySide6 import QtGui  # type: ignore

    except ImportError:

        return

    try:

        bg = QtGui.QColor(str(bg_hex or "#2D3035"))

        base = QtGui.QColor("#1F2127")

        pal = widget.palette()

        # Window/Button cover most container widgets; Base covers viewports in some cases.

        pal.setColor(QtGui.QPalette.Window, bg)

        pal.setColor(QtGui.QPalette.Button, bg)

        pal.setColor(QtGui.QPalette.Base, base)

        pal.setColor(QtGui.QPalette.AlternateBase, bg)

        widget.setPalette(pal)

        widget.setAutoFillBackground(True)

    except Exception:

        pass





def _swm_force_dark_recursive(root_widget, bg_hex     )        :

    """Recursively force background painting for child widgets.



    Maya's embedded Qt style sometimes leaves child containers/viewports in the

    default palette (grey). This function is a brute-force safety net.

    """

    if root_widget is None or QtCore is None or QtWidgets is None:

        return



    try:

        all_children = [root_widget] + list(root_widget.findChildren(QtWidgets.QWidget))

    except Exception:

        all_children = [root_widget]



    # Don't force autofill on interactive controls; it often produces grey bars

    # (notably on QCheckBox) in Maya's embedded Qt.

    try:

        skip_types = (

            QtWidgets.QAbstractButton,

            QtWidgets.QLabel,

            QtWidgets.QLineEdit,

            QtWidgets.QComboBox,

            QtWidgets.QAbstractSpinBox,

            QtWidgets.QAbstractItemView,

            QtWidgets.QTextEdit,

            QtWidgets.QPlainTextEdit,

        )

    except Exception:

        skip_types = tuple()



    for w in all_children:

        try:

            w.setAttribute(QtCore.Qt.WA_StyledBackground, True)

        except Exception:

            pass



        try:

            if skip_types and isinstance(w, skip_types):

                continue

        except Exception:

            pass



        # Only force autofill on container widgets; avoids fighting control-specific styles.

        try:

            if isinstance(

                w,

                (

                    QtWidgets.QDialog,

                    QtWidgets.QFrame,

                    QtWidgets.QGroupBox,

                    QtWidgets.QScrollArea,

                    QtWidgets.QAbstractScrollArea,

                ),

            ):

                _swm_apply_bg_palette(w, bg_hex)

        except Exception:

            pass



        # Viewports are the most common source of stubborn grey.

        try:

            if isinstance(w, QtWidgets.QAbstractScrollArea):

                vp = w.viewport()

                if vp is not None:

                    try:

                        vp.setAttribute(QtCore.Qt.WA_StyledBackground, True)

                    except Exception:

                        pass

                    _swm_apply_bg_palette(vp, bg_hex)

        except Exception:

            pass





def _swm_force_groupboxes_bg(groupboxes, bg_hex     )        :

    """Force QGroupBox panels to paint the same dark background as ADV.



    In Maya's embedded Qt, QGroupBox often ends up drawing a native-looking

    panel with a grey fill. Setting palette alone is sometimes ignored, so we

    also apply a tiny per-widget QSS override.

    """

    if not groupboxes or QtCore is None:

        return

    bg = str(bg_hex or "#2D3035")

    for w in groupboxes:

        if w is None:

            continue

        try:

            w.setAttribute(QtCore.Qt.WA_StyledBackground, True)

        except Exception:

            pass

        _swm_apply_bg_palette(w, bg)

        try:

            name = w.objectName() or "swmSection"

            w.setStyleSheet((w.styleSheet() or "") + ("background-color:%s;" % bg))

        except Exception:

            pass





def _swm_make_section_frame(title     , object_name     ):

    """Create a custom section container to avoid QGroupBox native grey panels."""

    frame = QtWidgets.QFrame()

    frame.setObjectName(object_name)

    frame.setFrameShape(QtWidgets.QFrame.NoFrame)



    v = QtWidgets.QVBoxLayout(frame)

    v.setContentsMargins(10, 10, 10, 10)

    v.setSpacing(6)



    title_lbl = QtWidgets.QLabel(title)

    title_lbl.setObjectName(object_name + "_title")

    v.addWidget(title_lbl)



    content = QtWidgets.QWidget()

    content.setObjectName(object_name + "_content")

    v.addWidget(content, 1)

    return frame, content





def _swm_qt_dark_stylesheet(root_object_name             = None)       :

    """Fallback dark QSS (close to ADV look) when ADV's theme helpers are not reachable."""

    bg = "#2D3035"

    accent = "#2F80ED"

    btn = "#3A3D46"

    btn_hover = "#4A4F5B"

    btn_pressed = "#26282E"



    rules = []

    if root_object_name:

        rules.append('QWidget#%s{background-color:%s;}' % (root_object_name, bg))

    # Force common containers to paint their own background (prevents random grey panels).

    rules.append('QDialog,QMainWindow,QFrame,QGroupBox,QScrollArea,QAbstractScrollArea,QWidget{background-color:%s;color:#D8D8D8;font-size:12px;}' % bg)

    rules.append('QLabel{background:transparent;}')

    rules.append('QGroupBox{border:1px solid #3A3D46;border-radius:8px;margin-top:12px;padding-top:6px;background:transparent;font-weight:600;}')

    rules.append('QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}')

    rules.append('QPushButton{background:%s;border:1px solid #1E2026;border-radius:8px;padding:6px 10px;min-height:22px;}' % btn)

    rules.append('QPushButton:hover{background:%s;}' % btn_hover)

    rules.append('QPushButton:pressed{background:%s;}' % btn_pressed)

    rules.append('QLineEdit,QTextEdit,QPlainTextEdit,QComboBox,QSpinBox,QDoubleSpinBox,QListWidget{background:#1F2127;border:1px solid #14151A;border-radius:8px;padding:4px 6px;}')

    rules.append('QListWidget::item{background:transparent;}')

    rules.append('QListWidget::item:selected{background:%s;color:#FFFFFF;}' % accent)

    rules.append('QComboBox::drop-down{border:0px;width:18px;}')

    rules.append('QComboBox:hover{border:1px solid %s;}' % accent)

    rules.append('QComboBox QAbstractItemView{background:#1F2127;color:#D8D8D8;selection-background-color:%s;selection-color:#FFFFFF;outline:0px;}' % accent)

    rules.append('QMenu{background:#1F2127;color:#D8D8D8;border:1px solid #14151A;}')

    rules.append('QMenu::item:selected{background:%s;color:#FFFFFF;}' % accent)

    rules.append('QCheckBox{spacing:6px;}')

    rules.append('QCheckBox::indicator{width:12px;height:12px;border-radius:6px;border:1px solid #14151A;background:transparent;}')

    rules.append('QCheckBox::indicator:checked{background:%s;border:1px solid %s;}' % (accent, accent))

    rules.append('QScrollBar:vertical{background:transparent;width:12px;margin:0px;}')

    rules.append('QScrollBar::handle:vertical{background:#4A4F5B;border-radius:6px;min-height:24px;}')

    rules.append('QScrollBar::handle:vertical:hover{background:#5A6170;}')

    rules.append('QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0px;}')

    rules.append('QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:none;}')

    return ''.join(rules)





def _swm_apply_button_styles(widget):

    """Force button colors so all buttons consistently match UI6-like tones."""

    if widget is None or QtWidgets is None:

        return

    base = "#3F444F"

    hov = "#4A505C"

    pre = "#2C3038"

    base_css = (

        "QPushButton{background:%s;border:1px solid #1E2026;border-radius:8px;padding:4px 8px;min-height:20px;}"

        "QPushButton:hover{background:%s;}"

        "QPushButton:pressed{background:%s;}" % (base, hov, pre)

    )

    try:

        buttons = widget.findChildren(QtWidgets.QPushButton) or []

    except Exception:

        buttons = []

    for b in buttons:

        try:

            b.setStyleSheet(base_css)

        except Exception:

            pass





def _swm_qt_qss_patch(bg_hex     )       :

    """Small override patch to eliminate unstyled grey areas under Maya/Qt."""

    bg = str(bg_hex or "#2D3035")

    inp = "#1F2127"

    # Force generic QWidget backgrounds to match the window background.

    # Then re-apply input widgets to a slightly darker fill.

    btn = "#3F444F"

    btn_hover = "#4A505C"

    btn_pressed = "#2C3038"

    return (

        ('QWidget{background-color:%s;}' % bg)

        + ('QWidget#chanaiToolsSkinWeightMirrorQt{background-color:%s;}' % bg)

        + ('QWidget#chanaiToolsSkinWeightMirrorQt QGroupBox{background-color:%s;}' % bg)

        + ('QWidget#chanaiToolsSkinWeightMirrorQt QPushButton{background:%s;border:1px solid #1E2026;border-radius:8px;padding:4px 8px;min-height:20px;}' % btn)

        + ('QWidget#chanaiToolsSkinWeightMirrorQt QPushButton:hover{background:%s;}' % btn_hover)

        + ('QWidget#chanaiToolsSkinWeightMirrorQt QPushButton:pressed{background:%s;}' % btn_pressed)

        + ('QDialog,QMainWindow,QFrame,QGroupBox,QScrollArea,QAbstractScrollArea{background-color:%s;}' % bg)

        + ('QAbstractScrollArea::viewport{background-color:%s;}' % bg)

        + ('QFrame#swmGroupSettings,QFrame#swmGroupInfluence,QFrame#swmGroupEdit{background-color:%s;border:1px solid #3A3D46;border-radius:8px;}' % bg)

        + ('QWidget#swmGroupSettings_content,QWidget#swmGroupInfluence_content,QWidget#swmGroupEdit_content{background-color:%s;}' % bg)

        + 'QLabel#swmGroupSettings_title,QLabel#swmGroupInfluence_title,QLabel#swmGroupEdit_title{background:transparent;font-weight:600;}'

        + 'QFrame#swmGroupSettings QAbstractButton,QFrame#swmGroupInfluence QAbstractButton,QFrame#swmGroupEdit QAbstractButton{background:transparent;}'

        + ('QGroupBox QWidget{background-color:%s;}' % bg)

        + 'QGroupBox::title{background:transparent;}'

        + 'QLabel,QCheckBox{background:transparent;}'

        + 'QFrame{background:transparent;}'

        + ('QLineEdit,QTextEdit,QPlainTextEdit,QComboBox,QSpinBox,QDoubleSpinBox,QListWidget{background:%s;}' % inp)

        + ('QListWidget::viewport{background:%s;}' % inp)

        + ('QAbstractItemView{background:%s;}' % inp)

    )





def _try_apply_adv_qstyle(widget, object_name             = None, allow_bg_image       = False)        :

    """Try to reuse ADV's global Qt theme if ADV is loaded in the same Maya session."""

    try:

        import sys



        for m in list(sys.modules.values()):

            if m is None:

                continue

            fn = getattr(m, '_adv_apply_qstyle_to_qt_widget', None)

            is_enabled = getattr(m, '_adv_qstyle_is_enabled', None)

            if callable(fn):

                try:

                    enabled = bool(is_enabled(default=True)) if callable(is_enabled) else True

                except Exception:

                    enabled = True

                try:

                    return bool(fn(widget, enabled=enabled, object_name=object_name, allow_bg_image=allow_bg_image))

                except Exception:

                    return False

    except Exception:

        pass

    return False

    try:

        ptr = omui.MQtUtil.mainWindow()

        if ptr is None:

            return None

        return wrapInstance(int(ptr), QtWidgets.QWidget)

    except Exception:

        return None





class _SkinWeightMirrorDialog(QtWidgets.QDialog):

    def __init__(self, parent=None):

        super(_SkinWeightMirrorDialog, self).__init__(parent)

        self.setObjectName("chanaiToolsSkinWeightMirrorQt")

        self.setWindowTitle(u"蒙皮权重镜像 (Qt)  [%s]" % _SWM_QT_BUILD)

        self.setMinimumWidth(420)

        self.resize(520, 640)



        # Match ADV's global background color (optionVar-driven).

        self._bg_hex = _swm_get_adv_bg_hex()



        self._script_job_id = None

        self._refresh_guard = False



        root = QtWidgets.QVBoxLayout(self)

        root.setContentsMargins(10, 10, 10, 10)

        root.setSpacing(8)



        # -------- Settings --------

        gb, gb_content = _swm_make_section_frame(u"镜像设置", "swmGroupSettings")

        root.addWidget(gb)

        _swm_apply_bg_palette(gb, self._bg_hex)

        g = QtWidgets.QGridLayout(gb_content)

        g.setContentsMargins(0, 0, 0, 0)

        g.setHorizontalSpacing(4)

        g.setVerticalSpacing(6)



        axis_lbl = QtWidgets.QLabel(u"镜像轴")

        try:

            axis_lbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        except Exception:

            pass

        self.axis_cb = QtWidgets.QComboBox()

        self.axis_cb.addItems(["X", "Y", "Z"])

        dir_lbl = QtWidgets.QLabel(u"方向")

        try:

            dir_lbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        except Exception:

            pass

        self.dir_cb = QtWidgets.QComboBox()

        self.dir_cb.addItems(["L->R", "R->L"])

        tol_lbl = QtWidgets.QLabel(u"侧向阈值")

        try:

            tol_lbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        except Exception:

            pass

        self.tol_sp = _swm_make_double_spinbox()

        self.tol_sp.setDecimals(6)

        self.tol_sp.setRange(0.0, 999999.0)

        self.tol_sp.setSingleStep(0.001)

        self.tol_sp.setValue(0.001)



        self.use_sel_cb = QtWidgets.QCheckBox(u"仅使用选择顶点")

        self.use_sel_cb.setChecked(True)

        self.ignore_side_cb = QtWidgets.QCheckBox(u"忽略方向过滤(全模型匹配)")

        self.swap_lr_cb = QtWidgets.QCheckBox(u"镜像骨骼L/R名称")

        self.swap_lr_cb.setChecked(True)

        try:

            self.axis_cb.setFixedWidth(90)

            self.dir_cb.setFixedWidth(90)

            self.tol_sp.setFixedWidth(110)

        except Exception:

            pass



        g.addWidget(axis_lbl, 0, 0)

        g.addWidget(self.axis_cb, 0, 1)

        g.addWidget(dir_lbl, 0, 2)

        g.addWidget(self.dir_cb, 0, 3)

        g.addWidget(tol_lbl, 1, 0)

        g.addWidget(self.tol_sp, 1, 1)

        g.addWidget(self.use_sel_cb, 2, 0, 1, 2)

        g.addWidget(self.ignore_side_cb, 2, 2, 1, 2)

        g.addWidget(self.swap_lr_cb, 3, 0, 1, 2)



        try:

            g.setColumnStretch(0, 0)

            g.setColumnStretch(1, 0)

            g.setColumnStretch(2, 0)

            g.setColumnStretch(3, 0)

            g.setColumnStretch(4, 1)

            g.addItem(

                QtWidgets.QSpacerItem(0, 0, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum),

                0,

                4,

                1,

                1,

            )

        except Exception:

            pass



        btn_row = QtWidgets.QHBoxLayout()

        self.mirror_btn = QtWidgets.QPushButton(u"镜像权重")

        self.select_mirror_btn = QtWidgets.QPushButton(u"选中镜像顶点")

        self.show_full_mesh_btn = QtWidgets.QPushButton(u"显示完整模型")

        btn_row.addWidget(self.mirror_btn)

        btn_row.addWidget(self.select_mirror_btn)

        btn_row.addWidget(self.show_full_mesh_btn)

        g.addLayout(btn_row, 4, 0, 1, 4)



        # -------- Influence list --------

        gb2, gb2_content = _swm_make_section_frame(u"选中顶点影响骨骼", "swmGroupInfluence")

        root.addWidget(gb2, 1)

        _swm_apply_bg_palette(gb2, self._bg_hex)

        v = QtWidgets.QVBoxLayout(gb2_content)

        v.setContentsMargins(0, 0, 0, 0)

        v.setSpacing(6)

        self.infl_list = QtWidgets.QListWidget()

        self.infl_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)

        v.addWidget(self.infl_list, 1)



        infl_btn_row = QtWidgets.QHBoxLayout()

        self.mirror_infl_btn = QtWidgets.QPushButton(u"镜像骨骼权重")

        self.select_mirror_infl_btn = QtWidgets.QPushButton(u"选中镜像骨骼")

        self.refresh_btn = QtWidgets.QPushButton(u"刷新")

        infl_btn_row.addWidget(self.mirror_infl_btn)

        infl_btn_row.addWidget(self.select_mirror_infl_btn)

        infl_btn_row.addWidget(self.refresh_btn)

        v.addLayout(infl_btn_row)



        # -------- Weight edit / clipboard --------

        gb3, gb3_content = _swm_make_section_frame(u"编辑/拷贝", "swmGroupEdit")

        root.addWidget(gb3)

        _swm_apply_bg_palette(gb3, self._bg_hex)

        b = QtWidgets.QVBoxLayout(gb3_content)

        b.setContentsMargins(0, 0, 0, 0)

        b.setSpacing(6)



        step_row = QtWidgets.QHBoxLayout()

        # Presets: absolute weights for the active influence.

        preset_row = QtWidgets.QHBoxLayout()

        self.preset_buttons = []

        for v in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0):

            b0 = QtWidgets.QPushButton(str(v).rstrip('0').rstrip('.') if v not in (0.25, 0.75) else str(v))

            b0.setFixedHeight(22)

            b0.clicked.connect(lambda _=False, __v=v: (_set_influence_weight(__v), self.refresh()))

            preset_row.addWidget(b0)

            self.preset_buttons.append(b0)

        b.addLayout(preset_row)



        self.add_btn = QtWidgets.QPushButton(u"+")

        self.sub_btn = QtWidgets.QPushButton(u"-")

        self.smooth_btn = QtWidgets.QPushButton(u"平滑权重")

        try:

            self.add_btn.setMinimumWidth(80)

            self.sub_btn.setMinimumWidth(80)

        except Exception:

            pass

        self.step_sp = _swm_make_double_spinbox()

        self.step_sp.setDecimals(6)

        self.step_sp.setRange(0.0, 999999.0)

        self.step_sp.setSingleStep(0.001)

        self.step_sp.setValue(0.001)

        step_row.addWidget(self.add_btn)

        step_row.addWidget(self.sub_btn)

        step_row.addWidget(self.smooth_btn)

        step_row.addStretch(1)

        step_row.addWidget(QtWidgets.QLabel(u"步进"))

        step_row.addWidget(self.step_sp)

        b.addLayout(step_row)



        # Vertex weight clipboard / transfer in one row.

        tr_row = QtWidgets.QHBoxLayout()

        self.copy_vtx_btn = QtWidgets.QPushButton(u"Copy")

        self.paste_vtx_btn = QtWidgets.QPushButton(u"paste")

        self.get_transfer_btn = QtWidgets.QPushButton(u"获取权重")

        self.cut_vtx_btn = QtWidgets.QPushButton(u"剪切权重")

        tr_row.addWidget(self.copy_vtx_btn)

        tr_row.addWidget(self.paste_vtx_btn)

        tr_row.addWidget(self.get_transfer_btn)

        tr_row.addWidget(self.cut_vtx_btn)

        b.addLayout(tr_row)



        self.match_by_id_cb = QtWidgets.QCheckBox(u"粘贴按顶点ID匹配(同拓扑)")

        self.match_by_id_cb.setChecked(True)

        b.addWidget(self.match_by_id_cb)



        cp_row2 = QtWidgets.QHBoxLayout()

        self.copy_model_btn = QtWidgets.QPushButton(u"拷贝模型权重")

        self.paste_model_btn = QtWidgets.QPushButton(u"粘贴模型权重")

        cp_row2.addWidget(self.copy_model_btn)

        cp_row2.addWidget(self.paste_model_btn)

        b.addLayout(cp_row2)



        jt_row = QtWidgets.QHBoxLayout()

        self.export_jnt_btn = QtWidgets.QPushButton(u"导出骨骼信息")

        self.import_jnt_btn = QtWidgets.QPushButton(u"导入骨骼信息")

        jt_row.addWidget(self.export_jnt_btn)

        jt_row.addWidget(self.import_jnt_btn)

        b.addLayout(jt_row)



        tip = QtWidgets.QLabel(u"提示: 使用模型居中对称坐标。")

        tip.setWordWrap(True)

        root.addWidget(tip)



        # Keep references so we can force their painting after applying ADV theme/QSS.

        self._section_groupboxes = [gb, gb2, gb3]



        # Signals

        self.mirror_btn.clicked.connect(self._on_mirror)

        self.select_mirror_btn.clicked.connect(self._on_select_mirror)

        self.mirror_infl_btn.clicked.connect(self._on_mirror_influence)

        self.select_mirror_infl_btn.clicked.connect(self._on_select_mirror_influence)

        self.refresh_btn.clicked.connect(self.refresh)

        self.infl_list.itemSelectionChanged.connect(self._on_influence_selected)



        self.add_btn.clicked.connect(lambda: self._on_weight_edit("add"))

        self.sub_btn.clicked.connect(lambda: self._on_weight_edit("sub"))

        self.smooth_btn.clicked.connect(lambda: self._on_weight_edit("smooth"))

        self.copy_vtx_btn.clicked.connect(lambda: (copy_vertex_weights(), self.refresh()))

        self.paste_vtx_btn.clicked.connect(lambda: (paste_vertex_weights(), self.refresh()))

        self.cut_vtx_btn.clicked.connect(lambda: (cut_vertex_weights_to_paint_influence(), self.refresh()))

        self.get_transfer_btn.clicked.connect(lambda: (get_transfer_vertex_weights(), self.refresh()))

        self.show_full_mesh_btn.clicked.connect(lambda: (show_full_model(), self.refresh()))

        self.copy_model_btn.clicked.connect(lambda: (copy_model_weights(), self.refresh()))

        self.paste_model_btn.clicked.connect(lambda: (paste_model_weights(bool(self.match_by_id_cb.isChecked())), self.refresh()))

        self.export_jnt_btn.clicked.connect(lambda: export_selected_joints_json())

        self.import_jnt_btn.clicked.connect(lambda: import_joints_json())



        self._install_script_job()

        self.refresh()



        # Make it look like ADV's dark Qt theme when possible.

        try:

            self.setAttribute(QtCore.Qt.WA_StyledBackground, True)

        except Exception:

            pass

        try:

            self.setAutoFillBackground(True)

        except Exception:

            pass



        if _try_apply_adv_qstyle(self, object_name=self.objectName(), allow_bg_image=False):

            try:

                # Patch on top of ADV theme to avoid any remaining Maya/Qt grey panels.

                self.setStyleSheet((self.styleSheet() or '') + _swm_qt_qss_patch(self._bg_hex))

            except Exception:

                pass

        else:

            self.setStyleSheet(_swm_qt_dark_stylesheet(root_object_name=self.objectName()) + _swm_qt_qss_patch(self._bg_hex))



        # Ensure all buttons match the intended brightness (ADV-like).

        try:

            _swm_apply_button_styles(self)

        except Exception:

            pass



        # Extra safety: force the top-level background to paint.

        _swm_apply_bg_palette(self, self._bg_hex)

        _swm_force_dark_recursive(self, self._bg_hex)

        _swm_force_groupboxes_bg(getattr(self, '_section_groupboxes', None), self._bg_hex)



    def _install_script_job(self):

        try:

            if self._script_job_id:

                cmds.scriptJob(kill=self._script_job_id, force=True)

        except Exception:

            pass

        try:

            self._script_job_id = cmds.scriptJob(event=["SelectionChanged", self.refresh], protected=True)

        except Exception:

            self._script_job_id = None



    def closeEvent(self, event):

        try:

            if self._script_job_id:

                cmds.scriptJob(kill=self._script_job_id, force=True)

        except Exception:

            pass

        self._script_job_id = None

        return super(_SkinWeightMirrorDialog, self).closeEvent(event)



    def _settings(self):

        axis = str(self.axis_cb.currentText())

        direction = str(self.dir_cb.currentText())

        tolerance = float(self.tol_sp.value())

        use_selection = bool(self.use_sel_cb.isChecked())

        ignore_side_filter = bool(self.ignore_side_cb.isChecked())

        swap_lr_influences = bool(self.swap_lr_cb.isChecked())

        return axis, direction, tolerance, use_selection, ignore_side_filter, swap_lr_influences



    def refresh(self):

        if self._refresh_guard:

            return

        self._refresh_guard = True

        try:

            self.infl_list.clear()

            mesh = _get_mesh_from_selection()

            if not mesh:

                return

            skin = _get_skin_cluster(mesh)

            if not skin:

                return

            verts = _get_selected_vertices(mesh)

            if not verts:

                return

            # cap

            if len(verts) > 800:

                verts = verts[:800]



            # Reuse the same aggregation logic as cmds UI (fast if OpenMaya available).

            items = []

            infl_label_map = {}

            try:

                if om2 is not None and oma2 is not None:

                    shape = _get_mesh_shape(mesh)

                    if shape:

                        fn_skin = _om_skin_fn(skin)

                        mesh_dag = _om_dagpath(shape)

                        inf_paths = fn_skin.influenceObjects() or []

                        inf_full = [p.fullPathName() for p in inf_paths]

                        full_to_index = {n: i for i, n in enumerate(inf_full)}



                        infl_cmds = cmds.skinCluster(skin, q=True, inf=True) or []

                        idx_map = {}

                        for j in infl_cmds:

                            lp = (cmds.ls(j, l=True) or [j])[0]

                            ii = full_to_index.get(lp)

                            if ii is None:

                                leaf = lp.split("|")[-1]

                                hits = [k for k, n in enumerate(inf_full) if n.split("|")[-1] == leaf]

                                if len(hits) == 1:

                                    ii = hits[0]

                            if ii is not None:

                                idx_map[j] = int(ii)



                        if idx_map:

                            comp_fn = om2.MFnSingleIndexedComponent()

                            comp_obj = comp_fn.create(om2.MFn.kMeshVertComponent)

                            comp_fn.addElements([int(v) for v in verts])

                            weights, inf_count = fn_skin.getWeights(mesh_dag, comp_obj)

                            inf_count = int(inf_count)

                            vcount = int(len(verts))

                            total = {j: 0.0 for j in idx_map.keys()}

                            for vi in range(vcount):

                                off = vi * inf_count

                                for j, ii in idx_map.items():

                                    total[j] += float(weights[off + ii])

                            pinned = []

                            try:

                                cur = _resolve_influence_for_skin(skin, _get_current_paint_influence())

                            except Exception:

                                cur = ""

                            try:

                                ui = _resolve_influence_for_skin(skin, str(_LAST_UI_SELECTED_INFLUENCE[0] or ""))

                            except Exception:

                                ui = ""

                            for _p in (cur, ui):

                                if _p and (_p not in pinned):

                                    pinned.append(_p)



                            for j, sum_w in total.items():

                                avg = sum_w / float(vcount)

                                if (avg > 0.0001) or (j in pinned):

                                    label = "%s  (%.4f)" % (j, avg)

                                    infl_label_map[label] = j

                                    items.append(label)

            except Exception:

                items = []



            if not items:

                infl = _get_influences(skin)

                if not infl:

                    return

                total = {j: 0.0 for j in infl}

                for vid in verts:

                    w = _get_vertex_weights(skin, mesh, int(vid), infl)

                    for jnt, vv in w.items():

                        total[jnt] += float(vv)

                count = float(len(verts))

                pinned = []

                try:

                    cur = _resolve_influence_for_skin(skin, _get_current_paint_influence())

                except Exception:

                    cur = ""

                try:

                    ui = _resolve_influence_for_skin(skin, str(_LAST_UI_SELECTED_INFLUENCE[0] or ""))

                except Exception:

                    ui = ""

                for _p in (cur, ui):

                    if _p and (_p not in pinned):

                        pinned.append(_p)



                for jnt, sum_w in total.items():

                    avg_w = sum_w / count

                    if (avg_w > 0.0001) or (jnt in pinned):

                        label = "%s  (%.4f)" % (jnt, avg_w)

                        infl_label_map[label] = jnt

                        items.append(label)



            # Store map on instance for selection callback.

            self._infl_label_map = infl_label_map

            for it in sorted(items):

                self.infl_list.addItem(it)

        finally:

            self._refresh_guard = False



    def _on_influence_selected(self):

        try:

            items = self.infl_list.selectedItems() or []

        except Exception:

            items = []

        if not items:

            return

        label = str(items[0].text())

        influence = None

        try:

            influence = getattr(self, "_infl_label_map", {}).get(label, label)

        except Exception:

            influence = label

        try:

            _LAST_UI_SELECTED_INFLUENCE[0] = str(influence or "")

        except Exception:

            pass

        mesh = _get_mesh_from_selection()

        if not mesh:

            return

        skin = _get_skin_cluster(mesh)

        if not skin:

            return

        influence_full = (cmds.ls(influence, l=True) or [influence])[0]

        _focus_paint_influence(skin, influence_full)



    def _on_mirror(self):

        axis, direction, tolerance, use_selection, ignore_side_filter, swap_lr_influences = self._settings()

        mirror_skin_weights(axis, direction, tolerance, use_selection, ignore_side_filter, swap_lr_influences)

        self.refresh()



    def _on_select_mirror(self):

        axis, direction, tolerance, use_selection, ignore_side_filter, _ = self._settings()

        select_mirror_vertices(axis, direction, tolerance, use_selection, ignore_side_filter)

        self.refresh()



    def _on_mirror_influence(self):

        axis, direction, tolerance, use_selection, ignore_side_filter, _ = self._settings()

        mirror_influence_weights(axis, direction, tolerance, use_selection, ignore_side_filter)

        self.refresh()



    def _on_select_mirror_influence(self):

        axis, _, tolerance, _, _, _ = self._settings()

        select_mirror_influence(axis, tolerance)

        self.refresh()



    def _on_weight_edit(self, mode     ):

        _edit_influence_weights(mode, float(self.step_sp.value()))

        self.refresh()





_QT_DIALOG = None





def show_qt():

    """Show Qt-style UI (PySide2/6)."""

    global _QT_DIALOG

    if QtWidgets is None:

        cmds.warning(u"当前 Maya 环境未找到 PySide2/6，无法打开 Qt 界面。")

        return



    try:

        if _QT_DIALOG is not None:

            _QT_DIALOG.close()

            _QT_DIALOG.deleteLater()

    except Exception:

        pass

    _QT_DIALOG = None



    parent = _qt_maya_main_window()

    dlg = _SkinWeightMirrorDialog(parent)

    dlg.setWindowFlags(dlg.windowFlags() | QtCore.Qt.Window)

    dlg.show()

    dlg.raise_()

    dlg.activateWindow()

    _QT_DIALOG = dlg





def showQt():

    """Alias for show_qt()."""

    return show_qt()





# Auto-run when the script is executed directly (e.g., drag & drop into Maya).

if __name__ == "__main__":

    try:

        show()

    except Exception as exc:

        cmds.warning("启动蒙皮权重镜像工具失败: %s" % exc)
