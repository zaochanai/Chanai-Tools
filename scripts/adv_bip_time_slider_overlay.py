# -*- coding: utf-8 -*-
"""BIP time slider overlay.

在 Maya 原生时间滑块（$gPlayBackSlider）上方叠加一个很薄的时间条，绘制关键帧点：
- 默认：选中控制器的关键帧全部画黑色
- BIP 高亮：若检测到四肢控制器，则对应 FKIK* 的 FKIKBlend==10 的帧画黄色

注意：这是 overlay 叠加绘制，不会创建 timeSliderBookmark，也不会改动原生 time slider 的 UI 布局。
"""

from __future__ import absolute_import, division, print_function


_MANAGER = None
BIP_BOOKMARK_PREFIX = "BIP_Key_"
FOOTSTEP_BOOKMARK_PREFIX = "FootstepKey_"
FOOTSTEP_ATTR = "ADV_Footstep"


def _check_bookmark_support():
    """检查当前 Maya 版本是否支持 timeSliderBookmark，并尝试加载插件"""
    cmds, mel, omui = _maya_imports()
    try:
        version = int(cmds.about(version=True)[:4])
        if version < 2020:
            return False

        plugin_name = 'timeSliderBookmark'
        if not cmds.pluginInfo(plugin_name, query=True, loaded=True):
            try:
                cmds.loadPlugin(plugin_name)
            except Exception:
                return False
        return True
    except Exception:
        return False


def _qt_imports():
    try:
        from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore
        import shiboken2 as shiboken  # type: ignore
        return QtCore, QtGui, QtWidgets, shiboken
    except ImportError:
        from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore
        import shiboken6 as shiboken  # type: ignore
        return QtCore, QtGui, QtWidgets, shiboken


def _maya_imports():
    import maya.cmds as cmds  # noqa
    import maya.mel as mel  # noqa
    try:
        from maya import OpenMayaUI as omui  # noqa
    except ImportError:
        omui = None
    return cmds, mel, omui


def _qt_is_valid(obj):
    if obj is None:
        return False
    try:
        try:
            import shiboken2 as shiboken  # type: ignore
        except Exception:
            import shiboken6 as shiboken  # type: ignore
        return bool(shiboken.isValid(obj))
    except Exception:
        return True


def _get_time_slider_widget():
    cmds, mel, omui = _maya_imports()
    if omui is None:
        return None
    try:
        slider = mel.eval('$tmp=$gPlayBackSlider')
    except Exception:
        slider = None
    if not slider:
        return None

    QtCore, QtGui, QtWidgets, shiboken = _qt_imports()

    try:
        ptr = omui.MQtUtil.findControl(slider)
    except Exception:
        ptr = None
    if not ptr:
        return None

    try:
        try:
            w = shiboken.wrapInstance(int(ptr), QtWidgets.QWidget)
        except Exception:
            w = shiboken.wrapInstance(long(ptr), QtWidgets.QWidget)  # type: ignore[name-defined]
    except Exception:
        return None

    try:
        if w is None:
            return None
        if not shiboken.isValid(w):
            return None
    except Exception:
        pass

    return w


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

    switches = set()
    for n in selection or []:
        short = _short_name(n)
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
        switches.add(ns + 'FKIK{}{}'.format(limb, side))

    return switches


def _as_int_frames(times):
    frames = set()
    for t in times or []:
        try:
            frames.add(int(round(float(t))))
        except Exception:
            pass
    return frames


class _BipOverlayBar(object):
    HEIGHT = 36
    # Inner padding to better match Maya time slider tick area.
    PAD_RATIO = 0.03
    PAD_MIN = 12
    PAD_MAX = 48
    # Small bias (tune alignment). Negative = move left.
    X_BIAS_PX = -1


class BipTimeSliderOverlayWidget(object):
    pass


def _make_overlay_widget_class():
    QtCore, QtGui, QtWidgets, shiboken2 = _qt_imports()

    class BipTimeSliderOverlay(QtWidgets.QWidget):
        def __init__(self, parent=None):
            super(BipTimeSliderOverlay, self).__init__(parent)
            self.setObjectName('AdvBipTimeSliderOverlay')
            self.setFixedHeight(_BipOverlayBar.HEIGHT)
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
            # Ensure the widget doesn't behave like a "mask" over the time slider.
            try:
                self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            except Exception:
                pass
            self.setAutoFillBackground(False)
            try:
                self.setStyleSheet('background: transparent;')
            except Exception:
                pass

            self._start = 1
            self._end = 120
            self._current = 1
            self._black = set()
            self._yellow = set()

        def set_range(self, start_frame, end_frame):
            try:
                s = int(round(float(start_frame)))
                e = int(round(float(end_frame)))
            except Exception:
                return
            if e < s:
                s, e = e, s
            if s != self._start or e != self._end:
                self._start = s
                self._end = e
                self.update()

        def set_current(self, current_frame):
            try:
                c = int(round(float(current_frame)))
            except Exception:
                return
            if c != self._current:
                self._current = c
                self.update()

        def set_frames(self, black_frames=None, yellow_frames=None):
            black_frames = set(black_frames or [])
            yellow_frames = set(yellow_frames or [])
            if black_frames != self._black or yellow_frames != self._yellow:
                self._black = black_frames
                self._yellow = yellow_frames
                self.update()

        def _get_bookmark_positions(self):
            """计算帧号对应的 x 坐标，返回 {frame: x} 字典"""
            frame_to_x = {}
            
            try:
                # 获取时间滑块的父容器，用于坐标映射
                parent_widget = self.parent()
                if not parent_widget or not _qt_is_valid(parent_widget):
                    return frame_to_x
                
                cmds, mel, omui = _maya_imports()
                
                # 使用时间滑块的坐标映射计算 x 位置
                min_time = cmds.playbackOptions(q=True, minTime=True)
                max_time = cmds.playbackOptions(q=True, maxTime=True)
                time_span = max(1, max_time - min_time)
                parent_width = parent_widget.width()
                
                # 应用内边距逻辑
                pad = int(max(_BipOverlayBar.PAD_MIN, min(_BipOverlayBar.PAD_MAX, parent_width * _BipOverlayBar.PAD_RATIO)))
                inner_width = max(1, parent_width - 2 * pad)
                
                # 计算所有可能的帧
                all_frames = set(self._black) | set(self._yellow)
                for frame in all_frames:
                    ratio = (float(frame) - min_time) / time_span
                    x = pad + int(ratio * inner_width)
                    frame_to_x[frame] = x
                        
            except Exception:
                pass
            
            return frame_to_x

        def paintEvent(self, event):
            # 防止“已删除”刷屏（仍然让 Qt 安全退出）
            try:
                if not _qt_is_valid(self):
                    return
            except Exception:
                pass

            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
            rect = self.rect()

            # 从书签系统获取 x 坐标映射（使用书签的实际位置）
            frame_to_x = self._get_bookmark_positions()
            
            # Short markers (half height), centered vertically
            marker_len = max(8, int(rect.height() * 0.5))
            y0 = int((rect.height() - marker_len) * 0.5)
            y1 = y0 + marker_len

            # black frames
            pen_black = QtGui.QPen(QtGui.QColor(0, 0, 0, 255))
            pen_black.setWidth(4)
            painter.setPen(pen_black)
            for f in self._black:
                if f not in frame_to_x:
                    continue
                x = frame_to_x[f]
                painter.drawLine(x, y0, x, y1)

            # yellow frames (draw on top)
            pen_yellow = QtGui.QPen(QtGui.QColor(255, 200, 0, 255))
            pen_yellow.setWidth(6)
            painter.setPen(pen_yellow)
            for f in self._yellow:
                if f not in frame_to_x:
                    continue
                x = frame_to_x[f]
                painter.drawLine(x, y0, x, y1)

            # Cover Maya's red current-time indicator with our own line (no background mask).
            try:
                cf = int(round(float(self._current)))
            except Exception:
                cf = None
            if cf is not None and cf in frame_to_x:
                x = frame_to_x[cf]
                if cf in self._yellow:
                    painter.setPen(pen_yellow)
                else:
                    painter.setPen(pen_black)
                painter.drawLine(x, 0, x, rect.height())

            painter.end()

    return BipTimeSliderOverlay


_BipTimeSliderOverlay = None


class _OverlayManager(object):
    def __init__(self):
        QtCore, QtGui, QtWidgets, shiboken2 = _qt_imports()
        self._QtCore = QtCore
        self._QtWidgets = QtWidgets
        self._shiboken2 = shiboken2

        self._slider = None
        self._parent = None
        self._overlay = None
        self._event_filter = None
        self._timer = None
        self._tick = 0
        self._bip_mode = True

    def _clear_bip_bookmarks(self):
        if not _check_bookmark_support():
            return
        cmds, mel, omui = _maya_imports()
        try:
            bms = cmds.ls(type='timeSliderBookmark') or []
            for bm in bms:
                try:
                    short = bm.split('|')[-1]
                    short_no_ns = short.rsplit(':', 1)[-1]
                except Exception:
                    short_no_ns = bm

                match = False
                if short_no_ns.startswith(BIP_BOOKMARK_PREFIX):
                    match = True
                else:
                    try:
                        nm = cmds.getAttr(bm + '.name')
                        if isinstance(nm, str) and nm.startswith(BIP_BOOKMARK_PREFIX):
                            match = True
                    except Exception:
                        pass

                if match:
                    try:
                        cmds.delete(bm)
                    except Exception:
                        pass

            try:
                cmds.refresh(f=True)
            except Exception:
                pass
        except Exception:
            pass

    def _update_bip_bookmarks(self, black_frames, yellow_frames):
        if not _check_bookmark_support():
            return

        cmds, mel, omui = _maya_imports()
        try:
            self._clear_bip_bookmarks()
        except Exception:
            pass

        all_frames = sorted(set(black_frames or []) | set(yellow_frames or []))
        if not all_frames:
            return

        for i, frame in enumerate(all_frames):
            bookmark_name = "{}{}".format(BIP_BOOKMARK_PREFIX, i)
            try:
                bm = cmds.createNode('timeSliderBookmark', name=bookmark_name, skipSelect=True)
                cmds.setAttr(bm + '.name', '{}F{}'.format(BIP_BOOKMARK_PREFIX, frame), type='string')
                cmds.setAttr(bm + '.timeRangeStart', frame)
                cmds.setAttr(bm + '.timeRangeStop', frame)
                if frame in yellow_frames:
                    cmds.setAttr(bm + '.color', 1.0, 0.8, 0.0, type='double3')
                else:
                    cmds.setAttr(bm + '.color', 0.0, 0.0, 0.0, type='double3')
            except Exception:
                pass

    def _get_footstep_frames(self):
        """Collect frames marked by FootstepKey_ bookmarks (namespace-safe)."""
        if not _check_bookmark_support():
            return set()
        cmds, mel, omui = _maya_imports()
        frames = set()
        try:
            bms = cmds.ls(type='timeSliderBookmark') or []
        except Exception:
            bms = []
        for bm in bms:
            try:
                short = bm.split('|')[-1]
                short_no_ns = short.rsplit(':', 1)[-1]
            except Exception:
                short_no_ns = bm
            match = False
            if short_no_ns.startswith(FOOTSTEP_BOOKMARK_PREFIX):
                match = True
            else:
                try:
                    nm = cmds.getAttr(bm + '.name')
                    if isinstance(nm, str) and nm.startswith(FOOTSTEP_BOOKMARK_PREFIX):
                        match = True
                except Exception:
                    pass
            if not match:
                continue
            try:
                t = cmds.getAttr(bm + '.timeRangeStart')
                frames.add(int(round(float(t))))
            except Exception:
                pass
        return frames

    def _sync_footstep_bookmarks(self, frames):
        if not _check_bookmark_support():
            return
        cmds, mel, omui = _maya_imports()
        try:
            frames = set(int(round(float(f))) for f in (frames or []))
        except Exception:
            frames = set()

        try:
            bms = cmds.ls(type='timeSliderBookmark') or []
        except Exception:
            bms = []
        to_delete = []
        for bm in bms:
            try:
                short = bm.split('|')[-1]
                short_no_ns = short.rsplit(':', 1)[-1]
            except Exception:
                short_no_ns = bm
            match = False
            if short_no_ns.startswith(FOOTSTEP_BOOKMARK_PREFIX):
                match = True
            else:
                try:
                    nm = cmds.getAttr(bm + '.name')
                    if isinstance(nm, str) and nm.startswith(FOOTSTEP_BOOKMARK_PREFIX):
                        match = True
                except Exception:
                    pass
            if match:
                to_delete.append(bm)
        if to_delete:
            try:
                cmds.delete(list(set(to_delete)))
            except Exception:
                pass

        if not frames:
            return

        for i, frame in enumerate(sorted(frames)):
            bookmark_name = "{}BIP{}".format(FOOTSTEP_BOOKMARK_PREFIX, i)
            try:
                bm = cmds.createNode('timeSliderBookmark', name=bookmark_name, skipSelect=True)
                cmds.setAttr(bm + '.name', '{}F{}'.format(FOOTSTEP_BOOKMARK_PREFIX, frame), type='string')
                cmds.setAttr(bm + '.timeRangeStart', frame)
                cmds.setAttr(bm + '.timeRangeStop', frame)
                cmds.setAttr(bm + '.color', 1.0, 0.55, 0.0, type='double3')
            except Exception:
                pass

    def _get_footstep_frames_from_attr(self, transforms):
        cmds, mel, omui = _maya_imports()
        frames = set()
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
            for tt, vv in zip(t, v):
                try:
                    if float(vv) >= 0.5:
                        frames.add(int(round(float(tt))))
                except Exception:
                    pass
        return frames

    def is_installed(self):
        return _qt_is_valid(self._overlay)

    def set_bip_mode(self, enabled):
        self._bip_mode = bool(enabled)

    def install(self, bip_mode=True, force=False):
        self._bip_mode = bool(bip_mode)
        if self.is_installed() and not force:
            return True

        self.uninstall()

        slider = _get_time_slider_widget()
        if slider is None or not _qt_is_valid(slider):
            return False

        parent = slider.parentWidget()
        if parent is None or not _qt_is_valid(parent):
            return False

        global _BipTimeSliderOverlay
        if _BipTimeSliderOverlay is None:
            _BipTimeSliderOverlay = _make_overlay_widget_class()

        overlay = _BipTimeSliderOverlay(parent)
        overlay.show()
        overlay.raise_()

        self._slider = slider
        self._parent = parent
        self._overlay = overlay

        QtCore = self._QtCore

        class _Filter(QtCore.QObject):
            def __init__(self, mgr):
                super(_Filter, self).__init__(mgr._parent)
                self._mgr = mgr

            def eventFilter(self, obj, ev):
                try:
                    if ev.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Move, QtCore.QEvent.Show):
                        self._mgr._reposition()
                except Exception:
                    pass
                return False

        self._event_filter = _Filter(self)
        try:
            parent.installEventFilter(self._event_filter)
        except Exception:
            pass

        self._timer = QtCore.QTimer()
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

        self._reposition()
        self._refresh_data(force=True)
        return True

    def uninstall(self):
        try:
            if self._timer is not None:
                try:
                    self._timer.stop()
                except Exception:
                    pass
                self._timer = None
        except Exception:
            pass

        try:
            if self._parent is not None and self._event_filter is not None:
                try:
                    self._parent.removeEventFilter(self._event_filter)
                except Exception:
                    pass
        except Exception:
            pass
        self._event_filter = None

        try:
            if self._overlay is not None and _qt_is_valid(self._overlay):
                try:
                    self._overlay.hide()
                except Exception:
                    pass
                try:
                    self._overlay.setParent(None)
                except Exception:
                    pass
                try:
                    self._overlay.deleteLater()
                except Exception:
                    pass
        except Exception:
            pass

        self._overlay = None
        self._parent = None
        self._slider = None
        try:
            self._clear_bip_bookmarks()
        except Exception:
            pass

    def _reposition(self):
        if not _qt_is_valid(self._overlay) or not _qt_is_valid(self._slider):
            return
        try:
            sg = self._slider.geometry()
        except Exception:
            return
        h = self._overlay.height()
        x = int(sg.x())
        w = int(sg.width())
        y = int(sg.y()) - h - 1
        if y < 0:
            y = 0
        try:
            self._overlay.setGeometry(x, y, w, h)
        except Exception:
            pass

    def _on_tick(self):
        if not _qt_is_valid(self._overlay) or not _qt_is_valid(self._slider) or not _qt_is_valid(self._parent):
            self.uninstall()
            return

        self._tick += 1
        # Always update current time
        cmds, mel, omui = _maya_imports()
        try:
            cur = cmds.currentTime(q=True)
        except Exception:
            cur = None
        if cur is not None:
            try:
                self._overlay.set_current(cur)
            except Exception:
                pass

        # Refresh data at lower frequency
        if (self._tick % 4) == 0:
            self._refresh_data(force=False)

        # Keep alignment
        self._reposition()

    def _get_visible_range(self):
        cmds, mel, omui = _maya_imports()
        try:
            # If range slider visible, use it
            slider_name = mel.eval('$tmp=$gPlayBackSlider')
            if slider_name and cmds.timeControl(slider_name, q=True, rangeVisible=True):
                arr = cmds.timeControl(slider_name, q=True, rangeArray=True)
                if arr and len(arr) >= 2:
                    return float(arr[0]), float(arr[1])
        except Exception:
            pass

        try:
            return float(cmds.playbackOptions(q=True, minTime=True)), float(cmds.playbackOptions(q=True, maxTime=True))
        except Exception:
            return 1.0, 120.0

    def _refresh_data(self, force=False):
        cmds, mel, omui = _maya_imports()

        start, end = self._get_visible_range()
        try:
            self._overlay.set_range(start, end)
        except Exception:
            pass

        selection = cmds.ls(sl=True) or []
        if not selection:
            try:
                self._overlay.set_frames(set(), set())
            except Exception:
                pass
            return

        # Prefer transforms
        transforms = []
        for n in selection:
            try:
                if cmds.nodeType(n) == 'transform':
                    transforms.append(n)
                else:
                    p = (cmds.listRelatives(n, parent=True, fullPath=True) or [None])[0]
                    if p:
                        transforms.append(p)
            except Exception:
                pass
        # Deduplicate
        seen = set()
        transforms = [t for t in transforms if not (t in seen or seen.add(t))]

        # black frames from selected controls
        black_frames = set()
        try:
            times = cmds.keyframe(transforms, q=True, timeChange=True)
            black_frames = _as_int_frames(times)
        except Exception:
            black_frames = set()

        yellow_frames = set()
        if self._bip_mode:
            switches = _detect_limb_switches_from_selection(transforms)
            attr_candidates = ['FKIKBlend', 'fkikblend', 'fkIkBlend', 'FKIKblend']
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
                if not t or not v:
                    continue
                for tt, vv in zip(t, v):
                    try:
                        if float(vv) >= 9.999:
                            yellow_frames.add(int(round(float(tt))))
                    except Exception:
                        pass

        # Do not overwrite orange footstep markers.
        try:
            foot_frames = self._get_footstep_frames_from_attr(transforms)
            foot_frames |= self._get_footstep_frames()
        except Exception:
            foot_frames = set()
        if foot_frames:
            try:
                black_frames = set(black_frames) - set(foot_frames)
            except Exception:
                pass
            try:
                yellow_frames = set(yellow_frames) - set(foot_frames)
            except Exception:
                pass

        if self._bip_mode:
            try:
                self._sync_footstep_bookmarks(foot_frames)
            except Exception:
                pass
            try:
                self._update_bip_bookmarks(black_frames, yellow_frames)
            except Exception:
                pass
            try:
                self._overlay.set_frames([], [])
            except Exception:
                pass
        else:
            try:
                self._overlay.set_frames(black_frames, yellow_frames)
            except Exception:
                pass


def install(bip_mode=True, force=False):
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = _OverlayManager()
    return _MANAGER.install(bip_mode=bip_mode, force=force)


def uninstall():
    global _MANAGER
    if _MANAGER is None:
        return
    try:
        _MANAGER.uninstall()
    except Exception:
        pass


def clear_bip_bookmarks():
    """Force clear BIP bookmarks even if overlay is not installed."""
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = _OverlayManager()
    try:
        _MANAGER._clear_bip_bookmarks()
    except Exception:
        pass


def refresh_now():
    """Force immediate refresh of overlay/bookmarks."""
    global _MANAGER
    if _MANAGER is None:
        return
    try:
        _MANAGER._refresh_data(force=True)
    except Exception:
        pass


def set_bip_mode(enabled=True):
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = _OverlayManager()
    try:
        _MANAGER.set_bip_mode(bool(enabled))
    except Exception:
        pass


def toggle():
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = _OverlayManager()
    if _MANAGER.is_installed():
        uninstall()
        return False
    return bool(install(bip_mode=True, force=True))
