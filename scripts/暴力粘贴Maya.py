# -*- coding: utf-8 -*-
#!/usr/bin/env python
"""
暴力粘贴工具 Python版本 - Maya 2018中文显示完全修复版
兼容Maya 2018 (Python 2.7) 和更高版本
保留所有核心功能，修复中文显示问题
转写3DsMax的暴击粘贴
转写者：一方狂三
"""

import os
import json
import maya.mel as mel
import maya.cmds as cmds


class CPToolsPython:
    def __init__(self):
        self.window_name = "cpToolsPythonWin"
        self.data_dir = self.get_data_directory()
        self.language = "chinese"  # 默认中文
        self.pose_list = []
        self.anim_list = []
        self.current_mode = 1  # 1=姿态模式, 2=动画模式
        self.ignore_namespace = False  # 添加忽略命名空间属性

        # 确保数据目录存在
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        # 语言配置
        self.init_language()

        # UI控件引用
        self.ui_controls = {}

    def get_data_directory(self):
        """获取数据存储目录 - 修改为maya scripts平级路径的CopyLibrary文件夹"""
        try:
            # 获取maya的scripts目录
            scripts_dir = cmds.internalVar(usd=True)
            # 规范化路径格式
            scripts_dir = os.path.normpath(scripts_dir)
            # 到scripts的父目录
            parent_dir = os.path.dirname(scripts_dir)
            # 确保我们获取到了正确的父目录
            parent_dir = os.path.normpath(parent_dir)
            # 创建CopyLibrary目录
            copy_library_dir = os.path.join(parent_dir, "CopyLibrary")
            # 规范化最终路径
            copy_library_dir = os.path.normpath(copy_library_dir)

            # 确保目录存在
            if not os.path.exists(copy_library_dir):
                os.makedirs(copy_library_dir)

            # 创建pose和animation子目录
            pose_dir = os.path.join(copy_library_dir, "pose")
            anim_dir = os.path.join(copy_library_dir, "animation")
            if not os.path.exists(pose_dir):
                os.makedirs(pose_dir)
            if not os.path.exists(anim_dir):
                os.makedirs(anim_dir)

            return copy_library_dir
        except Exception as e:
            print("获取数据目录失败: {}".format(str(e)))

        #  fallback到旧路径
        user_dir = cmds.internalVar(userAppDir=True)
        return os.path.join(user_dir, "cptools_data").replace('/', '\\')

    def init_language(self):
        """初始化语言配置 - 修复Maya 2018中文显示"""
        self.lang_config = {
            "chinese": {
                "window_title": u"暴力帧拷贝粘贴V2.0 Python版",
                "pose_mode": u"姿态模式",
                "anim_mode": u"动画模式",
                "copy_frame": u"拷贝帧",
                "paste_frame": u"粘贴帧",
                "precision": u"精度",
                "offset": u"偏移",
                "times": u"次数",
                "delete_all": u"删除所有",
                "delete_sel": u"删除选中",
                "refresh": u"刷新列表",
                "frame_copy": u"逐帧拷贝-S",
                "key_copy": u"关键帧拷贝-K",
                "local_mode": u"本地模式",
                "auto_range": u"自动范围",
                "pose_list_label": u"姿态:",
                "anim_list_label": u"动画:",
                "saved_data_label": u"保存的数据:",
                "list_ops_label": u"列表操作:",
                "main_ops_label": u"主要操作:",
                "anim_settings_label": u"动画设置:",
                "range_label": u"范围:",
                "to_label": u"到",
                "custom_range_label": u"自定义范围",
                "general_settings_label": u"通用设置:",
                "options_label": u"选项:",
                "transform_control_label": u"变换控制:",
                "dense_frames_label": u"满",
                "dense_frames_tooltip": u"开启后每帧都有关键帧，关闭后仅在原关键帧间插值",
                "language_label": u"语言/Language:",
                "pseudo_tcb_label": u"伪TCB",
                # 消息文本
                "no_selection": u"请先选择至少一个物体",
                "copy_failed": u"拷贝失败: {}",
                "paste_failed": u"粘贴失败: {}",
                "no_valid_transform": u"没有有效的变换数据",
                "input_name_title": u"输入命名",
                "input_name_message": u"请输入姿态名称:",
                "confirm": u"确定",
                "cancel": u"取消",
                "overwrite_mode": u"覆盖模式",
                "recorded_pose": u"已记录 {} 个物体的姿态数据: {}",
                "select_pose": u"请选择一个姿态",
                "load_pose_failed": u"无法加载姿态数据",
                "select_objects": u"请先选择要应用变换的物体",
                "pasted_pose": u"已粘贴姿态数据到 {} 个物体 {}次",
                "select_animation": u"请选择一个动画",
                "load_anim_failed": u"无法加载动画数据",
                "time_range_error": u"时间范围错误",
                "no_valid_anim": u"没有记录到有效的动画数据",
                "recorded_anim": u"已记录 {} 个物体在 {}-{} 帧的动画数据",
                "no_valid_frames": u"没有有效的动画帧数据",
                "pasted_anim": u"已粘贴动画数据到 {} 个物体，{} 帧 ({}次)",
                "save_failed": u"保存文件失败: {}",
                "load_failed": u"加载数据失败: {}",
                "delete_all_files": u"已删除所有数据文件",
                "select_to_delete": u"请选择要删除的项目",
                "file_not_exist": u"文件不存在",
                "delete_failed": u"删除失败: {}",
                "deleted_pose": u"已删除姿态: {}",
                "deleted_anim": u"已删除动画: {}",
                "select_objects_first": u"请先选择物体",
                "reset_transforms": u"已重置 {} 个物体的变换",
                "select_rotation_objects": u"请选择至少一个有旋转动画的对象",
                "euler_applied": u"Euler过滤器已应用 - 处理了{}个对象",
                "no_rotation_anim": u"没有找到可处理的旋转动画对象",
                "tcb_applied": u"伪TCB效果已应用 - 处理了{}个对象 ({})",
                "dense_mode": u"满帧模式",
                "keyframe_mode": u"关键帧模式",
                "no_objects_in_scene": u"场景中找不到姿态相关的物体",
                "no_anim_objects_in_scene": u"场景中找不到动画相关的物体",
                "startup_failed": u"启动工具失败: {}",
                "ignore_namespace": u"忽略命名空间"
            },
            "english": {
                "window_title": "CopyPasteKey V2.0 Python",
                "pose_mode": "Pose Mode",
                "anim_mode": "Animation Mode",
                "copy_frame": "Copy",
                "paste_frame": "Paste",
                "precision": "Precision",
                "offset": "Offset",
                "times": "Times",
                "delete_all": "Delete All",
                "delete_sel": "Delete Selected",
                "refresh": "Refresh",
                "frame_copy": "Frame Copy-S",
                "key_copy": "Key Copy-K",
                "local_mode": "Local Mode",
                "auto_range": "Auto Range",
                "pose_list_label": "Pose:",
                "anim_list_label": "Animation:",
                "saved_data_label": "Saved Data:",
                "list_ops_label": "List Operations:",
                "main_ops_label": "Main Operations:",
                "anim_settings_label": "Animation Settings:",
                "range_label": "Range:",
                "to_label": "to",
                "custom_range_label": "Custom Range",
                "general_settings_label": "General Settings:",
                "options_label": "Options:",
                "transform_control_label": "Transform Control:",
                "dense_frames_label": "Dense",
                "dense_frames_tooltip": "Enable dense keyframes on every frame",
                "language_label": "Language:",
                "pseudo_tcb_label": "Pseudo TCB",
                # English messages
                "no_selection": "Please select at least one object",
                "copy_failed": "Copy failed: {}",
                "paste_failed": "Paste failed: {}",
                "no_valid_transform": "No valid transform data",
                "input_name_title": "Input Name",
                "input_name_message": "Enter pose name:",
                "confirm": "OK",
                "cancel": "Cancel",
                "ignore_namespace": "Ignore Namespace",
                "overwrite_mode": "Overwrite mode",
                "recorded_pose": "Recorded pose data for {} objects: {}",
                "select_pose": "Please select a pose",
                "load_pose_failed": "Failed to load pose data",
                "select_objects": "Please select objects to apply transform",
                "pasted_pose": "Pasted pose data to {} objects ({} times)",
                "select_animation": "Please select an animation",
                "load_anim_failed": "Failed to load animation data",
                "time_range_error": "Time range error",
                "no_valid_anim": "No valid animation data recorded",
                "recorded_anim": "Recorded animation data for {} objects from frame {}-{}",
                "no_valid_frames": "No valid animation frame data",
                "pasted_anim": "Pasted animation data to {} objects, {} frames ({} times)",
                "save_failed": "Save file failed: {}",
                "load_failed": "Load data failed: {}",
                "delete_all_files": "Deleted all data files",
                "select_to_delete": "Please select item to delete",
                "file_not_exist": "File does not exist",
                "delete_failed": "Delete failed: {}",
                "deleted_pose": "Deleted pose: {}",
                "deleted_anim": "Deleted animation: {}",
                "select_objects_first": "Please select objects first",
                "reset_transforms": "Reset transforms for {} objects",
                "select_rotation_objects": "Please select at least one object with rotation animation",
                "euler_applied": "Euler filter applied - processed {} objects",
                "no_rotation_anim": "No objects with rotation animation found",
                "tcb_applied": "Pseudo TCB effect applied - processed {} objects ({})",
                "dense_mode": "Dense Mode",
                "keyframe_mode": "Keyframe Mode",
                "no_objects_in_scene": "Cannot find pose-related objects in scene",
                "no_anim_objects_in_scene": "Cannot find animation-related objects in scene",
                "startup_failed": "Tool startup failed: {}"
            }
        }

    def get_text(self, key):
        """获取本地化文本 - 确保返回适合UI显示的字符串"""
        text = u"{}".format(self.lang_config[self.language].get(key, key))
        return text  # 转换为Maya UI可以正确显示的格式

    def on_ignore_namespace_changed(self, *args):
        """忽略命名空间选项变化回调"""
        self.ignore_namespace = cmds.checkBox(
            self.ui_controls['ignore_namespace'], q=True, value=True)

    def get_base_name(self, obj_name):
        """从对象名称中提取基本名称（忽略命名空间）"""
        # 分割对象名称，获取最后一部分（去除命名空间）
        return obj_name.split('|')[-1].split(':')[-1]

    def create_ui(self):
        """创建主UI界面 - 修复中文显示问题"""
        if cmds.window(self.window_name, exists=True):
            cmds.deleteUI(self.window_name)

        window = cmds.window(self.window_name,
                             title=self.get_text(u"window_title"),
                             widthHeight=(250, 400),
                             resizeToFitChildren=True)

        # 主布局
        main_layout = cmds.columnLayout(
            adjustableColumn=True, rowSpacing=5, columnAttach=('both', 5))

        # 模式选择
        cmds.separator(height=10)
        self.ui_controls['mode_radio'] = cmds.radioButtonGrp(
            numberOfRadioButtons=2,
            labelArray2=[self.get_text("pose_mode"),
                         self.get_text("anim_mode")],
            select=1,
            changeCommand=self.on_mode_changed
        )

        # 添加忽略命名空间选项
        self.ui_controls['ignore_namespace'] = cmds.checkBox(
            label=self.get_text("ignore_namespace"),
            value=False,
            changeCommand=self.on_ignore_namespace_changed
        )

        cmds.separator(height=10)

        # 列表区域
        self.ui_controls['saved_data_label'] = cmds.text(
            label=self.get_text("saved_data_label"), align='left')

        # 姿态列表
        self.ui_controls['pose_list'] = cmds.optionMenu(
            label=self.get_text("pose_list_label"),
            changeCommand=self.on_pose_selection_changed,
            visible=True
        )

        # 动画列表
        self.ui_controls['anim_list'] = cmds.optionMenu(
            label=self.get_text("anim_list_label"),
            changeCommand=self.on_anim_selection_changed,
            visible=False
        )

        cmds.separator(height=10)

        # 列表操作按钮
        self.ui_controls['list_ops_label'] = cmds.text(
            label=self.get_text("list_ops_label"), align='left')
        list_layout = cmds.rowLayout(
            numberOfColumns=3, adjustableColumn=1, columnAttach=[(1, 'both', 0), (2, 'both', 0), (3, 'both', 0)])
        self.ui_controls['refresh'] = cmds.button(
            label=self.get_text("refresh"), command=self.refresh_list)
        self.ui_controls['delete_sel'] = cmds.button(label=self.get_text("delete_sel"),
                                                     command=self.delete_selection)
        self.ui_controls['delete_all'] = cmds.button(label=self.get_text("delete_all"),
                                                     command=self.delete_all_files)
        cmds.setParent('..')

        cmds.separator(height=10)

        # 拷贝粘贴按钮
        self.ui_controls['main_ops_label'] = cmds.text(
            label=self.get_text("main_ops_label"), align='left')
        main_ops_layout = cmds.rowLayout(
            numberOfColumns=2, columnWidth2=(120, 120))
        self.ui_controls['copy_btn'] = cmds.button(
            label=self.get_text("copy_frame"),
            height=40,
            command=self.copy_transforms,
            backgroundColor=[0.4, 0.6, 0.8]
        )
        self.ui_controls['paste_btn'] = cmds.button(
            label=self.get_text("paste_frame"),
            height=40,
            command=self.paste_transforms,
            backgroundColor=[0.8, 0.6, 0.4]
        )
        cmds.setParent('..')

        cmds.separator(height=10)

        # 动画模式专用控件
        self.ui_controls['anim_settings_label'] = cmds.text(
            label=self.get_text("anim_settings_label"), align='left')

        # 拷贝模式
        self.ui_controls['copy_mode_radio'] = cmds.radioButtonGrp(
            numberOfRadioButtons=2,
            labelArray2=[self.get_text("frame_copy"),
                         self.get_text("key_copy")],
            select=1,
            enable=False
        )

        # 时间范围
        time_layout = cmds.rowLayout(
            numberOfColumns=4, columnWidth4=(60, 60, 60, 60))
        self.ui_controls['range_label'] = cmds.text(
            label=self.get_text("range_label"))
        self.ui_controls['start_frame'] = cmds.intField(
            value=1, enable=False, width=50)
        self.ui_controls['to_label'] = cmds.text(
            label=self.get_text("to_label"))
        self.ui_controls['end_frame'] = cmds.intField(
            value=100, enable=False, width=50)
        cmds.setParent('..')

        # 范围模式
        self.ui_controls['range_mode'] = cmds.checkBox(
            label=self.get_text("custom_range_label"),
            value=False,
            enable=False,
            changeCommand=self.toggle_range_mode
        )

        cmds.separator(height=10)

        # 通用设置
        self.ui_controls['general_settings_label'] = cmds.text(
            label=self.get_text("general_settings_label"), align='left')

        # 精度和次数
        settings_layout = cmds.rowLayout(
            numberOfColumns=4, columnWidth4=(60, 60, 60, 60))
        self.ui_controls['precision_label'] = cmds.text(
            label=self.get_text("precision") + ":")
        self.ui_controls['precision'] = cmds.intField(
            value=3, minValue=1, maxValue=10, width=50)
        self.ui_controls['times_label'] = cmds.text(
            label=self.get_text("times") + ":")
        self.ui_controls['paste_times'] = cmds.intField(
            value=1, minValue=1, maxValue=10, width=50)
        cmds.setParent('..')

        # 偏移
        offset_layout = cmds.rowLayout(
            numberOfColumns=2, columnWidth2=(120, 120))
        self.ui_controls['offset_label'] = cmds.text(
            label=self.get_text("offset") + ":")
        self.ui_controls['offset_field'] = cmds.intField(
            value=0, enable=False, width=100)
        cmds.setParent('..')

        cmds.separator(height=10)

        # 选项
        self.ui_controls['options_label'] = cmds.text(
            label=self.get_text("options_label"), align='left')

        self.ui_controls['local_checkbox'] = cmds.checkBox(
            label=self.get_text("local_mode"),
            value=False,
            changeCommand=self.refresh_list
        )

        self.ui_controls['range_checkbox'] = cmds.checkBox(
            label=self.get_text("auto_range"),
            value=False,
            enable=False,
            changeCommand=self.on_auto_range_changed
        )

        cmds.separator(height=10)

        # 变换控制
        self.ui_controls['transform_control_label'] = cmds.text(
            label=self.get_text("transform_control_label"), align='left')

        # 满帧开关
        self.ui_controls['dense_frames_check'] = cmds.checkBox(
            label=self.get_text("dense_frames_label"),
            value=True,
            annotation=self.get_text("dense_frames_tooltip")
        )

        transform_layout = cmds.rowLayout(
            numberOfColumns=3, adjustableColumn=1, columnAttach=[(1, 'both', 0), (2, 'both', 0), (3, 'both', 0)])
        self.ui_controls['reset_btn'] = cmds.button(
            label="Reset", command=self.reset_transforms)
        self.ui_controls['euler_btn'] = cmds.button(
            label="Euler", command=self.apply_euler_filter)
        self.ui_controls['pseudo_tcb_label'] = cmds.button(label=self.get_text("pseudo_tcb_label"),
                                                           command=self.apply_pseudo_tcb)
        cmds.setParent('..')

        cmds.separator(height=10)

        # 语言切换
        lang_layout = cmds.rowLayout(numberOfColumns=2, adjustableColumn=1, columnAttach=[
                                     (1, 'both', 0), (2, 'right', 0)])
        self.ui_controls['language_label'] = cmds.text(
            label=self.get_text("language_label"))
        self.ui_controls['lang_btn'] = cmds.button(
            label=(u"中") if self.language == "chinese" else "En",
            width=30,
            command=lambda *args: self.toggle_language()
        )
        cmds.setParent('..')

        cmds.separator(height=10)

        # 进度条
        self.ui_controls['progress_bar'] = cmds.progressBar(
            maxValue=100, height=8)

        cmds.showWindow(window)

        # 初始化界面状态
        self.refresh_list()
        self.update_mode_ui()

    def on_mode_changed(self, *args):
        """模式切换回调"""
        self.current_mode = cmds.radioButtonGrp(
            self.ui_controls['mode_radio'], q=True, select=True)
        self.update_mode_ui()
        self.refresh_list()

    def update_mode_ui(self):
        """更新界面状态根据当前模式"""
        is_pose_mode = (self.current_mode == 1)

        # 显示/隐藏对应的列表
        cmds.optionMenu(
            self.ui_controls['pose_list'], e=True, visible=is_pose_mode)
        cmds.optionMenu(
            self.ui_controls['anim_list'], e=True, visible=not is_pose_mode)

        # 启用/禁用动画模式特有的控件
        cmds.radioButtonGrp(
            self.ui_controls['copy_mode_radio'], e=True, enable=not is_pose_mode)
        cmds.checkBox(self.ui_controls['range_mode'],
                      e=True, enable=not is_pose_mode)
        cmds.checkBox(
            self.ui_controls['range_checkbox'], e=True, enable=not is_pose_mode)
        cmds.intField(self.ui_controls['offset_field'],
                      e=True, enable=not is_pose_mode)

        # 根据range_mode状态设置时间范围字段
        if not is_pose_mode:
            range_enabled = cmds.checkBox(
                self.ui_controls['range_mode'], q=True, value=True)
            cmds.intField(
                self.ui_controls['start_frame'], e=True, enable=range_enabled)
            cmds.intField(
                self.ui_controls['end_frame'], e=True, enable=range_enabled)
        else:
            cmds.intField(
                self.ui_controls['start_frame'], e=True, enable=False)
            cmds.intField(self.ui_controls['end_frame'], e=True, enable=False)

    def toggle_range_mode(self, value):
        """切换帧数范围模式"""
        cmds.intField(self.ui_controls['start_frame'], e=True, enable=value)
        cmds.intField(self.ui_controls['end_frame'], e=True, enable=value)

        if value:
            # 设置当前时间轴范围
            start_frame = int(cmds.playbackOptions(q=True, minTime=True))
            end_frame = int(cmds.playbackOptions(q=True, maxTime=True))
            cmds.intField(
                self.ui_controls['start_frame'], e=True, value=start_frame)
            cmds.intField(
                self.ui_controls['end_frame'], e=True, value=end_frame)

    def toggle_language(self, *args):
        """切换语言 - 只更新文本不重建UI以修复闪退问题"""
        # 切换语言
        if self.language == "chinese":
            self.language = "english"
        else:
            self.language = "chinese"

        # 更新窗口标题
        cmds.window(self.window_name, e=True,
                    title=self.get_text("window_title"))

        # 更新模式选择标签
        cmds.radioButtonGrp(self.ui_controls['mode_radio'], e=True,
                            labelArray2=[self.get_text("pose_mode"), self.get_text("anim_mode")])

        # 更新忽略命名空间复选框标签
        cmds.checkBox(self.ui_controls['ignore_namespace'], e=True,
                      label=self.get_text("ignore_namespace"))

        # 更新文本标签
        cmds.text(self.ui_controls.get('saved_data_label'),
                  e=True, label=self.get_text("saved_data_label"))
        cmds.text(self.ui_controls.get('list_ops_label'),
                  e=True, label=self.get_text("list_ops_label"))
        cmds.text(self.ui_controls.get('main_ops_label'),
                  e=True, label=self.get_text("main_ops_label"))
        cmds.text(self.ui_controls.get('anim_settings_label'),
                  e=True, label=self.get_text("anim_settings_label"))
        cmds.text(self.ui_controls.get('general_settings_label'),
                  e=True, label=self.get_text("general_settings_label"))
        cmds.text(self.ui_controls.get('options_label'),
                  e=True, label=self.get_text("options_label"))
        cmds.text(self.ui_controls.get('transform_control_label'),
                  e=True, label=self.get_text("transform_control_label"))
        cmds.text(self.ui_controls.get('language_label'),
                  e=True, label=self.get_text("language_label"))

        # 更新选项菜单标签
        cmds.optionMenu(self.ui_controls.get('pose_list'),
                        e=True, label=self.get_text("pose_list_label"))
        cmds.optionMenu(self.ui_controls.get('anim_list'),
                        e=True, label=self.get_text("anim_list_label"))

        # 更新按钮标签
        cmds.button(self.ui_controls.get('refresh'),
                    e=True, label=self.get_text("refresh"))
        cmds.button(self.ui_controls.get('delete_sel'),
                    e=True, label=self.get_text("delete_sel"))
        cmds.button(self.ui_controls.get('delete_all'),
                    e=True, label=self.get_text("delete_all"))
        cmds.button(self.ui_controls.get('copy_btn'), e=True,
                    label=self.get_text("copy_frame"))
        cmds.button(self.ui_controls.get('paste_btn'), e=True,
                    label=self.get_text("paste_frame"))
        cmds.button(self.ui_controls.get('lang_btn'), e=True, label=(
            u"中") if self.language == "chinese" else "En")

        # 更新动画设置相关文本
        cmds.radioButtonGrp(self.ui_controls.get('copy_mode_radio'), e=True,
                            labelArray2=[self.get_text("frame_copy"), self.get_text("key_copy")])
        cmds.text(self.ui_controls.get('range_label'),
                  e=True, label=self.get_text("range_label"))
        cmds.text(self.ui_controls.get('to_label'),
                  e=True, label=self.get_text("to_label"))
        cmds.checkBox(self.ui_controls.get('range_mode'), e=True,
                      label=self.get_text("custom_range_label"))

        # 更新通用设置相关文本
        cmds.text(self.ui_controls.get('precision_label'),
                  e=True, label=self.get_text("precision") + ":")
        cmds.text(self.ui_controls.get('times_label'),
                  e=True, label=self.get_text("times") + ":")
        cmds.text(self.ui_controls.get('offset_label'),
                  e=True, label=self.get_text("offset") + ":")

        # 更新选项相关文本
        cmds.checkBox(self.ui_controls.get('local_checkbox'),
                      e=True, label=self.get_text("local_mode"))
        cmds.checkBox(self.ui_controls.get('range_checkbox'),
                      e=True, label=self.get_text("auto_range"))
        cmds.checkBox(self.ui_controls.get('dense_frames_check'), e=True, label=self.get_text("dense_frames_label"),
                      annotation=self.get_text("dense_frames_tooltip"))
        cmds.button(self.ui_controls.get('pseudo_tcb_label'),
                    e=True, label=self.get_text("pseudo_tcb_label"))

        # 刷新列表以更新可能的文本
        self.refresh_list()

    def on_auto_range_changed(self, value):
        """自动帧数范围切换"""
        if value and self.current_mode == 2:
            self.update_frame_range_from_selection()

    def update_frame_range_from_selection(self):
        """从选中的动画项更新帧数范围"""
        if self.current_mode == 2:
            selected_item = self.get_selected_animation()
            if selected_item:
                self.parse_frame_range_from_name(selected_item)

    def get_world_transform_optimized(self, obj_list):
        """优化的批量获取世界变换"""
        transforms = {}

        # 按层级排序，先处理父级
        sorted_objs = self.sort_by_hierarchy(obj_list)

        for obj in sorted_objs:
            if not cmds.objExists(obj):
                continue

            try:
                # 获取世界矩阵
                matrix = cmds.xform(obj, q=True, matrix=True, worldSpace=True)
                transforms[obj] = {
                    'matrix': matrix,
                    'type': 'world'
                }
            except:
                continue

        return transforms

    def sort_by_hierarchy(self, obj_list):
        """按层级排序对象列表，父级在前"""
        sorted_objs = []
        processed = set()

        def add_hierarchy(obj):
            if obj in processed or obj in sorted_objs:
                return

            # 先添加父级
            try:
                parent = cmds.listRelatives(obj, parent=True, path=True)
                if parent and parent[0] in obj_list:
                    add_hierarchy(parent[0])
            except:
                pass

            if obj not in sorted_objs:
                sorted_objs.append(obj)
                processed.add(obj)

        for obj in obj_list:
            add_hierarchy(obj)

        return sorted_objs

    def copy_transforms(self, *args):
        """拷贝变换数据"""
        selection = cmds.ls(selection=True, long=True)
        if not selection:
            cmds.warning(self.get_text("no_selection"))
            return

        try:
            if self.current_mode == 1:
                self.copy_pose_transforms(selection)
            else:
                self.copy_animation_transforms(selection)
        except Exception as e:
            cmds.warning(self.get_text("copy_failed").format(str(e)))

    def copy_pose_transforms(self, selection):
        """拷贝姿态变换 - 修复中文消息显示"""
        current_frame = int(cmds.currentTime(q=True))

        # 获取变换数据
        transform_data = self.get_world_transform_optimized(selection)

        if not transform_data:
            cmds.warning(self.get_text("no_valid_transform"))
            return

        # 生成文件名
        pose_name = "Pose {} ({})".format(
            len(self.pose_list) + 1, current_frame)

        # 检查是否有Ctrl键按下（自定义命名）
        modifiers = cmds.getModifiers()
        if modifiers & 4:  # Ctrl键
            result = cmds.promptDialog(
                title=self.get_text("input_name_title"),
                message=self.get_text("input_name_message"),
                button=[self.get_text("confirm"), self.get_text("cancel")],
                defaultButton=self.get_text("confirm"),
                cancelButton=self.get_text("cancel"),
                dismissString=self.get_text("cancel"),
                text=u'_pose'
            )
            if result == self.get_text("confirm"):
                custom_name = cmds.promptDialog(query=True, text=True)
                pose_name = u"{} {} ({})".format(
                    custom_name, len(self.pose_list) + 1, current_frame)

        # 检查是否有Alt键按下（覆盖模式）
        elif modifiers & 8:  # Alt键
            selected_pose = self.get_selected_pose()
            if selected_pose:
                pose_name = selected_pose
                print(self.get_text("overwrite_mode"))

        # 保存数据
        self.save_pose_data(pose_name, selection, transform_data)

        # 更新列表
        self.refresh_list()

        cmds.warning(self.get_text("recorded_pose").format(
            len(transform_data), pose_name))

    def copy_animation_transforms(self, selection):
        """拷贝动画变换"""
        # 获取帧数范围
        range_mode = cmds.checkBox(
            self.ui_controls['range_mode'], q=True, value=True)
        if range_mode:
            start_frame = cmds.intField(
                self.ui_controls['start_frame'], q=True, value=True)
            end_frame = cmds.intField(
                self.ui_controls['end_frame'], q=True, value=True)
        else:
            start_frame = int(cmds.playbackOptions(q=True, minTime=True))
            end_frame = int(cmds.playbackOptions(q=True, maxTime=True))

        if start_frame >= end_frame:
            cmds.warning(self.get_text("time_range_error"))
            return

        # 获取拷贝模式
        copy_mode_index = cmds.radioButtonGrp(
            self.ui_controls['copy_mode_radio'], q=True, select=True)
        copy_mode = "S" if copy_mode_index == 1 else "K"

        # 生成文件名
        anim_name = "Animation {}-{} ({}-{})".format(
            len(self.anim_list) + 1, copy_mode, start_frame, end_frame)

        # 记录动画数据
        if copy_mode == "S":
            # 逐帧模式
            anim_data = self.record_frame_by_frame(
                selection, start_frame, end_frame)
        else:
            # 关键帧模式
            anim_data = self.record_keyframes_only(
                selection, start_frame, end_frame)

        if not anim_data:
            cmds.warning(self.get_text("no_valid_anim"))
            return

        # 保存数据
        self.save_animation_data(anim_name, selection,
                                 anim_data, start_frame, end_frame, copy_mode)

        # 更新列表
        self.refresh_list()

        cmds.warning(self.get_text("recorded_anim").format(
            len(selection), start_frame, end_frame))

    def record_frame_by_frame(self, selection, start_frame, end_frame):
        """逐帧记录模式"""
        original_time = cmds.currentTime(q=True)
        anim_data = {}

        try:
            cmds.refresh(suspend=True)
            total_frames = end_frame - start_frame + 1

            for i, frame in enumerate(range(start_frame, end_frame + 1)):
                cmds.currentTime(frame)

                # 更新进度条
                progress = (float(i) / total_frames) * 100
                cmds.progressBar(
                    self.ui_controls['progress_bar'], e=True, progress=progress)

                # 获取当前帧的变换数据
                frame_transforms = self.get_world_transform_optimized(
                    selection)
                if frame_transforms:
                    anim_data[frame] = frame_transforms

        finally:
            cmds.currentTime(original_time)
            cmds.refresh(suspend=False)
            cmds.progressBar(
                self.ui_controls['progress_bar'], e=True, progress=0)

        return anim_data

    def record_keyframes_only(self, selection, start_frame, end_frame):
        """关键帧记录模式"""
        original_time = cmds.currentTime(q=True)
        anim_data = {}
        keyframes = set()

        # 收集所有关键帧
        for obj in selection:
            if not cmds.objExists(obj):
                continue
            try:
                obj_keyframes = cmds.keyframe(obj, q=True, timeChange=True)
                if obj_keyframes:
                    for kf in obj_keyframes:
                        if start_frame <= kf <= end_frame:
                            keyframes.add(int(kf))
            except:
                continue

        if not keyframes:
            # 如果没有关键帧，至少记录起始和结束帧
            keyframes = {start_frame, end_frame}

        keyframes = sorted(list(keyframes))

        try:
            cmds.refresh(suspend=True)
            total_frames = len(keyframes)

            for i, frame in enumerate(keyframes):
                cmds.currentTime(frame)

                # 更新进度条
                progress = (float(i) / total_frames) * 100
                cmds.progressBar(
                    self.ui_controls['progress_bar'], e=True, progress=progress)

                # 获取当前帧的变换数据
                frame_transforms = self.get_world_transform_optimized(
                    selection)
                if frame_transforms:
                    anim_data[frame] = frame_transforms

        finally:
            cmds.currentTime(original_time)
            cmds.refresh(suspend=False)
            cmds.progressBar(
                self.ui_controls['progress_bar'], e=True, progress=0)

        return anim_data

    def paste_transforms(self, *args):
        """粘贴变换数据"""
        try:
            if self.current_mode == 1:
                self.paste_pose_transforms()
            else:
                self.paste_animation_transforms()
        except Exception as e:
            cmds.warning(self.get_text("paste_failed").format(str(e)))

    def paste_pose_transforms(self):
        """粘贴姿态变换"""
        selected_pose = self.get_selected_pose()
        if not selected_pose:
            cmds.warning(self.get_text("select_pose"))
            return

        # 加载姿态数据
        pose_data = self.load_pose_data(selected_pose)
        if not pose_data:
            cmds.warning(self.get_text("load_pose_failed"))
            return

        selection = cmds.ls(selection=True, long=True)
        if not selection:
            cmds.warning(self.get_text("select_objects"))
            return

        # 获取粘贴次数
        paste_times = cmds.intField(
            self.ui_controls['paste_times'], q=True, value=True)
        precision = cmds.intField(
            self.ui_controls['precision'], q=True, value=True)

        # 执行多次粘贴
        for paste_round in range(paste_times):
            for precision_round in range(precision):
                self.apply_pose_transforms(selection, pose_data['transforms'])

        cmds.warning(self.get_text("pasted_pose").format(
            len(selection), paste_times))

        # 刷新列表
        self.refresh_list()

    def paste_animation_transforms(self):
        """粘贴动画变换"""
        selected_anim = self.get_selected_animation()
        if not selected_anim:
            cmds.warning(self.get_text("select_animation"))
            return

        # 加载动画数据
        anim_data = self.load_animation_data(selected_anim)
        if not anim_data:
            cmds.warning(self.get_text("load_anim_failed"))
            return

        selection = cmds.ls(selection=True, long=True)
        if not selection:
            cmds.warning(self.get_text("select_objects"))
            return

        # 获取偏移和粘贴次数
        offset = cmds.intField(
            self.ui_controls['offset_field'], q=True, value=True)
        paste_times = cmds.intField(
            self.ui_controls['paste_times'], q=True, value=True)
        precision = cmds.intField(
            self.ui_controls['precision'], q=True, value=True)

        # 执行多次粘贴
        for paste_round in range(paste_times):
            for precision_round in range(precision):
                self.apply_animation_transforms(selection, anim_data, offset)

        frame_count = len(anim_data.get('frames', {}))
        cmds.warning(self.get_text("pasted_anim").format(
            len(selection), frame_count, paste_times))

        # 刷新列表
        self.refresh_list()

    def apply_pose_transforms(self, selection, transform_data):
        """应用姿态变换到选中物体"""
        # 按层级排序，先处理父级
        sorted_selection = self.sort_by_hierarchy(selection)

        for obj in sorted_selection:
            if not cmds.objExists(obj):
                continue

            # 查找匹配的变换数据
            obj_short_name = obj.split('|')[-1]  # 获取短名称
            if self.ignore_namespace:
                obj_base_name = self.get_base_name(obj)
            else:
                obj_base_name = obj_short_name
            transform = None

            # 尝试多种匹配方式
            for stored_obj, stored_transform in transform_data.items():
                stored_short_name = stored_obj.split('|')[-1]
                if self.ignore_namespace:
                    stored_base_name = self.get_base_name(stored_obj)
                else:
                    stored_base_name = stored_short_name

                if (obj == stored_obj or
                    obj_short_name == stored_obj or
                    obj_short_name == stored_short_name or
                        (self.ignore_namespace and obj_base_name == stored_base_name)):
                    transform = stored_transform
                    break

            if not transform:
                continue

            try:
                # 应用世界矩阵变换
                if 'matrix' in transform:
                    cmds.xform(
                        obj, matrix=transform['matrix'], worldSpace=True)
                else:
                    # 兼容旧格式
                    if 'translation' in transform:
                        cmds.xform(
                            obj, translation=transform['translation'], worldSpace=True)
                    if 'rotation' in transform:
                        cmds.xform(
                            obj, rotation=transform['rotation'], worldSpace=True)
                    if 'scale' in transform:
                        cmds.xform(
                            obj, scale=transform['scale'], worldSpace=True)

                # 设置关键帧
                cmds.setKeyframe(
                    obj, attribute=['translate', 'rotate', 'scale'])

            except Exception as e:
                print(((u"应用变换到 {} 失败: {}").format(obj, str(e))))
                continue

    def apply_animation_transforms(self, selection, anim_data, offset=0):
        """应用动画变换到选中物体"""
        original_time = cmds.currentTime(q=True)
        frames_data = anim_data.get('frames', {})

        if not frames_data:
            cmds.warning(self.get_text("no_valid_frames"))
            return

        try:
            cmds.refresh(suspend=True)

            # 按层级排序选择的物体
            sorted_selection = self.sort_by_hierarchy(selection)

            total_frames = len(frames_data)
            processed_frames = 0

            for source_frame, frame_transforms in frames_data.items():
                target_frame = int(source_frame) + offset
                cmds.currentTime(target_frame)

                # 更新进度条
                progress = (float(processed_frames) / total_frames) * 100
                cmds.progressBar(
                    self.ui_controls['progress_bar'], e=True, progress=progress)

                # 应用每个物体的变换
                for obj in sorted_selection:
                    if not cmds.objExists(obj):
                        continue

                    # 查找匹配的变换数据
                    obj_short_name = obj.split('|')[-1]
                    if self.ignore_namespace:
                        obj_base_name = self.get_base_name(obj)
                    else:
                        obj_base_name = obj_short_name
                    transform = None

                    for stored_obj, stored_transform in frame_transforms.items():
                        stored_short_name = stored_obj.split('|')[-1]
                        if self.ignore_namespace:
                            stored_base_name = self.get_base_name(stored_obj)
                        else:
                            stored_base_name = stored_short_name

                        if (obj == stored_obj or
                            obj_short_name == stored_obj or
                            obj_short_name == stored_short_name or
                                (self.ignore_namespace and obj_base_name == stored_base_name)):
                            transform = stored_transform
                            break

                    if not transform:
                        continue

                    try:
                        # 应用变换
                        if 'matrix' in transform:
                            cmds.xform(
                                obj, matrix=transform['matrix'], worldSpace=True)

                        # 设置关键帧
                        cmds.setKeyframe(
                            obj, attribute=['translate', 'rotate', 'scale'])

                    except Exception as e:
                        print(((u"应用动画变换到 {} 帧 {} 失败: {}").format(
                            obj, target_frame, str(e))))
                        continue

                processed_frames += 1

        finally:
            cmds.currentTime(original_time)
            cmds.refresh(suspend=False)
            cmds.progressBar(
                self.ui_controls['progress_bar'], e=True, progress=0)

    def save_pose_data(self, pose_name, selection, transform_data):
        """保存姿态数据到文件"""
        # 确定保存目录 (pose子目录)
        if cmds.checkBox(self.ui_controls['local_checkbox'], q=True, value=True):
            save_dir = os.path.join(self.data_dir, "localMode", "pose")
        else:
            save_dir = os.path.join(self.data_dir, "pose")

        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        file_path = os.path.join(save_dir, "{}.json".format(pose_name))

        # 准备保存的数据
        save_data = {
            'type': 'pose',
            'version': '2.0',
            # 保存基本名称或短名称
            'objects': [self.get_base_name(obj) for obj in selection] if self.ignore_namespace else [obj.split('|')[-1] for obj in selection],
            'transforms': {}
        }

        # 转换数据格式以便保存
        for obj, transform in transform_data.items():
            if self.ignore_namespace:
                obj_save_name = self.get_base_name(obj)
            else:
                obj_save_name = obj.split('|')[-1]
            save_data['transforms'][obj_save_name] = transform

        # 保存到文件
        try:
            with open(file_path, 'w') as f:
                json.dump(save_data, f, indent=2)
        except Exception as e:
            cmds.warning(self.get_text("save_failed").format(str(e)))

    def save_animation_data(self, anim_name, selection, anim_data, start_frame, end_frame, copy_mode):
        """保存动画数据到文件"""
        # 确定保存目录 (animation子目录)
        if cmds.checkBox(self.ui_controls['local_checkbox'], q=True, value=True):
            save_dir = os.path.join(self.data_dir, "localMode", "animation")
        else:
            save_dir = os.path.join(self.data_dir, "animation")

        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        file_path = os.path.join(save_dir, "{}.json".format(anim_name))

        # 准备保存的数据
        save_data = {
            'type': 'animation',
            'version': '2.0',
            'copy_mode': copy_mode,
            'start_frame': start_frame,
            'end_frame': end_frame,
            'objects': [self.get_base_name(obj) for obj in selection] if self.ignore_namespace else [obj.split('|')[-1] for obj in selection],
            'frames': {}
        }

        # 转换帧数据格式
        for frame, frame_transforms in anim_data.items():
            frame_data = {}
            for obj, transform in frame_transforms.items():
                if self.ignore_namespace:
                    obj_save_name = self.get_base_name(obj)
                else:
                    obj_save_name = obj.split('|')[-1]
                frame_data[obj_save_name] = transform
            save_data['frames'][str(frame)] = frame_data

        # 保存到文件
        try:
            with open(file_path, 'w') as f:
                json.dump(save_data, f, indent=2)
        except Exception as e:
            cmds.warning(self.get_text("save_failed").format(str(e)))

    def load_pose_data(self, pose_name):
        """加载姿态数据"""
        # 确定加载目录 (pose子目录)
        if cmds.checkBox(self.ui_controls['local_checkbox'], q=True, value=True):
            load_dir = os.path.join(self.data_dir, "localMode", "pose")
        else:
            load_dir = os.path.join(self.data_dir, "pose")

        file_path = os.path.join(load_dir, "{}.json".format(pose_name))

        if not os.path.exists(file_path):
            return None

        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(self.get_text("load_failed").format(str(e)))
            return None

    def load_animation_data(self, anim_name):
        """加载动画数据"""
        # 确定加载目录 (animation子目录)
        if cmds.checkBox(self.ui_controls['local_checkbox'], q=True, value=True):
            load_dir = os.path.join(self.data_dir, "localMode", "animation")
        else:
            load_dir = os.path.join(self.data_dir, "animation")

        file_path = os.path.join(load_dir, "{}.json".format(anim_name))

        if not os.path.exists(file_path):
            return None

        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(self.get_text("load_failed").format(str(e)))
            return None

    def refresh_list(self, *args):
        """刷新列表 - 修复UI闪退问题"""
        # 确保UI控件存在
        if not hasattr(self, 'ui_controls') or not self.ui_controls:
            return

        # 确定目录
        try:
            if 'local_checkbox' in self.ui_controls and cmds.checkBox(self.ui_controls['local_checkbox'], exists=True):
                is_local = cmds.checkBox(
                    self.ui_controls['local_checkbox'], q=True, value=True)
            else:
                is_local = False
        except:
            is_local = False

        if is_local:
            data_dir = os.path.join(self.data_dir, "localMode")
        else:
            data_dir = self.data_dir

        if not os.path.exists(data_dir):
            try:
                os.makedirs(data_dir)
            except Exception as e:
                print("Failed to create directory: {}".format(str(e)))
                return

        # 清除现有列表项
        # 姿态列表
        if 'pose_list' in self.ui_controls and cmds.optionMenu(self.ui_controls['pose_list'], exists=True):
            try:
                # 使用更可靠的方式清除所有项
                cmds.optionMenu(
                    self.ui_controls['pose_list'], e=True, deleteAllItems=True)
            except Exception as e:
                print("Error clearing pose list: {}".format(str(e)))

        # 动画列表
        if 'anim_list' in self.ui_controls and cmds.optionMenu(self.ui_controls['anim_list'], exists=True):
            try:
                # 使用更可靠的方式清除所有项
                cmds.optionMenu(
                    self.ui_controls['anim_list'], e=True, deleteAllItems=True)
            except Exception as e:
                print("Error clearing anim list: {}".format(str(e)))

        # 加载姿态文件 (从pose子目录)
        self.pose_list = []
        pose_files = []
        try:
            pose_dir = os.path.join(data_dir, "pose")
            if os.path.exists(pose_dir):
                for file_name in os.listdir(pose_dir):
                    if file_name.startswith('Pose') and file_name.endswith('.json'):
                        pose_name = file_name[:-5]  # 移除.json扩展名
                        pose_files.append(pose_name)
        except Exception as e:
            print("Error loading pose files: {}".format(str(e)))

        # 自然排序
        try:
            pose_files.sort(key=self.natural_sort_key)
        except:
            pass

        # 添加姿态项
        if 'pose_list' in self.ui_controls and cmds.optionMenu(self.ui_controls['pose_list'], exists=True):
            for pose_name in pose_files:
                try:
                    cmds.menuItem(label=pose_name,
                                  parent=self.ui_controls['pose_list'])
                    self.pose_list.append(pose_name)
                except:
                    continue

        # 加载动画文件 (从animation子目录)
        self.anim_list = []
        anim_files = []
        try:
            anim_dir = os.path.join(data_dir, "animation")
            if os.path.exists(anim_dir):
                for file_name in os.listdir(anim_dir):
                    if file_name.startswith('Animation') and file_name.endswith('.json'):
                        anim_name = file_name[:-5]  # 移除.json扩展名
                        anim_files.append(anim_name)
        except Exception as e:
            print("Error loading anim files: {}".format(str(e)))

        # 自然排序
        anim_files.sort(key=self.natural_sort_key)

        for anim_name in anim_files:
            cmds.menuItem(label=anim_name,
                          parent=self.ui_controls['anim_list'])
            self.anim_list.append(anim_name)

        # 选择最后一个项目
        if self.current_mode == 1 and self.pose_list:
            cmds.optionMenu(
                self.ui_controls['pose_list'], e=True, select=len(self.pose_list))
        elif self.current_mode == 2 and self.anim_list:
            cmds.optionMenu(
                self.ui_controls['anim_list'], e=True, select=len(self.anim_list))

    def natural_sort_key(self, text):
        """自然排序的键函数"""
        import re
        return [int(c) if c.isdigit() else c.lower() for c in re.split('([0-9]+)', text)]

    def get_selected_pose(self):
        """获取当前选中的姿态"""
        try:
            return cmds.optionMenu(self.ui_controls['pose_list'], q=True, value=True)
        except:
            return None

    def get_selected_animation(self):
        """获取当前选中的动画"""
        try:
            return cmds.optionMenu(self.ui_controls['anim_list'], q=True, value=True)
        except:
            return None

    def on_pose_selection_changed(self, *args):
        """姿态选择变化回调"""
        selected_pose = self.get_selected_pose()
        if selected_pose:
            # 加载并选择关联的物体
            pose_data = self.load_pose_data(selected_pose)
            if pose_data and 'objects' in pose_data:
                objects_to_select = []
                for obj_name in pose_data['objects']:
                    # 尝试找到场景中的对象
                    try:
                        if self.ignore_namespace:
                            # 忽略命名空间，查找所有匹配基本名称的对象
                            all_objects = cmds.ls(long=True)
                            for obj in all_objects:
                                if self.get_base_name(obj) == obj_name:
                                    objects_to_select.append(obj)
                        else:
                            # 使用传统方式查找
                            scene_objs = cmds.ls(obj_name, long=True)
                            if scene_objs:
                                objects_to_select.extend(scene_objs)
                    except:
                        continue

                if objects_to_select:
                    cmds.select(objects_to_select, replace=True)
                else:
                    cmds.warning(self.get_text("no_objects_in_scene"))

    def on_anim_selection_changed(self, *args):
        """动画选择变化回调"""
        selected_anim = self.get_selected_animation()
        if selected_anim:
            # 加载并选择关联的物体
            anim_data = self.load_animation_data(selected_anim)
            if anim_data and 'objects' in anim_data:
                objects_to_select = []
                for obj_name in anim_data['objects']:
                    # 尝试找到场景中的对象
                    try:
                        if self.ignore_namespace:
                            # 忽略命名空间，查找所有匹配基本名称的对象
                            all_objects = cmds.ls(long=True)
                            for obj in all_objects:
                                if self.get_base_name(obj) == obj_name:
                                    objects_to_select.append(obj)
                        else:
                            # 使用传统方式查找
                            scene_objs = cmds.ls(obj_name, long=True)
                            if scene_objs:
                                objects_to_select.extend(scene_objs)
                    except:
                        continue

                if objects_to_select:
                    cmds.select(objects_to_select, replace=True)
                else:
                    cmds.warning(self.get_text("no_anim_objects_in_scene"))

            # 更新帧数范围（如果启用了自动帧数范围）
            if cmds.checkBox(self.ui_controls['range_checkbox'], q=True, value=True):
                self.parse_frame_range_from_name(selected_anim)

    def parse_frame_range_from_name(self, anim_name):
        """从动画名称解析帧数范围"""
        import re
        # 查找类似 (1-100) 的模式
        pattern = r'\((\d+)-(\d+)\)'
        match = re.search(pattern, anim_name)
        if match:
            start_frame = int(match.group(1))
            end_frame = int(match.group(2))
            cmds.intField(
                self.ui_controls['start_frame'], e=True, value=start_frame)
            cmds.intField(
                self.ui_controls['end_frame'], e=True, value=end_frame)

    def delete_selection(self, *args):
        """删除选中的项目"""
        if self.current_mode == 1:
            self.delete_selected_pose()
        else:
            self.delete_selected_animation()

    def delete_all_files(self, *args):
        """删除所有文件"""
        # 确定基础目录
        if cmds.checkBox(self.ui_controls['local_checkbox'], q=True, value=True):
            base_dir = os.path.join(self.data_dir, "localMode")
        else:
            base_dir = self.data_dir

        if not os.path.exists(base_dir):
            return

        # 删除pose和animation子目录中的所有.json文件
        for sub_dir in ["pose", "animation"]:
            try:
                target_dir = os.path.join(base_dir, sub_dir)
                if os.path.exists(target_dir):
                    for file_name in os.listdir(target_dir):
                        if file_name.endswith('.json'):
                            try:
                                os.remove(os.path.join(target_dir, file_name))
                            except:
                                pass
            except:
                pass

        self.refresh_list()
        cmds.warning(self.get_text("delete_all_files"))

    def delete_selected_pose(self):
        """删除选中的姿态"""
        selected_pose = self.get_selected_pose()
        if not selected_pose:
            cmds.warning(self.get_text("select_to_delete"))
            return

        # 确定目录 (pose子目录)
        if cmds.checkBox(self.ui_controls['local_checkbox'], q=True, value=True):
            data_dir = os.path.join(self.data_dir, "localMode", "pose")
        else:
            data_dir = os.path.join(self.data_dir, "pose")

        file_path = os.path.join(data_dir, "{}.json".format(selected_pose))

        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                self.refresh_list()
                cmds.warning(self.get_text(
                    "deleted_pose").format(selected_pose))
            else:
                cmds.warning(self.get_text("file_not_exist"))
        except Exception as e:
            cmds.warning(self.get_text("delete_failed").format(str(e)))

    def delete_selected_animation(self):
        """删除选中的动画"""
        selected_anim = self.get_selected_animation()
        if not selected_anim:
            cmds.warning(self.get_text("select_to_delete"))
            return

        # 确定目录 (animation子目录)
        if cmds.checkBox(self.ui_controls['local_checkbox'], q=True, value=True):
            data_dir = os.path.join(self.data_dir, "localMode", "animation")
        else:
            data_dir = os.path.join(self.data_dir, "animation")

        file_path = os.path.join(data_dir, "{}.json".format(selected_anim))

        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                self.refresh_list()
                cmds.warning(self.get_text(
                    "deleted_anim").format(selected_anim))
            else:
                cmds.warning(self.get_text("file_not_exist"))
        except Exception as e:
            cmds.warning(self.get_text("delete_failed").format(str(e)))

    def reset_transforms(self, *args):
        """重置变换"""
        selection = cmds.ls(selection=True)
        if not selection:
            cmds.warning(self.get_text("select_objects_first"))
            return

        for obj in selection:
            try:
                # 重置变换属性
                attrs = ['translateX', 'translateY', 'translateZ',
                         'rotateX', 'rotateY', 'rotateZ']
                for attr in attrs:
                    if cmds.getAttr("{}.{}".format(obj, attr), settable=True):
                        cmds.setAttr("{}.{}".format(obj, attr), 0)

                scale_attrs = ['scaleX', 'scaleY', 'scaleZ']
                for attr in scale_attrs:
                    if cmds.getAttr("{}.{}".format(obj, attr), settable=True):
                        cmds.setAttr("{}.{}".format(obj, attr), 1)
            except:
                continue

        cmds.warning(self.get_text("reset_transforms").format(len(selection)))

    def apply_euler_filter(self, *args):
        """应用Euler过滤器"""
        selection = cmds.ls(selection=True, type=['transform', 'joint'])
        if not selection:
            cmds.warning(self.get_text("select_rotation_objects"))
            return

        processed_count = 0

        for obj in selection:
            if self.has_rotation_animation(obj):
                print(((u"对 {} 应用Euler过滤器...").format(obj)))
                try:
                    cmds.select(obj)
                    mel.eval('filterCurve;')
                    processed_count += 1
                    print(((u"✓ {} Euler过滤器应用完成").format(obj)))
                except Exception as e:
                    print(((u"✗ {} Euler过滤器应用失败: {}").format(obj, str(e))))
            else:
                print(((u"跳过 {} - 没有旋转动画").format(obj)))

        if processed_count > 0:
            cmds.warning(self.get_text(
                "euler_applied").format(processed_count))
        else:
            cmds.warning(self.get_text("no_rotation_anim"))

    def apply_pseudo_tcb(self, *args):
        """应用伪TCB效果（SLERP四元数插值）"""
        selection = cmds.ls(selection=True, type=['transform', 'joint'])
        if not selection:
            cmds.warning(self.get_text("select_rotation_objects"))
            return

        # 获取满帧开关状态
        dense_frames = cmds.checkBox(
            self.ui_controls['dense_frames_check'], q=True, value=True)

        processed_count = 0

        for obj in selection:
            if self.has_rotation_animation(obj):
                print(((u"对 {} 应用伪TCB效果 (SLERP插值)...").format(obj)))
                if self.apply_slerp_quaternion_interpolation(obj, dense_frames):
                    processed_count += 1
                    print(((u"✓ {} 伪TCB效果应用完成").format(obj)))
                else:
                    print(((u"✗ {} 伪TCB效果应用失败").format(obj)))
            else:
                print(((u"跳过 {} - 没有旋转动画").format(obj)))

        if processed_count > 0:
            mode_text = self.get_text(
                "dense_mode") if dense_frames else self.get_text("keyframe_mode")
            cmds.warning(self.get_text("tcb_applied").format(
                processed_count, mode_text))
        else:
            cmds.warning(self.get_text("no_rotation_anim"))

    def has_rotation_animation(self, obj):
        """检查对象是否有旋转动画"""
        for axis in ['X', 'Y', 'Z']:
            if cmds.keyframe("{}.rotate{}".format(obj, axis), q=True, keyframeCount=True):
                return True
        return False

    def apply_slerp_quaternion_interpolation(self, obj, dense_frames=True):
        """应用SLERP四元数插值"""
        try:
            import maya.api.OpenMaya as om
            import math

            # 获取关键帧时间
            keyframe_times = self.get_all_rotation_keyframes(obj)
            if len(keyframe_times) < 2:
                print(((u"对象 {} 的关键帧数量不足").format(obj)))
                return False

            print(((u"开始SLERP四元数插值...")))

            # 收集四元数关键帧
            quat_keyframes = []
            for time in keyframe_times:
                quat = self.get_world_quaternion_at_time(obj, time)
                quat_keyframes.append((time, quat))

            # 确保四元数连续性
            corrected_quats = self.ensure_quaternion_continuity(quat_keyframes)

            # 创建SLERP插值样本
            if dense_frames:
                # 满帧模式：每帧都有样本
                dense_samples = self.create_dense_slerp_interpolation(
                    corrected_quats)
            else:
                # 关键帧模式：仅保留原关键帧
                dense_samples = self.create_keyframe_slerp_interpolation(
                    corrected_quats)

            # 应用到对象
            return self.apply_quaternion_samples_to_object(obj, dense_samples)

        except Exception as e:
            print(((u"SLERP插值失败: {}").format(str(e))))
            return False

    def get_all_rotation_keyframes(self, obj):
        """获取所有旋转关键帧时间"""
        times = []
        for axis in ['X', 'Y', 'Z']:
            axis_times = cmds.keyframe("{}.rotate{}".format(
                obj, axis), q=True, timeChange=True) or []
            times.extend(axis_times)

        unique_times = sorted(list(set(times)))
        return unique_times

    def get_world_quaternion_at_time(self, obj, time):
        """获取指定时间的世界四元数"""
        import maya.api.OpenMaya as om

        current_time = cmds.currentTime(query=True)
        cmds.currentTime(time)

        try:
            world_matrix = cmds.xform(
                obj, query=True, worldSpace=True, matrix=True)
            maya_matrix = om.MMatrix(world_matrix)
            transform_matrix = om.MTransformationMatrix(maya_matrix)
            return transform_matrix.rotation(asQuaternion=True)
        finally:
            cmds.currentTime(current_time)

    def ensure_quaternion_continuity(self, quat_keyframes):
        """确保四元数序列的连续性"""
        import maya.api.OpenMaya as om

        if len(quat_keyframes) < 2:
            return quat_keyframes

        corrected = [quat_keyframes[0]]

        for i in range(1, len(quat_keyframes)):
            time, current_quat = quat_keyframes[i]
            prev_time, prev_quat = corrected[-1]

            # 计算点积判断是否需要反向
            dot_product = (prev_quat.x * current_quat.x +
                           prev_quat.y * current_quat.y +
                           prev_quat.z * current_quat.z +
                           prev_quat.w * current_quat.w)

            if dot_product < 0:
                # 使用反向四元数确保最短路径
                current_quat = om.MQuaternion(-current_quat.x, -current_quat.y,
                                              -current_quat.z, -current_quat.w)

            corrected.append((time, current_quat))

        return corrected

    def create_dense_slerp_interpolation(self, quat_keyframes):
        """创建密集的SLERP插值样本（满帧模式）"""
        if len(quat_keyframes) < 2:
            return quat_keyframes

        dense_samples = []

        # 获取时间范围
        start_time = quat_keyframes[0][0]
        end_time = quat_keyframes[-1][0]

        # 为每一帧创建插值样本
        for frame in range(int(start_time), int(end_time) + 1):
            current_time = float(frame)
            interpolated_quat = self.interpolate_quaternion_at_time(
                quat_keyframes, current_time)
            if interpolated_quat:
                dense_samples.append((current_time, interpolated_quat))

        print(((u"满帧模式: 生成了 {} 个SLERP插值样本").format(len(dense_samples))))
        return dense_samples

    def create_keyframe_slerp_interpolation(self, quat_keyframes):
        """创建关键帧间的SLERP插值样本（仅保留原关键帧）"""
        if len(quat_keyframes) < 2:
            return quat_keyframes

        # 关键帧模式：只保留原有关键帧的时间点，不添加插值帧
        optimized_samples = []

        for i, (time, quat) in enumerate(quat_keyframes):
            # 直接保留原关键帧时间，但使用连续性修正后的四元数
            optimized_samples.append((time, quat))

        print(((u"关键帧模式: 保留了 {} 个原始关键帧时间点").format(len(optimized_samples))))
        return optimized_samples

    def interpolate_quaternion_at_time(self, quat_keyframes, target_time):
        """在指定时间进行四元数插值"""
        # 如果正好在关键帧上
        for time, quat in quat_keyframes:
            if abs(time - target_time) < 0.001:
                return quat

        # 找到包围目标时间的两个关键帧
        for i in range(len(quat_keyframes) - 1):
            time1, quat1 = quat_keyframes[i]
            time2, quat2 = quat_keyframes[i + 1]

            if time1 <= target_time <= time2:
                # 计算插值参数
                t = (target_time - time1) / (time2 - time1)

                # 执行SLERP插值
                interpolated_quat = self.slerp_quaternion(quat1, quat2, t)
                return interpolated_quat

        # 超出范围时返回最近的关键帧
        if target_time < quat_keyframes[0][0]:
            return quat_keyframes[0][1]
        else:
            return quat_keyframes[-1][1]

    def slerp_quaternion(self, q1, q2, t):
        """四元数球形线性插值（SLERP）"""
        import maya.api.OpenMaya as om
        import math

        # 计算点积
        dot = q1.x * q2.x + q1.y * q2.y + q1.z * q2.z + q1.w * q2.w

        # 如果点积为负，使用较短路径
        if dot < 0:
            q2 = om.MQuaternion(-q2.x, -q2.y, -q2.z, -q2.w)
            dot = -dot

        # 如果四元数非常接近，使用线性插值
        if dot > 0.9995:
            result = om.MQuaternion(
                q1.x + t * (q2.x - q1.x),
                q1.y + t * (q2.y - q1.y),
                q1.z + t * (q2.z - q1.z),
                q1.w + t * (q2.w - q1.w)
            )
            return result.normal()

        # 标准SLERP公式
        theta_0 = math.acos(abs(dot))
        theta = theta_0 * t
        sin_theta = math.sin(theta)
        sin_theta_0 = math.sin(theta_0)

        s0 = math.cos(theta) - dot * sin_theta / sin_theta_0
        s1 = sin_theta / sin_theta_0

        return om.MQuaternion(
            s0 * q1.x + s1 * q2.x,
            s0 * q1.y + s1 * q2.y,
            s0 * q1.z + s1 * q2.z,
            s0 * q1.w + s1 * q2.w
        )

    def apply_quaternion_samples_to_object(self, obj, quat_samples):
        """将四元数样本应用到对象"""
        import maya.api.OpenMaya as om
        import math

        try:
            # 删除现有旋转关键帧
            for axis in ['X', 'Y', 'Z']:
                try:
                    cmds.cutKey(
                        obj, attribute="rotate{}".format(axis), clear=True)
                except:
                    pass

            # 转换四元数为连续欧拉角
            euler_samples = self.convert_quaternions_to_continuous_euler(
                quat_samples)

            # 应用关键帧
            for time, (rx, ry, rz) in euler_samples:
                cmds.setKeyframe(obj, attribute="rotateX", time=time, value=rx)
                cmds.setKeyframe(obj, attribute="rotateY", time=time, value=ry)
                cmds.setKeyframe(obj, attribute="rotateZ", time=time, value=rz)

            # 设置切线为线性确保平滑
            for axis in ['X', 'Y', 'Z']:
                try:
                    cmds.keyTangent(obj, attribute="rotate{}".format(axis),
                                    inTangentType='linear', outTangentType='linear')
                except:
                    pass

            print(((u"SLERP插值完成 - 应用了 {} 个关键帧").format(len(euler_samples))))
            return True

        except Exception as e:
            print(((u"应用四元数样本失败: {}").format(str(e))))
            return False

    def convert_quaternions_to_continuous_euler(self, quat_samples):
        """将四元数序列转换为连续的欧拉角序列"""
        import maya.api.OpenMaya as om
        import math

        if not quat_samples:
            return []

        euler_samples = []
        previous_euler = None

        for time, quat in quat_samples:
            # 将四元数转换为欧拉角
            euler_rotation = quat.asEulerRotation()
            current_euler = [
                math.degrees(euler_rotation.x),
                math.degrees(euler_rotation.y),
                math.degrees(euler_rotation.z)
            ]

            # 如果不是第一帧，确保与前一帧的连续性
            if previous_euler is not None:
                current_euler = self.ensure_euler_continuity(
                    previous_euler, current_euler)

            euler_samples.append((time, tuple(current_euler)))
            previous_euler = current_euler

        return euler_samples

    def ensure_euler_continuity(self, prev_euler, current_euler):
        """确保欧拉角的连续性（避免跳跃）"""
        continuous_euler = []

        for i in range(3):
            prev_angle = prev_euler[i]
            curr_angle = current_euler[i]

            # 找到最接近的等效角度
            candidates = [
                curr_angle,
                curr_angle + 360,
                curr_angle - 360
            ]

            # 选择与前一角度差异最小的候选
            best_angle = min(candidates, key=lambda x: abs(x - prev_angle))
            continuous_euler.append(best_angle)

        return continuous_euler


# 全局函数，用于启动工具
def show_cptools_python():
    """显示暴力粘贴工具"""
    try:
        global cptools_instance
        cptools_instance = CPToolsPython()
        cptools_instance.create_ui()
    except Exception as e:
        # 确保错误消息也使用安全的字符串处理
        error_msg = u"启动工具失败: {}".format(str(e))
        cmds.warning(error_msg)
        import traceback
        traceback.print_exc()


def _paste_pose_get_icon_path():
    try:
        this_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(this_dir, 'UI.png')
        if os.path.exists(icon_path):
            return icon_path
    except Exception:
        pass
    return 'commandButton.png'


def paste_pose_install_shelf_button():
    """Install a shelf button that launches this tool UI."""
    try:
        # Resolve current shelf
        shelf_top = ''
        try:
            shelf_top = mel.eval('global string $gShelfTopLevel; $gShelfTopLevel;')
        except Exception:
            shelf_top = ''
        if not shelf_top:
            shelf_top = 'ShelfLayout'
        shelf = cmds.tabLayout(shelf_top, q=True, st=True)
        if not shelf:
            cmds.warning(u"未找到当前工具架")
            return

        # Remove existing Paste Pose buttons on this shelf
        try:
            children = cmds.shelfLayout(shelf, q=True, ca=True) or []
            for c in children:
                if not cmds.control(c, q=True, exists=True):
                    continue
                ann = ''
                try:
                    ann = cmds.shelfButton(c, q=True, annotation=True) or ''
                except Exception:
                    ann = ''
                if ann == 'Paste Pose':
                    try:
                        cmds.deleteUI(c)
                    except Exception:
                        pass
        except Exception:
            pass

        # Build shelf command
        py_path = os.path.abspath(__file__).replace('\\', '/')
        cmd = "import runpy; ns=runpy.run_path(r'%s'); fn=ns.get('show_cptools_python'); fn()" % py_path

        cmds.shelfButton(
            parent=shelf,
            command=cmd,
            sourceType='python',
            image=_paste_pose_get_icon_path(),
            annotation='Paste Pose',
            label='',
        )

        try:
            mel.eval('saveAllShelves "%s"' % shelf_top)
        except Exception:
            pass

        cmds.inViewMessage(amg=u'<hl>Paste Pose</hl> 已安装到工具架', pos='topCenter', fade=True)
    except Exception as e:
        cmds.warning(u"安装到工具架失败: {}".format(str(e)))


def paste_pose_drop_ui():
    """UI shown when the file is dragged & dropped into Maya."""
    win = 'PastePose_DropUI'
    if cmds.window(win, exists=True):
        cmds.deleteUI(win)

    cmds.window(win, title=u'Paste Pose', sizeable=False)
    cmds.columnLayout(adjustableColumn=True, columnAttach=('both', 12), rowSpacing=8)
    cmds.text(label=u'拖入检测到 Paste Pose 脚本', align='left')
    cmds.separator(height=6)
    cmds.rowLayout(numberOfColumns=2, columnWidth2=(140, 140), columnAlign2=('center', 'center'))
    cmds.button(label=u'打开工具', height=32, command=lambda *_: (cmds.deleteUI(win), show_cptools_python()))
    cmds.button(label=u'安装到工具架', height=32, command=lambda *_: (paste_pose_install_shelf_button(), cmds.deleteUI(win)))
    cmds.setParent('..')
    cmds.button(label=u'关闭', height=28, command=lambda *_: cmds.deleteUI(win))
    cmds.showWindow(win)


def onMayaDroppedPythonFile(*args, **kwargs):
    # When users drag-drop this script into Maya, show installer UI.
    paste_pose_drop_ui()


# 启动工具
if __name__ == "__main__":
    show_cptools_python()
