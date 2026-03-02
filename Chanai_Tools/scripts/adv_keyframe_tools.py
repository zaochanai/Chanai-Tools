# -*- coding: utf-8 -*-
from maya import cmds
import sys
import os

try:
    from PySide2 import QtWidgets, QtCore, QtGui
    QT_AVAILABLE = True
except ImportError:
    try:
        from PySide6 import QtWidgets, QtCore, QtGui
        QT_AVAILABLE = True
    except ImportError:
        QT_AVAILABLE = False


WINDOW_NAME = "ADV_KeyframeToolsWin"
_INTERVAL_FIELD = "advKeyframeIntervalField"
_QT_WINDOW_OBJECT = "ADV_KeyframeToolsQtWin"


def _get_adv_main_module():
    """获取ADV主模块，用于访问Qt样式函数。"""
    try:
        # 尝试从已加载的模块中获取
        for name, mod in sys.modules.items():
            if 'ADV_extension' in name or 'ADV_fast_select' in name:
                if hasattr(mod, '_adv_apply_qstyle_to_qt_widget'):
                    return mod
        # 尝试直接导入
        script_dir = os.path.dirname(os.path.dirname(__file__))
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        import importlib
        mod = importlib.import_module('ADV_extension')
        return mod
    except Exception:
        return None


def _get_time_range_for_key_ops():
    """获取时间滑块范围（底部时间轴两端的范围）。

    注意：这里按你的需求，不使用时间轴“拖拽选区”的 range。
    """
    start = cmds.playbackOptions(q=True, minTime=True)
    end = cmds.playbackOptions(q=True, maxTime=True)
    if start > end:
        start, end = end, start
    return float(start), float(end)


def _iter_parent_chain(node):
    cur = node
    while True:
        parents = cmds.listRelatives(cur, parent=True, fullPath=True) or []
        if not parents:
            return
        parent = parents[0]
        yield parent
        cur = parent


def _collect_key_times(node):
    try:
        times = cmds.keyframe(node, q=True, tc=True) or []
    except Exception:
        times = []
    out = set()
    for t in times:
        if t is None:
            continue
        try:
            out.add(float(t))
        except Exception:
            pass
    return out


def apply_parent_keys():
    """选择控制器 → 搜索父级关键帧时间 → 在这些时间点给当前对象打关键帧。"""
    nodes = cmds.ls(sl=True, long=True) or []
    if not nodes:
        cmds.warning(u"请先选择一个或多个控制器")
        return

    cmds.undoInfo(openChunk=True)
    try:
        for node in nodes:
            key_times = set()
            for parent in _iter_parent_chain(node):
                key_times |= _collect_key_times(parent)

            if not key_times:
                cmds.warning(u"未找到父级关键帧: {}".format(node.split('|')[-1]))
                continue

            for t in sorted(key_times):
                try:
                    cmds.setKeyframe(node, time=(t, t))
                except Exception:
                    pass
    finally:
        cmds.undoInfo(closeChunk=True)


def _apply_key_times_from_source_to_targets(source_node, target_nodes):
    """把 source 的关键帧时间应用到 target：在同样时间点给 target 打默认关键帧。"""
    if not source_node or not target_nodes:
        return

    try:
        key_times = sorted(_collect_key_times(source_node))
    except Exception:
        key_times = []

    if not key_times:
        cmds.warning(u"未找到源对象关键帧: {}".format(source_node.split('|')[-1]))
        return

    cmds.undoInfo(openChunk=True)
    try:
        for node in target_nodes:
            if not node or not cmds.objExists(node):
                continue
            for t in key_times:
                try:
                    cmds.setKeyframe(node, time=(t, t))
                except Exception:
                    pass
    finally:
        cmds.undoInfo(closeChunk=True)


def apply_object_keys_last_is_source():
    """类似“父子关系”选择规则：最后一个选择为源，前面所有选择为目标。"""
    try:
        nodes = cmds.ls(orderedSelection=True, long=True) or []
    except Exception:
        nodes = cmds.ls(sl=True, long=True) or []

    if len(nodes) < 2:
        cmds.warning(u"请至少选择 2 个对象（最后一个为源，前面为目标）")
        return

    source = nodes[-1]
    targets = nodes[:-1]

    _apply_key_times_from_source_to_targets(source, targets)
    try:
        cmds.inViewMessage(
            amg=u'<span style="color:#7aa0ff;">%s</span>' % (u"已应用对象关键帧（最后为源）"),
            pos='topCenter',
            fade=True,
            fadeStayTime=1200
        )
    except Exception:
        pass


def clear_keys_in_range():
    """一键清除时间轴范围内关键帧（范围=时间滑块范围/播放范围）"""
    nodes = cmds.ls(sl=True, long=True) or []
    if not nodes:
        cmds.warning(u"请先选择一个或多个控制器")
        return

    start, end = _get_time_range_for_key_ops()
    cmds.undoInfo(openChunk=True)
    try:
        for node in nodes:
            try:
                cmds.cutKey(node, time=(start, end))
            except Exception:
                pass
    finally:
        cmds.undoInfo(closeChunk=True)


def clear_keys_outside_range():
    """一键清除时间轴范围外关键帧（范围=时间滑块范围/播放范围）"""
    nodes = cmds.ls(sl=True, long=True) or []
    if not nodes:
        cmds.warning(u"请先选择一个或多个控制器")
        return

    start, end = _get_time_range_for_key_ops()
    eps = 0.001
    very_small = -1.0e10
    very_large = 1.0e10

    cmds.undoInfo(openChunk=True)
    try:
        for node in nodes:
            try:
                cmds.cutKey(node, time=(very_small, start - eps))
            except Exception:
                pass
            try:
                cmds.cutKey(node, time=(end + eps, very_large))
            except Exception:
                pass
    finally:
        cmds.undoInfo(closeChunk=True)


def interval_clear_keys(interval=None, field_control=None):
    """按间隔清理关键帧：在时间滑块范围内仅保留每隔 N 帧的关键帧。

    interval: int，步长；None 时会尝试从 UI 的 intField 读取。
    field_control: intField 名称；None 时默认使用本模块窗口的字段。
    """
    nodes = cmds.ls(sl=True, long=True) or []
    if not nodes:
        cmds.warning(u"请先选择一个或多个控制器")
        return

    if interval is None:
        if not field_control:
            field_control = _INTERVAL_FIELD
        try:
            if cmds.control(field_control, exists=True):
                interval = int(cmds.intField(field_control, q=True, v=True))
        except Exception:
            interval = None

    # Backward compatibility: old embedded UI used this name
    if interval is None:
        try:
            if cmds.control("alignIntervalField", exists=True):
                interval = int(cmds.intField("alignIntervalField", q=True, v=True))
        except Exception:
            interval = None

    try:
        interval = int(interval)
    except Exception:
        interval = 1

    if interval <= 1:
        cmds.warning(u"间隔值必须大于 1")
        return

    start, end = _get_time_range_for_key_ops()

    def _is_keep_time(t, base, step):
        try:
            v = (float(t) - float(base)) / float(step)
            return abs(v - round(v)) < 1.0e-6
        except Exception:
            return False

    cmds.undoInfo(openChunk=True)
    try:
        for node in nodes:
            try:
                times = cmds.keyframe(node, q=True, tc=True) or []
            except Exception:
                times = []

            if not times:
                continue

            to_delete = []
            for t in times:
                try:
                    tf = float(t)
                except Exception:
                    continue
                if tf < start or tf > end:
                    continue
                if not _is_keep_time(tf, start, interval):
                    to_delete.append(tf)

            for t in sorted(set(to_delete)):
                try:
                    cmds.cutKey(node, time=(t, t))
                except Exception:
                    pass
    finally:
        cmds.undoInfo(closeChunk=True)


def show():
    """弹出关键帧工具窗口。"""
    if QT_AVAILABLE:
        try:
            return show_qt()
        except Exception as e:
            import traceback
            error_msg = u"Qt界面启动失败: {}\n{}".format(str(e), traceback.format_exc())
            cmds.warning(error_msg)
            print(error_msg)
            # 回退到cmds界面
            return show_cmds()
    else:
        return show_cmds()


def show_qt():
    """使用Qt创建现代化的关键帧工具窗口。"""
    try:
        # 关闭已存在的窗口
        for widget in QtWidgets.QApplication.allWidgets():
            if widget.objectName() == _QT_WINDOW_OBJECT:
                try:
                    widget.close()
                    widget.deleteLater()
                except Exception:
                    pass
    except Exception:
        pass

    # 获取Maya主窗口作为父窗口
    maya_main_window = None
    try:
        from maya import OpenMayaUI as omui
        try:
            from shiboken2 import wrapInstance
        except ImportError:
            from shiboken6 import wrapInstance
        maya_main_window_ptr = omui.MQtUtil.mainWindow()
        if maya_main_window_ptr:
            maya_main_window = wrapInstance(int(maya_main_window_ptr), QtWidgets.QWidget)
    except Exception:
        pass

    dialog = KeyframeToolsDialog(parent=maya_main_window)

    # 应用ADV的Qt样式
    try:
        adv_module = _get_adv_main_module()
        if adv_module:
            # 注册到Qt样式目标，这样当用户切换Qt风格时会自动更新
            register_func = getattr(adv_module, '_adv_register_qt_style_target', None)
            if callable(register_func):
                register_func(_QT_WINDOW_OBJECT, dialog, allow_bg_image=True)

            # 立即应用当前的Qt样式
            apply_func = getattr(adv_module, '_adv_apply_qstyle_to_qt_widget', None)
            is_enabled_func = getattr(adv_module, '_adv_qstyle_is_enabled', None)
            if callable(apply_func) and callable(is_enabled_func):
                enabled = is_enabled_func(default=True)
                apply_func(dialog, enabled=enabled, object_name=_QT_WINDOW_OBJECT, allow_bg_image=True)
    except Exception as e:
        print(u"应用Qt样式失败: {}".format(str(e)))

    dialog.show()
    return dialog


def show_cmds():
    """使用Maya cmds创建传统UI窗口（备用方案）。"""
    try:
        if cmds.window(WINDOW_NAME, exists=True):
            cmds.deleteUI(WINDOW_NAME)
    except Exception:
        pass

    title = u"关键帧工具"
    w = cmds.window(WINDOW_NAME, title=title, widthHeight=(440, 210), sizeable=True)
    cmds.columnLayout(adjustableColumn=True, columnAttach=('both', 8), rowSpacing=6)

    cmds.rowLayout(numberOfColumns=3, adjustableColumn=3, columnWidth3=(50, 70, 1), columnAlign3=('left', 'left', 'left'))
    cmds.text(label=u"间隔", align='left', width=50)
    cmds.intField(_INTERVAL_FIELD, v=5, minValue=2, width=70)
    cmds.text(label=u"(用于间接清理)", align='left')
    cmds.setParent('..')

    def _two_button_row(left_label, left_cmd, left_color, right_label, right_cmd, right_color):
        row = cmds.formLayout(nd=100)
        b1 = cmds.button(label=left_label, height=28, backgroundColor=left_color, command=left_cmd)
        b2 = cmds.button(label=right_label, height=28, backgroundColor=right_color, command=right_cmd)
        cmds.formLayout(
            row,
            e=True,
            attachForm=[
                (b1, 'left', 0), (b1, 'top', 0), (b1, 'bottom', 0),
                (b2, 'right', 0), (b2, 'top', 0), (b2, 'bottom', 0),
            ],
            attachPosition=[
                (b1, 'right', 2, 50),
                (b2, 'left', 2, 50),
            ],
        )
        cmds.setParent('..')

    _two_button_row(
        u"应用父级",
        lambda *_: apply_parent_keys(),
        (0.55, 0.55, 0.65),
        u"间接清理",
        lambda *_: interval_clear_keys(),
        (0.55, 0.55, 0.60),
    )

    _two_button_row(
        u"清除范围外",
        lambda *_: clear_keys_outside_range(),
        (0.50, 0.55, 0.50),
        u"清除范围内",
        lambda *_: clear_keys_in_range(),
        (0.55, 0.50, 0.50),
    )

    cmds.button(label=u"应用对象关键帧", height=28, backgroundColor=(0.5, 0.5, 0.65),
                command=lambda *_: apply_object_keys_last_is_source())

    cmds.showWindow(w)
    return w


class KeyframeToolsDialog(QtWidgets.QDialog):
    """关键帧工具的Qt对话框。"""

    def __init__(self, parent=None):
        super(KeyframeToolsDialog, self).__init__(parent)
        self.setObjectName(_QT_WINDOW_OBJECT)
        self.setWindowTitle(u"关键帧工具")

        # 设置窗口标志
        try:
            self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        except Exception:
            pass

        self.resize(480, 380)
        self._setup_ui()

    def closeEvent(self, event):
        """窗口关闭时注销Qt样式目标。"""
        try:
            adv_module = _get_adv_main_module()
            if adv_module:
                unregister_func = getattr(adv_module, '_adv_unregister_qt_style_target', None)
                if callable(unregister_func):
                    unregister_func(_QT_WINDOW_OBJECT)
        except Exception:
            pass
        super(KeyframeToolsDialog, self).closeEvent(event)

    def _setup_ui(self):
        """构建UI界面。"""
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # 标题
        title_label = QtWidgets.QLabel(u"关键帧工具")
        title_font = title_label.font()
        try:
            title_font.setPointSize(12)
            title_font.setBold(True)
        except Exception:
            pass
        title_label.setFont(title_font)
        main_layout.addWidget(title_label)

        # 描述
        desc_label = QtWidgets.QLabel(u"快速管理和操作关键帧的工具集")
        desc_label.setWordWrap(True)
        main_layout.addWidget(desc_label)

        # 分隔线
        line = QtWidgets.QFrame()
        try:
            line.setFrameShape(QtWidgets.QFrame.HLine)
            line.setFrameShadow(QtWidgets.QFrame.Sunken)
        except Exception:
            pass
        main_layout.addWidget(line)

        # 间隔设置区域
        interval_label = QtWidgets.QLabel(u"间隔设置")
        interval_font = interval_label.font()
        try:
            interval_font.setBold(True)
        except Exception:
            pass
        interval_label.setFont(interval_font)
        main_layout.addWidget(interval_label)

        interval_layout = QtWidgets.QHBoxLayout()
        interval_layout.setSpacing(8)

        interval_text = QtWidgets.QLabel(u"间隔帧数:")
        interval_layout.addWidget(interval_text)

        self.interval_spinbox = QtWidgets.QSpinBox()
        self.interval_spinbox.setMinimum(2)
        self.interval_spinbox.setMaximum(100)
        self.interval_spinbox.setValue(5)
        self.interval_spinbox.setFixedWidth(80)
        interval_layout.addWidget(self.interval_spinbox)

        interval_hint = QtWidgets.QLabel(u"(用于间隔清理功能)")
        interval_layout.addWidget(interval_hint)
        interval_layout.addStretch()

        main_layout.addLayout(interval_layout)
        main_layout.addSpacing(10)

        # 操作按钮区域
        buttons_label = QtWidgets.QLabel(u"关键帧操作")
        buttons_font = buttons_label.font()
        try:
            buttons_font.setBold(True)
        except Exception:
            pass
        buttons_label.setFont(buttons_font)
        main_layout.addWidget(buttons_label)

        # 第一行：应用父级 + 间隔清理
        row1_layout = QtWidgets.QHBoxLayout()
        row1_layout.setSpacing(8)

        btn_apply_parent = QtWidgets.QPushButton(u"应用父级关键帧")
        btn_apply_parent.setMinimumHeight(36)
        btn_apply_parent.clicked.connect(self._on_apply_parent_keys)
        row1_layout.addWidget(btn_apply_parent)

        btn_interval_clear = QtWidgets.QPushButton(u"间隔清理关键帧")
        btn_interval_clear.setMinimumHeight(36)
        btn_interval_clear.clicked.connect(self._on_interval_clear_keys)
        row1_layout.addWidget(btn_interval_clear)

        main_layout.addLayout(row1_layout)

        # 第二行：清除范围外 + 清除范围内
        row2_layout = QtWidgets.QHBoxLayout()
        row2_layout.setSpacing(8)

        btn_clear_outside = QtWidgets.QPushButton(u"清除范围外关键帧")
        btn_clear_outside.setMinimumHeight(36)
        btn_clear_outside.clicked.connect(self._on_clear_keys_outside_range)
        row2_layout.addWidget(btn_clear_outside)

        btn_clear_inside = QtWidgets.QPushButton(u"清除范围内关键帧")
        btn_clear_inside.setMinimumHeight(36)
        btn_clear_inside.clicked.connect(self._on_clear_keys_in_range)
        row2_layout.addWidget(btn_clear_inside)

        main_layout.addLayout(row2_layout)

        # 第三行：应用对象关键帧
        btn_apply_object = QtWidgets.QPushButton(u"应用对象关键帧（最后为源）")
        btn_apply_object.setMinimumHeight(36)
        btn_apply_object.clicked.connect(self._on_apply_object_keys)
        main_layout.addWidget(btn_apply_object)

        main_layout.addSpacing(10)

        # 帮助信息
        help_label = QtWidgets.QLabel(
            u"提示：\n"
            u"• 应用父级：将父级对象的关键帧时间应用到选中对象\n"
            u"• 间隔清理：保留每隔N帧的关键帧，删除其他帧\n"
            u"• 清除范围外/内：根据时间滑块范围清除关键帧\n"
            u"• 应用对象：将最后选择的对象关键帧应用到其他对象"
        )
        help_label.setWordWrap(True)
        main_layout.addWidget(help_label)

        main_layout.addStretch()

    def _on_apply_parent_keys(self):
        """应用父级关键帧按钮回调。"""
        try:
            apply_parent_keys()
        except Exception as e:
            cmds.warning(u"应用父级关键帧失败: {}".format(str(e)))

    def _on_interval_clear_keys(self):
        """间隔清理关键帧按钮回调。"""
        try:
            interval = self.interval_spinbox.value()
            interval_clear_keys(interval=interval)
        except Exception as e:
            cmds.warning(u"间隔清理关键帧失败: {}".format(str(e)))

    def _on_clear_keys_outside_range(self):
        """清除范围外关键帧按钮回调。"""
        try:
            clear_keys_outside_range()
        except Exception as e:
            cmds.warning(u"清除范围外关键帧失败: {}".format(str(e)))

    def _on_clear_keys_in_range(self):
        """清除范围内关键帧按钮回调。"""
        try:
            clear_keys_in_range()
        except Exception as e:
            cmds.warning(u"清除范围内关键帧失败: {}".format(str(e)))

    def _on_apply_object_keys(self):
        """应用对象关键帧按钮回调。"""
        try:
            apply_object_keys_last_is_source()
        except Exception as e:
            cmds.warning(u"应用对象关键帧失败: {}".format(str(e)))
