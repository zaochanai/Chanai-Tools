# -*- coding: utf-8 -*-
"""ADV 动画层帧标记工具

将选中对象的关键帧显示为 Maya 时间轴书签（timeSliderBookmark）。
支持自动检测：选择变化 / 动画层切换 / 关键帧变化时自动刷新。

需求：Maya 2020+（timeSliderBookmark）
"""

import maya.cmds as cmds
import maya.api.OpenMaya as om
from contextlib import contextmanager

_QT_AVAILABLE = False
_QT_IMPORT_ERROR = None
_QT_BINDING = None  # 'PySide2' | 'PySide6' | 'PySide'

try:
    from PySide2 import QtWidgets, QtCore
    _QT_AVAILABLE = True
    _QT_BINDING = 'PySide2'
except Exception as e:
    _QT_IMPORT_ERROR = e
    try:
        # Maya 2025 (Qt6)
        from PySide6 import QtWidgets, QtCore  # type: ignore
        _QT_AVAILABLE = True
        _QT_BINDING = 'PySide6'
        _QT_IMPORT_ERROR = None
    except ImportError:
        try:
            # Very old Maya / legacy environments
            from PySide import QtWidgets, QtCore  # type: ignore
            _QT_AVAILABLE = True
            _QT_BINDING = 'PySide'
            _QT_IMPORT_ERROR = None
        except Exception as e2:
            _QT_IMPORT_ERROR = e2

            class _QtWidgetsDummy(object):
                class QDialog(object):
                    pass

            class _QtCoreDummy(object):
                class Qt(object):
                    Tool = 0
                    WindowStaysOnTopHint = 0

            QtWidgets = _QtWidgetsDummy
            QtCore = _QtCoreDummy


def _qt_window_flag(name):
    """Qt5/Qt6 compatible window flag lookup."""
    try:
        v = getattr(QtCore.Qt, name)
        if v is not None:
            return v
    except Exception:
        pass
    try:
        # Qt6 enum scoping
        wt = getattr(QtCore.Qt, 'WindowType', None)
        if wt is not None:
            return getattr(wt, name)
    except Exception:
        pass
    return 0


STYLE_SHEET = """
QDialog{background:#2b2b2b;color:#d6d6d6;}
QGroupBox{border:1px solid #3b3b3b;border-radius:6px;margin-top:10px;padding:10px;}
QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}
QLabel{color:#d6d6d6;}
QPushButton{background:#383838;border:1px solid #3f3f3f;border-radius:6px;padding:8px;font-weight:700;min-height:34px;color:#ffffff;}
QPushButton:hover{border:1px solid #5b5b5b;}
QPushButton:pressed{background:#2f2f2f;}
QPushButton#createBtn{background:#2f6a3a;border:none;color:#ffffff;}
QPushButton#createBtn:hover{background:#348546;}
QPushButton#clearBtn{background:#8a3a34;border:none;color:#ffffff;}
QPushButton#clearBtn:hover{background:#a2463f;}
QCheckBox{color:#d6d6d6;spacing:6px;}
QCheckBox::indicator{width:18px;height:18px;border-radius:4px;border:1px solid #3f3f3f;background:#383838;}
QCheckBox::indicator:checked{background:#2d4d85;border:1px solid #4c6aa4;}
"""

BOOKMARK_PREFIX = "LayerKey_"
FOOTSTEP_PREFIX = "FootstepKey_"
FOOTSTEP_ATTR = "ADV_Footstep"


@contextmanager
def _undo_chunk(name=u"ADV FrameMark"):
    try:
        cmds.undoInfo(openChunk=True, chunkName=name)
    except Exception:
        pass
    try:
        yield
    finally:
        try:
            cmds.undoInfo(closeChunk=True)
        except Exception:
            pass


@contextmanager
def _undo_suspend_without_flush():
    try:
        if om.MGlobal.isUndoing() or om.MGlobal.isRedoing():
            yield
            return
    except Exception:
        pass

    prev = None
    changed = False
    try:
        prev = bool(cmds.undoInfo(q=True, stateWithoutFlush=True))
    except Exception:
        prev = None
    try:
        cmds.undoInfo(stateWithoutFlush=False)
        changed = True
    except Exception:
        changed = False
    try:
        yield
    finally:
        try:
            if om.MGlobal.isUndoing() or om.MGlobal.isRedoing():
                return
        except Exception:
            pass
        if not changed:
            return
        if prev is None:
            try:
                cmds.undoInfo(stateWithoutFlush=True)
            except Exception:
                pass
            return
        try:
            cmds.undoInfo(stateWithoutFlush=bool(prev))
        except Exception:
            pass


def _diag_bool(v):
    try:
        return u"是" if bool(v) else u"否"
    except Exception:
        return u"否"


def _diag_safe_str(v):
    try:
        return str(v)
    except Exception:
        try:
            return repr(v)
        except Exception:
            return "<unprintable>"


def diagnose_undo(layer_tool=None):
    lines = []
    ok = True

    try:
        undo_enabled = bool(cmds.undoInfo(q=True, state=True))
    except Exception:
        undo_enabled = None
    try:
        swof = cmds.undoInfo(q=True, stateWithoutFlush=True)
    except Exception:
        swof = None
    try:
        undoing = bool(om.MGlobal.isUndoing())
    except Exception:
        undoing = None
    try:
        redoing = bool(om.MGlobal.isRedoing())
    except Exception:
        redoing = None

    lines.append(u"[Undo] 开启: {}".format(_diag_safe_str(undo_enabled)))
    lines.append(u"[Undo] stateWithoutFlush: {}".format(_diag_safe_str(swof)))
    lines.append(u"[Undo] isUndoing: {}  isRedoing: {}".format(_diag_safe_str(undoing), _diag_safe_str(redoing)))

    bip_enabled = None
    drag_job = None
    if layer_tool is not None:
        try:
            bip_enabled = bool(getattr(layer_tool, "_bip_overlay_enabled", False))
        except Exception:
            bip_enabled = None
        try:
            drag_job = getattr(layer_tool, "_bip_drag_job_id", None)
        except Exception:
            drag_job = None
        try:
            drag_job_exists = bool(drag_job) and bool(cmds.scriptJob(exists=int(drag_job)))
        except Exception:
            drag_job_exists = None
        lines.append(u"[BIP] 开启: {}  DragRelease scriptJob: {}".format(_diag_safe_str(bip_enabled), _diag_safe_str(drag_job_exists)))

    if undo_enabled is False:
        ok = False
        lines.append(u"[结果] Undo 当前被关闭：Ctrl+Z 当然会失效。")

    tmp = None
    tx_val = 1.234
    try:
        with _undo_chunk(u"ADV Undo Diagnose"):
            tmp = cmds.createNode('transform', name='ADV_UndoDiag_TMP#', skipSelect=True)
            cmds.setAttr(tmp + '.translateX', float(tx_val))
        exists_before = bool(tmp) and bool(cmds.objExists(tmp))
        lines.append(u"[测试] 创建节点: {}".format(_diag_bool(exists_before)))

        try:
            cmds.undo()
        except Exception as e:
            ok = False
            lines.append(u"[测试] undo() 调用失败: {}".format(_diag_safe_str(e)))
            exists_after_undo = None
        else:
            exists_after_undo = bool(tmp) and bool(cmds.objExists(tmp))
            lines.append(u"[测试] undo() 后节点存在: {}".format(_diag_safe_str(exists_after_undo)))
            if exists_after_undo:
                ok = False

        try:
            cmds.redo()
        except Exception as e:
            lines.append(u"[测试] redo() 调用失败: {}".format(_diag_safe_str(e)))
        else:
            exists_after_redo = bool(tmp) and bool(cmds.objExists(tmp))
            lines.append(u"[测试] redo() 后节点存在: {}".format(_diag_safe_str(exists_after_redo)))
            if exists_after_redo:
                try:
                    cur = float(cmds.getAttr(tmp + '.translateX'))
                except Exception:
                    cur = None
                lines.append(u"[测试] redo() 后 translateX: {}".format(_diag_safe_str(cur)))

        try:
            cmds.undo()
        except Exception:
            pass
    except Exception as e:
        ok = False
        lines.append(u"[测试] 异常: {}".format(_diag_safe_str(e)))
        try:
            if tmp and cmds.objExists(tmp):
                cmds.delete(tmp)
        except Exception:
            pass

    lines.append(u"[结果] {}".format(u"通过" if ok else u"失败"))

    try:
        print(u"\n".join([u"[ADV][帧标记撤回诊断]"] + lines))
    except Exception:
        pass


def do_diagnose_undo():
    if not _QT_AVAILABLE:
        diagnose_undo(layer_tool=None)
        return _show_cmds_window()
    w = show()
    try:
        diagnose_undo(layer_tool=w)
    except Exception:
        try:
            diagnose_undo(layer_tool=None)
        except Exception:
            pass
    try:
        cmds.inViewMessage(
            amg=(u'<span style="color:{};">帧标记撤回诊断：{}</span>'.format('#27ae60' if ok else '#e74c3c', u"通过" if ok else u"失败")),
            pos='topCenter',
            fade=True,
            fadeStayTime=1600,
        )
    except Exception:
        pass
    if not ok:
        try:
            cmds.warning(u"[ADV][帧标记] 撤回诊断失败：请打开 Script Editor 查看详细输出。")
        except Exception:
            pass
    return ok


def _check_bookmark_support():
    """检查当前 Maya 版本是否支持 timeSliderBookmark，并尝试加载插件"""
    try:
        version = int(cmds.about(version=True)[:4])
        if version < 2020:
            return False

        plugin_name = 'timeSliderBookmark'
        if not cmds.pluginInfo(plugin_name, query=True, loaded=True):
            try:
                cmds.loadPlugin(plugin_name)
                print(u"[ADV LayerBookmarkTool] 已加载 timeSliderBookmark 插件")
            except Exception:
                print(u"[ADV LayerBookmarkTool] 无法加载 timeSliderBookmark 插件")
                return False
        return True
    except Exception:
        return False


BOOKMARK_SUPPORTED = _check_bookmark_support()


class LayerBookmarkTool(QtWidgets.QDialog):

    def __init__(self, parent=None):
        if parent is None:
            parent = self._get_maya_main_window()
        super(LayerBookmarkTool, self).__init__(parent)

        self.setWindowTitle(u"帧标记")
        self.setMinimumSize(560, 230)
        self.setSizeGripEnabled(True)
        flags = self.windowFlags()
        flags = flags | _qt_window_flag('Tool')
        flags = flags & ~_qt_window_flag('WindowStaysOnTopHint')
        self.setWindowFlags(flags)
        self.setStyleSheet(STYLE_SHEET)

        self._last_keyframes = []
        self._selection_job_id = None
        self._layer_job_ids = []
        self._animlayer_create_cb = None

        # 轮询刷新：用于关键帧变化但 Selection 未变化的情况
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(400)
        self._poll_timer.timeout.connect(self._poll_refresh)

        # BIP follow: keep recorded footstep frames synced to previous sliding frame.
        self._footsteps = {}  # (ctrl_fullpath, frame_int) -> {'source': int, 'bookmark': str, 'switches': set(), 'ensured': bool}
        self._bip_drag_job_id = None
        self._last_selection_sig = None
        self._bip_follow_error_last_sig = None
        self._bip_follow_error_last_time = 0.0
        self._bip_follow_deferred = False
        self._auto_align_enabled = False
        self._auto_add_attr_enabled = False

        self._setup_ui()

        self._bip_overlay_enabled = False

    @staticmethod
    def _short_name(node):
        name = (node or '').split('|')[-1]
        if ':' in name:
            name = name.rsplit(':', 1)[-1]
        return name

    @staticmethod
    def _namespace(node):
        name = (node or '').split('|')[-1]
        if ':' in name:
            return name.rsplit(':', 1)[0] + ':'
        return ''

    def _detect_limb_switches_from_selection(self, selection):
        """Return set of FKIK switch node names based on selected FK/IK limb controllers."""
        arm_bases = {u"FKShoulder", u"FKElbow", u"FKWrist", u"IKArm", u"PoleArm"}
        leg_bases = {u"FKHip", u"FKKnee", u"FKAnkle", u"IKLeg", u"PoleLeg", u"IKFoot", u"PoleFoot"}
        attr_candidates = ['FKIKBlend', 'fkikblend', 'fkIkBlend', 'FKIKblend']

        switches = set()
        for n in selection:
            short = self._short_name(n)
            # If user selects FKIK switch itself, accept it directly.
            try:
                for a in attr_candidates:
                    if cmds.attributeQuery(a, node=n, exists=True):
                        switches.add(n)
                        break
            except Exception:
                pass
            if not short.endswith(('_L', '_R')):
                continue
            side = short[-2:]
            base = short[:-2]

            limb = None
            if base in arm_bases:
                limb = 'Arm'
            elif base in leg_bases:
                limb = 'Leg'
            if not limb:
                continue

            ns = self._namespace(n)
            base_name = ns + 'FKIK{}{}'.format(limb, side)

            def _has_fkik_attr(node):
                for a in attr_candidates:
                    try:
                        if cmds.attributeQuery(a, node=node, exists=True):
                            return True
                    except Exception:
                        pass
                return False

            # 1) Exact name
            if cmds.objExists(base_name) and _has_fkik_attr(base_name):
                switches.add(base_name)
                continue

            # 2) Common suffix/prefix variants (e.g. FKIKArm_L_CTRL)
            try:
                candidates = cmds.ls(base_name + '*') or []
            except Exception:
                candidates = []
            for c in candidates:
                if c and cmds.objExists(c) and _has_fkik_attr(c):
                    switches.add(c)
                    break

            # 3) Fuzzy match within namespace
            if ns:
                pattern = ns + '*FKIK*{}*{}*'.format(limb, side)
            else:
                pattern = '*FKIK*{}*{}*'.format(limb, side)
            try:
                candidates = cmds.ls(pattern) or []
            except Exception:
                candidates = []
            for c in candidates:
                if c and cmds.objExists(c) and _has_fkik_attr(c):
                    switches.add(c)
                    break

        return switches

    def _key_and_set_fkikblend(self, value, _undo=True, _auto_align=True):
        """Key selected controls, and if they belong to limbs, set FKIK*.FKIKBlend to value and key it."""
        if _undo:
            with _undo_chunk(u"帧标记-打帧"):
                return self._key_and_set_fkikblend(value, _undo=False, _auto_align=_auto_align)
        selection = cmds.ls(sl=True) or []
        if not selection:
            cmds.warning(u"请先选择控制器")
            return

        attr_candidates = ['FKIKBlend', 'fkikblend', 'fkIkBlend', 'FKIKblend']

        # Also key raw selection in case transform filtering misses shapes
        for n in selection:
            try:
                cmds.setKeyframe(n)
            except Exception:
                pass

        # Prefer transforms
        transforms = []
        for n in selection:
            if cmds.nodeType(n) == 'transform':
                transforms.append(n)
                continue
            parent = (cmds.listRelatives(n, parent=True, fullPath=True) or [None])[0]
            if parent and cmds.objExists(parent):
                transforms.append(parent)
        # Deduplicate while keeping order
        seen = set()
        transforms = [t for t in transforms if not (t in seen or seen.add(t))]

        for ctrl in transforms:
            try:
                cmds.setKeyframe(ctrl)
            except Exception:
                pass

        switches = self._detect_limb_switches_from_selection(transforms)
        if not switches:
            # Still clear footstep marker on this frame if user is converting it.
            try:
                self._set_footstep_attr_at_current_frame(transforms, 0)
                self._clear_footsteps_on_current_frame(transforms)
            except Exception:
                pass
            try:
                self._refresh_footsteps_display()
            except Exception:
                pass
            if _auto_align:
                self._maybe_run_auto_align(_undo=False)
            return

        # Set FKIKBlend on detected switches and key it.
        for sw in sorted(switches):
            if not sw or not cmds.objExists(sw):
                continue

            attr = None
            for a in attr_candidates:
                try:
                    if cmds.attributeQuery(a, node=sw, exists=True):
                        attr = a
                        break
                except Exception:
                    pass
            if not attr:
                continue

            plug = '{}.{}'.format(sw, attr)

            # If the attribute is driven by a non-animCurve connection, setting may fail.
            try:
                incoming = cmds.listConnections(plug, s=True, d=False, p=True) or []
            except Exception:
                incoming = []
            if incoming:
                try:
                    node_types = {cmds.nodeType(p.split('.', 1)[0]) for p in incoming if p}
                except Exception:
                    node_types = set()
                if node_types and not any(t.startswith('animCurve') for t in node_types):
                    try:
                        cmds.warning(u"[ADV LayerBookmarkTool] {} 有输入连接({})，可能无法直接设值".format(plug, ','.join(sorted(node_types))))
                    except Exception:
                        pass

            ok = False
            try:
                cmds.setAttr(plug, float(value))
                ok = True
            except Exception:
                ok = False

            try:
                cmds.setKeyframe(sw, at=attr)
            except Exception:
                try:
                    cmds.setKeyframe(plug)
                except Exception:
                    pass

            # Visible feedback for debugging
            try:
                cur_v = cmds.getAttr(plug)
            except Exception:
                cur_v = None
            try:
                print(u"[ADV LayerBookmarkTool] FKIK: {} -> {} (set:{} now:{})".format(plug, value, ok, cur_v))
            except Exception:
                pass

        # If this frame had an orange footstep marker, remove it so BIP black/yellow can show.
        try:
            self._set_footstep_attr_at_current_frame(transforms, 0)
            self._clear_footsteps_on_current_frame(transforms)
        except Exception:
            pass
        try:
            self._refresh_footsteps_display()
        except Exception:
            pass

        if _auto_align:
            self._maybe_run_auto_align(_undo=False)
        self._trigger_bip_refresh()

    def _maybe_run_auto_align(self, _undo=False):
        if not self._bip_overlay_enabled:
            return
        try:
            enabled = bool(getattr(self, '_auto_align_enabled', False))
        except Exception:
            enabled = False
        if not enabled:
            return
        try:
            self._run_align_once(_undo=_undo)
        except Exception:
            pass

    def _clear_footsteps_on_current_frame(self, transforms):
        if not self._bip_overlay_enabled:
            return
        try:
            cur_frame = int(round(float(cmds.currentTime(q=True))))
        except Exception:
            return
        self._clear_footsteps_for_transforms_at_frame(transforms, cur_frame)

    def _set_footstep_attr_at_current_frame(self, transforms, value):
        try:
            cur_frame = int(round(float(cmds.currentTime(q=True))))
        except Exception:
            return
        for ctrl in transforms or []:
            self._set_footstep_attr_at_frame(ctrl, cur_frame, value)

    def _set_footstep_attr_at_frame(self, ctrl, frame, value):
        if not ctrl or not cmds.objExists(ctrl):
            return
        try:
            frame = int(round(float(frame)))
        except Exception:
            return
        try:
            exists = cmds.attributeQuery(FOOTSTEP_ATTR, node=ctrl, exists=True)
        except Exception:
            exists = False
        if not exists:
            # Only auto-add attribute when enabled.
            if not self._auto_add_attr_enabled:
                return
            try:
                cmds.addAttr(ctrl, longName=FOOTSTEP_ATTR, at='bool', k=True)
            except Exception:
                return
        plug = '{}.{}'.format(ctrl, FOOTSTEP_ATTR)
        # Apply immediately at current time so viewport reacts without frame change.
        try:
            cmds.setAttr(plug, int(bool(value)))
        except Exception:
            pass
        try:
            cmds.setKeyframe(plug, time=(frame, frame), value=int(bool(value)))
        except Exception:
            try:
                cmds.setKeyframe(plug, time=(frame, frame))
            except Exception:
                pass

    def _get_footstep_frames_from_attr_map(self, transforms):
        """Return {ctrl: set(frames)} for ADV_Footstep keys on each ctrl."""
        mapping = {}
        for ctrl in transforms or []:
            if not ctrl or not cmds.objExists(ctrl):
                continue
            try:
                if not cmds.attributeQuery(FOOTSTEP_ATTR, node=ctrl, exists=True):
                    continue
            except Exception:
                continue
            plug = '{}.{}'.format(ctrl, FOOTSTEP_ATTR)
            try:
                t = cmds.keyframe(plug, q=True, timeChange=True) or []
                v = cmds.keyframe(plug, q=True, valueChange=True) or []
            except Exception:
                t, v = [], []
            frames = set()
            for tt, vv in zip(t, v):
                try:
                    if float(vv) >= 0.5:
                        frames.add(int(round(float(tt))))
                except Exception:
                    pass
            if frames:
                mapping[ctrl] = frames
        return mapping

    def _rebuild_footsteps_from_attr(self, transforms=None):
        if not self._bip_overlay_enabled:
            return
        if transforms is None:
            transforms = self._get_selection_transforms_long()
        if not transforms:
            return
        mapping = self._get_footstep_frames_from_attr_map(transforms)
        if not mapping:
            return
        try:
            self._footsteps.clear()
        except Exception:
            pass
        switches = self._detect_limb_switches_from_selection(transforms)
        for ctrl, frames in mapping.items():
            for f in frames:
                self._record_footstep(ctrl, int(f), int(f), switches)

    def _clear_footsteps_for_transforms_at_frame(self, transforms, frame):
        """Remove footstep record + orange bookmark for given transforms at a specific frame."""
        try:
            frame = int(frame)
        except Exception:
            return

        # Remove internal records
        try:
            for ctrl in transforms or []:
                self._footsteps.pop((ctrl, frame), None)
        except Exception:
            pass

        if not BOOKMARK_SUPPORTED:
            return

        # Delete matching bookmark nodes by name attribute to be robust.
        try:
            all_bookmarks = cmds.ls(type='timeSliderBookmark') or []
        except Exception:
            all_bookmarks = []

        to_delete = []
        for ctrl in transforms or []:
            ctrl_short = self._short_name(ctrl)
            expected_label = u'{}{} F{}'.format(FOOTSTEP_PREFIX, ctrl_short, int(frame))
            expected_node = '{}{}_F{}'.format(FOOTSTEP_PREFIX, self._sanitize_name(ctrl_short), int(frame))

            for bm in all_bookmarks:
                try:
                    if self._short_name(bm) == expected_node:
                        to_delete.append(bm)
                        continue
                except Exception:
                    pass
                try:
                    nm = cmds.getAttr(bm + '.name')
                    if nm == expected_label:
                        to_delete.append(bm)
                        continue
                except Exception:
                    pass

        if to_delete:
            try:
                cmds.delete(list(set(to_delete)))
            except Exception:
                pass

        # Caller decides when to refresh display.

    def _refresh_footsteps_display(self):
        try:
            self._rebuild_footsteps_from_attr()
        except Exception:
            pass
        try:
            self._refresh_footstep_bookmarks_for_selection()
        except Exception:
            pass

    def _get_translate_at_time(self, node, frame):
        # Local translate sampling to match setAttr('.translate*') (prevents world/local mismatch).
        try:
            v = cmds.getAttr(node + '.translate', time=frame)
            if v and isinstance(v, (list, tuple)):
                t = v[0]
                if t and len(t) >= 3:
                    return (float(t[0]), float(t[1]), float(t[2]))
        except Exception:
            pass
        return None

    def _find_prev_sliding_frame(self, switches, cur_time):
        attr_candidates = ['FKIKBlend', 'fkikblend', 'fkIkBlend', 'FKIKblend']
        best = None
        for sw in switches:
            if not cmds.objExists(sw):
                continue
            attr = None
            for a in attr_candidates:
                try:
                    if cmds.attributeQuery(a, node=sw, exists=True):
                        attr = a
                        break
                except Exception:
                    pass
            if not attr:
                continue
            plug = '{}.{}'.format(sw, attr)
            try:
                t = cmds.keyframe(plug, q=True, timeChange=True) or []
                v = cmds.keyframe(plug, q=True, valueChange=True) or []
            except Exception:
                t, v = [], []
            for tt, vv in zip(t, v):
                try:
                    if float(vv) >= 9.999 and float(tt) < float(cur_time):
                        if (best is None) or (float(tt) > float(best)):
                            best = tt
                except Exception:
                    pass
        if best is None:
            return None
        try:
            return int(round(float(best)))
        except Exception:
            return None

    def _key_and_align_footstep(self, *_, **kwargs):
        """先打滑动关键帧，再把当前位移对齐到上一个滑动关键帧的上一帧位移。"""
        _undo = bool(kwargs.get('_undo', True))
        if _undo:
            with _undo_chunk(u"帧标记-踩踏帧"):
                return self._key_and_align_footstep(_undo=False)
        selection = cmds.ls(sl=True) or []
        if not selection:
            cmds.warning(u"请先选择控制器")
            return

        # 先计算“上一个滑动关键帧”（作为跟随源），再执行滑动关键帧
        try:
            cur_time = cmds.currentTime(q=True)
        except Exception:
            cur_time = None
        if cur_time is None:
            return

        # Prefer transforms
        transforms = []
        for n in selection:
            if cmds.nodeType(n) == 'transform':
                transforms.append(n)
                continue
            parent = (cmds.listRelatives(n, parent=True, fullPath=True) or [None])[0]
            if parent and cmds.objExists(parent):
                transforms.append(parent)
        # Deduplicate while keeping order
        seen = set()
        transforms = [t for t in transforms if not (t in seen or seen.add(t))]

        switches = self._detect_limb_switches_from_selection(transforms)
        if not switches:
            cmds.warning(u"未检测到 FKIK 开关，无法执行踩踏对齐")
            return

        prev_time = self._find_prev_sliding_frame(switches, cur_time)
        if prev_time is None:
            # No sliding found: fall back to previous translate keyframe; if none, use current.
            prev_time = self._find_prev_translate_keyframe(transforms[0] if transforms else None, cur_time)
        if prev_time is None:
            prev_time = cur_time

        # 先执行滑动关键帧（保持旧行为：把当前帧设为 FKIKBlend=10 并打帧）
        self._key_and_set_fkikblend(10, _undo=False, _auto_align=False)

        # Prefer transforms
        transforms = []
        for n in selection:
            if cmds.nodeType(n) == 'transform':
                transforms.append(n)
                continue
            parent = (cmds.listRelatives(n, parent=True, fullPath=True) or [None])[0]
            if parent and cmds.objExists(parent):
                transforms.append(parent)
        # Deduplicate while keeping order
        cur_frame = int(round(float(cur_time)))
        for ctrl in transforms:
            p1 = self._get_translate_at_time(ctrl, prev_time)
            if p1 is None:
                continue
            try:
                # Snap current frame to the previous sliding keyframe position.
                cmds.setAttr(ctrl + '.translateX', float(p1[0]))
                cmds.setAttr(ctrl + '.translateY', float(p1[1]))
                cmds.setAttr(ctrl + '.translateZ', float(p1[2]))
                cmds.setKeyframe(ctrl, at=['translateX', 'translateY', 'translateZ'])
            except Exception:
                pass

            # Record for BIP-follow and create orange bookmark marker (BIP mode only).
            if self._bip_overlay_enabled:
                self._record_footstep(ctrl, cur_frame, int(prev_time), switches)
            try:
                self._set_footstep_attr_at_frame(ctrl, cur_frame, 1)
            except Exception:
                pass

        # Optional: auto align after creating footstep.
        try:
            self._refresh_footsteps_display()
        except Exception:
            pass
        self._maybe_run_auto_align(_undo=False)
        self._trigger_bip_refresh()
    def _trigger_bip_refresh(self):
        if not self._bip_overlay_enabled:
            return
        try:
            from . import adv_bip_time_slider_overlay
        except Exception:
            try:
                import adv_bip_time_slider_overlay
            except Exception:
                adv_bip_time_slider_overlay = None
        if adv_bip_time_slider_overlay is None:
            return
        try:
            adv_bip_time_slider_overlay.refresh_now()
        except Exception:
            pass

        # Follow is triggered on DragRelease when BIP mode is enabled.

    def _sanitize_name(self, s):
        s = (s or '').replace('|', '_').replace(':', '_')
        out = []
        for ch in s:
            if ch.isalnum() or ch in ['_', '-']:
                out.append(ch)
            else:
                out.append('_')
        return ''.join(out)

    def _ensure_footstep_bookmark(self, ctrl, frame):
        if not BOOKMARK_SUPPORTED:
            return None

        ctrl_short = self._short_name(ctrl)
        name = '{}{}_F{}'.format(FOOTSTEP_PREFIX, self._sanitize_name(ctrl_short), int(frame))

        try:
            if not cmds.objExists(name):
                bm = cmds.createNode('timeSliderBookmark', name=name, skipSelect=True)
            else:
                bm = name
            try:
                cmds.setAttr(bm + '.name', u'{}{} F{}'.format(FOOTSTEP_PREFIX, ctrl_short, int(frame)), type='string')
            except Exception:
                pass
            try:
                cmds.setAttr(bm + '.timeRangeStart', int(frame))
                cmds.setAttr(bm + '.timeRangeStop', int(frame))
            except Exception:
                pass
            # Orange
            try:
                cmds.setAttr(bm + '.color', 1.0, 0.55, 0.0, type='double3')
            except Exception:
                pass
            return bm
        except Exception:
            return None

    def _record_footstep(self, ctrl, frame, source_frame, switches):
        key = (ctrl, int(frame))
        data = self._footsteps.get(key) or {}
        # source_frame is recorded as a hint; follow logic will re-resolve dynamically.
        data['source_hint'] = int(source_frame)
        data['switches'] = set(switches or [])
        data.setdefault('ensured', False)
        bm = self._ensure_footstep_bookmark(ctrl, frame)
        if bm:
            data['bookmark'] = bm
        self._footsteps[key] = data

    def _get_selection_transforms_long(self):
        """Return selected transform nodes (long paths), best-effort."""
        try:
            sel = cmds.ls(sl=True, long=True) or []
        except Exception:
            sel = []

        transforms = []
        for n in sel:
            try:
                if cmds.nodeType(n) == 'transform':
                    transforms.append(n)
                    continue
            except Exception:
                pass
            try:
                parent = (cmds.listRelatives(n, parent=True, fullPath=True) or [None])[0]
            except Exception:
                parent = None
            if parent and cmds.objExists(parent):
                transforms.append(parent)

        # Deduplicate while keeping order
        out = []
        seen = set()
        for t in transforms:
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
        return out

    def _refresh_footstep_bookmarks_for_selection(self, selection_transforms=None):
        """Show orange footstep bookmarks only for current selection.

        timeSliderBookmark is global, so we delete & recreate for the selected controls.
        """
        if not self._bip_overlay_enabled:
            return
        if selection_transforms is None:
            selection_transforms = self._get_selection_transforms_long()

        try:
            with _undo_suspend_without_flush():
                self._clear_footstep_bookmarks()
                if not selection_transforms:
                    return
                sel_set = set(selection_transforms)
                for (ctrl, frame), data in list(self._footsteps.items()):
                    if ctrl not in sel_set:
                        continue
                    bm = self._ensure_footstep_bookmark(ctrl, frame)
                    if bm:
                        data['bookmark'] = bm
        except Exception:
            pass

    def _find_prev_footstep_frame(self, ctrl, frame):
        """Find nearest previous footstep-marked frame for the same ctrl."""
        try:
            frame = int(frame)
        except Exception:
            return None
        best = None
        for (c, f) in self._footsteps.keys():
            if c != ctrl:
                continue
            try:
                f = int(f)
            except Exception:
                continue
            if f < frame and (best is None or f > best):
                best = f
        return best

    def _find_prev_translate_keyframe(self, ctrl, frame):
        """Nearest previous translate keyframe time (int frame) for a control."""
        try:
            frame = int(frame)
        except Exception:
            return None

        times = set()
        for at in ('translateX', 'translateY', 'translateZ'):
            plug = '{}.{}'.format(ctrl, at)
            try:
                t = cmds.keyframe(plug, q=True, timeChange=True) or []
            except Exception:
                t = []
            for tt in t:
                try:
                    times.add(int(round(float(tt))))
                except Exception:
                    pass
        if not times:
            return None
        prev = [t for t in times if t < frame]
        if not prev:
            return None
        return max(prev)

    def _find_prev_source_frame(self, ctrl, switches, frame):
        """Resolve source frame for a footstep.

        Desired behavior: always follow the nearest previous *sliding* frame (FKIKBlend=10).
        If no sliding exists, fall back to the nearest previous footstep frame.
        """
        try:
            frame_i = int(frame)
        except Exception:
            return None, None

        prev_sliding = self._find_prev_sliding_frame(list(switches or []), frame_i)
        if prev_sliding is not None:
            return 'sliding', int(prev_sliding)

        prev_footstep = self._find_prev_footstep_frame(ctrl, frame_i)
        if prev_footstep is not None:
            return 'footstep', int(prev_footstep)

        return None, None

    def _is_sliding_at_frame(self, switches, frame):
        attr_candidates = ['FKIKBlend', 'fkikblend', 'fkIkBlend', 'FKIKblend']
        for sw in switches or []:
            if not sw or not cmds.objExists(sw):
                continue
            attr = None
            for a in attr_candidates:
                try:
                    if cmds.attributeQuery(a, node=sw, exists=True):
                        attr = a
                        break
                except Exception:
                    pass
            if not attr:
                continue
            plug = '{}.{}'.format(sw, attr)
            try:
                v = cmds.getAttr(plug, time=frame)
                if float(v) >= 9.999:
                    return True
            except Exception:
                pass
        return False

    def _ensure_sliding_at_frame(self, switches, frame):
        """Force FKIKBlend=10 at specific frame (used when source sliding disappears)."""
        attr_candidates = ['FKIKBlend', 'fkikblend', 'fkIkBlend', 'FKIKblend']
        try:
            frame = int(round(float(frame)))
        except Exception:
            return

        for sw in switches or []:
            if not sw or not cmds.objExists(sw):
                continue
            attr = None
            for a in attr_candidates:
                try:
                    if cmds.attributeQuery(a, node=sw, exists=True):
                        attr = a
                        break
                except Exception:
                    pass
            if not attr:
                continue
            plug = '{}.{}'.format(sw, attr)
            try:
                # Key explicit value at time without changing currentTime.
                cmds.setKeyframe(plug, time=(frame, frame), value=10.0)
            except Exception:
                try:
                    cmds.setKeyframe(sw, at=attr, time=(frame, frame), value=10.0)
                except Exception:
                    pass

    def _set_translate_at_frame(self, ctrl, frame, txyz):
        if txyz is None:
            return
        try:
            frame = int(round(float(frame)))
        except Exception:
            return

        targets = {
            'translateX': float(txyz[0]),
            'translateY': float(txyz[1]),
            'translateZ': float(txyz[2]),
        }

        for at, val in targets.items():
            plug = '{}.{}'.format(ctrl, at)
            # Avoid re-keying the same value every timer tick.
            try:
                existing = cmds.keyframe(plug, q=True, time=(frame, frame), valueChange=True)
                if existing and abs(float(existing[0]) - float(val)) < 1e-6:
                    continue
            except Exception:
                pass
            try:
                cmds.setKeyframe(plug, time=(frame, frame), value=float(val))
            except Exception:
                try:
                    cmds.setKeyframe(ctrl, at=at, time=(frame, frame), value=float(val))
                except Exception:
                    pass

    def _update_footsteps_follow(self, *_, **kwargs):
        """When BIP mode is enabled, keep recorded footstep frames synced to their source.

        Triggered on DragRelease to avoid snapping while user is dragging.
        """
        _undo = bool(kwargs.get('_undo', True))
        if _undo:
            with _undo_chunk(u"帧标记-踩踏跟随"):
                return self._update_footsteps_follow(_undo=False)
        if not self._bip_overlay_enabled:
            return
        if not self._footsteps:
            return

        dead = []
        try:
            cur_time = int(round(float(cmds.currentTime(q=True))))
        except Exception:
            cur_time = None

        # Process footsteps in ascending frame order per controller for stable propagation.
        by_ctrl = {}
        for (ctrl, frame), data in list(self._footsteps.items()):
            by_ctrl.setdefault(ctrl, []).append((int(frame), data))

        for ctrl, items in by_ctrl.items():
            if not ctrl or not cmds.objExists(ctrl):
                for frame, _ in items:
                    dead.append((ctrl, frame))
                continue

            items.sort(key=lambda it: it[0])
            for frame, data in items:
                switches = data.get('switches') or self._detect_limb_switches_from_selection([ctrl])
                data['switches'] = set(switches or [])

                kind, source = self._find_prev_source_frame(ctrl, data['switches'], frame)
                if source is None:
                    continue

                if kind == 'sliding':
                    data['ensured'] = False
                    txyz = self._get_translate_at_time(ctrl, source)
                    self._set_translate_at_frame(ctrl, frame, txyz)
                    if cur_time is not None and int(frame) == cur_time and txyz is not None:
                        try:
                            cmds.setAttr(ctrl + '.translateX', float(txyz[0]))
                            cmds.setAttr(ctrl + '.translateY', float(txyz[1]))
                            cmds.setAttr(ctrl + '.translateZ', float(txyz[2]))
                        except Exception:
                            pass
                elif kind == 'footstep':
                    txyz = self._get_translate_at_time(ctrl, source)
                    self._set_translate_at_frame(ctrl, frame, txyz)
                    if cur_time is not None and int(frame) == cur_time and txyz is not None:
                        try:
                            cmds.setAttr(ctrl + '.translateX', float(txyz[0]))
                            cmds.setAttr(ctrl + '.translateY', float(txyz[1]))
                            cmds.setAttr(ctrl + '.translateZ', float(txyz[2]))
                        except Exception:
                            pass
                    if not data.get('ensured'):
                        self._ensure_sliding_at_frame(data['switches'], frame)
                        data['ensured'] = True

        for k in dead:
            try:
                self._footsteps.pop(k, None)
            except Exception:
                pass

    def _get_maya_main_window(self):
        try:
            from shiboken2 import wrapInstance
        except ImportError:
            try:
                from shiboken import wrapInstance
            except ImportError:
                wrapInstance = None

        try:
            import maya.OpenMayaUI as omui
            main_window_ptr = omui.MQtUtil.mainWindow()
            if main_window_ptr and wrapInstance:
                return wrapInstance(int(main_window_ptr), QtWidgets.QWidget)
        except Exception:
            pass
        return None
    def _setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        mode_group = QtWidgets.QGroupBox(u"模式")
        mode_layout = QtWidgets.QHBoxLayout(mode_group)
        mode_layout.setContentsMargins(12, 10, 12, 10)
        mode_layout.setSpacing(14)

        self.bip_check = QtWidgets.QCheckBox(u"BIP模式")
        self.bip_check.setCursor(QtCore.Qt.PointingHandCursor)
        self.bip_check.setToolTip(u"在时间滑块上方叠加一条关键帧显示条：黑色=选中控制器关键帧；黄色=四肢 FKIKBlend=10")
        self.bip_check.stateChanged.connect(self._on_bip_check_changed)
        mode_layout.addWidget(self.bip_check)

        self.auto_align_check = QtWidgets.QCheckBox(u"自动对齐")
        self.auto_align_check.setCursor(QtCore.Qt.PointingHandCursor)
        self.auto_align_check.setToolTip(u"开启后：点击 设置帧/滑动帧/踩踏帧 会在打帧后自动执行一次对齐")
        self.auto_align_check.stateChanged.connect(self._on_auto_align_check_changed)
        self.auto_align_check.setEnabled(False)
        mode_layout.addWidget(self.auto_align_check)

        self.auto_check = QtWidgets.QCheckBox(u"层自动")
        self.auto_check.setCursor(QtCore.Qt.PointingHandCursor)
        self.auto_check.stateChanged.connect(self._on_auto_check_changed)
        mode_layout.addWidget(self.auto_check)
        mode_layout.addStretch(1)

        bookmark_group = QtWidgets.QGroupBox(u"层书签")
        bookmark_layout = QtWidgets.QHBoxLayout(bookmark_group)
        bookmark_layout.setContentsMargins(12, 10, 12, 10)
        bookmark_layout.setSpacing(14)

        self.create_btn = QtWidgets.QPushButton(u"创建层书签")
        self.create_btn.setObjectName("createBtn")
        self.create_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.create_btn.clicked.connect(self._on_create_bookmarks)
        self.create_btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        bookmark_layout.addWidget(self.create_btn)

        self.clear_btn = QtWidgets.QPushButton(u"清除层书签")
        self.clear_btn.setObjectName("clearBtn")
        self.clear_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self._on_clear_bookmarks)
        self.clear_btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        bookmark_layout.addWidget(self.clear_btn)

        key_group = QtWidgets.QGroupBox(u"关键帧")
        key_layout = QtWidgets.QGridLayout(key_group)
        key_layout.setContentsMargins(12, 10, 12, 10)
        key_layout.setSpacing(12)
        key_layout.setColumnStretch(0, 1)
        key_layout.setColumnStretch(1, 1)
        key_layout.setColumnStretch(2, 1)
        key_layout.setColumnStretch(3, 1)

        self.key_fk_btn = QtWidgets.QPushButton(u"设置帧")
        self.key_fk_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.key_fk_btn.setToolTip(u"给选中控制器打帧；若检测到四肢控制器，则将 FKIK*.FKIKBlend 设为 0 并打帧")
        self.key_fk_btn.clicked.connect(lambda *_: self._key_and_set_fkikblend(0))
        self.key_fk_btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        key_layout.addWidget(self.key_fk_btn, 0, 0)

        self.key_ik_btn = QtWidgets.QPushButton(u"滑动帧")
        self.key_ik_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.key_ik_btn.setToolTip(u"给选中控制器打帧；若检测到四肢控制器，则将 FKIK*.FKIKBlend 设为 10 并打帧")
        self.key_ik_btn.clicked.connect(lambda *_: self._key_and_set_fkikblend(10))
        self.key_ik_btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        key_layout.addWidget(self.key_ik_btn, 0, 1)

        self.key_step_btn = QtWidgets.QPushButton(u"踩踏帧")
        self.key_step_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.key_step_btn.setToolTip(u"先执行滑动帧(FKIKBlend=10)，再读取上一个滑动帧的位置，并对齐到上一帧位移")
        self.key_step_btn.clicked.connect(self._key_and_align_footstep)
        self.key_step_btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        key_layout.addWidget(self.key_step_btn, 0, 2)

        self.align_btn = QtWidgets.QPushButton(u"对齐")
        self.align_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.align_btn.setToolTip(u"执行一次 IKFK 对齐（调用大UI的对齐逻辑）")
        self.align_btn.clicked.connect(self._run_align_once)
        self.align_btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        key_layout.addWidget(self.align_btn, 0, 3)

        self.clear_footstep_btn = QtWidgets.QPushButton(u"清理踩踏标记")
        self.clear_footstep_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.clear_footstep_btn.setToolTip(u"删除选中控制器上的踩踏标记属性（ADV_Footstep）及其关键帧")
        self.clear_footstep_btn.clicked.connect(self._clear_footstep_attrs)
        self.clear_footstep_btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        key_layout.addWidget(self.clear_footstep_btn, 1, 0, 1, 2)

        self.diag_undo_btn = QtWidgets.QPushButton(u"撤回诊断")
        self.diag_undo_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.diag_undo_btn.setToolTip(u"检测 BIP/书签相关逻辑是否把 Undo 状态卡死，并做一次安全的 undo/redo 回环测试")
        self.diag_undo_btn.clicked.connect(self._on_diagnose_undo)
        self.diag_undo_btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        key_layout.addWidget(self.diag_undo_btn, 1, 2, 1, 2)

        main_layout.addWidget(mode_group)
        main_layout.addWidget(bookmark_group)
        main_layout.addWidget(key_group)

    def _on_diagnose_undo(self):
        try:
            diagnose_undo(layer_tool=self)
        except Exception:
            try:
                cmds.warning(u"[ADV][帧标记] 撤回诊断执行失败，请查看 Script Editor。")
            except Exception:
                pass

    def _on_auto_align_check_changed(self, state):
        self._auto_align_enabled = bool(state == QtCore.Qt.Checked)
        self._auto_add_attr_enabled = bool(self._auto_align_enabled)

    def _clear_footstep_attrs(self):
        selection = cmds.ls(sl=True) or []
        if not selection:
            cmds.warning(u"请先选择控制器")
            return

        transforms = []
        for n in selection:
            try:
                if cmds.nodeType(n) == 'transform':
                    transforms.append(n)
                    continue
            except Exception:
                pass
            parent = (cmds.listRelatives(n, parent=True, fullPath=True) or [None])[0]
            if parent and cmds.objExists(parent):
                transforms.append(parent)
        seen = set()
        transforms = [t for t in transforms if not (t in seen or seen.add(t))]

        for ctrl in transforms:
            if not ctrl or not cmds.objExists(ctrl):
                continue
            try:
                if not cmds.attributeQuery(FOOTSTEP_ATTR, node=ctrl, exists=True):
                    continue
            except Exception:
                continue
            plug = '{}.{}'.format(ctrl, FOOTSTEP_ATTR)
            try:
                cmds.cutKey(plug, clear=True)
            except Exception:
                pass
            try:
                cmds.deleteAttr(ctrl, attribute=FOOTSTEP_ATTR)
            except Exception:
                pass

        # Clear local records/bookmarks for current selection.
        try:
            for ctrl in transforms:
                keys = [k for k in self._footsteps.keys() if k[0] == ctrl]
                for k in keys:
                    self._footsteps.pop(k, None)
        except Exception:
            pass
        try:
            self._refresh_footstep_bookmarks_for_selection()
        except Exception:
            pass

    def _on_bip_check_changed(self, state):
        enabled = bool(state)
        try:
            from . import adv_bip_time_slider_overlay
        except Exception:
            try:
                import adv_bip_time_slider_overlay
            except Exception:
                adv_bip_time_slider_overlay = None

        if not adv_bip_time_slider_overlay:
            try:
                cmds.warning(u"BIP模式：无法导入 adv_bip_time_slider_overlay")
            except Exception:
                pass
            return

        try:
            if enabled:
                # Reload to pick up on-disk tweaks without restarting Maya.
                try:
                    import importlib
                    adv_bip_time_slider_overlay = importlib.reload(adv_bip_time_slider_overlay)
                except Exception:
                    pass
                ok = bool(adv_bip_time_slider_overlay.install(bip_mode=True, force=True))
                if not ok:
                    cmds.warning(u"BIP模式：无法找到时间滑块控件（$gPlayBackSlider）")
                    enabled = False
            else:
                adv_bip_time_slider_overlay.uninstall()
                try:
                    adv_bip_time_slider_overlay.clear_bip_bookmarks()
                except Exception:
                    pass
        except Exception:
            pass

        # When BIP mode is turned off, also stop & clear footstep markers.
        if not enabled:
            try:
                self._footsteps.clear()
            except Exception:
                pass
            try:
                self._clear_footstep_bookmarks()
            except Exception:
                pass

        self._bip_overlay_enabled = enabled

        # Auto-align toggle is only meaningful in BIP mode.
        try:
            if hasattr(self, 'auto_align_check'):
                self.auto_align_check.setEnabled(bool(enabled))
                if not enabled:
                    self.auto_align_check.blockSignals(True)
                    self.auto_align_check.setChecked(False)
                    self.auto_align_check.blockSignals(False)
                    self._auto_align_enabled = False
        except Exception:
            pass

        # Follow triggers only after user finishes dragging (no continuous snapping).
        if enabled:
            try:
                if self._bip_drag_job_id is None or (not cmds.scriptJob(exists=self._bip_drag_job_id)):
                    self._bip_drag_job_id = cmds.scriptJob(
                        event=["DragRelease", self._on_bip_drag_release],
                        compressUndo=False,
                        protected=True,
                    )
            except Exception:
                self._bip_drag_job_id = None
            # Rebuild orange footstep bookmarks for current selection.
            try:
                self._rebuild_footsteps_from_attr()
                self._refresh_footstep_bookmarks_for_selection()
            except Exception:
                pass
        else:
            try:
                if self._bip_drag_job_id is not None and cmds.scriptJob(exists=self._bip_drag_job_id):
                    cmds.scriptJob(kill=self._bip_drag_job_id, force=True)
            except Exception:
                pass
            self._bip_drag_job_id = None

    def _on_bip_drag_release(self, *args):
        """Safe wrapper for DragRelease to prevent Traceback spam in Script Editor."""
        try:
            if self._bip_follow_deferred:
                return
            self._bip_follow_deferred = True

            def _do_follow_deferred():
                try:
                    self._bip_follow_deferred = False
                except Exception:
                    pass
                if not self._bip_overlay_enabled:
                    return

                prev_undo_state = None
                try:
                    prev_undo_state = bool(cmds.undoInfo(q=True, state=True))
                except Exception:
                    prev_undo_state = None
                try:
                    if prev_undo_state is not False:
                        cmds.undoInfo(state=False)
                except Exception:
                    pass
                try:
                    with _undo_suspend_without_flush():
                        self._update_footsteps_follow(_undo=False)
                finally:
                    try:
                        if prev_undo_state is not None:
                            cmds.undoInfo(state=bool(prev_undo_state))
                    except Exception:
                        pass

            try:
                import maya.utils as _maya_utils
                _maya_utils.executeDeferred(_do_follow_deferred)
            except Exception:
                try:
                    _do_follow_deferred()
                except Exception:
                    pass
        except Exception:
            try:
                import time
                import traceback
                now = float(time.time())
                sig = traceback.format_exc()
            except Exception:
                now = 0.0
                sig = 'BIP follow error'

            # Throttle same error spam.
            try:
                if sig == self._bip_follow_error_last_sig and (now - float(self._bip_follow_error_last_time or 0.0)) < 1.0:
                    return
            except Exception:
                pass

            try:
                self._bip_follow_error_last_sig = sig
                self._bip_follow_error_last_time = now
            except Exception:
                pass

            # Print once for debugging, then disable follow to stop repeated callbacks.
            try:
                print(sig)
            except Exception:
                pass

            try:
                if self._bip_drag_job_id is not None and cmds.scriptJob(exists=self._bip_drag_job_id):
                    cmds.scriptJob(kill=self._bip_drag_job_id, force=True)
            except Exception:
                pass
            self._bip_drag_job_id = None

            try:
                cmds.warning(u"帧标记：踩踏跟随发生异常，已暂停跟随（避免刷屏）。请把 Script Editor 里第一条 Traceback 发我。")
            except Exception:
                pass

    def _clear_footstep_bookmarks(self):
        """Delete all orange footstep bookmarks created by this tool."""
        try:
            all_bookmarks = cmds.ls(type='timeSliderBookmark') or []
        except Exception:
            all_bookmarks = []

        to_delete = []
        for bm in all_bookmarks:
            try:
                if self._short_name(bm).startswith(FOOTSTEP_PREFIX):
                    to_delete.append(bm)
                    continue
            except Exception:
                pass
            try:
                n = cmds.getAttr(bm + '.name')
                if isinstance(n, str) and n.startswith(FOOTSTEP_PREFIX):
                    to_delete.append(bm)
                    continue
            except Exception:
                pass

        if to_delete:
            try:
                cmds.delete(list(set(to_delete)))
            except Exception:
                pass

    def _shutdown(self):
        """Best-effort cleanup so no timers/overlays/bookmarks are left behind."""
        # Stop jobs/timers.
        try:
            self._stop_auto_detect()
        except Exception:
            pass
        try:
            if self._bip_drag_job_id is not None and cmds.scriptJob(exists=self._bip_drag_job_id):
                cmds.scriptJob(kill=self._bip_drag_job_id, force=True)
        except Exception:
            pass
        self._bip_drag_job_id = None

        # Ensure BIP overlay is uninstalled even if checkbox stateChanged doesn't fire.
        try:
            from . import adv_bip_time_slider_overlay
        except Exception:
            try:
                import adv_bip_time_slider_overlay
            except Exception:
                adv_bip_time_slider_overlay = None
        if adv_bip_time_slider_overlay is not None:
            try:
                adv_bip_time_slider_overlay.uninstall()
            except Exception:
                pass
            try:
                adv_bip_time_slider_overlay.clear_bip_bookmarks()
            except Exception:
                pass

        try:
            self._bip_overlay_enabled = False
        except Exception:
            pass
        try:
            if hasattr(self, 'bip_check'):
                self.bip_check.blockSignals(True)
                self.bip_check.setChecked(False)
                self.bip_check.blockSignals(False)
        except Exception:
            try:
                self.bip_check.blockSignals(False)
            except Exception:
                pass

        # Remove bookmarks created by this tool.
        try:
            self._clear_footstep_bookmarks()
        except Exception:
            pass
        try:
            self._clear_layer_bookmarks()
        except Exception:
            pass
        try:
            self._footsteps.clear()
        except Exception:
            pass

    def _run_align_once(self, *_, **kwargs):
        """Run one-shot IKFK alignment (same logic as the big UI)."""
        _undo = bool(kwargs.get('_undo', True))
        if _undo:
            with _undo_chunk(u"帧标记-对齐"):
                return self._run_align_once(_undo=False)
        # 1) Prefer ADV's built-in align function if available.
        try:
            import importlib
            for mod_name in ('ADV_extension',):
                try:
                    mod = importlib.import_module(mod_name)
                except Exception:
                    mod = None
                if mod is None:
                    continue
                if hasattr(mod, 'run_ikfk_align_only'):
                    mod.run_ikfk_align_only()
                    return
                if hasattr(mod, 'run_ikfk_align'):
                    mod.run_ikfk_align()
                    return
        except Exception:
            pass

        # 2) Fallback to AutoIKFKAlign tool (if bundled).
        try:
            import importlib
            for mod_name in ('auto_ikfk_align', 'AutoIKFKAlign.auto_ikfk_align'):
                try:
                    aik = importlib.import_module(mod_name)
                except Exception:
                    aik = None
                if aik is None:
                    continue
                if hasattr(aik, 'auto_ikfk_align'):
                    aik.auto_ikfk_align()
                    return
                if hasattr(aik, 'show'):
                    aik.show()
                    return
        except Exception:
            pass

        try:
            cmds.warning(u"对齐：未找到可用的对齐入口（ADV_extension / auto_ikfk_align）")
        except Exception:
            pass

    def _on_auto_check_changed(self, state):
        if state == QtCore.Qt.Checked:
            if not BOOKMARK_SUPPORTED:
                cmds.warning(u"timeSliderBookmark 需要 Maya 2020 或更高版本")
                try:
                    cmds.inViewMessage(
                        amg=u'<span style="color:#e74c3c;">需要 Maya 2020+ 版本</span>',
                        pos='topCenter',
                        fade=True,
                        fadeStayTime=2000,
                    )
                except Exception:
                    pass
                self.auto_check.setChecked(False)
                return
            self._start_auto_detect()
        else:
            self._stop_auto_detect()

    def _start_auto_detect(self):
        self._stop_auto_detect()

        self._start_listen_animlayer_created()

        self._selection_job_id = cmds.scriptJob(
            event=["SelectionChanged", self._on_selection_changed],
            protected=True,
        )

        layers = self._get_all_anim_layers()
        if layers:
            self._setup_layer_watchers(layers)

        if not self._poll_timer.isActive():
            self._poll_timer.start()

        self._on_selection_changed()

    def _poll_refresh(self):
        if not self.auto_check.isChecked():
            return
        self._on_selection_changed()

    def _setup_layer_watchers(self, layers):
        for layer in layers:
            try:
                j1 = cmds.scriptJob(
                    attributeChange=["{}.selected".format(layer), self._on_layer_changed],
                    protected=True,
                )
                j2 = cmds.scriptJob(
                    attributeChange=["{}.preferred".format(layer), self._on_layer_changed],
                    protected=True,
                )
                self._layer_job_ids.extend([j1, j2])
            except Exception:
                pass

    def _start_listen_animlayer_created(self):
        self._stop_listen_animlayer_created()

        def _on_node_added(mobj, clientData):
            fn = om.MFnDependencyNode(mobj)
            if fn.typeName == "animLayer":
                cmds.evalDeferred(self._refresh_layer_watchers)

        self._animlayer_create_cb = om.MDGMessage.addNodeAddedCallback(_on_node_added, "animLayer")

    def _stop_listen_animlayer_created(self):
        if self._animlayer_create_cb is not None:
            try:
                om.MMessage.removeCallback(self._animlayer_create_cb)
            except Exception:
                pass
            self._animlayer_create_cb = None

    def _refresh_layer_watchers(self):
        for jid in self._layer_job_ids:
            try:
                if cmds.scriptJob(exists=jid):
                    cmds.scriptJob(kill=jid, force=True)
            except Exception:
                pass
        self._layer_job_ids = []

        layers = self._get_all_anim_layers()
        if layers:
            if self._selection_job_id is None:
                self._selection_job_id = cmds.scriptJob(
                    event=["SelectionChanged", self._on_selection_changed],
                    protected=True,
                )
            self._setup_layer_watchers(layers)

        self._on_selection_changed()

    def _get_all_anim_layers(self):
        root = cmds.animLayer(q=True, root=True)
        if not root:
            return []
        layers, queue, seen = [], [root], set()
        while queue:
            lyr = queue.pop(0)
            if lyr in seen or not cmds.objExists(lyr):
                continue
            seen.add(lyr)
            layers.append(lyr)
            kids = cmds.animLayer(lyr, q=True, children=True) or []
            if isinstance(kids, str):
                kids = [kids]
            queue.extend(kids)
        return layers

    def _stop_auto_detect(self):
        try:
            if self._poll_timer.isActive():
                self._poll_timer.stop()
        except Exception:
            pass

        if self._selection_job_id is not None:
            try:
                if cmds.scriptJob(exists=self._selection_job_id):
                    cmds.scriptJob(kill=self._selection_job_id, force=True)
            except Exception:
                pass
            self._selection_job_id = None

        for jid in self._layer_job_ids:
            try:
                if cmds.scriptJob(exists=jid):
                    cmds.scriptJob(kill=jid, force=True)
            except Exception:
                pass
        self._layer_job_ids = []

        self._stop_listen_animlayer_created()

    def _on_layer_changed(self):
        self._on_selection_changed()

    def _on_selection_changed(self):
        # Footstep markers are recorded during BIP, but *displayed* only for current selection.
        try:
            sel_long = cmds.ls(sl=True, long=True) or []
            sig = tuple(sorted(sel_long))
        except Exception:
            sig = None
        if sig != self._last_selection_sig:
            self._last_selection_sig = sig
            if self._bip_overlay_enabled:
                try:
                    self._rebuild_footsteps_from_attr()
                    self._refresh_footstep_bookmarks_for_selection()
                except Exception:
                    pass

        keyframes = self._get_root_layer_keyframes()
        if keyframes != self._last_keyframes:
            self._last_keyframes = keyframes
            self._update_bookmarks(keyframes)

    def _get_animlayer_root(self):
        try:
            return cmds.animLayer(q=True, root=True)
        except Exception:
            return None

    def _keys_of_object_on_layer(self, obj, layer):
        plugs = cmds.listAnimatable(obj) or []
        if isinstance(plugs, str):
            plugs = [plugs]

        curves = set()
        for plug in plugs:
            try:
                c = cmds.animLayer(layer, q=True, findCurveForPlug=plug)
            except Exception:
                c = None
            if not c:
                continue

            if isinstance(c, (list, tuple)):
                for cc in c:
                    if cc and cmds.objExists(cc):
                        curves.add(cc)
            else:
                if cmds.objExists(c):
                    curves.add(c)

        times = set()
        for c in curves:
            for t in (cmds.keyframe(c, q=True, timeChange=True) or []):
                times.add(int(t))

        return sorted(times)

    def _get_root_layer_keyframes(self):
        selection = cmds.ls(sl=True, long=True) or []
        if not selection:
            return []

        root = self._get_animlayer_root()
        if not root:
            return []

        all_keyframes = set()
        for obj in selection:
            keys = self._keys_of_object_on_layer(obj, root)
            all_keyframes.update(keys)

        return sorted(all_keyframes)

    def _update_bookmarks(self, keyframes):
        if not BOOKMARK_SUPPORTED:
            return
        with _undo_suspend_without_flush():
            self._clear_layer_bookmarks()
            if not keyframes:
                return

            # 检测当前选择的物体中是否有四肢控制器，从而推导 FKIK 开关
            selection = cmds.ls(sl=True, long=True) or []
            transforms = [x for x in selection if cmds.nodeType(x) == 'transform']
            switches = self._detect_limb_switches_from_selection(transforms)

            # 查询这些开关上的关键帧及其值，找出值 >= 9.999 的帧 → 黄色
            yellow_frames = set()
            attr_candidates = ['FKIKBlend', 'fkikblend', 'fkIkBlend', 'FKIKblend']
            for sw in switches:
                for attr_name in attr_candidates:
                    full_attr = sw + '.' + attr_name
                    if not cmds.objExists(full_attr):
                        continue
                    t = cmds.keyframe(full_attr, q=True, timeChange=True) or []
                    v = cmds.keyframe(full_attr, q=True, valueChange=True) or []
                    for tt, vv in zip(t, v):
                        if float(vv) >= 9.999:
                            yellow_frames.add(int(round(float(tt))))
                    break  # 找到匹配的属性就停止

            for i, frame in enumerate(keyframes):
                bookmark_name = "{}{}".format(BOOKMARK_PREFIX, i)
                try:
                    bm = cmds.createNode('timeSliderBookmark', name=bookmark_name, skipSelect=True)
                    cmds.setAttr(bm + '.name', '{}F{}'.format(BOOKMARK_PREFIX, frame), type='string')
                    cmds.setAttr(bm + '.timeRangeStart', frame)
                    cmds.setAttr(bm + '.timeRangeStop', frame)
                    
                    # 设置颜色：黄色 = (1, 0.8, 0)；否则默认（灰色）
                    if frame in yellow_frames:
                        cmds.setAttr(bm + '.color', 1.0, 0.8, 0.0, type='double3')
                except Exception:
                    pass

    def _get_keyframes(self):
        keyframes = set()
        try:
            selection = cmds.ls(selection=True)
            if not selection:
                cmds.warning(u"请先选择对象")
                return []

            for obj in selection:
                all_curves = cmds.listConnections(obj, type='animCurve') or []

                attrs = cmds.listAttr(obj, keyable=True) or []
                for attr in attrs:
                    try:
                        full_attr = "{}.{}".format(obj, attr)
                        curves = cmds.listConnections(full_attr, type='animCurve') or []
                        all_curves.extend(curves)
                    except Exception:
                        pass

                blends = cmds.listConnections(obj, type='animBlendNodeBase') or []
                for blend in blends:
                    curves = cmds.listConnections(blend, type='animCurve') or []
                    all_curves.extend(curves)

                all_curves = list(set(all_curves))

                for curve in all_curves:
                    keys = cmds.keyframe(curve, query=True, timeChange=True) or []
                    for k in keys:
                        keyframes.add(int(k))

        except Exception as e:
            print(u"获取关键帧时出错: {}".format(e))

        return sorted(keyframes)

    def _on_create_bookmarks(self, *_args, **kwargs):
        _undo = bool(kwargs.get('_undo', True))
        if _undo:
            with _undo_chunk(u"帧标记-创建层书签"):
                return self._on_create_bookmarks(_undo=False)
        if not BOOKMARK_SUPPORTED:
            cmds.warning(u"timeSliderBookmark 需要 Maya 2020 或更高版本")
            try:
                cmds.inViewMessage(
                    amg=u'<span style="color:#e74c3c;">需要 Maya 2020+ 版本</span>',
                    pos='topCenter',
                    fade=True,
                    fadeStayTime=2000,
                )
            except Exception:
                pass
            return

        keyframes = self._get_keyframes()
        if not keyframes:
            cmds.warning(u"没有找到关键帧")
            return

        # 检测当前选择的物体中是否有四肢控制器，从而推导 FKIK 开关
        selection = cmds.ls(sl=True, long=True) or []
        transforms = [x for x in selection if cmds.nodeType(x) == 'transform']
        switches = self._detect_limb_switches_from_selection(transforms)

        # 查询这些开关上的关键帧及其值，找出值 >= 9.999 的帧 → 黄色
        yellow_frames = set()
        attr_candidates = ['FKIKBlend', 'fkikblend', 'fkIkBlend', 'FKIKblend']
        for sw in switches:
            for attr_name in attr_candidates:
                full_attr = sw + '.' + attr_name
                if not cmds.objExists(full_attr):
                    continue
                t = cmds.keyframe(full_attr, q=True, timeChange=True) or []
                v = cmds.keyframe(full_attr, q=True, valueChange=True) or []
                for tt, vv in zip(t, v):
                    if float(vv) >= 9.999:
                        yellow_frames.add(int(round(float(tt))))
                break  # 找到匹配的属性就停止

        with _undo_suspend_without_flush():
            self._clear_layer_bookmarks()
            for i, frame in enumerate(keyframes):
                bookmark_name = "{}{}".format(BOOKMARK_PREFIX, i)
                try:
                    bm = cmds.createNode('timeSliderBookmark', name=bookmark_name, skipSelect=True)
                    cmds.setAttr(bm + '.name', '{}F{}'.format(BOOKMARK_PREFIX, frame), type='string')
                    cmds.setAttr(bm + '.timeRangeStart', frame)
                    cmds.setAttr(bm + '.timeRangeStop', frame)
                    
                    # 设置颜色：黄色 = (1, 0.8, 0)；否则默认（灰色）
                    if frame in yellow_frames:
                        cmds.setAttr(bm + '.color', 1.0, 0.8, 0.0, type='double3')
                except Exception:
                    pass

        try:
            cmds.inViewMessage(
                amg=u'<span style="color:#27ae60;">已创建 {} 个书签</span>'.format(len(keyframes)),
                pos='topCenter',
                fade=True,
                fadeStayTime=1500,
            )
        except Exception:
            pass

    def _clear_layer_bookmarks(self):
        try:
            all_bookmarks = cmds.ls(type='timeSliderBookmark') or []
            to_delete = [bm for bm in all_bookmarks if BOOKMARK_PREFIX in bm]
            if to_delete:
                cmds.delete(to_delete)
        except Exception:
            pass

    def _on_clear_bookmarks(self, *_args, **kwargs):
        _undo = bool(kwargs.get('_undo', True))
        if _undo:
            with _undo_chunk(u"帧标记-清除层书签"):
                return self._on_clear_bookmarks(_undo=False)
        self._clear_layer_bookmarks()
        self._last_keyframes = []
        try:
            cmds.inViewMessage(
                amg=u'<span style="color:#e74c3c;">书签已清除</span>',
                pos='topCenter',
                fade=True,
                fadeStayTime=1500,
            )
        except Exception:
            pass

    def closeEvent(self, event):
        self._shutdown()
        super(LayerBookmarkTool, self).closeEvent(event)


_CMDS_WIN = 'ADV_LayerBookmarkTool_Cmds'


def _short_name(node):
    name = (node or '').split('|')[-1]
    if ':' in name:
        name = name.rsplit(':', 1)[-1]
    return name


def _namespace(node):
    name = (node or '').split('|')[-1]
    if ':' in name:
        return name.rsplit(':', 1)[0] + ':'
    return ''


def _detect_limb_switches_from_selection(selection):
    arm_bases = {u"FKShoulder", u"FKElbow", u"FKWrist", u"IKArm", u"PoleArm"}
    leg_bases = {u"FKHip", u"FKKnee", u"FKAnkle", u"IKLeg", u"PoleLeg", u"IKFoot", u"PoleFoot"}
    attr_candidates = ['FKIKBlend', 'fkikblend', 'fkIkBlend', 'FKIKblend']

    switches = set()
    for n in (selection or []):
        short = _short_name(n)

        # If user selects FKIK switch itself, accept it directly.
        try:
            for a in attr_candidates:
                if cmds.attributeQuery(a, node=n, exists=True):
                    switches.add(n)
                    break
        except Exception:
            pass

        if not short.endswith(('_L', '_R')):
            continue
        side = short[-2:]
        base = short[:-2]

        limb = None
        if base in arm_bases:
            limb = 'Arm'
        elif base in leg_bases:
            limb = 'Leg'
        if not limb:
            continue

        ns = _namespace(n)
        sw = ns + 'FKIK{}{}'.format(limb, side)

        ok = False
        try:
            for a in attr_candidates:
                if cmds.attributeQuery(a, node=sw, exists=True):
                    ok = True
                    break
        except Exception:
            ok = False

        if ok:
            switches.add(sw)

    return switches


def _clear_layer_bookmarks_cmds():
    try:
        all_bookmarks = cmds.ls(type='timeSliderBookmark') or []
        to_delete = [bm for bm in all_bookmarks if BOOKMARK_PREFIX in bm]
        if to_delete:
            cmds.delete(to_delete)
    except Exception:
        pass


def _keys_of_object_on_layer(obj, layer):
    plugs = cmds.listAnimatable(obj) or []
    if isinstance(plugs, str):
        plugs = [plugs]

    curves = set()
    for plug in plugs:
        try:
            c = cmds.animLayer(layer, q=True, findCurveForPlug=plug)
        except Exception:
            c = None
        if not c:
            continue

        if isinstance(c, (list, tuple)):
            for cc in c:
                if cc and cmds.objExists(cc):
                    curves.add(cc)
        else:
            if cmds.objExists(c):
                curves.add(c)

    times = set()
    for c in curves:
        for t in (cmds.keyframe(c, q=True, timeChange=True) or []):
            try:
                times.add(int(t))
            except Exception:
                pass

    return sorted(times)


def _get_root_layer_keyframes(selection_long):
    if not selection_long:
        return []

    try:
        root = cmds.animLayer(q=True, root=True)
    except Exception:
        root = None
    if not root:
        return []

    all_keyframes = set()
    for obj in selection_long:
        try:
            keys = _keys_of_object_on_layer(obj, root)
        except Exception:
            keys = []
        all_keyframes.update(keys)
    return sorted(all_keyframes)


def _get_all_keyframes(selection_short):
    keyframes = set()
    selection = selection_short or []
    for obj in selection:
        try:
            all_curves = cmds.listConnections(obj, type='animCurve') or []

            attrs = cmds.listAttr(obj, keyable=True) or []
            for attr in attrs:
                try:
                    full_attr = "{}.{}".format(obj, attr)
                    curves = cmds.listConnections(full_attr, type='animCurve') or []
                    all_curves.extend(curves)
                except Exception:
                    pass

            blends = cmds.listConnections(obj, type='animBlendNodeBase') or []
            for blend in blends:
                curves = cmds.listConnections(blend, type='animCurve') or []
                all_curves.extend(curves)

            all_curves = list(set(all_curves))
            for curve in all_curves:
                keys = cmds.keyframe(curve, query=True, timeChange=True) or []
                for k in keys:
                    try:
                        keyframes.add(int(k))
                    except Exception:
                        pass
        except Exception:
            pass
    return sorted(keyframes)


def _compute_yellow_frames_from_switches(switches):
    yellow_frames = set()
    attr_candidates = ['FKIKBlend', 'fkikblend', 'fkIkBlend', 'FKIKblend']
    for sw in (switches or []):
        for attr_name in attr_candidates:
            full_attr = sw + '.' + attr_name
            if not cmds.objExists(full_attr):
                continue
            t = cmds.keyframe(full_attr, q=True, timeChange=True) or []
            v = cmds.keyframe(full_attr, q=True, valueChange=True) or []
            for tt, vv in zip(t, v):
                try:
                    if float(vv) >= 9.999:
                        yellow_frames.add(int(round(float(tt))))
                except Exception:
                    pass
            break
    return yellow_frames


def _update_bookmarks_cmds(keyframes, selection_long=None):
    if not BOOKMARK_SUPPORTED:
        cmds.warning(u"timeSliderBookmark 需要 Maya 2020 或更高版本")
        return

    selection_long = selection_long or (cmds.ls(sl=True, long=True) or [])
    transforms = [x for x in selection_long if cmds.nodeType(x) == 'transform']
    switches = _detect_limb_switches_from_selection(transforms)
    yellow_frames = _compute_yellow_frames_from_switches(switches)

    with _undo_suspend_without_flush():
        _clear_layer_bookmarks_cmds()
        if not keyframes:
            return
        for i, frame in enumerate(keyframes):
            bookmark_name = "{}{}".format(BOOKMARK_PREFIX, i)
            try:
                bm = cmds.createNode('timeSliderBookmark', name=bookmark_name, skipSelect=True)
                cmds.setAttr(bm + '.name', '{}F{}'.format(BOOKMARK_PREFIX, frame), type='string')
                cmds.setAttr(bm + '.timeRangeStart', frame)
                cmds.setAttr(bm + '.timeRangeStop', frame)
                if frame in yellow_frames:
                    cmds.setAttr(bm + '.color', 1.0, 0.8, 0.0, type='double3')
            except Exception:
                pass


def _cmds_create_root_layer_bookmarks(*_):
    selection_long = cmds.ls(sl=True, long=True) or []
    if not selection_long:
        cmds.warning(u"请先选择对象")
        return
    frames = _get_root_layer_keyframes(selection_long)
    if not frames:
        cmds.warning(u"根动画层未找到关键帧")
        return
    with _undo_chunk(u"帧标记-创建层书签(根层)"):
        _update_bookmarks_cmds(frames, selection_long=selection_long)


def _cmds_create_all_key_bookmarks(*_):
    selection = cmds.ls(sl=True) or []
    if not selection:
        cmds.warning(u"请先选择对象")
        return
    frames = _get_all_keyframes(selection)
    if not frames:
        cmds.warning(u"没有找到关键帧")
        return
    with _undo_chunk(u"帧标记-创建层书签(全部)"):
        _update_bookmarks_cmds(frames)


def _cmds_clear_bookmarks(*_):
    with _undo_chunk(u"帧标记-清除层书签"):
        _clear_layer_bookmarks_cmds()


def _show_cmds_window():
    if cmds.window(_CMDS_WIN, exists=True):
        try:
            cmds.deleteUI(_CMDS_WIN)
        except Exception:
            pass

    title = u"帧标记 (简易模式)"
    if _QT_IMPORT_ERROR is not None:
        try:
            title = u"帧标记 (Qt不可用-简易模式)"
        except Exception:
            pass

    cmds.window(_CMDS_WIN, title=title, sizeable=False, widthHeight=(420, 160))
    cmds.columnLayout(adjustableColumn=True, rowSpacing=8, columnAlign='center')

    if _QT_IMPORT_ERROR is not None:
        cmds.text(
            label=u"检测到 PySide2/shiboken2 导入异常，已自动降级为 cmds 窗口。\n"
                  u"（不影响书签创建/清除；BIP/自动对齐等 Qt UI 功能不可用）",
            align='left'
        )

    cmds.rowLayout(numberOfColumns=3, adjustableColumn=1, columnAlign=(1, 'center'), columnAttach=[(1, 'both', 0), (2, 'both', 0), (3, 'both', 0)])
    cmds.button(label=u"创建/刷新(根动画层)", command=_cmds_create_root_layer_bookmarks, height=34)
    cmds.button(label=u"创建(全部关键帧)", command=_cmds_create_all_key_bookmarks, height=34)
    cmds.button(label=u"清除标记", command=_cmds_clear_bookmarks, height=34)
    cmds.setParent('..')

    cmds.rowLayout(numberOfColumns=1, adjustableColumn=1, columnAlign=(1, 'center'), columnAttach=[(1, 'both', 0)])
    cmds.button(label=u"撤回诊断", command=lambda *_: diagnose_undo(layer_tool=None), height=30)
    cmds.setParent('..')

    cmds.showWindow(_CMDS_WIN)
    return _CMDS_WIN


def show():
    global adv_layer_bookmark_window

    if not _QT_AVAILABLE:
        return _show_cmds_window()

    try:
        adv_layer_bookmark_window.close()
        adv_layer_bookmark_window.deleteLater()
    except Exception:
        pass

    adv_layer_bookmark_window = LayerBookmarkTool()
    adv_layer_bookmark_window.show()
    return adv_layer_bookmark_window


def do_set_frame():
    if not _QT_AVAILABLE:
        cmds.warning(u"当前 Maya 的 Qt(PySide2/shiboken2) 异常：仅能使用简易模式的书签创建/清除。")
        return _show_cmds_window()
    w = show()
    try:
        w._key_and_set_fkikblend(0)
    except Exception:
        pass


def do_slide_frame():
    if not _QT_AVAILABLE:
        cmds.warning(u"当前 Maya 的 Qt(PySide2/shiboken2) 异常：仅能使用简易模式的书签创建/清除。")
        return _show_cmds_window()
    w = show()
    try:
        w._key_and_set_fkikblend(10)
    except Exception:
        pass


def do_footstep_frame():
    if not _QT_AVAILABLE:
        cmds.warning(u"当前 Maya 的 Qt(PySide2/shiboken2) 异常：仅能使用简易模式的书签创建/清除。")
        return _show_cmds_window()
    w = show()
    try:
        w._key_and_align_footstep()
    except Exception:
        pass


def do_align_once():
    if not _QT_AVAILABLE:
        cmds.warning(u"当前 Maya 的 Qt(PySide2/shiboken2) 异常：仅能使用简易模式的书签创建/清除。")
        return _show_cmds_window()
    w = show()
    try:
        w._run_align_once()
    except Exception:
        pass


def install_hotkey_runtime_commands():
    """创建 Hotkey Editor 可映射的 runtimeCommand（默认不绑定按键）。"""
    with _undo_suspend_without_flush():
        try:
            cmds.runTimeCommand(
                'ADV_FrameMark_SetFrame',
                annotation=u'ADV 帧标记：设置帧',
                category='ADV',
                command='import adv_layer_bookmark_tool as m; m.do_set_frame()',
                commandLanguage='python',
            )
            cmds.runTimeCommand(
                'ADV_FrameMark_SlideFrame',
                annotation=u'ADV 帧标记：滑动帧',
                category='ADV',
                command='import adv_layer_bookmark_tool as m; m.do_slide_frame()',
                commandLanguage='python',
            )
            cmds.runTimeCommand(
                'ADV_FrameMark_FootstepFrame',
                annotation=u'ADV 帧标记：踩踏帧',
                category='ADV',
                command='import adv_layer_bookmark_tool as m; m.do_footstep_frame()',
                commandLanguage='python',
            )
            cmds.runTimeCommand(
                'ADV_FrameMark_AlignOnce',
                annotation=u'ADV 帧标记：对齐',
                category='ADV',
                command='import adv_layer_bookmark_tool as m; m.do_align_once()',
                commandLanguage='python',
            )
            try:
                cmds.inViewMessage(
                    amg=u'<span style="color:#27ae60;">已创建快捷键命令：Hotkey Editor 里搜索 ADV_FrameMark_*</span>',
                    pos='topCenter',
                    fade=True,
                    fadeStayTime=1800,
                )
            except Exception:
                pass
        except Exception as e:
            try:
                cmds.warning(u"创建快捷键命令失败: {}".format(e))
            except Exception:
                pass


def onMayaDroppedPythonFile(*args):
    show()


if __name__ == "__main__":
    show()
