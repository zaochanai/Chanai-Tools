# -*- coding: utf-8 -*-
import io
import os
import time

import maya.cmds as cmds
import maya.mel as mel
import maya.utils as maya_utils

try:
    from PySide2 import QtWidgets, QtCore
    from shiboken2 import wrapInstance
except ImportError:
    from PySide import QtWidgets, QtCore
    from shiboken import wrapInstance

import maya.OpenMayaUI as omui


_WINDOW_OBJECT_NAME = "chanaiToolsBipWindow"
_UI_VERSION = 4
_BOOKMARK_PREFIX = "chanai_tools_bipMark_"
_DRIVER_ATTR_NAME = "FKIKBlend"
_BLACK_VALUE_MAX = 9.999
_VALUE_YELLOW = 10.0
_OPTIONVAR_MAYA_PY_PATH = "chanai_tools_maya_py_path"
_OPTIONVAR_PREV_HOTKEY_S = "chanai_tools_bip_prevHotkey_s"
_OPTIONVAR_DIAG_ENABLED = "chanai_tools_bip_diag_enabled"
_OPTIONVAR_MARKS_ENABLED = "chanai_tools_bip_marks_enabled"
_RUNTIME_CMD = "chanaiToolsBip_SetKeyAndRefresh"
_NAME_CMD = "chanaiToolsBip_SetKeyAndRefreshNameCmd"
_HOTKEY_CHAR = "s"
_BOOKMARK_STEP_PREFIX = _BOOKMARK_PREFIX + "step_"
_STEP_ORANGE = (1.0, 0.55, 0.0)
# New name (what the user sees on controllers). Keep legacy support so existing
# scenes don't break.
_STEP_ATTR_NAME = "Tread"
_STEP_ATTR_NAME_LEGACY = "chanaiToolsBipStepFrame"
_STEP_LABEL = "Tread"
_WIN_INSTANCE = None


def _force_time_slider_redraw():
    """Best-effort: force Maya to redraw time slider bookmark overlays.

    Some Maya builds keep drawing stale bookmark overlays until a UI redraw or
    a time update happens. This function is defensive and must never raise.
    """
    try:
        cur = cmds.currentTime(query=True)
        cmds.currentTime(cur, update=True)
    except Exception:
        pass
    try:
        cmds.refresh(force=True)
    except Exception:
        pass

    # Poke timeControl widgets; flags vary across versions.
    try:
        controls = _time_slider_controls()
    except Exception:
        controls = []
    for control in controls:
        for flag in ("redraw", "refresh"):
            try:
                cmds.timeControl(control, edit=True, **{flag: True})
                break
            except Exception:
                continue


# Maya versions that don't ship the timeSliderBookmark node type will emit
# warnings like "Unknown object type: timeSliderBookmark" if we call
# cmds.ls(type='timeSliderBookmark'). Guard all such calls.
_BOOKMARK_NODETYPE = "timeSliderBookmark"
_BOOKMARK_NODETYPE_AVAILABLE = None


def _bookmark_nodetype_available(refresh=False):
    """Return True if the timeSliderBookmark node type exists in this Maya."""
    global _BOOKMARK_NODETYPE_AVAILABLE
    if refresh:
        _BOOKMARK_NODETYPE_AVAILABLE = None
    if _BOOKMARK_NODETYPE_AVAILABLE is not None:
        return bool(_BOOKMARK_NODETYPE_AVAILABLE)
    try:
        _BOOKMARK_NODETYPE_AVAILABLE = _BOOKMARK_NODETYPE in (cmds.allNodeTypes() or [])
    except Exception:
        _BOOKMARK_NODETYPE_AVAILABLE = False
    return bool(_BOOKMARK_NODETYPE_AVAILABLE)


def _diag_log_path():
    # Requested: write diagnostics into this package folder.
    try:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "tread_diagnostic.log")
    except Exception:
        return os.path.join(os.getcwd(), "tread_diagnostic.log")


def _diag_enabled():
    try:
        if cmds.optionVar(exists=_OPTIONVAR_DIAG_ENABLED):
            return bool(cmds.optionVar(q=_OPTIONVAR_DIAG_ENABLED))
    except Exception:
        pass
    # Default ON (user explicitly requested diagnostics).
    return True


def _marks_enabled():
    try:
        if cmds.optionVar(exists=_OPTIONVAR_MARKS_ENABLED):
            return bool(cmds.optionVar(q=_OPTIONVAR_MARKS_ENABLED))
    except Exception:
        pass
    return True


def _set_marks_enabled(state):
    """Persist whether BIP marks should be shown (used by UI + S-hotkey hook)."""
    try:
        cmds.optionVar(intValue=(_OPTIONVAR_MARKS_ENABLED, 1 if state else 0))
    except Exception:
        pass


def _strip_namespace(name):
    """Return short name without DAG path and without namespace."""
    try:
        n = str(name).split("|")[-1]
    except Exception:
        n = str(name)
    if ":" in n:
        try:
            n = n.rsplit(":", 1)[1]
        except Exception:
            pass
    return n


def _infer_fkik_switch_short_from_selection(sel):
    """Best-effort: infer which FKIK switch control should be active.

    Users often select IK controls like IKArm_R / IKLeg_L etc instead of the
    FKIK switch control itself. If we always fall back to scene-wide search,
    we tend to pick FKIKArm_L due to preference ordering.
    """
    if not sel:
        return None
    base = _strip_namespace(sel[-1])
    low = base.lower()

    # Common AdvancedSkeleton naming.
    if "arm" in low:
        if "_r" in low or "right" in low or "armr" in low or "arm_r" in low:
            return "FKIKArm_R"
        if "_l" in low or "left" in low or "arml" in low or "arm_l" in low:
            return "FKIKArm_L"

    if "leg" in low:
        if "_r" in low or "right" in low or "legr" in low or "leg_r" in low:
            return "FKIKLeg_R"
        if "_l" in low or "left" in low or "legl" in low or "leg_l" in low:
            return "FKIKLeg_L"

    if "spine" in low:
        return "FKIKSpine_M"
    return None


def _diag_write(lines):
    """Append diagnostic lines to a log file (best-effort, never raises)."""
    if not _diag_enabled():
        return
    if not lines:
        return
    try:
        if isinstance(lines, (str, bytes)):
            lines = [lines]
    except Exception:
        lines = [str(lines)]

    try:
        path = _diag_log_path()
        try:
            with io.open(path, 'a', encoding='utf-8') as f:
                for ln in lines:
                    try:
                        f.write(str(ln) + "\n")
                    except Exception:
                        pass
        except TypeError:
            with open(path, 'a') as f:
                for ln in lines:
                    try:
                        f.write(str(ln) + "\n")
                    except Exception:
                        pass
    except Exception:
        pass


def _diag_snapshot(tag, frame=None, nodes=None, extra=None):
    """Capture a snapshot of current state for debugging Tread behavior."""
    try:
        ver = ""
        try:
            ver = cmds.about(version=True)
        except Exception:
            ver = ""

        try:
            cur = cmds.currentTime(query=True)
        except Exception:
            cur = None
        if frame is None:
            frame = cur

        if nodes is None:
            try:
                nodes = _selected_nodes()
            except Exception:
                nodes = []

        driver = None
        try:
            driver = _active_driver_attr()
        except Exception:
            driver = None

        key_times = []
        try:
            key_times = _get_driver_key_times()
        except Exception:
            key_times = []

        prev_t = None
        try:
            prev_t = _prev_key_before(key_times, frame)
        except Exception:
            prev_t = None

        step_exists = False
        try:
            step_exists = bool(cmds.objExists(_step_node_name(frame)))
        except Exception:
            step_exists = False

        lines = []
        lines.append("=" * 70)
        lines.append("TAG: {}".format(tag))
        lines.append("Maya: {}".format(ver))
        lines.append("Frame: {} (current={})".format(frame, cur))
        lines.append("Driver: {}".format(driver))
        lines.append("DriverKeyTimes(count={}): {}".format(len(key_times), key_times[:30]))
        lines.append("PrevKeyBefore: {}".format(prev_t))
        lines.append("TreadBookmarkExists: {}".format(step_exists))
        lines.append("Nodes(count={}): {}".format(len(nodes or []), nodes))

        for n in (nodes or [])[:20]:
            lines.append("-- Node: {}".format(n))
            # Step attr plugs
            for an in (_STEP_ATTR_NAME, _STEP_ATTR_NAME_LEGACY):
                plug = "{}.{}".format(n, an)
                try:
                    ex = bool(cmds.objExists(plug))
                except Exception:
                    ex = False
                if not ex:
                    continue
                try:
                    v = cmds.getAttr(plug, time=float(frame))
                except Exception:
                    v = "<getAttr failed>"
                lines.append("   attr {} = {}".format(plug, v))

            for axis in ("X", "Y", "Z"):
                plug = "{}.translate{}".format(n, axis)
                try:
                    lock = cmds.getAttr(plug, lock=True)
                except Exception:
                    lock = "?"
                try:
                    conn = cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
                except Exception:
                    conn = []
                try:
                    v_now = cmds.getAttr(plug, time=float(frame))
                except Exception:
                    v_now = "<getAttr failed>"
                v_prev = None
                if prev_t is not None:
                    try:
                        v_prev = cmds.getAttr(plug, time=float(prev_t))
                    except Exception:
                        v_prev = "<getAttr failed>"
                lines.append("   {} lock={} now={} prev@{}={} conn={}".format(plug, lock, v_now, prev_t, v_prev, conn))

        if extra:
            lines.append("EXTRA: {}".format(extra))
        _diag_write(lines)
    except Exception as exc:
        _diag_write(["diag_snapshot failed: {}".format(exc)])


def _step_attr_plug(node):
    """Return the plug name to use for the step/tread flag on this node."""
    if not node:
        return None
    new_plug = "{}.{}".format(node, _STEP_ATTR_NAME)
    legacy_plug = "{}.{}".format(node, _STEP_ATTR_NAME_LEGACY)
    try:
        if cmds.objExists(new_plug):
            return new_plug
    except Exception:
        pass
    try:
        if cmds.objExists(legacy_plug):
            return legacy_plug
    except Exception:
        pass
    return new_plug


# AdvancedSkeleton commonly uses these FKIK switch controls.
_FKIK_CTRL_PREFERRED = (
    "FKIKArm_L",
    "FKIKArm_R",
    "FKIKLeg_L",
    "FKIKLeg_R",
    "FKIKSpine_M",
)


def _with_undo_suspended(fn):
    """Run fn() without affecting the user's undo queue (best-effort)."""
    prev = None
    try:
        prev = bool(cmds.undoInfo(q=True, stateWithoutFlush=True))
    except Exception:
        prev = None

    try:
        # Disable undo recording without flushing.
        try:
            cmds.undoInfo(stateWithoutFlush=False)
        except Exception:
            pass

        return fn()
    finally:
        # Restore prior state (default to enabled).
        try:
            if prev is None or prev is True:
                cmds.undoInfo(stateWithoutFlush=True)
        except Exception:
            pass


def _with_undo_and_autokey_suspended(fn):
    """Run fn() without adding undo steps and without triggering autokey (best-effort)."""
    prev_auto = None
    try:
        prev_auto = bool(cmds.autoKeyframe(query=True, state=True))
    except Exception:
        prev_auto = None

    def _do():
        try:
            if prev_auto:
                cmds.autoKeyframe(state=False)
        except Exception:
            pass
        return fn()

    try:
        return _with_undo_suspended(_do)
    finally:
        try:
            if prev_auto:
                cmds.autoKeyframe(state=True)
        except Exception:
            pass


def _ensure_step_attr(node):
    """Ensure the per-controller step/slide boolean attr exists."""
    if not node:
        return None
    # Always ensure the new attribute exists so the user sees "Tread" in channel box.
    new_plug = "{}.{}".format(node, _STEP_ATTR_NAME)
    try:
        if not cmds.objExists(new_plug):
            cmds.addAttr(node, longName=_STEP_ATTR_NAME, attributeType="bool", keyable=True)
    except Exception:
        pass
    # Return whichever exists (prefer new).
    try:
        if cmds.objExists(new_plug):
            return new_plug
    except Exception:
        pass
    legacy_plug = "{}.{}".format(node, _STEP_ATTR_NAME_LEGACY)
    try:
        if cmds.objExists(legacy_plug):
            return legacy_plug
    except Exception:
        pass
    return None


def _set_step_attr_key(nodes, enabled):
    """Set + key the step attribute (enabled=True means step frame, False means slide frame)."""
    nodes = [n for n in (nodes or []) if n]
    if not nodes:
        return False
    for n in nodes:
        # Prefer new attr, but also set legacy if present (back-compat).
        plug_new = None
        try:
            plug_new = _ensure_step_attr(n)
        except Exception:
            plug_new = None
        plugs = []
        if plug_new:
            plugs.append(plug_new)
        legacy_plug = "{}.{}".format(n, _STEP_ATTR_NAME_LEGACY)
        try:
            if cmds.objExists(legacy_plug) and legacy_plug not in plugs:
                plugs.append(legacy_plug)
        except Exception:
            pass
        for plug in plugs:
            try:
                cmds.setAttr(plug, 1 if enabled else 0)
            except Exception:
                pass
            try:
                cmds.setKeyframe(plug)
            except Exception:
                pass
    return True


def _find_upstream_animcurve_from_plug(plug):
    """Return an animCurve node driving this plug, if any (best-effort)."""
    try:
        direct = cmds.listConnections(plug, source=True, destination=False, type="animCurve") or []
        if direct:
            return direct[0]
    except Exception:
        pass

    # If the plug is driven by another node (unitConversion/etc), walk upstream.
    try:
        src_plugs = cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
    except Exception:
        src_plugs = []
    if not src_plugs:
        return None

    visited = set()
    queue = list(src_plugs)
    while queue and len(visited) < 200:
        p = queue.pop(0)
        if not p or p in visited:
            continue
        visited.add(p)
        try:
            node = str(p).split(".", 1)[0]
        except Exception:
            node = None
        if not node:
            continue
        try:
            ntype = cmds.nodeType(node) or ""
        except Exception:
            ntype = ""
        if str(ntype).startswith("animCurve"):
            return node
        try:
            ups = cmds.listConnections(node, source=True, destination=False, plugs=True) or []
        except Exception:
            ups = []
        for up in ups:
            if up and up not in visited:
                queue.append(up)
    return None


def delete_step_attr(nodes):
    """Delete the step attribute from nodes (undoable)."""
    nodes = [n for n in (nodes or []) if n]
    if not nodes:
        return 0
    deleted = 0
    for n in nodes:
        for an in (_STEP_ATTR_NAME, _STEP_ATTR_NAME_LEGACY):
            plug = "{}.{}".format(n, an)
            try:
                if not cmds.objExists(plug):
                    continue
            except Exception:
                continue
            try:
                cmds.deleteAttr(n, attribute=an)
                deleted += 1
            except Exception:
                pass
    return deleted


def _selection_namespace():
    """Return namespace prefix like 'char:' based on current selection (best-effort)."""
    try:
        sel = cmds.ls(selection=True, long=False) or []
    except Exception:
        sel = []
    if not sel:
        return ""
    # Prefer the last selected item as "active".
    name = str(sel[-1])
    if ":" not in name:
        return ""
    return name.rsplit(":", 1)[0] + ":"


def _ensure_bookmark_plugin():
    # If the node type already exists, we're good (some Maya builds may have it
    # available without an explicit plugin load).
    if _bookmark_nodetype_available():
        return True

    plugin_name = "timeSliderBookmark"
    try:
        if not cmds.pluginInfo(plugin_name, query=True, loaded=True):
            cmds.loadPlugin(plugin_name)
    except Exception:
        return False

    # Re-check node types after load.
    return _bookmark_nodetype_available(refresh=True)


def _safe_ls_bookmarks(pattern=None):
    """List timeSliderBookmark nodes without triggering 'Unknown object type' warnings."""
    if not _bookmark_nodetype_available():
        return []
    try:
        if pattern:
            return cmds.ls(pattern, type=_BOOKMARK_NODETYPE) or []
        return cmds.ls(type=_BOOKMARK_NODETYPE) or []
    except Exception:
        return []


def _time_slider_controls():
    controls = []
    for name in ("timeControl1", "timeControl2"):
        try:
            if cmds.timeControl(name, exists=True):
                controls.append(name)
        except Exception:
            pass
    if controls:
        return controls
    try:
        control = mel.eval("global string $gPlayBackSlider; $gPlayBackSlider;")
        if control:
            controls.append(control)
    except Exception:
        pass
    return controls


def _set_bookmark_visibility(state=True):
    for control in _time_slider_controls():
        try:
            cmds.timeControl(control, edit=True, bookmarkVisible=bool(state))
        except Exception:
            pass


def _find_driver_nodes_in_scene(preferred_ns=""):
    """Return likely FKIK switcher nodes in the scene, ordered by preference."""
    found = []

    preferred_ns = str(preferred_ns or "")

    # 1) Preferred control names (with/without namespaces).
    for short in _FKIK_CTRL_PREFERRED:
        # First try the preferred namespace (so switching between characters works).
        if preferred_ns:
            try:
                found.extend(cmds.ls(preferred_ns + short, long=True) or [])
            except Exception:
                pass
        try:
            found.extend(cmds.ls(short, long=True) or [])
        except Exception:
            pass
        try:
            found.extend(cmds.ls("*:" + short, long=True) or [])
        except Exception:
            pass

    # 2) Fallback: any transform that has FKIKBlend.
    try:
        any_fkik = cmds.ls("*FKIK*", long=True) or []
    except Exception:
        any_fkik = []
    for n in any_fkik:
        try:
            if cmds.objExists("{}.{}".format(n, _DRIVER_ATTR_NAME)):
                found.append(n)
        except Exception:
            pass

    # De-dup while preserving order.
    uniq = []
    seen = set()
    for n in found:
        if not n or n in seen:
            continue
        seen.add(n)
        uniq.append(n)
    return uniq


def _find_driver_attr_in_scene(preferred_ns=""):
    for node in _find_driver_nodes_in_scene(preferred_ns=preferred_ns):
        plug = "{}.{}".format(node, _DRIVER_ATTR_NAME)
        try:
            if cmds.objExists(plug):
                return plug
        except Exception:
            pass
    return None


def _active_driver_attr():
    sel = cmds.ls(selection=True, long=True) or []
    for node in sel:
        attr = "{}.{}".format(node, _DRIVER_ATTR_NAME)
        if cmds.objExists(attr):
            return attr

    if sel:
        # If the user selected a limb IK control (IKArm_R etc), prefer the
        # matching FKIK switch control within the same namespace.
        last = sel[-1]
        ns = ""
        if ":" in str(last):
            ns = str(last).rsplit(":", 1)[0] + ":"
        inferred = _infer_fkik_switch_short_from_selection(sel)
        if ns and inferred:
            plug = "{}.{}".format(ns + inferred, _DRIVER_ATTR_NAME)
            try:
                if cmds.objExists(plug):
                    return plug
            except Exception:
                pass

        first = sel[0]
        ns = ""
        if ":" in first:
            ns = first.rsplit(":", 1)[0] + ":"
        if ns:
            # Prefer searching within the active namespace even if the selected
            # object is not the FKIK switch control.
            plug = _find_driver_attr_in_scene(preferred_ns=ns)
            if plug:
                return plug

    # Scene-wide fallback (no selection needed). Prefer active selection namespace.
    return _find_driver_attr_in_scene(preferred_ns=_selection_namespace())


def _step_node_name(frame):
    try:
        f = int(round(float(frame)))
    except Exception:
        f = int(frame)
    return _BOOKMARK_STEP_PREFIX + str(f)


def add_step_mark(frame=None):
    """Create/update an orange step mark at the given frame (does not add undo steps)."""
    if not _marks_enabled():
        return None
    if frame is None:
        frame = cmds.currentTime(query=True)
    try:
        f = int(round(float(frame)))
    except Exception:
        f = int(frame)
    name = _step_node_name(f)
    label = _STEP_LABEL
    return _with_undo_suspended(lambda: _ensure_bookmark(name, label, _STEP_ORANGE, f))


def _get_driver_key_times():
    """Return sorted unique key times (float) from animCurves driving FKIKBlend."""
    attr = _active_driver_attr()
    if not attr:
        return []

    curves = set()
    try:
        direct = cmds.listConnections(attr, source=True, destination=False, type="animCurve") or []
        for c in direct:
            curves.add(c)
    except Exception:
        pass

    if not curves:
        visited = set()
        queue = [attr]
        while queue and len(visited) < 200:
            plug = queue.pop(0)
            if not plug or plug in visited:
                continue
            visited.add(plug)
            try:
                src_plugs = cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
            except Exception:
                src_plugs = []
            for sp in src_plugs:
                try:
                    node = str(sp).split(".", 1)[0]
                except Exception:
                    node = None
                if not node:
                    continue
                try:
                    ntype = cmds.nodeType(node)
                except Exception:
                    ntype = ""
                if ntype.startswith("animCurve"):
                    curves.add(node)
                    continue
                try:
                    upstream = cmds.listConnections(node, source=True, destination=False, plugs=True) or []
                except Exception:
                    upstream = []
                for up in upstream:
                    if up and up not in visited:
                        queue.append(up)

    if not curves:
        return []

    times = []
    for c in sorted(curves):
        try:
            times.extend(cmds.keyframe(c, query=True, timeChange=True) or [])
        except Exception:
            pass
    return sorted({float(t) for t in (times or [])})


def _is_step_frame(node, frame=None):
    if frame is None:
        frame = cmds.currentTime(query=True)
    plug = _step_attr_plug(node)
    try:
        if not cmds.objExists(plug):
            return False
    except Exception:
        return False
    v = _value_at_time(plug, frame)
    if v is None:
        return False
    return bool(v >= 0.5)


def _snap_nodes_to_prev_fkik_key_translation(nodes=None, frame=None):
    """Snap nodes' translate back to the previous FKIKBlend keyframe translate.

    Important: many rigs drive translate channels via upstream nodes (connections).
    In that case, setAttr() on translate does nothing. We therefore key the
    upstream animCurve (if found) at the current frame.

    Runs with undo suspended but autokey ENABLED (so keys are actually created).
    """
    if frame is None:
        frame = cmds.currentTime(query=True)
    if nodes is None:
        nodes = _selected_nodes()
    nodes = [n for n in (nodes or []) if n]
    if not nodes:
        return False

    key_times = _get_driver_key_times()
    prev_t = _prev_slide_key_before(key_times, frame, driver_attr=_active_driver_attr(), nodes=nodes)
    if prev_t is None:
        return False

    def _do():
        # Key the tread frame back to the previous slide pose.
        keyed = _key_nodes_translate_from_time(nodes, src_time=prev_t, dst_time=frame)
        
        # 强制刷新视口和DG评估
        if keyed > 0:
            try:
                # 方法1：强制DG评估
                cmds.dgdirty(allPlugs=True)
            except Exception:
                pass
            
            try:
                # 方法2：刷新当前时间
                cur = cmds.currentTime(query=True)
                cmds.currentTime(cur, update=True)
            except Exception:
                pass
            
            try:
                # 方法3：强制视口刷新
                cmds.refresh(force=True)
            except Exception:
                pass
        
        return bool(keyed)

    # 只禁用undo，不禁用autokey
    return bool(_with_undo_suspended(_do))


def align_future_tread_frames_to_prev_fkik_key(nodes, start_frame):
    """Re-align all Tread frames after start_frame to follow updated slide poses.

    This is used when the user edits a previous slide key's pose: downstream
    Tread frames should update automatically.
    """
    nodes = [n for n in (nodes or []) if n]
    if not nodes:
        return 0

    try:
        sf0 = float(start_frame)
    except Exception:
        sf0 = None

    step_frames = _list_step_frames()
    if sf0 is not None:
        step_frames = [sf for sf in step_frames if float(sf) > sf0]
    if not step_frames:
        return 0

    key_times = _get_driver_key_times()
    if not key_times:
        return 0

    def _do():
        total = 0
        for sf in step_frames:
            prev_t = _prev_key_before(key_times, sf)
            if prev_t is None:
                continue
            total += int(_key_nodes_translate_from_time(nodes, src_time=prev_t, dst_time=sf) or 0)
        return total

    return int(_with_undo_suspended(_do) or 0)


def _key_nodes_translate_from_time(nodes, src_time, dst_time):
    """Key nodes' translateXYZ at dst_time using values sampled at src_time."""
    nodes = [n for n in (nodes or []) if n]
    if not nodes:
        return 0

    def _close_enough(a, b, eps=1e-6):
        try:
            return abs(float(a) - float(b)) <= float(eps)
        except Exception:
            return False

    def _curve_value_at_time(curve, t):
        # Prefer keyframe eval (works even if not connected).
        try:
            v = cmds.keyframe(curve, query=True, eval=True, time=(float(t), float(t))) or []
            if v:
                return float(v[0])
        except Exception:
            pass
        # Fallback: animCurve output evaluation.
        try:
            return float(cmds.getAttr(curve + ".output", time=float(t)))
        except Exception:
            return None

    keyed = 0
    curves_modified = []
    
    for n in nodes:
        for axis in ("X", "Y", "Z"):
            plug = "{}.translate{}".format(n, axis)
            try:
                v = cmds.getAttr(plug, time=float(src_time))
            except Exception:
                continue

            # If translate is driven by an animCurve/utility node, key the upstream
            # animCurve instead of the driven translate plug.
            target_curve = _find_upstream_animcurve_from_plug(plug)
            if target_curve:
                try:
                    cur_v = _curve_value_at_time(target_curve, dst_time)
                    # 检查当前值是否已经正确，如果不同才需要打关键帧
                    if cur_v is None or not _close_enough(cur_v, v):
                        cmds.setKeyframe(target_curve, t=float(dst_time), v=float(v))
                        curves_modified.append(target_curve)
                        keyed += 1
                        _diag_write(["tread_key_set: curve={} t={} v={} (was {})".format(target_curve, dst_time, v, cur_v)])
                    else:
                        # 值已经正确，但仍然确保有关键帧存在
                        cmds.setKeyframe(target_curve, t=float(dst_time), v=float(v))
                        _diag_write(["tread_key_maintain: curve={} t={} v={} (unchanged)".format(target_curve, dst_time, v)])
                except Exception as exc:
                    _diag_snapshot(
                        "tread_key_failed",
                        frame=dst_time,
                        nodes=[n],
                        extra={"axis": axis, "plug": plug, "curve": target_curve, "exc": str(exc)},
                    )
            else:
                try:
                    cur_v = None
                    try:
                        cur_v = cmds.getAttr(plug, time=float(dst_time))
                    except Exception:
                        cur_v = None
                    # 检查当前值是否已经正确
                    if cur_v is None or not _close_enough(cur_v, v):
                        cmds.setKeyframe(n, attribute="translate{}".format(axis), t=float(dst_time), v=float(v))
                        keyed += 1
                        _diag_write(["tread_key_set: node={} attr=translate{} t={} v={} (was {})".format(n, axis, dst_time, v, cur_v)])
                    else:
                        cmds.setKeyframe(n, attribute="translate{}".format(axis), t=float(dst_time), v=float(v))
                        _diag_write(["tread_key_maintain: node={} attr=translate{} t={} v={} (unchanged)".format(n, axis, dst_time, v)])
                except Exception as exc:
                    _diag_snapshot(
                        "tread_key_failed",
                        frame=dst_time,
                        nodes=[n],
                        extra={"axis": axis, "plug": plug, "curve": None, "exc": str(exc)},
                    )
    
    # 强制刷新修改过的动画曲线，确保视口更新
    if curves_modified:
        try:
            for curve in curves_modified:
                # 触发动画曲线的重新评估
                cmds.getAttr(curve + ".output")
        except Exception:
            pass
    
    return keyed


def align_nodes_on_frame_to_prev_fkik_key(nodes, frame):
    """On `frame`, key nodes' translate to match the previous FKIKBlend keyframe translate."""
    nodes = [n for n in (nodes or []) if n]
    if not nodes:
        return 0
    key_times = _get_driver_key_times()
    prev_t = _prev_slide_key_before(key_times, frame, driver_attr=_active_driver_attr(), nodes=nodes)
    if prev_t is None:
        return 0
    return _key_nodes_translate_from_time(nodes, src_time=prev_t, dst_time=frame)


def _list_step_frames():
    frames = []
    nodes = _safe_ls_bookmarks(_BOOKMARK_STEP_PREFIX + "*")
    for n in nodes:
        try:
            t = cmds.getAttr(n + ".timeRangeStart")
            frames.append(int(round(float(t))))
        except Exception:
            pass
    return sorted({int(f) for f in frames})


def _prev_key_at_or_before(times, frame):
    if not times:
        return None
    try:
        f = float(frame)
    except Exception:
        return None
    prev = None
    for t in times:
        if t <= f:
            prev = t
        else:
            break
    return prev


def _prev_key_before(times, frame):
    """Return the previous key strictly before frame.

    Step/Tread frames key FKIKBlend on the current frame; using "<= frame" would
    pick the current key and prevent aligning to the prior slide key.
    """
    if not times:
        return None
    try:
        f = float(frame)
    except Exception:
        return None
    prev = None
    for t in times:
        if t < f:
            prev = t
        else:
            break
    return prev


def _prev_slide_key_before(times, frame, driver_attr=None, nodes=None):
    """Return the previous *slide* key strictly before `frame`.

    Slide key definition for this tool:
    - FKIKBlend evaluates to IK (>= _BLACK_VALUE_MAX)
    - AND the per-controller Tread attribute is OFF

    This avoids picking a previous tread frame when FKIKBlend is keyed on both
    slide and tread frames.
    """
    if not times:
        return None
    try:
        f = float(frame)
    except Exception:
        return None

    if driver_attr is None:
        try:
            driver_attr = _active_driver_attr()
        except Exception:
            driver_attr = None

    if nodes is None:
        try:
            nodes = _selected_nodes()
        except Exception:
            nodes = []
    nodes = [n for n in (nodes or []) if n]

    for t in reversed(list(times)):
        try:
            if float(t) >= f:
                continue
        except Exception:
            continue

        # Must be IK.
        if driver_attr:
            v = _value_at_time(driver_attr, t)
            if v is None or v < _BLACK_VALUE_MAX:
                continue

        # Must not be a tread frame for the involved controllers.
        is_tread = False
        for n in nodes:
            plug = _step_attr_plug(n)
            if not plug:
                continue
            try:
                if not cmds.objExists(plug):
                    continue
            except Exception:
                continue
            pv = _value_at_time(plug, t)
            if pv is not None and pv >= 0.5:
                is_tread = True
                break
        if is_tread:
            continue

        return t

    # Fallback: any previous FKIKBlend key.
    return _prev_key_before(times, frame)


def align_step_marks_to_prev_fkik_key(nodes=None):
    """For each orange STEP frame, key selected nodes' translate to the previous FKIKBlend keyframe translate.

    Rule: the previous FKIKBlend keyframe counts even if it is a "black" key (treated as slide key).
    """
    if nodes is None:
        nodes = _selected_nodes()
    nodes = [n for n in (nodes or []) if n]
    if not nodes:
        cmds.warning("请选择需要对齐位移的控制器")
        return 0

    if not _active_driver_attr():
        cmds.warning("找不到 FKIK 控制器的 {} 通道，无法对齐踩踏帧".format(_DRIVER_ATTR_NAME))
        return 0

    key_times = _get_driver_key_times()
    if not key_times:
        return 0

    step_frames = _list_step_frames()
    if not step_frames:
        return 0

    aligned = 0
    cmds.undoInfo(openChunk=True)
    try:
        for sf in step_frames:
            prev_t = _prev_key_before(key_times, sf)
            if prev_t is None:
                continue
            # Snap translate at sf to translate at prev_t.
            for n in nodes:
                for axis in ("X", "Y", "Z"):
                    plug = "{}.translate{}".format(n, axis)
                    try:
                        v = cmds.getAttr(plug, time=float(prev_t))
                    except Exception:
                        continue
                    try:
                        cmds.setKeyframe(n, attribute="translate{}".format(axis), t=float(sf), v=float(v))
                    except Exception:
                        pass
            aligned += 1
    finally:
        cmds.undoInfo(closeChunk=True)
    return aligned


def _selected_nodes():
    return cmds.ls(selection=True, long=True) or []


def _set_key_on_selected():
    sel = _selected_nodes()
    if not sel:
        cmds.warning("请先选择控制器")
        return False
    return True


def _set_driver_value_and_key(value):
    attr = _active_driver_attr()
    if not attr:
        cmds.warning("找不到 FKIK 控制器的 {} 通道".format(_DRIVER_ATTR_NAME))
        return False
    cmds.setAttr(attr, float(value))
    cmds.setKeyframe(attr)
    return True


def _list_chanai_tools_bookmarks():
    """Return all timeSliderBookmark nodes created by this tool (best-effort)."""
    nodes = _safe_ls_bookmarks()
    out = []
    for n in nodes:
        try:
            if str(n).startswith(_BOOKMARK_PREFIX):
                out.append(n)
        except Exception:
            pass
    return out


def _clear_all_chanai_tools_bookmarks():
    """Delete all bookmarks created by this tool (BIP marks + STEP marks)."""
    try:
        nodes = _list_chanai_tools_bookmarks()
        if nodes:
            cmds.delete(nodes)
    except Exception:
        pass


def _clear_bip_key_bookmarks():
    """Delete only the black/yellow BIP key bookmarks; keep orange STEP marks."""
    try:
        nodes = [n for n in _list_chanai_tools_bookmarks() if not str(n).startswith(_BOOKMARK_STEP_PREFIX)]
        if nodes:
            cmds.delete(nodes)
    except Exception:
        pass


def _ensure_bookmark(node_name, label, color_rgb, frame):
    if not _ensure_bookmark_plugin():
        return None
    if not cmds.objExists(node_name):
        try:
            cmds.createNode(_BOOKMARK_NODETYPE, name=node_name, skipSelect=True)
        except Exception:
            node_name = cmds.rename(cmds.createNode(_BOOKMARK_NODETYPE), node_name)
    try:
        cmds.setAttr(node_name + ".name", str(label), type="string")
    except Exception:
        pass
    try:
        cmds.setAttr(node_name + ".color", float(color_rgb[0]), float(color_rgb[1]), float(color_rgb[2]), type="double3")
    except Exception:
        pass
    try:
        cmds.setAttr(node_name + ".timeRangeStart", float(frame))
        cmds.setAttr(node_name + ".timeRangeStop", float(frame))
    except Exception:
        pass
    return node_name


def _get_driver_keyframes():
    """Return FKIKBlend key times (frames) from real animCurves driving the attribute.

    Note: querying cmds.keyframe() on a driven plug can sometimes look like it is
    "sampling" or returning unexpected time values. To match the user's intent
    (mark only actual keyed frames), we walk upstream to find animCurve nodes and
    use their key times.
    """

    # De-dup and coerce to whole frames.
    return sorted({int(round(float(t))) for t in _get_driver_key_times()})


def _active_controller_node():
    """Return the active controller node for per-controller marking.

    Matches Maya convention: the last-selected item is the active one.
    """
    try:
        sel = cmds.ls(selection=True, long=True) or []
    except Exception:
        sel = []
    if not sel:
        return None
    return str(sel[-1])


def _node_keyframes(node):
    """Return sorted unique whole-frame key times on this node (best-effort)."""
    if not node:
        return []
    times = []
    try:
        times = cmds.keyframe(node, query=True, timeChange=True) or []
    except Exception:
        times = []
    # De-dup and coerce to whole frames.
    out = []
    seen = set()
    for t in times or []:
        try:
            f = int(round(float(t)))
        except Exception:
            continue
        if f in seen:
            continue
        seen.add(f)
        out.append(f)
    return sorted(out)


def _value_at_time(attr, frame):
    try:
        v = cmds.getAttr(attr, time=float(frame))
    except Exception:
        return None
    if isinstance(v, (list, tuple)):
        if not v:
            return None
        if isinstance(v[0], (list, tuple)):
            return float(v[0][0])
        return float(v[0])
    return float(v)


def _is_tread_frame(frame, nodes=None, driver_attr=None):
    """Tread frame rule:

    - FKIKBlend is 10 (>= _BLACK_VALUE_MAX)
    - AND the per-controller Tread attribute is enabled (True) on at least one node

    This is used both for orange marking and for snap enforcement.
    """
    if driver_attr is None:
        driver_attr = _active_driver_attr()
    if not driver_attr:
        return False

    v = _value_at_time(driver_attr, frame)
    if v is None or v < _BLACK_VALUE_MAX:
        return False

    if nodes is None:
        nodes = _selected_nodes()
    nodes = [n for n in (nodes or []) if n]
    if not nodes:
        return False

    for n in nodes:
        plug = _step_attr_plug(n)
        if not plug:
            continue
        try:
            if not cmds.objExists(plug):
                continue
        except Exception:
            continue
        pv = _value_at_time(plug, frame)
        if pv is None:
            continue
        if pv >= 0.5:
            return True
    return False


def update_bip_marks():
    if not _marks_enabled():
        # If marks are disabled, ensure we leave the time slider clean.
        try:
            clear_bip_marks()
        except Exception:
            pass
        return False
    if not _ensure_bookmark_plugin():
        cmds.warning("timeSliderBookmark 插件无法加载")
        return False

    def _do():
        _set_bookmark_visibility(True)
        # Rebuild everything so switching controllers doesn't leave stale STEP marks.
        _clear_all_chanai_tools_bookmarks()

        # 3ds Max Biped style: marks follow the active controller.
        # If the controller has no keys, show nothing.
        ctrl = _active_controller_node()
        if not ctrl:
            return False

        frames = _node_keyframes(ctrl)
        if not frames:
            return False

        driver_attr = _active_driver_attr()

        for frame in frames:
            # Orange Tread takes precedence over yellow/black.
            if _is_tread_frame(frame, nodes=[ctrl], driver_attr=driver_attr):
                add_step_mark(frame=frame)
                continue

            val = None
            if driver_attr:
                val = _value_at_time(driver_attr, frame)
            is_yellow = bool(val is not None and val >= _BLACK_VALUE_MAX)
            color = (1.0, 1.0, 0.0) if is_yellow else (0.0, 0.0, 0.0)
            name = _BOOKMARK_PREFIX + str(int(frame))
            label = "BIP {} {}".format(int(frame), "Y" if is_yellow else "B")
            _ensure_bookmark(name, label, color, frame)

        _force_time_slider_redraw()
        return True

    return _with_undo_suspended(_do)


def clear_bip_marks():
    _clear_all_chanai_tools_bookmarks()
    return True


class BipWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        if parent is None:
            parent = _maya_main_window()
        super(BipWindow, self).__init__(parent)
        self.setObjectName(_WINDOW_OBJECT_NAME)
        self.setWindowTitle("层标记")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        # Resizable window; keep a sensible minimum so all buttons remain visible.
        self.setMinimumSize(520, 240)
        self.resize(560, 300)
        self._ui_version = _UI_VERSION
        self._selection_job = None
        self._drag_job = None
        self._drag_press_job = None
        self._undo_job = None
        self._redo_job = None
        self._attr_job = None
        self._xform_job_ids = []
        self._refresh_scheduled = False
        self._step_enforce_scheduled = False
        self._step_enforce_guard = False
        self._step_snap_timer = None
        self._is_dragging = False
        self._time_job = None
        self._last_time_change = 0.0
        # Suppress snap briefly around undo/redo; otherwise snap can immediately
        # re-apply and makes Ctrl+Z feel like it doesn't work.
        self._suppress_snap_until = 0.0

        # Lightweight Qt styling (keeps a Maya-friendly dark UI without fighting the host theme too much).
        try:
            self.setStyleSheet(
                "QDialog { background: #2b2b2b; color: #ddd; }"
                "QCheckBox { spacing: 6px; }"
                "QPushButton { padding: 6px 10px; background: #3a3a3a; border: 1px solid #555; border-radius: 3px; }"
                "QPushButton:hover { background: #444; }"
                "QPushButton:pressed { background: #2f2f2f; }"
            )
        except Exception:
            pass

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.enable_marks = QtWidgets.QCheckBox("显示 BIP 标记（读 FKIKBlend）")
        try:
            self.enable_marks.setChecked(bool(_marks_enabled()))
        except Exception:
            self.enable_marks.setChecked(True)
        self.enable_marks.stateChanged.connect(self._on_toggle_marks)
        layout.addWidget(self.enable_marks)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        layout.addLayout(row)

        self.set_btn = QtWidgets.QPushButton("设置帧")
        self.slide_btn = QtWidgets.QPushButton("滑动帧")
        self.step_btn = QtWidgets.QPushButton("踩踏帧")
        row.addWidget(self.set_btn)
        row.addWidget(self.slide_btn)
        row.addWidget(self.step_btn)

        self.set_btn.clicked.connect(self._on_set_frame)
        self.slide_btn.clicked.connect(self._on_slide_frame)
        self.step_btn.clicked.connect(self._on_step_frame)

        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(6)
        layout.addLayout(row2)

        self.refresh_btn = QtWidgets.QPushButton("刷新标记")
        self.clear_btn = QtWidgets.QPushButton("清除标记")
        self.clear_attr_btn = QtWidgets.QPushButton("清除属性")
        row2.addWidget(self.refresh_btn)
        row2.addWidget(self.clear_btn)
        row2.addWidget(self.clear_attr_btn)

        self.refresh_btn.clicked.connect(lambda *_: update_bip_marks())
        self.clear_btn.clicked.connect(lambda *_: clear_bip_marks())
        self.clear_attr_btn.clicked.connect(self._on_clear_attr)

        # Diagnostics controls
        row3 = QtWidgets.QHBoxLayout()
        row3.setSpacing(6)
        layout.addLayout(row3)

        self.diag_cb = QtWidgets.QCheckBox("诊断输出")
        try:
            self.diag_cb.setChecked(_diag_enabled())
        except Exception:
            self.diag_cb.setChecked(True)
        self.diag_cb.stateChanged.connect(self._on_diag_changed)
        row3.addWidget(self.diag_cb)

        self.open_log_btn = QtWidgets.QPushButton("打开日志")
        self.open_folder_btn = QtWidgets.QPushButton("打开目录")
        self.clear_log_btn = QtWidgets.QPushButton("清空日志")
        row3.addWidget(self.open_log_btn)
        row3.addWidget(self.open_folder_btn)
        row3.addWidget(self.clear_log_btn)

        self.open_log_btn.clicked.connect(self._on_open_log)
        self.open_folder_btn.clicked.connect(self._on_open_log_folder)
        self.clear_log_btn.clicked.connect(self._on_clear_log)

        self._start_selection_watch()
        self._start_auto_refresh()
        if self.enable_marks.isChecked():
            update_bip_marks()
        else:
            # Respect persisted toggle state.
            clear_bip_marks()

        # Always install the S hotkey while the window is open.
        _install_s_hotkey()

        # Debounce snap-back so dragging doesn't fight the user; snap happens
        # shortly after the last xform change.
        try:
            self._step_snap_timer = QtCore.QTimer(self)
            self._step_snap_timer.setSingleShot(True)
            self._step_snap_timer.setInterval(120)
            self._step_snap_timer.timeout.connect(self._enforce_step_snap_now)
        except Exception:
            self._step_snap_timer = None

    def _on_toggle_marks(self, state):
        enabled = (state == QtCore.Qt.Checked)
        _set_marks_enabled(enabled)
        if enabled:
            self._rebuild_attr_watch()
            # Re-enable tread enforcement watchers.
            self._rebuild_xform_watch()
            update_bip_marks()
        else:
            # Disable background tread enforcement when marks are hidden.
            try:
                if self._step_snap_timer is not None:
                    self._step_snap_timer.stop()
            except Exception:
                pass
            self._step_enforce_scheduled = False
            self._is_dragging = False
            try:
                self._rebuild_xform_watch()  # kills existing xform jobs
            except Exception:
                pass
            clear_bip_marks()

    def _on_diag_changed(self, state):
        try:
            cmds.optionVar(intValue=(_OPTIONVAR_DIAG_ENABLED, 1 if state == QtCore.Qt.Checked else 0))
        except Exception:
            pass

    def _on_open_log(self):
        try:
            path = _diag_log_path()
            if os.path.isfile(path):
                os.startfile(path)
            else:
                # Create empty file so it can be opened.
                _diag_write(["(log created)"])
                os.startfile(path)
        except Exception:
            try:
                cmds.warning("无法打开日志文件: {}".format(_diag_log_path()))
            except Exception:
                pass

    def _on_open_log_folder(self):
        try:
            folder = os.path.dirname(_diag_log_path())
            if folder and os.path.isdir(folder):
                os.startfile(folder)
        except Exception:
            try:
                cmds.warning("无法打开日志目录: {}".format(os.path.dirname(_diag_log_path())))
            except Exception:
                pass

    def _on_clear_log(self):
        try:
            path = _diag_log_path()
            try:
                with io.open(path, 'w', encoding='utf-8') as f:
                    f.write("")
            except TypeError:
                with open(path, 'w') as f:
                    f.write("")
        except Exception:
            pass

    def _on_set_frame(self):
        if not _set_key_on_selected():
            return
        cmds.undoInfo(openChunk=True)
        try:
            cmds.setKeyframe(_selected_nodes())
            _set_driver_value_and_key(0.0)
            _set_step_attr_key(_selected_nodes(), enabled=False)
        finally:
            cmds.undoInfo(closeChunk=True)
        if self.enable_marks.isChecked():
            update_bip_marks()

    def _on_slide_frame(self):
        if not _set_key_on_selected():
            return
        cmds.undoInfo(openChunk=True)
        try:
            cmds.setKeyframe(_selected_nodes())
            _set_driver_value_and_key(_VALUE_YELLOW)
            _set_step_attr_key(_selected_nodes(), enabled=False)
        finally:
            cmds.undoInfo(closeChunk=True)
        if self.enable_marks.isChecked():
            update_bip_marks()

    def _on_step_frame(self):
        sel = _selected_nodes()
        if not sel:
            cmds.warning("请先选择控制器")
            return
        # Step (Tread) frame:
        # - Set FKIKBlend=10 (IK) and key it
        # - Enable + key the per-controller step flag
        # - Add an orange Tread bookmark (no undo pollution)
        cmds.undoInfo(openChunk=True)
        try:
            # Do NOT key all attributes on the controller here.
            # Tread should only align translation; keying everything (including
            # rotate) makes rotation edits appear to "snap back".
            _set_driver_value_and_key(_VALUE_YELLOW)
            _set_step_attr_key(sel, enabled=True)
        finally:
            cmds.undoInfo(closeChunk=True)

        # Snap translate without adding undo steps.
        try:
            frame = cmds.currentTime(query=True)
        except Exception:
            frame = None
        if frame is not None:
            try:
                _diag_snapshot("tread_click_before_align", frame=frame, nodes=sel)
            except Exception:
                pass
            try:
                _snap_nodes_to_prev_fkik_key_translation(nodes=sel, frame=frame)
            except Exception:
                pass
            try:
                _diag_snapshot("tread_click_after_align", frame=frame, nodes=sel)
            except Exception:
                pass

        add_step_mark()
        if self.enable_marks.isChecked():
            update_bip_marks()
        # Keep the snap-back behavior when the user moves on a tread frame.
        if self.enable_marks.isChecked():
            self._enforce_step_snap_deferred()

    def _start_selection_watch(self):
        if self._selection_job is not None:
            return
        try:
            self._selection_job = cmds.scriptJob(event=["SelectionChanged", self._on_selection_changed], protected=True)
        except Exception:
            self._selection_job = None

        # Snap right after drag ends (more reliable than timers during viewport interaction).
        if self._drag_job is None:
            try:
                self._drag_job = cmds.scriptJob(event=["DragRelease", self._enforce_step_snap_deferred], protected=True)
            except Exception:
                self._drag_job = None

        if self._drag_press_job is None:
            try:
                self._drag_press_job = cmds.scriptJob(event=["DragPress", self._on_drag_press], protected=True)
            except Exception:
                self._drag_press_job = None

        # Avoid fighting Undo/Redo (undo should win).
        if self._undo_job is None:
            try:
                self._undo_job = cmds.scriptJob(event=["Undo", self._on_undo_or_redo], protected=True)
            except Exception:
                self._undo_job = None
        if self._redo_job is None:
            try:
                self._redo_job = cmds.scriptJob(event=["Redo", self._on_undo_or_redo], protected=True)
            except Exception:
                self._redo_job = None

        if self._time_job is None:
            try:
                self._time_job = cmds.scriptJob(event=["timeChanged", self._on_time_changed], protected=True)
            except Exception:
                self._time_job = None

    def _on_time_changed(self, *_):
        try:
            self._last_time_change = time.time()
        except Exception:
            self._last_time_change = 0.0

        # If the user jumps onto a tread frame, enforce the snap so the pose
        # matches the previous slide key (no undo pollution).
        try:
            if cmds.play(query=True, state=True):
                return
        except Exception:
            pass
        try:
            self._enforce_step_snap_deferred()
        except Exception:
            pass

    def _on_drag_press(self, *_):
        self._is_dragging = True

    def _on_undo_or_redo(self, *_):
        # Cancel any pending snap and suppress for a short window so undo state
        # is visible before any enforcement runs.
        try:
            self._suppress_snap_until = time.time() + 0.5
        except Exception:
            self._suppress_snap_until = 0.0
        try:
            if self._step_snap_timer is not None:
                self._step_snap_timer.stop()
        except Exception:
            pass
        self._step_enforce_scheduled = False

    def _rebuild_xform_watch(self):
        # Kill old jobs
        for jid in list(self._xform_job_ids or []):
            try:
                if cmds.scriptJob(exists=jid):
                    cmds.scriptJob(kill=jid, force=True)
            except Exception:
                pass
        self._xform_job_ids = []

        # Watch translate only (NOT rotate) so the tread frame can keep position
        # locked while allowing free rotation edits.
        if not self.enable_marks.isChecked():
            return

        sel = _selected_nodes()
        if not sel:
            return

        for n in sel:
            for axis in ("X", "Y", "Z"):
                plug = "{}.translate{}".format(n, axis)
                try:
                    if not cmds.objExists(plug):
                        continue
                except Exception:
                    continue
                try:
                    jid = cmds.scriptJob(attributeChange=[plug, self._on_xform_changed], protected=True)
                    self._xform_job_ids.append(jid)
                except Exception:
                    pass

    def _on_xform_changed(self, *_):
        # Ignore changes caused by scrubbing / evaluation.
        try:
            if time.time() - float(self._last_time_change or 0.0) < 0.15:
                return
        except Exception:
            pass

        # During viewport dragging, rely on DragRelease (more stable).
        if self._is_dragging:
            return

        self._enforce_step_snap_deferred()

    def _enforce_step_snap_deferred(self):
        # Respect UI toggle: if marks are off, treat tread enforcement as disabled.
        if not self.enable_marks.isChecked():
            return
        # Drag release implies we're no longer dragging.
        self._is_dragging = False
        try:
            if time.time() < float(self._suppress_snap_until or 0.0):
                return
        except Exception:
            pass
        if self._step_enforce_guard:
            return
        
        # 添加额外检查：只在踩踏帧上才触发对齐
        sel = _selected_nodes()
        if not sel:
            return
        
        try:
            frame = cmds.currentTime(query=True)
        except Exception:
            frame = None
        
        try:
            driver_attr = _active_driver_attr()
        except Exception:
            driver_attr = None
        
        is_step = _is_tread_frame(frame, nodes=sel, driver_attr=driver_attr)
        if not is_step:
            # 不在踩踏帧上，不触发对齐
            return

        # Snap immediately. Debounce/timers can look like a slow "ease" back.
        # Guarding + tread-frame checks already prevent excessive recursion.
        try:
            self._enforce_step_snap_now()
        except Exception:
            pass

    def _enforce_step_snap_immediate(self):
        """立即对齐踩踏帧（已废弃，改为只在拖拽结束时对齐）"""
        # 此方法已废弃，不再使用
        # 原因：监听 attributeChange 会导致切换帧、删除关键帧等操作也触发对齐
        # 现在只在 DragRelease 时通过 _enforce_step_snap_deferred 触发对齐
        pass

    def _enforce_step_snap_now(self):
        """延迟对齐（保留用于其他触发场景，如DragRelease）"""
        self._step_enforce_scheduled = False
        # Respect UI toggle: if marks are off, treat tread enforcement as disabled.
        if not self.enable_marks.isChecked():
            return
        try:
            if time.time() < float(self._suppress_snap_until or 0.0):
                return
        except Exception:
            pass
        if self._step_enforce_guard:
            return
        sel = _selected_nodes()
        if not sel:
            return
        # Enforce only on Tread/step frames.
        try:
            frame = cmds.currentTime(query=True)
        except Exception:
            frame = None
        # Use the same tread-frame rule as bookmark coloring.
        try:
            driver_attr = _active_driver_attr()
        except Exception:
            driver_attr = None
        is_step = _is_tread_frame(frame, nodes=sel, driver_attr=driver_attr)

        if not is_step:
            # 不在踩踏帧上，不执行对齐
            # 注意：也不执行传播逻辑，避免在非踩踏帧上自动打关键帧
            return
            
        self._step_enforce_guard = True
        try:
            _diag_snapshot("tread_snap_deferred_before", frame=frame, nodes=sel)
            keyed = _snap_nodes_to_prev_fkik_key_translation(nodes=sel, frame=frame)
            _diag_write(["tread_snap_deferred: keyed={} keys".format(keyed)])
            try:
                cmds.refresh(force=True)
            except Exception:
                pass
            _diag_snapshot("tread_snap_deferred_after", frame=frame, nodes=sel, extra={"keyed": keyed})
        finally:
            self._step_enforce_guard = False

    def _start_auto_refresh(self):
        """Auto-update marks when FKIKBlend changes (no follow-the-current-frame marker)."""
        # Bind to the currently active driver attr (may change with selection).
        self._rebuild_attr_watch()

    def _stop_auto_refresh(self):
        for jid_attr in ("_attr_job",):
            jid = getattr(self, jid_attr, None)
            if not jid:
                continue
            try:
                if cmds.scriptJob(exists=jid):
                    cmds.scriptJob(kill=jid, force=True)
            except Exception:
                pass
            setattr(self, jid_attr, None)

    def _rebuild_attr_watch(self):
        # Kill old watcher
        if self._attr_job is not None:
            try:
                if cmds.scriptJob(exists=self._attr_job):
                    cmds.scriptJob(kill=self._attr_job, force=True)
            except Exception:
                pass
            self._attr_job = None

        try:
            plug = _active_driver_attr()
        except Exception:
            plug = None
        if not plug:
            return

        try:
            self._attr_job = cmds.scriptJob(attributeChange=[plug, self._schedule_refresh], protected=True)
        except Exception:
            self._attr_job = None

    def _schedule_refresh(self, *_):
        if not self.enable_marks.isChecked():
            return
        if self._refresh_scheduled:
            return
        self._refresh_scheduled = True
        try:
            maya_utils.executeDeferred(self._refresh_now)
        except Exception:
            cmds.evalDeferred(self._refresh_now)

    def _refresh_now(self):
        self._refresh_scheduled = False
        if not self.enable_marks.isChecked():
            return
        # Only mark real FKIKBlend keyframes; do not follow the current time.
        update_bip_marks()

    def _stop_selection_watch(self):
        if self._selection_job is None:
            return
        try:
            if cmds.scriptJob(exists=self._selection_job):
                cmds.scriptJob(kill=self._selection_job, force=True)
        except Exception:
            pass
        self._selection_job = None

        if self._drag_job is not None:
            try:
                if cmds.scriptJob(exists=self._drag_job):
                    cmds.scriptJob(kill=self._drag_job, force=True)
            except Exception:
                pass
            self._drag_job = None

        if self._drag_press_job is not None:
            try:
                if cmds.scriptJob(exists=self._drag_press_job):
                    cmds.scriptJob(kill=self._drag_press_job, force=True)
            except Exception:
                pass
            self._drag_press_job = None

        for jid_name in ("_undo_job", "_redo_job"):
            jid = getattr(self, jid_name, None)
            if not jid:
                continue
            try:
                if cmds.scriptJob(exists=jid):
                    cmds.scriptJob(kill=jid, force=True)
            except Exception:
                pass
            setattr(self, jid_name, None)

        if self._time_job is not None:
            try:
                if cmds.scriptJob(exists=self._time_job):
                    cmds.scriptJob(kill=self._time_job, force=True)
            except Exception:
                pass
            self._time_job = None

        # Also stop transform watchers
        try:
            self._rebuild_xform_watch()
        except Exception:
            pass

    def _on_selection_changed(self):
        # Selection may imply a different FKIK control/namespace; re-bind watcher first.
        self._rebuild_attr_watch()
        if self.enable_marks.isChecked():
            self._rebuild_xform_watch()
        else:
            # Ensure no background tread jobs are active when marks are off.
            try:
                self._rebuild_xform_watch()
            except Exception:
                pass
        if self.enable_marks.isChecked():
            # Refresh twice: once immediately, once deferred. This avoids cases
            # where the time slider overlay lags behind selection changes.
            try:
                update_bip_marks()
            except Exception:
                pass
            try:
                maya_utils.executeDeferred(update_bip_marks)
            except Exception:
                try:
                    cmds.evalDeferred(update_bip_marks)
                except Exception:
                    pass

    def _on_clear_attr(self):
        sel = _selected_nodes()
        if not sel:
            return
        cmds.undoInfo(openChunk=True)
        try:
            delete_step_attr(sel)
        finally:
            cmds.undoInfo(closeChunk=True)

    def closeEvent(self, event):
        self._stop_selection_watch()
        self._stop_auto_refresh()
        _uninstall_s_hotkey()
        super(BipWindow, self).closeEvent(event)


def _maya_main_window():
    main_window_ptr = omui.MQtUtil.mainWindow()
    if main_window_ptr:
        return wrapInstance(int(main_window_ptr), QtWidgets.QWidget)
    return None


def _ensure_maya_py_path_optionvar():
    try:
        if cmds.optionVar(exists=_OPTIONVAR_MAYA_PY_PATH):
            return
        scripts_dir = None
        try:
            scripts_dir = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            scripts_dir = None

        if not scripts_dir:
            return
        cmds.optionVar(stringValue=(_OPTIONVAR_MAYA_PY_PATH, scripts_dir))
    except Exception:
        pass


def _install_s_hotkey():
    _ensure_maya_py_path_optionvar()
    try:
        prev = cmds.hotkey(k=_HOTKEY_CHAR, query=True, name=True) or ""
        cmds.optionVar(stringValue=(_OPTIONVAR_PREV_HOTKEY_S, prev))
    except Exception:
        pass

    cmd = (
        "import maya.cmds as cmds\n"
        "import sys\n"
        "p = None\n"
        "try:\n"
        "    p = cmds.optionVar(q='{opt}')\n"
        "except Exception:\n"
        "    p = None\n"
        "if p and p not in sys.path:\n"
        "    sys.path.append(p)\n"
        "cmds.setKeyframe()\n"
        "try:\n"
        "    import time_slider_bip as t\n"
        "    try:\n"
        "        enabled = True\n"
        "        if cmds.optionVar(exists='{ov}'):\n"
        "            enabled = bool(cmds.optionVar(q='{ov}'))\n"
        "        if enabled:\n"
        "            t.update_bip_marks()\n"
        "    except Exception:\n"
        "        pass\n"
        "except Exception:\n"
        "    pass\n"
    ).format(opt=_OPTIONVAR_MAYA_PY_PATH, ov=_OPTIONVAR_MARKS_ENABLED)
    try:
        if cmds.runTimeCommand(_RUNTIME_CMD, exists=True):
            cmds.runTimeCommand(_RUNTIME_CMD, edit=True, commandLanguage="python", command=cmd)
        else:
            cmds.runTimeCommand(_RUNTIME_CMD, annotation="Set key and refresh BIP marks", category="CHANAI_TOOLS", commandLanguage="python", command=cmd)
    except Exception:
        return False

    # Maya's nameCommand does not support an `exists` flag in some versions.
    name_exists = False
    try:
        # Querying any field will error if it doesn't exist.
        cmds.nameCommand(_NAME_CMD, query=True, annotation=True)
        name_exists = True
    except Exception:
        name_exists = False

    if not name_exists:
        try:
            cmds.nameCommand(_NAME_CMD, annotation="Set key and refresh BIP marks", command=_RUNTIME_CMD)
        except Exception:
            return False

    try:
        cmds.hotkey(k=_HOTKEY_CHAR, name=_NAME_CMD)
    except Exception:
        return False
    return True


def _uninstall_s_hotkey():
    try:
        if not cmds.optionVar(exists=_OPTIONVAR_PREV_HOTKEY_S):
            return True
        prev = cmds.optionVar(q=_OPTIONVAR_PREV_HOTKEY_S) or ""
        if prev:
            cmds.hotkey(k=_HOTKEY_CHAR, name=prev)
        else:
            cmds.hotkey(k=_HOTKEY_CHAR, name="")
    except Exception:
        pass
    return True


def show():
    global _WIN_INSTANCE
    _ensure_maya_py_path_optionvar()
    try:
        cmds.inViewMessage(amg="CHANAI_TOOLS BIP launching...", pos="topCenter", fade=True, alpha=0.9)
    except Exception:
        pass
    existing = None
    for w in QtWidgets.QApplication.topLevelWidgets():
        if w.objectName() == _WINDOW_OBJECT_NAME:
            existing = w
            break

    if existing is not None:
        try:
            # If the code has changed (new UI version), rebuild instead of reusing an old instance.
            try:
                if getattr(existing, "_ui_version", None) != _UI_VERSION:
                    try:
                        existing.close()
                    except Exception:
                        pass
                    existing = None
            except Exception:
                pass

            if existing is not None:
                try:
                    existing.show()
                    existing.showNormal()
                except Exception:
                    pass
                existing.raise_()
                existing.activateWindow()
                _WIN_INSTANCE = existing
                return existing
        except Exception:
            pass

    try:
        win = BipWindow()
        win.show()
        try:
            win.showNormal()
            win.raise_()
            win.activateWindow()
        except Exception:
            pass
        _WIN_INSTANCE = win
        return win
    except Exception as exc:
        try:
            import traceback

            traceback.print_exc()
        except Exception:
            pass
        try:
            cmds.warning("BIP 窗口创建失败: {}".format(exc))
        except Exception:
            pass
        return None


def main():
    return show()


def onMayaDroppedPythonFile(*_):
    try:
        maya_utils.executeDeferred(show)
    except Exception:
        cmds.evalDeferred(show)


if __name__ == "__main__":
    main()
