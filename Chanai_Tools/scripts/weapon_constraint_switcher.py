# -*- coding: utf-8 -*-

"""

Maya Weapon Constraint Switcher

武器约束快速切换工具

使用方法：

1. 运行脚本打开UI

2. 选择约束目标（如左手、右手控制器），点击"Add Constraint Target"添加

3. 选择武器控制器，点击"Setup Weapon Controller"

4. 在武器控制器的属性面板中使用Props切换约束，使用Align对齐

"""



import maya.cmds as cmds

import maya.mel as mel



try:

    from maya import OpenMayaUI as omui

except Exception:

    omui = None



QT_AVAILABLE = False

QtCore = None

QtWidgets = None

QtGui = None

_WRAP_INSTANCE = None

try:

    from PySide2 import QtCore, QtWidgets, QtGui  # type: ignore

    import shiboken2  # type: ignore

    _WRAP_INSTANCE = shiboken2.wrapInstance

    QT_AVAILABLE = True

except ImportError:

    try:

        from PySide6 import QtCore, QtWidgets, QtGui  # type: ignore

        import shiboken6  # type: ignore

        _WRAP_INSTANCE = shiboken6.wrapInstance

        QT_AVAILABLE = True

    except ImportError:

        QT_AVAILABLE = False



SCRIPT_VERSION = "WCS_2026_02_27_rebind_fix"



_WCS_QT_WINDOW = None





def _get_maya_main_window():

    """Return Maya main window as QtWidgets.QWidget."""

    if not QT_AVAILABLE or (omui is None) or (_WRAP_INSTANCE is None):

        return None

    try:

        ptr = omui.MQtUtil.mainWindow()

        if not ptr:

            return None

        return _WRAP_INSTANCE(int(ptr), QtWidgets.QWidget)

    except Exception:

        return None





def force_reset_wcs_jobs(verbose=True):

    """Force-kill stale Props/Align attributeChange jobs created by this tool."""

    jobs = cmds.scriptJob(listJobs=True) or []

    killed = []

    for job in jobs:

        j = str(job)

        if ('.Props' not in j) and ('.Align' not in j):

            continue

        if 'attributeChange' not in j:

            continue

        try:

            job_id = int(j.split(':', 1)[0])

        except Exception:

            continue

        if cmds.scriptJob(exists=job_id):

            cmds.scriptJob(kill=job_id, force=True)

            killed.append(job_id)

    if verbose:

        print("[WCS] {} force reset jobs: {}".format(SCRIPT_VERSION, killed))

    return killed



class WeaponConstraintSwitcher:

    def __init__(self):

        self.window_name = "weaponConstraintSwitcherWin"

        self.constraint_targets = ['L_Hand', 'R_Hand', 'Spine', 'World']  # 默认目标列表（不能有空格）

        self.weapon_ctrl = None

        self.script_jobs = []  # 存储 scriptJob ID

        self.language = 'zh'  # 默认中文 'zh' 或 'en'

        self.selected_index = -1  # 当前选中的目标索引

        self.debug_enabled = False  # 调试日志开关

        # (ctrl, frame_int, props_value) pairs already processed to ensure one-shot behavior.

        self._processed_props_switches = set()



        # UI 文本字典

        self.ui_text = {

            'zh': {

                'title': '武器约束切换器',

                'step1': '步骤 1: 管理约束目标列表',

                'input_name': '输入目标名称：',

                'add_to_list': '添加到列表',

                'current_targets': '目标列表：',

                'edit_buttons': '编辑操作：',

                'delete_btn': '删除',

                'modify_btn': '修改',

                'move_up_btn': '上移 ↑',

                'move_down_btn': '下移 ↓',

                'clear_targets': '清空列表',

                'step2': '步骤 2: 创建约束节点',

                'step2_desc': '选择武器控制器，然后点击创建约束：',

                'parent_level': '约束父级层数：',

                'create_constraint': '创建约束节点',

                'align_l_hand': '对齐 L hand',

                'align_r_hand': '对齐 R hand',

                'help1': '创建后，使用 Props 属性切换约束目标',

                'help2': '使用 Align 属性对齐到当前目标',

                'language_switch': '切换语言 (Switch Language)',

                'debug_mode': '调试模式（打印日志到脚本编辑器）',

                'no_targets': '还未添加目标...',

                'warning_no_name': '请输入目标名称！',

                'warning_no_selection': '请先在列表中选择一个目标！',

                'warning_no_weapon': '请先选择武器控制器！',

                'warning_no_targets': '请先添加目标到列表！',

                'warning_no_parent': '找不到控制器的第 {level} 级父级！',

                'warning_no_source': '找不到源控制器: {name}',

                'warning_no_dst': '找不到目标控制器: {name}',

                'added_to_list': '已添加到列表',

                'deleted_from_list': '已从列表删除',

                'modified_target': '已修改目标名称',

                'created_controllers': '已创建 {count} 个控制器并设置约束',

                'constraint_target': '约束目标: {target}',

                'setup_complete': '设置完成',

                'already_setup_title': '已经设置过',

                'already_setup_msg': '{ctrl} 已经设置过约束。是否重新设置？',

                'aligned_to': '已对齐到',

                'aligned_target': '已对齐 {dst} 到 {src}',

                'select_target_hint': '点击列表中的目标进行选择'

            },

            'en': {

                'title': 'Weapon Constraint Switcher',

                'step1': 'Step 1: Manage Constraint Target List',

                'input_name': 'Enter target name:',

                'add_to_list': 'Add to List',

                'current_targets': 'Target List:',

                'edit_buttons': 'Edit Operations:',

                'delete_btn': 'Delete',

                'modify_btn': 'Modify',

                'move_up_btn': 'Move Up ↑',

                'move_down_btn': 'Move Down ↓',

                'clear_targets': 'Clear List',

                'step2': 'Step 2: Create Constraint Node',

                'step2_desc': 'Select weapon controller, then click create:',

                'parent_level': 'Constraint Parent Level:',

                'create_constraint': 'Create Constraint Node',

                'align_l_hand': 'Align L hand',

                'align_r_hand': 'Align R hand',

                'help1': 'After creation, use Props attribute to switch targets',

                'help2': 'Use Align attribute to align to current target',

                'language_switch': '切换语言 (Switch Language)',

                'debug_mode': 'Debug Mode (print logs to Script Editor)',

                'no_targets': 'No targets added yet...',

                'warning_no_name': 'Please enter a target name!',

                'warning_no_selection': 'Please select a target from the list first!',

                'warning_no_weapon': 'Please select a weapon controller!',

                'warning_no_targets': 'Please add targets to the list first!',

                'warning_no_parent': 'Cannot find level {level} parent of controller!',

                'warning_no_source': 'Cannot find source controller: {name}',

                'warning_no_dst': 'Cannot find destination controller: {name}',

                'added_to_list': 'Added to list',

                'deleted_from_list': 'Deleted from list',

                'modified_target': 'Modified target name',

                'created_controllers': 'Created {count} controllers and setup constraint',

                'constraint_target': 'Constraint target: {target}',

                'setup_complete': 'setup complete',

                'already_setup_title': 'Already Setup',

                'already_setup_msg': '{ctrl} already has constraint setup. Rebuild?',

                'aligned_to': 'Aligned to',

                'aligned_target': 'Aligned {dst} to {src}',

                'select_target_hint': 'Click a target in the list to select'

            }

        }



    def get_text(self, key):

        """获取当前语言的文本"""

        return self.ui_text[self.language].get(key, key)



    def _dbg(self, message):

        """Print debug message when debug mode is enabled."""

        if self.debug_enabled:

            print("[WCS DEBUG] {}".format(message))



    def _translation_from_matrix(self, matrix_vals):

        """Extract world translation from a 4x4 matrix flat list (row-major)."""

        try:

            if matrix_vals and len(matrix_vals) >= 16:

                return (

                    float(matrix_vals[12]),

                    float(matrix_vals[13]),

                    float(matrix_vals[14]),

                )

        except Exception:

            pass

        return None



    def _read_world_matrix(self, node, at_time=None):

        """Read node.worldMatrix[0] at specific time without changing currentTime."""

        if not node or (not cmds.objExists(node)):

            return None

        try:

            if at_time is None:

                raw = cmds.getAttr('{}.worldMatrix[0]'.format(node))

            else:

                raw = cmds.getAttr('{}.worldMatrix[0]'.format(node), time=at_time)

            if not raw:

                return None

            vals = raw[0] if isinstance(raw[0], (tuple, list)) else raw

            vals = list(vals)

            if len(vals) >= 16:

                return vals[:16]

        except Exception:

            return None

        return None



    def _dbg_node_pose(self, label, node, at_time=None):

        """Debug print node world translation/matrix snapshot."""

        m = self._read_world_matrix(node, at_time=at_time)

        t = self._translation_from_matrix(m)

        ttxt = "None" if t is None else "({:.3f}, {:.3f}, {:.3f})".format(t[0], t[1], t[2])

        if at_time is None:

            self._dbg("{}: node={}, t={}".format(label, node, ttxt))

        else:

            self._dbg("{}: node={}, time={:.3f}, t={}".format(label, node, float(at_time), ttxt))

        return m, t



    def _find_prev_transform_key_time(self, node, at_time):

        """Find latest keyed time <= at_time on node TR channels. Return None if no key."""

        if not node or (not cmds.objExists(node)):

            return None

        channels = (

            'translateX', 'translateY', 'translateZ',

            'rotateX', 'rotateY', 'rotateZ',

        )

        best = None

        tmax = float(at_time)

        for ch in channels:

            plug = "{}.{}".format(node, ch)

            if not cmds.objExists(plug):

                continue

            try:

                times = cmds.keyframe(plug, query=True, timeChange=True) or []

            except Exception:

                times = []

            for tt in times:

                try:

                    tv = float(tt)

                except Exception:

                    continue

                if tv <= tmax + 1e-4 and ((best is None) or (tv > best)):

                    best = tv

        return best



    def _resolve_scene_node(self, raw_name):

        """Resolve a transform by exact or namespace-free name (e.g. L_Hand / ns:L_Hand)."""

        if not raw_name:

            return None

        name = str(raw_name).strip()

        if not name:

            return None

        if cmds.objExists(name):

            return name



        matches = cmds.ls(name, long=False, type='transform') or []

        if matches:

            return matches[0]

        matches = cmds.ls('*:{}'.format(name), long=False, type='transform') or []

        if matches:

            return matches[0]

        return None



    def _get_axisfix_parent(self, node):

        """Return immediate AxisFix parent for node if any."""

        if not node or (not cmds.objExists(node)):

            return None

        try:

            parent = cmds.listRelatives(node, parent=True, fullPath=False) or []

        except Exception:

            parent = []

        if not parent:

            return None

        p = str(parent[0])

        if p.endswith('_AxisFix_GRP'):

            return p

        return None



    def _apply_world_matrix(self, node, world_matrix):

        """Apply world matrix to node. Prefer OPM when available and writable (ADV-style)."""

        if (not node) or (not cmds.objExists(node)):

            return False

        if (not world_matrix) or (len(world_matrix) != 16):

            return False



        try:

            if cmds.objExists(node + '.offsetParentMatrix'):

                incoming = cmds.listConnections(node + '.offsetParentMatrix', s=True, d=False, p=True) or []

                locked = False

                try:

                    locked = bool(cmds.getAttr(node + '.offsetParentMatrix', l=True))

                except Exception:

                    locked = False

                if (not incoming) and (not locked):

                    try:

                        import maya.api.OpenMaya as om

                        pim = cmds.getAttr(node + '.parentInverseMatrix')[0]

                        mm_world = om.MMatrix(list(world_matrix))

                        mm_pim = om.MMatrix(list(pim))

                        mm_local = mm_pim * mm_world

                        local = []

                        for r in range(4):

                            for c in range(4):

                                local.append(float(mm_local[r][c]))

                        try:

                            cmds.setAttr(node + '.offsetParentMatrix', *local, type='matrix')

                        except Exception:

                            cmds.setAttr(node + '.offsetParentMatrix', local, type='matrix')

                        return True

                    except Exception:

                        pass

        except Exception:

            pass



        try:

            cmds.xform(node, ws=True, m=world_matrix)

            return True

        except Exception:

            return False



    def align_to_hand(self, hand_name, *args, **kwargs):

        """Align our hand target (L_Hand/R_Hand) to ADV rig hand controller (IKArm/FKWrist)."""

        weapon_ctrl = kwargs.get('weapon_ctrl', None)

        parent_level = kwargs.get('parent_level', None)

        if weapon_ctrl:

            selection = [weapon_ctrl]

        else:

            selection = cmds.ls(selection=True) or []



        if not selection:

            cmds.warning(self.get_text('warning_no_weapon'))

            return False

        cmds.undoInfo(openChunk=True, chunkName='WP_Props_AlignHand')

        try:

            result = self._align_to_hand_impl(hand_name, selection, parent_level)

        finally:

            cmds.undoInfo(closeChunk=True)

        return result

    def _align_to_hand_impl(self, hand_name, selection, parent_level):

        """align_to_hand 内部实现（在 undo chunk 内执行）"""

        self.weapon_ctrl = selection[0]



        if parent_level is None:

            parent_level = 1

            try:

                if hasattr(self, 'parent_level_field'):

                    parent_level = cmds.intField(self.parent_level_field, query=True, value=True)

            except Exception:

                parent_level = 1

        try:

            parent_level = int(parent_level)

        except Exception:

            parent_level = 1



        # Destination must be our own target controller (e.g. L_Hand / R_Hand),

        # not the constrained parent group.

        dst_node = self._resolve_scene_node(hand_name)

        if not dst_node:

            cmds.warning(self.get_text('warning_no_dst').format(name=hand_name))

            return False



        # Resolve ADV side source (prefer IKArm, fallback to FKWrist/FKXWrist).

        side = 'L' if 'L' in str(hand_name).upper() else 'R'

        source_node = None

        src_candidates = [

            'IKArm_{}'.format(side),

            'FKWrist_{}'.format(side),

            'FKXWrist_{}'.format(side),

            'AlignIKToWrist_{}'.format(side),

        ]

        for n in src_candidates:

            source_node = self._resolve_scene_node(n)

            if source_node:

                break



        # If selected node has namespace, prefer namespaced ADV controls.

        if (not source_node) and self.weapon_ctrl and (':' in self.weapon_ctrl):

            ns = self.weapon_ctrl.rsplit(':', 1)[0]

            for n in src_candidates:

                source_node = self._resolve_scene_node('{}:{}'.format(ns, n))

                if source_node:

                    break



        if not source_node:

            cmds.warning(self.get_text('warning_no_source').format(name='/'.join(src_candidates)))

            return False



        world_m = self._read_world_matrix(source_node)

        if not world_m:

            cmds.warning(self.get_text('warning_no_source').format(name=source_node))

            return False



        # ADV-style correction: if destination is under AxisFix, drive AxisFix parent and zero local TR.

        axisfix_parent = self._get_axisfix_parent(dst_node)

        driven_node = axisfix_parent if axisfix_parent else dst_node

        ok = self._apply_world_matrix(driven_node, world_m)



        if axisfix_parent:

            try:

                cmds.xform(dst_node, os=True, t=(0.0, 0.0, 0.0))

            except Exception:

                pass

            try:

                cmds.xform(dst_node, os=True, ro=(0.0, 0.0, 0.0))

            except Exception:

                pass



        if not ok:

            return False



        self._dbg("Align hand(ADV): src={}, dst={}, axisFix={}".format(source_node, dst_node, axisfix_parent))

        try:

            msg = self.get_text('aligned_target').format(dst=dst_node, src=source_node)

        except Exception:

            msg = "Aligned {} to {}".format(dst_node, source_node)

        cmds.inViewMessage(amg='<hl>{}</hl>'.format(msg), pos='topCenter', fade=True)

        return True



    def create_ui(self):

        """创建UI界面"""

        if cmds.window(self.window_name, exists=True):

            cmds.deleteUI(self.window_name)



        window = cmds.window(self.window_name, title=self.get_text('title'), widthHeight=(450, 450))



        main_layout = cmds.columnLayout(adjustableColumn=True, rowSpacing=5, columnAttach=('both', 5))



        # 标题

        self.title_text = cmds.text(label=self.get_text('title'), font="boldLabelFont", height=30)

        cmds.separator(height=10)



        # 步骤 1: 管理目标列表

        self.step1_text = cmds.text(label=self.get_text('step1'), align="left", font="boldLabelFont")



        # 输入框和添加按钮

        cmds.rowLayout(numberOfColumns=2, adjustableColumn=1, columnAttach=[(1, 'both', 0), (2, 'both', 5)])

        self.input_name_text = cmds.text(label=self.get_text('input_name'), align="left", width=100)

        cmds.setParent('..')



        cmds.rowLayout(numberOfColumns=2, adjustableColumn=1, columnAttach=[(1, 'both', 0), (2, 'both', 5)])

        self.input_name_field = cmds.textField(placeholderText="L_Hand")

        self.add_to_list_btn = cmds.button(label=self.get_text('add_to_list'), command=self.add_to_list, width=100, backgroundColor=[0.4, 0.6, 0.4])

        cmds.setParent('..')



        cmds.separator(height=5)



        # 目标列表

        self.current_targets_text = cmds.text(label=self.get_text('current_targets'), align="left")

        self.target_list_text = cmds.textScrollList(

            numberOfRows=8,

            allowMultiSelection=False,

            selectCommand=self.on_target_selected,

            height=120

        )



        # 编辑按钮

        self.edit_buttons_text = cmds.text(label=self.get_text('edit_buttons'), align="left")

        cmds.rowLayout(numberOfColumns=5, adjustableColumn=5, columnAttach=[(1, 'both', 2), (2, 'both', 2), (3, 'both', 2), (4, 'both', 2), (5, 'both', 2)])

        self.delete_btn = cmds.button(label=self.get_text('delete_btn'), command=self.delete_target, backgroundColor=[0.6, 0.3, 0.3])

        self.modify_btn = cmds.button(label=self.get_text('modify_btn'), command=self.modify_target, backgroundColor=[0.5, 0.5, 0.3])

        self.move_up_btn = cmds.button(label=self.get_text('move_up_btn'), command=self.move_up)

        self.move_down_btn = cmds.button(label=self.get_text('move_down_btn'), command=self.move_down)

        self.clear_targets_btn = cmds.button(label=self.get_text('clear_targets'), command=self.clear_targets, backgroundColor=[0.5, 0.3, 0.3])

        cmds.setParent('..')



        cmds.separator(height=10)



        # 步骤 2: 创建约束节点

        self.step2_text = cmds.text(label=self.get_text('step2'), align="left", font="boldLabelFont")

        self.step2_desc_text = cmds.text(label=self.get_text('step2_desc'), align="left")



        # 约束父级层数输入

        cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnAttach=[(1, 'both', 0), (2, 'both', 5)])

        self.parent_level_text = cmds.text(label=self.get_text('parent_level'), align="left", width=120)

        self.parent_level_field = cmds.intField(value=1, minValue=0, maxValue=10, step=1, width=60)

        cmds.setParent('..')



        cmds.separator(height=5)



        cmds.rowLayout(numberOfColumns=3, adjustableColumn=1, columnAttach=[(1, 'both', 0), (2, 'both', 4), (3, 'both', 4)])

        self.create_constraint_btn = cmds.button(label=self.get_text('create_constraint'), command=self.create_constraint_node, height=35, backgroundColor=[0.4, 0.5, 0.7])

        self.align_l_hand_btn = cmds.button(label=self.get_text('align_l_hand'), command=lambda *_: self.align_to_hand('L_Hand'), height=35, backgroundColor=[0.35, 0.45, 0.6])

        self.align_r_hand_btn = cmds.button(label=self.get_text('align_r_hand'), command=lambda *_: self.align_to_hand('R_Hand'), height=35, backgroundColor=[0.35, 0.45, 0.6])

        cmds.setParent('..')



        cmds.separator(height=10)



        # 帮助信息

        self.help1_text = cmds.text(label=self.get_text('help1'), align="left", font="smallPlainLabelFont")

        self.help2_text = cmds.text(label=self.get_text('help2'), align="left", font="smallPlainLabelFont")



        cmds.separator(height=10)



        # 语言切换按钮

        cmds.button(label=self.get_text('language_switch'), command=self.toggle_language, height=25, backgroundColor=[0.3, 0.3, 0.4])



        # 调试开关

        self.debug_check = cmds.checkBox(

            label=self.get_text('debug_mode'),

            value=self.debug_enabled,

            changeCommand=self.on_debug_toggle

        )



        cmds.showWindow(window)

        self.update_target_list_display()



    def toggle_language(self, *args):

        """切换语言"""

        self.language = 'en' if self.language == 'zh' else 'zh'

        self.refresh_ui()



    def on_debug_toggle(self, *args):

        """UI debug checkbox callback."""

        try:

            self.debug_enabled = bool(cmds.checkBox(self.debug_check, query=True, value=True))

        except Exception:

            self.debug_enabled = False

        print("[WCS] Debug mode: {}".format('ON' if self.debug_enabled else 'OFF'))



    def refresh_ui(self):

        """刷新UI文本"""

        cmds.window(self.window_name, edit=True, title=self.get_text('title'))

        cmds.text(self.title_text, edit=True, label=self.get_text('title'))

        cmds.text(self.step1_text, edit=True, label=self.get_text('step1'))

        cmds.text(self.input_name_text, edit=True, label=self.get_text('input_name'))

        cmds.button(self.add_to_list_btn, edit=True, label=self.get_text('add_to_list'))

        cmds.text(self.current_targets_text, edit=True, label=self.get_text('current_targets'))

        cmds.text(self.edit_buttons_text, edit=True, label=self.get_text('edit_buttons'))

        cmds.button(self.delete_btn, edit=True, label=self.get_text('delete_btn'))

        cmds.button(self.modify_btn, edit=True, label=self.get_text('modify_btn'))

        cmds.button(self.move_up_btn, edit=True, label=self.get_text('move_up_btn'))

        cmds.button(self.move_down_btn, edit=True, label=self.get_text('move_down_btn'))

        cmds.button(self.clear_targets_btn, edit=True, label=self.get_text('clear_targets'))

        cmds.text(self.step2_text, edit=True, label=self.get_text('step2'))

        cmds.text(self.step2_desc_text, edit=True, label=self.get_text('step2_desc'))

        cmds.text(self.parent_level_text, edit=True, label=self.get_text('parent_level'))

        cmds.button(self.create_constraint_btn, edit=True, label=self.get_text('create_constraint'))

        if hasattr(self, 'align_l_hand_btn'):

            cmds.button(self.align_l_hand_btn, edit=True, label=self.get_text('align_l_hand'))

        if hasattr(self, 'align_r_hand_btn'):

            cmds.button(self.align_r_hand_btn, edit=True, label=self.get_text('align_r_hand'))

        cmds.text(self.help1_text, edit=True, label=self.get_text('help1'))

        cmds.text(self.help2_text, edit=True, label=self.get_text('help2'))

        if hasattr(self, 'debug_check'):

            cmds.checkBox(self.debug_check, edit=True, label=self.get_text('debug_mode'), value=self.debug_enabled)

        self.update_target_list_display()



    def add_to_list(self, *args):

        """添加目标到列表"""

        name = cmds.textField(self.input_name_field, query=True, text=True).strip()



        if not name:

            cmds.warning(self.get_text('warning_no_name'))

            return



        # 添加到列表

        self.constraint_targets.append(name)

        self.update_target_list_display()



        # 清空输入框

        cmds.textField(self.input_name_field, edit=True, text="")



        msg = u'<hl>{}</hl> {}'.format(name, self.get_text("added_to_list"))
        cmds.inViewMessage(amg=msg, pos='topCenter', fade=True)



    def on_target_selected(self):

        """当列表中的目标被选中时"""

        selected = cmds.textScrollList(self.target_list_text, query=True, selectIndexedItem=True)

        if selected:

            self.selected_index = selected[0] - 1  # 转换为0索引



    def delete_target(self, *args):

        """删除选中的目标"""

        if self.selected_index < 0 or self.selected_index >= len(self.constraint_targets):

            cmds.warning(self.get_text('warning_no_selection'))

            return



        deleted_name = self.constraint_targets[self.selected_index]

        del self.constraint_targets[self.selected_index]

        self.selected_index = -1



        self.update_target_list_display()

        msg = u'<hl>{}</hl> {}'.format(deleted_name, self.get_text("deleted_from_list"))
        cmds.inViewMessage(amg=msg, pos='topCenter', fade=True)



    def modify_target(self, *args):

        """修改选中的目标名称"""

        if self.selected_index < 0 or self.selected_index >= len(self.constraint_targets):

            cmds.warning(self.get_text('warning_no_selection'))

            return



        new_name = cmds.textField(self.input_name_field, query=True, text=True).strip()



        if not new_name:

            cmds.warning(self.get_text('warning_no_name'))

            return



        old_name = self.constraint_targets[self.selected_index]

        self.constraint_targets[self.selected_index] = new_name



        self.update_target_list_display()

        cmds.textField(self.input_name_field, edit=True, text="")



        msg = u'<hl>{}</hl> → <hl>{}</hl> {}'.format(old_name, new_name, self.get_text("modified_target"))
        cmds.inViewMessage(amg=msg, pos='topCenter', fade=True)



    def move_up(self, *args):

        """上移选中的目标"""

        if self.selected_index <= 0:

            return



        # 交换位置

        self.constraint_targets[self.selected_index], self.constraint_targets[self.selected_index - 1] =\
            self.constraint_targets[self.selected_index - 1], self.constraint_targets[self.selected_index]



        self.selected_index -= 1

        self.update_target_list_display()



        # 重新选中

        cmds.textScrollList(self.target_list_text, edit=True, selectIndexedItem=self.selected_index + 1)



    def move_down(self, *args):

        """下移选中的目标"""

        if self.selected_index < 0 or self.selected_index >= len(self.constraint_targets) - 1:

            return



        # 交换位置

        self.constraint_targets[self.selected_index], self.constraint_targets[self.selected_index + 1] =\
            self.constraint_targets[self.selected_index + 1], self.constraint_targets[self.selected_index]



        self.selected_index += 1

        self.update_target_list_display()



        # 重新选中

        cmds.textScrollList(self.target_list_text, edit=True, selectIndexedItem=self.selected_index + 1)



    def clear_targets(self, *args):

        """清空所有目标"""

        self.constraint_targets = []

        self.selected_index = -1

        self.update_target_list_display()



    def update_target_list_display(self):

        """更新目标列表显示"""

        cmds.textScrollList(self.target_list_text, edit=True, removeAll=True)



        if self.constraint_targets:

            for target in self.constraint_targets:

                cmds.textScrollList(self.target_list_text, edit=True, append=target)



    def _create_square_controller(self, name, size=1.5):

        """Create a flat square controller curve on XZ plane."""

        s = float(size)

        pts = [

            (-s, 0.0, -s),

            (-s, 0.0, s),

            (s, 0.0, s),

            (s, 0.0, -s),

            (-s, 0.0, -s),

        ]

        return cmds.curve(name=name, degree=1, point=pts)



    def _set_controller_green(self, ctrl):

        """Set curve shape override color to green."""

        if not ctrl or (not cmds.objExists(ctrl)):

            return

        shapes = cmds.listRelatives(ctrl, shapes=True, fullPath=True) or []

        for shape in shapes:

            try:

                if cmds.nodeType(shape) != 'nurbsCurve':

                    continue

            except Exception:

                continue

            try:

                cmds.setAttr('{}.overrideEnabled'.format(shape), 1)

                cmds.setAttr('{}.overrideRGBColors'.format(shape), 1)

                cmds.setAttr('{}.overrideColorRGB'.format(shape), 0.1, 0.9, 0.2)

            except Exception:

                pass



    def create_constraint_node(self, *args, **kwargs):

        """创建约束节点 - 创建控制器并设置约束"""

        weapon_ctrl = kwargs.get('weapon_ctrl', None)

        parent_level = kwargs.get('parent_level', None)

        if weapon_ctrl:

            selection = [weapon_ctrl]

        else:

            selection = cmds.ls(selection=True)



        if not selection:

            cmds.warning(self.get_text('warning_no_weapon'))

            return

        if not self.constraint_targets:

            cmds.warning(self.get_text('warning_no_targets'))

            return

        cmds.undoInfo(openChunk=True, chunkName='WP_Props_Create')

        try:

            self._create_constraint_node_impl(selection, parent_level)

        finally:

            cmds.undoInfo(closeChunk=True)

        return

    def _create_constraint_node_impl(self, selection, parent_level):

        """创建约束节点内部实现（在 undo chunk 内执行）"""



        self.weapon_ctrl = selection[0]



        # 获取父级层数（支持 Qt 调用传参）

        if parent_level is None:

            parent_level = 1

            try:

                if hasattr(self, 'parent_level_field'):

                    parent_level = cmds.intField(self.parent_level_field, query=True, value=True)

            except Exception:

                parent_level = 1

        try:

            parent_level = int(parent_level)

        except Exception:

            parent_level = 1



        # 获取约束目标（控制器的父级）

        constraint_target = self.get_parent_at_level(self.weapon_ctrl, parent_level)



        if not constraint_target:

            cmds.warning(self.get_text('warning_no_parent').format(level=parent_level))

            return



        print("Constraint target: {} (level {} parent of {})".format(constraint_target, parent_level, self.weapon_ctrl))



        # 检查是否已经设置过

        if cmds.attributeQuery('Props', node=self.weapon_ctrl, exists=True):

            result = cmds.confirmDialog(

                title=self.get_text('already_setup_title'),

                message=self.get_text('already_setup_msg').format(ctrl=self.weapon_ctrl),

                button=['Yes', 'No'],

                defaultButton='Yes',

                cancelButton='No',

                dismissString='No'

            )

            if result == 'No':

                return

            else:

                self.cleanup_existing_setup(self.weapon_ctrl, constraint_target)



        # 创建总组（所有 Props 控制器分组统一放这里）

        master_group = 'Bip_Props'

        if not cmds.objExists(master_group):

            master_group = cmds.group(empty=True, name=master_group)



        # 创建控制器

        created_controllers = []

        for i, name in enumerate(self.constraint_targets):

            # 给控制器名称添加 Props_ 前缀
            ctrl_name = 'Props_{}'.format(name)

            # 如果控制器不存在，则创建

            if not cmds.objExists(ctrl_name):

                # 计算位置：每个控制器间隔5单位

                x_pos = (i + 1) * 5.0



                # 创建方块控制器

                ctrl = self._create_square_controller(name=ctrl_name, size=1.5)



                # 设置位置

                cmds.setAttr('{}.translateX'.format(ctrl), x_pos)

                cmds.setAttr('{}.translateY'.format(ctrl), 0)

                cmds.setAttr('{}.translateZ'.format(ctrl), 0)



                # 统一设置为绿色

                self._set_controller_green(ctrl)



                # 创建组（使用控制器名称+_Group）

                group_name = '{}_Group'.format(ctrl_name)

                if not cmds.objExists(group_name):

                    group = cmds.group(ctrl, name=group_name)

                    # 将组移动到控制器的位置

                    cmds.xform(group, worldSpace=True, pivots=[x_pos, 0, 0])

                else:

                    group = group_name



                # 放进总组

                try:

                    parent = cmds.listRelatives(group, parent=True, fullPath=False) or []

                    if (not parent) or (parent[0] != master_group):

                        cmds.parent(group, master_group)

                except Exception:

                    pass



                created_controllers.append(ctrl)

            else:

                # 已存在控制器也统一为绿色；若其组存在，确保纳入总组

                self._set_controller_green(ctrl_name)

                group_name = '{}_Group'.format(ctrl_name)

                if cmds.objExists(group_name):

                    try:

                        parent = cmds.listRelatives(group_name, parent=True, fullPath=False) or []

                        if (not parent) or (parent[0] != master_group):

                            cmds.parent(group_name, master_group)

                    except Exception:

                        pass



        # 在创建约束之前，先对齐到第一个目标控制器

        first_target = 'Props_{}'.format(self.constraint_targets[0])

        if cmds.objExists(first_target):

            # 创建临时约束对齐到第一个目标（不保持偏移）

            temp_constraint = cmds.parentConstraint(first_target, constraint_target, maintainOffset=False)[0]

            cmds.delete(temp_constraint)

            print("Aligned {} to {}".format(constraint_target, first_target))



        # 创建约束（约束目标是父级组，但属性在控制器上）

        self.create_constraint_setup(self.weapon_ctrl, constraint_target)



        msg = self.get_text('created_controllers').format(count=len(created_controllers))
        msg2 = self.get_text("constraint_target").format(target=constraint_target)
        full_msg = u'<hl>{}</hl><br>{}'.format(msg, msg2)
        cmds.inViewMessage(amg=full_msg, pos='topCenter', fade=True)

        cmds.select(self.weapon_ctrl, replace=True)



    def get_parent_at_level(self, node, level):

        """获取指定层级的父级节点"""

        if level == 0:

            return node



        current = node

        for i in range(level):

            parents = cmds.listRelatives(current, parent=True, fullPath=False)

            if not parents:

                return None

            current = parents[0]



        return current



    def cleanup_existing_setup(self, ctrl, constraint_target=None):

        """清理已存在的设置"""

        # 如果没有指定约束目标，尝试从约束中查找

        if constraint_target is None:

            constraints = cmds.listConnections(ctrl, type='parentConstraint', source=False, destination=True)

            if constraints:

                # 获取约束的目标对象

                constraint_target_list = cmds.parentConstraint(constraints[0], query=True, targetList=True)

                if constraint_target_list:

                    constraint_target = constraint_target_list[0]



        # 删除约束（从约束目标上删除，parentConstraint 是流入 constraint_target 的，用 source=True）

        if constraint_target and cmds.objExists(constraint_target):

            constraints = cmds.listConnections(constraint_target, type='parentConstraint', source=True, destination=False)

            if constraints:

                for constraint in constraints:

                    if cmds.objExists(constraint):

                        cmds.delete(constraint)



        # 删除属性

        if cmds.attributeQuery('Props', node=ctrl, exists=True):

            cmds.deleteAttr('{}.Props'.format(ctrl))

        if cmds.attributeQuery('Align', node=ctrl, exists=True):

            cmds.deleteAttr('{}.Align'.format(ctrl))



        # 删除 condition 节点

        condition_nodes = cmds.ls('{}_propsCondition_*'.format(ctrl))

        if condition_nodes:

            cmds.delete(condition_nodes)



        # 删除该控制器相关 scriptJob（Align / Props）

        self.kill_ctrl_script_jobs(ctrl)



    def kill_ctrl_script_jobs(self, ctrl):

        """Kill old scriptJobs for this ctrl to avoid duplicate callbacks."""

        all_jobs = cmds.scriptJob(listJobs=True) or []

        killed = []

        for job in all_jobs:

            if ctrl not in job:

                continue

            if ('Align' not in job) and ('Props' not in job):

                continue

            try:

                job_id = int(str(job).split(':', 1)[0])

            except Exception:

                continue

            if cmds.scriptJob(exists=job_id):

                cmds.scriptJob(kill=job_id, force=True)

                killed.append(job_id)

        if killed:

            self._dbg("Killed old scriptJobs for {}: {}".format(ctrl, killed))



    def _get_props_targets_from_enum(self, ctrl):

        """Read target list snapshot from ctrl.Props enum."""

        if (not ctrl) or (not cmds.objExists(ctrl)):

            return []

        if not cmds.attributeQuery('Props', node=ctrl, exists=True):

            return []

        try:

            enum_info = cmds.attributeQuery('Props', node=ctrl, listEnum=True) or []

            if not enum_info:

                return []

            raw = enum_info[0] if isinstance(enum_info, (list, tuple)) else enum_info

            if not raw:

                return []

            return [t for t in str(raw).split(':') if t]

        except Exception:

            return []



    def _infer_setup_nodes_for_ctrl(self, ctrl):

        """Infer existing setup nodes for one ctrl.

        Returns:
            (constraint_node, constraint_target, targets)
        """

        targets = self._get_props_targets_from_enum(ctrl)

        constraint_node = None

        constraint_target = None

        cond_nodes = []

        try:

            cond_nodes = cmds.listConnections('{}.Props'.format(ctrl), source=False, destination=True, type='condition') or []

        except Exception:

            cond_nodes = []

        if not cond_nodes:

            try:

                cond_nodes = cmds.ls('{}_propsCondition_*'.format(ctrl), type='condition') or []

            except Exception:

                cond_nodes = []

        for cond in cond_nodes:

            try:

                out_dests = cmds.listConnections('{}.outColorR'.format(cond), source=False, destination=True, plugs=True) or []

            except Exception:

                out_dests = []

            for dst in out_dests:

                cnode = str(dst).split('.', 1)[0]

                try:

                    if cmds.nodeType(cnode) == 'parentConstraint':

                        constraint_node = cnode

                        break

                except Exception:

                    pass

            if constraint_node:

                break

        if constraint_node:

            try:

                c_targets = cmds.parentConstraint(constraint_node, query=True, targetList=True) or []

                if c_targets:

                    targets = list(c_targets)

            except Exception:

                pass

            for plug_name in ('constraintTranslateX', 'constraintRotateX', 'constraintParentInverseMatrix'):

                try:

                    conns = cmds.listConnections('{}.{}'.format(constraint_node, plug_name), source=False, destination=True, plugs=True) or []

                    if conns:

                        constraint_target = str(conns[0]).split('.', 1)[0]

                        break

                except Exception:

                    pass

            if not constraint_target:

                try:

                    src_conns = cmds.listConnections('{}.constraintParentInverseMatrix'.format(constraint_node), source=True, destination=False, plugs=True) or []

                    if src_conns:

                        constraint_target = str(src_conns[0]).split('.', 1)[0]

                except Exception:

                    pass

        return constraint_node, constraint_target, targets



    def rebind_existing_setups(self, reset_stuck_align=True, verbose=True):

        """Recreate Props/Align scriptJobs for already-built setups after scene reopen."""

        ctrls = []

        try:

            ctrls = cmds.ls(type='transform') or []

        except Exception:

            ctrls = []

        changed = []

        skipped = []

        for ctrl in ctrls:

            if (not cmds.objExists(ctrl)) or (not cmds.attributeQuery('Props', node=ctrl, exists=True)):

                continue

            if not cmds.attributeQuery('Align', node=ctrl, exists=True):

                continue

            constraint_node, constraint_target, targets = self._infer_setup_nodes_for_ctrl(ctrl)

            if (not constraint_target) or (not targets):

                skipped.append((ctrl, 'missing setup nodes'))

                continue

            if not cmds.objExists(constraint_target):

                skipped.append((ctrl, 'constraint target missing'))

                continue

            self.kill_ctrl_script_jobs(ctrl)

            self._processed_props_switches = {k for k in self._processed_props_switches if k[0] != ctrl}

            self.create_align_callback(ctrl, constraint_node, constraint_target, targets=targets)

            self.create_props_callback(ctrl, constraint_target, targets=targets)

            if reset_stuck_align:

                try:

                    if bool(cmds.getAttr('{}.Align'.format(ctrl))):

                        cmds.setAttr('{}.Align'.format(ctrl), 0)

                except Exception:

                    pass

            changed.append((ctrl, constraint_target, list(targets)))

        if verbose:

            print("[WCS] Rebind setups done: changed={} skipped={}".format(len(changed), len(skipped)))

            for item in changed:

                print("  [OK] ctrl={} target={} targets={}".format(item[0], item[1], item[2]))

            for item in skipped:

                print("  [SKIP] ctrl={} reason={}".format(item[0], item[1]))

        return {'changed': changed, 'skipped': skipped}



    def create_constraint_setup(self, ctrl, constraint_target):

        """创建约束设置



        Args:

            ctrl: 控制器（属性添加在这里）

            constraint_target: 约束目标（约束应用在这里）

        """

        # 先清理旧回调，避免重复监听导致执行两次/抖动

        self.kill_ctrl_script_jobs(ctrl)

        # Reset one-shot cache for this ctrl on rebuild.

        self._processed_props_switches = {k for k in self._processed_props_switches if k[0] != ctrl}

        # 将目标名称转换为带 Props_ 前缀的控制器名称
        targets = ['Props_{}'.format(name) for name in self.constraint_targets]

        self._dbg("Create setup ctrl={}, constraint_target={}, targets={}".format(ctrl, constraint_target, targets))



        # 创建 Parent Constraint（约束应用在 constraint_target 上）

        constraint = cmds.parentConstraint(targets, constraint_target, maintainOffset=True)[0]



        # 获取约束的权重属性

        target_weights = []

        for i, target in enumerate(targets):

            weight_attr = '{}.{}W{}'.format(constraint, target, i)

            target_weights.append(weight_attr)



        # 创建 Props 枚举属性（在控制器上）- 显示原始名称

        enum_string = ":".join(self.constraint_targets)

        cmds.addAttr(ctrl, longName='Props', attributeType='enum', enumName=enum_string, keyable=True)



        # 创建 Align 属性（在控制器上）- 枚举类型：0=Disabled, 1=Align

        cmds.addAttr(ctrl, longName='Align', attributeType='enum', enumName='Disabled:Align', keyable=True)



        # 设置 Props 切换逻辑

        for i, weight_attr in enumerate(target_weights):

            # 创建 condition 节点

            condition_node = cmds.createNode('condition', name='{}_propsCondition_{}'.format(ctrl, i))

            cmds.setAttr('{}.secondTerm'.format(condition_node), i)

            cmds.setAttr('{}.colorIfTrueR'.format(condition_node), 1)

            cmds.setAttr('{}.colorIfFalseR'.format(condition_node), 0)



            # 连接 Props 到 condition

            cmds.connectAttr('{}.Props'.format(ctrl), '{}.firstTerm'.format(condition_node))



            # 连接 condition 到权重

            cmds.connectAttr('{}.outColorR'.format(condition_node), weight_attr, force=True)



        # 初始化为第一个目标

        cmds.setAttr('{}.Props'.format(ctrl), 0)



        # 强制刷新约束权重，确保只有第一个目标的权重为1

        cmds.refresh()



        # 设置 Align 对齐逻辑（使用脚本节点）

        self.create_align_callback(ctrl, constraint, constraint_target, targets=targets)



        # 设置 Props 切换时的关键帧处理

        self.create_props_callback(ctrl, constraint_target, targets=targets)



    def create_align_callback(self, ctrl, constraint, constraint_target, targets=None):

        """创建对齐回调 - 使用 scriptJob 监听属性变化



        Args:

            ctrl: 控制器（属性在这里）

            constraint: 约束节点

            constraint_target: 约束目标（约束应用在这里）

        """

        targets = list(targets or self.constraint_targets)



        def align_to_target():

            """对齐函数"""

            if not cmds.objExists(ctrl):

                self._dbg("Align callback ignored, ctrl missing: {}".format(ctrl))

                return



            # 检查 Align 属性是否为 1 (Align)

            align_value = cmds.getAttr('{}.Align'.format(ctrl))

            if align_value != 1:

                self._dbg("Align callback ignored, {}.Align is not 1 (Align)".format(ctrl))

                return



            # 获取当前 Props 值

            current_props = cmds.getAttr('{}.Props'.format(ctrl))



            if current_props >= len(targets):

                cmds.setAttr('{}.Align'.format(ctrl), 0)

                self._dbg("Align callback reset Align, invalid Props index {}".format(current_props))

                return



            current_target = targets[current_props]

            self._dbg("Align callback running: ctrl={}, props={}, target={}".format(ctrl, current_props, current_target))



            # 查找当前的约束（在 constraint_target 上，parentConstraint 是流入 constraint_target 的）

            constraint_node = None

            if constraint and cmds.objExists(constraint):

                constraint_node = constraint

            else:

                constraints = cmds.listConnections(constraint_target, type='parentConstraint', source=True, destination=False)

                if constraints:

                    constraint_node = constraints[0]

            if constraint_node:



                # 断开所有 condition 节点的连接（但不删除节点）

                for i in range(len(targets)):

                    condition_node = '{}_propsCondition_{}'.format(ctrl, i)

                    if cmds.objExists(condition_node):

                        # 查找并断开连接

                        connections = cmds.listConnections('{}.outColorR'.format(condition_node), plugs=True, destination=True)

                        if connections:

                            for conn in connections:

                                cmds.disconnectAttr('{}.outColorR'.format(condition_node), conn)



                # 删除约束

                cmds.delete(constraint_node)



                # 对齐到目标（不保持偏移）

                temp_constraint = cmds.parentConstraint(current_target, constraint_target, maintainOffset=False)[0]

                cmds.delete(temp_constraint)



                # 重新创建约束（保持偏移）

                new_constraint = cmds.parentConstraint(targets, constraint_target, maintainOffset=True)[0]



                # 重新连接权重 - 确保使用正确的目标索引

                for i, target in enumerate(targets):

                    condition_node = '{}_propsCondition_{}'.format(ctrl, i)

                    if cmds.objExists(condition_node):

                        # 获取新约束中该目标的权重属性

                        weight_attr = '{}.{}W{}'.format(new_constraint, target, i)



                        # 检查权重属性是否存在

                        if cmds.attributeQuery('{}W{}'.format(target, i), node=new_constraint, exists=True):

                            cmds.connectAttr('{}.outColorR'.format(condition_node), weight_attr, force=True)

                        else:

                            print("Warning: Weight attribute {} not found".format(weight_attr))



                # 刷新以确保权重正确应用

                cmds.refresh()



                msg = u'{} {}'.format(self.get_text("aligned_to"), current_target)
                cmds.inViewMessage(amg='<hl>{}</hl>'.format(msg), pos='topCenter', fade=True)



            # 自动重置 Align 属性回 0 (Disabled)

            cmds.setAttr('{}.Align'.format(ctrl), 0)



        # 创建 scriptJob 监听 Align 属性变化

        job_id = cmds.scriptJob(attributeChange=['{}.Align'.format(ctrl), align_to_target], protected=True)

        self.script_jobs.append(job_id)



        print("Created scriptJob {} for {}.Align".format(job_id, ctrl))

        self._dbg("Registered Align scriptJob id={} for {}".format(job_id, ctrl))



    def create_props_callback(self, ctrl, constraint_target, targets=None):

        """创建 Props 切换回调 - 处理关键帧避免跳动



        Args:

            ctrl: 控制器（Props属性在这里）

            constraint_target: 约束目标（约束应用在这里）

        """

        targets = list(targets or self.constraint_targets)

        in_props_callback = [False]

        try:

            last_props_value = [int(cmds.getAttr('{}.Props'.format(ctrl)))]

        except Exception:

            last_props_value = [-1]



        def on_props_changed():

            """Props 切换时的处理函数"""

            if not cmds.objExists(ctrl):

                self._dbg("Props callback ignored, ctrl missing: {}".format(ctrl))

                return

            if in_props_callback[0]:

                self._dbg("Props callback ignored (re-entry)")

                return



            in_props_callback[0] = True

            try:

                # 获取当前时间和前一帧

                current_time = cmds.currentTime(query=True)

                prev_time = current_time - 1

                self._dbg("Props callback trigger: ctrl={}, time={}, prev={}".format(ctrl, current_time, prev_time))



                # 读取当前 Props 值

                current_props = int(cmds.getAttr('{}.Props'.format(ctrl)))

                # 按 S 打帧（值没变）时直接忽略，避免无意义重建约束引发抖动。

                if current_props == last_props_value[0]:

                    self._dbg("Props callback ignored (no value change): {}".format(current_props))

                    return



                # 仅在“当前帧值”和“前一帧值”不同的切换边界触发一次。

                try:

                    prev_props = int(cmds.getAttr('{}.Props'.format(ctrl), time=prev_time))

                except Exception:

                    prev_props = current_props

                if prev_props == current_props:

                    self._dbg(

                        "Props callback ignored (not a switch boundary): prev={}, cur={}".format(prev_props, current_props)

                    )

                    last_props_value[0] = current_props

                    return



                frame_key = int(round(float(current_time)))

                once_key = (ctrl, frame_key, int(current_props))

                if once_key in self._processed_props_switches:

                    self._dbg("Props callback ignored (already processed): {}".format(once_key))

                    last_props_value[0] = current_props

                    return



                last_props_value[0] = current_props

                self._dbg("Props changed: new={}".format(current_props))



                if current_props >= len(targets):

                    self._dbg("Props callback ignored (out of range): {} >= {}".format(current_props, len(targets)))

                    return



                if prev_props < 0 or prev_props >= len(targets):

                    self._dbg("Props callback ignored (prev out of range): {}".format(prev_props))

                    return



                # 按用户需求：读取“上一帧旧目标控制器（如 L_Hand）”的世界矩阵。

                prev_target_name = targets[prev_props]

                sample_time = prev_time

                # 优先使用“切换前最近关键帧（<= prev_time）”作为对齐来源，

                # 避免误取到切换帧或仅插值帧。

                try:

                    key_t = self._find_prev_transform_key_time(prev_target_name, prev_time)

                    if key_t is not None:

                        sample_time = float(key_t)

                except Exception:

                    sample_time = prev_time



                desired_world_matrix = None

                try:

                    raw = cmds.getAttr('{}.worldMatrix[0]'.format(prev_target_name), time=sample_time)

                    if raw:

                        vals = raw[0] if isinstance(raw[0], (tuple, list)) else raw

                        desired_world_matrix = list(vals)

                    self._dbg(

                        "Read source target matrix: target={}, prevProps={}, "

                        "sampleTime={:.3f}, fallbackPrev={:.3f}".format(prev_target_name, prev_props, float(sample_time), float(prev_time))

                    )

                except Exception:

                    desired_world_matrix = None

                    self._dbg("Failed to read previous-frame source target matrix: {}".format(prev_target_name))



                current_target = targets[current_props]

                self._dbg("Props target resolved: {}".format(current_target))



                # Position diagnostics: expected source pose and current driven/controller pose.

                _src_m, src_t = self._dbg_node_pose("SRC_PREV_TARGET", prev_target_name, at_time=sample_time)

                _new_tgt_m, new_tgt_t = self._dbg_node_pose("DST_CUR_TARGET", current_target, at_time=current_time)

                _before_m, before_t = self._dbg_node_pose("DRIVEN_BEFORE", constraint_target, at_time=current_time)

                _ctrl_before_m, ctrl_before_t = self._dbg_node_pose("CTRL_BEFORE", ctrl, at_time=current_time)



                # 采用“暴力粘贴”同款思路：直接把控制器贴到来源世界矩阵。

                # 不重建约束节点，避免求值抖动和来回触发。

                if desired_world_matrix and len(desired_world_matrix) == 16:

                    old_auto_key = False

                    try:

                        # 避免回位动作触发自动打帧，污染 10/11 帧并造成来回抖动。

                        old_auto_key = bool(cmds.autoKeyframe(query=True, state=True))

                        if old_auto_key:

                            cmds.autoKeyframe(state=False)

                        # Direct world-matrix paste to controller, like brute paste tool.

                        cmds.xform(ctrl, worldSpace=True, matrix=desired_world_matrix)



                        # 显式打键：确保通道上可见数值/关键帧，不依赖 auto key。

                        try:

                            cmds.setKeyframe(ctrl, attribute=['translateX', 'translateY', 'translateZ', 'rotateX', 'rotateY', 'rotateZ'])

                        except Exception:

                            self._dbg("Failed to key TR for {}".format(ctrl))

                        try:

                            cmds.setKeyframe(ctrl, attribute='Props')

                        except Exception:

                            self._dbg("Failed to key Props for {}".format(ctrl))



                        _ctrl_after_m, ctrl_after_t = self._dbg_node_pose("CTRL_AFTER_PASTE", ctrl, at_time=current_time)

                        _driven_after_m, driven_after_t = self._dbg_node_pose("DRIVEN_AFTER_SWITCH", constraint_target, at_time=current_time)



                        # Numeric delta diagnostics to confirm alignment quality on controller.

                        desired_t = self._translation_from_matrix(desired_world_matrix)

                        if desired_t and ctrl_after_t:

                            dx = ctrl_after_t[0] - desired_t[0]

                            dy = ctrl_after_t[1] - desired_t[1]

                            dz = ctrl_after_t[2] - desired_t[2]

                            self._dbg(

                                "CTRL_DELTA_FROM_DESIRED: dx={:.4f}, dy={:.4f}, dz={:.4f}; "

                                "desired={}, after={}".format(dx, dy, dz, desired_t, ctrl_after_t)

                            )



                        if ctrl_before_t and ctrl_after_t:

                            self._dbg(

                                "CTRL_MOVE_THIS_SWITCH: from={} -> to={}; "

                                "srcPrev={}, dstNow={}, drivenNow={}".format(ctrl_before_t, ctrl_after_t, src_t, new_tgt_t, driven_after_t)

                            )



                        self._dbg(

                            "Applied brute-matrix paste on switch boundary: oldTarget={}, "

                            "newTarget={}, ctrl={}".format(prev_target_name, current_target, ctrl)

                        )

                    except Exception:

                        self._dbg("Failed brute-matrix paste on switch boundary")

                    finally:

                        try:

                            if old_auto_key:

                                cmds.autoKeyframe(state=True)

                        except Exception:

                            pass

                else:

                    self._dbg("Skip switch-boundary paste: desired matrix invalid")



                self._processed_props_switches.add(once_key)



                print("Props switched to {} with world-matrix preservation".format(current_target))

            finally:

                in_props_callback[0] = False



        # 创建 scriptJob 监听 Props 属性变化

        job_id = cmds.scriptJob(attributeChange=['{}.Props'.format(ctrl), on_props_changed], protected=True)

        self.script_jobs.append(job_id)



        print("Created scriptJob {} for {}.Props".format(job_id, ctrl))

        self._dbg("Registered Props scriptJob id={} for {}, initialValue={}, version={}".format(job_id, ctrl, last_props_value[0], SCRIPT_VERSION))





if QT_AVAILABLE:

    class WeaponConstraintSwitcherQtDialog(QtWidgets.QDialog):

        """Dark Qt UI for weapon constraint switcher."""



        def __init__(self, switcher, parent=None):

            super(WeaponConstraintSwitcherQtDialog, self).__init__(parent)

            self.switcher = switcher

            self.setObjectName("WCS_DarkDialog")

            self.setWindowTitle(self.switcher.get_text('title'))

            self.resize(520, 620)

            self._build_ui()

            self._apply_dark_style()

            self.refresh_texts()

            self.refresh_target_list()

            self._force_label_colors()



        def _build_ui(self):

            root = QtWidgets.QVBoxLayout(self)

            root.setContentsMargins(12, 12, 12, 12)

            root.setSpacing(8)



            self.title_label = QtWidgets.QLabel()

            self.title_label.setObjectName("WcsTitle")

            root.addWidget(self.title_label)



            line = QtWidgets.QFrame()

            line.setFrameShape(QtWidgets.QFrame.HLine)

            line.setFrameShadow(QtWidgets.QFrame.Sunken)

            root.addWidget(line)



            self.step1_label = QtWidgets.QLabel()

            self.step1_label.setObjectName("WcsSection")

            root.addWidget(self.step1_label)



            row_input = QtWidgets.QHBoxLayout()

            self.input_name_label = QtWidgets.QLabel()

            row_input.addWidget(self.input_name_label)

            self.input_edit = QtWidgets.QLineEdit()

            self.input_edit.setPlaceholderText("L_Hand")

            row_input.addWidget(self.input_edit, 1)

            self.add_btn = QtWidgets.QPushButton()

            self.add_btn.clicked.connect(self.on_add)

            row_input.addWidget(self.add_btn)

            root.addLayout(row_input)



            self.current_targets_label = QtWidgets.QLabel()

            root.addWidget(self.current_targets_label)



            self.target_list = QtWidgets.QListWidget()

            self.target_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)

            self.target_list.currentRowChanged.connect(self.on_row_changed)

            root.addWidget(self.target_list, 1)



            self.edit_label = QtWidgets.QLabel()

            root.addWidget(self.edit_label)



            edit_grid = QtWidgets.QGridLayout()

            self.delete_btn = QtWidgets.QPushButton()

            self.delete_btn.clicked.connect(self.on_delete)

            edit_grid.addWidget(self.delete_btn, 0, 0)

            self.modify_btn = QtWidgets.QPushButton()

            self.modify_btn.clicked.connect(self.on_modify)

            edit_grid.addWidget(self.modify_btn, 0, 1)

            self.move_up_btn = QtWidgets.QPushButton()

            self.move_up_btn.clicked.connect(self.on_move_up)

            edit_grid.addWidget(self.move_up_btn, 0, 2)

            self.move_down_btn = QtWidgets.QPushButton()

            self.move_down_btn.clicked.connect(self.on_move_down)

            edit_grid.addWidget(self.move_down_btn, 0, 3)

            self.clear_btn = QtWidgets.QPushButton()

            self.clear_btn.clicked.connect(self.on_clear)

            edit_grid.addWidget(self.clear_btn, 0, 4)

            root.addLayout(edit_grid)



            line2 = QtWidgets.QFrame()

            line2.setFrameShape(QtWidgets.QFrame.HLine)

            line2.setFrameShadow(QtWidgets.QFrame.Sunken)

            root.addWidget(line2)



            self.step2_label = QtWidgets.QLabel()

            self.step2_label.setObjectName("WcsSection")

            root.addWidget(self.step2_label)

            self.step2_desc_label = QtWidgets.QLabel()

            root.addWidget(self.step2_desc_label)



            row_parent = QtWidgets.QHBoxLayout()

            self.parent_level_label = QtWidgets.QLabel()

            row_parent.addWidget(self.parent_level_label)

            self.parent_spin = QtWidgets.QSpinBox()

            self.parent_spin.setRange(0, 10)

            self.parent_spin.setValue(1)

            row_parent.addWidget(self.parent_spin)

            row_parent.addStretch(1)

            root.addLayout(row_parent)



            create_row = QtWidgets.QHBoxLayout()

            create_row.setSpacing(6)

            self.create_btn = QtWidgets.QPushButton()

            self.create_btn.setMinimumHeight(34)

            self.create_btn.clicked.connect(self.on_create)

            create_row.addWidget(self.create_btn, 1)

            self.align_l_btn = QtWidgets.QPushButton()

            self.align_l_btn.setMinimumHeight(34)

            self.align_l_btn.clicked.connect(self.on_align_l)

            create_row.addWidget(self.align_l_btn)

            self.align_r_btn = QtWidgets.QPushButton()

            self.align_r_btn.setMinimumHeight(34)

            self.align_r_btn.clicked.connect(self.on_align_r)

            create_row.addWidget(self.align_r_btn)

            root.addLayout(create_row)



            self.help1 = QtWidgets.QLabel()

            self.help1.setWordWrap(True)

            root.addWidget(self.help1)

            self.help2 = QtWidgets.QLabel()

            self.help2.setWordWrap(True)

            root.addWidget(self.help2)



            bottom = QtWidgets.QHBoxLayout()

            self.lang_btn = QtWidgets.QPushButton()

            self.lang_btn.clicked.connect(self.on_toggle_language)

            bottom.addWidget(self.lang_btn)

            self.debug_check = QtWidgets.QCheckBox()

            self.debug_check.setChecked(bool(self.switcher.debug_enabled))

            self.debug_check.toggled.connect(self.on_debug_toggled)

            bottom.addWidget(self.debug_check)

            bottom.addStretch(1)

            root.addLayout(bottom)



        def _apply_dark_style(self):

            self.setStyleSheet(

                """

                QDialog#WCS_DarkDialog { background-color: #252830; }

                QWidget { background-color: #252830; color: #D8D8D8; font-size: 12px; }

                QLabel { background: transparent; color: #D8D8D8; }

                QAbstractItemView, QListWidget, QListWidget::item, QLineEdit, QSpinBox,

                QPushButton, QCheckBox, QGroupBox, QRadioButton {

                    color: #D8D8D8;

                }

                QLabel#WcsTitle { font-size: 16px; font-weight: 700; color: #D8D8D8; padding: 2px 0 6px 0; }

                QLabel#WcsSection { font-size: 12px; font-weight: 600; color: #D8D8D8; }

                QLineEdit, QListWidget, QSpinBox {

                    background: #1F2127;

                    border: 1px solid #14151A;

                    border-radius: 8px;

                    padding: 4px 6px;

                    color: #D8D8D8;

                    selection-background-color: #4A90D9;

                    selection-color: #FFFFFF;

                }

                QLineEdit::placeholder { color: #9AA0AA; }

                QListWidget::item:selected { background: #4A90D9; color: #FFFFFF; }

                QPushButton {

                    background: #3A3F4A;

                    border: 1px solid #1E2026;

                    border-radius: 8px;

                    padding: 6px 10px;

                    min-height: 22px;

                    color: #D8D8D8;

                }

                QPushButton:hover { background: #4A4F5B; }

                QPushButton:pressed { background: #2E323B; }

                QPushButton:disabled { color: #9AA0AA; }

                QCheckBox { spacing: 6px; color: #D8D8D8; }

                QCheckBox::indicator { width: 12px; height: 12px; border-radius: 6px; border: 1px solid #14151A; background: transparent; }

                QCheckBox::indicator:checked { background: #4A90D9; border: 1px solid #4A90D9; }

                QFrame { color: #14151A; }

                """

            )



        def refresh_texts(self):

            t = self.switcher.get_text

            self.setWindowTitle(t('title'))

            self.title_label.setText(t('title'))

            self.step1_label.setText(t('step1'))

            self.input_name_label.setText(t('input_name'))

            self.add_btn.setText(t('add_to_list'))

            self.current_targets_label.setText(t('current_targets'))

            self.edit_label.setText(t('edit_buttons'))

            self.delete_btn.setText(t('delete_btn'))

            self.modify_btn.setText(t('modify_btn'))

            self.move_up_btn.setText(t('move_up_btn'))

            self.move_down_btn.setText(t('move_down_btn'))

            self.clear_btn.setText(t('clear_targets'))

            self.step2_label.setText(t('step2'))

            self.step2_desc_label.setText(t('step2_desc'))

            self.parent_level_label.setText(t('parent_level'))

            self.create_btn.setText(t('create_constraint'))

            self.align_l_btn.setText(t('align_l_hand'))

            self.align_r_btn.setText(t('align_r_hand'))

            self.help1.setText(t('help1'))

            self.help2.setText(t('help2'))

            self.lang_btn.setText(t('language_switch'))

            self.debug_check.setText(t('debug_mode'))

            self._force_label_colors()



        def _force_label_colors(self):

            """Force key labels to light text to avoid Maya/theme overrides."""

            white = 'color:#D8D8D8;background:transparent;'

            for w in (

                self.title_label,

                self.step1_label,

                self.input_name_label,

                self.current_targets_label,

                self.edit_label,

                self.step2_label,

                self.step2_desc_label,

                self.parent_level_label,

                self.help1,

                self.help2,

            ):

                try:

                    w.setStyleSheet(white)

                except Exception:

                    pass



        def refresh_target_list(self):

            self.target_list.blockSignals(True)

            self.target_list.clear()

            self.target_list.addItems(self.switcher.constraint_targets)

            if 0 <= self.switcher.selected_index < self.target_list.count():

                self.target_list.setCurrentRow(self.switcher.selected_index)

            self.target_list.blockSignals(False)



        def _warn(self, msg):

            cmds.warning(msg)



        def on_row_changed(self, row):

            self.switcher.selected_index = int(row)



        def on_add(self):

            name = self.input_edit.text().strip()

            if not name:

                self._warn(self.switcher.get_text('warning_no_name'))

                return

            self.switcher.constraint_targets.append(name)

            self.input_edit.clear()

            self.refresh_target_list()

            msg = u'<hl>{}</hl> {}'.format(name, self.switcher.get_text("added_to_list"))
            cmds.inViewMessage(amg=msg, pos='topCenter', fade=True)



        def on_delete(self):

            idx = self.switcher.selected_index

            if idx < 0 or idx >= len(self.switcher.constraint_targets):

                self._warn(self.switcher.get_text('warning_no_selection'))

                return

            name = self.switcher.constraint_targets[idx]

            del self.switcher.constraint_targets[idx]

            self.switcher.selected_index = -1

            self.refresh_target_list()

            msg = u'<hl>{}</hl> {}'.format(name, self.switcher.get_text("deleted_from_list"))
            cmds.inViewMessage(amg=msg, pos='topCenter', fade=True)



        def on_modify(self):

            idx = self.switcher.selected_index

            if idx < 0 or idx >= len(self.switcher.constraint_targets):

                self._warn(self.switcher.get_text('warning_no_selection'))

                return

            new_name = self.input_edit.text().strip()

            if not new_name:

                self._warn(self.switcher.get_text('warning_no_name'))

                return

            old_name = self.switcher.constraint_targets[idx]

            self.switcher.constraint_targets[idx] = new_name

            self.input_edit.clear()

            self.refresh_target_list()

            self.target_list.setCurrentRow(idx)

            msg = u'<hl>{}</hl> -> <hl>{}</hl> {}'.format(old_name, new_name, self.switcher.get_text("modified_target"))
            cmds.inViewMessage(amg=msg, pos='topCenter', fade=True)



        def on_move_up(self):

            idx = self.switcher.selected_index

            if idx <= 0:

                return

            t = self.switcher.constraint_targets

            t[idx - 1], t[idx] = t[idx], t[idx - 1]

            self.switcher.selected_index = idx - 1

            self.refresh_target_list()

            self.target_list.setCurrentRow(idx - 1)



        def on_move_down(self):

            idx = self.switcher.selected_index

            t = self.switcher.constraint_targets

            if idx < 0 or idx >= len(t) - 1:

                return

            t[idx + 1], t[idx] = t[idx], t[idx + 1]

            self.switcher.selected_index = idx + 1

            self.refresh_target_list()

            self.target_list.setCurrentRow(idx + 1)



        def on_clear(self):

            self.switcher.constraint_targets = []

            self.switcher.selected_index = -1

            self.refresh_target_list()



        def on_create(self):

            self.switcher.create_constraint_node(parent_level=int(self.parent_spin.value()))



        def on_align_l(self):

            self.switcher.align_to_hand('L_Hand', parent_level=int(self.parent_spin.value()))



        def on_align_r(self):

            self.switcher.align_to_hand('R_Hand', parent_level=int(self.parent_spin.value()))



        def on_toggle_language(self):

            self.switcher.language = 'en' if self.switcher.language == 'zh' else 'zh'

            self.refresh_texts()



        def on_debug_toggled(self, checked):

            self.switcher.debug_enabled = bool(checked)

            print("[WCS] Debug mode: {}".format('ON' if self.switcher.debug_enabled else 'OFF'))





def show_qt_ui(switcher):

    """Show dark Qt UI window."""

    global _WCS_QT_WINDOW

    if not QT_AVAILABLE:

        return None



    try:

        if _WCS_QT_WINDOW is not None:

            try:

                _WCS_QT_WINDOW.close()

                _WCS_QT_WINDOW.deleteLater()

            except Exception:

                pass

    except Exception:

        pass



    parent = _get_maya_main_window()

    _WCS_QT_WINDOW = WeaponConstraintSwitcherQtDialog(switcher, parent=parent)

    _WCS_QT_WINDOW.show()

    _WCS_QT_WINDOW.raise_()

    _WCS_QT_WINDOW.activateWindow()

    return _WCS_QT_WINDOW



def run(use_qt=True):

    """运行工具"""

    # Hard reset stale callbacks from previous code versions before creating UI.

    force_reset_wcs_jobs(verbose=True)

    print("[WCS] Running {}".format(SCRIPT_VERSION))

    switcher = WeaponConstraintSwitcher()

    # Recreate callbacks for existing scenes (scriptJobs are not persisted in Maya files).
    try:

        switcher.rebind_existing_setups(reset_stuck_align=True, verbose=True)

    except Exception as e:

        print("[WCS] Rebind existing setups failed: {}".format(e))

    if use_qt and QT_AVAILABLE:

        show_qt_ui(switcher)

    else:

        switcher.create_ui()



# 运行

if __name__ == "__main__":

    run()
