# -*- coding: utf-8 -*-
"""
Curve Debugger (AnimBot Auto Tangent)
Auto-apply tangent operation after TRS manipulation settles.
"""

import os
import time

import maya.cmds as cmds
import maya.mel as mel
import maya.utils as maya_utils
import maya.api.OpenMaya as om2

try:
    from PySide2 import QtCore, QtWidgets, QtGui
    import shiboken2
    import maya.OpenMayaUI as omui
except ImportError:
    QtCore = None
    QtWidgets = None
    QtGui = None
    shiboken2 = None
    omui = None


class AnimBotAutoTangent(object):
    WINDOW_NAME = "advCurveDebuggerWin"
    WINDOW_TITLE = u"曲线调试"

    TANGENT_MODES = {
        "flow_tangent": ("Flow Tangent", "tangents_flowTangent"),
        "best_guess_tangent": ("Best Guess Tangent", "tangents_bestGuessTangent"),
        "polished_tangent": ("Polished Tangent", "tangents_polishedTangent"),
        "cycle_match_tangent": ("Cycle Match Tangent", "tangents_cycleMatchTangent"),
        "bounce_tangent": ("Bounce Tangent", "tangents_bounceTangent"),
        "auto_tangent": {
            "label": "Maya Auto Ease",
            "kind": "maya",
            "mel": "keyTangent -e -itt autoease -ott autoease -animation objects graphEditor1FromOutliner;",
        },
        "step_tangent": {
            "label": "Maya Step",
            "kind": "maya",
            "mel": "keyTangent -e -ott step -animation objects graphEditor1FromOutliner;",
        },
        "blt": {
            "label": "Maya Linear",
            "kind": "maya",
            "mel": "keyTangent -e -itt linear -ott linear -animation objects graphEditor1FromOutliner;",
        },
        "spline_tangent": {
            "label": "Maya Spline",
            "kind": "maya",
            "mel": "keyTangent -e -itt spline -ott spline -animation objects graphEditor1FromOutliner;",
        },
    }

    def __init__(self):
        self.is_enabled = False
        self.script_jobs = []
        self.check_timer_job = None

        self._is_applying = False
        self._apply_scheduled = False

        self._maya_chunk_open = False
        self._maya_chunk_name = "ADV_CurveDebugger_AutoTangent"

        self._suppress_on_close = False

        self._mouse_filter = None
        self._mouse_down = False
        self._mouse_drag_started = False

        self._attr_cb_ids = {}
        self._pending_transform = False
        self._last_change_time = 0.0
        self._debounce_seconds = 0.25
        self._cooldown_until = 0.0
        self._cooldown_seconds = 0.35

        self._selected_mode = "best_guess_tangent"
        self._mode_buttons = {}

        self._btn_bg_default = (0.22, 0.22, 0.22)
        self._btn_bg_selected_animbot = (0.32, 0.55, 0.32)
        self._btn_bg_selected_maya = (0.22, 0.35, 0.62)

        self._qt_dialog = None
        self._animbot_available_cached = None

    def _mode_kind(self, mode_key):
        mode = self.TANGENT_MODES.get(mode_key)
        if isinstance(mode, dict):
            return mode.get("kind", "maya")
        return "animbot"

    def _mode_label(self, mode_key):
        mode = self.TANGENT_MODES.get(mode_key)
        if isinstance(mode, dict):
            return mode.get("label", mode_key)
        if isinstance(mode, (tuple, list)) and mode:
            return mode[0]
        return mode_key

    def _animbot_available(self):
        try:
            v = self._animbot_available_cached
        except Exception:
            v = None
        if v is not None:
            return bool(v)
        ok = False
        try:
            from animBot._api.core import CORE as _ANIMBOT_CORE  # noqa: F401
            ok = True
        except Exception:
            ok = False
        self._animbot_available_cached = bool(ok)
        return bool(ok)

    def _ui_dir(self):
        try:
            here = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            return ""
        return os.path.normpath(os.path.join(here, "..", "UI"))

    def _ensure_xbmlangpath(self):
        ui_dir = self._ui_dir()
        if not ui_dir:
            return
        entry = ui_dir.replace("\\", "/") + "/%B"
        current = os.environ.get("XBMLANGPATH", "")
        parts = [p for p in current.split(";") if p]
        if entry in parts:
            return
        os.environ["XBMLANGPATH"] = ";".join([entry] + parts)

    @staticmethod
    def _as_maya_path(path):
        return (path or "").replace("\\", "/")

    def _icon_path(self, mode_key):
        ui_dir = self._ui_dir()
        if not ui_dir:
            return ""
        p = os.path.join(ui_dir, mode_key + ".png")
        return self._as_maya_path(p) if os.path.exists(p) else ""

    def _icon_path_qt(self, mode_key):
        ui_dir = self._ui_dir()
        if not ui_dir:
            return ""
        p = os.path.join(ui_dir, mode_key + ".png")
        if not os.path.exists(p):
            return ""
        return os.path.abspath(p).replace("\\", "/")

    def on_drag_press(self):
        if (not self.is_enabled) or self._is_applying:
            return
        if (not self._maya_chunk_open) and self._mode_kind(self._selected_mode) == "maya":
            try:
                cmds.undoInfo(openChunk=True, chunkName=self._maya_chunk_name)
                self._maya_chunk_open = True
            except Exception:
                self._maya_chunk_open = False

    def _qt_available(self):
        return QtCore is not None and QtWidgets is not None and shiboken2 is not None and omui is not None

    def _maya_main_window(self):
        if not self._qt_available():
            return None
        ptr = omui.MQtUtil.mainWindow()
        if ptr is None:
            return None
        return shiboken2.wrapInstance(int(ptr), QtWidgets.QWidget)

    def _is_transform_context(self):
        try:
            ctx = cmds.currentCtx()
        except Exception:
            return False
        lower = (ctx or "").lower()
        if ("movesupercontext" in lower) or ("rotatesupercontext" in lower) or ("scalesupercontext" in lower):
            return True
        return ("move" in lower) or ("rotate" in lower) or ("scale" in lower)

    def _install_mouse_filter(self):
        if not self._qt_available():
            return False
        if self._mouse_filter is not None:
            return True

        owner = self

        class _MouseFilter(QtCore.QObject):
            def eventFilter(self, obj, event):
                if (not owner.is_enabled) or owner._is_applying:
                    return False
                et = event.type()
                if et not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease):
                    return False
                try:
                    panel = cmds.getPanel(withFocus=True)
                    if not panel or cmds.getPanel(typeOf=panel) != "modelPanel":
                        return False
                except Exception:
                    return False
                if not owner._is_transform_context():
                    return False
                try:
                    btn = event.button()
                except Exception:
                    btn = None
                if btn != QtCore.Qt.LeftButton:
                    return False
                if et == QtCore.QEvent.MouseButtonPress:
                    owner._mouse_down = True
                    owner._mouse_drag_started = False
                    return False
                if et == QtCore.QEvent.MouseMove:
                    if owner._mouse_down and (not owner._mouse_drag_started):
                        owner._mouse_drag_started = True
                        owner.on_drag_press()
                    return False
                if owner._mouse_down:
                    owner._mouse_down = False
                    owner._mouse_drag_started = False
                return False

        self._mouse_filter = _MouseFilter(self._maya_main_window())
        QtWidgets.QApplication.instance().installEventFilter(self._mouse_filter)
        return True

    def _remove_mouse_filter(self):
        if self._mouse_filter is None:
            return
        try:
            QtWidgets.QApplication.instance().removeEventFilter(self._mouse_filter)
        except Exception:
            pass
        self._mouse_filter = None

    def _ui_set_status(self, enabled):
        try:
            if isinstance(getattr(self, 'status_text', None), str):
                cmds.text(self.status_text, edit=True,
                          label=("状态: 开启" if enabled else "状态: 关闭"),
                          backgroundColor=([0.3, 0.6, 0.3] if enabled else [0.3, 0.3, 0.3]))
        except Exception:
            pass
        try:
            if isinstance(getattr(self, 'toggle_button', None), str):
                cmds.button(self.toggle_button, edit=True,
                            label=("关闭" if enabled else "开启"),
                            backgroundColor=([0.6, 0.4, 0.4] if enabled else [0.4, 0.6, 0.4]))
        except Exception:
            pass
        try:
            dlg = getattr(self, '_qt_dialog', None)
            if dlg is not None:
                dlg._sync_state()
        except Exception:
            pass

    def show_ui(self):
        if self._qt_available():
            try:
                return self.show_qt_ui()
            except Exception:
                pass

        if cmds.window(self.WINDOW_NAME, exists=True):
            self._suppress_on_close = True
            try:
                cmds.deleteUI(self.WINDOW_NAME, window=True)
            finally:
                self._suppress_on_close = False

        window = cmds.window(
            self.WINDOW_NAME,
            title=self.WINDOW_TITLE,
            widthHeight=(360, 240),
            sizeable=True,
            resizeToFitChildren=True
        )
        self._ensure_xbmlangpath()
        if (not self._animbot_available()) and self._mode_kind(self._selected_mode) == "animbot":
            self._selected_mode = "auto_tangent"
        cmds.columnLayout(adjustableColumn=True, rowSpacing=8, columnOffset=["both", 10])
        cmds.separator(height=10, style="none")

        self.status_text = cmds.text(
            label="状态: 关闭",
            align="center",
            font="boldLabelFont",
            backgroundColor=[0.3, 0.3, 0.3]
        )
        cmds.separator(height=5, style="none")
        self.toggle_button = cmds.button(
            label="开启",
            height=40,
            command=self.toggle_auto_tangent,
            backgroundColor=[0.4, 0.6, 0.4]
        )
        cmds.separator(height=5, style="none")
        cmds.text(label="开启后会在移动/旋转/缩放操作完成后\n自动调用曲线调整", align="center", font="smallPlainLabelFont")
        cmds.separator(height=6, style="none")

        cmds.text(label="Maya 曲线(点击选择):", align="center")
        cmds.separator(height=4, style="none")
        cmds.rowLayout(numberOfColumns=4, columnWidth4=(72, 72, 72, 72), height=72)
        self._mode_buttons = {}
        for k in ("auto_tangent", "step_tangent", "blt", "spline_tangent"):
            icon = self._icon_path(k)
            btn = cmds.iconTextButton(
                style="iconOnly",
                image1=icon if icon else "",
                annotation=self._mode_label(k),
                width=64,
                height=64,
                backgroundColor=self._btn_bg_default,
                command=lambda _=None, kk=k: self._set_selected_mode(kk)
            )
            self._mode_buttons[k] = btn
        cmds.setParent("..")

        cmds.separator(height=10, style="none")
        cmds.text(label="AnimBot 曲线(点击选择):", align="center")
        cmds.separator(height=4, style="none")

        cmds.rowLayout(numberOfColumns=5, columnWidth5=(72, 72, 72, 72, 72), height=72)
        animbot_ok = bool(self._animbot_available())
        for k in ("flow_tangent", "best_guess_tangent", "polished_tangent", "cycle_match_tangent", "bounce_tangent"):
            icon = self._icon_path(k)
            btn = cmds.iconTextButton(
                style="iconOnly",
                image1=icon if icon else "",
                annotation=(self._mode_label(k) if animbot_ok else (self._mode_label(k) + " (需要AnimBot)")),
                width=64,
                height=64,
                backgroundColor=self._btn_bg_default,
                enable=bool(animbot_ok),
                command=lambda _=None, kk=k: self._set_selected_mode(kk)
            )
            self._mode_buttons[k] = btn
        cmds.setParent("..")

        cmds.separator(height=10, style="none")
        cmds.showWindow(window)

        self._set_selected_mode(self._selected_mode, update_print=False)
        cmds.scriptJob(uiDeleted=[self.WINDOW_NAME, self.on_window_closed], parent=self.WINDOW_NAME)
        return window

    def show_qt_ui(self):
        existing = getattr(self, '_qt_dialog', None)
        if existing is not None:
            try:
                existing.raise_()
                existing.activateWindow()
                return existing
            except Exception:
                pass
        dlg = _AnimBotAutoTangentDialog(self, parent=self._maya_main_window())
        self._qt_dialog = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    def toggle_auto_tangent(self, *args):
        if self.is_enabled:
            self.disable_auto_tangent()
        else:
            self.enable_auto_tangent()

    def enable_auto_tangent(self):
        self.is_enabled = True
        self._ui_set_status(True)

        job_id = cmds.scriptJob(event=["SelectionChanged", self._on_selection_changed], protected=True)
        self.script_jobs.append(job_id)
        self._rebuild_attr_callbacks()

        try:
            self._install_mouse_filter()
        except Exception:
            pass

        self.check_timer_job = cmds.scriptJob(event=["idle", self._idle_tick], protected=True)
        self.script_jobs.append(self.check_timer_job)

    def disable_auto_tangent(self):
        self.is_enabled = False
        self._ui_set_status(False)

        for job_id in self.script_jobs:
            if cmds.scriptJob(exists=job_id):
                cmds.scriptJob(kill=job_id, force=True)
        self.script_jobs = []
        self.check_timer_job = None
        self._is_applying = False
        self._apply_scheduled = False

        self._pending_transform = False
        self._last_change_time = 0.0
        self._cooldown_until = 0.0
        self._clear_attr_callbacks()

        try:
            self._remove_mouse_filter()
        except Exception:
            pass

        if self._maya_chunk_open:
            try:
                cmds.undoInfo(closeChunk=True)
            except Exception:
                pass
            self._maya_chunk_open = False

    def on_window_closed(self):
        if self._suppress_on_close:
            return
        if self.is_enabled:
            self.disable_auto_tangent()
        try:
            self._qt_dialog = None
        except Exception:
            pass

    def _on_selection_changed(self):
        try:
            maya_utils.executeDeferred(self._rebuild_attr_callbacks)
        except Exception:
            self._rebuild_attr_callbacks()

    def _clear_attr_callbacks(self):
        for _node, cb_id in list(self._attr_cb_ids.items()):
            try:
                om2.MMessage.removeCallback(cb_id)
            except Exception:
                pass
        self._attr_cb_ids = {}

    def _rebuild_attr_callbacks(self):
        if not self.is_enabled:
            return
        self._clear_attr_callbacks()
        sel = cmds.ls(selection=True, long=True) or []
        for node in sel:
            try:
                sl = om2.MSelectionList()
                sl.add(node)
                mobj = sl.getDependNode(0)
            except Exception:
                continue

            def _cb(msg, plug, other_plug, clientData=None):
                if not (msg & om2.MNodeMessage.kAttributeSet):
                    return
                if self._is_applying:
                    return
                if time.time() < self._cooldown_until:
                    return
                try:
                    name = plug.partialName(useLongNames=True)
                except Exception:
                    return
                if name in ("translate", "rotate", "scale") or name.startswith("translate") or name.startswith("rotate") or name.startswith("scale"):
                    self._pending_transform = True
                    self._last_change_time = time.time()
                    if (not self._maya_chunk_open) and self._mode_kind(self._selected_mode) == "maya":
                        try:
                            cmds.undoInfo(openChunk=True, chunkName=self._maya_chunk_name)
                            self._maya_chunk_open = True
                        except Exception:
                            self._maya_chunk_open = False

            try:
                cb_id = om2.MNodeMessage.addAttributeChangedCallback(mobj, _cb)
                self._attr_cb_ids[node] = cb_id
            except Exception:
                pass

    def _idle_tick(self):
        if (not self.is_enabled) or self._is_applying:
            return
        if not self._pending_transform:
            return
        now = time.time()
        if (now - self._last_change_time) >= self._debounce_seconds:
            self._pending_transform = False
            self._schedule_tangent_adjustment()

    def _schedule_tangent_adjustment(self):
        if self._apply_scheduled or self._is_applying or (not self.is_enabled):
            return
        self._apply_scheduled = True

        def _run():
            self._apply_scheduled = False
            self.execute_tangent_adjustment()

        maya_utils.executeDeferred(_run)

    def execute_tangent_adjustment(self):
        if (not self.is_enabled) or self._is_applying:
            return
        self._is_applying = True
        self._pending_transform = False
        self._last_change_time = 0.0
        try:
            selection = cmds.ls(selection=True)
            if not selection:
                return

            mode = self.TANGENT_MODES.get(self._selected_mode, self.TANGENT_MODES["best_guess_tangent"])
            if isinstance(mode, dict) and mode.get("kind") == "maya":
                mel_cmd = mode.get("mel", "")
                if not mel_cmd:
                    raise RuntimeError("Missing MEL command for mode: {0}".format(self._selected_mode))
                self._cooldown_until = time.time() + self._cooldown_seconds
                try:
                    mel.eval(mel_cmd)
                finally:
                    if self._maya_chunk_open:
                        try:
                            cmds.undoInfo(closeChunk=True)
                        except Exception:
                            pass
                        self._maya_chunk_open = False
            else:
                if not self._animbot_available():
                    try:
                        cmds.warning(u"[ADV][曲线调试] 未检测到 AnimBot，无法执行 AnimBot 曲线。")
                    except Exception:
                        pass
                    return
                self._cooldown_until = time.time() + self._cooldown_seconds
                prev_undo_enabled = None
                try:
                    prev_undo_enabled = om2.MGlobal.isUndoEnabled()
                    om2.MGlobal.setUndoEnabled(False)
                except Exception:
                    prev_undo_enabled = None
                try:
                    from animBot._api.core import CORE as ANIMBOT_CORE
                    _label, trigger_name = mode if isinstance(mode, (tuple, list)) else ("Best Guess Tangent", "tangents_bestGuessTangent")
                    trigger_fn = getattr(ANIMBOT_CORE.trigger, trigger_name, None)
                    if trigger_fn is None:
                        raise RuntimeError("AnimBot trigger not found: {0}".format(trigger_name))
                    trigger_fn()
                finally:
                    try:
                        if prev_undo_enabled is not None:
                            om2.MGlobal.setUndoEnabled(prev_undo_enabled)
                    except Exception:
                        pass
        finally:
            self._is_applying = False
            if self._maya_chunk_open:
                try:
                    cmds.undoInfo(closeChunk=True)
                except Exception:
                    pass
                self._maya_chunk_open = False

    def _set_selected_mode(self, mode_key, update_print=True):
        if mode_key not in self.TANGENT_MODES:
            return
        if self._mode_kind(mode_key) == "animbot" and (not self._animbot_available()):
            try:
                cmds.warning(u"[ADV][曲线调试] 未检测到 AnimBot：AnimBot 模式不可用。")
            except Exception:
                pass
            return
        prev_kind = self._mode_kind(self._selected_mode)
        self._selected_mode = mode_key
        if self._maya_chunk_open and prev_kind == "maya" and self._mode_kind(self._selected_mode) != "maya":
            try:
                cmds.undoInfo(closeChunk=True)
            except Exception:
                pass
            self._maya_chunk_open = False

        selected_kind = self._mode_kind(self._selected_mode)
        selected_color = self._btn_bg_selected_maya if selected_kind == "maya" else self._btn_bg_selected_animbot
        for k, btn in (self._mode_buttons or {}).items():
            try:
                cmds.iconTextButton(
                    btn,
                    e=True,
                    backgroundColor=selected_color if k == self._selected_mode else self._btn_bg_default,
                )
            except Exception:
                pass
        try:
            dlg = getattr(self, '_qt_dialog', None)
            if dlg is not None:
                dlg._sync_mode_buttons()
        except Exception:
            pass


if QtWidgets is not None:
    class _AnimBotAutoTangentDialog(QtWidgets.QDialog):
        def __init__(self, tool, parent=None):
            super(_AnimBotAutoTangentDialog, self).__init__(parent)
            self._tool = tool
            self.setObjectName("advCurveDebuggerQtWin")
            self.setWindowTitle(tool.WINDOW_TITLE)
            self.setWindowFlags(self.windowFlags() | QtCore.Qt.Window)
            self.setMinimumWidth(420)

            self._status = QtWidgets.QLabel()
            self._status.setAlignment(QtCore.Qt.AlignCenter)
            self._status.setMinimumHeight(24)

            self._toggle = QtWidgets.QPushButton()
            self._toggle.setMinimumHeight(34)
            self._toggle.clicked.connect(self._on_toggle_clicked)

            self._desc = QtWidgets.QLabel(u"开启后会在移动/旋转/缩放操作完成后\n自动调用曲线调整")
            self._desc.setAlignment(QtCore.Qt.AlignCenter)

            self._maya_group = QtWidgets.QGroupBox(u"Maya 曲线(点击选择)")
            self._animbot_group = QtWidgets.QGroupBox(u"AnimBot 曲线(点击选择)")

            self._mode_btns = {}
            self._mode_group = QtWidgets.QButtonGroup(self)
            self._mode_group.setExclusive(True)

            self._build_mode_buttons(self._maya_group, ("auto_tangent", "step_tangent", "blt", "spline_tangent"), columns=4)
            self._build_mode_buttons(self._animbot_group, ("flow_tangent", "best_guess_tangent", "polished_tangent", "cycle_match_tangent", "bounce_tangent"), columns=5)

            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(12, 12, 12, 12)
            lay.setSpacing(10)
            lay.addWidget(self._status)
            lay.addWidget(self._toggle)
            lay.addWidget(self._desc)
            lay.addWidget(self._maya_group)
            lay.addWidget(self._animbot_group)

            self.setStyleSheet(self._style_sheet())
            self._sync_state()
            self._sync_mode_buttons()

        def _style_sheet(self):
            return (
                "QDialog{background:#2b2b2b;color:#d6d6d6;}"
                "QGroupBox{border:1px solid #3b3b3b;border-radius:6px;margin-top:10px;padding:10px;}"
                "QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}"
                "QLabel{color:#d6d6d6;}"
                "QLabel#statusOn{background:#2f5f2f;border-radius:6px;padding:6px;font-weight:600;}"
                "QLabel#statusOff{background:#3a3a3a;border-radius:6px;padding:6px;font-weight:600;}"
                "QPushButton{border:none;border-radius:6px;padding:8px;font-weight:700;}"
                "QPushButton#btnOn{background:#8a3a34;color:#ffffff;}"
                "QPushButton#btnOff{background:#2f6a3a;color:#ffffff;}"
                "QToolButton{background:#383838;border:1px solid #3f3f3f;border-radius:6px;padding:4px;}"
                "QToolButton:hover{border:1px solid #5b5b5b;}"
            )

        def _build_mode_buttons(self, group_box, mode_keys, columns):
            grid = QtWidgets.QGridLayout(group_box)
            grid.setContentsMargins(8, 16, 8, 8)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(8)
            r = 0
            c = 0
            for key in mode_keys:
                btn = QtWidgets.QToolButton()
                btn.setCheckable(True)
                btn.setAutoRaise(False)
                try:
                    btn.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
                except Exception:
                    pass
                btn.setToolTip(self._tool._mode_label(key))
                btn.setFixedSize(72, 72)
                icon_path = self._tool._icon_path_qt(key)
                if icon_path and QtGui is not None:
                    ok = False
                    try:
                        pm = QtGui.QPixmap(icon_path)
                        if not pm.isNull():
                            btn.setIcon(QtGui.QIcon(pm))
                            ok = True
                    except Exception:
                        ok = False
                    if not ok:
                        try:
                            btn.setIcon(QtGui.QIcon(icon_path))
                            ok = True
                        except Exception:
                            ok = False
                    if ok:
                        btn.setIconSize(QtCore.QSize(60, 60))
                        btn.setText("")
                    else:
                        btn.setText(self._tool._mode_label(key))
                else:
                    btn.setText(self._tool._mode_label(key))
                if self._tool._mode_kind(key) == "animbot" and (not self._tool._animbot_available()):
                    btn.setEnabled(False)
                    try:
                        btn.setToolTip(self._tool._mode_label(key) + u"\n需要安装 AnimBot")
                    except Exception:
                        pass
                btn.clicked.connect(lambda _=False, kk=key: self._tool._set_selected_mode(kk))
                self._mode_group.addButton(btn)
                self._mode_btns[key] = btn
                grid.addWidget(btn, r, c)
                c += 1
                if c >= int(columns):
                    c = 0
                    r += 1

        def _on_toggle_clicked(self):
            try:
                self._tool.toggle_auto_tangent()
            except Exception:
                pass
            self._sync_state()

        def _sync_state(self):
            enabled = bool(getattr(self._tool, 'is_enabled', False))
            if enabled:
                self._status.setObjectName("statusOn")
                self._status.setText(u"状态: 开启")
                self._toggle.setObjectName("btnOn")
                self._toggle.setText(u"关闭")
            else:
                self._status.setObjectName("statusOff")
                self._status.setText(u"状态: 关闭")
                self._toggle.setObjectName("btnOff")
                self._toggle.setText(u"开启")
            self.style().unpolish(self._status)
            self.style().polish(self._status)
            self.style().unpolish(self._toggle)
            self.style().polish(self._toggle)

        def _sync_mode_buttons(self):
            sel = getattr(self._tool, '_selected_mode', '')
            kind = self._tool._mode_kind(sel) if sel else 'animbot'
            if kind == "maya":
                selected_css = "QToolButton{background:#2d4d85;border:1px solid #4c6aa4;}"
            else:
                selected_css = "QToolButton{background:#2f5f2f;border:1px solid #4b7a4b;}"
            for k, btn in (self._mode_btns or {}).items():
                is_sel = (k == sel)
                btn.blockSignals(True)
                btn.setChecked(is_sel)
                btn.blockSignals(False)
                if is_sel:
                    btn.setStyleSheet(selected_css)
                else:
                    btn.setStyleSheet("")

        def closeEvent(self, event):
            try:
                if getattr(self._tool, 'is_enabled', False):
                    self._tool.disable_auto_tangent()
            except Exception:
                pass
            try:
                self._tool._qt_dialog = None
            except Exception:
                pass
            return super(_AnimBotAutoTangentDialog, self).closeEvent(event)


_auto_tangent_instance = None


def show_ui():
    global _auto_tangent_instance
    if _auto_tangent_instance is None:
        _auto_tangent_instance = AnimBotAutoTangent()
    return _auto_tangent_instance.show_ui()
