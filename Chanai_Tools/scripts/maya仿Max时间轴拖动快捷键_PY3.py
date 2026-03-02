# -*- coding: utf-8 -*-
import maya.cmds as cmds
import maya.OpenMayaUI as omui
import traceback
import sys

try:
    from PySide2 import QtWidgets, QtCore  # type: ignore
    from shiboken2 import wrapInstance  # type: ignore
except ImportError:
    from PySide6 import QtWidgets, QtCore  # type: ignore
    from shiboken6 import wrapInstance  # type: ignore


def _qt_enum(root, dotted, fallback=None):
    try:
        cur = root
        for p in str(dotted).split('.'):
            cur = getattr(cur, p)
        return cur
    except Exception:
        return fallback


_CTRL_MOD = _qt_enum(QtCore, 'Qt.ControlModifier', None) or _qt_enum(QtCore, 'Qt.KeyboardModifier.ControlModifier', None)
_ALT_MOD = _qt_enum(QtCore, 'Qt.AltModifier', None) or _qt_enum(QtCore, 'Qt.KeyboardModifier.AltModifier', None)
_SHIFT_MOD = _qt_enum(QtCore, 'Qt.ShiftModifier', None) or _qt_enum(QtCore, 'Qt.KeyboardModifier.ShiftModifier', None)

_BTN_L = _qt_enum(QtCore, 'Qt.LeftButton', None) or _qt_enum(QtCore, 'Qt.MouseButton.LeftButton', None)
_BTN_R = _qt_enum(QtCore, 'Qt.RightButton', None) or _qt_enum(QtCore, 'Qt.MouseButton.RightButton', None)
_BTN_M = _qt_enum(QtCore, 'Qt.MiddleButton', None) or _qt_enum(QtCore, 'Qt.MouseButton.MiddleButton', None)

_CTX_NO_MENU = _qt_enum(QtCore, 'Qt.NoContextMenu', None) or _qt_enum(QtCore, 'Qt.ContextMenuPolicy.NoContextMenu', None)

_EVT_MOUSE_PRESS = _qt_enum(QtCore, 'QEvent.MouseButtonPress', None) or _qt_enum(QtCore, 'QEvent.Type.MouseButtonPress', None)
_EVT_MOUSE_MOVE = _qt_enum(QtCore, 'QEvent.MouseMove', None) or _qt_enum(QtCore, 'QEvent.Type.MouseMove', None)
_EVT_MOUSE_RELEASE = _qt_enum(QtCore, 'QEvent.MouseButtonRelease', None) or _qt_enum(QtCore, 'QEvent.Type.MouseButtonRelease', None)

_DIAG_MAX = 260
_DIAG_LOG = []
_DIAG_COUNTS = {
    'mousePress': 0,
    'mouseMove': 0,
    'mouseRelease': 0,
    'press_mod_fail': 0,
    'press_hit_fail': 0,
    'drag_start': 0,
    'drag_move': 0,
    'drag_move_nonzero': 0,
    'drag_release': 0,
}
_DIAG_LAST = {}


def _diag_enabled():
    try:
        return bool(cmds.optionVar(q='ADV_TimeSliderDragDebug')) if cmds.optionVar(exists='ADV_TimeSliderDragDebug') else True
    except Exception:
        return True


def _diag_push(tag, **kw):
    if not _diag_enabled():
        return
    try:
        import time
        ts = time.time()
    except Exception:
        ts = 0.0
    try:
        d = {'t': ts, 'tag': str(tag)}
        d.update(kw or {})
    except Exception:
        d = {'t': ts, 'tag': str(tag)}
    _DIAG_LOG.append(d)
    _DIAG_LAST[str(tag)] = d
    if len(_DIAG_LOG) > _DIAG_MAX:
        del _DIAG_LOG[: len(_DIAG_LOG) - _DIAG_MAX]


def _as_int(v, default=None):
    try:
        return int(v)
    except Exception:
        return default


def _enum_eq(a, b):
    if a is None or b is None:
        return False
    try:
        if a == b:
            return True
    except Exception:
        pass
    ia = _as_int(a, None)
    ib = _as_int(b, None)
    if ia is None or ib is None:
        return False
    return ia == ib


def diagnose_export(max_lines=200):
    try:
        max_lines = int(max_lines)
    except Exception:
        max_lines = 200
    max_lines = max(20, min(2000, max_lines))

    lines = []
    lines.append('TimeSliderDrag Diagnose')
    try:
        lines.append('Maya: %s' % str(cmds.about(v=True)))
    except Exception:
        pass
    try:
        lines.append('Qt: %s' % ('PySide6' if 'PySide6' in sys.modules else ('PySide2' if 'PySide2' in sys.modules else 'Unknown')))
    except Exception:
        pass
    try:
        lines.append('Debug enabled: %s' % str(bool(_diag_enabled())))
    except Exception:
        pass
    lines.append('Counts: %s' % str(_DIAG_COUNTS))
    try:
        lines.append('Last tags: %s' % str(sorted(list(_DIAG_LAST.keys()))[-12:]))
    except Exception:
        pass
    lines.append('--- tail ---')
    tail = _DIAG_LOG[-max_lines:] if _DIAG_LOG else []
    for it in tail:
        try:
            lines.append(str(it))
        except Exception:
            pass
    return '\n'.join(lines)


def _wrap_ptr(ptr, base):
    if not ptr:
        return None
    try:
        return wrapInstance(int(ptr), base)
    except Exception:
        try:
            return wrapInstance(long(ptr), base)  # type: ignore[name-defined]
        except Exception:
            return None


def _find_playback_slider_control_name():
    try:
        import maya.mel as mel
    except Exception:
        mel = None
    if not mel:
        return ''
    try:
        return str(mel.eval('$tmp=$gPlayBackSlider') or '')
    except Exception:
        return ''


def find_time_slider():
    name = _find_playback_slider_control_name()
    if name:
        ptr = None
        try:
            ptr = omui.MQtUtil.findControl(name)
        except Exception:
            ptr = None
        if not ptr:
            try:
                short = str(name).split('|')[-1]
            except Exception:
                short = ''
            if short:
                try:
                    ptr = omui.MQtUtil.findControl(short)
                except Exception:
                    ptr = None
        w = _wrap_ptr(ptr, QtWidgets.QWidget)
        if w:
            return w

    all_controls = []
    try:
        all_controls = cmds.lsUI(type="timeControl") or []
    except Exception:
        all_controls = []
    if all_controls:
        ptr = None
        try:
            ptr = omui.MQtUtil.findControl(all_controls[0])
        except Exception:
            ptr = None
        w = _wrap_ptr(ptr, QtWidgets.QWidget)
        if w:
            return w
    return None


def _is_child_of(w, parent):
    if not w or not parent:
        return False
    try:
        cur = w
        while cur is not None:
            if cur == parent:
                return True
            cur = cur.parentWidget()
    except Exception:
        pass
    return False


def _has_mod(mods, token):
    if token is None:
        return False
    try:
        return bool(mods & token)
    except Exception:
        try:
            return bool(int(mods) & int(token))
        except Exception:
            return False


def _point_in_widget_global_rect(widget, gx, gy):
    if not widget:
        return False
    try:
        w = widget
        tl = w.mapToGlobal(QtCore.QPoint(0, 0))
        x0 = int(tl.x())
        y0 = int(tl.y())
        x1 = x0 + int(w.width())
        y1 = y0 + int(w.height())
        return (gx >= x0) and (gx <= x1) and (gy >= y0) and (gy <= y1)
    except Exception:
        return False


class MaxTimeSliderController(QtCore.QObject):
    def __init__(self):
        super(MaxTimeSliderController, self).__init__()
        self.slider = find_time_slider()
        self._app = None
        try:
            self._app = QtWidgets.QApplication.instance()
        except Exception:
            self._app = None

        self.is_dragging = False
        self.start_frame = 0
        self.start_x = 0
        self.drag_button = None
        self.original_range = [0, 0]
        self._press_widget = None

        if self._app:
            try:
                self._app.installEventFilter(self)
            except Exception:
                pass
    
    def stop(self):
        try:
            if self._app:
                self._app.removeEventFilter(self)
        except Exception:
            pass

    def eventFilter(self, obj, event):
        try:
            et = event.type()
            if _EVT_MOUSE_PRESS is not None and et == _EVT_MOUSE_PRESS:
                try:
                    _DIAG_COUNTS['mousePress'] += 1
                except Exception:
                    pass
                return self.handle_mouse_press(event)
            if _EVT_MOUSE_MOVE is not None and et == _EVT_MOUSE_MOVE:
                try:
                    _DIAG_COUNTS['mouseMove'] += 1
                except Exception:
                    pass
                return self.handle_mouse_move(event)
            if _EVT_MOUSE_RELEASE is not None and et == _EVT_MOUSE_RELEASE:
                try:
                    _DIAG_COUNTS['mouseRelease'] += 1
                except Exception:
                    pass
                return self.handle_mouse_release(event)
        except Exception:
            traceback.print_exc()
        return False

    def handle_mouse_press(self, event):
        try:
            if not self._app:
                return False
            if not self.slider:
                self.slider = find_time_slider()
            if not self.slider:
                return False

            try:
                mods = event.modifiers()
            except Exception:
                mods = 0

            want = True
            if _CTRL_MOD is not None and (not _has_mod(mods, _CTRL_MOD)):
                want = False
            if _ALT_MOD is not None and (not _has_mod(mods, _ALT_MOD)):
                want = False
            if _SHIFT_MOD is not None and _has_mod(mods, _SHIFT_MOD):
                want = False
            if not want:
                try:
                    _DIAG_COUNTS['press_mod_fail'] += 1
                except Exception:
                    pass
                _diag_push('press_mod_fail')
                return False

            try:
                gpos = event.globalPosition()
                gx = int(gpos.x())
                gy = int(gpos.y())
            except Exception:
                try:
                    gp = event.globalPos()
                    gx = int(gp.x())
                    gy = int(gp.y())
                except Exception:
                    _diag_push('press_pos_fail')
                    return False

            hit = _point_in_widget_global_rect(self.slider, gx, gy)
            if not hit:
                try:
                    _DIAG_COUNTS['press_hit_fail'] += 1
                except Exception:
                    pass
                try:
                    tl = self.slider.mapToGlobal(QtCore.QPoint(0, 0))
                    rect = (int(tl.x()), int(tl.y()), int(self.slider.width()), int(self.slider.height()))
                except Exception:
                    rect = None
                _diag_push('press_hit_fail', gx=int(gx), gy=int(gy), rect=rect)
                return False

            self.is_dragging = True
            self.start_x = gx
            self._press_widget = self.slider
            try:
                self.drag_button = event.button()
            except Exception:
                self.drag_button = None

            if _enum_eq(self.drag_button, _BTN_L):
                self.start_frame = cmds.playbackOptions(q=True, min=True)
            elif _enum_eq(self.drag_button, _BTN_R):
                self.start_frame = cmds.playbackOptions(q=True, max=True)
            elif _enum_eq(self.drag_button, _BTN_M):
                self.original_range = [
                    cmds.playbackOptions(q=True, min=True),
                    cmds.playbackOptions(q=True, max=True)
                ]
                self.start_frame = (self.original_range[0] + self.original_range[1]) / 2

            try:
                _DIAG_COUNTS['drag_start'] += 1
            except Exception:
                pass
            _diag_push('drag_start', btn=str(self.drag_button), start_x=int(self.start_x))
            try:
                event.accept()
            except Exception:
                pass
            return True
        except Exception as e:
            try:
                self.is_dragging = False
            except Exception:
                pass
            _diag_push('press_exception', err=str(e))
            return False

    def handle_mouse_move(self, event):
        if not self.is_dragging:
            return False
        if not self.slider:
            self.is_dragging = False
            return False

        min_frame = cmds.playbackOptions(q=True, min=True)
        max_frame = cmds.playbackOptions(q=True, max=True)
        total_frames = max(1, max_frame - min_frame)
        slider_width = self.slider.width()

        if slider_width <= 0:
            return False

        try:
            gpos = event.globalPosition()
            current_x = int(gpos.x())
        except Exception:
            try:
                gp = event.globalPos()
                current_x = int(gp.x())
            except Exception:
                return False

        px_per_frame = slider_width / float(total_frames)
        delta_frames = int((current_x - self.start_x) / px_per_frame)
        try:
            _DIAG_COUNTS['drag_move'] += 1
        except Exception:
            pass
        if int(delta_frames) != 0:
            try:
                _DIAG_COUNTS['drag_move_nonzero'] += 1
            except Exception:
                pass

        if _enum_eq(self.drag_button, _BTN_L):
            cmds.playbackOptions(min=self.start_frame - delta_frames)
        elif _enum_eq(self.drag_button, _BTN_R):
            cmds.playbackOptions(max=self.start_frame - delta_frames)
        elif _enum_eq(self.drag_button, _BTN_M):
            range_size = self.original_range[1] - self.original_range[0]
            new_center = self.start_frame - delta_frames
            cmds.playbackOptions(
                min=new_center - range_size / 2,
                max=new_center + range_size / 2
            )

        self.slider.update()
        if int(delta_frames) != 0:
            _diag_push('drag_move', dx=int(current_x - self.start_x), df=int(delta_frames), w=int(slider_width), total=int(total_frames))
        try:
            event.accept()
        except Exception:
            pass
        return True

    def handle_mouse_release(self, event):
        self.is_dragging = False
        self._press_widget = None
        try:
            _DIAG_COUNTS['drag_release'] += 1
        except Exception:
            pass
        try:
            mn = cmds.playbackOptions(q=True, min=True)
            mx = cmds.playbackOptions(q=True, max=True)
        except Exception:
            mn = None
            mx = None
        _diag_push('drag_release', min=mn, max=mx)
        return False


def start_time_slider_control():
    try:
        cmds.refresh()
        global _controller
        try:
            if _controller is not None:
                try:
                    _controller.stop()
                except Exception:
                    pass
        except Exception:
            pass
        _controller = MaxTimeSliderController()
        try:
            if not getattr(_controller, '_app', None):
                return False
        except Exception:
            return False
        return True
    except Exception as e:
        cmds.warning("启动失败: " + str(e))
        return False


if __name__ == "__main__":
    start_time_slider_control()
