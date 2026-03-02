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

# Stored as long path
ALIGN_TARGET_OBJECT = None


WINDOW_NAME = "ADV_AlignToolWin"
_QT_WINDOW_OBJECT = "ADV_AlignToolQtWin"

_UI = {
    "targetText": "advAlignTargetText",
    "posX": "advAlignPosX",
    "posY": "advAlignPosY",
    "posZ": "advAlignPosZ",
    "rotX": "advAlignRotX",
    "rotY": "advAlignRotY",
    "rotZ": "advAlignRotZ",
    "space": "advAlignSpace",
    "ref": "advAlignRef",
}


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


def _ctrl_exists(name):
    try:
        return bool(name) and cmds.control(name, exists=True)
    except Exception:
        return False


def _get_cb(name, default=True):
    try:
        if _ctrl_exists(name):
            return bool(cmds.checkBox(name, q=True, v=True))
    except Exception:
        pass
    return bool(default)


def _get_rbg(name, default=1):
    try:
        if _ctrl_exists(name):
            return int(cmds.radioButtonGrp(name, q=True, sl=True))
    except Exception:
        pass
    return int(default)


def get_world_pos(node):
    """获取世界坐标位置"""
    return cmds.xform(node, q=True, ws=True, t=True)


def get_world_rot(node):
    """获取世界旋转(欧拉角)"""
    return cmds.xform(node, q=True, ws=True, rotation=True)


def get_pivot_world(node):
    """获取pivot世界坐标"""
    return cmds.xform(node, q=True, ws=True, rp=True)


def get_bbox_center(node):
    """获取包围盒中心"""
    bb = cmds.exactWorldBoundingBox(node)
    cx = (bb[0] + bb[3]) / 2.0
    cy = (bb[1] + bb[4]) / 2.0
    cz = (bb[2] + bb[5]) / 2.0
    return [cx, cy, cz]


def set_align_target(text_control=None):
    """设置对齐目标"""
    global ALIGN_TARGET_OBJECT

    selection = cmds.ls(selection=True, long=True)
    if not selection:
        cmds.warning(u"请先选择一个目标物体!")
        return

    ALIGN_TARGET_OBJECT = selection[0]
    target_name = ALIGN_TARGET_OBJECT.split('|')[-1]
    try:
        if not text_control:
            text_control = _UI.get("targetText")
        if text_control and cmds.control(text_control, exists=True):
            cmds.text(text_control, edit=True, label=target_name)
    except Exception:
        pass
    print(u"对齐目标已设置: %s" % target_name)


def run_align_tool(text_control=None, ui=None):
    """执行对齐操作"""
    global ALIGN_TARGET_OBJECT

    if ui is None:
        ui = {}

    if not ALIGN_TARGET_OBJECT:
        cmds.warning(u"请先设置对齐目标!")
        return

    # 检查目标是否还存在
    if not cmds.objExists(ALIGN_TARGET_OBJECT):
        cmds.warning(u"目标对象不存在!")
        ALIGN_TARGET_OBJECT = None
        try:
            if not text_control:
                text_control = ui.get("targetText") or _UI.get("targetText")
            if text_control and cmds.control(text_control, exists=True):
                cmds.text(text_control, edit=True, label=u"<未设置>")
        except Exception:
            pass
        return

    # 获取当前选择
    selection = cmds.ls(selection=True, long=True)
    if not selection:
        cmds.warning(u"请选择需要对齐的对象!")
        return

    # 移除目标自身
    objects = [obj for obj in selection if obj != ALIGN_TARGET_OBJECT]
    if not objects:
        cmds.warning(u"除目标外没有其它对象需要对齐!")
        return

    # 获取UI参数
    # Allow standalone window controls (preferred) and keep legacy embedded control names as fallback.
    posX = ui.get("posX") or _UI.get("posX") or "alignPosX"
    posY = ui.get("posY") or _UI.get("posY") or "alignPosY"
    posZ = ui.get("posZ") or _UI.get("posZ") or "alignPosZ"
    rotX = ui.get("rotX") or _UI.get("rotX") or "alignRotX"
    rotY = ui.get("rotY") or _UI.get("rotY") or "alignRotY"
    rotZ = ui.get("rotZ") or _UI.get("rotZ") or "alignRotZ"
    space = ui.get("space") or _UI.get("space") or "alignSpace"
    ref = ui.get("ref") or _UI.get("ref") or "alignRef"

    opt = {
        'posX': _get_cb(posX, True),
        'posY': _get_cb(posY, True),
        'posZ': _get_cb(posZ, True),
        'rotX': _get_cb(rotX, True),
        'rotY': _get_cb(rotY, True),
        'rotZ': _get_cb(rotZ, True),
        'space': 'world' if _get_rbg(space, 1) == 1 else 'local',
        'ref': 'pivot' if _get_rbg(ref, 1) == 1 else 'bbox'
    }

    # 获取参考点位置
    if opt['ref'] == 'bbox':
        ref_pos = get_bbox_center(ALIGN_TARGET_OBJECT)
    else:
        ref_pos = get_pivot_world(ALIGN_TARGET_OBJECT)

    # 目标旋转
    target_rot_world = get_world_rot(ALIGN_TARGET_OBJECT)

    # 执行对齐
    for obj in objects:
        # 位置对齐
        if opt['space'] == 'world':
            if opt['posX'] or opt['posY'] or opt['posZ']:
                current_pos = get_world_pos(obj)
                new_pos = [current_pos[0], current_pos[1], current_pos[2]]
                if opt['posX']:
                    new_pos[0] = ref_pos[0]
                if opt['posY']:
                    new_pos[1] = ref_pos[1]
                if opt['posZ']:
                    new_pos[2] = ref_pos[2]
                cmds.xform(obj, ws=True, t=new_pos)

        # 旋转对齐
        if opt['rotX'] or opt['rotY'] or opt['rotZ']:
            if opt['space'] == 'world':
                current_rot = get_world_rot(obj)
                new_rot = [current_rot[0], current_rot[1], current_rot[2]]
                if opt['rotX']:
                    new_rot[0] = target_rot_world[0]
                if opt['rotY']:
                    new_rot[1] = target_rot_world[1]
                if opt['rotZ']:
                    new_rot[2] = target_rot_world[2]
                cmds.xform(obj, ws=True, rotation=new_rot)

    try:
        cmds.inViewMessage(amg=u"<hl>对齐完成</hl>", pos='midCenter', fade=True)
    except Exception:
        pass
    print(u"对齐完成: %d 个对象已对齐到 %s" % (len(objects), ALIGN_TARGET_OBJECT.split('|')[-1]))


def simple_align_objects():
    """简单对齐：选择两个对象，第二个对齐到第一个"""
    selection = cmds.ls(selection=True, long=True)
    if len(selection) < 2:
        cmds.warning(u"请选择两个对象：第一个是源对象，第二个是目标对象（将对齐到第一个）")
        return

    source = selection[0]
    target = selection[1]

    # 获取源对象的世界空间位置和旋转
    t = cmds.xform(source, q=True, ws=True, t=True)
    r = cmds.xform(source, q=True, ws=True, ro=True)

    # 将目标对象对齐到源对象
    cmds.undoInfo(openChunk=True)
    try:
        cmds.xform(target, ws=True, t=(t[0], t[1], t[2]))
        cmds.xform(target, ws=True, ro=(r[0], r[1], r[2]))

        try:
            cmds.inViewMessage(amg=u"<hl>对齐完成</hl>", pos='midCenter', fade=True)
        except Exception:
            pass
        print(u"已对齐: %s -> %s" % (source.split("|")[-1], target.split("|")[-1]))
    finally:
        cmds.undoInfo(closeChunk=True)


def align_bone_chain():
    """对齐骨骼链：选择两个根骨骼，通过名称匹配对齐整个层级（支持分支）"""
    selection = cmds.ls(selection=True, long=True, type="transform")
    if len(selection) < 2:
        cmds.warning(u"请选择两个根骨骼：第一个是源骨骼链，第二个是目标骨骼链（将对齐到第一个）")
        return

    source_root = selection[0]
    target_root = selection[1]

    # 递归获取骨骼层级结构（保持父子关系）
    def get_hierarchy_dict(root):
        """返回 {short_name: full_path} 字典"""
        result = {}
        short_name = root.split("|")[-1]
        result[short_name] = root

        children = cmds.listRelatives(root, children=True, type="transform", f=True) or []
        for child in children:
            result.update(get_hierarchy_dict(child))

        return result

    # 获取源和目标的骨骼字典
    source_dict = get_hierarchy_dict(source_root)
    target_dict = get_hierarchy_dict(target_root)

    # 找到匹配的骨骼对
    matched_pairs = []
    for short_name, target_path in target_dict.items():
        if short_name in source_dict:
            matched_pairs.append((source_dict[short_name], target_path))

    if not matched_pairs:
        cmds.warning(u"没有找到匹配的骨骼（根据骨骼名称匹配）")
        return

    # 对齐所有匹配的骨骼
    cmds.undoInfo(openChunk=True)
    try:
        for src, tgt in matched_pairs:
            t = cmds.xform(src, q=True, ws=True, t=True)
            r = cmds.xform(src, q=True, ws=True, ro=True)

            cmds.xform(tgt, ws=True, t=(t[0], t[1], t[2]))
            cmds.xform(tgt, ws=True, ro=(r[0], r[1], r[2]))

        try:
            cmds.inViewMessage(amg=u"<hl>骨骼链对齐完成</hl>", pos='midCenter', fade=True)
        except Exception:
            pass
        print(u"已对齐骨骼链: %d 个骨骼从 %s 对齐到 %s" % (len(matched_pairs), source_root.split("|")[-1], target_root.split("|")[-1]))
    finally:
        cmds.undoInfo(closeChunk=True)


def run_mirror_tool(mirror_axis='YZ', mirror_behavior=True):
    """执行镜像操作

    Args:
        mirror_axis: 镜像轴 ('YZ', 'XZ', 'XY')
        mirror_behavior: 是否镜像行为 (True/False)
    """
    selection = cmds.ls(selection=True, long=True)
    if not selection:
        cmds.warning(u"请先选择需要镜像的对象!")
        return

    cmds.undoInfo(openChunk=True)
    try:
        for obj in selection:
            try:
                # 使用Maya的mirrorJoint命令
                cmds.mirrorJoint(
                    obj,
                    mirrorYZ=(mirror_axis == 'YZ'),
                    mirrorXZ=(mirror_axis == 'XZ'),
                    mirrorXY=(mirror_axis == 'XY'),
                    mirrorBehavior=mirror_behavior
                )
            except Exception as e:
                cmds.warning(u"镜像失败 {}: {}".format(obj.split('|')[-1], str(e)))

        try:
            cmds.inViewMessage(amg=u"<hl>镜像完成</hl>", pos='midCenter', fade=True)
        except Exception:
            pass
        print(u"镜像完成: %d 个对象" % len(selection))
    finally:
        cmds.undoInfo(closeChunk=True)


def show():
    """弹出对齐工具窗口。"""
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
    """使用Qt创建现代化的对齐工具窗口。"""
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

    dialog = AlignToolDialog(parent=maya_main_window)

    # 应用ADV的Qt样式
    try:
        adv_module = _get_adv_main_module()
        if adv_module:
            # 注册到Qt样式目标
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

    w = cmds.window(WINDOW_NAME, title=u"对齐工具", widthHeight=(440, 380), sizeable=True)
    cmds.columnLayout(adjustableColumn=True, columnAttach=('both', 8), rowSpacing=6)

    label_w = 90

    # 快速对齐区域
    cmds.text(label=u"快速对齐", font="boldLabelFont", align="left")
    cmds.separator(height=4)

    cmds.button(label=u"对齐对象 (选2个：第2个对齐到第1个)", height=30, backgroundColor=(0.4, 0.6, 0.9),
                command=lambda *_: simple_align_objects())

    cmds.button(label=u"对齐骨骼链 (选2个根骨骼：第2个对齐到第1个)", height=30, backgroundColor=(0.4, 0.6, 0.9),
                command=lambda *_: align_bone_chain())

    cmds.separator(height=10, style="in")

    # 高级对齐区域
    cmds.text(label=u"高级对齐（需要先设置目标）", font="boldLabelFont", align="left")
    cmds.separator(height=4)

    cmds.text(label=u"目标对象:", font="boldLabelFont", align="left")
    cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnWidth2=(label_w, 1), columnAlign2=('left', 'left'), columnAttach=[(1, 'both', 0), (2, 'both', 0)])
    cmds.text(label='', width=label_w)
    cmds.text(_UI["targetText"], label=u"<未设置>", align="left", backgroundColor=(0.2, 0.2, 0.2))
    cmds.setParent('..')

    cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnWidth2=(label_w, 1), columnAlign2=('left', 'left'), columnAttach=[(1, 'both', 0), (2, 'both', 0)])
    cmds.text(label='', width=label_w)
    cmds.button(label=u"设置目标 (选第一个)", height=25, backgroundColor=(0.4, 0.5, 0.6),
                command=lambda *_: set_align_target())
    cmds.setParent('..')

    cmds.separator(height=6)

    cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnWidth2=(label_w, 1), columnAlign2=('left', 'left'), columnAttach=[(1, 'both', 0), (2, 'both', 0)])
    cmds.text(label=u"位置轴:", align='left', width=label_w)
    cmds.rowLayout(numberOfColumns=3, columnWidth3=(60, 60, 60))
    cmds.checkBox(_UI["posX"], label='X', v=True)
    cmds.checkBox(_UI["posY"], label='Y', v=True)
    cmds.checkBox(_UI["posZ"], label='Z', v=True)
    cmds.setParent('..')
    cmds.setParent('..')

    cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnWidth2=(label_w, 1), columnAlign2=('left', 'left'), columnAttach=[(1, 'both', 0), (2, 'both', 0)])
    cmds.text(label=u"旋转轴:", align='left', width=label_w)
    cmds.rowLayout(numberOfColumns=3, columnWidth3=(60, 60, 60))
    cmds.checkBox(_UI["rotX"], label='X', v=True)
    cmds.checkBox(_UI["rotY"], label='Y', v=True)
    cmds.checkBox(_UI["rotZ"], label='Z', v=True)
    cmds.setParent('..')
    cmds.setParent('..')

    cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnWidth2=(label_w, 1), columnAlign2=('left', 'left'), columnAttach=[(1, 'both', 0), (2, 'both', 0)])
    cmds.text(label=u"空间:", align='left', width=label_w)
    cmds.radioButtonGrp(_UI["space"], labelArray2=[u"世界", u"本地"], numberOfRadioButtons=2, sl=1)
    cmds.setParent('..')

    cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnWidth2=(label_w, 1), columnAlign2=('left', 'left'), columnAttach=[(1, 'both', 0), (2, 'both', 0)])
    cmds.text(label=u"参考点:", align='left', width=label_w)
    cmds.radioButtonGrp(_UI["ref"], labelArray2=[u"Pivot", u"包围盒"], numberOfRadioButtons=2, sl=1)
    cmds.setParent('..')

    cmds.separator(height=6)

    cmds.button(label=u"执行高级对齐", height=30, backgroundColor=(0.4, 0.6, 0.9),
                command=lambda *_: run_align_tool())

    cmds.showWindow(w)
    return w


class AlignToolDialog(QtWidgets.QDialog):
    """对齐工具的Qt对话框。"""

    def __init__(self, parent=None):
        super(AlignToolDialog, self).__init__(parent)
        self.setObjectName(_QT_WINDOW_OBJECT)
        self.setWindowTitle(u"对齐工具")

        # 设置窗口标志
        try:
            self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        except Exception:
            pass

        self.resize(480, 520)
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
        super(AlignToolDialog, self).closeEvent(event)

    def _setup_ui(self):
        """构建UI界面。"""
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # 标题
        title_label = QtWidgets.QLabel(u"对齐工具")
        title_font = title_label.font()
        try:
            title_font.setPointSize(12)
            title_font.setBold(True)
        except Exception:
            pass
        title_label.setFont(title_font)
        main_layout.addWidget(title_label)

        # 描述
        desc_label = QtWidgets.QLabel(u"快速对齐和镜像对象")
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

        # 快速对齐区域
        quick_align_label = QtWidgets.QLabel(u"快速对齐")
        quick_align_font = quick_align_label.font()
        try:
            quick_align_font.setBold(True)
        except Exception:
            pass
        quick_align_label.setFont(quick_align_font)
        main_layout.addWidget(quick_align_label)

        # 简单对齐按钮
        btn_simple_align = QtWidgets.QPushButton(u"对齐对象 (选2个：第2个对齐到第1个)")
        btn_simple_align.setMinimumHeight(36)
        btn_simple_align.clicked.connect(self._on_simple_align)
        main_layout.addWidget(btn_simple_align)

        # 骨骼链对齐按钮
        btn_chain_align = QtWidgets.QPushButton(u"对齐骨骼链 (选2个根骨骼：第2个对齐到第1个)")
        btn_chain_align.setMinimumHeight(36)
        btn_chain_align.clicked.connect(self._on_chain_align)
        main_layout.addWidget(btn_chain_align)

        main_layout.addSpacing(10)

        # 分隔线
        line2 = QtWidgets.QFrame()
        try:
            line2.setFrameShape(QtWidgets.QFrame.HLine)
            line2.setFrameShadow(QtWidgets.QFrame.Sunken)
        except Exception:
            pass
        main_layout.addWidget(line2)

        # 高级对齐区域
        advanced_label = QtWidgets.QLabel(u"高级对齐（需要先设置目标）")
        advanced_font = advanced_label.font()
        try:
            advanced_font.setBold(True)
        except Exception:
            pass
        advanced_label.setFont(advanced_font)
        main_layout.addWidget(advanced_label)

        # 目标对象区域
        target_label = QtWidgets.QLabel(u"目标对象")
        main_layout.addWidget(target_label)

        self.target_label = QtWidgets.QLabel(u"<未设置>")
        main_layout.addWidget(self.target_label)

        btn_set_target = QtWidgets.QPushButton(u"设置目标 (选第一个)")
        btn_set_target.setMinimumHeight(32)
        btn_set_target.clicked.connect(self._on_set_target)
        main_layout.addWidget(btn_set_target)

        main_layout.addSpacing(10)

        # 对齐选项区域
        align_label = QtWidgets.QLabel(u"对齐选项")
        align_font = align_label.font()
        try:
            align_font.setBold(True)
        except Exception:
            pass
        align_label.setFont(align_font)
        main_layout.addWidget(align_label)

        # 位置轴
        pos_layout = QtWidgets.QHBoxLayout()
        pos_label = QtWidgets.QLabel(u"位置轴:")
        pos_label.setFixedWidth(80)
        pos_layout.addWidget(pos_label)

        self.cb_pos_x = QtWidgets.QCheckBox("X")
        self.cb_pos_x.setChecked(True)
        pos_layout.addWidget(self.cb_pos_x)

        self.cb_pos_y = QtWidgets.QCheckBox("Y")
        self.cb_pos_y.setChecked(True)
        pos_layout.addWidget(self.cb_pos_y)

        self.cb_pos_z = QtWidgets.QCheckBox("Z")
        self.cb_pos_z.setChecked(True)
        pos_layout.addWidget(self.cb_pos_z)

        pos_layout.addStretch()
        main_layout.addLayout(pos_layout)

        # 旋转轴
        rot_layout = QtWidgets.QHBoxLayout()
        rot_label = QtWidgets.QLabel(u"旋转轴:")
        rot_label.setFixedWidth(80)
        rot_layout.addWidget(rot_label)

        self.cb_rot_x = QtWidgets.QCheckBox("X")
        self.cb_rot_x.setChecked(True)
        rot_layout.addWidget(self.cb_rot_x)

        self.cb_rot_y = QtWidgets.QCheckBox("Y")
        self.cb_rot_y.setChecked(True)
        rot_layout.addWidget(self.cb_rot_y)

        self.cb_rot_z = QtWidgets.QCheckBox("Z")
        self.cb_rot_z.setChecked(True)
        rot_layout.addWidget(self.cb_rot_z)

        rot_layout.addStretch()
        main_layout.addLayout(rot_layout)

        # 空间
        space_layout = QtWidgets.QHBoxLayout()
        space_label = QtWidgets.QLabel(u"空间:")
        space_label.setFixedWidth(80)
        space_layout.addWidget(space_label)

        self.rb_world = QtWidgets.QRadioButton(u"世界")
        self.rb_world.setChecked(True)
        space_layout.addWidget(self.rb_world)

        self.rb_local = QtWidgets.QRadioButton(u"本地")
        space_layout.addWidget(self.rb_local)

        space_layout.addStretch()
        main_layout.addLayout(space_layout)

        # 参考点
        ref_layout = QtWidgets.QHBoxLayout()
        ref_label = QtWidgets.QLabel(u"参考点:")
        ref_label.setFixedWidth(80)
        ref_layout.addWidget(ref_label)

        self.rb_pivot = QtWidgets.QRadioButton(u"Pivot")
        self.rb_pivot.setChecked(True)
        ref_layout.addWidget(self.rb_pivot)

        self.rb_bbox = QtWidgets.QRadioButton(u"包围盒")
        ref_layout.addWidget(self.rb_bbox)

        ref_layout.addStretch()
        main_layout.addLayout(ref_layout)

        # 执行对齐按钮
        btn_align = QtWidgets.QPushButton(u"执行高级对齐")
        btn_align.setMinimumHeight(36)
        btn_align.clicked.connect(self._on_run_align)
        main_layout.addWidget(btn_align)

        main_layout.addSpacing(10)

        # 分隔线
        line3 = QtWidgets.QFrame()
        try:
            line3.setFrameShape(QtWidgets.QFrame.HLine)
            line3.setFrameShadow(QtWidgets.QFrame.Sunken)
        except Exception:
            pass
        main_layout.addWidget(line3)

        # 镜像选项区域
        mirror_label = QtWidgets.QLabel(u"镜像选项")
        mirror_font = mirror_label.font()
        try:
            mirror_font.setBold(True)
        except Exception:
            pass
        mirror_label.setFont(mirror_font)
        main_layout.addWidget(mirror_label)

        # 镜像轴
        axis_layout = QtWidgets.QHBoxLayout()
        axis_label = QtWidgets.QLabel(u"镜像轴:")
        axis_label.setFixedWidth(80)
        axis_layout.addWidget(axis_label)

        self.rb_mirror_yz = QtWidgets.QRadioButton("YZ")
        self.rb_mirror_yz.setChecked(True)
        axis_layout.addWidget(self.rb_mirror_yz)

        self.rb_mirror_xz = QtWidgets.QRadioButton("XZ")
        axis_layout.addWidget(self.rb_mirror_xz)

        self.rb_mirror_xy = QtWidgets.QRadioButton("XY")
        axis_layout.addWidget(self.rb_mirror_xy)

        axis_layout.addStretch()
        main_layout.addLayout(axis_layout)

        # 镜像行为
        self.cb_mirror_behavior = QtWidgets.QCheckBox(u"镜像行为")
        self.cb_mirror_behavior.setChecked(True)
        main_layout.addWidget(self.cb_mirror_behavior)

        # 执行镜像按钮
        btn_mirror = QtWidgets.QPushButton(u"执行镜像")
        btn_mirror.setMinimumHeight(36)
        btn_mirror.clicked.connect(self._on_run_mirror)
        main_layout.addWidget(btn_mirror)

        main_layout.addStretch()

    def _on_simple_align(self):
        """简单对齐按钮回调。"""
        simple_align_objects()

    def _on_chain_align(self):
        """骨骼链对齐按钮回调。"""
        align_bone_chain()

    def _on_set_target(self):
        """设置目标按钮回调。"""
        global ALIGN_TARGET_OBJECT
        selection = cmds.ls(selection=True, long=True)
        if not selection:
            cmds.warning(u"请先选择一个目标物体!")
            return

        ALIGN_TARGET_OBJECT = selection[0]
        target_name = ALIGN_TARGET_OBJECT.split('|')[-1]
        self.target_label.setText(target_name)
        print(u"对齐目标已设置: %s" % target_name)

    def _on_run_align(self):
        """执行对齐按钮回调。"""
        global ALIGN_TARGET_OBJECT

        if not ALIGN_TARGET_OBJECT:
            cmds.warning(u"请先设置对齐目标!")
            return

        # 检查目标是否还存在
        if not cmds.objExists(ALIGN_TARGET_OBJECT):
            cmds.warning(u"目标对象不存在!")
            ALIGN_TARGET_OBJECT = None
            self.target_label.setText(u"<未设置>")
            return

        # 获取当前选择
        selection = cmds.ls(selection=True, long=True)
        if not selection:
            cmds.warning(u"请选择需要对齐的对象!")
            return

        # 移除目标自身
        objects = [obj for obj in selection if obj != ALIGN_TARGET_OBJECT]
        if not objects:
            cmds.warning(u"除目标外没有其它对象需要对齐!")
            return

        # 获取UI参数
        opt = {
            'posX': self.cb_pos_x.isChecked(),
            'posY': self.cb_pos_y.isChecked(),
            'posZ': self.cb_pos_z.isChecked(),
            'rotX': self.cb_rot_x.isChecked(),
            'rotY': self.cb_rot_y.isChecked(),
            'rotZ': self.cb_rot_z.isChecked(),
            'space': 'world' if self.rb_world.isChecked() else 'local',
            'ref': 'pivot' if self.rb_pivot.isChecked() else 'bbox'
        }

        # 获取参考点位置
        if opt['ref'] == 'bbox':
            ref_pos = get_bbox_center(ALIGN_TARGET_OBJECT)
        else:
            ref_pos = get_pivot_world(ALIGN_TARGET_OBJECT)

        # 目标旋转
        target_rot_world = get_world_rot(ALIGN_TARGET_OBJECT)

        # 执行对齐
        for obj in objects:
            # 位置对齐
            if opt['space'] == 'world':
                if opt['posX'] or opt['posY'] or opt['posZ']:
                    current_pos = get_world_pos(obj)
                    new_pos = [current_pos[0], current_pos[1], current_pos[2]]
                    if opt['posX']:
                        new_pos[0] = ref_pos[0]
                    if opt['posY']:
                        new_pos[1] = ref_pos[1]
                    if opt['posZ']:
                        new_pos[2] = ref_pos[2]
                    cmds.xform(obj, ws=True, t=new_pos)

            # 旋转对齐
            if opt['rotX'] or opt['rotY'] or opt['rotZ']:
                if opt['space'] == 'world':
                    current_rot = get_world_rot(obj)
                    new_rot = [current_rot[0], current_rot[1], current_rot[2]]
                    if opt['rotX']:
                        new_rot[0] = target_rot_world[0]
                    if opt['rotY']:
                        new_rot[1] = target_rot_world[1]
                    if opt['rotZ']:
                        new_rot[2] = target_rot_world[2]
                    cmds.xform(obj, ws=True, rotation=new_rot)

        try:
            cmds.inViewMessage(amg=u"<hl>对齐完成</hl>", pos='midCenter', fade=True)
        except Exception:
            pass
        print(u"对齐完成: %d 个对象已对齐到 %s" % (len(objects), ALIGN_TARGET_OBJECT.split('|')[-1]))

    def _on_run_mirror(self):
        """执行镜像按钮回调。"""
        # 获取镜像轴
        if self.rb_mirror_yz.isChecked():
            mirror_axis = 'YZ'
        elif self.rb_mirror_xz.isChecked():
            mirror_axis = 'XZ'
        else:
            mirror_axis = 'XY'

        # 获取镜像行为
        mirror_behavior = self.cb_mirror_behavior.isChecked()

        # 执行镜像
        run_mirror_tool(mirror_axis=mirror_axis, mirror_behavior=mirror_behavior)
