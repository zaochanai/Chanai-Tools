# -*- coding: utf-8 -*-
"""facial_driver_recorder_tool.py

A small Maya tool for recording an additive facial driver mapping into an
existing ADV/DrivingSystem-like setup:

    driverAttr -> animCurve (SDK) -> blendWeighted.input[*] -> (unitConversion) -> drivenAttr

Workflow (timeline edit / ADV-like):
- Pick a driver control (e.g. talkBCon_Z) and a driver plug (e.g. translateX).
- Set a frame range N and a target driver value.
- Enter Edit:
    * tool saves current playback range
    * tool temporarily drives the driver plug from the timeline (frame 0..N -> driver 0..target)
    * tool captures base values at frame 0, then disconnects driven plugs so you can key poses
- You scrub the timeline (0..N) and key your driven transforms at multiple frames.
- Commit:
    * tool samples the keyed frames, computes deltas per frame (posed - base)
    * tool writes a multi-key additive SDK layer into an empty blendWeighted.input[index]
    * tool restores original connections and restores the previous playback range

Notes:
- For rotate channels, if the driven plug is fed by a unitConversion node,
  the tool converts posed values using current angle unit + conversionFactor
  so written SDK values match what you posed.
- If a driven plug has no incoming connection, the tool can create a new
  blendWeighted (and unitConversion for rotate) to keep the same style.

Usage:
    import facial_driver_recorder_tool as fdr
    fdr.show_ui()

Tested assumptions:
- Your scene already uses blendWeighted for additive stacking and unitConversion
  for rotate channels (as in your trace output).
"""


import json
import math
from contextlib import contextmanager
from functools import wraps

import maya.cmds as cmds
try:
    import maya.mel as mel
except Exception:  # pragma: no cover
    mel = None

# Optional but available inside Maya: used for matrix math (bake controller edits into parent groups).
try:  # Maya 2017+
    import maya.api.OpenMaya as om2
except Exception:  # pragma: no cover
    om2 = None


_WINDOW = "facialDriverRecorderWin"
_SESSION_OPT_VAR = "facialDriverRecorder_session_v1"
_LANG_OPT_VAR = "facialDriverRecorder_lang_v1"  # "zh" | "en"

_MIRROR_AXIS_OPT_VAR = "facialDriverRecorder_mirrorAxis_v2"  # "X"|"Y"|"Z"
_MIRROR_DIR_OPT_VAR = "facialDriverRecorder_mirrorDir_v1"  # "L2R"|"R2L"

_WRITE_MODE_OPT_VAR = "facialDriverRecorder_writeMode_v1"  # "add" | "update"
_FDR_TAG_ATTR = "fdrTag"  # string attr on animCurve nodes created by this tool
_DRIVER_TARGET_MATCH_EPS = 1e-4

_FRAME_RANGE_OPT_VAR = "facialDriverRecorder_frameRange_v1"  # int >= 1

_SDK_FOLD_OPT_VAR = "facialDriverRecorder_sdkFold_v1"  # 0/1
_SDK_DRIVER_FILTER_OPT_VAR = "facialDriverRecorder_sdkDriverFilter_v1"  # 0 = All, else index
_DRIVEN_TARGETS_OPT_VAR = "facialDriverRecorder_drivenTargets_v1"  # JSON list[str]

# UI-only cache: populated by Scan SDK, used by Edit/Delete buttons.
_SDK_SCAN_ITEMS = []
# UI-only view cache: the items currently shown in the list (after driver filter).
_SDK_SCAN_ITEMS_VIEW = []
_SDK_DRIVER_MENU_MAP = {}  # label -> (driverPlug, driverTarget)
_SDK_TREE_LEAF_MAP = {}  # treeItemId -> scan item
_SDK_TREE_ROOT_MAP = {}  # treeRootId -> info dict (driverNode/driverPlug/...)
_DRIVER_ATTR_OPTIONS = (
    "translateX",
    "translateY",
    "translateZ",
    "rotateX",
    "rotateY",
    "rotateZ",
    "qRotateX",
    "qRotateY",
    "qRotateZ",
)

_UNDO_CHUNK_DEPTH = 0


@contextmanager
def _undo_chunk(label= "Facial Driver Recorder"):
    """Group a user action into one Maya undo step (nested-safe)."""
    global _UNDO_CHUNK_DEPTH
    opened = False
    try:
        if _UNDO_CHUNK_DEPTH == 0:
            try:
                cmds.undoInfo(openChunk=True, chunkName=str(label))
            except Exception:
                cmds.undoInfo(openChunk=True)
            opened = True
        _UNDO_CHUNK_DEPTH += 1
        yield
    finally:
        if _UNDO_CHUNK_DEPTH > 0:
            _UNDO_CHUNK_DEPTH -= 1
        if opened:
            try:
                cmds.undoInfo(closeChunk=True)
            except Exception:
                pass


@contextmanager
def _suspend_undo_recording():
    """Temporarily disable undo recording without flushing current stack."""
    prev_state = True
    try:
        prev_state = bool(cmds.undoInfo(q=True, state=True))
    except Exception:
        prev_state = True

    try:
        if prev_state:
            cmds.undoInfo(stateWithoutFlush=False)
    except Exception:
        pass

    try:
        yield
    finally:
        try:
            cmds.undoInfo(stateWithoutFlush=bool(prev_state))
        except Exception:
            pass


def _undoable(label):
    """Decorator: run function inside a single Maya undo chunk."""
    def _decorator(func):
        @wraps(func)
        def _wrapped(*args, **kwargs):
            with _undo_chunk(label):
                return func(*args, **kwargs)
        return _wrapped
    return _decorator


def _driver_attr_candidates(node):
    """Return driver attr options for a node, including user-defined numeric attrs."""
    out = []
    seen = set()

    def _add(name):
        if not name or name in seen:
            return
        seen.add(name)
        out.append(name)

    for a in _DRIVER_ATTR_OPTIONS:
        _add(a)

    if not node or (not cmds.objExists(node)):
        return out

    try:
        user_attrs = cmds.listAttr(node, ud=True) or []
    except Exception:
        user_attrs = []

    for a in user_attrs:
        plug = "{}.{}".format(node, a)
        if not _attr_exists(plug):
            continue
        try:
            if not (cmds.getAttr(plug, k=True) or cmds.getAttr(plug, cb=True)):
                continue
        except Exception:
            pass
        try:
            atype = cmds.getAttr(plug, type=True)
        except Exception:
            atype = ""
        if atype in ("double", "doubleAngle", "doubleLinear", "float", "long", "short", "byte", "bool", "enum", "time"):
            _add(a)

    return out


_STRINGS = {
    "zh": {
        "title": "表情驱动录制器",
        "driver_frame": "驱动（Driver）",
        "driver_node": "驱动节点",
        "load_selected": "从选择读取",
        "select_node": "选择物体",
        "driver_attr": "驱动属性",
        "target_value": "目标值",
        "target_hint": "（例：X=1）",
        "frame_range": "帧范围",
        "frame_range_hint": "（0~N 帧）",
        "driven_frame": "被驱动通道（Driven Channels）",
        "driven_targets_frame": "被驱动物体",
        "driven_targets_add": "添加选择",
        "driven_targets_remove": "移除所选",
        "driven_targets_clear": "清空列表",
        "driven_targets_select": "选中列表",
        "actions_frame": "操作",
            "write_mode": "写入方式",
            "write_add": "新增层（叠加，不破坏原曲线）",
            "write_update": "修改上一层（仅本工具创建）",
            "warn_update_fallback": "未找到可修改的旧层（本工具创建）。已改为新增一层：{plug}",
            "warn_update_missing_layer": "写入方式为“修改上一层”时，该通道没有找到可覆盖的旧层，已跳过：{plug}（如需自动创建，请切换为“新增层”）",
        "enter_edit": "进入编辑",
        "commit": "应用",
        "cancel": "取消",
        "howto": "使用步骤：",
        "howto_1": "1）选择要修改的“被驱动对象”（建议选控制器的父组/驱动组，如 *_qudong_G）。",
        "howto_2": "2）设置驱动节点/属性/目标值，然后点“进入编辑”。",
        "howto_3": "3）摆姿势（移动/旋转被驱动对象），然后点“应用”。",
        "howto_4": "（应用后会把驱动值自动归零。）",
        "lang": "English",
        "drive_parent": "驱动父组（上一级）",
        "parent_levels": "父级层数",
        "bake_to_parent": "控制器写入父级",
        "warn_select_driver": "请先选择一个驱动控制器（transform）。",
        "warn_driver_node_not_found": "驱动节点不存在：{node}",
        "scan_sdk": "检查SDK",
        "warn_scan_no_selection": "请先选择要检查的对象（transform）。",
        "sdk_list_frame": "SDK 列表",
        "sdk_driver_filter": "Driver 过滤",
        "sdk_driver_all": "（全部 Driver）",
        "sdk_fold": "折叠名称（隐藏长前缀）",
        "sdk_edit_selected": "编辑所选 SDK",
        "sdk_edit_driver": "按 Driver 批量编辑",
        "sdk_delete_selected": "删除所选 SDK",
        "sdk_select_driver": "选中Driver",
        "warn_sdk_item_not_selected": "请先在 SDK 列表里选择一条。",
        "warn_sdk_item_invalid": "所选 SDK 项无效/已不存在，请重新检查SDK。",
        "warn_sdk_no_driver_items": "当前扫描结果里没有找到该 Driver 的 SDK 层。",
        "confirm_delete_title": "删除 SDK",
        "confirm_delete_msg": "确定删除这条 SDK 层吗？\n\n{desc}",
        "confirm_delete_multi_msg": "确定删除所选 SDK 层吗？\n\n数量: {count}",
        "confirm_cleanup_dupes_title": "清理重复 SDK",
        "confirm_cleanup_dupes_msg": "发现同一个 Driver 在同一通道上存在多层（会叠加）。\n\n是否保留一层并删除其余重复层？\n\nDriver: {driver}\n重复层数: {count}",
        "confirm_add_over_existing_title": "新增层确认",
        "confirm_add_over_existing_msg": "检测到当前驱动已在部分通道上存在 SDK 层。\n\n继续“新增层”会叠加效果（可能越叠越夸张）。\n\nDriver: {driver}\n受影响通道数: {count}\n\n是否继续新增？",
        "warn_delete_multi_outputs": "该曲线节点有多个输出连接（{count} 个），为避免误删已取消：{node}",
        "warn_select_driven": "请先选择你要修改的被驱动对象（transform），再点进入编辑。",
        "warn_driven_list_empty": "被驱动物体列表为空。请先添加控制器，或直接在场景中选择控制器。",
        "warn_session_active": "已有未结束的会话：请先应用（Commit）或取消（Cancel）。",
        "warn_driver_missing": "找不到驱动属性：{plug}",
        "warn_controller_selected": "你选中了控制器本体：{node}。建议勾选“驱动父组”或直接选它的父组/驱动组（例如 *_qudong_G），否则控制器会出现被驱动（变黄/出现驱动关键帧标记）。",
        "warn_no_driven_plugs": "没有找到可编辑的被驱动通道。请检查选择对象与通道勾选（tX/tY/...）。",
        "warn_edit_targets_selected": "已自动选择录制目标：{count} 个。请直接移动/旋转这些目标来摆姿势（不要再移动原控制器，否则录制的父组/驱动组数值不会变化，Commit 会被全部跳过）。",
        "warn_auto_bake_parent_mode": "检测到当前选择是控制器，已自动切换为“控制器写入父级”模式（更接近 ADV 的 Driving Systems Edit）。你可以直接给控制器打帧，Commit 后会写入父组并清理临时关键帧。",
        "warn_bake_mode_hint": "当前为“烘焙到父组”模式：你可以继续编辑控制器。Commit 时会把你的控制器姿势换算成父组/驱动组的增量并写入。",
        "warn_timeline_requires_non_bake": "时间轴编辑模式（0~N 帧）当前不支持“烘焙到父组”。如需像 ADV 那样缩短时间轴并在中间打多帧，请先取消勾选“控制器写入父级（烘焙到父组）”。",
        "warn_bake_needs_parent": "“烘焙到父组”需要勾选“驱动父组”。",
        "warn_bake_requires_api": "当前 Maya 环境无法使用 maya.api.OpenMaya，无法进行烘焙计算。请关闭“烘焙到父组”，或换到支持 API 的 Maya 版本。",
        "warn_failed_set_driver0": "无法把驱动值设置为 0：{plug}",
        "warn_failed_set_driver_edit": "无法把驱动值设置为编辑值：{plug}",
        "warn_no_active_session": "没有正在进行的会话。请先点“进入编辑”。",
        "warn_session_driver_invalid": "会话里的驱动无效。请取消后重试。",
        "warn_failed_create_sdk": "创建 SDK 失败：{plug} ({err})",
        "warn_no_session_cancel": "没有可取消的会话。",

        # Use ASCII parentheses to avoid font/encoding issues in some Maya UI builds.
        "create_frame": "创建修型骨骼/控制器 (ADV Create)",
        "create_name": "基础名称",
        "create_parent": "父级（可选）",
        "create_radius": "控制器大小",
        "create_btn": "按当前选择位置创建",
        "create_load_parent": "从选择读取父级",
        "warn_create_select_point": "请选择一个点/物体作为创建位置（例如：顶点 vtx、locator、joint、transform）。",

        "mirror_frame": "镜像编辑",
        "mirror_dir": "方向",
        "mirror_axis": "镜像轴",
        "mirror_apply": "镜像应用",
        "mirror_warn_no_pairs": "镜像：未找到可用的 L/R 配对（需要命名包含 _L/_R 或 _L_/_R_）。",
        "mirror_warn_no_src": "镜像：当前方向下没有找到源对象（请选 L 或 R 侧控制器）。",
    },
    "en": {
        "title": "Facial Driver Recorder",
        "driver_frame": "Driver",
        "driver_node": "Driver node",
        "load_selected": "Load Selected",
        "select_node": "Select Node",
        "driver_attr": "Driver attr",
        "target_value": "Target value",
        "target_hint": "(example: X=1)",
        "frame_range": "Frame range",
        "frame_range_hint": "(0..N frames)",
        "driven_frame": "Driven Channels",
        "driven_targets_frame": "Driven Objects",
        "driven_targets_add": "Add Selected",
        "driven_targets_remove": "Remove Selected",
        "driven_targets_clear": "Clear List",
        "driven_targets_select": "Select Listed",
        "actions_frame": "Actions",
            "write_mode": "Write mode",
            "write_add": "Add layer (safe, non-destructive)",
            "write_update": "Update last layer (tool-created only)",
            "warn_update_fallback": "No existing tool-created layer found; added a new layer instead: {plug}",
            "warn_update_missing_layer": "Write mode is 'Update', but no existing layer was found to overwrite; skipped: {plug} (switch to 'Add' to create)",
        "enter_edit": "Enter Edit",
        "commit": "Apply",
        "cancel": "Cancel",
        "howto": "How to use:",
        "howto_1": "1) Select driven transforms (prefer offset/driver groups like *_qudong_G).",
        "howto_2": "2) Set driver node/attr/value, then click Enter Edit.",
        "howto_3": "3) Pose driven transforms, then click Commit.",
        "howto_4": "(Driver will be set back to 0 after Commit.)",
        "lang": "中文",
        "drive_parent": "Drive parent group (1 level up)",
        "parent_levels": "Parent levels",
        "bake_to_parent": "Edit controllers, but write to parent (bake)",
        "warn_select_driver": "Select a driver control (transform) first.",
        "warn_driver_node_not_found": "Driver node does not exist: {node}",
        "scan_sdk": "Scan SDK",
        "warn_scan_no_selection": "Select transforms to scan first.",
        "sdk_list_frame": "SDK List",
        "sdk_driver_filter": "Driver filter",
        "sdk_driver_all": "(All drivers)",
        "sdk_fold": "Fold names (hide long prefix)",
        "sdk_edit_selected": "Edit Selected SDK",
        "sdk_edit_driver": "Edit By Driver",
        "sdk_delete_selected": "Delete Selected SDK",
        "sdk_select_driver": "Select Driver",
        "warn_sdk_item_not_selected": "Select an item in the SDK list first.",
        "warn_sdk_item_invalid": "Selected SDK item is invalid/missing; rescan first.",
        "warn_sdk_no_driver_items": "No SDK layers found for this driver in the current scan.",
        "confirm_delete_title": "Delete SDK",
        "confirm_delete_msg": "Delete this SDK layer?\n\n{desc}",
        "confirm_delete_multi_msg": "Delete selected SDK layers?\n\nCount: {count}",
        "confirm_cleanup_dupes_title": "Cleanup Duplicate SDK",
        "confirm_cleanup_dupes_msg": "Duplicate layers found for the same driver on the same plug (they will add up).\n\nKeep one layer and delete the duplicates?\n\nDriver: {driver}\nDuplicate layers: {count}",
        "confirm_add_over_existing_title": "Confirm Add Layer",
        "confirm_add_over_existing_msg": "Existing SDK layers already found for this driver on some plugs.\n\nContinuing in 'Add layer' will stack effects.\n\nDriver: {driver}\nAffected plugs: {count}\n\nContinue adding?",
        "warn_delete_multi_outputs": "Curve has multiple output connections ({count}); cancelled to avoid unintended deletion: {node}",
        "warn_select_driven": "Select the driven controls (transforms) you want to pose, then Enter Edit.",
        "warn_driven_list_empty": "Driven object list is empty. Add controllers first, or select controls in the scene.",
        "warn_session_active": "A session is already active. Commit or Cancel first.",
        "warn_driver_missing": "Driver plug not found: {plug}",
        "warn_controller_selected": "You selected a controller transform: {node}. Enable 'Drive parent group' or select its offset/driver group (e.g. *_qudong_G), otherwise the controller itself will become driven (yellow / driven key ticks).",
        "warn_no_driven_plugs": "No driven plugs found. Check your selection and channel checkboxes (tX/tY/...).",
        "warn_edit_targets_selected": "Auto-selected {count} recording targets. Pose by moving/rotating these targets (do not move the original controllers, otherwise the parent/offset targets won't change and Commit will skip everything).",
        "warn_auto_bake_parent_mode": "Detected controller selection. Switched to 'Bake to parent' automatically (closer to ADV Driving Systems Edit). Key the controllers directly; Commit will write to parent groups and clean temporary keys.",
        "warn_bake_mode_hint": "Bake-to-parent mode: keep editing the controllers. On Commit, your controller pose will be converted into an additive delta on the parent/offset group.",
        "warn_timeline_requires_non_bake": "Timeline edit mode (0..N) is not supported in bake-to-parent mode yet. To use ADV-like multi-frame timeline editing, uncheck 'Bake to parent' first.",
        "warn_bake_needs_parent": "Bake-to-parent requires 'Drive parent group' to be enabled.",
        "warn_bake_requires_api": "maya.api.OpenMaya is not available in this Maya environment; bake-to-parent cannot run. Disable bake mode or use a Maya version with the API.",
        "warn_failed_set_driver0": "Failed to set driver to 0: {plug}",
        "warn_failed_set_driver_edit": "Failed to set driver to edit value: {plug}",
        "warn_no_active_session": "No active session. Use Enter Edit first.",
        "warn_session_driver_invalid": "Session driver is invalid. Cancel and try again.",
        "warn_failed_create_sdk": "Failed to create SDK for {plug}: {err}",
        "warn_no_session_cancel": "No active session to cancel.",

        "create_frame": "Create corrective joint/control (ADV Create)",
        "create_name": "Base name",
        "create_parent": "Parent (optional)",
        "create_radius": "Control size",
        "create_btn": "Create at current selection",
        "create_load_parent": "Load Parent From Selection",
        "warn_create_select_point": "Select a point/object as the placement target (e.g. mesh vtx, locator, joint, transform).",

        "mirror_frame": "Mirror Edit",
        "mirror_dir": "Direction",
        "mirror_axis": "Mirror axis",
        "mirror_apply": "Apply Mirror",
        "mirror_warn_no_pairs": "Mirror: no L/R pairs found (name must contain _L/_R or _L_/_R_).",
        "mirror_warn_no_src": "Mirror: no source nodes found for this direction (select L or R side controls).",
    },
}


def _sdk_fold_enabled():
    try:
        if cmds.optionVar(exists=_SDK_FOLD_OPT_VAR):
            return bool(int(cmds.optionVar(q=_SDK_FOLD_OPT_VAR)))
    except Exception:
        pass
    return False


def _sdk_make_display(item, folded):
    """Build UI display string for an SDK item."""
    driven_plug = str(item.get("drivenPlug") or "")
    bw_index = item.get("bwIndex")
    curve = str(item.get("curve") or "")
    driver_plug = str(item.get("driverPlug") or "")
    driver_node = driver_plug.split(".", 1)[0] if driver_plug else ""

    if folded:
        # Keep only the curve name + driver node (short and scannable).
        # Example: bw_xxx_input_1_ driver=ICon_Z
        if driver_node:
            return "{} driver={}".format(curve, driver_node)
        return "{}".format(curve)

    # Full display: drivenPlug + layer index + curve + driver plug.
    if bw_index is None:
        return "{}  {}  driver={}".format(driven_plug, curve, driver_plug or '?')
    return "{}  [#{}]  {}  driver={}".format(driven_plug, bw_index, curve, driver_plug or '?')


def _sdk_guess_controller_name(driven_node):
    """Heuristic: show a nicer controller name for ADV-style *_qudong_G nodes."""
    dn = str(driven_node or "")
    if not dn:
        return ""
    if dn.endswith("_qudong_G"):
        guess = dn[: -len("_qudong_G")] + "_Con"
        try:
            if cmds.objExists(guess):
                return guess
        except Exception:
            pass
    return dn


def _sdk_tree_root_label(driven_node, driver_node):
    ctrl = _sdk_guess_controller_name(driven_node)
    dn = driver_node or "?"
    return "{}  driver={}".format(ctrl, dn).strip()


def _sdk_tree_leaf_label(item, folded):
    driven_plug = str(item.get("drivenPlug") or "")
    driven_attr = driven_plug.split(".", 1)[1] if "." in driven_plug else driven_plug
    bw_index = item.get("bwIndex")
    curve = str(item.get("curve") or "")
    driver_plug = str(item.get("driverPlug") or "")
    driver_attr = driver_plug.split(".", 1)[1] if "." in driver_plug else driver_plug
    try:
        dt = float(item.get("driverTarget") or 0.0)
    except Exception:
        dt = 0.0

    if folded:
        if bw_index is None:
            return "{}  {}={:g}".format(driven_attr, driver_attr, dt)
        return "{}  {}={:g}  [#{}]".format(driven_attr, driver_attr, dt, bw_index)

    if bw_index is None:
        return "{}  {}={:g}  {}".format(driven_attr, driver_attr, dt, curve).strip()
    return "{}  {}={:g}  [#{}]  {}".format(driven_attr, driver_attr, dt, bw_index, curve).strip()


def _ui_sdk_refresh_tree_display(items, folded):
    """Rebuild the SDK tree view from scan items."""
    global _SDK_TREE_LEAF_MAP
    global _SDK_TREE_ROOT_MAP
    _SDK_TREE_LEAF_MAP = {}
    _SDK_TREE_ROOT_MAP = {}

    if not cmds.treeView("fdr_sdkTree", exists=True):
        return

    # Clear existing tree.
    try:
        cmds.treeView("fdr_sdkTree", e=True, removeAll=True)
    except Exception:
        try:
            cmds.treeView("fdr_sdkTree", e=True, ra=True)
        except Exception:
            pass

    # Group by (drivenNode, driverNode)
    groups = {}
    for it in (items or []):
        driven_plug = str(it.get("drivenPlug") or "")
        driven_node = driven_plug.split(".", 1)[0] if driven_plug else ""
        driver_node = str(it.get("driverNode") or "")
        if not driver_node:
            dp = str(it.get("driverPlug") or "")
            driver_node = dp.split(".", 1)[0] if dp else ""
        k = (driven_node, driver_node)
        groups.setdefault(k, []).append(it)

    # Stable order: driven name then driver name.
    ordered_keys = sorted(groups.keys(), key=lambda x: (str(x[0] or ""), str(x[1] or "")))

    root_i = 0
    leaf_i = 0
    root_ids = []
    for driven_node, driver_node in ordered_keys:
        root_i += 1
        root_id = "fdrRoot_{}".format(root_i)
        try:
            cmds.treeView("fdr_sdkTree", e=True, addItem=(root_id, ""))
            cmds.treeView("fdr_sdkTree", e=True, displayLabel=(root_id, _sdk_tree_root_label(driven_node, driver_node)))
            root_ids.append(root_id)
        except Exception:
            continue

        # Cache root -> driver info so UI actions can work when the user selects the root item.
        # Pick a representative item from the group (driverPlug/target can vary, but driver node should be the same).
        rep = (groups.get((driven_node, driver_node)) or [{}])[0]
        try:
            _SDK_TREE_ROOT_MAP[root_id] = {
                "drivenNode": driven_node,
                "driverNode": driver_node,
                "driverPlug": str(rep.get("driverPlug") or ""),
                "driverTarget": rep.get("driverTarget"),
            }
        except Exception:
            _SDK_TREE_ROOT_MAP[root_id] = {"drivenNode": driven_node, "driverNode": driver_node}

        # Sort leaves by drivenPlug then bwIndex.
        def _lk(it):
            dr = str(it.get("drivenPlug") or "")
            bi = it.get("bwIndex")
            bi = int(bi) if bi is not None else 10**9
            return (dr, bi)

        for it in sorted(groups[(driven_node, driver_node)], key=_lk):
            leaf_i += 1
            leaf_id = "fdrLeaf_{}".format(leaf_i)
            try:
                cmds.treeView("fdr_sdkTree", e=True, addItem=(leaf_id, root_id))
                cmds.treeView("fdr_sdkTree", e=True, displayLabel=(leaf_id, _sdk_tree_leaf_label(it, folded)))
                _SDK_TREE_LEAF_MAP[leaf_id] = it
            except Exception:
                continue

    # Default to collapsed (folded) roots so the list is scannable.
    for rid in root_ids:
        try:
            cmds.treeView("fdr_sdkTree", e=True, expandItem=(rid, False))
        except Exception:
            try:
                cmds.treeView("fdr_sdkTree", e=True, collapseItem=rid)
            except Exception:
                pass


def _sdk_driver_key(item):
    """Group key for SDK list: (driverPlug, driverTarget)."""
    dp = str(item.get("driverPlug") or "")
    try:
        dt = float(item.get("driverTarget") or 0.0)
    except Exception:
        dt = 0.0
    return (dp, float(dt))


def _sdk_driver_label(driver_plug, driver_target):
    if not driver_plug:
        return "?"
    # Keep it compact but explicit.
    try:
        t = float(driver_target)
    except Exception:
        t = 0.0
    # Use g formatting to avoid trailing zeros.
    return "{} = {:g}".format(driver_plug, t)


def _ui_sdk_rebuild_driver_menu():
    """Rebuild the driver filter dropdown based on current scan cache."""
    global _SDK_DRIVER_MENU_MAP
    _SDK_DRIVER_MENU_MAP = {}

    if not cmds.optionMenu("fdr_sdkDriverFilter", exists=True):
        return

    # Delete existing menu items.
    try:
        existing = cmds.optionMenu("fdr_sdkDriverFilter", q=True, ill=True) or []
    except Exception:
        existing = []
    for mi in existing:
        try:
            cmds.deleteUI(mi)
        except Exception:
            pass

    # Build unique driver groups in display order (scan items are already sorted).
    groups = []
    seen = set()
    for it in (_SDK_SCAN_ITEMS or []):
        k = _sdk_driver_key(it)
        if not k[0]:
            continue
        if k in seen:
            continue
        seen.add(k)
        groups.append(k)

    # Recreate menu items.
    cmds.menuItem(parent="fdr_sdkDriverFilter", l=_t("sdk_driver_all"))
    for dp, dt in groups:
        lab = _sdk_driver_label(dp, dt)
        _SDK_DRIVER_MENU_MAP[lab] = (dp, float(dt))
        cmds.menuItem(parent="fdr_sdkDriverFilter", l=lab)

    # Restore persisted selection (by index).
    try:
        idx = 1
        if cmds.optionVar(exists=_SDK_DRIVER_FILTER_OPT_VAR):
            idx = int(cmds.optionVar(q=_SDK_DRIVER_FILTER_OPT_VAR))
        idx = max(1, min(idx, 1 + len(groups)))
        # optionMenu uses the label for setting value.
        if idx == 1:
            cmds.optionMenu("fdr_sdkDriverFilter", e=True, v=_t("sdk_driver_all"))
        else:
            cmds.optionMenu("fdr_sdkDriverFilter", e=True, sl=idx)
    except Exception:
        pass


def _confirm(title, message):
    """Simple yes/no confirm dialog (best-effort)."""
    try:
        r = cmds.confirmDialog(
            title=title,
            message=message,
            button=["Yes", "No"],
            defaultButton="No",
            cancelButton="No",
            dismissString="No",
        )
        return r == "Yes"
    except Exception:
        # If dialog fails (e.g. in batch), default to not destructive.
        return False


def _tag_set(node, data):
    """Attach a lightweight JSON tag to a node (best-effort)."""
    if not cmds.objExists(node):
        return
    try:
        if not cmds.attributeQuery(_FDR_TAG_ATTR, node=node, exists=True):
            cmds.addAttr(node, ln=_FDR_TAG_ATTR, dt="string")
        cmds.setAttr("{}.{}".format(node, _FDR_TAG_ATTR), json.dumps(data, ensure_ascii=True), type="string")
    except Exception:
        pass


def _tag_get(node):
    if not cmds.objExists(node):
        return None
    try:
        if not cmds.attributeQuery(_FDR_TAG_ATTR, node=node, exists=True):
            return None
        raw = cmds.getAttr("{}.{}".format(node, _FDR_TAG_ATTR))
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


def _animcurve_from_plug(dest_plug):
    """Return animCurve node driving dest_plug, if any."""
    srcs = cmds.listConnections(dest_plug, s=True, d=False, p=False, scn=True) or []
    for n in srcs:
        try:
            if cmds.nodeType(n).startswith("animCurve"):
                return n
        except Exception:
            continue
    return None


def _canonical_node_name(node):
    """Best-effort canonical DAG path for stable comparisons."""
    n = str(node or "")
    if not n:
        return ""
    try:
        if cmds.objExists(n):
            long_names = cmds.ls(n, l=True) or []
            if long_names:
                return str(long_names[0])
    except Exception:
        pass
    return n


def _canonical_plug_name(plug):
    p = str(plug or "")
    if "." not in p:
        return p
    node, attr = p.split(".", 1)
    return "{}.{}".format(_canonical_node_name(node), attr)


def _plug_matches(a, b):
    """Compare plugs robustly across short/long DAG path forms."""
    pa = str(a or "")
    pb = str(b or "")
    if not pa or not pb:
        return False
    if pa == pb:
        return True

    ca = _canonical_plug_name(pa)
    cb = _canonical_plug_name(pb)
    if ca and cb and ca == cb:
        return True

    if "." not in pa or "." not in pb:
        return False
    na, aa = pa.split(".", 1)
    nb, ab = pb.split(".", 1)
    if aa != ab:
        return False
    return na.split("|")[-1] == nb.split("|")[-1]


def _curve_is_driven_by(curve, driver_plug):
    if not cmds.objExists(curve):
        return False
    # Driven keys typically connect driver -> animCurve.input
    try:
        srcs = cmds.listConnections(curve + ".input", s=True, d=False, p=True, scn=True) or []
    except Exception:
        srcs = []
    for s in (srcs or []):
        if _plug_matches(str(s), str(driver_plug)):
            return True
    return False


def _set_animcurve_key_unitless(curve, driver_value, driven_value):
    """Set a key on a unitless animCurve (animCurveUU etc) at input=driver_value."""
    cmds.setKeyframe(curve, float=float(driver_value), value=float(driven_value))
    # Tangents linear for pose-style controls.
    try:
        cmds.keyTangent(curve, e=True, float=(float(driver_value), float(driver_value)), itt="linear", ott="linear")
    except Exception:
        # Fallback: apply to all keys.
        try:
            cmds.keyTangent(curve, e=True, itt="linear", ott="linear")
        except Exception:
            pass


def _find_existing_tool_layer(
    bt_bw,
    driver_plug,
    driven_plug,
    driver_target = None,
):
    """Find an existing blendWeighted.input[i] animCurve created by this tool for driven_plug.

    Returns (index, curveNode).
    """
    try:
        size = int(cmds.getAttr(bt_bw + ".input", size=True))
    except Exception:
        size = 0

    best = None
    for i in range(max(size, 8) + 64):
        in_plug = "{}.input[{}]".format(bt_bw, i)
        curve = _animcurve_from_plug(in_plug)
        if not curve:
            continue
        if not _curve_is_driven_by(curve, driver_plug):
            continue
        tag = _tag_get(curve) or {}
        if tag.get("tool") != "facial_driver_recorder":
            continue
        tag_driven = str(tag.get("driven") or "")
        if not _plug_matches(tag_driven, str(driven_plug)):
            continue
        if driver_target is not None:
            try:
                dt = float(tag.get("driverTarget"))
            except Exception:
                dt = None
            if dt is None or abs(dt - float(driver_target)) > float(_DRIVER_TARGET_MATCH_EPS):
                continue
        # Prefer the highest index (last added layer).
        if (best is None) or (i > best[0]):
            best = (i, curve)

    return best


def _write_additive_layer(
    driver_plug,
    driver_target,
    driven_plug,
    bt,
    delta_bw,
    write_mode,
    keys = None,
    prefer_any_existing = False,
):
    """Write an additive SDK layer for driven_plug.

    Returns (result, index)
      result: "created" | "updated"
      index: blendWeighted input index used
    """
    write_mode = (write_mode or "add").lower()

    # Default keys: classic 0->0, target->delta.
    if not keys:
        keys = [(0.0, 0.0), (float(driver_target), float(delta_bw))]
    keys = _dedupe_sort_keys(keys)
    if not keys:
        keys = [(0.0, 0.0)]

    # Always enforce 0 -> 0 for additive layers.
    if abs(keys[0][0]) > 1e-8:
        keys = [(0.0, 0.0)] + keys
    else:
        keys[0] = (0.0, 0.0)

    # Re-sort after inserting the 0-key (important when target is negative).
    keys = _dedupe_sort_keys(keys)
    # Ensure the 0-key remains exactly 0.
    for i, (x, _y) in enumerate(keys):
        if abs(float(x)) <= 1e-8:
            keys[i] = (0.0, 0.0)
            break

    if write_mode == "update":
        found = _find_existing_tool_layer(bt.bw, driver_plug, driven_plug, driver_target=driver_target)
        if found:
            idx, curve = found
            # Replace all keys on the existing curve.
            try:
                cmds.cutKey(curve, clear=True)
            except Exception:
                pass
            for x, y in keys:
                _set_animcurve_key_unitless(curve, float(x), float(y))
            return "updated", idx

        # Optional fallback for SDK-list batch edit:
        # update any existing layer that matches this driver on the same blendWeighted.
        if prefer_any_existing:
            layers = _find_animcurve_layers_for_driver(bt.bw, driver_plug)
            if layers:
                layers.sort(key=lambda x: x[0])
                idx, curve = layers[-1]
                try:
                    cmds.cutKey(curve, clear=True)
                except Exception:
                    pass
                for x, y in keys:
                    _set_animcurve_key_unitless(curve, float(x), float(y))
                return "updated", idx

    # Default: create a new layer (or fallback when update layer not found).
    idx = _find_free_bw_input_index(bt.bw)
    driven_bw_plug = "{}.input[{}]".format(bt.bw, idx)
    for x, y in keys:
        _set_driven_key(driver_plug, float(x), driven_bw_plug, float(y))

    # Tag created animCurve so we can update it later.
    curve = _animcurve_from_plug(driven_bw_plug)
    if curve:
        _tag_set(
            curve,
            {
                "tool": "facial_driver_recorder",
                "driver": _canonical_plug_name(driver_plug),
                "driverTarget": float(driver_target),
                "driven": _canonical_plug_name(driven_plug),
                "bw": bt.bw,
                "bwIndex": int(idx),
            },
        )

    return "created", idx


def _mark_active_timeline_session_for_driver_batch(items):
    """Narrow the active timeline session to scanned SDK plugs and prefer updating existing layers.

    This is used by "Edit By Driver" so the batch workflow behaves like
    "enter 0..N timeline -> edit keys -> overwrite current SDK".
    """
    session = _session_load()
    if not session:
        return

    mode = str(session.get("mode") or "")
    if mode not in ("timeline", "timelineBakeToParent"):
        return

    item_scope = {
        _canonical_plug_name(str(it.get("drivenPlug") or ""))
        for it in (items or [])
        if str(it.get("drivenPlug") or "")
    }
    if not item_scope:
        return

    if mode == "timeline":
        entries = session.get("entries") or []
        entries = [
            e
            for e in entries
            if _canonical_plug_name(str(e.get("plug") or "")) in item_scope
        ]
        session["entries"] = entries
        session["prefer_existing_layer"] = True
        if not entries:
            _cancel_timeline(session)
            _warn(_t("warn_sdk_no_driver_items"))
            return
        _session_save(session)
        return

    # timelineBakeToParent
    pairs = session.get("pairs") or []
    pairs = [
        p
        for p in pairs
        if _canonical_plug_name(str(p.get("driven_plug") or "")) in item_scope
    ]
    session["pairs"] = pairs
    session["prefer_existing_layer"] = True

    # Keep only controller edit plugs still referenced by remaining pairs.
    edit_scope = {str(p.get("edit_plug") or "") for p in pairs if str(p.get("edit_plug") or "")}
    ctrl_entries = session.get("ctrl_entries") or []
    session["ctrl_entries"] = [e for e in ctrl_entries if str(e.get("plug") or "") in edit_scope]

    if not pairs:
        _cancel_timeline_bake_to_parent(session)
        _warn(_t("warn_sdk_no_driver_items"))
        return

    _session_save(session)


def _optvar_get_str(name, default):
    if cmds.optionVar(exists=name):
        try:
            v = cmds.optionVar(q=name)
            if isinstance(v, str) and v:
                return v
        except Exception:
            pass
    return default


def _optvar_get_int(name, default):
    if cmds.optionVar(exists=name):
        try:
            return int(cmds.optionVar(q=name))
        except Exception:
            pass
    return int(default)


def _mirror_axis_matrix(axis):
    """Reflection matrix for a given axis (world plane)."""
    if om2 is None:
        raise RuntimeError("maya.api.OpenMaya is not available")

    a = (axis or "X").upper()
    if a not in ("X", "Y", "Z"):
        a = "X"

    # diag(-1,1,1,1) etc.
    sx, sy, sz = 1.0, 1.0, 1.0
    if a == "X":
        sx = -1.0
    elif a == "Y":
        sy = -1.0
    elif a == "Z":
        sz = -1.0

    return om2.MMatrix(
        [
            sx, 0.0, 0.0, 0.0,
            0.0, sy, 0.0, 0.0,
            0.0, 0.0, sz, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
    )


def _decompose_local_trs(
    m_local, rotate_order_index
):
    """Decompose local matrix into (t, rDegrees, s) respecting rotateOrder."""
    if om2 is None:
        raise RuntimeError("maya.api.OpenMaya is not available")

    tm = om2.MTransformationMatrix(m_local)
    t = tm.translation(om2.MSpace.kTransform)

    e = tm.rotation()
    order_map = {
        0: om2.MEulerRotation.kXYZ,
        1: om2.MEulerRotation.kYZX,
        2: om2.MEulerRotation.kZXY,
        3: om2.MEulerRotation.kXZY,
        4: om2.MEulerRotation.kYXZ,
        5: om2.MEulerRotation.kZYX,
    }
    e.reorderIt(order_map.get(int(rotate_order_index), om2.MEulerRotation.kXYZ))
    r = (om2.MAngle(e.x).asDegrees(), om2.MAngle(e.y).asDegrees(), om2.MAngle(e.z).asDegrees())

    s = tm.scale(om2.MSpace.kTransform)
    return (float(t.x), float(t.y), float(t.z)), (float(r[0]), float(r[1]), float(r[2])), (float(s[0]), float(s[1]), float(s[2]))


def _mirror_counterpart_name(node):
    """Return the opposite side counterpart name, preserving dag-path prefix.

    Supports common naming styles:
    - *_L_* <-> *_R_*
    - *_L   <-> *_R
    - L_*   <-> R_*
    - Left* <-> Right*
    """
    if not node:
        return None

    # Preserve dag-path prefix if present.
    if "|" in node:
        prefix, leaf = node.rsplit("|", 1)
        prefix = prefix + "|"
    else:
        prefix, leaf = "", node

    new_leaf = None
    if "_L_" in leaf:
        new_leaf = leaf.replace("_L_", "_R_")
    elif "_R_" in leaf:
        new_leaf = leaf.replace("_R_", "_L_")
    elif leaf.endswith("_L"):
        new_leaf = leaf[:-2] + "_R"
    elif leaf.endswith("_R"):
        new_leaf = leaf[:-2] + "_L"
    elif leaf.startswith("L_"):
        new_leaf = "R_" + leaf[2:]
    elif leaf.startswith("R_"):
        new_leaf = "L_" + leaf[2:]
    elif "Left" in leaf:
        new_leaf = leaf.replace("Left", "Right")
    elif "Right" in leaf:
        new_leaf = leaf.replace("Right", "Left")

    if not new_leaf:
        return None

    return prefix + new_leaf


def _mirror_build_pairs(nodes):
    """Build a src->dst mapping for L<->R pairs from the provided nodes."""
    pairs = {}
    for n in nodes:
        if not cmds.objExists(n):
            continue
        # Only mirror nodes that look like sided controls.
        if ("_L" not in n) and ("_R" not in n) and ("Left" not in n) and ("Right" not in n) and ("L_" not in n) and ("R_" not in n):
            continue
        dst = _mirror_counterpart_name(n)
        if not dst or dst == n:
            continue
        if cmds.objExists(dst):
            pairs[n] = dst
    return pairs


def _mirror_side(node):
    """Return 'L' or 'R' if the node name looks sided, otherwise None."""
    leaf = node.rsplit("|", 1)[-1]
    if "_L_" in leaf or leaf.endswith("_L") or leaf.startswith("L_") or "Left" in leaf:
        return "L"
    if "_R_" in leaf or leaf.endswith("_R") or leaf.startswith("R_") or "Right" in leaf:
        return "R"
    return None


def _mirror_apply_once(src, dst, channels, axis):
    """Mirror src to dst by copying LOCAL channel values.

    This matches most facial/biped control rigs (including ADV-style workflows):
    users expect per-channel mirroring (e.g. X axis mirror => tx negated, ty/tz kept)
    rather than world-matrix reflections which can introduce unexpected axis coupling
    under rotated parents.
    """
    if not (cmds.objExists(src) and cmds.objExists(dst)):
        return

    axis = (axis or "X").upper()
    if axis not in ("X", "Y", "Z"):
        axis = "X"

    try:
        tx = _get_scalar(src + ".translateX")
        ty = _get_scalar(src + ".translateY")
        tz = _get_scalar(src + ".translateZ")
        rx = _get_scalar(src + ".rotateX")
        ry = _get_scalar(src + ".rotateY")
        rz = _get_scalar(src + ".rotateZ")
        sx = _get_scalar(src + ".scaleX")
        sy = _get_scalar(src + ".scaleY")
        sz = _get_scalar(src + ".scaleZ")
    except Exception:
        return

    # Basic per-channel sign rules.
    # Mirror across X means flipping the X position and the Y/Z rotation components.
    if axis == "X":
        tx = -tx
        ry = -ry
        rz = -rz
    elif axis == "Y":
        ty = -ty
        rx = -rx
        rz = -rz
    elif axis == "Z":
        tz = -tz
        rx = -rx
        ry = -ry

    desired = {
        "translateX": tx,
        "translateY": ty,
        "translateZ": tz,
        "rotateX": rx,
        "rotateY": ry,
        "rotateZ": rz,
        # For most controller rigs, keep scale as-is.
        "scaleX": sx,
        "scaleY": sy,
        "scaleZ": sz,
    }

    for ch in (channels or []):
        plug = "{}.{}".format(dst, ch)
        if not _attr_exists(plug):
            continue
        # Don't fight the rig if this channel is still connected.
        if _get_incoming_source_plug(plug):
            continue
        try:
            if cmds.getAttr(plug, lock=True):
                continue
        except Exception:
            pass

        v = desired.get(ch)
        if v is None:
            continue
        try:
            _set_scalar(plug, float(v))
        except Exception:
            pass


@_undoable("FDR Mirror Apply")
def mirror_apply(nodes, channels, axis, direction):
    """Apply one-shot mirror for nodes (selection/session). direction: 'L2R' or 'R2L'."""
    nodes = [n for n in (nodes or []) if cmds.objExists(n)]
    if not nodes:
        return

    pairs = _mirror_build_pairs(nodes)
    if not pairs:
        _warn(_t("mirror_warn_no_pairs"))
        return

    direction = (direction or "L2R").upper()
    if direction not in ("L2R", "R2L"):
        direction = "L2R"

    wanted_src_side = "L" if direction == "L2R" else "R"
    had_src = False
    for src, dst in pairs.items():
        if _mirror_side(src) != wanted_src_side:
            continue
        had_src = True
        _mirror_apply_once(src, dst, channels, axis)

    if not had_src:
        _warn(_t("mirror_warn_no_src"))


def _get_lang():
    if cmds.optionVar(exists=_LANG_OPT_VAR):
        try:
            v = cmds.optionVar(q=_LANG_OPT_VAR)
            if v in ("zh", "en"):
                return v
        except Exception:
            pass
    return "zh"


def _set_lang(lang):
    if lang not in ("zh", "en"):
        lang = "zh"
    cmds.optionVar(sv=(_LANG_OPT_VAR, lang))


def _t(key):
    lang = _get_lang()
    return _STRINGS.get(lang, _STRINGS["en"]).get(key, key)


# ----------------------------
# Low-level helpers
# ----------------------------

def _warn(msg):
    cmds.warning(msg)


def _selection_world_position_average():
    """Return a world-space position for the current selection.

    Supports:
    - transform selection (uses its ws translation)
    - component selection (vtx/edge/face): converts to vertices and averages ws positions
    """
    sel = cmds.ls(sl=True, fl=True) or []
    if not sel:
        return None

    # If it's a component (contains a '.'), convert to vertices and average.
    if "." in sel[0]:
        vtx = cmds.polyListComponentConversion(sel, toVertex=True) or []
        vtx = cmds.ls(vtx, fl=True) or []
        if not vtx:
            return None
        acc = [0.0, 0.0, 0.0]
        for v in vtx:
            try:
                p = cmds.pointPosition(v, w=True)
            except Exception:
                continue
            acc[0] += float(p[0])
            acc[1] += float(p[1])
            acc[2] += float(p[2])
        n = float(len(vtx))
        if n <= 0.0:
            return None
        return acc[0] / n, acc[1] / n, acc[2] / n

    # Transform selection.
    node = sel[0]
    if not cmds.objExists(node):
        return None
    try:
        p = cmds.xform(node, q=True, ws=True, t=True)
        return float(p[0]), float(p[1]), float(p[2])
    except Exception:
        return None


def _ensure_suffix(name, suffix):
    return name if name.endswith(suffix) else (name + suffix)


@_undoable("FDR Create Corrective")
def create_corrective_joint_and_control(base_name, parent, radius= 1.0):
    """Create a corrective joint + controller at current selection.

    Creates:
    - <base>_joint
    - <base>_Con inside <base>_qudong_G
    Parents both joint and qudong_G under `parent` if provided.
    Adds a parentConstraint + scaleConstraint from ctrl -> joint.
    """
    pos = _selection_world_position_average()
    if pos is None:
        _warn(_t("warn_create_select_point"))
        return {}

    base_name = (base_name or "").strip()
    if not base_name:
        base_name = "Corrective"

    joint_name = _ensure_suffix(base_name, "_joint")
    ctrl_name = _ensure_suffix(base_name, "_Con")
    grp_name = _ensure_suffix(base_name, "_qudong_G")

    # Create joint.
    cmds.select(cl=True)
    jnt = cmds.joint(n=joint_name, p=pos)
    try:
        cmds.setAttr(jnt + ".jointOrientX", 0)
        cmds.setAttr(jnt + ".jointOrientY", 0)
        cmds.setAttr(jnt + ".jointOrientZ", 0)
    except Exception:
        pass

    # Create controller (zeroed under qudong group).
    ctrl = cmds.circle(name=ctrl_name, normal=(0, 0, 1), radius=float(radius), ch=False)[0]
    grp = cmds.group(ctrl, name=grp_name)
    try:
        cmds.xform(grp, ws=True, t=pos)
    except Exception:
        pass

    # Parent under requested parent.
    if parent and cmds.objExists(parent):
        try:
            cmds.parent(grp, parent)
        except Exception:
            pass
        try:
            cmds.parent(jnt, parent)
            cmds.xform(jnt, ws=True, t=pos)
        except Exception:
            pass

    # Constraints: ctrl drives joint.
    try:
        cmds.parentConstraint(ctrl, jnt, mo=True)
    except Exception:
        pass
    try:
        cmds.scaleConstraint(ctrl, jnt, mo=True)
    except Exception:
        pass

    # Add to common sets if they exist (ADV-like housekeeping).
    for s in ("AllSet", "ControlSet"):
        if cmds.objExists(s):
            try:
                cmds.sets(ctrl, add=s)
                shape = (cmds.listRelatives(ctrl, s=True, f=False) or [None])[0]
                if shape:
                    cmds.sets(shape, add=s)
            except Exception:
                pass

    return {"joint": jnt, "ctrl": ctrl, "group": grp}


def _optvar_exists(name):
    return bool(cmds.optionVar(exists=name))


def _optvar_get_json(name):
    if not _optvar_exists(name):
        return None
    try:
        return json.loads(cmds.optionVar(q=name))
    except Exception:
        return None


def _optvar_set_json(name, data):
    cmds.optionVar(sv=(name, json.dumps(data)))


def _optvar_remove(name):
    if _optvar_exists(name):
        cmds.optionVar(remove=name)


def _normalize_transform_nodes(nodes):
    out = []
    seen = set()
    for n in (nodes or []):
        try:
            node = str(n).strip()
        except Exception:
            node = ""
        if not node or node in seen:
            continue
        try:
            if not cmds.objExists(node):
                continue
            if cmds.nodeType(node) != "transform":
                continue
        except Exception:
            continue
        seen.add(node)
        out.append(node)
    return out


def _driven_targets_load():
    data = _optvar_get_json(_DRIVEN_TARGETS_OPT_VAR)
    if not isinstance(data, list):
        return []
    return _normalize_transform_nodes(data)


def _driven_targets_save(nodes):
    clean = _normalize_transform_nodes(nodes)
    try:
        _optvar_set_json(_DRIVEN_TARGETS_OPT_VAR, clean)
    except Exception:
        pass


def _attr_exists(plug):
    # Prefer the simplest check first: Maya can answer attribute existence for plugs.
    # This also works when `node` is a full DAG path (e.g. "|grp|ctrl.translateX").
    try:
        if cmds.objExists(plug):
            return True
    except Exception:
        pass

    try:
        node, attr = plug.split(".", 1)
    except ValueError:
        return False

    if not cmds.objExists(node):
        return False

    try:
        return bool(cmds.attributeQuery(attr, node=node, exists=True))
    except Exception:
        # Some Maya cmds are picky about full DAG paths in the `node=` argument.
        # Retry with the leaf name if possible.
        try:
            short = node.split("|")[-1]
            if short and cmds.objExists(short):
                return bool(cmds.attributeQuery(attr, node=short, exists=True))
        except Exception:
            pass
    return False


def _get_scalar(plug):
    # Assumes scalar plug (tx/ry/etc.)
    return float(cmds.getAttr(plug))


def _set_scalar(plug, value):
    cmds.setAttr(plug, value)


def _is_rotate_plug(plug):
    """Return True if this plug is a standard Euler rotate channel (rotateX/Y/Z).

    Maya rotate attrs are in degrees but can accumulate beyond 360.
    When recording additive layers we typically want the shortest signed delta.
    """
    try:
        _node, attr = plug.split(".", 1)
    except ValueError:
        return False
    return str(attr).lower().startswith("rotate")


def _shortest_angle_delta_deg(base_deg, target_deg):
    """Compute shortest signed delta (degrees) from base -> target.

    This avoids wrap issues where base might be 720 but visually equals 0,
    which would otherwise produce huge deltas like -678.
    """
    try:
        b = float(base_deg)
        t = float(target_deg)
    except Exception:
        return float(target_deg) - float(base_deg)

    # Wrap into [-180, 180) range.
    d = (t - b + 180.0) % 360.0 - 180.0
    return float(d)


def _delta_for_plug(plug, base, target):
    """Delta policy for recording.

    For rotate plugs we use shortest angular delta; for others simple subtraction.
    """
    if _is_rotate_plug(str(plug)):
        return _shortest_angle_delta_deg(float(base), float(target))
    return float(target) - float(base)


def _plug_split(plug):
    node, attr = plug.split(".", 1)
    return str(node), str(attr)


def _mel_escape_string(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _mel_proc_exists(proc_name):
    if mel is None:
        return False
    if not proc_name:
        return False
    try:
        return bool(int(mel.eval('exists "{}"'.format(_mel_escape_string(proc_name)))))
    except Exception:
        try:
            return bool(int(mel.eval("exists {}".format(proc_name))))
        except Exception:
            return False


def _driver_uses_adv_q_flow(driver_plug):
    """Return True when driver should be evaluated through ADV blended/Q helpers."""
    if not driver_plug or "." not in driver_plug:
        return False
    _node, attr = _plug_split(driver_plug)
    if attr.startswith("qRotate"):
        return True
    # Keep ordinary TRS attributes on direct scalar path.
    attr_l = attr.lower()
    if attr_l.startswith("translate") or attr_l.startswith("rotate") or attr_l.startswith("scale"):
        return False
    # Non-settable custom driver attrs in ADV are usually blended-driver outputs.
    if not _mel_proc_exists("asSetBlendedAttribute"):
        return False
    try:
        return not bool(cmds.getAttr(driver_plug, settable=True))
    except Exception:
        return False


def _set_driver_value_adv(driver_plug, value):
    """Set ADV blended/Q driver value using MEL helpers without noisy logging."""
    if mel is None or (not driver_plug) or ("." not in driver_plug):
        return False
    node, attr = _plug_split(driver_plug)
    # ADV tools commonly expect short names; long DAG paths can break FK-prefixed lookups.
    if "|" in node:
        node = node.split("|")[-1]
    node_q = _mel_escape_string(node)
    attr_q = _mel_escape_string(attr)
    val = float(value)

    used = False
    # Blended attributes (including blended QRotate drivers).
    if _mel_proc_exists("asSetBlendedAttribute"):
        try:
            mel.eval('asSetBlendedAttribute "{}" "{}" {} 0;'.format(node_q, attr_q, val))
            used = True
        except Exception:
            pass

    # Single qRotate driver should also push the source rotate channel.
    if attr.startswith("qRotate") and _mel_proc_exists("asSetRotationFromQRotate"):
        try:
            mel.eval('asSetRotationFromQRotate "{}" "{}" {};'.format(node_q, attr_q, val))
            used = True
        except Exception:
            pass

    return used


def _set_driver_value(driver_plug, value):
    """Set driver value; route ADV Q/blended drivers to MEL helpers when needed."""
    if _driver_uses_adv_q_flow(driver_plug):
        if _set_driver_value_adv(driver_plug, value):
            return
    _set_scalar(driver_plug, value)


def _get_incoming_source_plug(dest_plug):
    """Return the first incoming source plug driving dest_plug, or None."""
    srcs = cmds.listConnections(dest_plug, s=True, d=False, p=True, scn=True) or []
    return srcs[0] if srcs else None


def _disconnect(src_plug, dest_plug):
    try:
        if cmds.isConnected(src_plug, dest_plug):
            cmds.disconnectAttr(src_plug, dest_plug)
    except Exception:
        pass


def _connect(src_plug, dest_plug):
    try:
        if not cmds.isConnected(src_plug, dest_plug):
            cmds.connectAttr(src_plug, dest_plug, f=True)
    except Exception:
        pass


def _safe_name(s):
    # CreateNode names can't contain these.
    return (
        s.replace("|", "_")
        .replace(":", "_")
        .replace(".", "_")
        .replace("[", "_")
        .replace("]", "_")
    )


def _is_controller_transform(node):
    """Heuristic: transform with a nurbsCurve shape."""
    if not cmds.objExists(node):
        return False
    shapes = cmds.listRelatives(node, s=True, f=False) or []
    for s in shapes:
        try:
            if cmds.nodeType(s) == "nurbsCurve":
                return True
        except Exception:
            continue
    return False


def _should_auto_bake_to_parent(nodes, use_parent, bake_to_parent):
    """Auto-switch to bake workflow when users selected controllers under parent-drive mode.

    This matches ADV's edit behavior more closely: users animate controller transforms,
    but the committed result should be written onto the parent/offset driven groups.
    """
    if bake_to_parent or (not use_parent):
        return False
    for n in (nodes or []):
        if _is_controller_transform(str(n)):
            return True
    return False


def _parent_levels(nodes, levels):
    """Return unique parents N levels up for each node (skips nodes without enough parents)."""
    levels = max(int(levels), 1)
    out = []
    for n in nodes:
        cur = n
        ok = True
        for _ in range(levels):
            p = cmds.listRelatives(cur, p=True, f=False) or []
            if not p:
                ok = False
                break
            cur = p[0]
        if ok and cur not in out:
            out.append(cur)
    return out


def _parent_map(nodes, levels):
    """Map each node to its ancestor N levels up (nodes without enough parents are skipped)."""
    levels = max(int(levels), 1)
    out = {}
    for n in nodes:
        cur = n
        ok = True
        for _ in range(levels):
            p = cmds.listRelatives(cur, p=True, f=False) or []
            if not p:
                ok = False
                break
            cur = p[0]
        if ok:
            out[n] = cur
    return out


def _m_from_list16(vals):
    if om2 is None:
        raise RuntimeError("maya.api.OpenMaya is not available")
    return om2.MMatrix(vals)


def _list16_from_m(m):
    """Best-effort: convert an MMatrix into a flat list[16] (row-major) for cmds.xform.

    maya.api.OpenMaya MMatrix iteration behavior can vary (flat 16 vs 4 rows). We normalize.
    """
    try:
        vals = list(m)
    except Exception:
        vals = []

    # Case A: already flat 16.
    if len(vals) == 16 and (not isinstance(vals[0], (list, tuple))):
        return [float(x) for x in vals]

    # Case B: 4 rows of 4.
    if len(vals) == 4 and isinstance(vals[0], (list, tuple)) and len(vals[0]) == 4:
        out = []
        for r in range(4):
            for c in range(4):
                out.append(float(vals[r][c]))
        return out

    # Case C: indexable as m[r][c].
    out = []
    try:
        for r in range(4):
            row = m[r]
            for c in range(4):
                out.append(float(row[c]))
        if len(out) == 16:
            return out
    except Exception:
        pass

    # Give up: identity.
    return [
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    ]


def _m_identity():
    if om2 is None:
        raise RuntimeError("maya.api.OpenMaya is not available")
    return om2.MMatrix()


def _decompose_local_tr(m_local, rotate_order_index):
    """Decompose a local matrix into (translate, rotateDegrees) respecting rotateOrder."""
    if om2 is None:
        raise RuntimeError("maya.api.OpenMaya is not available")

    tm = om2.MTransformationMatrix(m_local)
    t = tm.translation(om2.MSpace.kTransform)

    # Rotation from matrix is in radians; reorder to match the node's rotateOrder.
    e = tm.rotation()
    order_map = {
        0: om2.MEulerRotation.kXYZ,
        1: om2.MEulerRotation.kYZX,
        2: om2.MEulerRotation.kZXY,
        3: om2.MEulerRotation.kXZY,
        4: om2.MEulerRotation.kYXZ,
        5: om2.MEulerRotation.kZYX,
    }
    e.reorderIt(order_map.get(int(rotate_order_index), om2.MEulerRotation.kXYZ))
    r = (om2.MAngle(e.x).asDegrees(), om2.MAngle(e.y).asDegrees(), om2.MAngle(e.z).asDegrees())

    return (float(t.x), float(t.y), float(t.z)), (float(r[0]), float(r[1]), float(r[2]))


class _BlendTarget:
    def __init__(self, bw, conversion_factor, kind):
        self.bw = bw
        self.conversion_factor = conversion_factor  # 1.0 if none
        self.kind = kind  # "direct" or "unitConversion" or "created"


def _angle_unit_to_radians_scale():
    """Return radians-per-unit for Maya's current angle unit."""
    try:
        unit = str(cmds.currentUnit(q=True, a=True) or "deg").lower()
    except Exception:
        unit = "deg"

    if unit == "rad":
        return 1.0
    if unit == "min":
        return math.pi / (180.0 * 60.0)
    if unit == "sec":
        return math.pi / (180.0 * 3600.0)
    return math.pi / 180.0


def _to_blendweighted_delta(driven_plug, delta, bt):
    """Map posed delta (display units) to blendWeighted input units."""
    out = float(delta)
    if (not bt) or ("." not in str(driven_plug)):
        return out

    try:
        _node, attr = str(driven_plug).split(".", 1)
    except ValueError:
        return out

    if not str(attr).lower().startswith("rotate"):
        return out

    # Only apply scaling when there is a unitConversion in the path.
    if bt.kind not in ("unitConversion", "created"):
        return out

    try:
        cf = float(bt.conversion_factor)
    except Exception:
        cf = 1.0
    if abs(cf) <= 1e-12:
        return out

    # unitConversion computes output = input * conversionFactor in internal angle units (radians).
    # getAttr returns current UI angle units, so convert UI delta back to BW input space.
    return out * _angle_unit_to_radians_scale() / cf


def _find_blendweighted_for_driven(dest_plug, recorded_src_plug= None):
    """Find the blendWeighted that ultimately drives dest_plug.

    Returns _BlendTarget(bw, conversion_factor, kind)

    If recorded_src_plug is provided, prefer it (more stable while we temporarily disconnect).
    """

    src_plug = recorded_src_plug or _get_incoming_source_plug(dest_plug)
    if not src_plug:
        return None

    src_node = src_plug.split(".", 1)[0]
    src_type = cmds.nodeType(src_node)

    if src_type == "blendWeighted" and src_plug.endswith(".output"):
        return _BlendTarget(bw=src_node, conversion_factor=1.0, kind="direct")

    if src_type == "unitConversion" and src_plug.endswith(".output"):
        try:
            cf = float(cmds.getAttr(src_node + ".conversionFactor"))
        except Exception:
            cf = 1.0

        bw_src = cmds.listConnections(src_node + ".input", s=True, d=False, p=True, scn=True) or []
        if not bw_src:
            return None
        bw_node = bw_src[0].split(".", 1)[0]
        if cmds.nodeType(bw_node) == "blendWeighted":
            return _BlendTarget(bw=bw_node, conversion_factor=cf, kind="unitConversion")

    return None


def _ensure_network_for_driven(dest_plug):
    """Ensure there is a blendWeighted network feeding dest_plug.

    If already driven by blendWeighted/unitConversion, returns it.
    If not driven, creates a new network and connects it.
    """

    found = _find_blendweighted_for_driven(dest_plug)
    if found:
        return found

    dest_node, dest_attr = dest_plug.split(".", 1)
    safe = _safe_name(dest_node + "_" + dest_attr)

    bw = cmds.createNode("blendWeighted", n="bw_" + safe)
    # Keep scenes cleaner.
    try:
        cmds.setAttr(bw + ".isHistoricallyInteresting", 0)
    except Exception:
        pass

    if dest_attr.lower().startswith("rotate"):
        uc = cmds.createNode("unitConversion", n="uc_" + safe)
        uc_cf = float(_angle_unit_to_radians_scale())
        try:
            cmds.setAttr(uc + ".conversionFactor", uc_cf)
        except Exception:
            pass
        _connect(bw + ".output", uc + ".input")
        _connect(uc + ".output", dest_plug)
        return _BlendTarget(bw=bw, conversion_factor=uc_cf, kind="created")

    _connect(bw + ".output", dest_plug)
    return _BlendTarget(bw=bw, conversion_factor=1.0, kind="created")


def _find_free_bw_input_index(bw, search_extra= 64):
    """Find a free (unconnected) index on blendWeighted.input[*]."""
    try:
        size = int(cmds.getAttr(bw + ".input", size=True))
    except Exception:
        size = 0

    max_i = max(size + search_extra, 8)
    for i in range(max_i):
        plug = "{}.input[{}]".format(bw, i)
        if not (cmds.listConnections(plug, s=True, d=False, p=True, scn=True) or []):
            return i

    return max_i


def _set_driven_key(driver_plug, driver_value, driven_plug, driven_value):
    """Create/update a driven key on driven_plug at driver_value."""
    # Use linear as a safe default for pose style controls.
    cmds.setDrivenKeyframe(
        driven_plug,
        currentDriver=driver_plug,
        driverValue=driver_value,
        value=driven_value,
        inTangentType="linear",
        outTangentType="linear",
    )


def _get_playback_slider():
    """Best-effort resolve the global playback slider control for timeControl queries."""
    if mel is None:
        return None
    try:
        return str(mel.eval("$tmp=$gPlayBackSlider"))
    except Exception:
        return None


def _playback_state_capture():
    """Capture timeline/playback state so we can restore on Commit/Cancel."""
    state = {}
    try:
        state["min"] = float(cmds.playbackOptions(q=True, min=True))
        state["max"] = float(cmds.playbackOptions(q=True, max=True))
        state["ast"] = float(cmds.playbackOptions(q=True, ast=True))
        state["aet"] = float(cmds.playbackOptions(q=True, aet=True))
    except Exception:
        pass

    try:
        state["currentTime"] = float(cmds.currentTime(q=True))
    except Exception:
        pass

    try:
        state["autoKey"] = bool(cmds.autoKeyframe(q=True, state=True))
    except Exception:
        pass

    slider = _get_playback_slider()
    if slider:
        try:
            state["snap"] = bool(cmds.timeControl(slider, q=True, snap=True))
        except Exception:
            pass

    return state


def _playback_state_restore(state):
    if not state:
        return

    slider = _get_playback_slider()
    if slider and ("snap" in state):
        try:
            cmds.timeControl(slider, e=True, snap=bool(state.get("snap")))
        except Exception:
            pass

    try:
        if "min" in state:
            cmds.playbackOptions(e=True, min=float(state["min"]))
        if "max" in state:
            cmds.playbackOptions(e=True, max=float(state["max"]))
        if "ast" in state:
            cmds.playbackOptions(e=True, ast=float(state["ast"]))
        if "aet" in state:
            cmds.playbackOptions(e=True, aet=float(state["aet"]))
    except Exception:
        pass

    try:
        if "currentTime" in state:
            cmds.currentTime(float(state["currentTime"]), e=True)
    except Exception:
        pass

    try:
        if "autoKey" in state:
            cmds.autoKeyframe(state=bool(state["autoKey"]))
    except Exception:
        pass


def _driver_value_from_time(driver_target, frame_range, time_value):
    fr = max(int(frame_range), 1)
    t = float(time_value)
    if t < 0.0:
        t = 0.0
    if t > float(fr):
        t = float(fr)
    return float(driver_target) * (t / float(fr))


def _apply_driver_value_for_time(driver_plug, driver_target, frame_range, time_value= None):
    if time_value is None:
        try:
            time_value = float(cmds.currentTime(q=True))
        except Exception:
            time_value = 0.0
    dv = _driver_value_from_time(float(driver_target), int(frame_range), float(time_value))
    # Time-changed callbacks can fire very frequently while scrubbing.
    # Keep them out of undo queue to avoid flooding undo steps.
    with _suspend_undo_recording():
        _set_driver_value(str(driver_plug), float(dv))


def _create_driver_time_script_job(driver_plug, driver_target, frame_range):
    try:
        return int(
            cmds.scriptJob(
                event=[
                    "timeChanged",
                    lambda _args=None, _dp=str(driver_plug), _dt=float(driver_target), _fr=int(frame_range): _apply_driver_value_for_time(_dp, _dt, _fr),
                ],
                protected=True,
                killWithScene=True,
            )
        )
    except Exception:
        return None


def _kill_script_job(job_id):
    if not job_id:
        return
    try:
        if cmds.scriptJob(exists=int(job_id)):
            cmds.scriptJob(kill=int(job_id), force=True)
    except Exception:
        pass


def _restore_timeline_driver_mapping(session, driver_plug):
    mode = str(session.get("driver_time_mode") or "md")
    if mode == "scriptJob":
        _kill_script_job(session.get("driver_time_job"))
        if driver_plug and _attr_exists(driver_plug):
            try:
                _set_driver_value(driver_plug, 0.0)
            except Exception:
                pass
        return

    md = session.get("driver_time_md")
    if md and cmds.objExists(str(md)):
        _disconnect_if_connected(str(md) + ".outputX", str(driver_plug))
        _safe_delete(str(md))

    driver_src = session.get("driver_src")
    if driver_src and _attr_exists(driver_plug):
        try:
            _connect(str(driver_src), driver_plug)
        except Exception:
            pass
    else:
        try:
            _set_driver_value(driver_plug, 0.0)
        except Exception:
            pass

    if session.get("driver_locked") and _attr_exists(driver_plug):
        try:
            cmds.setAttr(driver_plug, lock=True)
        except Exception:
            pass


def _safe_delete(node):
    if node and cmds.objExists(node):
        try:
            cmds.delete(node)
        except Exception:
            pass


def _disconnect_if_connected(src_plug, dst_plug):
    try:
        if cmds.isConnected(src_plug, dst_plug):
            cmds.disconnectAttr(src_plug, dst_plug)
    except Exception:
        pass


def _delete_driving_animcurves(dest_plug):
    """Delete animCurve nodes that currently drive dest_plug (cleanup for timeline edit)."""
    try:
        src_nodes = cmds.listConnections(dest_plug, s=True, d=False, p=False, scn=True) or []
    except Exception:
        src_nodes = []
    for n in src_nodes:
        try:
            if cmds.nodeType(n).startswith("animCurve"):
                _safe_delete(n)
        except Exception:
            continue


def _collect_animcurves_on_node(node):
    """Collect animCurve nodes directly connected to a transform node (incoming)."""
    if not node or (not cmds.objExists(node)):
        return set()
    try:
        curves = cmds.listConnections(node, s=True, d=False, p=False, scn=True, type="animCurve") or []
        return set([str(c) for c in curves if c and cmds.objExists(c)])
    except Exception:
        return set()


def _cleanup_new_animcurves_from_session(session):
    """Delete animCurves created during timeline edit on tracked edit nodes.

    ADV's DS edit does not leave ordinary keyframes on controllers. This cleanup keeps
    that behavior by removing only animCurves that were not present before Enter Edit.
    """
    if not session:
        return

    nodes = [str(n) for n in (session.get("cleanup_nodes") or []) if n]
    pre_map = session.get("pre_animcurves") or {}
    if not nodes:
        return

    for n in nodes:
        pre = set([str(c) for c in (pre_map.get(n) or []) if c])
        cur = _collect_animcurves_on_node(n)
        for c in sorted(list(cur - pre)):
            _safe_delete(c)


def _dedupe_sort_keys(keys):
    """Sort by driver value and de-dupe by driver value (keep last)."""
    tmp = {}
    for x, y in keys or []:
        try:
            tmp[float(x)] = float(y)
        except Exception:
            continue
    out = sorted(tmp.items(), key=lambda kv: kv[0])
    return [(float(x), float(y)) for x, y in out]


# ----------------------------
# Session data (stored in optionVar)
# ----------------------------

def _session_load():
    return _optvar_get_json(_SESSION_OPT_VAR)


def _session_save(data):
    _optvar_set_json(_SESSION_OPT_VAR, data)


def _session_clear():
    _optvar_remove(_SESSION_OPT_VAR)


# ----------------------------
# Core operations
# ----------------------------

@_undoable("FDR Enter Edit")
def enter_edit(driver_plug, driver_target_value, driven_nodes, channels):
    """Disconnect driven channels so user can pose them at driver_target_value."""

    if not _attr_exists(driver_plug):
        _warn(_t("warn_driver_missing").format(plug=driver_plug))
        return

    driven_plugs = []
    for n in driven_nodes:
        if not cmds.objExists(n):
            continue
        for ch in channels:
            plug = "{}.{}".format(n, ch)
            if _attr_exists(plug):
                driven_plugs.append(plug)

    if not driven_plugs:
        _warn(_t("warn_no_driven_plugs"))
        return

    # If a previous session exists, refuse to overwrite (safer).
    if _session_load():
        _warn(_t("warn_session_active"))
        return

    # Capture base pose at driver=0 with the rig connected.
    try:
        _set_driver_value(driver_plug, 0.0)
    except Exception:
        _warn(_t("warn_failed_set_driver0").format(plug=driver_plug))
        return

    entries = []
    for plug in driven_plugs:
        # Store lock state and unlock temporarily for editing.
        try:
            locked = bool(cmds.getAttr(plug, lock=True))
        except Exception:
            locked = False
        if locked:
            try:
                cmds.setAttr(plug, lock=False)
            except Exception:
                pass

        base = _get_scalar(plug)
        src = _get_incoming_source_plug(plug)

        # Disconnect so user can edit.
        if src:
            _disconnect(src, plug)

        entries.append(
            {
                "plug": plug,
                "base": base,
                "src": src,
                "locked": locked,
            }
        )

    # Set driver to the edit value as requested.
    try:
        _set_driver_value(driver_plug, float(driver_target_value))
    except Exception:
        _warn(_t("warn_failed_set_driver_edit").format(plug=driver_plug))

    session = {
        "driver": driver_plug,
        "driver_target": float(driver_target_value),
        "driven_nodes": list(driven_nodes),
        "channels": list(channels),
        "entries": entries,
    }
    _session_save(session)

    print("// Facial Driver Recorder: ENTER EDIT")
    print("// Driver: {}  target={}".format(driver_plug, driver_target_value))
    print("// Driven plugs: {} (disconnected for posing)".format(len(entries)))


@_undoable("FDR Enter Edit Timeline")
def enter_edit_timeline(
    driver_plug,
    driver_target_value,
    frame_range,
    driven_nodes,
    channels,
    cleanup_extra_nodes = None,
):
    """ADV-like workflow: drive driver_plug from the timeline (0..N) and let the user key poses.

    Timeline mapping: frame 0 -> driver 0, frame N -> driver_target_value.
    On Commit we sample keyed frames and write a multi-key additive SDK curve.
    """

    if not _attr_exists(driver_plug):
        _warn(_t("warn_driver_missing").format(plug=driver_plug))
        return

    frame_range = max(int(frame_range), 1)

    driven_plugs = []
    for n in driven_nodes:
        if not cmds.objExists(n):
            continue
        for ch in channels:
            plug = "{}.{}".format(n, ch)
            if _attr_exists(plug):
                driven_plugs.append(plug)

    if not driven_plugs:
        _warn(_t("warn_no_driven_plugs"))
        return

    cleanup_nodes = list(dict.fromkeys([str(p).split(".", 1)[0] for p in driven_plugs if p and "." in str(p)]))
    for n in (cleanup_extra_nodes or []):
        n_str = str(n or "")
        if (not n_str) or (n_str in cleanup_nodes) or (not cmds.objExists(n_str)):
            continue
        cleanup_nodes.append(n_str)
    pre_animcurves = {n: sorted(list(_collect_animcurves_on_node(n))) for n in cleanup_nodes}

    if _session_load():
        _warn(_t("warn_session_active"))
        return

    pb_state = _playback_state_capture()
    try:
        cmds.autoKeyframe(state=True)
    except Exception:
        pass

    driver_src = None
    driver_locked = False
    md = None
    driver_time_mode = "md"
    driver_time_job = None

    if _driver_uses_adv_q_flow(driver_plug):
        driver_time_mode = "scriptJob"
        try:
            _set_driver_value(driver_plug, 0.0)
        except Exception:
            _playback_state_restore(pb_state)
            _warn(_t("warn_failed_set_driver0").format(plug=driver_plug))
            return
        driver_time_job = _create_driver_time_script_job(driver_plug, float(driver_target_value), int(frame_range))
        if not driver_time_job:
            _playback_state_restore(pb_state)
            _warn(_t("warn_failed_set_driver_edit").format(plug=driver_plug))
            return
    else:
        # Disconnect existing driver input and connect time-driven mapping.
        try:
            driver_locked = bool(cmds.getAttr(driver_plug, lock=True))
        except Exception:
            driver_locked = False
        if driver_locked:
            try:
                cmds.setAttr(driver_plug, lock=False)
            except Exception:
                pass

        driver_src = _get_incoming_source_plug(driver_plug)
        if driver_src:
            _disconnect(driver_src, driver_plug)

        scale = float(driver_target_value) / float(frame_range)
        md = cmds.createNode("multiplyDivide", n="fdrDriverTimeScale#")
        try:
            cmds.setAttr(md + ".operation", 1)  # multiply
        except Exception:
            pass
        try:
            cmds.connectAttr("time1.outTime", md + ".input1X", f=True)
        except Exception:
            pass
        try:
            cmds.setAttr(md + ".input2X", float(scale))
        except Exception:
            pass

        try:
            cmds.connectAttr(md + ".outputX", driver_plug, f=True)
        except Exception:
            _safe_delete(md)
            if driver_src:
                _connect(driver_src, driver_plug)
            if driver_locked:
                try:
                    cmds.setAttr(driver_plug, lock=True)
                except Exception:
                    pass
            _playback_state_restore(pb_state)
            _warn(_t("warn_failed_set_driver_edit").format(plug=driver_plug))
            return

    # Timeline range 0..N.
    try:
        cmds.playbackOptions(e=True, min=0.0, ast=0.0, aet=float(frame_range), max=float(frame_range))
    except Exception:
        pass
    slider = _get_playback_slider()
    if slider:
        try:
            cmds.timeControl(slider, e=True, snap=False)
        except Exception:
            pass

    # Base capture at time 0 (driver==0).
    try:
        cmds.currentTime(0.0, e=True)
    except Exception:
        pass
    if driver_time_mode == "scriptJob":
        try:
            _set_driver_value(driver_plug, 0.0)
        except Exception:
            pass

    entries = []
    for plug in driven_plugs:
        try:
            locked = bool(cmds.getAttr(plug, lock=True))
        except Exception:
            locked = False
        if locked:
            try:
                cmds.setAttr(plug, lock=False)
            except Exception:
                pass

        base = _get_scalar(plug)
        src = _get_incoming_source_plug(plug)
        if src:
            _disconnect(src, plug)
        try:
            _set_scalar(plug, float(base))
        except Exception:
            pass

        entries.append({"plug": plug, "base": base, "src": src, "locked": locked})

    session = {
        "mode": "timeline",
        "driver": driver_plug,
        "driver_target": float(driver_target_value),
        "frame_range": int(frame_range),
        "driver_time_mode": str(driver_time_mode),
        "driver_time_job": driver_time_job,
        "driver_src": driver_src,
        "driver_locked": bool(driver_locked),
        "driver_time_md": md,
        "playback": pb_state,
        "driven_nodes": list(driven_nodes),
        "channels": list(channels),
        "entries": entries,
        "cleanup_nodes": cleanup_nodes,
        "pre_animcurves": pre_animcurves,
    }
    _session_save(session)

    print("// Facial Driver Recorder: ENTER EDIT (TIMELINE)")
    print("// Driver: {}  target@frame{}={}".format(driver_plug, frame_range, driver_target_value))
    print("// Timeline: 0..{} (driver driven by time)".format(frame_range))
    print("// Driven plugs: {} (disconnected; key poses on timeline)".format(len(entries)))


@_undoable("FDR Enter Edit Timeline Bake")
def enter_edit_timeline_bake_to_parent(
    driver_plug,
    driver_target_value,
    frame_range,
    controller_nodes,
    parent_levels,
    channels,
):
    """Timeline edit, but pose controllers and write keys to their parent groups.

    This is the "ADV-like" experience the user expects on offset-group rigs:
    - user selects controller transforms
    - tool maps each controller -> N-level parent group
    - user keys controller channels on frames 0..N
    - Commit samples controller deltas and writes multi-key additive SDK layers on parent channels

    Notes:
    - This assumes controller local channel offsets are equivalent to the parent channel offsets
      (typical for zeroed controls under an offset/SDK group). For more complex hierarchies,
      the single-pose matrix bake mode may be more accurate.
    """

    if not _attr_exists(driver_plug):
        _warn(_t("warn_driver_missing").format(plug=driver_plug))
        return

    frame_range = max(int(frame_range), 1)
    parent_levels = max(int(parent_levels), 1)

    controller_nodes = [n for n in (controller_nodes or []) if cmds.objExists(n)]
    if not controller_nodes:
        _warn(_t("warn_select_driven"))
        return

    cleanup_nodes = list(dict.fromkeys([str(n) for n in controller_nodes if n and cmds.objExists(n)]))
    pre_animcurves = {n: sorted(list(_collect_animcurves_on_node(n))) for n in cleanup_nodes}

    if not channels:
        _warn(_t("warn_no_driven_plugs"))
        return

    if _session_load():
        _warn(_t("warn_session_active"))
        return

    mapping = _parent_map(controller_nodes, parent_levels)
    if not mapping:
        _warn(_t("warn_select_driven"))
        return

    pb_state = _playback_state_capture()
    try:
        cmds.autoKeyframe(state=True)
    except Exception:
        pass

    driver_src = None
    driver_locked = False
    md = None
    driver_time_mode = "md"
    driver_time_job = None

    if _driver_uses_adv_q_flow(driver_plug):
        driver_time_mode = "scriptJob"
        try:
            _set_driver_value(driver_plug, 0.0)
        except Exception:
            _playback_state_restore(pb_state)
            _warn(_t("warn_failed_set_driver0").format(plug=driver_plug))
            return
        driver_time_job = _create_driver_time_script_job(driver_plug, float(driver_target_value), int(frame_range))
        if not driver_time_job:
            _playback_state_restore(pb_state)
            _warn(_t("warn_failed_set_driver_edit").format(plug=driver_plug))
            return
    else:
        # Disconnect existing driver input and connect time-driven mapping.
        try:
            driver_locked = bool(cmds.getAttr(driver_plug, lock=True))
        except Exception:
            driver_locked = False
        if driver_locked:
            try:
                cmds.setAttr(driver_plug, lock=False)
            except Exception:
                pass

        driver_src = _get_incoming_source_plug(driver_plug)
        if driver_src:
            _disconnect(driver_src, driver_plug)

        scale = float(driver_target_value) / float(frame_range)
        md = cmds.createNode("multiplyDivide", n="fdrDriverTimeScale#")
        try:
            cmds.setAttr(md + ".operation", 1)  # multiply
        except Exception:
            pass
        try:
            cmds.connectAttr("time1.outTime", md + ".input1X", f=True)
        except Exception:
            pass
        try:
            cmds.setAttr(md + ".input2X", float(scale))
        except Exception:
            pass

        try:
            cmds.connectAttr(md + ".outputX", driver_plug, f=True)
        except Exception:
            _safe_delete(md)
            if driver_src:
                _connect(driver_src, driver_plug)
            if driver_locked:
                try:
                    cmds.setAttr(driver_plug, lock=True)
                except Exception:
                    pass
            _playback_state_restore(pb_state)
            _warn(_t("warn_failed_set_driver_edit").format(plug=driver_plug))
            return

    # Timeline range 0..N.
    try:
        cmds.playbackOptions(e=True, min=0.0, ast=0.0, aet=float(frame_range), max=float(frame_range))
    except Exception:
        pass
    slider = _get_playback_slider()
    if slider:
        try:
            cmds.timeControl(slider, e=True, snap=False)
        except Exception:
            pass

    # Base capture at time 0 (driver==0).
    try:
        cmds.currentTime(0.0, e=True)
    except Exception:
        pass
    if driver_time_mode == "scriptJob":
        try:
            _set_driver_value(driver_plug, 0.0)
        except Exception:
            pass

    ctrl_entries = []
    pairs = []
    for ctrl, parent in mapping.items():
        if (not ctrl) or (not parent):
            continue
        if (not cmds.objExists(ctrl)) or (not cmds.objExists(parent)):
            continue
        for ch in channels:
            edit_plug = "{}.{}".format(ctrl, ch)
            driven_plug = "{}.{}".format(parent, ch)
            if not _attr_exists(edit_plug):
                continue
            if not _attr_exists(driven_plug):
                # Parent does not have this channel; skip mapping for that channel.
                continue

            try:
                locked = bool(cmds.getAttr(edit_plug, lock=True))
            except Exception:
                locked = False
            if locked:
                try:
                    cmds.setAttr(edit_plug, lock=False)
                except Exception:
                    pass

            base = 0.0
            try:
                base = float(_get_scalar(edit_plug))
            except Exception:
                base = 0.0

            src = _get_incoming_source_plug(edit_plug)
            if src:
                _disconnect(src, edit_plug)
            try:
                _set_scalar(edit_plug, float(base))
            except Exception:
                pass

            ctrl_entries.append({"plug": edit_plug, "src": src, "locked": locked, "base": float(base)})
            pairs.append({"edit_plug": edit_plug, "driven_plug": driven_plug, "base": float(base)})

    if not pairs:
        # Nothing to edit/write.
        _restore_timeline_driver_mapping(
            {
                "driver_time_mode": str(driver_time_mode),
                "driver_time_job": driver_time_job,
                "driver_time_md": md,
                "driver_src": driver_src,
                "driver_locked": bool(driver_locked),
            },
            str(driver_plug),
        )
        _playback_state_restore(pb_state)
        _warn(_t("warn_no_driven_plugs"))
        return

    session = {
        "mode": "timelineBakeToParent",
        "driver": driver_plug,
        "driver_target": float(driver_target_value),
        "frame_range": int(frame_range),
        "driver_time_mode": str(driver_time_mode),
        "driver_time_job": driver_time_job,
        "driver_src": driver_src,
        "driver_locked": bool(driver_locked),
        "driver_time_md": md,
        "playback": pb_state,
        "parent_levels": int(parent_levels),
        "channels": list(channels),
        "mapping": [{"ctrl": c, "parent": p} for c, p in mapping.items()],
        "ctrl_entries": ctrl_entries,
        "pairs": pairs,
        "cleanup_nodes": cleanup_nodes,
        "pre_animcurves": pre_animcurves,
    }
    _session_save(session)

    print("// Facial Driver Recorder: ENTER EDIT (TIMELINE BAKE)")
    print("// Driver: {}  target@frame{}={}".format(driver_plug, frame_range, driver_target_value))
    print("// Timeline: 0..{} (driver driven by time)".format(frame_range))
    print("// Controllers: {}  Pairs: {} (key controllers; commit writes to parents)".format(len(controller_nodes), len(pairs)))


@_undoable("FDR Enter Edit Bake")
def enter_edit_bake_to_parent(
    driver_plug,
    driver_target_value,
    controller_nodes,
    parent_levels,
    channels,
):
    """Let the user pose controllers, but later write additive deltas onto parent/offset groups.

    This solves the common rig layout where controls are children of *_qudong_G (moving the child
    does not change the parent channels). We compute the required parent delta from the final
    controller world pose and the controller's base relative transform.
    """

    if om2 is None:
        _warn(_t("warn_bake_requires_api"))
        return

    if not _attr_exists(driver_plug):
        _warn(_t("warn_driver_missing").format(plug=driver_plug))
        return

    controller_nodes = [n for n in controller_nodes if cmds.objExists(n)]
    if not controller_nodes:
        _warn(_t("warn_select_driven"))
        return

    if not channels:
        _warn(_t("warn_no_driven_plugs"))
        return

    # If a previous session exists, refuse to overwrite (safer).
    if _session_load():
        _warn(_t("warn_session_active"))
        return

    parent_levels = max(int(parent_levels), 1)
    mapping = _parent_map(controller_nodes, parent_levels)
    if not mapping:
        _warn(_t("warn_select_driven"))
        return

    # Set driver to the edit value so user sees the pose they are editing.
    try:
        _set_driver_value(driver_plug, float(driver_target_value))
    except Exception:
        _warn(_t("warn_failed_set_driver_edit").format(plug=driver_plug))

    # Record controller base TR (so we can reset after baking), and disconnect selected channels for editing.
    ctrl_entries = []
    ctrl_base = {}
    for ctrl in controller_nodes:
        base_vals = {}
        for ch in ("translateX", "translateY", "translateZ", "rotateX", "rotateY", "rotateZ"):
            plug = "{}.{}".format(ctrl, ch)
            if _attr_exists(plug):
                try:
                    base_vals[ch] = _get_scalar(plug)
                except Exception:
                    pass
        ctrl_base[ctrl] = base_vals

        # Disconnect only the channels the user asked to edit/record.
        for ch in channels:
            plug = "{}.{}".format(ctrl, ch)
            if not _attr_exists(plug):
                continue

            try:
                locked = bool(cmds.getAttr(plug, lock=True))
            except Exception:
                locked = False
            if locked:
                try:
                    cmds.setAttr(plug, lock=False)
                except Exception:
                    pass

            src = _get_incoming_source_plug(plug)
            if src:
                _disconnect(src, plug)

            ctrl_entries.append({"plug": plug, "src": src, "locked": locked})

    session = {
        "mode": "bakeToParent",
        "driver": driver_plug,
        "driver_target": float(driver_target_value),
        "parent_levels": int(parent_levels),
        "channels": list(channels),
        "mapping": [{"ctrl": c, "parent": p} for c, p in mapping.items()],
        "ctrl_entries": ctrl_entries,
        "ctrl_base": ctrl_base,
    }
    _session_save(session)

    _warn(_t("warn_bake_mode_hint"))
    print("// Facial Driver Recorder: ENTER EDIT (BAKE)")
    print("// Driver: {}  target={}".format(driver_plug, driver_target_value))
    print("// Controllers: {}  mappedParents: {}".format(len(controller_nodes), len(mapping)))


@_undoable("FDR Commit")
def commit(write_mode= "add", apply_threshold= 1e-8):
    """Write additive SDK curves into blendWeighted inputs and restore rig connections."""

    session = _session_load()
    if not session:
        _warn(_t("warn_no_active_session"))
        return

    if session.get("mode") == "bakeToParent":
        _commit_bake_to_parent(session, write_mode=write_mode, apply_threshold=apply_threshold)
        return

    # Edit many existing SDK layers for the same driver, but pose controllers and write to parents.
    if session.get("mode") == "editDriverBakeToParent":
        _commit_edit_driver_bake_to_parent(session, write_mode=write_mode, apply_threshold=apply_threshold)
        return

    # Edit an existing selected SDK layer (from the SDK list).
    if session.get("mode") == "editLayer":
        _commit_edit_layer(session, apply_threshold=apply_threshold)
        return

    # Edit many existing SDK layers for the same driver (from the SDK list).
    if session.get("mode") == "editDriver":
        _commit_edit_driver(session, apply_threshold=apply_threshold)
        return

    if session.get("mode") == "timeline":
        _commit_timeline(session, write_mode=write_mode, apply_threshold=apply_threshold)
        return

    if session.get("mode") == "timelineBakeToParent":
        _commit_timeline_bake_to_parent(session, write_mode=write_mode, apply_threshold=apply_threshold)
        return

    driver_plug = session.get("driver")
    driver_target = float(session.get("driver_target", 1.0))
    entries = session.get("entries", [])

    if not driver_plug or not _attr_exists(driver_plug):
        _warn(_t("warn_session_driver_invalid"))
        return

    # Safety: if user insists on add-mode, warn when existing layers already exist for this driver.
    if (write_mode or "").lower() == "add":
        driven_plugs = [str(e.get("plug") or "") for e in (entries or [])]
        if not _confirm_add_over_existing(driver_plug, driven_plugs):
            cancel()
            return

    # Read the posed target values while still disconnected.
    for e in entries:
        plug = e["plug"]
        try:
            e["target"] = _get_scalar(plug)
        except Exception:
            e["target"] = None

    # Restore connections and lock states.
    for e in entries:
        plug = e["plug"]
        src = e.get("src")
        if src:
            _connect(src, plug)

        if e.get("locked"):
            try:
                cmds.setAttr(plug, lock=True)
            except Exception:
                pass

    # Ensure driver returns to 0 (as you requested).
    try:
        _set_driver_value(driver_plug, 0.0)
    except Exception:
        pass

    created = 0
    updated = 0
    skipped = 0

    # Create additive SDK curves into blendWeighted.
    for e in entries:
        plug = e["plug"]
        base = e.get("base")
        target = e.get("target")
        src = e.get("src")

        if target is None or base is None:
            skipped += 1
            continue

        delta = _delta_for_plug(str(plug), float(base), float(target))
        if abs(delta) <= apply_threshold:
            skipped += 1
            continue

        # Find or create the blendWeighted that drives this plug.
        bt = _find_blendweighted_for_driven(plug, recorded_src_plug=src)
        if not bt:
            bt = _ensure_network_for_driven(plug)

        delta_bw = _to_blendweighted_delta(str(plug), float(delta), bt)

        try:
            result, _used_idx = _write_additive_layer(
                driver_plug=driver_plug,
                driver_target=driver_target,
                driven_plug=plug,
                bt=bt,
                delta_bw=float(delta_bw),
                write_mode=write_mode,
            )
            if result == "updated":
                updated += 1
            else:
                created += 1
                if (write_mode or "").lower() == "update":
                    _warn(_t("warn_update_fallback").format(plug=plug))
        except Exception as ex:
            _warn(_t("warn_failed_create_sdk").format(plug=plug, err=ex))
            skipped += 1

    # Restore driver to 0 again for safety.
    try:
        _set_driver_value(driver_plug, 0.0)
    except Exception:
        pass

    _session_clear()

    print("// Facial Driver Recorder: COMMIT")
    print("// Created additive SDKs: {}".format(created))
    print("// Updated existing SDKs: {}".format(updated))
    print("// Skipped (no change / failed): {}".format(skipped))


def _commit_bake_to_parent(session, write_mode= "add", apply_threshold= 1e-8):
    driver_plug = session.get("driver")
    driver_target = float(session.get("driver_target", 1.0))
    channels = session.get("channels") or []
    mapping = session.get("mapping") or []
    ctrl_entries = session.get("ctrl_entries") or []
    ctrl_base = session.get("ctrl_base") or {}

    if om2 is None:
        _warn(_t("warn_bake_requires_api"))
        return

    if not driver_plug or not _attr_exists(driver_plug):
        _warn(_t("warn_session_driver_invalid"))
        return

    # Evaluate at driver target.
    try:
        _set_driver_value(driver_plug, float(driver_target))
    except Exception:
        _warn(_t("warn_failed_set_driver_edit").format(plug=driver_plug))

    created = 0
    updated = 0
    skipped = 0

    for pair in mapping:
        ctrl = pair.get("ctrl")
        parent = pair.get("parent")
        if not ctrl or not parent or (not cmds.objExists(ctrl)) or (not cmds.objExists(parent)):
            skipped += 1
            continue

        # Desired controller world pose (user-edited).
        try:
            c_world_desired = cmds.xform(ctrl, q=True, ws=True, m=True)
        except Exception:
            skipped += 1
            continue

        # Reset controller to base values (captured at Enter Edit) so we can compute the relative transform.
        base_vals = ctrl_base.get(ctrl, {})
        for ch, v in base_vals.items():
            plug = "{}.{}".format(ctrl, ch)
            if _attr_exists(plug):
                try:
                    _set_scalar(plug, float(v))
                except Exception:
                    pass

        # Compute controller relative matrix to the target parent (works even if parent is an ancestor).
        try:
            p_world_current = cmds.xform(parent, q=True, ws=True, m=True)
            c_world_base = cmds.xform(ctrl, q=True, ws=True, m=True)
        except Exception:
            skipped += 1
            continue

        try:
            m_p = _m_from_list16([float(x) for x in p_world_current])
            m_c_base = _m_from_list16([float(x) for x in c_world_base])
            m_c_desired = _m_from_list16([float(x) for x in c_world_desired])
        except Exception:
            skipped += 1
            continue

        # c_rel = inv(P) * C
        m_c_rel = m_p.inverse() * m_c_base
        # P_desired = C_desired * inv(c_rel)
        m_p_world_desired = m_c_desired * m_c_rel.inverse()

        # Let Maya decompose the desired parent world matrix into local TRS.
        # This is more robust than manual Euler decomposition under mirrored/negative-scale rigs.
        p_parent = (cmds.listRelatives(parent, p=True, f=False) or [None])[0]
        try:
            ro = int(cmds.getAttr(parent + ".rotateOrder"))
        except Exception:
            ro = 0

        tmp = None
        try:
            tmp = cmds.createNode("transform", n="__fdrTmpBake__#", p=(p_parent if p_parent and cmds.objExists(p_parent) else None))
            try:
                cmds.setAttr(tmp + ".rotateOrder", ro)
            except Exception:
                pass
            cmds.xform(tmp, ws=True, m=[float(x) for x in _list16_from_m(m_p_world_desired)])
            desired_by_channel = {
                "translateX": float(cmds.getAttr(tmp + ".translateX")),
                "translateY": float(cmds.getAttr(tmp + ".translateY")),
                "translateZ": float(cmds.getAttr(tmp + ".translateZ")),
                "rotateX": float(cmds.getAttr(tmp + ".rotateX")),
                "rotateY": float(cmds.getAttr(tmp + ".rotateY")),
                "rotateZ": float(cmds.getAttr(tmp + ".rotateZ")),
                "scaleX": float(cmds.getAttr(tmp + ".scaleX")),
                "scaleY": float(cmds.getAttr(tmp + ".scaleY")),
                "scaleZ": float(cmds.getAttr(tmp + ".scaleZ")),
            }
        except Exception:
            skipped += 1
            continue
        finally:
            if tmp and cmds.objExists(tmp):
                try:
                    cmds.delete(tmp)
                except Exception:
                    pass

        # Write additive deltas onto the parent channels.
        for ch in channels:
            driven_plug = "{}.{}".format(parent, ch)
            if not _attr_exists(driven_plug):
                continue

            desired_val = desired_by_channel.get(ch)
            if desired_val is None:
                continue

            try:
                current_val = _get_scalar(driven_plug)
            except Exception:
                skipped += 1
                continue

            delta = _delta_for_plug(str(driven_plug), float(current_val), float(desired_val))
            if abs(delta) <= apply_threshold:
                skipped += 1
                continue

            bt = _find_blendweighted_for_driven(driven_plug)
            if not bt:
                bt = _ensure_network_for_driven(driven_plug)

            delta_bw = _to_blendweighted_delta(str(driven_plug), float(delta), bt)

            try:
                result, _used_idx = _write_additive_layer(
                    driver_plug=driver_plug,
                    driver_target=driver_target,
                    driven_plug=driven_plug,
                    bt=bt,
                    delta_bw=float(delta_bw),
                    write_mode=write_mode,
                )
                if result == "updated":
                    updated += 1
                else:
                    created += 1
                    if (write_mode or "").lower() == "update":
                        _warn(_t("warn_update_fallback").format(plug=driven_plug))
            except Exception as ex:
                _warn(_t("warn_failed_create_sdk").format(plug=driven_plug, err=ex))
                skipped += 1

    # Restore controller connections/locks (we keep their values at base).
    for e in ctrl_entries:
        plug = e.get("plug")
        if not plug:
            continue
        src = e.get("src")
        if src:
            _connect(src, plug)
        if e.get("locked"):
            try:
                cmds.setAttr(plug, lock=True)
            except Exception:
                pass

    # Driver back to 0 for safety.
    try:
        _set_driver_value(driver_plug, 0.0)
    except Exception:
        pass

    _session_clear()

    print("// Facial Driver Recorder: COMMIT (BAKE)")
    print("// Created additive SDKs: {}".format(created))
    print("// Updated existing SDKs: {}".format(updated))
    print("// Skipped (no change / failed): {}".format(skipped))


@_undoable("FDR Cancel")
def cancel():
    """Restore original connections and driver=0 without writing keys."""

    session = _session_load()
    if not session:
        _warn(_t("warn_no_session_cancel"))
        return

    if session.get("mode") == "bakeToParent":
        _cancel_bake_to_parent(session)
        return

    if session.get("mode") == "editDriverBakeToParent":
        _cancel_bake_to_parent(session)
        return

    if session.get("mode") == "timeline":
        _cancel_timeline(session)
        return

    if session.get("mode") == "timelineBakeToParent":
        _cancel_timeline_bake_to_parent(session)
        return

    driver_plug = session.get("driver")
    entries = session.get("entries", [])

    # Restore driver=0 first.
    if driver_plug and _attr_exists(driver_plug):
        try:
            _set_driver_value(driver_plug, 0.0)
        except Exception:
            pass

    # Put driven channels back to base pose and reconnect.
    for e in entries:
        plug = e["plug"]
        base = e.get("base")
        src = e.get("src")

        try:
            if base is not None:
                _set_scalar(plug, float(base))
        except Exception:
            pass

        if src:
            _connect(src, plug)

        if e.get("locked"):
            try:
                cmds.setAttr(plug, lock=True)
            except Exception:
                pass

    _session_clear()

    print("// Facial Driver Recorder: CANCEL")


def _commit_timeline(session, write_mode= "add", apply_threshold= 1e-8):
    driver_plug = session.get("driver")
    driver_target = float(session.get("driver_target", 1.0))
    frame_range = int(session.get("frame_range") or 1)
    entries = session.get("entries") or []
    prefer_existing_layer = bool(session.get("prefer_existing_layer"))

    if not driver_plug or not _attr_exists(driver_plug):
        _warn(_t("warn_session_driver_invalid"))
        return

    frame_range = max(int(frame_range), 1)

    if (write_mode or "").lower() == "add":
        driven_plugs = [str(e.get("plug") or "") for e in entries]
        if not _confirm_add_over_existing(driver_plug, driven_plugs):
            _cancel_timeline(session)
            return

    # Union of all keyed frames on driven plugs.
    times_set = set()
    for e in entries:
        plug = str(e.get("plug") or "")
        if not plug:
            continue
        try:
            ts = cmds.keyframe(plug, q=True, tc=True) or []
            for t in ts:
                times_set.add(float(t))
        except Exception:
            continue

    times_set.add(0.0)
    times_set.add(float(frame_range))
    times = sorted([t for t in times_set if (t >= -1e-6) and (t <= float(frame_range) + 1e-6)])

    # Sample deltas (posedValue - baseValue) at each keyed frame.
    try:
        pre_time = float(cmds.currentTime(q=True))
    except Exception:
        pre_time = 0.0

    sampled = {}
    for e in entries:
        plug = str(e.get("plug") or "")
        if plug and (e.get("base") is not None):
            sampled[plug] = []

    for t in times:
        try:
            cmds.currentTime(float(t), e=True)
        except Exception:
            pass
        driver_value = float(driver_target) * (float(t) / float(frame_range))
        for e in entries:
            plug = str(e.get("plug") or "")
            if plug not in sampled:
                continue
            base = float(e.get("base") or 0.0)
            try:
                v = float(_get_scalar(plug))
            except Exception:
                continue
            sampled[plug].append((float(driver_value), float(_delta_for_plug(str(plug), float(base), float(v)))))

    try:
        cmds.currentTime(pre_time, e=True)
    except Exception:
        pass

    # Clean up user animation curves on driven plugs (created while disconnected).
    for e in entries:
        plug = str(e.get("plug") or "")
        if plug:
            _delete_driving_animcurves(plug)

    # Restore driven connections and locks.
    for e in entries:
        plug = str(e.get("plug") or "")
        if not plug:
            continue
        src = e.get("src")
        if src:
            _connect(src, plug)
        if e.get("locked"):
            try:
                cmds.setAttr(plug, lock=True)
            except Exception:
                pass

    created = 0
    updated = 0
    skipped = 0

    # Write per-plug multi-key additive layers.
    for plug, pairs in sampled.items():
        # Skip if all deltas are small.
        max_abs = 0.0
        for _x, y in pairs:
            max_abs = max(max_abs, abs(float(y)))
        if max_abs <= float(apply_threshold):
            skipped += 1
            continue

        # Lookup recorded src for network resolution.
        recorded_src = None
        for e in entries:
            if str(e.get("plug") or "") == plug:
                recorded_src = e.get("src")
                break

        bt = _find_blendweighted_for_driven(plug, recorded_src_plug=recorded_src)
        if not bt:
            bt = _ensure_network_for_driven(plug)

        keys_bw = []
        for x, y in pairs:
            delta_bw = _to_blendweighted_delta(str(plug), float(y), bt)
            keys_bw.append((float(x), float(delta_bw)))

        try:
            result, _used_idx = _write_additive_layer(
                driver_plug=driver_plug,
                driver_target=driver_target,
                driven_plug=plug,
                bt=bt,
                delta_bw=float(keys_bw[-1][1] if keys_bw else 0.0),
                write_mode=write_mode,
                keys=keys_bw,
                prefer_any_existing=prefer_existing_layer,
            )
            if result == "updated":
                updated += 1
            else:
                created += 1
                if (write_mode or "").lower() == "update":
                    _warn(_t("warn_update_fallback").format(plug=plug))
        except Exception as ex:
            _warn(_t("warn_failed_create_sdk").format(plug=plug, err=ex))
            skipped += 1

    # Restore driver mapping and playback state.
    _cleanup_new_animcurves_from_session(session)
    _restore_timeline_driver_mapping(session, str(driver_plug))
    _playback_state_restore(session.get("playback") or {})
    _session_clear()

    print("// Facial Driver Recorder: COMMIT (TIMELINE)")
    print("// Created additive SDKs: {}".format(created))
    print("// Updated existing SDKs: {}".format(updated))
    print("// Skipped (no change / failed): {}".format(skipped))


def _commit_timeline_bake_to_parent(session, write_mode= "add", apply_threshold= 1e-8):
    driver_plug = session.get("driver")
    driver_target = float(session.get("driver_target", 1.0))
    frame_range = int(session.get("frame_range") or 1)
    pairs = session.get("pairs") or []
    ctrl_entries = session.get("ctrl_entries") or []
    prefer_existing_layer = bool(session.get("prefer_existing_layer"))

    if not driver_plug or not _attr_exists(driver_plug):
        _warn(_t("warn_session_driver_invalid"))
        return

    frame_range = max(int(frame_range), 1)

    driven_plugs = [str(p.get("driven_plug") or "") for p in pairs]
    driven_plugs = [p for p in driven_plugs if p]
    if not driven_plugs:
        _warn(_t("warn_no_driven_plugs"))
        _cancel_timeline_bake_to_parent(session)
        return

    if (write_mode or "").lower() == "add":
        if not _confirm_add_over_existing(driver_plug, driven_plugs):
            _cancel_timeline_bake_to_parent(session)
            return

    # Union of all keyed frames on controller (edit) plugs.
    times_set = set()
    for p in pairs:
        edit_plug = str(p.get("edit_plug") or "")
        if not edit_plug:
            continue
        try:
            ts = cmds.keyframe(edit_plug, q=True, tc=True) or []
            for t in ts:
                times_set.add(float(t))
        except Exception:
            continue

    times_set.add(0.0)
    times_set.add(float(frame_range))
    times = sorted([t for t in times_set if (t >= -1e-6) and (t <= float(frame_range) + 1e-6)])

    try:
        pre_time = float(cmds.currentTime(q=True))
    except Exception:
        pre_time = 0.0

    # drivenPlug -> list[(driverValue, delta)]
    sampled = {}
    for p in pairs:
        dp = str(p.get("driven_plug") or "")
        if dp and dp not in sampled:
            sampled[dp] = []

    # Sample controller offsets; write them to parent channels.
    for t in times:
        try:
            cmds.currentTime(float(t), e=True)
        except Exception:
            pass
        driver_value = float(driver_target) * (float(t) / float(frame_range))

        # Aggregate deltas per driven plug. If multiple controllers map to the same driven plug,
        # we sum them (rare, but prevents silent overwrite).
        accum = {dp: 0.0 for dp in sampled.keys()}
        for p in pairs:
            edit_plug = str(p.get("edit_plug") or "")
            driven_plug = str(p.get("driven_plug") or "")
            if (not edit_plug) or (not driven_plug) or (driven_plug not in sampled):
                continue
            base = float(p.get("base") or 0.0)
            try:
                v = float(_get_scalar(edit_plug))
            except Exception:
                continue
            accum[driven_plug] = float(accum.get(driven_plug, 0.0)) + float(_delta_for_plug(str(edit_plug), float(base), float(v)))

        for dp, dy in accum.items():
            sampled[dp].append((float(driver_value), float(dy)))

    try:
        cmds.currentTime(pre_time, e=True)
    except Exception:
        pass

    # Clean up user animation curves on controller plugs.
    for e in ctrl_entries:
        plug = str(e.get("plug") or "")
        if plug:
            _delete_driving_animcurves(plug)

    # Restore controller plugs to base, then reconnect and relock.
    for e in ctrl_entries:
        plug = str(e.get("plug") or "")
        if not plug:
            continue
        base = e.get("base")
        try:
            if base is not None:
                _set_scalar(plug, float(base))
        except Exception:
            pass
        src = e.get("src")
        if src:
            _connect(str(src), plug)
        if e.get("locked"):
            try:
                cmds.setAttr(plug, lock=True)
            except Exception:
                pass

    created = 0
    updated = 0
    skipped = 0

    # Write additive multi-key layers to parent driven plugs.
    for plug, pairs_xy in sampled.items():
        max_abs = 0.0
        for _x, y in pairs_xy:
            max_abs = max(max_abs, abs(float(y)))
        if max_abs <= float(apply_threshold):
            skipped += 1
            continue

        bt = _find_blendweighted_for_driven(plug)
        if not bt:
            bt = _ensure_network_for_driven(plug)

        keys_bw = []
        for x, y in pairs_xy:
            delta_bw = _to_blendweighted_delta(str(plug), float(y), bt)
            keys_bw.append((float(x), float(delta_bw)))

        try:
            result, _used_idx = _write_additive_layer(
                driver_plug=driver_plug,
                driver_target=driver_target,
                driven_plug=plug,
                bt=bt,
                delta_bw=float(keys_bw[-1][1] if keys_bw else 0.0),
                write_mode=write_mode,
                keys=keys_bw,
                prefer_any_existing=prefer_existing_layer,
            )
            if result == "updated":
                updated += 1
            else:
                created += 1
                if (write_mode or "").lower() == "update":
                    _warn(_t("warn_update_fallback").format(plug=plug))
        except Exception as ex:
            _warn(_t("warn_failed_create_sdk").format(plug=plug, err=ex))
            skipped += 1

    # Restore driver mapping and playback state.
    _cleanup_new_animcurves_from_session(session)
    _restore_timeline_driver_mapping(session, str(driver_plug))
    _playback_state_restore(session.get("playback") or {})
    _session_clear()

    print("// Facial Driver Recorder: COMMIT (TIMELINE BAKE)")
    print("// Created additive SDKs: {}".format(created))
    print("// Updated existing SDKs: {}".format(updated))
    print("// Skipped (no change / failed): {}".format(skipped))


def _cancel_timeline(session):
    driver_plug = session.get("driver")
    entries = session.get("entries") or []

    # Clean up user animation curves on driven plugs.
    for e in entries:
        plug = str(e.get("plug") or "")
        if plug:
            _delete_driving_animcurves(plug)

    # Restore driven channels back to base and reconnect.
    for e in entries:
        plug = str(e.get("plug") or "")
        if not plug:
            continue
        base = e.get("base")
        src = e.get("src")

        try:
            if base is not None:
                _set_scalar(plug, float(base))
        except Exception:
            pass

        if src:
            _connect(src, plug)

        if e.get("locked"):
            try:
                cmds.setAttr(plug, lock=True)
            except Exception:
                pass

    # Restore driver mapping.
    if driver_plug:
        _restore_timeline_driver_mapping(session, str(driver_plug))

    _cleanup_new_animcurves_from_session(session)
    _playback_state_restore(session.get("playback") or {})
    _session_clear()

    print("// Facial Driver Recorder: CANCEL (TIMELINE)")


def _cancel_timeline_bake_to_parent(session):
    driver_plug = session.get("driver")
    ctrl_entries = session.get("ctrl_entries") or []

    # Clean up user animation curves on controller plugs.
    for e in ctrl_entries:
        plug = str(e.get("plug") or "")
        if plug:
            _delete_driving_animcurves(plug)

    # Restore controller plugs back to base and reconnect.
    for e in ctrl_entries:
        plug = str(e.get("plug") or "")
        if not plug:
            continue
        base = e.get("base")
        src = e.get("src")

        try:
            if base is not None:
                _set_scalar(plug, float(base))
        except Exception:
            pass

        if src:
            _connect(str(src), plug)

        if e.get("locked"):
            try:
                cmds.setAttr(plug, lock=True)
            except Exception:
                pass

    # Restore driver mapping.
    if driver_plug:
        _restore_timeline_driver_mapping(session, str(driver_plug))

    _cleanup_new_animcurves_from_session(session)
    _playback_state_restore(session.get("playback") or {})
    _session_clear()

    print("// Facial Driver Recorder: CANCEL (TIMELINE BAKE)")


def _cancel_bake_to_parent(session):
    driver_plug = session.get("driver")
    ctrl_entries = session.get("ctrl_entries") or []
    ctrl_base = session.get("ctrl_base") or {}

    # Restore driver=0.
    if driver_plug and _attr_exists(driver_plug):
        try:
            _set_driver_value(driver_plug, 0.0)
        except Exception:
            pass

    # Restore controller base values.
    for ctrl, base_vals in ctrl_base.items():
        if not cmds.objExists(ctrl):
            continue
        for ch, v in (base_vals or {}).items():
            plug = "{}.{}".format(ctrl, ch)
            if _attr_exists(plug):
                try:
                    _set_scalar(plug, float(v))
                except Exception:
                    pass

    # Reconnect controller channels and relock.
    for e in ctrl_entries:
        plug = e.get("plug")
        if not plug:
            continue
        src = e.get("src")
        if src:
            _connect(src, plug)
        if e.get("locked"):
            try:
                cmds.setAttr(plug, lock=True)
            except Exception:
                pass

    _session_clear()
    print("// Facial Driver Recorder: CANCEL (BAKE)")


# ----------------------------
# UI
# ----------------------------

def _ui_driven_list_items_cmds():
    try:
        if not cmds.textScrollList("fdr_drivenList", exists=True):
            return []
    except Exception:
        return []
    try:
        items = cmds.textScrollList("fdr_drivenList", q=True, ai=True) or []
    except Exception:
        items = []
    return _normalize_transform_nodes(items)


def _ui_driven_list_set_items_cmds(nodes, select_items= None):
    clean = _normalize_transform_nodes(nodes)
    try:
        if not cmds.textScrollList("fdr_drivenList", exists=True):
            _driven_targets_save(clean)
            return
    except Exception:
        _driven_targets_save(clean)
        return

    try:
        cmds.textScrollList("fdr_drivenList", e=True, ra=True)
        for n in clean:
            cmds.textScrollList("fdr_drivenList", e=True, a=n)
        if select_items:
            for n in _normalize_transform_nodes(select_items):
                try:
                    cmds.textScrollList("fdr_drivenList", e=True, si=n)
                except Exception:
                    pass
    except Exception:
        pass
    _driven_targets_save(clean)


def _ui_driven_list_load_cmds():
    _ui_driven_list_set_items_cmds(_driven_targets_load())


def _ui_driven_list_add_selected_cmds(*_):
    sel = _normalize_transform_nodes(cmds.ls(sl=True, type="transform") or [])
    if not sel:
        _warn(_t("warn_select_driven"))
        return
    cur = _ui_driven_list_items_cmds()
    merged = list(cur)
    existing = set(cur)
    for n in sel:
        if n not in existing:
            merged.append(n)
            existing.add(n)
    _ui_driven_list_set_items_cmds(merged, select_items=sel)


def _ui_driven_list_remove_selected_cmds(*_):
    try:
        chosen = cmds.textScrollList("fdr_drivenList", q=True, si=True) or []
    except Exception:
        chosen = []
    chosen_set = set(_normalize_transform_nodes(chosen))
    if not chosen_set:
        return
    cur = _ui_driven_list_items_cmds()
    keep = [n for n in cur if n not in chosen_set]
    _ui_driven_list_set_items_cmds(keep)


def _ui_driven_list_clear_cmds(*_):
    _ui_driven_list_set_items_cmds([])


def _ui_driven_list_select_scene_cmds(*_):
    cur = _ui_driven_list_items_cmds()
    if not cur:
        _warn(_t("warn_driven_list_empty"))
        return
    try:
        chosen = cmds.textScrollList("fdr_drivenList", q=True, si=True) or []
    except Exception:
        chosen = []
    to_select = _normalize_transform_nodes(chosen) or cur
    if not to_select:
        _warn(_t("warn_driven_list_empty"))
        return
    try:
        cmds.select(to_select, r=True)
    except Exception:
        pass


def _ui_get_driven_nodes_cmds():
    """Prefer stored driven-list nodes; fall back to current scene selection."""
    listed = _ui_driven_list_items_cmds()
    if listed:
        return listed
    return _normalize_transform_nodes(cmds.ls(sl=True, type="transform") or [])


def _ui_get_driver_plug():
    node = cmds.textField("fdr_driverNode", q=True, tx=True).strip()
    attr = cmds.optionMenu("fdr_driverAttr", q=True, v=True)
    if not node:
        return ""
    return "{}.{}".format(node, attr)


def _ui_get_driver_sign_cmds():
    """Return +1/-1 from the cmds sign selector (best-effort)."""
    try:
        if cmds.radioButton("fdr_driverSignMinus", q=True, sl=True):
            return -1.0
    except Exception:
        pass
    return 1.0


def _ui_set_driver_value_with_sign_cmds(value):
    """Write signed value into cmds UI as [sign buttons] + [positive magnitude]."""
    try:
        v = float(value)
    except Exception:
        v = 1.0
    sign = -1.0 if v < 0.0 else 1.0
    mag = abs(float(v))

    try:
        cmds.floatField("fdr_driverValue", e=True, v=mag)
    except Exception:
        pass

    try:
        if sign < 0.0:
            cmds.radioButton("fdr_driverSignMinus", e=True, sl=True)
        else:
            cmds.radioButton("fdr_driverSignPlus", e=True, sl=True)
    except Exception:
        pass


def _ui_get_driver_value():
    try:
        mag = float(cmds.floatField("fdr_driverValue", q=True, v=True))
    except Exception:
        mag = 1.0
    return float(_ui_get_driver_sign_cmds()) * abs(float(mag))


def _restore_selection_safe(nodes):
    """Best-effort restore selection, keeping only existing nodes/components."""
    if not nodes:
        return
    try:
        keep = [str(n) for n in (nodes or []) if n and cmds.objExists(str(n))]
    except Exception:
        keep = []
    if not keep:
        return
    try:
        cmds.select(keep, r=True)
    except Exception:
        pass


def _ui_get_channels():
    mapping = {
        "fdr_tX": "translateX",
        "fdr_tY": "translateY",
        "fdr_tZ": "translateZ",
        "fdr_rX": "rotateX",
        "fdr_rY": "rotateY",
        "fdr_rZ": "rotateZ",
        "fdr_sX": "scaleX",
        "fdr_sY": "scaleY",
        "fdr_sZ": "scaleZ",
    }
    out = []
    for cb, ch in mapping.items():
        try:
            if cmds.checkBox(cb, q=True, v=True):
                out.append(ch)
        except Exception:
            pass
    return out


def _ui_get_write_mode():
    """Return internal write mode: 'add' or 'update'."""
    try:
        v = cmds.optionMenu("fdr_writeMode", q=True, v=True)
    except Exception:
        # Safer default: prefer overwriting the existing tool layer rather than stacking.
        return "update"

    # Normalize from localized labels.
    if v == _t("write_update"):
        return "update"
    return "add"


def _ui_load_driver_from_selection(*_):
    sel = cmds.ls(sl=True, type="transform") or []
    if not sel:
        _warn(_t("warn_select_driver"))
        return
    cmds.textField("fdr_driverNode", e=True, tx=sel[0])
    _ui_refresh_driver_attr_menu(sel[0])


def _ui_select_driver_node(*_):
    node = ""
    try:
        node = cmds.textField("fdr_driverNode", q=True, tx=True).strip()
    except Exception:
        node = ""
    if not node:
        _warn(_t("warn_select_driver"))
        return
    if not cmds.objExists(node):
        _warn(_t("warn_driver_node_not_found").format(node=node))
        return
    try:
        cmds.select(node, r=True)
    except Exception:
        pass


def _ui_enter_edit(*_):
    driver_plug = _ui_get_driver_plug()
    driver_value = _ui_get_driver_value()
    try:
        frame_range = int(cmds.intField("fdr_frameRange", q=True, v=True))
    except Exception:
        frame_range = 10
    frame_range = max(int(frame_range), 1)
    try:
        cmds.optionVar(iv=(_FRAME_RANGE_OPT_VAR, int(frame_range)))
    except Exception:
        pass
    channels = _ui_get_channels()

    selected_nodes = _ui_get_driven_nodes_cmds()
    if not selected_nodes:
        _warn(_t("warn_driven_list_empty"))
        return

    # Avoid accidentally including the driver node in driven selection.
    driver_node = driver_plug.split(".", 1)[0] if driver_plug else ""
    selected_nodes = [n for n in selected_nodes if n != driver_node]
    if not selected_nodes:
        _warn(_t("warn_select_driven"))
        return

    use_parent = bool(cmds.checkBox("fdr_useParent", q=True, v=True))
    parent_levels = int(cmds.intField("fdr_parentLevels", q=True, v=True))

    bake_to_parent = bool(cmds.checkBox("fdr_bakeToParent", q=True, v=True))
    if bake_to_parent and not use_parent:
        _warn(_t("warn_bake_needs_parent"))
        return

    auto_bake = _should_auto_bake_to_parent(selected_nodes, use_parent=use_parent, bake_to_parent=bake_to_parent)
    if auto_bake:
        bake_to_parent = True
        _warn(_t("warn_auto_bake_parent_mode"))
        try:
            cmds.checkBox("fdr_bakeToParent", e=True, v=True)
        except Exception:
            pass

    # Bake-to-parent timeline: edit controllers, commit writes to parents.
    if bake_to_parent and use_parent:
        enter_edit_timeline_bake_to_parent(
            driver_plug,
            driver_value,
            frame_range,
            selected_nodes,
            parent_levels,
            channels,
        )
        _restore_selection_safe(selected_nodes)
        return

    driven_nodes = list(selected_nodes)
    if use_parent:
        driven_nodes = _parent_levels(driven_nodes, parent_levels)
        if not driven_nodes:
            _warn(_t("warn_select_driven"))
            return
    else:
        # Warn if user selected controller transforms directly.
        for n in driven_nodes:
            if _is_controller_transform(n):
                _warn(_t("warn_controller_selected").format(node=n))
                break

    # Timeline edit is the ADV-like workflow: pose/key within 0..N, then Commit writes multi-key SDK.
    enter_edit_timeline(
        driver_plug,
        driver_value,
        frame_range,
        driven_nodes,
        channels,
        cleanup_extra_nodes=selected_nodes,
    )
    _restore_selection_safe(selected_nodes)


def _ui_commit(*_):
    mode = _ui_get_write_mode()
    try:
        cmds.optionVar(sv=(_WRITE_MODE_OPT_VAR, mode))
    except Exception:
        pass
    commit(write_mode=mode)


def _bw_connected_input_indices(bw, search_extra= 64):
    """Return indices i where blendWeighted.input[i] has an incoming connection."""
    try:
        size = int(cmds.getAttr(bw + ".input", size=True))
    except Exception:
        size = 0

    out = []
    max_i = max(size + int(search_extra), 8)
    for i in range(max_i):
        plug = "{}.input[{}]".format(bw, i)
        try:
            if cmds.listConnections(plug, s=True, d=False, p=True, scn=True) or []:
                out.append(i)
        except Exception:
            continue
    return out


def _describe_animcurve(curve):
    """Describe an animCurve layer for scan output."""
    driver = ""
    try:
        srcs = cmds.listConnections(curve + ".input", s=True, d=False, p=True, scn=True) or []
        driver = srcs[0] if srcs else ""
    except Exception:
        driver = ""

    kc = "?"
    try:
        kc = str(int(cmds.keyframe(curve, q=True, kc=True)))
    except Exception:
        pass

    tag = _tag_get(curve) or {}
    is_tool = bool(tag) and (tag.get("tool") == "facial_driver_recorder")
    tool_flag = "tool" if is_tool else "ext"

    if driver:
        return "{} driver={} keys={} tag={}".format(curve, driver, kc, tool_flag)
    return "{} keys={} tag={}".format(curve, kc, tool_flag)


def _animcurve_driver_plug(curve):
    """Return driver plug connected to animCurve.input (or '')."""
    try:
        srcs = cmds.listConnections(curve + ".input", s=True, d=False, p=True, scn=True) or []
        return str(srcs[0]) if srcs else ""
    except Exception:
        return ""


def _animcurve_driver_target(curve):
    """Best-effort: infer the non-zero driver key (float time) for the curve."""
    try:
        floats = cmds.keyframe(curve, q=True, floatChange=True) or []
        floats = [float(x) for x in floats]
    except Exception:
        floats = []

    if not floats:
        return 1.0

    # Common: [0, target]. Target can be negative (e.g. -1), so prefer the
    # non-zero key with the largest absolute magnitude.
    nz = [f for f in floats if abs(float(f)) > 1e-8]
    if nz:
        return float(max(nz, key=lambda x: abs(float(x))))
    # Fallback: all keys are ~0.
    return float(floats[-1])


def scan_sdk_detailed(driven_nodes, channels):
    """Detailed scan: returns (report, items) for UI list."""

    driven_nodes = [n for n in (driven_nodes or []) if cmds.objExists(n)]
    channels = list(channels or [])
    if not driven_nodes or not channels:
        return "", []

    lines = []
    items = []
    lines.append("// Facial Driver Recorder: SCAN SDK")
    lines.append("// Nodes: {}  Channels: {}".format(len(driven_nodes), len(channels)))

    scanned = 0
    has_incoming = 0
    bw_count = 0
    animcurve_direct = 0

    for n in driven_nodes:
        for ch in channels:
            plug = "{}.{}".format(n, ch)
            if not _attr_exists(plug):
                continue

            scanned += 1
            src = _get_incoming_source_plug(plug)
            if not src:
                lines.append("{}: (no incoming)".format(plug))
                continue

            has_incoming += 1

            src_node = src.split(".", 1)[0]
            try:
                src_type = cmds.nodeType(src_node)
            except Exception:
                src_type = ""

            bt = None
            try:
                bt = _find_blendweighted_for_driven(plug, recorded_src_plug=src)
            except Exception:
                bt = None

            if bt and cmds.objExists(bt.bw):
                bw_count += 1
                cf_note = ""
                if bt.kind == "unitConversion":
                    cf_note = " cf={:g}".format(bt.conversion_factor)
                lines.append("{}: blendWeighted {} ({}{})".format(plug, bt.bw, bt.kind, cf_note))

                indices = _bw_connected_input_indices(bt.bw)
                lines.append("  layers: {}".format(len(indices)))
                for i in indices:
                    in_plug = "{}.input[{}]".format(bt.bw, i)
                    srcs = cmds.listConnections(in_plug, s=True, d=False, p=True, scn=True) or []
                    if not srcs:
                        continue

                    layer_src = srcs[0]
                    layer_node = layer_src.split(".", 1)[0]
                    try:
                        layer_type = cmds.nodeType(layer_node)
                    except Exception:
                        layer_type = ""

                    if layer_type.startswith("animCurve"):
                        lines.append("  [{}] animCurve {}".format(i,  _describe_animcurve(layer_node)))

                        driver_plug = _animcurve_driver_plug(layer_node)
                        driver_node = driver_plug.split(".", 1)[0] if driver_plug else ""
                        driver_target = _animcurve_driver_target(layer_node)
                        tag = _tag_get(layer_node) or {}
                        is_tool = bool(tag) and (tag.get("tool") == "facial_driver_recorder")
                        items.append(
                            {
                                "drivenPlug": plug,
                                "bw": bt.bw,
                                "bwIndex": int(i),
                                "curve": layer_node,
                                "driverPlug": driver_plug,
                                "driverNode": driver_node,
                                "driverTarget": float(driver_target),
                                "tagTool": bool(is_tool),
                                "kind": bt.kind,
                                "conversionFactor": float(bt.conversion_factor),
                            }
                        )
                    else:
                        lines.append("  [{}] {} {}".format(i, layer_type, layer_src))

                continue

            if src_type.startswith("animCurve"):
                animcurve_direct += 1
                lines.append("{}: animCurve {}".format(plug,  _describe_animcurve(src_node)))

                driver_plug = _animcurve_driver_plug(src_node)
                driver_node = driver_plug.split(".", 1)[0] if driver_plug else ""
                driver_target = _animcurve_driver_target(src_node)
                tag = _tag_get(src_node) or {}
                is_tool = bool(tag) and (tag.get("tool") == "facial_driver_recorder")
                items.append(
                    {
                        "drivenPlug": plug,
                        "bw": "",
                        "bwIndex": None,
                        "curve": src_node,
                        "driverPlug": driver_plug,
                        "driverNode": driver_node,
                        "driverTarget": float(driver_target),
                        "tagTool": bool(is_tool),
                        "kind": "directCurve",
                        "conversionFactor": 1.0,
                    }
                )
            else:
                lines.append("{}: {} {}".format(plug, src_type, src))

    lines.append(
        "// Scanned plugs: {}  withIncoming: {}  blendWeighted: {}  animCurveDirect: {}".format(scanned, has_incoming, bw_count, animcurve_direct)
    )

    return "\n".join(lines), items


def scan_sdk(driven_nodes, channels):
    """Scan selected driven plugs and report existing SDK / driving networks.

    This is intentionally non-destructive: it only inspects connections.
    Returns the human-readable report string (also printed by UI).
    """

    report, _items = scan_sdk_detailed(driven_nodes, channels)
    return report


def _ui_scan_sdk(*_):
    channels = _ui_get_channels()
    if not channels:
        _warn(_t("warn_no_driven_plugs"))
        return

    driven_nodes = _ui_get_driven_nodes_cmds()
    if not driven_nodes:
        _warn(_t("warn_driven_list_empty"))
        return

    # Avoid accidentally including the driver node.
    driver_plug = _ui_get_driver_plug()
    driver_node = driver_plug.split(".", 1)[0] if driver_plug else ""
    driven_nodes = [n for n in driven_nodes if n != driver_node]

    use_parent = bool(cmds.checkBox("fdr_useParent", q=True, v=True))
    parent_levels = int(cmds.intField("fdr_parentLevels", q=True, v=True))
    bake_to_parent = bool(cmds.checkBox("fdr_bakeToParent", q=True, v=True))

    # Match the actual commit target behavior.
    if bake_to_parent and not use_parent:
        _warn(_t("warn_bake_needs_parent"))
        return
    if bake_to_parent and use_parent:
        mapping = _parent_map(driven_nodes, parent_levels)
        driven_nodes = list(dict.fromkeys(mapping.values()))
    elif use_parent:
        driven_nodes = _parent_levels(driven_nodes, parent_levels)

    if not driven_nodes:
        _warn(_t("warn_select_driven"))
        return

    global _SDK_SCAN_ITEMS

    report, items = scan_sdk_detailed(driven_nodes, channels)
    if not report:
        return

    _SDK_SCAN_ITEMS = list(items or [])

    # Sort so same driver groups together.
    def _k(it):
        dn = str(it.get("driverNode") or "")
        dp = str(it.get("driverPlug") or "")
        dr = str(it.get("drivenPlug") or "")
        bi = it.get("bwIndex")
        bi = int(bi) if bi is not None else 10**9
        return (dn, dp, dr, bi)

    _SDK_SCAN_ITEMS.sort(key=_k)
    _ui_sdk_refresh_list_display()

    print(report)


def _ui_sdk_refresh_list_display(*_):
    """Rebuild the SDK list UI based on current cache + fold option."""
    global _SDK_SCAN_ITEMS_VIEW

    folded = False
    try:
        if cmds.checkBox("fdr_sdkFold", exists=True):
            folded = bool(cmds.checkBox("fdr_sdkFold", q=True, v=True))
    except Exception:
        folded = _sdk_fold_enabled()

    # Persist option.
    try:
        cmds.optionVar(iv=(_SDK_FOLD_OPT_VAR, int(bool(folded))))
    except Exception:
        pass

    try:
        has_list = cmds.textScrollList("fdr_sdkList", exists=True)
    except Exception:
        has_list = False
    try:
        has_tree = cmds.treeView("fdr_sdkTree", exists=True)
    except Exception:
        has_tree = False

    if not (has_list or has_tree):
        return

    # Current view = full scan list (tree provides grouping/expanding).
    view_items = list(_SDK_SCAN_ITEMS or [])
    _SDK_SCAN_ITEMS_VIEW = list(view_items)

    # Rebuild tree view (primary display).
    if has_tree:
        try:
            _ui_sdk_refresh_tree_display(_SDK_SCAN_ITEMS_VIEW, folded)
        except Exception:
            pass

    if not has_list:
        return

        # Preserve selection index if possible.
        old_sii = cmds.textScrollList("fdr_sdkList", q=True, sii=True) or []

    try:
        # Preserve selection index if possible.
        old_sii = cmds.textScrollList("fdr_sdkList", q=True, sii=True) or []

        cmds.textScrollList("fdr_sdkList", e=True, ra=True)
        for it in _SDK_SCAN_ITEMS_VIEW:
            cmds.textScrollList("fdr_sdkList", e=True, a=_sdk_make_display(it, folded))

        if old_sii:
            try:
                cmds.textScrollList("fdr_sdkList", e=True, sii=old_sii)
            except Exception:
                pass
    except Exception:
        pass


def _sdk_item_desc(item):
    plug = item.get("drivenPlug") or ""
    bw = item.get("bw") or ""
    idx = item.get("bwIndex")
    curve = item.get("curve") or ""
    driver = item.get("driverPlug") or ""
    if bw and (idx is not None):
        return "{}\nBW: {}.input[{}]\nCurve: {}\nDriver: {}".format(plug, bw, idx, curve, driver).strip()
    return "{}\nCurve: {}\nDriver: {}".format(plug, curve, driver).strip()


def _sdk_ui_set_driver_fields(driver_plug):
    if not driver_plug or "." not in driver_plug:
        return
    node, attr = driver_plug.split(".", 1)
    try:
        cmds.textField("fdr_driverNode", e=True, tx=node)
    except Exception:
        pass
    _ui_refresh_driver_attr_menu(node, prefer_attr=attr)


def _ui_refresh_driver_attr_menu(node, prefer_attr= None):
    if not cmds.optionMenu("fdr_driverAttr", exists=True):
        return
    attrs = _driver_attr_candidates(node)
    try:
        cmds.optionMenu("fdr_driverAttr", e=True, deleteAllItems=True)
    except Exception:
        try:
            cmds.optionMenu("fdr_driverAttr", e=True, dai=True)
        except Exception:
            return
    for a in attrs:
        cmds.menuItem(l=a)

    if not attrs:
        return

    pick = prefer_attr if (prefer_attr in attrs) else attrs[0]
    try:
        cmds.optionMenu("fdr_driverAttr", e=True, v=pick)
    except Exception:
        pass


def _sdk_items_for_same_driver(driver_plug, driver_target):
    """Return scan items matching this driver plug and (approximately) target."""
    out = []
    if not driver_plug:
        return out

    try:
        dt = float(driver_target)
    except Exception:
        dt = 1.0

    for it in (_SDK_SCAN_ITEMS or []):
        if not _plug_matches(str(it.get("driverPlug") or ""), str(driver_plug)):
            continue
        try:
            t = float(it.get("driverTarget") or 0.0)
        except Exception:
            t = 0.0
        if abs(t - dt) <= float(_DRIVER_TARGET_MATCH_EPS):
            out.append(it)
    return out


def _find_animcurve_layers_for_driver(bw, driver_plug):
    """Return [(bwIndex, animCurveNode), ...] for layers driven by driver_plug."""
    out = []
    if not bw or not cmds.objExists(bw) or not driver_plug:
        return out
    for i in _bw_connected_input_indices(bw):
        in_plug = "{}.input[{}]".format(bw, i)
        curve = _animcurve_from_plug(in_plug)
        if not curve:
            continue
        if _curve_is_driven_by(curve, driver_plug):
            out.append((int(i), curve))
    return out


@_undoable("FDR Enter Edit Driver")
def enter_edit_driver_group(driver_plug, driver_target, items):
    """Enter edit mode for a driver plug (e.g. ICon_Z.translateX at -1) across many driven plugs.

    The scope comes from the current Scan SDK result (selection + channel checkboxes).
    """

    if _session_load():
        _warn(_t("warn_session_active"))
        return

    if not driver_plug or not _attr_exists(driver_plug):
        _warn(_t("warn_driver_missing").format(plug=driver_plug))
        return

    # Build unique driven plug list.
    seen = set()
    driven_plugs = []
    for it in (items or []):
        p = str(it.get("drivenPlug") or "")
        if not p or (p in seen) or (not _attr_exists(p)):
            continue
        seen.add(p)
        driven_plugs.append(p)

    if not driven_plugs:
        _warn(_t("warn_sdk_no_driver_items"))
        return

    # Capture base at driver=0 with the rig connected.
    try:
        _set_driver_value(driver_plug, 0.0)
    except Exception:
        _warn(_t("warn_failed_set_driver0").format(plug=driver_plug))
        return

    entries = []
    duplicate_curves = []

    for plug in driven_plugs:
        try:
            locked = bool(cmds.getAttr(plug, lock=True))
        except Exception:
            locked = False
        if locked:
            try:
                cmds.setAttr(plug, lock=False)
            except Exception:
                pass

        base = _get_scalar(plug)
        src = _get_incoming_source_plug(plug)
        if src:
            _disconnect(src, plug)

        # Determine which curve we will overwrite.
        bt = _find_blendweighted_for_driven(plug, recorded_src_plug=src)
        curve_keep = None
        bw = ""
        bw_index = None
        if bt and bt.bw:
            bw = bt.bw
            layers = _find_animcurve_layers_for_driver(bt.bw, driver_plug)
            if layers:
                # Keep the highest index by default (last-added).
                layers.sort(key=lambda x: x[0])
                bw_index, curve_keep = layers[-1]
                # Mark the rest as duplicates.
                for _i, c in layers[:-1]:
                    duplicate_curves.append(c)

        entries.append(
            {
                "plug": plug,
                "base": base,
                "src": src,
                "locked": locked,
                "curve": curve_keep,
                "bw": bw,
                "bwIndex": bw_index,
            }
        )

    # Set driver to the edit value so user sees the pose to edit.
    try:
        _set_driver_value(driver_plug, float(driver_target))
    except Exception:
        _warn(_t("warn_failed_set_driver_edit").format(plug=driver_plug))

    session = {
        "mode": "editDriver",
        "driver": driver_plug,
        "driver_target": float(driver_target),
        "entries": entries,
        "dup_curves": list(dict.fromkeys([c for c in duplicate_curves if c])),
    }
    _session_save(session)

    # Match the normal workflow: select the actual recording targets so the user
    # does not accidentally move controller children (which won't change parent/offset values).
    try:
        target_nodes = [str(e.get("plug", "")).split(".", 1)[0] for e in entries if e.get("plug")]
        target_nodes = [n for n in dict.fromkeys(target_nodes) if n and cmds.objExists(n)]
        if target_nodes:
            cmds.select(target_nodes, r=True)
            _warn(_t("warn_edit_targets_selected").format(count=len(target_nodes)))
    except Exception:
        pass

    print("// Facial Driver Recorder: ENTER EDIT (DRIVER)")
    print("// Driver: {}  target={}".format(driver_plug, driver_target))
    print("// Driven plugs: {}".format(len(entries)))


@_undoable("FDR Enter Edit Driver Bake")
def enter_edit_driver_group_bake_to_parent(
    driver_plug,
    driver_target,
    controller_nodes,
    parent_levels,
    channels,
    items,
):
    """Batch edit by driver: pose visible controllers, but write/overwrite SDK deltas on parents.

    This is the bake-to-parent workflow combined with editDriver's "overwrite existing layer"
    behavior, so users don't have to manipulate hidden *_qudong_G groups.
    """

    if om2 is None:
        _warn(_t("warn_bake_requires_api"))
        return

    if _session_load():
        _warn(_t("warn_session_active"))
        return

    if not driver_plug or not _attr_exists(driver_plug):
        _warn(_t("warn_driver_missing").format(plug=driver_plug))
        return

    controller_nodes = [n for n in (controller_nodes or []) if n and cmds.objExists(n)]
    if not controller_nodes:
        _warn(_t("warn_select_driven"))
        return

    channels = list(channels or [])
    if not channels:
        _warn(_t("warn_no_driven_plugs"))
        return

    parent_levels = max(int(parent_levels), 1)
    mapping = _parent_map(controller_nodes, parent_levels)
    if not mapping:
        _warn(_t("warn_select_driven"))
        return

    # Scope driven plugs as: mapped parents x selected channels.
    # For Edit-By-Driver we prefer overwriting existing layers discovered by Scan SDK.
    # This avoids pulling unrelated channels into update mode (which causes "missing layer").
    parent_nodes = [p for p in dict.fromkeys(list(mapping.values())) if p and cmds.objExists(p)]
    driven_plugs = []
    for p in parent_nodes:
        for ch in channels:
            plug = "{}.{}".format(p, ch)
            if _attr_exists(plug):
                driven_plugs.append(plug)
    driven_plugs = list(dict.fromkeys(driven_plugs))

    # If scan items are available, narrow the scope to those existing SDK plugs.
    item_scope = {
        _canonical_plug_name(str(it.get("drivenPlug") or ""))
        for it in (items or [])
        if str(it.get("drivenPlug") or "") and _attr_exists(str(it.get("drivenPlug") or ""))
    }
    if item_scope:
        driven_plugs = [p for p in driven_plugs if _canonical_plug_name(p) in item_scope]
    if not driven_plugs:
        _warn(_t("warn_no_driven_plugs"))
        return

    # Capture base values for driven parent plugs at driver=0 with the rig connected.
    # We will write additive deltas relative to this base (same idea as non-bake edit).
    driven_base = {}
    try:
        _set_driver_value(driver_plug, 0.0)
    except Exception:
        _warn(_t("warn_failed_set_driver0").format(plug=driver_plug))
        return

    for p in driven_plugs:
        try:
            driven_base[p] = float(_get_scalar(p))
        except Exception:
            # If we can't read it now, we can't reliably compute a delta later.
            pass

    # Set driver to the edit value so user sees the pose they are editing.
    try:
        _set_driver_value(driver_plug, float(driver_target))
    except Exception:
        _warn(_t("warn_failed_set_driver_edit").format(plug=driver_plug))

    # Record controller base TR (so we can reset after baking), and disconnect selected channels for editing.
    ctrl_entries = []
    ctrl_base = {}
    for ctrl in controller_nodes:
        base_vals = {}
        for ch in ("translateX", "translateY", "translateZ", "rotateX", "rotateY", "rotateZ"):
            plug = "{}.{}".format(ctrl, ch)
            if _attr_exists(plug):
                try:
                    base_vals[ch] = _get_scalar(plug)
                except Exception:
                    pass
        ctrl_base[ctrl] = base_vals

        for ch in channels:
            plug = "{}.{}".format(ctrl, ch)
            if not _attr_exists(plug):
                continue

            try:
                locked = bool(cmds.getAttr(plug, lock=True))
            except Exception:
                locked = False
            if locked:
                try:
                    cmds.setAttr(plug, lock=False)
                except Exception:
                    pass

            src = _get_incoming_source_plug(plug)
            if src:
                _disconnect(src, plug)

            ctrl_entries.append({"plug": plug, "src": src, "locked": locked})

    # Precompute which curve to overwrite per driven plug.
    # Prefer exact curves from scan items first (works for both blendWeighted and directCurve).
    # If multiple exist for the same plug, keep the highest bwIndex as "last layer", mark others as duplicates.
    item_layers_by_plug = {}
    for it in (items or []):
        p = str(it.get("drivenPlug") or "")
        c = str(it.get("curve") or "")
        if not p or not c or not cmds.objExists(c):
            continue
        raw_idx = it.get("bwIndex")
        try:
            idx = int(raw_idx) if raw_idx is not None else -1
        except Exception:
            idx = -1
        item_layers_by_plug.setdefault(_canonical_plug_name(p), []).append((idx, c))

    driven_entries = []
    duplicate_curves = []
    for plug in driven_plugs:
        curve_keep = None
        bw = ""
        bw_index = None

        # 1) Prefer the scan result.
        existing = item_layers_by_plug.get(_canonical_plug_name(plug)) or []
        if existing:
            existing = sorted(existing, key=lambda x: x[0])
            bw_index, curve_keep = existing[-1]
            for _i, c in existing[:-1]:
                duplicate_curves.append(c)
            # Normalize direct-curve's sentinel index.
            if bw_index is not None and int(bw_index) < 0:
                bw_index = None

        # 2) Fallback: infer from current blendWeighted network.
        if not curve_keep:
            bt = _find_blendweighted_for_driven(plug)
            if bt and bt.bw:
                bw = bt.bw
                layers = _find_animcurve_layers_for_driver(bt.bw, driver_plug)
                if layers:
                    layers.sort(key=lambda x: x[0])
                    bw_index, curve_keep = layers[-1]
                    for _i, c in layers[:-1]:
                        duplicate_curves.append(c)

        driven_entries.append(
            {
                "plug": plug,
                "curve": curve_keep,
                "bw": bw,
                "bwIndex": bw_index,
            }
        )

    session = {
        "mode": "editDriverBakeToParent",
        "driver": driver_plug,
        "driver_target": float(driver_target),
        "parent_levels": int(parent_levels),
        "channels": list(channels),
        "mapping": [{"ctrl": c, "parent": p} for c, p in mapping.items()],
        "ctrl_entries": ctrl_entries,
        "ctrl_base": ctrl_base,
        "driven_entries": driven_entries,
        "driven_base": driven_base,
        "dup_curves": list(dict.fromkeys([c for c in duplicate_curves if c])),
    }
    _session_save(session)

    # Keep selection on controllers (visible) for convenience.
    try:
        cmds.select(controller_nodes, r=True)
        _warn(_t("warn_bake_mode_hint"))
    except Exception:
        pass

    print("// Facial Driver Recorder: ENTER EDIT (DRIVER BAKE)")
    print("// Driver: {}  target={}".format(driver_plug, driver_target))
    print("// Controllers: {}  Driven plugs: {}".format(len(controller_nodes), len(driven_entries)))


def _commit_edit_driver_bake_to_parent(
    session,
    write_mode = "update",
    apply_threshold = 1e-8,
):
    driver_plug = session.get("driver")
    driver_target = float(session.get("driver_target", 1.0))
    channels = session.get("channels") or []
    mapping = session.get("mapping") or []
    ctrl_entries = session.get("ctrl_entries") or []
    ctrl_base = session.get("ctrl_base") or {}
    driven_entries = session.get("driven_entries") or []
    driven_base = session.get("driven_base") or {}
    dup_curves = session.get("dup_curves") or []

    if om2 is None:
        _warn(_t("warn_bake_requires_api"))
        return

    if not driver_plug or not _attr_exists(driver_plug):
        _warn(_t("warn_session_driver_invalid"))
        return

    # Optional: cleanup duplicate layers (ask once).
    dup_curves = [c for c in dup_curves if c and cmds.objExists(c)]
    if dup_curves:
        if _confirm(
            _t("confirm_cleanup_dupes_title"),
            _t("confirm_cleanup_dupes_msg").format(driver=driver_plug, count=len(dup_curves)),
        ):
            deleted = 0
            for c in dup_curves:
                try:
                    outs = cmds.listConnections(c, s=False, d=True, p=True, scn=True) or []
                except Exception:
                    outs = []
                if len(outs) > 1:
                    continue
                try:
                    cmds.delete(c)
                    deleted += 1
                except Exception:
                    pass
            print("// Facial Driver Recorder: deleted duplicate curves: {}/{}".format(deleted, len(dup_curves)))

    # Evaluate at driver target.
    try:
        _set_driver_value(driver_plug, float(driver_target))
    except Exception:
        _warn(_t("warn_failed_set_driver_edit").format(plug=driver_plug))

    # Fast lookup: drivenPlug -> curve
    curve_by_plug = {}
    for e in driven_entries:
        p = str(e.get("plug") or "")
        c = str(e.get("curve") or "")
        if p and c:
            curve_by_plug[_canonical_plug_name(p)] = c

    driven_plug_scope = {
        _canonical_plug_name(str(e.get("plug") or ""))
        for e in driven_entries
        if e.get("plug")
    }

    created = 0
    updated = 0
    skipped = 0
    skipped_missing_layer = 0
    missing_layer_examples = []

    for pair in mapping:
        ctrl = pair.get("ctrl")
        parent = pair.get("parent")
        if not ctrl or not parent or (not cmds.objExists(ctrl)) or (not cmds.objExists(parent)):
            skipped += 1
            continue

        # Desired controller world pose (user-edited).
        try:
            c_world_desired = cmds.xform(ctrl, q=True, ws=True, m=True)
        except Exception:
            skipped += 1
            continue

        # Reset controller to base values (captured at Enter Edit) so we can compute the relative transform.
        base_vals = ctrl_base.get(ctrl, {})
        for ch, v in (base_vals or {}).items():
            plug = "{}.{}".format(ctrl, ch)
            if _attr_exists(plug):
                try:
                    _set_scalar(plug, float(v))
                except Exception:
                    pass

        # Compute controller relative matrix to the target parent.
        try:
            p_world_current = cmds.xform(parent, q=True, ws=True, m=True)
            c_world_base = cmds.xform(ctrl, q=True, ws=True, m=True)
        except Exception:
            skipped += 1
            continue

        try:
            m_p = _m_from_list16([float(x) for x in p_world_current])
            m_c_base = _m_from_list16([float(x) for x in c_world_base])
            m_c_desired = _m_from_list16([float(x) for x in c_world_desired])
        except Exception:
            skipped += 1
            continue

        m_c_rel = m_p.inverse() * m_c_base
        m_p_world_desired = m_c_desired * m_c_rel.inverse()

        # Let Maya decompose desired parent world matrix into local TRS.
        p_parent = (cmds.listRelatives(parent, p=True, f=False) or [None])[0]
        try:
            ro = int(cmds.getAttr(parent + ".rotateOrder"))
        except Exception:
            ro = 0

        tmp = None
        try:
            tmp = cmds.createNode(
                "transform",
                n="__fdrTmpDriverBake__#",
                p=(p_parent if p_parent and cmds.objExists(p_parent) else None),
            )
            try:
                cmds.setAttr(tmp + ".rotateOrder", ro)
            except Exception:
                pass
            cmds.xform(tmp, ws=True, m=[float(x) for x in _list16_from_m(m_p_world_desired)])
            desired_by_channel = {
                "translateX": float(cmds.getAttr(tmp + ".translateX")),
                "translateY": float(cmds.getAttr(tmp + ".translateY")),
                "translateZ": float(cmds.getAttr(tmp + ".translateZ")),
                "rotateX": float(cmds.getAttr(tmp + ".rotateX")),
                "rotateY": float(cmds.getAttr(tmp + ".rotateY")),
                "rotateZ": float(cmds.getAttr(tmp + ".rotateZ")),
                "scaleX": float(cmds.getAttr(tmp + ".scaleX")),
                "scaleY": float(cmds.getAttr(tmp + ".scaleY")),
                "scaleZ": float(cmds.getAttr(tmp + ".scaleZ")),
            }
        except Exception:
            skipped += 1
            continue
        finally:
            if tmp and cmds.objExists(tmp):
                try:
                    cmds.delete(tmp)
                except Exception:
                    pass

        for ch in channels:
            driven_plug = "{}.{}".format(parent, ch)
            if not _attr_exists(driven_plug):
                continue

            # Only touch plugs that are in the driver-scan scope.
            driven_plug_key = _canonical_plug_name(driven_plug)
            if driven_plug_scope and (driven_plug_key not in driven_plug_scope):
                continue

            desired_val = desired_by_channel.get(ch)
            if desired_val is None:
                continue

            # Compute additive delta relative to base at driver=0.
            if driven_plug not in driven_base:
                skipped += 1
                continue
            try:
                base_val = float(driven_base.get(driven_plug))
            except Exception:
                skipped += 1
                continue

            delta = _delta_for_plug(str(driven_plug), float(base_val), float(desired_val))
            if abs(delta) <= apply_threshold:
                skipped += 1
                continue

            bt = _find_blendweighted_for_driven(driven_plug)
            if not bt:
                bt = _ensure_network_for_driven(driven_plug)

            delta_bw = _to_blendweighted_delta(str(driven_plug), float(delta), bt)

            curve = curve_by_plug.get(driven_plug_key)
            if curve and cmds.objExists(curve):
                try:
                    _set_animcurve_key_unitless(curve, 0.0, 0.0)
                    _set_animcurve_key_unitless(curve, float(driver_target), float(delta_bw))
                    updated += 1
                except Exception as ex:
                    _warn(_t("warn_failed_create_sdk").format(plug=driven_plug, err=ex))
                    skipped += 1
                continue

            # No existing curve for this plug+driver.
            if (write_mode or "").lower() == "update":
                skipped_missing_layer += 1
                if len(missing_layer_examples) < 6:
                    missing_layer_examples.append(driven_plug)
                continue

            # In add-mode, create a new layer.
            try:
                idx = _find_free_bw_input_index(bt.bw)
                driven_bw_plug = "{}.input[{}]".format(bt.bw, idx)
                _set_driven_key(driver_plug, 0.0, driven_bw_plug, 0.0)
                _set_driven_key(driver_plug, float(driver_target), driven_bw_plug, float(delta_bw))
                created += 1
            except Exception as ex:
                _warn(_t("warn_failed_create_sdk").format(plug=driven_plug, err=ex))
                skipped += 1

    # Restore controller connections/locks (we keep their values at base).
    for e in ctrl_entries:
        plug = e.get("plug")
        if not plug:
            continue
        src = e.get("src")
        if src:
            _connect(src, plug)
        if e.get("locked"):
            try:
                cmds.setAttr(plug, lock=True)
            except Exception:
                pass

    # Driver back to 0 for safety.
    try:
        _set_driver_value(driver_plug, 0.0)
    except Exception:
        pass

    _session_clear()

    print("// Facial Driver Recorder: COMMIT (DRIVER BAKE)")
    print("// Updated layers: {}".format(updated))
    print("// Created layers: {}".format(created))
    print("// Skipped (no change / failed): {}".format(skipped))
    if skipped_missing_layer:
        print("// Skipped (missing layer in update mode): {}".format(skipped_missing_layer))
        # User-facing warning: in update mode we do not create new layers.
        plug_hint = ", ".join(missing_layer_examples) if missing_layer_examples else "<multiple>"
        _warn(_t("warn_update_missing_layer").format(plug=plug_hint))


def _commit_edit_driver(session, apply_threshold= 1e-8):
    driver_plug = session.get("driver")
    driver_target = float(session.get("driver_target", 1.0))
    entries = session.get("entries") or []
    dup_curves = session.get("dup_curves") or []

    if not driver_plug or not _attr_exists(driver_plug):
        _warn(_t("warn_session_driver_invalid"))
        return

    # Read posed targets while still disconnected.
    for e in entries:
        plug = e.get("plug")
        try:
            e["target"] = _get_scalar(plug) if plug else None
        except Exception:
            e["target"] = None

    # Restore connections and locks.
    for e in entries:
        plug = e.get("plug")
        src = e.get("src")
        if plug and src:
            _connect(src, plug)
        if plug and e.get("locked"):
            try:
                cmds.setAttr(plug, lock=True)
            except Exception:
                pass

    # Driver back to 0 for safety.
    try:
        _set_driver_value(driver_plug, 0.0)
    except Exception:
        pass

    # Optional: cleanup duplicate layers (ask once).
    dup_curves = [c for c in dup_curves if c and cmds.objExists(c)]
    if dup_curves:
        if _confirm(
            _t("confirm_cleanup_dupes_title"),
            _t("confirm_cleanup_dupes_msg").format(driver=driver_plug, count=len(dup_curves)),
        ):
            deleted = 0
            for c in dup_curves:
                try:
                    # Safety: don't delete if curve drives multiple outputs.
                    outs = cmds.listConnections(c, s=False, d=True, p=True, scn=True) or []
                except Exception:
                    outs = []
                if len(outs) > 1:
                    continue
                try:
                    cmds.delete(c)
                    deleted += 1
                except Exception:
                    pass
            print("// Facial Driver Recorder: deleted duplicate curves: {}/{}".format(deleted, len(dup_curves)))

    updated = 0
    created = 0
    skipped = 0

    for e in entries:
        plug = e.get("plug")
        base = e.get("base")
        target = e.get("target")
        src = e.get("src")

        if (not plug) or (target is None) or (base is None):
            skipped += 1
            continue

        delta = _delta_for_plug(str(plug), float(base), float(target))
        if abs(delta) <= apply_threshold:
            skipped += 1
            continue

        bt = _find_blendweighted_for_driven(plug, recorded_src_plug=src)
        if not bt:
            bt = _ensure_network_for_driven(plug)

        delta_bw = _to_blendweighted_delta(str(plug), float(delta), bt)

        curve = e.get("curve")
        if curve and cmds.objExists(curve):
            try:
                _set_animcurve_key_unitless(curve, 0.0, 0.0)
                _set_animcurve_key_unitless(curve, float(driver_target), float(delta_bw))
                updated += 1
            except Exception as ex:
                _warn(_t("warn_failed_create_sdk").format(plug=plug, err=ex))
                skipped += 1
            continue

        # If no existing curve found, create a new layer (still only one for this plug).
        try:
            idx = _find_free_bw_input_index(bt.bw)
            driven_bw_plug = "{}.input[{}]".format(bt.bw, idx)
            _set_driven_key(driver_plug, 0.0, driven_bw_plug, 0.0)
            _set_driven_key(driver_plug, float(driver_target), driven_bw_plug, float(delta_bw))
            created += 1
        except Exception as ex:
            _warn(_t("warn_failed_create_sdk").format(plug=plug, err=ex))
            skipped += 1

    _session_clear()

    print("// Facial Driver Recorder: COMMIT (DRIVER)")
    print("// Updated layers: {}".format(updated))
    print("// Created layers: {}".format(created))
    print("// Skipped (no change / failed): {}".format(skipped))


def _confirm_add_over_existing(driver_plug, driven_plugs):
    """When in add mode, warn if existing layers for this driver are already present."""
    if not driver_plug:
        return True
    count = 0
    for plug in (driven_plugs or []):
        if not _attr_exists(plug):
            continue
        bt = _find_blendweighted_for_driven(plug)
        if not bt:
            continue
        layers = _find_animcurve_layers_for_driver(bt.bw, driver_plug)
        if layers:
            count += 1

    if count <= 0:
        return True

    return _confirm(
        _t("confirm_add_over_existing_title"),
        _t("confirm_add_over_existing_msg").format(driver=driver_plug, count=count),
    )


@_undoable("FDR Enter Edit Layer")
def enter_edit_existing_layer(item):
    if _session_load():
        _warn(_t("warn_session_active"))
        return

    driven_plug = str(item.get("drivenPlug") or "")
    curve = str(item.get("curve") or "")
    driver_plug = str(item.get("driverPlug") or "")
    driver_target = float(item.get("driverTarget") or 1.0)
    bw = str(item.get("bw") or "")
    bw_index = item.get("bwIndex")

    if (not driven_plug) or (not curve) or (not driver_plug):
        _warn(_t("warn_sdk_item_invalid"))
        return
    if not (_attr_exists(driven_plug) and _attr_exists(driver_plug) and cmds.objExists(curve)):
        _warn(_t("warn_sdk_item_invalid"))
        return

    try:
        _set_driver_value(driver_plug, 0.0)
    except Exception:
        _warn(_t("warn_failed_set_driver0").format(plug=driver_plug))
        return

    try:
        locked = bool(cmds.getAttr(driven_plug, lock=True))
    except Exception:
        locked = False
    if locked:
        try:
            cmds.setAttr(driven_plug, lock=False)
        except Exception:
            pass

    base = _get_scalar(driven_plug)
    src = _get_incoming_source_plug(driven_plug)
    if src:
        _disconnect(src, driven_plug)

    try:
        _set_driver_value(driver_plug, float(driver_target))
    except Exception:
        _warn(_t("warn_failed_set_driver_edit").format(plug=driver_plug))

    session = {
        "mode": "editLayer",
        "driver": driver_plug,
        "driver_target": float(driver_target),
        "entries": [{"plug": driven_plug, "base": base, "src": src, "locked": locked}],
        "edit_layer": {"curve": curve, "bw": bw, "bwIndex": bw_index},
    }
    _session_save(session)

    print("// Facial Driver Recorder: ENTER EDIT (LAYER)")
    print("// Driver: {}  target={}".format(driver_plug, driver_target))
    print("// Driven plug: {}  curve={}".format(driven_plug, curve))


def _commit_edit_layer(session, apply_threshold= 1e-8):
    driver_plug = session.get("driver")
    driver_target = float(session.get("driver_target", 1.0))
    entries = session.get("entries") or []
    edit_layer = session.get("edit_layer") or {}

    curve = edit_layer.get("curve")
    if not driver_plug or not _attr_exists(driver_plug):
        _warn(_t("warn_session_driver_invalid"))
        return
    if not curve or (not cmds.objExists(curve)):
        _warn(_t("warn_sdk_item_invalid"))
        return

    for e in entries:
        plug = e.get("plug")
        if not plug:
            continue
        try:
            e["target"] = _get_scalar(plug)
        except Exception:
            e["target"] = None

    for e in entries:
        plug = e.get("plug")
        if not plug:
            continue
        src = e.get("src")
        if src:
            _connect(src, plug)
        if e.get("locked"):
            try:
                cmds.setAttr(plug, lock=True)
            except Exception:
                pass

    try:
        _set_driver_value(driver_plug, 0.0)
    except Exception:
        pass

    updated = 0
    skipped = 0
    for e in entries:
        plug = e.get("plug")
        base = e.get("base")
        target = e.get("target")
        src = e.get("src")

        if (not plug) or (target is None) or (base is None):
            skipped += 1
            continue

        delta = _delta_for_plug(str(plug), float(base), float(target))
        if abs(delta) <= apply_threshold:
            skipped += 1
            continue

        bt = _find_blendweighted_for_driven(plug, recorded_src_plug=src)
        delta_bw = _to_blendweighted_delta(str(plug), float(delta), bt)

        try:
            _set_animcurve_key_unitless(curve, 0.0, 0.0)
            _set_animcurve_key_unitless(curve, float(driver_target), float(delta_bw))
            updated += 1
        except Exception as ex:
            _warn(_t("warn_failed_create_sdk").format(plug=plug, err=ex))
            skipped += 1

    _session_clear()
    print("// Facial Driver Recorder: COMMIT (LAYER)")
    print("// Updated layers: {}".format(updated))
    print("// Skipped (no change / failed): {}".format(skipped))


@_undoable("FDR Delete SDK Layer")
def delete_sdk_layer(item):
    curve = str(item.get("curve") or "")
    bw = str(item.get("bw") or "")
    idx = item.get("bwIndex")

    if not curve or (not cmds.objExists(curve)):
        return False

    try:
        outs = cmds.listConnections(curve, s=False, d=True, p=True, scn=True) or []
    except Exception:
        outs = []
    if len(outs) > 1:
        _warn(_t("warn_delete_multi_outputs").format(count=len(outs), node=curve))
        return False

    if bw and (idx is not None) and cmds.objExists(bw):
        in_plug = "{}.input[{}]".format(bw, int(idx))
        try:
            srcs = cmds.listConnections(in_plug, s=True, d=False, p=True, scn=True) or []
        except Exception:
            srcs = []
        for s in srcs:
            try:
                if s.split(".", 1)[0] == curve:
                    _disconnect(s, in_plug)
            except Exception:
                continue

    try:
        cmds.delete(curve)
        return True
    except Exception:
        return False


def _ui_sdk_get_selected_item():
    global _SDK_SCAN_ITEMS_VIEW
    global _SDK_TREE_LEAF_MAP

    # Prefer tree selection if available.
    try:
        if cmds.treeView("fdr_sdkTree", exists=True):
            sel_ids = cmds.treeView("fdr_sdkTree", q=True, selectItem=True) or []
            for sid in sel_ids:
                if sid in (_SDK_TREE_LEAF_MAP or {}):
                    return _SDK_TREE_LEAF_MAP[sid]
    except Exception:
        pass

    try:
        sii = cmds.textScrollList("fdr_sdkList", q=True, sii=True) or []
        if not sii:
            return None
        i = int(sii[0]) - 1
        if i < 0 or i >= len(_SDK_SCAN_ITEMS_VIEW):
            return None
        return _SDK_SCAN_ITEMS_VIEW[i]
    except Exception:
        return None


def _sdk_item_nodes(item):
    driven_plug = str(item.get("drivenPlug") or "")
    driven_node = driven_plug.split(".", 1)[0] if driven_plug else ""
    driver_node = str(item.get("driverNode") or "")
    if not driver_node:
        driver_plug = str(item.get("driverPlug") or "")
        driver_node = driver_plug.split(".", 1)[0] if driver_plug else ""
    return driven_node, driver_node


def _sdk_items_for_root(driven_node, driver_node, items):
    out = []
    for it in (items or []):
        dn, drn = _sdk_item_nodes(it)
        if dn == driven_node and drn == driver_node:
            out.append(it)
    return out


def _dedupe_sdk_items(items):
    seen = set()
    out = []
    for it in (items or []):
        curve = str(it.get("curve") or "")
        driven = str(it.get("drivenPlug") or "")
        driver = str(it.get("driverPlug") or "")
        key = (curve, driven, driver, str(it.get("bwIndex") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _ui_sdk_get_selected_items():
    """Return selected SDK items from the tree/list (multi-select supported)."""
    items = []

    # Prefer tree selection if available.
    try:
        if cmds.treeView("fdr_sdkTree", exists=True):
            sel_ids = cmds.treeView("fdr_sdkTree", q=True, selectItem=True) or []
            for sid in sel_ids:
                if sid in (_SDK_TREE_LEAF_MAP or {}):
                    items.append(_SDK_TREE_LEAF_MAP[sid])
                    continue
                if sid in (_SDK_TREE_ROOT_MAP or {}):
                    root = _SDK_TREE_ROOT_MAP[sid] or {}
                    driven_node = str(root.get("drivenNode") or "")
                    driver_node = str(root.get("driverNode") or "")
                    items.extend(_sdk_items_for_root(driven_node, driver_node, _SDK_SCAN_ITEMS_VIEW))
    except Exception:
        pass

    # Fallback: textScrollList selections (multi-select).
    if not items:
        try:
            sii = cmds.textScrollList("fdr_sdkList", q=True, sii=True) or []
            for idx in sii:
                i = int(idx) - 1
                if 0 <= i < len(_SDK_SCAN_ITEMS_VIEW):
                    items.append(_SDK_SCAN_ITEMS_VIEW[i])
        except Exception:
            pass

    return _dedupe_sdk_items(items)


def _ui_sdk_edit_selected(*_):
    item = _ui_sdk_get_selected_item()
    if not item:
        _warn(_t("warn_sdk_item_not_selected"))
        return
    _sdk_ui_set_driver_fields(str(item.get("driverPlug") or ""))
    try:
        _ui_set_driver_value_with_sign_cmds(float(item.get("driverTarget") or 1.0))
    except Exception:
        pass
    enter_edit_existing_layer(item)


def _ui_sdk_edit_driver(*_):
    item = _ui_sdk_get_selected_item()
    if not item:
        _warn(_t("warn_sdk_item_not_selected"))
        return

    driver_plug = str(item.get("driverPlug") or "")
    driver_target = float(item.get("driverTarget") or 1.0)

    # Scope for batch edit should follow the user's current selection.
    # not only the last Scan SDK cache (which may have been done on a different selection).
    # We do a lightweight internal scan here and filter by driver.
    channels = _ui_get_channels()
    if not channels:
        _warn(_t("warn_no_driven_plugs"))
        return

    controller_nodes = _ui_get_driven_nodes_cmds()
    if not controller_nodes:
        _warn(_t("warn_driven_list_empty"))
        return
    # Avoid accidentally including the driver node.
    driver_node = driver_plug.split(".", 1)[0] if driver_plug else ""
    controller_nodes = [n for n in controller_nodes if n != driver_node]
    if not controller_nodes:
        _warn(_t("warn_select_driven"))
        return

    use_parent = bool(cmds.checkBox("fdr_useParent", q=True, v=True))
    parent_levels = int(cmds.intField("fdr_parentLevels", q=True, v=True))
    bake_to_parent = bool(cmds.checkBox("fdr_bakeToParent", q=True, v=True))
    auto_bake = _should_auto_bake_to_parent(controller_nodes, use_parent=use_parent, bake_to_parent=bake_to_parent)
    if auto_bake:
        bake_to_parent = True
        _warn(_t("warn_auto_bake_parent_mode"))
        try:
            cmds.checkBox("fdr_bakeToParent", e=True, v=True)
        except Exception:
            pass

    driven_nodes = list(controller_nodes)
    if bake_to_parent and not use_parent:
        _warn(_t("warn_bake_needs_parent"))
        return
    if bake_to_parent and use_parent:
        mapping = _parent_map(controller_nodes, parent_levels)
        driven_nodes = list(dict.fromkeys(mapping.values()))
    elif use_parent:
        driven_nodes = _parent_levels(controller_nodes, parent_levels)

    temp_items = []
    if driven_nodes:
        try:
            _report, temp_items = scan_sdk_detailed(driven_nodes, channels)
        except Exception:
            temp_items = []

    def _match_items(source_items, strict_target):
        out = []
        for it in (source_items or []):
            if not _plug_matches(str(it.get("driverPlug") or ""), str(driver_plug)):
                continue
            if strict_target:
                try:
                    t = float(it.get("driverTarget") or 0.0)
                except Exception:
                    t = 0.0
                if abs(t - float(driver_target)) > float(_DRIVER_TARGET_MATCH_EPS):
                    continue
            out.append(it)
        return out

    items = _match_items(temp_items, strict_target=True)
    if not items:
        # If target inference is off or there are multiple targets, fall back to same driver plug.
        items = _match_items(temp_items, strict_target=False)
    if not items:
        # Final fallback: use last Scan SDK cache.
        items = _sdk_items_for_same_driver(driver_plug, driver_target)
        if not items:
            items = [
                it
                for it in (_SDK_SCAN_ITEMS or [])
                if _plug_matches(str(it.get("driverPlug") or ""), str(driver_plug))
            ]
    if not items:
        _warn(_t("warn_sdk_no_driver_items"))
        return

    # Batch edit should follow ADV-like timeline workflow (0..N), then Commit samples keys.
    try:
        frame_range = int(cmds.intField("fdr_frameRange", q=True, v=True))
    except Exception:
        frame_range = _optvar_get_int(_FRAME_RANGE_OPT_VAR, 10)
    frame_range = max(int(frame_range), 1)
    try:
        cmds.optionVar(iv=(_FRAME_RANGE_OPT_VAR, int(frame_range)))
    except Exception:
        pass

    _sdk_ui_set_driver_fields(driver_plug)
    _ui_set_driver_value_with_sign_cmds(driver_target)
    if bake_to_parent and use_parent:
        enter_edit_timeline_bake_to_parent(
            driver_plug=driver_plug,
            driver_target_value=driver_target,
            frame_range=frame_range,
            controller_nodes=controller_nodes,
            parent_levels=parent_levels,
            channels=channels,
        )
    else:
        if use_parent:
            driven_nodes = _parent_levels(controller_nodes, parent_levels)
            if not driven_nodes:
                _warn(_t("warn_select_driven"))
                return
        else:
            driven_nodes = controller_nodes
        enter_edit_timeline(
            driver_plug=driver_plug,
            driver_target_value=driver_target,
            frame_range=frame_range,
            driven_nodes=driven_nodes,
            channels=channels,
            cleanup_extra_nodes=controller_nodes,
        )
    _restore_selection_safe(controller_nodes)

    # Narrow timeline scope to scanned SDK plugs and prefer overwriting existing layers.
    _mark_active_timeline_session_for_driver_batch(items)


def _ui_sdk_delete_selected(*_):
    items = _ui_sdk_get_selected_items()
    if not items:
        _warn(_t("warn_sdk_item_not_selected"))
        return
    if len(items) == 1:
        desc = _sdk_item_desc(items[0])
        if not _confirm(_t("confirm_delete_title"), _t("confirm_delete_msg").format(desc=desc)):
            return
    else:
        if not _confirm(_t("confirm_delete_title"), _t("confirm_delete_multi_msg").format(count=len(items))):
            return

    ok_any = False
    with _undo_chunk("FDR Delete SDK Layers"):
        for it in items:
            if delete_sdk_layer(it):
                ok_any = True

    if not ok_any:
        _warn(_t("warn_sdk_item_invalid"))
        return
    _ui_scan_sdk()


def _ui_sdk_select_driver(*_):
    # Special case: allow selecting a ROOT (group) item in the tree.
    item = None
    driver_node = ""
    driver_plug = ""

    try:
        if cmds.treeView("fdr_sdkTree", exists=True):
            sel_ids = cmds.treeView("fdr_sdkTree", q=True, selectItem=True) or []
            if sel_ids:
                sid = sel_ids[0]
                if sid in (_SDK_TREE_LEAF_MAP or {}):
                    item = _SDK_TREE_LEAF_MAP[sid]
                elif sid in (_SDK_TREE_ROOT_MAP or {}):
                    root_info = _SDK_TREE_ROOT_MAP[sid] or {}
                    driver_node = str(root_info.get("driverNode") or "")
                    driver_plug = str(root_info.get("driverPlug") or "")
    except Exception:
        pass

    if item is None and (not driver_node):
        item = _ui_sdk_get_selected_item()

    if item:
        driver_node = str(item.get("driverNode") or "")
        driver_plug = str(item.get("driverPlug") or "")

    if (not driver_node) and driver_plug and ("." in driver_plug):
        driver_node = driver_plug.split(".", 1)[0]

    if not driver_node and not driver_plug:
        _warn(_t("warn_sdk_item_not_selected"))
        return

    if not driver_node or (not cmds.objExists(driver_node)):
        _warn(_t("warn_sdk_item_invalid"))
        return

    # Also update the driver fields in the UI when possible.
    try:
        if driver_plug:
            _sdk_ui_set_driver_fields(driver_plug)
        elif driver_node:
            cmds.textField("fdr_driverNode", e=True, tx=driver_node)
    except Exception:
        pass

    # Prefer selecting a transform (controller) if the driver node is a shape or a utility node.
    sel = driver_node
    try:
        if cmds.nodeType(driver_node) != "transform":
            parents = cmds.listRelatives(driver_node, p=True, type="transform") or []
            if parents:
                sel = parents[0]
    except Exception:
        sel = driver_node

    try:
        cmds.select(sel, r=True)
    except Exception:
        pass


def _ui_cancel(*_):
    cancel()


def _ui_create_load_parent_from_selection(*_):
    sel = cmds.ls(sl=True, type="transform") or []
    if not sel:
        _warn(_t("warn_select_driver"))
        return
    cmds.textField("fdr_createParent", e=True, tx=sel[0])


def _ui_create_corrective(*_):
    base = ""
    parent = ""
    radius = 1.0
    try:
        base = cmds.textField("fdr_createBase", q=True, tx=True).strip()
    except Exception:
        base = ""
    try:
        parent = cmds.textField("fdr_createParent", q=True, tx=True).strip()
    except Exception:
        parent = ""
    try:
        radius = float(cmds.floatField("fdr_createRadius", q=True, v=True))
    except Exception:
        radius = 1.0

    created = create_corrective_joint_and_control(base, parent or None, radius=radius)
    if created:
        try:
            cmds.select([created.get("ctrl"), created.get("joint")], r=True)
        except Exception:
            pass


def _ui_mirror_apply(*_):
    # Use selection when available; otherwise mirror the current session targets.
    nodes = cmds.ls(sl=True, type="transform") or []
    if not nodes:
        session = _session_load() or {}
        if session.get("mode") == "bakeToParent":
            mapping = session.get("mapping") or []
            nodes = [m.get("ctrl") for m in mapping if m.get("ctrl")]
        else:
            nodes = session.get("driven_nodes") or []

    channels = _ui_get_channels()
    axis = "X"
    direction = "L2R"
    try:
        axis = cmds.optionMenu("fdr_mirrorAxis", q=True, v=True)
    except Exception:
        axis = "X"
    try:
        direction = cmds.optionMenu("fdr_mirrorDir", q=True, v=True)
    except Exception:
        direction = "L2R"

    # UI shows arrows, but core uses L2R/R2L.
    dir_norm = str(direction).strip()
    if dir_norm in ("L\u2192R", "L->R", "L2R"):
        dir_norm = "L2R"
    elif dir_norm in ("R\u2192L", "R->L", "R2L"):
        dir_norm = "R2L"

    cmds.optionVar(sv=(_MIRROR_AXIS_OPT_VAR, str(axis)))
    cmds.optionVar(sv=(_MIRROR_DIR_OPT_VAR, str(dir_norm)))

    mirror_apply(nodes, channels, axis=axis, direction=dir_norm)


def show_ui_qt():
    """Show the Qt-based UI with dark theme (ADV-style)."""
    try:
        from PySide2 import QtWidgets, QtCore, QtGui
    except ImportError:
        try:
            from PySide6 import QtWidgets, QtCore, QtGui
        except ImportError:
            cmds.warning("Qt not available, falling back to Maya UI")
            show_ui()
            return

    try:
        import shiboken2
        from maya import OpenMayaUI as omui
    except ImportError:
        try:
            import shiboken6 as shiboken2
            from maya import OpenMayaUI as omui
        except ImportError:
            cmds.warning("Shiboken not available, falling back to Maya UI")
            show_ui()
            return

    # Get Maya main window
    def get_maya_window():
        ptr = omui.MQtUtil.mainWindow()
        if ptr:
            return shiboken2.wrapInstance(int(ptr), QtWidgets.QWidget)
        return None

    # Close existing window
    for widget in QtWidgets.QApplication.allWidgets():
        if widget.objectName() == "FacialDriverRecorderQtWindow":
            widget.close()
            widget.deleteLater()

    # Create main window
    maya_window = get_maya_window()
    window = QtWidgets.QDialog(maya_window)
    window.setObjectName("FacialDriverRecorderQtWindow")
    window.setWindowTitle(_t("title"))
    try:
        flags = window.windowFlags()
        flags |= QtCore.Qt.Window
        # Ensure system titlebar shows minimize/maximize controls.
        if hasattr(QtCore.Qt, "WindowMinMaxButtonsHint"):
            flags |= QtCore.Qt.WindowMinMaxButtonsHint
        if hasattr(QtCore.Qt, "WindowMinimizeButtonHint"):
            flags |= QtCore.Qt.WindowMinimizeButtonHint
        if hasattr(QtCore.Qt, "WindowMaximizeButtonHint"):
            flags |= QtCore.Qt.WindowMaximizeButtonHint
        if hasattr(QtCore.Qt, "WindowCloseButtonHint"):
            flags |= QtCore.Qt.WindowCloseButtonHint
        window.setWindowFlags(flags)
        if hasattr(QtCore.Qt, "WindowContextHelpButtonHint"):
            window.setWindowFlag(QtCore.Qt.WindowContextHelpButtonHint, False)
    except Exception:
        pass
    # Keep UI readable across mixed DPI / scaling settings.
    def _ui_scale_factor():
        screen = None
        try:
            screen = window.screen()
        except Exception:
            screen = None
        if screen is None:
            try:
                app = QtWidgets.QApplication.instance()
                if app is not None:
                    screen = app.primaryScreen()
            except Exception:
                screen = None

        dpi_scale = 1.0
        dpr_scale = 1.0
        try:
            if screen is not None:
                dpi = float(screen.logicalDotsPerInch() or 96.0)
                dpr = float(screen.devicePixelRatio() or 1.0)
                if dpi > 0.0:
                    dpi_scale = dpi / 96.0
                if dpr > 0.0:
                    dpr_scale = dpr
        except Exception:
            pass

        scale = dpi_scale
        if dpi_scale < 1.1 and dpr_scale > scale:
            scale = dpr_scale
        return max(1.0, min(2.0, float(scale)))

    _ui_scale = _ui_scale_factor()

    def _px(v):
        try:
            return max(1, int(round(float(v) * _ui_scale)))
        except Exception:
            return 1

    font_h = int(max(12, QtGui.QFontMetrics(window.font()).height()))
    ctrl_h = max(_px(24), font_h + _px(10))
    btn_h = max(_px(28), font_h + _px(12))
    btn_main_h = max(_px(32), font_h + _px(14))

    min_w = _px(300)  # 允许更小的最小宽度
    min_h = _px(200)  # 允许更小的最小高度
    init_w = _px(1050)
    init_h = _px(700)
    try:
        screen = window.screen()
        if screen is None:
            app = QtWidgets.QApplication.instance()
            if app is not None:
                screen = app.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            max_w = max(900, int(geo.width() * 0.96))
            max_h = max(620, int(geo.height() * 0.96))
            init_w = max(900, min(init_w, max_w))
            init_h = max(620, min(init_h, max_h))
    except Exception:
        pass
    window.setMinimumSize(min_w, min_h)
    window.resize(init_w, init_h)

    # Apply dark theme stylesheet (ADV-style)
    bg_color = "#2A2D34"
    bg_darker = "#1F2127"
    border_color = "#14151A"
    accent_color = "#5A8FBF"
    btn_color = "#3A3D46"
    btn_hover = "#4A4F5B"
    btn_pressed = "#2A2D34"
    text_color = "#D8D8D8"

    stylesheet = """
    QDialog {{
        background-color: {};
        color: {};
        font-size: {}px;
    }}
    QLabel {{
        background: transparent;
        color: {};
    }}
    QGroupBox {{
        border: 1px solid #3A3D46;
        border-radius: {}px;
        margin-top: {}px;
        padding-top: {}px;
        background: transparent;
        font-weight: 600;
        color: {};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: {}px;
        padding: 0 {}px;
        background: transparent;
    }}
    QPushButton {{
        background: {};
        border: 1px solid {};
        border-radius: {}px;
        padding: {}px {}px;
        min-height: {}px;
        color: {};
    }}
    QPushButton:hover {{
        background: {};
    }}
    QPushButton:pressed {{
        background: {};
    }}
    QPushButton:disabled {{
        background: #2A2D34;
        color: #5A5A5A;
    }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {};
        border: 1px solid {};
        border-radius: {}px;
        padding: {}px {}px;
        min-height: {}px;
        color: {};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {};
    }}
    QComboBox::drop-down {{
        border: 0px;
        width: {}px;
    }}
    QComboBox:hover {{
        border: 1px solid {};
    }}
    QComboBox QAbstractItemView {{
        background: {};
        color: {};
        selection-background-color: {};
        selection-color: #FFFFFF;
        outline: 0px;
    }}
    QCheckBox {{
        spacing: {}px;
        background: transparent;
        color: {};
    }}
    QCheckBox::indicator {{
        width: {}px;
        height: {}px;
        border-radius: {}px;
        border: 1px solid {};
        background: transparent;
    }}
    QCheckBox::indicator:checked {{
        background: {};
        border: 1px solid {};
    }}
    QTreeWidget {{
        background: {};
        border: 1px solid {};
        border-radius: {}px;
        color: {};
        outline: 0px;
    }}
    QTreeWidget::item {{
        padding: {}px;
    }}
    QTreeWidget::item:selected {{
        background: {};
        color: #FFFFFF;
    }}
    QTreeWidget::item:hover {{
        background: {};
    }}
    QScrollArea#fdrLeftScroll {{
        border: none;
        background: {};
    }}
    QScrollArea#fdrLeftScroll > QWidget > QWidget {{
        background: {};
    }}
    QFrame#fdrCreateContainer {{
        background: transparent;
        border: 1px solid #3A3D46;
        border-radius: {}px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: {}px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: #4A4F5B;
        border-radius: {}px;
        min-height: {}px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #5A6170;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: {}px;
        margin: 0px;
    }}
    QScrollBar::handle:horizontal {{
        background: #4A4F5B;
        border-radius: {}px;
        min-width: {}px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: #5A6170;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: none;
    }}
    """.format(bg_color, text_color, max(11, _px(12)), text_color, _px(8), _px(12), _px(8), text_color, _px(10), _px(4), btn_color, border_color, _px(8), _px(4), _px(10), btn_h, text_color, btn_hover, btn_pressed, bg_darker, border_color, _px(6), _px(3), _px(6), ctrl_h, text_color, accent_color, _px(20), accent_color, bg_darker, text_color, accent_color, _px(6), text_color, _px(14), _px(14), _px(7), border_color, accent_color, accent_color, bg_darker, border_color, _px(6), text_color, _px(4), accent_color, btn_hover, bg_color, bg_color, _px(8), _px(12), _px(6), _px(24), _px(12), _px(6), _px(24))
    window.setStyleSheet(stylesheet)

    # Main layout
    main_layout = QtWidgets.QHBoxLayout(window)
    main_layout.setContentsMargins(_px(8), _px(8), _px(8), _px(8))
    main_layout.setSpacing(_px(8))

    # ===== LEFT PANEL =====
    LEFT_MIN_W = _px(380)
    RIGHT_MIN_W = _px(440)
    FIELD_W = _px(160)
    LABEL_W = _px(80)

    left_widget = QtWidgets.QWidget()
    left_widget.setObjectName("fdrLeftPane")
    left_widget.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.MinimumExpanding)
    left_layout = QtWidgets.QVBoxLayout(left_widget)
    left_layout.setContentsMargins(0, 0, 0, 0)
    left_layout.setSpacing(_px(8))
    left_layout.setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)

    # Driver Group
    driver_group = QtWidgets.QGroupBox(_t("driver_frame"))
    driver_layout = QtWidgets.QVBoxLayout(driver_group)
    driver_layout.setSpacing(_px(6))

    # Driver node row
    node_layout = QtWidgets.QHBoxLayout()
    node_label = QtWidgets.QLabel(_t("driver_node") + ":")
    node_label.setFixedWidth(LABEL_W)
    node_layout.addWidget(node_label)
    window.driver_node_field = QtWidgets.QLineEdit()
    window.driver_node_field.setFixedWidth(FIELD_W)
    node_layout.addWidget(window.driver_node_field)
    btn_load = QtWidgets.QPushButton(_t("load_selected"))
    btn_load.setMinimumWidth(_px(76))
    btn_load.clicked.connect(lambda: _ui_load_driver_from_selection_qt(window))
    node_layout.addWidget(btn_load)
    btn_select = QtWidgets.QPushButton(_t("select_node"))
    btn_select.setMinimumWidth(_px(76))
    btn_select.clicked.connect(lambda: _ui_select_driver_node_qt(window))
    node_layout.addWidget(btn_select)
    node_layout.addStretch()
    driver_layout.addLayout(node_layout)

    # Driver attr row
    attr_layout = QtWidgets.QHBoxLayout()
    attr_label = QtWidgets.QLabel(_t("driver_attr") + ":")
    attr_label.setFixedWidth(LABEL_W)
    attr_layout.addWidget(attr_label)
    window.driver_attr_combo = QtWidgets.QComboBox()
    window.driver_attr_combo.addItems(list(_DRIVER_ATTR_OPTIONS))
    window.driver_attr_combo.setFixedWidth(FIELD_W)
    attr_layout.addWidget(window.driver_attr_combo)
    attr_layout.addStretch()
    driver_layout.addLayout(attr_layout)

    # Target value + frame range row
    value_layout = QtWidgets.QHBoxLayout()
    value_label = QtWidgets.QLabel(_t("target_value") + ":")
    value_label.setFixedWidth(LABEL_W)
    value_layout.addWidget(value_label)
    window.driver_sign_plus_btn = QtWidgets.QToolButton()
    window.driver_sign_plus_btn.setText("+")
    window.driver_sign_plus_btn.setCheckable(True)
    window.driver_sign_plus_btn.setChecked(True)
    window.driver_sign_plus_btn.setFixedSize(_px(24), ctrl_h)
    value_layout.addWidget(window.driver_sign_plus_btn)
    window.driver_sign_minus_btn = QtWidgets.QToolButton()
    window.driver_sign_minus_btn.setText("-")
    window.driver_sign_minus_btn.setCheckable(True)
    window.driver_sign_minus_btn.setFixedSize(_px(24), ctrl_h)
    value_layout.addWidget(window.driver_sign_minus_btn)
    window.driver_sign_group = QtWidgets.QButtonGroup(window)
    window.driver_sign_group.setExclusive(True)
    window.driver_sign_group.addButton(window.driver_sign_plus_btn)
    window.driver_sign_group.addButton(window.driver_sign_minus_btn)
    window.driver_value_spin = QtWidgets.QDoubleSpinBox()
    window.driver_value_spin.setObjectName("fdrDriverValueSpin")
    window.driver_value_spin.setDecimals(3)
    window.driver_value_spin.setRange(0.0, 999.0)
    window.driver_value_spin.setValue(1.0)
    window.driver_value_spin.setFixedWidth(_px(90))
    window.driver_value_spin.setMinimumHeight(ctrl_h)
    value_layout.addWidget(window.driver_value_spin)
    value_layout.addSpacing(_px(14))
    range_label = QtWidgets.QLabel(_t("frame_range") + ":")
    range_label.setFixedWidth(_px(80))
    value_layout.addWidget(range_label)
    window.frame_range_spin = QtWidgets.QSpinBox()
    window.frame_range_spin.setRange(1, 100000)
    window.frame_range_spin.setFixedWidth(_px(90))
    saved_range = _optvar_get_int(_FRAME_RANGE_OPT_VAR, 10)
    if saved_range < 1:
        saved_range = 10
    window.frame_range_spin.setValue(int(saved_range))
    value_layout.addWidget(window.frame_range_spin)
    value_layout.addStretch()
    driver_layout.addLayout(value_layout)

    # Drive parent row
    parent_layout = QtWidgets.QHBoxLayout()
    window.use_parent_check = QtWidgets.QCheckBox(_t("drive_parent"))
    window.use_parent_check.setChecked(True)
    window.use_parent_check.setMinimumWidth(_px(200))
    parent_layout.addWidget(window.use_parent_check)
    parent_levels_label = QtWidgets.QLabel(_t("parent_levels") + ":")
    parent_levels_label.setFixedWidth(_px(80))
    parent_layout.addWidget(parent_levels_label)
    window.parent_levels_spin = QtWidgets.QSpinBox()
    window.parent_levels_spin.setRange(1, 10)
    window.parent_levels_spin.setValue(1)
    window.parent_levels_spin.setMinimumWidth(_px(60))
    parent_layout.addWidget(window.parent_levels_spin)
    parent_layout.addStretch()
    driver_layout.addLayout(parent_layout)

    # Bake to parent row
    bake_layout = QtWidgets.QHBoxLayout()
    window.bake_to_parent_check = QtWidgets.QCheckBox(_t("bake_to_parent"))
    # Timeline edit (ADV-like) is the default workflow; bake-to-parent is a special case.
    window.bake_to_parent_check.setChecked(False)
    bake_layout.addWidget(window.bake_to_parent_check)
    bake_layout.addStretch()
    driver_layout.addLayout(bake_layout)

    left_layout.addWidget(driver_group)

    # Driven Channels Group
    driven_group = QtWidgets.QGroupBox(_t("driven_frame"))
    driven_layout = QtWidgets.QVBoxLayout(driven_group)
    driven_layout.setSpacing(_px(4))

    # Keep internal keys as real Maya plugs (translateX/rotateY/...), but display short labels.
    window.channel_checks = {}
    row_tr = QtWidgets.QHBoxLayout()
    row_tr.setSpacing(_px(8))
    row_s = QtWidgets.QHBoxLayout()
    row_s.setSpacing(_px(8))

    for plug_attr, label in (
        ("translateX", "tX"),
        ("translateY", "tY"),
        ("translateZ", "tZ"),
        ("rotateX", "rX"),
        ("rotateY", "rY"),
        ("rotateZ", "rZ"),
    ):
        cb = QtWidgets.QCheckBox(label)
        cb.setChecked(True)
        window.channel_checks[plug_attr] = cb
        row_tr.addWidget(cb)
    row_tr.addStretch()

    for plug_attr, label in (("scaleX", "sX"), ("scaleY", "sY"), ("scaleZ", "sZ")):
        cb = QtWidgets.QCheckBox(label)
        cb.setChecked(True)
        window.channel_checks[plug_attr] = cb
        row_s.addWidget(cb)
    row_s.addStretch()

    driven_layout.addLayout(row_tr)
    driven_layout.addLayout(row_s)

    left_layout.addWidget(driven_group)

    # Driven objects list (collapsible section)
    driven_targets_container = QtWidgets.QFrame()
    driven_targets_container.setObjectName("fdrCreateContainer")
    driven_targets_outer = QtWidgets.QVBoxLayout(driven_targets_container)
    driven_targets_outer.setContentsMargins(_px(8), _px(8), _px(8), _px(8))
    driven_targets_outer.setSpacing(_px(6))

    window.driven_targets_toggle_btn = QtWidgets.QToolButton()
    window.driven_targets_toggle_btn.setText(_t("driven_targets_frame"))
    window.driven_targets_toggle_btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
    window.driven_targets_toggle_btn.setArrowType(QtCore.Qt.DownArrow)
    window.driven_targets_toggle_btn.setCheckable(False)
    window.driven_targets_toggle_btn.setAutoRaise(True)
    window.driven_targets_toggle_btn.setFocusPolicy(QtCore.Qt.NoFocus)
    driven_targets_outer.addWidget(window.driven_targets_toggle_btn)

    driven_targets_body = QtWidgets.QWidget()
    driven_targets_layout = QtWidgets.QVBoxLayout(driven_targets_body)
    driven_targets_layout.setContentsMargins(0, 0, 0, 0)
    driven_targets_layout.setSpacing(_px(6))

    window.driven_list_widget = QtWidgets.QListWidget()
    try:
        window.driven_list_widget.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
    except Exception:
        pass
    window.driven_list_widget.setMinimumHeight(_px(120))
    driven_targets_layout.addWidget(window.driven_list_widget)

    driven_targets_btn_row1 = QtWidgets.QHBoxLayout()
    driven_targets_btn_row1.setSpacing(_px(6))
    btn_dt_add = QtWidgets.QPushButton(_t("driven_targets_add"))
    btn_dt_add.setMinimumHeight(btn_h)
    btn_dt_add.clicked.connect(lambda: _ui_driven_list_add_selected_qt(window))
    driven_targets_btn_row1.addWidget(btn_dt_add)
    btn_dt_remove = QtWidgets.QPushButton(_t("driven_targets_remove"))
    btn_dt_remove.setMinimumHeight(btn_h)
    btn_dt_remove.clicked.connect(lambda: _ui_driven_list_remove_selected_qt(window))
    driven_targets_btn_row1.addWidget(btn_dt_remove)
    driven_targets_layout.addLayout(driven_targets_btn_row1)

    driven_targets_btn_row2 = QtWidgets.QHBoxLayout()
    driven_targets_btn_row2.setSpacing(_px(6))
    btn_dt_select = QtWidgets.QPushButton(_t("driven_targets_select"))
    btn_dt_select.setMinimumHeight(btn_h)
    btn_dt_select.clicked.connect(lambda: _ui_driven_list_select_scene_qt(window))
    driven_targets_btn_row2.addWidget(btn_dt_select)
    btn_dt_clear = QtWidgets.QPushButton(_t("driven_targets_clear"))
    btn_dt_clear.setMinimumHeight(btn_h)
    btn_dt_clear.clicked.connect(lambda: _ui_driven_list_clear_qt(window))
    driven_targets_btn_row2.addWidget(btn_dt_clear)
    driven_targets_layout.addLayout(driven_targets_btn_row2)

    driven_targets_outer.addWidget(driven_targets_body)
    window._driven_targets_expanded = True

    def _set_driven_targets_expanded(expanded):
        state = bool(expanded)
        window._driven_targets_expanded = state
        driven_targets_body.setVisible(state)
        try:
            window.driven_targets_toggle_btn.setArrowType(QtCore.Qt.DownArrow if state else QtCore.Qt.RightArrow)
        except Exception:
            pass

    window.driven_targets_toggle_btn.clicked.connect(
        lambda: _set_driven_targets_expanded(not bool(getattr(window, "_driven_targets_expanded", True)))
    )
    _set_driven_targets_expanded(True)
    left_layout.addWidget(driven_targets_container)
    _ui_driven_list_load_qt(window)

    # Actions Group
    actions_group = QtWidgets.QGroupBox(_t("actions_frame"))
    actions_layout = QtWidgets.QVBoxLayout(actions_group)
    actions_layout.setSpacing(_px(8))

    # Main action buttons
    btn_row1 = QtWidgets.QHBoxLayout()
    btn_row1.setSpacing(_px(6))
    window.btn_enter_edit = QtWidgets.QPushButton(_t("enter_edit"))
    window.btn_enter_edit.setMinimumHeight(btn_main_h)
    window.btn_enter_edit.clicked.connect(lambda: _ui_enter_edit_qt(window))
    btn_row1.addWidget(window.btn_enter_edit)

    window.btn_commit = QtWidgets.QPushButton(_t("commit"))
    window.btn_commit.setMinimumHeight(btn_main_h)
    window.btn_commit.clicked.connect(lambda: _ui_commit_qt(window))
    btn_row1.addWidget(window.btn_commit)

    window.btn_cancel = QtWidgets.QPushButton(_t("cancel"))
    window.btn_cancel.setMinimumHeight(btn_main_h)
    window.btn_cancel.clicked.connect(lambda: _ui_cancel_qt(window))
    btn_row1.addWidget(window.btn_cancel)
    actions_layout.addLayout(btn_row1)

    # Write mode row
    mode_layout = QtWidgets.QHBoxLayout()
    mode_label = QtWidgets.QLabel(_t("write_mode") + ":")
    mode_label.setFixedWidth(_px(90))
    mode_layout.addWidget(mode_label)
    window.write_mode_combo = QtWidgets.QComboBox()
    window.write_mode_combo.addItems([_t("write_add"), _t("write_update")])
    window.write_mode_combo.setMinimumWidth(_px(250))
    saved_mode = _optvar_get_str(_WRITE_MODE_OPT_VAR, "update").lower()
    if saved_mode == "update":
        window.write_mode_combo.setCurrentIndex(1)
    else:
        window.write_mode_combo.setCurrentIndex(0)
    mode_layout.addWidget(window.write_mode_combo)
    mode_layout.addStretch()
    actions_layout.addLayout(mode_layout)

    left_layout.addWidget(actions_group)

    # Mirror Group
    mirror_group = QtWidgets.QGroupBox(_t("mirror_frame"))
    mirror_layout = QtWidgets.QVBoxLayout(mirror_group)
    mirror_layout.setSpacing(_px(6))

    mirror_row = QtWidgets.QHBoxLayout()
    mirror_dir_label = QtWidgets.QLabel(_t("mirror_dir") + ":")
    mirror_dir_label.setFixedWidth(_px(90))
    mirror_row.addWidget(mirror_dir_label)
    window.mirror_dir_combo = QtWidgets.QComboBox()
    # Avoid Unicode arrows; some Maya/Qt font fallbacks render them as garbled glyphs.
    window.mirror_dir_combo.addItems(["L->R", "R->L"])
    mirror_dir = _optvar_get_str(_MIRROR_DIR_OPT_VAR, "L2R").upper()
    window.mirror_dir_combo.setCurrentText("L->R" if mirror_dir == "L2R" else "R->L")
    window.mirror_dir_combo.setMinimumWidth(_px(100))
    mirror_row.addWidget(window.mirror_dir_combo)

    mirror_axis_label = QtWidgets.QLabel(_t("mirror_axis") + ":")
    mirror_axis_label.setFixedWidth(_px(80))
    mirror_row.addWidget(mirror_axis_label)
    window.mirror_axis_combo = QtWidgets.QComboBox()
    window.mirror_axis_combo.addItems(["X", "Y", "Z"])
    mirror_axis = _optvar_get_str(_MIRROR_AXIS_OPT_VAR, "X").upper()
    window.mirror_axis_combo.setCurrentText(mirror_axis if mirror_axis in ["X","Y","Z"] else "X")
    window.mirror_axis_combo.setMinimumWidth(_px(80))
    mirror_row.addWidget(window.mirror_axis_combo)
    mirror_row.addStretch()
    mirror_layout.addLayout(mirror_row)

    btn_mirror = QtWidgets.QPushButton(_t("mirror_apply"))
    btn_mirror.setMinimumHeight(btn_h)
    btn_mirror.clicked.connect(lambda: _ui_mirror_apply_qt(window))
    mirror_layout.addWidget(btn_mirror)

    left_layout.addWidget(mirror_group)

    # Create corrective joint/control (ADV-like Create)
    # Use a toolbutton-driven collapsible section instead of a checkable QGroupBox.
    # Some Maya/Qt builds render the checkable groupbox indicator with garbled glyphs.
    create_container = QtWidgets.QFrame()
    create_container.setObjectName("fdrCreateContainer")
    create_outer = QtWidgets.QVBoxLayout(create_container)
    create_outer.setContentsMargins(_px(8), _px(8), _px(8), _px(8))
    create_outer.setSpacing(_px(6))

    window.create_toggle_btn = QtWidgets.QToolButton()
    window.create_toggle_btn.setText(_t("create_frame"))
    window.create_toggle_btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
    window.create_toggle_btn.setArrowType(QtCore.Qt.RightArrow)
    window.create_toggle_btn.setCheckable(False)
    window.create_toggle_btn.setAutoRaise(True)
    window.create_toggle_btn.setFocusPolicy(QtCore.Qt.NoFocus)
    create_outer.addWidget(window.create_toggle_btn)

    create_body = QtWidgets.QWidget()
    create_layout = QtWidgets.QVBoxLayout(create_body)
    create_layout.setContentsMargins(0, 0, 0, 0)
    create_layout.setSpacing(_px(6))

    # Base name row
    create_base_row = QtWidgets.QHBoxLayout()
    create_base_label = QtWidgets.QLabel(_t("create_name") + ":")
    create_base_label.setFixedWidth(_px(90))
    create_base_row.addWidget(create_base_label)
    window.create_base_field = QtWidgets.QLineEdit()
    window.create_base_field.setMinimumWidth(_px(180))
    create_base_row.addWidget(window.create_base_field, 1)
    create_layout.addLayout(create_base_row)

    # Parent row
    create_parent_row = QtWidgets.QHBoxLayout()
    create_parent_label = QtWidgets.QLabel(_t("create_parent") + ":")
    create_parent_label.setFixedWidth(_px(90))
    create_parent_row.addWidget(create_parent_label)
    window.create_parent_field = QtWidgets.QLineEdit()
    window.create_parent_field.setMinimumWidth(_px(180))
    create_parent_row.addWidget(window.create_parent_field, 1)
    btn_create_load_parent = QtWidgets.QPushButton(_t("create_load_parent"))
    btn_create_load_parent.setMinimumWidth(_px(140))
    btn_create_load_parent.clicked.connect(lambda: _ui_create_load_parent_from_selection_qt(window))
    create_parent_row.addWidget(btn_create_load_parent)
    create_layout.addLayout(create_parent_row)

    # Radius row
    create_radius_row = QtWidgets.QHBoxLayout()
    create_radius_label = QtWidgets.QLabel(_t("create_radius") + ":")
    create_radius_label.setFixedWidth(_px(90))
    create_radius_row.addWidget(create_radius_label)
    window.create_radius_spin = QtWidgets.QDoubleSpinBox()
    window.create_radius_spin.setDecimals(3)
    window.create_radius_spin.setRange(0.001, 999.0)
    window.create_radius_spin.setValue(1.0)
    window.create_radius_spin.setMinimumWidth(_px(100))
    create_radius_row.addWidget(window.create_radius_spin)
    create_radius_row.addStretch()
    create_layout.addLayout(create_radius_row)

    # Create button
    btn_create = QtWidgets.QPushButton(_t("create_btn"))
    btn_create.setMinimumHeight(btn_h)
    btn_create.clicked.connect(lambda: _ui_create_corrective_qt(window))
    create_layout.addWidget(btn_create)

    create_outer.addWidget(create_body)
    create_body.setVisible(False)
    window._create_expanded = False

    def _update_left_panel_size():
        # Keep child widgets at natural height; let scroll area handle overflow.
        try:
            h = int(left_layout.sizeHint().height())
            if h < 1:
                h = 1
            left_widget.setMinimumHeight(h)
        except Exception:
            pass

    def _set_create_expanded(expanded):
        state = bool(expanded)
        window._create_expanded = state
        create_body.setVisible(state)
        try:
            window.create_toggle_btn.setArrowType(QtCore.Qt.DownArrow if state else QtCore.Qt.RightArrow)
        except Exception:
            pass
        _update_left_panel_size()

    def _on_create_clicked():
        _set_create_expanded(not bool(getattr(window, "_create_expanded", False)))

    window.create_toggle_btn.clicked.connect(_on_create_clicked)
    _set_create_expanded(False)
    left_layout.addWidget(create_container)

    # Language toggle button
    btn_lang = QtWidgets.QPushButton(_t("lang"))
    btn_lang.setMinimumHeight(btn_h)
    btn_lang.clicked.connect(lambda: _toggle_lang_qt(window))
    left_layout.addWidget(btn_lang)

    left_layout.addStretch()

    left_scroll = QtWidgets.QScrollArea()
    left_scroll.setObjectName("fdrLeftScroll")
    left_scroll.setWidgetResizable(True)
    left_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    left_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    left_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    left_scroll.setMinimumWidth(LEFT_MIN_W)
    left_scroll.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
    left_scroll.setWidget(left_widget)
    main_layout.addWidget(left_scroll, 43)
    _update_left_panel_size()

    # ===== RIGHT PANEL =====
    right_widget = QtWidgets.QWidget()
    right_widget.setMinimumWidth(RIGHT_MIN_W)
    right_widget.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
    right_layout = QtWidgets.QVBoxLayout(right_widget)
    right_layout.setContentsMargins(0, 0, 0, 0)
    right_layout.setSpacing(_px(8))

    # SDK List Group
    sdk_group = QtWidgets.QGroupBox(_t("sdk_list_frame"))
    sdk_layout = QtWidgets.QVBoxLayout(sdk_group)
    sdk_layout.setSpacing(_px(6))

    # Fold checkbox
    window.sdk_fold_check = QtWidgets.QCheckBox(_t("sdk_fold"))
    window.sdk_fold_check.setChecked(_sdk_fold_enabled())
    window.sdk_fold_check.stateChanged.connect(lambda: _ui_sdk_refresh_list_display_qt(window))
    sdk_layout.addWidget(window.sdk_fold_check)

    # SDK Tree
    window.sdk_tree = QtWidgets.QTreeWidget()
    window.sdk_tree.setHeaderHidden(True)
    window.sdk_tree.setMinimumHeight(_px(400))
    try:
        window.sdk_tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
    except Exception:
        pass
    sdk_layout.addWidget(window.sdk_tree)

    # SDK buttons
    btn_row_sdk1 = QtWidgets.QHBoxLayout()
    btn_row_sdk1.setSpacing(_px(6))
    btn_scan = QtWidgets.QPushButton(_t("scan_sdk"))
    btn_scan.setMinimumHeight(btn_h)
    btn_scan.clicked.connect(lambda: _ui_scan_sdk_qt(window))
    btn_row_sdk1.addWidget(btn_scan)

    btn_edit_sel = QtWidgets.QPushButton(_t("sdk_edit_selected"))
    btn_edit_sel.setMinimumHeight(btn_h)
    btn_edit_sel.clicked.connect(lambda: _ui_sdk_edit_selected_qt(window))
    btn_row_sdk1.addWidget(btn_edit_sel)

    btn_edit_driver = QtWidgets.QPushButton(_t("sdk_edit_driver"))
    btn_edit_driver.setMinimumHeight(btn_h)
    btn_edit_driver.clicked.connect(lambda: _ui_sdk_edit_driver_qt(window))
    btn_row_sdk1.addWidget(btn_edit_driver)
    sdk_layout.addLayout(btn_row_sdk1)

    btn_row_sdk2 = QtWidgets.QHBoxLayout()
    btn_row_sdk2.setSpacing(_px(6))
    btn_delete = QtWidgets.QPushButton(_t("sdk_delete_selected"))
    btn_delete.setMinimumHeight(btn_h)
    btn_delete.clicked.connect(lambda: _ui_sdk_delete_selected_qt(window))
    btn_row_sdk2.addWidget(btn_delete)

    btn_select_driver = QtWidgets.QPushButton(_t("sdk_select_driver"))
    btn_select_driver.setMinimumHeight(btn_h)
    btn_select_driver.clicked.connect(lambda: _ui_sdk_select_driver_qt(window))
    btn_row_sdk2.addWidget(btn_select_driver)
    sdk_layout.addLayout(btn_row_sdk2)

    right_layout.addWidget(sdk_group)

    main_layout.addWidget(right_widget, 57)

    # Store window reference
    window._qt_window = window

    window.show()


# ===== Qt UI Callback Functions =====


def commit_edit(write_mode= "add"):
    """Qt UI compatibility wrapper: commit current session."""
    commit(write_mode=write_mode)


def cancel_edit():
    """Qt UI compatibility wrapper: cancel/restore current session."""
    cancel()


def enter_edit_existing_layer_batch(
    driver_plug,
    driver_target,
    nodes,
    channels,
    use_parent = True,
    parent_levels = 1,
    bake_to_parent = False,
):
    """Qt UI helper: batch edit by driver using current selection as scope.

    This mirrors the Maya-UI behavior: find all existing SDK layers matching the driver
    across the selected nodes (or their parents), then enter editDriver / editDriverBakeToParent.
    """

    nodes = _normalize_transform_nodes(nodes)
    channels = list(channels or [])
    if not nodes or not channels:
        _warn(_t("warn_select_driven"))
        return

    # Match the actual commit target behavior.
    if bake_to_parent and not use_parent:
        _warn(_t("warn_bake_needs_parent"))
        return
    auto_bake = _should_auto_bake_to_parent(nodes, use_parent=use_parent, bake_to_parent=bake_to_parent)
    if auto_bake:
        bake_to_parent = True
        _warn(_t("warn_auto_bake_parent_mode"))

    driven_nodes = list(nodes)
    parent_levels = max(int(parent_levels), 1)
    if bake_to_parent and use_parent:
        mapping = _parent_map(nodes, parent_levels)
        driven_nodes = list(dict.fromkeys(mapping.values()))
    elif use_parent:
        driven_nodes = _parent_levels(nodes, parent_levels)

    # Scan for SDK items in the chosen scope.
    try:
        _report, temp_items = scan_sdk_detailed(driven_nodes, channels)
    except Exception:
        temp_items = []

    items = []
    try:
        dt = float(driver_target)
    except Exception:
        dt = 1.0

    for it in (temp_items or []):
        if not _plug_matches(str(it.get("driverPlug") or ""), str(driver_plug or "")):
            continue
        try:
            t = float(it.get("driverTarget") or 0.0)
        except Exception:
            t = 0.0
        if abs(t - dt) <= float(_DRIVER_TARGET_MATCH_EPS):
            items.append(it)

    if not items:
        # Fallback: same driver plug even if target inference mismatched.
        items = [
            it
            for it in (temp_items or [])
            if _plug_matches(str(it.get("driverPlug") or ""), str(driver_plug or ""))
        ]

    if not items:
        _warn(_t("warn_sdk_no_driver_items"))
        return

    frame_range = _optvar_get_int(_FRAME_RANGE_OPT_VAR, 10)
    frame_range = max(int(frame_range), 1)

    if bake_to_parent and use_parent:
        enter_edit_timeline_bake_to_parent(
            driver_plug=driver_plug,
            driver_target_value=dt,
            frame_range=frame_range,
            controller_nodes=nodes,
            parent_levels=parent_levels,
            channels=channels,
        )
    else:
        target_nodes = list(nodes)
        if use_parent:
            target_nodes = _parent_levels(nodes, parent_levels)
            if not target_nodes:
                _warn(_t("warn_select_driven"))
                return

        enter_edit_timeline(
            driver_plug=driver_plug,
            driver_target_value=dt,
            frame_range=frame_range,
            driven_nodes=target_nodes,
            channels=channels,
            cleanup_extra_nodes=nodes,
        )
    _restore_selection_safe(nodes)

    # Restrict to scanned SDK scope and force "overwrite existing layer" preference.
    _mark_active_timeline_session_for_driver_batch(items)

def _ui_load_driver_from_selection_qt(window):
    """Load driver node from selection (Qt version)."""
    sel = cmds.ls(sl=True, type="transform") or []
    if not sel:
        _warn(_t("warn_select_driver"))
        return
    window.driver_node_field.setText(sel[0])
    _ui_refresh_driver_attr_combo_qt(window, sel[0])
    print("// Loaded driver node: {}".format(sel[0]))


def _ui_refresh_driver_attr_combo_qt(window, node, prefer_attr= None):
    try:
        attrs = _driver_attr_candidates(node)
    except Exception:
        attrs = list(_DRIVER_ATTR_OPTIONS)
    window.driver_attr_combo.clear()
    window.driver_attr_combo.addItems(attrs)
    if attrs:
        pick = prefer_attr if (prefer_attr in attrs) else attrs[0]
        try:
            window.driver_attr_combo.setCurrentText(pick)
        except Exception:
            pass


def _ui_select_driver_node_qt(window):
    """Select driver node (Qt version)."""
    node = window.driver_node_field.text().strip()
    if not node:
        _warn(_t("warn_select_driver"))
        return
    if not cmds.objExists(node):
        _warn(_t("warn_driver_node_not_found").format(node=node))
        return
    try:
        cmds.select(node, r=True)
        print("// Selected driver node: {}".format(node))
    except Exception:
        pass


def _ui_driven_list_items_qt(window):
    lw = getattr(window, "driven_list_widget", None)
    if lw is None:
        return []
    try:
        items = [lw.item(i).text() for i in range(lw.count())]
    except Exception:
        items = []
    return _normalize_transform_nodes(items)


def _ui_driven_list_set_items_qt(window, nodes, selected= None):
    lw = getattr(window, "driven_list_widget", None)
    clean = _normalize_transform_nodes(nodes)
    if lw is None:
        _driven_targets_save(clean)
        return
    try:
        lw.blockSignals(True)
        lw.clear()
        for n in clean:
            lw.addItem(n)
        if selected:
            selected_set = set(_normalize_transform_nodes(selected))
            for i in range(lw.count()):
                it = lw.item(i)
                if it and (it.text() in selected_set):
                    it.setSelected(True)
        lw.blockSignals(False)
    except Exception:
        pass
    _driven_targets_save(clean)


def _ui_driven_list_load_qt(window):
    _ui_driven_list_set_items_qt(window, _driven_targets_load())


def _ui_driven_list_add_selected_qt(window):
    sel = _normalize_transform_nodes(cmds.ls(sl=True, type="transform") or [])
    if not sel:
        _warn(_t("warn_select_driven"))
        return
    cur = _ui_driven_list_items_qt(window)
    merged = list(cur)
    existing = set(cur)
    for n in sel:
        if n not in existing:
            merged.append(n)
            existing.add(n)
    _ui_driven_list_set_items_qt(window, merged, selected=sel)


def _ui_driven_list_remove_selected_qt(window):
    lw = getattr(window, "driven_list_widget", None)
    if lw is None:
        return
    chosen = []
    try:
        chosen = [it.text() for it in (lw.selectedItems() or []) if it]
    except Exception:
        chosen = []
    chosen_set = set(_normalize_transform_nodes(chosen))
    if not chosen_set:
        return
    keep = [n for n in _ui_driven_list_items_qt(window) if n not in chosen_set]
    _ui_driven_list_set_items_qt(window, keep)


def _ui_driven_list_clear_qt(window):
    _ui_driven_list_set_items_qt(window, [])


def _ui_driven_list_select_scene_qt(window):
    lw = getattr(window, "driven_list_widget", None)
    listed = _ui_driven_list_items_qt(window)
    if not listed:
        _warn(_t("warn_driven_list_empty"))
        return
    chosen = []
    if lw is not None:
        try:
            chosen = [it.text() for it in (lw.selectedItems() or []) if it]
        except Exception:
            chosen = []
    to_select = _normalize_transform_nodes(chosen) or listed
    if not to_select:
        _warn(_t("warn_driven_list_empty"))
        return
    try:
        cmds.select(to_select, r=True)
    except Exception:
        pass


def _ui_get_driven_nodes_qt(window):
    listed = _ui_driven_list_items_qt(window)
    if listed:
        return listed
    return _normalize_transform_nodes(cmds.ls(sl=True, type="transform") or [])


def _ui_get_driver_value_qt(window):
    """Return signed target value from Qt sign buttons + magnitude spinbox."""
    try:
        mag = float(window.driver_value_spin.value())
    except Exception:
        mag = 1.0
    mag = abs(float(mag))
    try:
        if bool(window.driver_sign_minus_btn.isChecked()):
            return -mag
    except Exception:
        pass
    return mag


def _ui_set_driver_value_with_sign_qt(window, value):
    """Write signed value into Qt UI as [sign buttons] + [positive magnitude]."""
    try:
        v = float(value)
    except Exception:
        v = 1.0
    sign_negative = bool(v < 0.0)
    mag = abs(float(v))
    try:
        window.driver_value_spin.setValue(mag)
    except Exception:
        pass
    try:
        if sign_negative:
            window.driver_sign_minus_btn.setChecked(True)
        else:
            window.driver_sign_plus_btn.setChecked(True)
    except Exception:
        pass


def _ui_enter_edit_qt(window):
    """Enter edit mode (Qt version)."""
    driver_node = window.driver_node_field.text().strip()
    driver_attr = window.driver_attr_combo.currentText()
    driver_value = _ui_get_driver_value_qt(window)
    frame_range = 10
    try:
        frame_range = int(window.frame_range_spin.value())
    except Exception:
        frame_range = 10
    frame_range = max(int(frame_range), 1)
    try:
        cmds.optionVar(iv=(_FRAME_RANGE_OPT_VAR, int(frame_range)))
    except Exception:
        pass
    use_parent = window.use_parent_check.isChecked()
    parent_levels = window.parent_levels_spin.value()
    bake_to_parent = window.bake_to_parent_check.isChecked()

    channels = [ch for ch, cb in window.channel_checks.items() if cb.isChecked()]

    if not driver_node:
        _warn(_t("warn_select_driver"))
        return

    driver_plug = "{}.{}".format(driver_node, driver_attr)
    selected_nodes = _ui_get_driven_nodes_qt(window)
    if not selected_nodes:
        _warn(_t("warn_driven_list_empty"))
        return

    # Avoid accidentally including the driver node.
    selected_nodes = [n for n in selected_nodes if n != driver_node]
    if not selected_nodes:
        _warn(_t("warn_select_driven"))
        return

    if bake_to_parent and not use_parent:
        _warn(_t("warn_bake_needs_parent"))
        return
    auto_bake = _should_auto_bake_to_parent(selected_nodes, use_parent=use_parent, bake_to_parent=bake_to_parent)
    if auto_bake:
        bake_to_parent = True
        _warn(_t("warn_auto_bake_parent_mode"))
        try:
            window.bake_to_parent_check.setChecked(True)
        except Exception:
            pass

    # Bake-to-parent timeline: edit controllers, commit writes to parents.
    if bake_to_parent and use_parent:
        enter_edit_timeline_bake_to_parent(
            driver_plug,
            driver_value,
            frame_range,
            selected_nodes,
            int(parent_levels),
            channels,
        )
        _restore_selection_safe(selected_nodes)
        return

    driven_nodes = list(selected_nodes)
    if use_parent:
        driven_nodes = _parent_levels(driven_nodes, int(parent_levels))
        if not driven_nodes:
            _warn(_t("warn_select_driven"))
            return
    else:
        for n in driven_nodes:
            if _is_controller_transform(n):
                _warn(_t("warn_controller_selected").format(node=n))
                break

    enter_edit_timeline(
        driver_plug,
        driver_value,
        frame_range,
        driven_nodes,
        channels,
        cleanup_extra_nodes=selected_nodes,
    )
    _restore_selection_safe(selected_nodes)


def _ui_commit_qt(window):
    """Commit changes (Qt version)."""
    write_mode_text = window.write_mode_combo.currentText()
    write_mode = "update" if _t("write_update") in write_mode_text else "add"
    commit_edit(write_mode=write_mode)


def _ui_cancel_qt(window):
    """Cancel edit mode (Qt version)."""
    cancel_edit()


def _ui_mirror_apply_qt(window):
    """Apply mirror (Qt version)."""
    mirror_dir = window.mirror_dir_combo.currentText()
    mirror_axis = window.mirror_axis_combo.currentText()
    # Accept both ASCII and legacy Unicode arrow forms.
    direction = "L2R" if ("L->R" in mirror_dir or "L\u2192R" in mirror_dir) else "R2L"
    sel = cmds.ls(sl=True, type="transform") or []
    channels = [ch for ch, cb in window.channel_checks.items() if cb.isChecked()]
    mirror_apply(nodes=sel, channels=channels, axis=mirror_axis, direction=direction)


def _ui_create_load_parent_from_selection_qt(window):
    """Load create-parent field from current selection (Qt version)."""
    sel = cmds.ls(sl=True, type="transform") or []
    if not sel:
        _warn(_t("warn_select_driver"))
        return
    try:
        window.create_parent_field.setText(sel[0])
    except Exception:
        pass


def _ui_create_corrective_qt(window):
    """Create corrective joint + controller at selection (Qt version)."""
    base = ""
    parent = ""
    radius = 1.0
    try:
        base = (window.create_base_field.text() or "").strip()
    except Exception:
        base = ""
    try:
        parent = (window.create_parent_field.text() or "").strip()
    except Exception:
        parent = ""
    try:
        radius = float(window.create_radius_spin.value())
    except Exception:
        radius = 1.0

    created = create_corrective_joint_and_control(base, parent or None, radius=radius)
    if created:
        try:
            cmds.select([created.get("ctrl"), created.get("joint")], r=True)
        except Exception:
            pass


def _toggle_lang_qt(window):
    """Toggle language (Qt version)."""
    cur = _get_lang()
    _set_lang("en" if cur == "zh" else "zh")
    window.close()
    show_ui_qt()


def _ui_sdk_refresh_list_display_qt(window):
    """Refresh SDK list display (Qt version)."""
    global _SDK_TREE_LEAF_MAP, _SDK_TREE_ROOT_MAP

    folded = window.sdk_fold_check.isChecked()
    try:
        cmds.optionVar(iv=(_SDK_FOLD_OPT_VAR, int(folded)))
    except Exception:
        pass

    window.sdk_tree.clear()
    _SDK_TREE_LEAF_MAP.clear()
    _SDK_TREE_ROOT_MAP.clear()

    if not _SDK_SCAN_ITEMS:
        return

    try:
        from PySide2.QtWidgets import QTreeWidgetItem
    except ImportError:
        try:
            from PySide6.QtWidgets import QTreeWidgetItem
        except ImportError:
            return

    groups = {}
    for item in _SDK_SCAN_ITEMS:
        driven_plug = str(item.get("drivenPlug") or "")
        driver_plug = str(item.get("driverPlug") or "")
        driven_node = driven_plug.split(".", 1)[0] if "." in driven_plug else driven_plug
        driver_node = driver_plug.split(".", 1)[0] if "." in driver_plug else ""
        key = (driven_node, driver_node)
        if key not in groups:
            groups[key] = []
        groups[key].append(item)

    for (driven_node, driver_node), items in sorted(groups.items()):
        root_label = _sdk_tree_root_label(driven_node, driver_node)
        root_item = QTreeWidgetItem([root_label])
        window.sdk_tree.addTopLevelItem(root_item)

        # Store root info
        root_id = id(root_item)
        _SDK_TREE_ROOT_MAP[str(root_id)] = {
            "drivenNode": driven_node,
            "driverNode": driver_node,
            "driverPlug": items[0].get("driverPlug") if items else "",
            "driverTarget": items[0].get("driverTarget") if items else 1.0,
        }
        root_item.setData(0, 32, root_id)

        for item in items:
            leaf_label = _sdk_tree_leaf_label(item, folded)
            leaf_item = QTreeWidgetItem([leaf_label])
            root_item.addChild(leaf_item)
            leaf_id = id(leaf_item)
            _SDK_TREE_LEAF_MAP[str(leaf_id)] = item
            leaf_item.setData(0, 32, leaf_id)

        # Default folded: show groups collapsed after scan/refresh.
        root_item.setExpanded(False)


def _ui_scan_sdk_qt(window):
    """Scan SDK (Qt version)."""
    driven_nodes = _ui_get_driven_nodes_qt(window)
    if not driven_nodes:
        _warn(_t("warn_driven_list_empty"))
        return

    channels = [ch for ch, cb in window.channel_checks.items() if cb.isChecked()]
    if not channels:
        _warn(_t("warn_no_driven_plugs"))
        return

    # Avoid accidentally including the driver node
    driver_node_text = window.driver_node_field.text().strip()
    if driver_node_text:
        driven_nodes = [n for n in driven_nodes if n != driver_node_text]

    use_parent = window.use_parent_check.isChecked()
    parent_levels = window.parent_levels_spin.value()
    bake_to_parent = window.bake_to_parent_check.isChecked()

    # Match the actual commit target behavior
    if bake_to_parent and not use_parent:
        _warn(_t("warn_bake_needs_parent"))
        return
    if bake_to_parent and use_parent:
        mapping = _parent_map(driven_nodes, parent_levels)
        driven_nodes = list(dict.fromkeys(mapping.values()))
    elif use_parent:
        driven_nodes = _parent_levels(driven_nodes, parent_levels)

    if not driven_nodes:
        _warn(_t("warn_select_driven"))
        return

    # Use scan_sdk_detailed to get both report and items
    global _SDK_SCAN_ITEMS, _SDK_SCAN_ITEMS_VIEW
    report, items = scan_sdk_detailed(driven_nodes=driven_nodes, channels=channels)

    if not report:
        return

    _SDK_SCAN_ITEMS = list(items or [])

    # Sort so same driver groups together
    def _k(it):
        dn = str(it.get("driverNode") or "")
        dp = str(it.get("driverPlug") or "")
        dr = str(it.get("drivenPlug") or "")
        bi = it.get("bwIndex")
        bi = int(bi) if bi is not None else 10**9
        return (dn, dp, dr, bi)

    _SDK_SCAN_ITEMS.sort(key=_k)
    _SDK_SCAN_ITEMS_VIEW = list(_SDK_SCAN_ITEMS)

    _ui_sdk_refresh_list_display_qt(window)

    print("// Scanned {} SDK layers".format(len(_SDK_SCAN_ITEMS)))
    if report:
        print(report)


def _ui_sdk_get_selected_item_qt(window):
    """Get selected SDK item from Qt tree."""
    selected = window.sdk_tree.selectedItems()
    if not selected:
        return None
    item = selected[0]
    leaf_id = item.data(0, 32)
    if leaf_id is None:
        return None
    return _SDK_TREE_LEAF_MAP.get(str(leaf_id))


def _ui_sdk_get_selected_items_qt(window):
    """Return selected SDK items from the Qt tree (multi-select)."""
    items = []
    try:
        selected = window.sdk_tree.selectedItems() or []
    except Exception:
        selected = []

    for item in selected:
        sid = item.data(0, 32)
        if sid is None:
            continue
        sid = str(sid)
        if sid in (_SDK_TREE_LEAF_MAP or {}):
            items.append(_SDK_TREE_LEAF_MAP[sid])
            continue
        if sid in (_SDK_TREE_ROOT_MAP or {}):
            root = _SDK_TREE_ROOT_MAP[sid] or {}
            driven_node = str(root.get("drivenNode") or "")
            driver_node = str(root.get("driverNode") or "")
            items.extend(_sdk_items_for_root(driven_node, driver_node, _SDK_SCAN_ITEMS_VIEW))

    return _dedupe_sdk_items(items)


def _ui_sdk_edit_selected_qt(window):
    """Edit selected SDK (Qt version)."""
    item = _ui_sdk_get_selected_item_qt(window)
    if not item:
        _warn(_t("warn_sdk_item_not_selected"))
        return

    driver_plug = str(item.get("driverPlug") or "")
    driver_target = float(item.get("driverTarget") or 1.0)

    # Update Qt UI fields
    if driver_plug and "." in driver_plug:
        driver_node, driver_attr = driver_plug.split(".", 1)
        window.driver_node_field.setText(driver_node)
        _ui_refresh_driver_attr_combo_qt(window, driver_node, prefer_attr=driver_attr)
        _ui_set_driver_value_with_sign_qt(window, driver_target)

    enter_edit_existing_layer(item)


def _ui_sdk_edit_driver_qt(window):
    """Edit by driver (Qt version)."""
    # Allow selecting either a leaf (single channel) or a root (group).
    item = _ui_sdk_get_selected_item_qt(window)
    root_info = None
    if not item:
        try:
            selected = window.sdk_tree.selectedItems() or []
            if selected:
                sid = selected[0].data(0, 32)
                if sid is not None:
                    root_info = (_SDK_TREE_ROOT_MAP or {}).get(str(sid))
        except Exception:
            root_info = None
    if not item and not root_info:
        _warn(_t("warn_sdk_item_not_selected"))
        return

    driver_plug = str((item or root_info or {}).get("driverPlug") or "")
    try:
        driver_target = float((item or root_info or {}).get("driverTarget") or 1.0)
    except Exception:
        driver_target = 1.0

    # Update Qt UI fields
    if driver_plug and "." in driver_plug:
        driver_node, driver_attr = driver_plug.split(".", 1)
        window.driver_node_field.setText(driver_node)
        _ui_refresh_driver_attr_combo_qt(window, driver_node, prefer_attr=driver_attr)
        _ui_set_driver_value_with_sign_qt(window, driver_target)

    channels = [ch for ch, cb in window.channel_checks.items() if cb.isChecked()]
    try:
        frame_range = int(window.frame_range_spin.value())
    except Exception:
        frame_range = _optvar_get_int(_FRAME_RANGE_OPT_VAR, 10)
    frame_range = max(int(frame_range), 1)
    try:
        cmds.optionVar(iv=(_FRAME_RANGE_OPT_VAR, int(frame_range)))
    except Exception:
        pass
    sel = _ui_get_driven_nodes_qt(window)
    if not sel:
        _warn(_t("warn_driven_list_empty"))
        return

    enter_edit_existing_layer_batch(
        driver_plug=driver_plug,
        driver_target=driver_target,
        nodes=sel,
        channels=channels,
        use_parent=bool(window.use_parent_check.isChecked()),
        parent_levels=int(window.parent_levels_spin.value()),
        bake_to_parent=bool(window.bake_to_parent_check.isChecked()),
    )


def _ui_sdk_delete_selected_qt(window):
    """Delete selected SDK (Qt version)."""
    items = _ui_sdk_get_selected_items_qt(window)
    if not items:
        _warn(_t("warn_sdk_item_not_selected"))
        return

    try:
        from PySide2.QtWidgets import QMessageBox
    except ImportError:
        try:
            from PySide6.QtWidgets import QMessageBox
        except ImportError:
            return

    if len(items) == 1:
        one = items[0]
        curve = str(one.get("curve") or "")
        driven_plug = str(one.get("drivenPlug") or "")
        driver_plug = str(one.get("driverPlug") or "")
        desc = "Curve: {}\nDriven: {}\nDriver: {}".format(curve, driven_plug, driver_plug)
        msg = _t("confirm_delete_msg").format(desc=desc)
    else:
        msg = _t("confirm_delete_multi_msg").format(count=len(items))

    reply = QMessageBox.question(
        window,
        _t("confirm_delete_title"),
        msg,
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No
    )

    if reply == QMessageBox.Yes:
        ok_any = False
        with _undo_chunk("FDR Delete SDK Layers"):
            for it in items:
                if delete_sdk_layer(it):
                    ok_any = True
        if ok_any:
            _ui_scan_sdk_qt(window)
        else:
            _warn(_t("warn_sdk_item_invalid"))


def _ui_sdk_select_driver_qt(window):
    """Select driver node (Qt version)."""
    item = _ui_sdk_get_selected_item_qt(window)
    root_info = None
    if not item:
        try:
            selected = window.sdk_tree.selectedItems() or []
            if selected:
                sid = selected[0].data(0, 32)
                if sid is not None:
                    root_info = (_SDK_TREE_ROOT_MAP or {}).get(str(sid))
        except Exception:
            root_info = None
    if not item and not root_info:
        _warn(_t("warn_sdk_item_not_selected"))
        return

    driver_plug = str((item or root_info or {}).get("driverPlug") or "")
    driver_node = driver_plug.split(".", 1)[0] if "." in driver_plug else driver_plug
    if driver_node and cmds.objExists(driver_node):
        try:
            cmds.select(driver_node, r=True)
            print("// Selected driver: {}".format(driver_node))
        except Exception:
            _warn("Cannot select: {}".format(driver_node))
    else:
        _warn(_t("warn_driver_node_not_found").format(node=driver_node))


def show_ui():
    """Show UI - prefer Qt version if available."""
    try:
        return show_ui_qt()
    except Exception as e:
        import traceback
        print("Qt UI failed, falling back to cmds UI: {}".format(str(e)))
        print(traceback.format_exc())
        return show_ui_cmds()


def show_ui_cmds():
    """Show the cmds-based UI (fallback)."""
    if cmds.window(_WINDOW, exists=True):
        cmds.deleteUI(_WINDOW)

    def _ui_scale_cmds():
        try:
            s = float(cmds.mayaDpiSetting(q=True, realScaleValue=True))
            if s > 0.0:
                return max(1.0, min(2.0, s))
        except Exception:
            pass
        return 1.0

    _ui_scale = _ui_scale_cmds()

    def _px(v):
        try:
            return max(1, int(round(float(v) * _ui_scale)))
        except Exception:
            return 1

    # Fixed-size window; left pane fixed width, right pane takes remainder.
    WIN_W = _px(900)
    LEFT_W = _px(360)
    LW = _px(80)    # label column width (px) for aligned rows
    FW = _px(120)   # default field width
    BTN_H_22 = _px(22)
    BTN_H_24 = _px(24)
    BTN_H_26 = _px(26)
    BTN_H_28 = _px(28)
    FIELD_W_70 = _px(70)
    FIELD_W_80 = _px(80)
    FIELD_W_100 = _px(100)
    FIELD_W_120 = _px(120)
    FIELD_W_180 = _px(180)
    FIELD_W_200 = _px(200)
    FIELD_W_50 = _px(50)
    FIELD_W_60 = _px(60)
    TREE_H = _px(440)
    cmds.window(_WINDOW, title=_t("title"), sizeable=True, mnb=True, mxb=True, w=WIN_W, h=_px(620))
    form = cmds.formLayout(nd=100)

    # 鈹€鈹€ Left pane: fixed-width, non-stretching column 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
    left_col = cmds.columnLayout("fdr_leftCol", adj=False, w=LEFT_W, rs=0)

    # Driver frame
    cmds.frameLayout(label=_t("driver_frame"), collapsable=False, mw=8, mh=6, w=LEFT_W)
    cmds.columnLayout(adj=False, rs=3)

    # Driver node row: label + short field + two buttons
    cmds.rowLayout(nc=4, cw4=(LW, FIELD_W_100, _px(68), _px(68)), ct4=("left","left","left","left"), cl4=("center","center","center","center"))
    cmds.text(l=_t("driver_node"), al="right", w=LW)
    cmds.textField("fdr_driverNode", tx="", w=FIELD_W_100)
    cmds.button(l=_t("load_selected"), h=BTN_H_22, w=_px(68), c=_ui_load_driver_from_selection)
    cmds.button(l=_t("select_node"), h=BTN_H_22, w=_px(68), c=_ui_select_driver_node)
    cmds.setParent("..")

    # Driver attr row
    cmds.rowLayout(nc=2, cw2=(LW, FIELD_W_180), ct2=("left","left"))
    cmds.text(l=_t("driver_attr"), al="right", w=LW)
    cmds.optionMenu("fdr_driverAttr", w=FIELD_W_180)
    for a in _DRIVER_ATTR_OPTIONS:
        cmds.menuItem(l=a)
    cmds.setParent("..")

    # Target value row
    _SIGN_W = _px(24)
    cmds.rowLayout(
        nc=5,
        cw5=(LW, _SIGN_W, _SIGN_W, FIELD_W_70, FIELD_W_100),
        ct5=("left", "left", "left", "left", "left"),
    )
    cmds.text(l=_t("target_value"), al="right", w=LW)
    cmds.radioCollection("fdr_driverSignCollection")
    cmds.radioButton("fdr_driverSignPlus", l="+", sl=True, w=_SIGN_W)
    cmds.radioButton("fdr_driverSignMinus", l="-", w=_SIGN_W)
    cmds.floatField("fdr_driverValue", v=1.0, min=0.0, pre=3, w=FIELD_W_70)
    cmds.text(l=_t("target_hint"), al="left")
    cmds.setParent("..")

    # Frame range row (timeline edit)
    saved_range = _optvar_get_int(_FRAME_RANGE_OPT_VAR, 10)
    if saved_range < 1:
        saved_range = 10
    cmds.rowLayout(nc=3, cw3=(LW, FIELD_W_70, FIELD_W_100), ct3=("left", "left", "left"))
    cmds.text(l=_t("frame_range"), al="right", w=LW)
    cmds.intField("fdr_frameRange", v=int(saved_range), min=1, w=FIELD_W_70)
    cmds.text(l=_t("frame_range_hint"), al="left")
    cmds.setParent("..")

    # Drive parent row
    cmds.rowLayout(nc=3, cw3=(LW, FIELD_W_120, FIELD_W_50), ct3=("left","left","left"))
    cmds.text(l="", w=LW)
    cmds.checkBox("fdr_useParent", l=_t("drive_parent"), v=True)
    cmds.intField("fdr_parentLevels", v=1, min=1, w=FIELD_W_50)
    cmds.setParent("..")

    # Bake to parent row
    cmds.rowLayout(nc=2, cw2=(LW, FIELD_W_200), ct2=("left","left"))
    cmds.text(l="", w=LW)
    # Timeline edit (ADV-like) is the default workflow; bake-to-parent is a special case.
    cmds.checkBox("fdr_bakeToParent", l=_t("bake_to_parent"), v=False)
    cmds.setParent("..")

    cmds.setParent("..") # columnLayout
    cmds.setParent("..") # frameLayout

    # Driven channels frame
    cmds.frameLayout(label=_t("driven_frame"), collapsable=False, mw=8, mh=6, w=LEFT_W)
    _ch_row = cmds.rowLayout(nc=9)
    for _ci in range(1, 10):
        cmds.rowLayout(_ch_row, e=True, columnWidth=(_ci, _px(34)))
    cmds.checkBox("fdr_tX", l="tX", v=True)
    cmds.checkBox("fdr_tY", l="tY", v=True)
    cmds.checkBox("fdr_tZ", l="tZ", v=True)
    cmds.checkBox("fdr_rX", l="rX", v=True)
    cmds.checkBox("fdr_rY", l="rY", v=True)
    cmds.checkBox("fdr_rZ", l="rZ", v=True)
    cmds.checkBox("fdr_sX", l="sX", v=True)
    cmds.checkBox("fdr_sY", l="sY", v=True)
    cmds.checkBox("fdr_sZ", l="sZ", v=True)
    cmds.setParent("..")
    cmds.setParent("..")

    # Driven objects list (collapsible)
    cmds.frameLayout(label=_t("driven_targets_frame"), collapsable=True, collapse=False, mw=8, mh=6, w=LEFT_W)
    cmds.columnLayout(adj=False, rs=4)
    cmds.textScrollList("fdr_drivenList", nr=7, ams=True, h=_px(120), w=LEFT_W - _px(24))
    BW2 = (LEFT_W - 16 - 8) // 2
    cmds.rowLayout(nc=2, cw2=(BW2, BW2))
    cmds.button(l=_t("driven_targets_add"), h=BTN_H_24, w=BW2, c=_ui_driven_list_add_selected_cmds)
    cmds.button(l=_t("driven_targets_remove"), h=BTN_H_24, w=BW2, c=_ui_driven_list_remove_selected_cmds)
    cmds.setParent("..")
    cmds.rowLayout(nc=2, cw2=(BW2, BW2))
    cmds.button(l=_t("driven_targets_select"), h=BTN_H_24, w=BW2, c=_ui_driven_list_select_scene_cmds)
    cmds.button(l=_t("driven_targets_clear"), h=BTN_H_24, w=BW2, c=_ui_driven_list_clear_cmds)
    cmds.setParent("..")
    cmds.setParent("..") # columnLayout
    cmds.setParent("..") # frameLayout
    _ui_driven_list_load_cmds()

    # Actions frame
    cmds.frameLayout(label=_t("actions_frame"), collapsable=False, mw=8, mh=6, w=LEFT_W)
    cmds.columnLayout(adj=False, rs=4)

    BW3 = (LEFT_W - 16 - 8) // 3
    cmds.rowLayout(nc=3, cw3=(BW3, BW3, BW3))
    cmds.button(l=_t("enter_edit"), h=BTN_H_28, w=BW3, c=_ui_enter_edit)
    cmds.button(l=_t("commit"),     h=BTN_H_28, w=BW3, c=_ui_commit)
    cmds.button(l=_t("cancel"),     h=BTN_H_28, w=BW3, c=_ui_cancel)
    cmds.setParent("..")

    saved_mode = _optvar_get_str(_WRITE_MODE_OPT_VAR, "update").lower()
    if saved_mode not in ("add", "update"):
        saved_mode = "update"

    cmds.rowLayout(nc=2, cw2=(LW, FIELD_W_200), ct2=("left","left"))
    cmds.text(l=_t("write_mode"), al="right", w=LW)
    cmds.optionMenu("fdr_writeMode", w=FIELD_W_200)
    cmds.menuItem(l=_t("write_add"))
    cmds.menuItem(l=_t("write_update"))
    try:
        cmds.optionMenu(
            "fdr_writeMode", e=True,
            v=(_t("write_update") if saved_mode == "update" else _t("write_add")),
        )
    except Exception:
        pass
    cmds.setParent("..")

    cmds.setParent("..") # columnLayout
    cmds.setParent("..") # frameLayout

    # Mirror frame
    cmds.frameLayout(label=_t("mirror_frame"), collapsable=False, mw=8, mh=6, w=LEFT_W)
    cmds.columnLayout(adj=False, rs=4)

    mirror_axis = _optvar_get_str(_MIRROR_AXIS_OPT_VAR, "X").upper()
    if mirror_axis not in ("X", "Y", "Z"):
        mirror_axis = "X"
    mirror_dir = _optvar_get_str(_MIRROR_DIR_OPT_VAR, "L2R").upper()
    if mirror_dir not in ("L2R", "R2L"):
        mirror_dir = "L2R"

    cmds.rowLayout(nc=4, cw4=(LW, FIELD_W_80, FIELD_W_50, FIELD_W_60), ct4=("left","left","left","left"))
    cmds.text(l=_t("mirror_dir"), al="right", w=LW)
    cmds.optionMenu("fdr_mirrorDir", w=FIELD_W_80)
    # Avoid Unicode arrows; some Maya UIs render them as garbled glyphs.
    cmds.menuItem(l="L->R")
    cmds.menuItem(l="R->L")
    try:
        cmds.optionMenu("fdr_mirrorDir", e=True, v=("L->R" if mirror_dir == "L2R" else "R->L"))
    except Exception:
        pass
    cmds.text(l=_t("mirror_axis"), al="right")
    cmds.optionMenu("fdr_mirrorAxis", w=FIELD_W_60)
    for a in ("X", "Y", "Z"):
        cmds.menuItem(l=a)
    try:
        cmds.optionMenu("fdr_mirrorAxis", e=True, v=mirror_axis)
    except Exception:
        pass
    cmds.setParent("..")

    cmds.button(l=_t("mirror_apply"), h=BTN_H_26, c=_ui_mirror_apply)
    cmds.setParent("..") # columnLayout
    cmds.setParent("..") # frameLayout

    # Language toggle
    def _toggle_lang(*_):
        cur = _get_lang()
        _set_lang("en" if cur == "zh" else "zh")
        show_ui()

    cmds.separator(h=_px(6), style="none")
    cmds.button(l=_t("lang"), h=BTN_H_24, w=LEFT_W - _px(16), c=_toggle_lang)

    # Create corrective joint/control (collapsed by default)
    cmds.separator(h=_px(4), style="in")
    cmds.frameLayout(label=_t("create_frame"), collapsable=True, collapse=True, mw=8, mh=6, w=LEFT_W)
    cmds.columnLayout(adj=False, rs=4)

    cmds.rowLayout(nc=2, cw2=(LW, FIELD_W_180))
    cmds.text(l=_t("create_name"), al="right", w=LW)
    cmds.textField("fdr_createBase", tx="", w=FIELD_W_180)
    cmds.setParent("..")

    cmds.rowLayout(nc=3, cw3=(LW, FIELD_W_120, FIELD_W_100))
    cmds.text(l=_t("create_parent"), al="right", w=LW)
    cmds.textField("fdr_createParent", tx="", w=FIELD_W_120)
    cmds.button(l=_t("create_load_parent"), h=BTN_H_22, c=_ui_create_load_parent_from_selection)
    cmds.setParent("..")

    cmds.rowLayout(nc=2, cw2=(LW, FIELD_W_80))
    cmds.text(l=_t("create_radius"), al="right", w=LW)
    cmds.floatField("fdr_createRadius", v=1.0, pre=3, w=FIELD_W_80)
    cmds.setParent("..")

    cmds.button(l=_t("create_btn"), h=BTN_H_28, c=_ui_create_corrective)
    cmds.setParent("..") # columnLayout
    cmds.setParent("..") # frameLayout

    # End left pane
    cmds.setParent(form)

    # 鈹€鈹€ Right pane: SDK list management 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
    right_col = cmds.columnLayout("fdr_rightCol", adj=True)
    cmds.frameLayout(label=_t("sdk_list_frame"), collapsable=False, mw=6, mh=6)
    cmds.columnLayout(adj=True, rs=4)

    cmds.checkBox("fdr_sdkFold", l=_t("sdk_fold"), v=_sdk_fold_enabled(), cc=_ui_sdk_refresh_list_display)

    # SDK tree (fills right pane height)
    cmds.treeView("fdr_sdkTree", numberOfButtons=0, ams=True, h=TREE_H)
    # Legacy flat list (hidden, kept for compatibility)
    cmds.textScrollList("fdr_sdkList", nr=6, ams=True, vis=False)

    cmds.separator(h=_px(4), style="none")
    # Bottom button row: Scan SDK | Edit Selected | Edit By Driver | Delete | Select Driver
    # Row 1
    cmds.rowLayout(nc=3, adj=1)
    cmds.button(l=_t("scan_sdk"),         h=BTN_H_26, c=_ui_scan_sdk)
    cmds.button(l=_t("sdk_edit_selected"), h=BTN_H_26, c=_ui_sdk_edit_selected)
    cmds.button(l=_t("sdk_edit_driver"),  h=BTN_H_26, c=_ui_sdk_edit_driver)
    cmds.setParent("..")
    # Row 2
    cmds.rowLayout(nc=3, adj=1)
    cmds.button(l="",                        h=BTN_H_26, en=False)  # spacer
    cmds.button(l=_t("sdk_delete_selected"), h=BTN_H_26, c=_ui_sdk_delete_selected)
    cmds.button(l=_t("sdk_select_driver"),   h=BTN_H_26, c=_ui_sdk_select_driver)
    cmds.setParent("..")

    _ui_sdk_refresh_list_display()

    cmds.setParent("..") # columnLayout inside frame
    cmds.setParent("..") # frameLayout
    cmds.setParent(form)

    # Attach left (fixed px) and right (fills remainder)
    cmds.formLayout(
        form,
        e=True,
        attachForm=[
            (left_col,  "top",    0),
            (left_col,  "left",   0),
            (left_col,  "bottom", 0),
            (right_col, "top",    0),
            (right_col, "right",  0),
            (right_col, "bottom", 0),
        ],
        attachControl=[
            (right_col, "left", _px(4), left_col),
        ],
        attachNone=[
            (left_col, "right"),
        ],
    )

    cmds.showWindow(_WINDOW)


# Convenience when running as a script.
if __name__ == "__main__":
    # Use Qt UI by default (falls back to Maya UI if Qt not available)
    show_ui_qt()
