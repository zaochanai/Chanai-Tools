"""
AttributeHolderTool.py
功能: 为 Maya 选择的物体批量添加自定义属性，支持动态 UI 生成和属性变化触发代码
作者: x8
使用: 在 Maya Script Editor 中运行:
    import attribute_holder_tool
    attribute_holder_tool.show()
"""

import maya.cmds as cmds
import maya.mel as mel
from functools import partial

# Qt imports
try:
    from PySide2 import QtWidgets, QtCore, QtGui
    from PySide2.QtCore import Qt
    QT_AVAILABLE = True
except ImportError:
    try:
        from PySide6 import QtWidgets, QtCore, QtGui
        from PySide6.QtCore import Qt
        QT_AVAILABLE = True
    except ImportError:
        QT_AVAILABLE = False

class AttributeHolderTool:

    WINDOW_NAME = "AttributeHolderToolWindow"
    WINDOW_TITLE = "Attribute Holder 工具"

    # 支持的控件类型及其对应的 Maya 属性类型
    CONTROL_TYPES = {
        'floatSlider': {'attrType': 'float', 'hasRange': True},
        'intSlider': {'attrType': 'long', 'hasRange': True},
        'checkBox': {'attrType': 'bool', 'hasRange': False},
        'textField': {'attrType': 'string', 'hasRange': False},
        'floatField': {'attrType': 'float', 'hasRange': False},
        'intField': {'attrType': 'long', 'hasRange': False},
        'colorSlider': {'attrType': 'float3', 'hasRange': False},
        'optionMenu': {'attrType': 'enum', 'hasRange': False},
    }

    def __init__(self):
        self.dynamic_controls = []
        self.attr_definitions = []
        self.attr_check_boxes = []   # [(attrName, checkBoxCtrl), ...]
        self.attr_list_layout = None  # 属性勾选列表的容器 layout
        self.preview_layout   = None  # 属性预览控件的容器 layout

    def show(self):
        """显示工具窗口"""
        if cmds.window(self.WINDOW_NAME, exists=True):
            cmds.deleteUI(self.WINDOW_NAME)

        window = cmds.window(self.WINDOW_NAME, title=self.WINDOW_TITLE,
                             widthHeight=(480, 600), sizeable=True)

        # 外层滚动区，让窗口可以拉伸且内容不被截断
        cmds.scrollLayout(horizontalScrollBarThickness=0,
                          verticalScrollBarThickness=14,
                          childResizable=True)
        main_layout = cmds.columnLayout(adjustableColumn=True, rowSpacing=5)

        # 批量添加区域
        cmds.frameLayout(label="添加属性", collapsable=True, collapse=False, marginWidth=10, marginHeight=10)
        cmds.columnLayout(adjustableColumn=True, rowSpacing=5)
        cmds.button(label="为选择添加属性", height=30, command=self.add_attributes_to_selection,
                   annotation="为当前选择的所有对象添加自定义属性")
        cmds.setParent('..')
        cmds.setParent('..')

        # 删除属性区域（读取 + 勾选 + 删除）
        cmds.frameLayout(label="删除自定义属性", collapsable=True, collapse=False, marginWidth=10, marginHeight=10)
        cmds.columnLayout(adjustableColumn=True, rowSpacing=5)
        cmds.button(label="读取选中物体的自定义属性", height=30,
                   command=self.browse_custom_attributes,
                   annotation="读取当前选中物体上所有用户自定义属性，勾选后可批量删除")
        cmds.separator(height=6, style='in')
        # 勾选列表滚动容器
        cmds.scrollLayout(height=140, childResizable=True)
        self.attr_list_layout = cmds.columnLayout(adjustableColumn=True, rowSpacing=3)
        cmds.setParent('..')  # scrollLayout
        cmds.setParent('..')  # columnLayout
        cmds.separator(height=6, style='in')
        cmds.rowLayout(numberOfColumns=3, columnWidth3=(150, 150, 150), adjustableColumn=2)
        cmds.button(label="全选",   height=26, command=lambda *_: self._set_all_checks(True))
        cmds.button(label="全不选", height=26, command=lambda *_: self._set_all_checks(False))
        cmds.button(label="删除勾选属性", height=26,
                   backgroundColor=(0.7, 0.3, 0.3),
                   command=self.remove_checked_attributes,
                   annotation="从选中物体上删除所有勾选的属性")
        cmds.setParent('..')  # rowLayout
        cmds.setParent('..')  # frameLayout columnLayout
        cmds.setParent('..')  # frameLayout

        # 动态 UI 生成区域
        cmds.frameLayout(label="动态属性定义", collapsable=True, collapse=False, marginWidth=10, marginHeight=10)
        cmds.columnLayout(adjustableColumn=True, rowSpacing=5)

        cmds.text(label="属性定义格式: 控件类型|属性名|显示名|默认值|最小值|最大值", align="left")
        cmds.text(label="示例: floatSlider|scale|全局缩放|1.0|0|10", align="left")

        cmds.rowLayout(numberOfColumns=3, columnWidth3=(100, 240, 120), adjustableColumn=2)
        cmds.text(label="属性组名称:", align="left")
        self.attr_group_name = cmds.textField(text="CustomAttrs", annotation="自定义属性组的名称")
        cmds.button(label="清空定义", height=24, command=self.clear_definitions)
        cmds.setParent('..')

        cmds.text(label="属性定义 (每行一个):", align="left")
        self.attr_definition_field = cmds.scrollField(height=200, wordWrap=False,
                                                      annotation="每行定义一个属性，格式见上方说明")

        cmds.text(label="属性变化触发代码 (Python):", align="left")
        self.callback_code_field = cmds.scrollField(height=120, wordWrap=False,
                                                    annotation="当属性变化时执行的 Python 代码，可用变量: node, attr, value")

        cmds.setParent('..')
        cmds.setParent('..')

        # 快捷控件模板
        cmds.frameLayout(label="快捷控件模板", collapsable=True, collapse=False, marginWidth=10, marginHeight=10)
        cmds.gridLayout(numberOfColumns=3, cellWidthHeight=(150, 30))

        cmds.button(label="Float Slider", command=partial(self.insert_template, "floatSlider|myFloat|浮点数|1.0|0|10"))
        cmds.button(label="Int Slider", command=partial(self.insert_template, "intSlider|myInt|整数|5|0|100"))
        cmds.button(label="CheckBox", command=partial(self.insert_template, "checkBox|myBool|启用|True"))
        cmds.button(label="Text Field", command=partial(self.insert_template, "textField|myText|文本|默认值"))
        cmds.button(label="Float Field", command=partial(self.insert_template, "floatField|myValue|数值|0.0"))
        cmds.button(label="Int Field", command=partial(self.insert_template, "intField|myCount|计数|0"))
        cmds.button(label="Color Slider", command=partial(self.insert_template, "colorSlider|myColor|颜色|1,1,1"))
        cmds.button(label="Option Menu", command=partial(self.insert_template, "optionMenu|myEnum|选项|A:B:C"))

        cmds.setParent('..')
        cmds.setParent('..')

        # 预览和操作按钮
        cmds.frameLayout(label="操作", collapsable=True, collapse=False, marginWidth=10, marginHeight=10)
        cmds.columnLayout(adjustableColumn=True, rowSpacing=5)
        cmds.rowLayout(numberOfColumns=2, columnWidth2=(230, 230), adjustableColumn=1)
        cmds.button(label="预览属性", height=30, command=self.parse_and_preview)
        cmds.button(label="清空预览", height=30, command=self._clear_preview)
        cmds.setParent('..')  # rowLayout
        cmds.separator(height=6, style='in')
        cmds.text(label="属性预览（可交互控件）：", align='left')
        cmds.scrollLayout(height=180, childResizable=True)
        self.preview_layout = cmds.columnLayout(adjustableColumn=True, rowSpacing=6)
        cmds.setParent('..')  # scrollLayout
        cmds.setParent('..')  # frameLayout columnLayout
        cmds.setParent('..')  # frameLayout

        # 日志区域
        cmds.frameLayout(label="日志", collapsable=True, collapse=False, marginWidth=10, marginHeight=10, borderVisible=False)
        cmds.columnLayout(adjustableColumn=True, rowSpacing=4)
        self.log_field = cmds.scrollField(height=100, editable=False, wordWrap=True)
        cmds.text(
            label='<a href="https://space.bilibili.com/101677535?spm_id_from=333.1365.0.0">by：早茶奈</a>',
            hyperlink=True,
            align="left"
        )
        cmds.setParent('..')  # columnLayout
        cmds.setParent('..')  # frameLayout

        cmds.showWindow(window)
        self.log("工具就绪")

    def log(self, message):
        """输出日志"""
        current = cmds.scrollField(self.log_field, query=True, text=True)
        new_text = current + "\n" + message if current else message
        cmds.scrollField(self.log_field, edit=True, text=new_text)
        print(message)

    def insert_template(self, template, *args):
        """插入控件模板"""
        current = cmds.scrollField(self.attr_definition_field, query=True, text=True)
        new_text = current + "\n" + template if current else template
        cmds.scrollField(self.attr_definition_field, edit=True, text=new_text)
        self.log("已插入模板: %s" % template)

    def clear_definitions(self, *args):
        """清空定义"""
        cmds.scrollField(self.attr_definition_field, edit=True, text="")
        cmds.scrollField(self.callback_code_field, edit=True, text="")
        self.attr_definitions = []
        self.log("已清空所有定义")

    def parse_definitions(self):
        """解析属性定义"""
        text = cmds.scrollField(self.attr_definition_field, query=True, text=True)
        lines = [line.strip() for line in text.split('\n') if line.strip()]

        self.attr_definitions = []
        for line in lines:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) < 3:
                self.log("[跳过] 格式错误: %s" % line)
                continue

            control_type = parts[0]
            if control_type not in self.CONTROL_TYPES:
                self.log("[跳过] 不支持的控件类型: %s" % control_type)
                continue

            attr_name = parts[1]
            nice_name = parts[2]
            default_value = parts[3] if len(parts) > 3 else None
            min_value = parts[4] if len(parts) > 4 else None
            max_value = parts[5] if len(parts) > 5 else None

            attr_def = {
                'controlType': control_type,
                'attrName': attr_name,
                'niceName': nice_name,
                'defaultValue': default_value,
                'minValue': min_value,
                'maxValue': max_value,
                'attrType': self.CONTROL_TYPES[control_type]['attrType'],
                'hasRange': self.CONTROL_TYPES[control_type]['hasRange']
            }

            self.attr_definitions.append(attr_def)

        return self.attr_definitions

    def _clear_preview(self):
        """清空预览区域"""
        if self.preview_layout and cmds.layout(self.preview_layout, exists=True):
            children = cmds.layout(self.preview_layout, query=True, childArray=True) or []
            for c in children:
                try:
                    cmds.deleteUI(c)
                except Exception:
                    pass

    def parse_and_preview(self, *args):
        """解析属性定义并在预览区生成可交互控件"""
        defs = self.parse_definitions()
        self._clear_preview()
        if not defs:
            self.log("没有有效的属性定义")
            cmds.text(label="（无属性定义）", parent=self.preview_layout, align='left')
            return

        self.log("\n=== 解析到 %d 个属性，已生成预览控件 ===" % len(defs))

        for d in defs:
            ct   = d['controlType']
            aname = d['attrName']
            nname = d['niceName']
            dval  = d['defaultValue']

            # 每个属性一行：label + 控件
            cmds.rowLayout(
                numberOfColumns=2,
                columnWidth2=(120, 300),
                adjustableColumn=2,
                parent=self.preview_layout
            )
            cmds.text(label="%s  (%s)" % (nname, aname), align='right')

            if ct == 'floatSlider':
                mn = float(d['minValue']) if d['minValue'] else 0.0
                mx = float(d['maxValue']) if d['maxValue'] else 10.0
                dv = float(dval) if dval else 0.0
                cmds.floatSliderGrp(field=True, minValue=mn, maxValue=mx, value=dv,
                                    columnWidth3=(1, 60, 200))

            elif ct == 'intSlider':
                mn = int(d['minValue']) if d['minValue'] else 0
                mx = int(d['maxValue']) if d['maxValue'] else 10
                dv = int(dval) if dval else 0
                cmds.intSliderGrp(field=True, minValue=mn, maxValue=mx, value=dv,
                                  columnWidth3=(1, 60, 200))

            elif ct == 'checkBox':
                dv = dval.lower() in ['true', '1', 'yes'] if dval else False
                cmds.checkBox(label='', value=dv)

            elif ct == 'textField':
                cmds.textField(text=dval or '')

            elif ct == 'floatField':
                dv = float(dval) if dval else 0.0
                cmds.floatField(value=dv)

            elif ct == 'intField':
                dv = int(dval) if dval else 0
                cmds.intField(value=dv)

            elif ct == 'colorSlider':
                try:
                    rgb = [float(v) for v in (dval or '1,1,1').split(',')]
                    r, g, b = rgb[0], rgb[1], rgb[2]
                except Exception:
                    r, g, b = 1.0, 1.0, 1.0
                cmds.colorSliderGrp(rgbValue=(r, g, b), columnWidth3=(1, 60, 200))

            elif ct == 'optionMenu':
                enum_items = (dval or 'A:B:C').split(':')
                om = cmds.optionMenu()
                for item in enum_items:
                    cmds.menuItem(label=item.strip())

            else:
                cmds.text(label="[不支持预览: %s]" % ct)

            cmds.setParent('..')  # rowLayout

    def add_attribute_to_node(self, node, attr_def):
        """为节点添加单个属性"""
        attr_name = attr_def['attrName']
        nice_name = attr_def['niceName']
        attr_type = attr_def['attrType']

        # 检查属性是否已存在
        if cmds.attributeQuery(attr_name, node=node, exists=True):
            self.log("[跳过] %s.%s 已存在" % (node, attr_name))
            return False

        # 添加属性
        try:
            if attr_type == 'bool':
                cmds.addAttr(node, longName=attr_name, niceName=nice_name, attributeType='bool', defaultValue=False)
                if attr_def['defaultValue']:
                    default = attr_def['defaultValue'].lower() in ['true', '1', 'yes']
                    cmds.setAttr("%s.%s" % (node, attr_name), default)

            elif attr_type == 'long':
                min_val = int(attr_def['minValue']) if attr_def['minValue'] else None
                max_val = int(attr_def['maxValue']) if attr_def['maxValue'] else None
                default_val = int(attr_def['defaultValue']) if attr_def['defaultValue'] else 0

                if min_val is not None and max_val is not None:
                    cmds.addAttr(node, longName=attr_name, niceName=nice_name, attributeType='long',
                               minValue=min_val, maxValue=max_val, defaultValue=default_val)
                else:
                    cmds.addAttr(node, longName=attr_name, niceName=nice_name, attributeType='long', defaultValue=default_val)

            elif attr_type == 'float':
                min_val = float(attr_def['minValue']) if attr_def['minValue'] else None
                max_val = float(attr_def['maxValue']) if attr_def['maxValue'] else None
                default_val = float(attr_def['defaultValue']) if attr_def['defaultValue'] else 0.0

                if min_val is not None and max_val is not None:
                    cmds.addAttr(node, longName=attr_name, niceName=nice_name, attributeType='float',
                               minValue=min_val, maxValue=max_val, defaultValue=default_val)
                else:
                    cmds.addAttr(node, longName=attr_name, niceName=nice_name, attributeType='float', defaultValue=default_val)

            elif attr_type == 'string':
                cmds.addAttr(node, longName=attr_name, niceName=nice_name, dataType='string')
                if attr_def['defaultValue']:
                    cmds.setAttr("%s.%s" % (node, attr_name), attr_def['defaultValue'], type='string')

            elif attr_type == 'float3':
                cmds.addAttr(node, longName=attr_name, niceName=nice_name, attributeType='float3', usedAsColor=True)
                cmds.addAttr(node, longName="%sR" % attr_name, attributeType='float', parent=attr_name)
                cmds.addAttr(node, longName="%sG" % attr_name, attributeType='float', parent=attr_name)
                cmds.addAttr(node, longName="%sB" % attr_name, attributeType='float', parent=attr_name)
                if attr_def['defaultValue']:
                    try:
                        rgb = [float(v) for v in attr_def['defaultValue'].split(',')]
                        if len(rgb) == 3:
                            cmds.setAttr("%s.%s" % (node, attr_name), rgb[0], rgb[1], rgb[2], type='float3')
                    except:
                        pass

            elif attr_type == 'enum':
                enum_str = attr_def['defaultValue'] if attr_def['defaultValue'] else "A:B:C"
                cmds.addAttr(node, longName=attr_name, niceName=nice_name, attributeType='enum', enumName=enum_str)

            # 设置属性为可关键帧
            cmds.setAttr("%s.%s" % (node, attr_name), keyable=True)

            return True

        except Exception as e:
            self.log("[错误] 添加属性失败 %s.%s: %s" % (node, attr_name, str(e)))
            return False

    def add_attributes_to_selection(self, *args):
        """为选择的对象添加属性"""
        selection = cmds.ls(selection=True)
        if not selection:
            cmds.warning("请先选择对象")
            self.log("[警告] 没有选择对象")
            return

        defs = self.parse_definitions()
        if not defs:
            self.log("[警告] 没有有效的属性定义")
            return

        group_name = cmds.textField(self.attr_group_name, query=True, text=True)
        callback_code = cmds.scrollField(self.callback_code_field, query=True, text=True)

        total_added = 0
        for node in selection:
            self.log("\n处理对象: %s" % node)
            for attr_def in defs:
                if self.add_attribute_to_node(node, attr_def):
                    total_added += 1

                    # 如果有回调代码，创建 scriptJob
                    if callback_code.strip():
                        self.create_attribute_callback(node, attr_def['attrName'], callback_code)

        self.log("\n=== 完成 ===")
        self.log("处理对象数: %d" % len(selection))
        self.log("添加属性数: %d" % total_added)


    def create_attribute_callback(self, node, attr_name, code):
        """为属性创建变化回调（使用 Maya API MNodeMessage，每次 setAttr 均触发）"""
        try:
            import maya.OpenMaya as om
            import sys

            # 用全局模块字典存回调 id，不依赖 import 模块名
            # 直接找当前已加载的模块对象（无论通过何种方式加载）
            _mod = None
            for _m in sys.modules.values():
                if getattr(_m, 'AttributeHolderTool', None) is AttributeHolderTool:
                    _mod = _m
                    break
            if _mod is None:
                # 找不到就用 builtins 兜底
                try:
                    import builtins as _builtins
                except ImportError:
                    import __builtin__ as _builtins
                _mod = _builtins

            if not hasattr(_mod, '_attr_cb_ids'):
                _mod._attr_cb_ids = {}

            callback_key = "%s.%s" % (node, attr_name)

            # 移除旧回调
            old_id = _mod._attr_cb_ids.get(callback_key)
            if old_id is not None:
                try:
                    om.MMessage.removeCallback(old_id)
                    self.log("[回调] 清除旧 MNodeMessage 回调")
                except Exception:
                    pass

            # 获取 MObject
            sel = om.MSelectionList()
            sel.add(node)
            mobj = om.MObject()
            sel.getDependNode(0, mobj)

            # 获取目标属性名（用 partialName 做过滤）
            dep_fn = om.MFnDependencyNode(mobj)
            target_plug = dep_fn.findPlug(attr_name, False)
            target_name = target_plug.partialName()

            def make_callback(node, attr_name, code, target_name):
                def cb(msg, plug, other_plug, client_data):
                    if not (msg & om.MNodeMessage.kAttributeSet):
                        return
                    if plug.partialName() != target_name:
                        return
                    import maya.cmds as _cmds
                    try:
                        if not _cmds.objExists(node):
                            return
                        value = _cmds.getAttr("%s.%s" % (node, attr_name))
                        print("属性触发: %s.%s = %s" % (node, attr_name, value))
                        exec_globals = {'cmds': _cmds, 'node': node, 'attr': attr_name, 'value': value}
                        exec(code, exec_globals)
                    except Exception as e:
                        print('Callback Error: %s' % e)
                        import traceback
                        traceback.print_exc()
                return cb

            cb_func = make_callback(node, attr_name, code, target_name)
            cb_id = om.MNodeMessage.addAttributeChangedCallback(mobj, cb_func)
            _mod._attr_cb_ids[callback_key] = cb_id

            self.log("[回调] 已为 %s.%s 创建 API 回调（每次 setAttr 均触发）" % (node, attr_name))

        except Exception as e:
            import traceback
            self.log("[错误] 创建回调失败: %s" % str(e))
            self.log(traceback.format_exc())

    def browse_custom_attributes(self, *args):
        """读取选中物体的用户自定义属性，填充勾选列表"""
        selection = cmds.ls(selection=True)
        if not selection:
            cmds.warning("请先选择对象")
            self.log("[警告] 没有选择对象")
            return

        # 收集所有选中物体上的自定义属性（取并集）
        attr_set = set()
        for node in selection:
            user_attrs = cmds.listAttr(node, userDefined=True) or []
            attr_set.update(user_attrs)

        # 清空旧列表
        self._clear_attr_list()

        if not attr_set:
            self.log("[提示] 选中物体上没有自定义属性")
            cmds.text(label="（无自定义属性）", parent=self.attr_list_layout, align='left')
            return

        # 按名称排序后逐个创建 checkBox
        for attr_name in sorted(attr_set):
            # 尝试获取当前值用于显示
            try:
                val = cmds.getAttr("%s.%s" % (selection[0], attr_name))
                hint = "  =  %s" % val
            except Exception:
                hint = ""
            cb = cmds.checkBox(
                label="%s%s" % (attr_name, hint),
                value=False,
                parent=self.attr_list_layout
            )
            self.attr_check_boxes.append((attr_name, cb))

        self.log("[读取] 共找到 %d 个自定义属性：%s" % (len(attr_set), ', '.join(sorted(attr_set))))

    def _clear_attr_list(self):
        """清空勾选列表"""
        if self.attr_list_layout and cmds.layout(self.attr_list_layout, exists=True):
            children = cmds.layout(self.attr_list_layout, query=True, childArray=True) or []
            for c in children:
                try:
                    cmds.deleteUI(c)
                except Exception:
                    pass
        self.attr_check_boxes = []

    def _set_all_checks(self, state):
        """全选 / 全不选"""
        for _, cb in self.attr_check_boxes:
            try:
                cmds.checkBox(cb, edit=True, value=state)
            except Exception:
                pass

    def remove_checked_attributes(self, *args):
        """删除勾选的属性"""
        selection = cmds.ls(selection=True)
        if not selection:
            cmds.warning("请先选择对象")
            self.log("[警告] 没有选择对象")
            return

        to_delete = []
        for attr_name, cb in self.attr_check_boxes:
            try:
                if cmds.checkBox(cb, query=True, value=True):
                    to_delete.append(attr_name)
            except Exception:
                pass

        if not to_delete:
            self.log("[提示] 没有勾选任何属性")
            return

        total_removed = 0
        for node in selection:
            for attr_name in to_delete:
                if cmds.attributeQuery(attr_name, node=node, exists=True):
                    try:
                        cmds.deleteAttr(node, attribute=attr_name)
                        total_removed += 1
                        self.log("[删除] %s.%s" % (node, attr_name))
                    except Exception as e:
                        self.log("[错误] 删除失败 %s.%s: %s" % (node, attr_name, str(e)))

        self.log("\n=== 删除完成  共删除 %d 个属性 ===" % total_removed)
        # 删完后自动刷新列表
        self.browse_custom_attributes()

    def remove_attributes_from_selection(self, *args):
        """兼容旧调用（实际已由 remove_checked_attributes 取代）"""
        self.remove_checked_attributes()


# 全局实例
_tool_instance = None
_qt_dialog = None

def show():
    """显示工具窗口 - 优先使用Qt版本"""
    if QT_AVAILABLE:
        try:
            return show_qt()
        except Exception as e:
            import traceback
            print("Qt UI failed, falling back to cmds UI:")
            print(traceback.format_exc())
            return show_cmds()
    else:
        return show_cmds()

def show_cmds():
    """显示cmds版本的工具窗口"""
    global _tool_instance
    _tool_instance = AttributeHolderTool()
    _tool_instance.show()

def show_qt():
    """显示Qt版本的工具窗口"""
    global _qt_dialog

    # 关闭旧窗口
    if _qt_dialog is not None:
        try:
            _qt_dialog.close()
            _qt_dialog.deleteLater()
        except:
            pass

    # 获取Maya主窗口
    maya_window = None
    try:
        import maya.OpenMayaUI as omui
        try:
            from shiboken2 import wrapInstance
        except ImportError:
            from shiboken6 import wrapInstance
        ptr = omui.MQtUtil.mainWindow()
        if ptr:
            maya_window = wrapInstance(int(ptr), QtWidgets.QWidget)
    except:
        pass

    _qt_dialog = AttributeHolderDialog(maya_window)
    _qt_dialog.show()
    return _qt_dialog


# ═══════════════════════════════════════════════════════════════
#  Qt UI 实现
# ═══════════════════════════════════════════════════════════════

class AttributeHolderDialog(QtWidgets.QDialog):
    """属性添加器 Qt 对话框 - 暗黑风格"""

    def __init__(self, parent=None):
        super(AttributeHolderDialog, self).__init__(parent)
        self.setWindowTitle("🎨 Attribute Holder")
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.resize(680, 820)

        self.attr_definitions = []
        self.attr_check_boxes = []

        self._setup_ui()
        self._apply_dark_style()
        self.log("工具就绪")

    def _setup_ui(self):
        """构建UI"""
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        # ── 添加属性区域 ──
        add_group = self._create_group("➕ 添加属性")
        add_layout = QtWidgets.QVBoxLayout()
        add_layout.setSpacing(6)

        self.add_btn = QtWidgets.QPushButton("为选择添加属性")
        self.add_btn.setMinimumHeight(36)
        self.add_btn.clicked.connect(self.add_attributes_to_selection)
        add_layout.addWidget(self.add_btn)

        add_group.setLayout(add_layout)
        main_layout.addWidget(add_group)

        # ── 删除属性区域 ──
        del_group = self._create_group("🗑️ 删除自定义属性")
        del_layout = QtWidgets.QVBoxLayout()
        del_layout.setSpacing(6)

        self.browse_btn = QtWidgets.QPushButton("读取选中物体的自定义属性")
        self.browse_btn.setMinimumHeight(36)
        self.browse_btn.clicked.connect(self.browse_custom_attributes)
        del_layout.addWidget(self.browse_btn)

        # 属性列表
        self.attr_list_widget = QtWidgets.QListWidget()
        self.attr_list_widget.setMaximumHeight(140)
        self.attr_list_widget.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        del_layout.addWidget(self.attr_list_widget)

        # 操作按钮
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(6)

        select_all_btn = QtWidgets.QPushButton("全选")
        select_all_btn.clicked.connect(lambda: self.attr_list_widget.selectAll())
        btn_row.addWidget(select_all_btn)

        clear_sel_btn = QtWidgets.QPushButton("全不选")
        clear_sel_btn.clicked.connect(lambda: self.attr_list_widget.clearSelection())
        btn_row.addWidget(clear_sel_btn)

        self.delete_btn = QtWidgets.QPushButton("删除勾选属性")
        self.delete_btn.setObjectName("deleteBtn")
        self.delete_btn.clicked.connect(self.remove_checked_attributes)
        btn_row.addWidget(self.delete_btn)

        del_layout.addLayout(btn_row)
        del_group.setLayout(del_layout)
        main_layout.addWidget(del_group)

        # ── 动态属性定义区域 ──
        def_group = self._create_group("⚙️ 动态属性定义")
        def_layout = QtWidgets.QVBoxLayout()
        def_layout.setSpacing(6)

        # 说明文本
        hint_label = QtWidgets.QLabel(
            "格式: 控件类型|属性名|显示名|默认值|最小值|最大值\n"
            "示例: floatSlider|scale|全局缩放|1.0|0|10"
        )
        hint_label.setStyleSheet("color: #888; font-size: 11px;")
        def_layout.addWidget(hint_label)

        # 属性组名称
        name_row = QtWidgets.QHBoxLayout()
        name_row.addWidget(QtWidgets.QLabel("属性组名称:"))
        self.attr_group_name = QtWidgets.QLineEdit("CustomAttrs")
        name_row.addWidget(self.attr_group_name, 1)
        clear_def_btn = QtWidgets.QPushButton("清空定义")
        clear_def_btn.clicked.connect(self.clear_definitions)
        name_row.addWidget(clear_def_btn)
        def_layout.addLayout(name_row)

        # 属性定义输入
        def_layout.addWidget(QtWidgets.QLabel("属性定义 (每行一个):"))
        self.attr_definition_field = QtWidgets.QPlainTextEdit()
        self.attr_definition_field.setMaximumHeight(160)
        self.attr_definition_field.setPlaceholderText("每行定义一个属性...")
        def_layout.addWidget(self.attr_definition_field)

        # 回调代码
        def_layout.addWidget(QtWidgets.QLabel("属性变化触发代码 (Python):"))
        self.callback_code_field = QtWidgets.QPlainTextEdit()
        self.callback_code_field.setMaximumHeight(100)
        self.callback_code_field.setPlaceholderText("可用变量: node, attr, value")
        def_layout.addWidget(self.callback_code_field)

        def_group.setLayout(def_layout)
        main_layout.addWidget(def_group)

        # ── 快捷模板区域 ──
        template_group = self._create_group("📋 快捷控件模板")
        template_layout = QtWidgets.QGridLayout()
        template_layout.setSpacing(4)

        templates = [
            ("Float Slider", "floatSlider|myFloat|浮点数|1.0|0|10"),
            ("Int Slider", "intSlider|myInt|整数|5|0|100"),
            ("CheckBox", "checkBox|myBool|启用|True"),
            ("Text Field", "textField|myText|文本|默认值"),
            ("Float Field", "floatField|myValue|数值|0.0"),
            ("Int Field", "intField|myCount|计数|0"),
            ("Color Slider", "colorSlider|myColor|颜色|1,1,1"),
            ("Option Menu", "optionMenu|myEnum|选项|A:B:C"),
        ]

        for i, (label, template) in enumerate(templates):
            btn = QtWidgets.QPushButton(label)
            btn.clicked.connect(lambda checked=False, t=template: self.insert_template(t))
            template_layout.addWidget(btn, i // 4, i % 4)

        template_group.setLayout(template_layout)
        main_layout.addWidget(template_group)

        # ── 预览区域 ──
        preview_group = self._create_group("👁️ 属性预览")
        preview_layout = QtWidgets.QVBoxLayout()
        preview_layout.setSpacing(6)

        preview_btn_row = QtWidgets.QHBoxLayout()
        self.preview_btn = QtWidgets.QPushButton("预览属性")
        self.preview_btn.clicked.connect(self.parse_and_preview)
        preview_btn_row.addWidget(self.preview_btn)

        clear_preview_btn = QtWidgets.QPushButton("清空预览")
        clear_preview_btn.clicked.connect(self._clear_preview)
        preview_btn_row.addWidget(clear_preview_btn)
        preview_layout.addLayout(preview_btn_row)

        # 预览滚动区域
        preview_scroll = QtWidgets.QScrollArea()
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setMaximumHeight(180)
        self.preview_widget = QtWidgets.QWidget()
        self.preview_layout = QtWidgets.QVBoxLayout(self.preview_widget)
        self.preview_layout.setContentsMargins(4, 4, 4, 4)
        self.preview_layout.setSpacing(4)
        preview_scroll.setWidget(self.preview_widget)
        preview_layout.addWidget(preview_scroll)

        preview_group.setLayout(preview_layout)
        main_layout.addWidget(preview_group)

        # ── 日志区域 ──
        log_group = self._create_group("📝 日志")
        log_layout = QtWidgets.QVBoxLayout()
        self.log_field = QtWidgets.QPlainTextEdit()
        self.log_field.setReadOnly(True)
        self.log_field.setMaximumHeight(80)
        log_layout.addWidget(self.log_field)

        # 作者信息
        author_label = QtWidgets.QLabel('<a href="https://space.bilibili.com/101677535">by: 早茶奈</a>')
        author_label.setOpenExternalLinks(True)
        author_label.setStyleSheet("color: #4a7fa5;")
        log_layout.addWidget(author_label)

        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)

    def _create_group(self, title):
        """创建分组框"""
        group = QtWidgets.QGroupBox(title)
        return group

    def _apply_dark_style(self):
        """应用暗黑风格"""
        self.setStyleSheet("""
            QDialog {
                background-color: #2a2a32;
                color: #d8d8d8;
            }
            QGroupBox {
                background-color: #2a2a32;
                border: 1px solid #3a3d46;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 8px;
                font-weight: bold;
                font-size: 12px;
                color: #88ccee;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #3a3a44;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: #4a7fa5;
                border-color: #6ab;
            }
            QPushButton:pressed {
                background-color: #2a5f85;
            }
            QPushButton#deleteBtn {
                background-color: #553333;
                border-color: #855;
            }
            QPushButton#deleteBtn:hover {
                background-color: #7a4444;
            }
            QLineEdit, QPlainTextEdit {
                background-color: #1e1e24;
                color: #ddd;
                border: 1px solid #3a3d46;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: 11px;
                selection-background-color: #4a7fa5;
            }
            QLineEdit:focus, QPlainTextEdit:focus {
                border-color: #4a7fa5;
            }
            QListWidget {
                background-color: #1e1e24;
                color: #ddd;
                border: 1px solid #3a3d46;
                border-radius: 3px;
                padding: 2px;
                font-size: 11px;
            }
            QListWidget::item {
                padding: 4px;
                border-radius: 2px;
            }
            QListWidget::item:selected {
                background-color: #4a7fa5;
            }
            QListWidget::item:hover {
                background-color: #3a3a48;
            }
            QScrollArea {
                border: 1px solid #3a3d46;
                border-radius: 3px;
                background-color: #1e1e24;
            }
            QScrollBar:vertical {
                width: 10px;
                background: #1e1e24;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #555566;
                border-radius: 5px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #6a6a7a;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QLabel {
                color: #ccc;
                font-size: 11px;
            }
            QSlider::groove:horizontal {
                background: #2a2a32;
                height: 4px;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #4a7fa5;
                width: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: #1e1e24;
                color: #ddd;
                border: 1px solid #3a3d46;
                border-radius: 3px;
                padding: 2px 4px;
                min-width: 60px;
            }
            QCheckBox {
                color: #ccc;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #555;
                border-radius: 3px;
                background: #2a2a32;
            }
            QCheckBox::indicator:checked {
                background: #4a7fa5;
                border-color: #6ab;
            }
        """)

    def log(self, message):
        """输出日志"""
        self.log_field.appendPlainText(message)
        print(message)

    def insert_template(self, template):
        """插入模板"""
        current = self.attr_definition_field.toPlainText()
        new_text = current + "\n" + template if current else template
        self.attr_definition_field.setPlainText(new_text)
        self.log("已插入模板: %s" % template)

    def clear_definitions(self):
        """清空定义"""
        self.attr_definition_field.clear()
        self.callback_code_field.clear()
        self.attr_definitions = []
        self.log("已清空所有定义")

    def parse_definitions(self):
        """解析属性定义"""
        text = self.attr_definition_field.toPlainText()
        lines = [line.strip() for line in text.split('\n') if line.strip()]

        self.attr_definitions = []
        CONTROL_TYPES = AttributeHolderTool.CONTROL_TYPES

        for line in lines:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) < 3:
                self.log("[跳过] 格式错误: %s" % line)
                continue

            control_type = parts[0]
            if control_type not in CONTROL_TYPES:
                self.log("[跳过] 不支持的控件类型: %s" % control_type)
                continue

            attr_def = {
                'controlType': control_type,
                'attrName': parts[1],
                'niceName': parts[2],
                'defaultValue': parts[3] if len(parts) > 3 else None,
                'minValue': parts[4] if len(parts) > 4 else None,
                'maxValue': parts[5] if len(parts) > 5 else None,
                'attrType': CONTROL_TYPES[control_type]['attrType'],
                'hasRange': CONTROL_TYPES[control_type]['hasRange']
            }
            self.attr_definitions.append(attr_def)

        return self.attr_definitions

    def _clear_preview(self):
        """清空预览"""
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def parse_and_preview(self):
        """解析并预览"""
        defs = self.parse_definitions()
        self._clear_preview()

        if not defs:
            self.log("没有有效的属性定义")
            label = QtWidgets.QLabel("（无属性定义）")
            label.setStyleSheet("color: #888;")
            self.preview_layout.addWidget(label)
            return

        self.log("\n=== 解析到 %d 个属性，已生成预览控件 ===" % len(defs))

        for d in defs:
            ct = d['controlType']
            aname = d['attrName']
            nname = d['niceName']
            dval = d['defaultValue']

            row = QtWidgets.QHBoxLayout()
            row.setSpacing(8)

            label = QtWidgets.QLabel("%s (%s)" % (nname, aname))
            label.setMinimumWidth(150)
            label.setStyleSheet("color: #88ccee;")
            row.addWidget(label)

            if ct == 'floatSlider':
                mn = float(d['minValue']) if d['minValue'] else 0.0
                mx = float(d['maxValue']) if d['maxValue'] else 10.0
                dv = float(dval) if dval else 0.0
                slider = QtWidgets.QSlider(Qt.Horizontal)
                slider.setRange(int(mn * 100), int(mx * 100))
                slider.setValue(int(dv * 100))
                row.addWidget(slider, 1)
                spinbox = QtWidgets.QDoubleSpinBox()
                spinbox.setRange(mn, mx)
                spinbox.setValue(dv)
                spinbox.setSingleStep(0.1)
                row.addWidget(spinbox)
                slider.valueChanged.connect(lambda v, sb=spinbox: sb.setValue(v / 100.0))
                spinbox.valueChanged.connect(lambda v, sl=slider: sl.setValue(int(v * 100)))

            elif ct == 'intSlider':
                mn = int(d['minValue']) if d['minValue'] else 0
                mx = int(d['maxValue']) if d['maxValue'] else 10
                dv = int(dval) if dval else 0
                slider = QtWidgets.QSlider(Qt.Horizontal)
                slider.setRange(mn, mx)
                slider.setValue(dv)
                row.addWidget(slider, 1)
                spinbox = QtWidgets.QSpinBox()
                spinbox.setRange(mn, mx)
                spinbox.setValue(dv)
                row.addWidget(spinbox)
                slider.valueChanged.connect(spinbox.setValue)
                spinbox.valueChanged.connect(slider.setValue)

            elif ct == 'checkBox':
                dv = dval.lower() in ['true', '1', 'yes'] if dval else False
                checkbox = QtWidgets.QCheckBox()
                checkbox.setChecked(dv)
                row.addWidget(checkbox)
                row.addStretch()

            elif ct == 'textField':
                textfield = QtWidgets.QLineEdit(dval or '')
                row.addWidget(textfield, 1)

            elif ct == 'floatField':
                dv = float(dval) if dval else 0.0
                spinbox = QtWidgets.QDoubleSpinBox()
                spinbox.setValue(dv)
                spinbox.setSingleStep(0.1)
                row.addWidget(spinbox)
                row.addStretch()

            elif ct == 'intField':
                dv = int(dval) if dval else 0
                spinbox = QtWidgets.QSpinBox()
                spinbox.setValue(dv)
                row.addWidget(spinbox)
                row.addStretch()

            elif ct == 'colorSlider':
                try:
                    rgb = [float(v) for v in (dval or '1,1,1').split(',')]
                    r, g, b = rgb[0], rgb[1], rgb[2]
                except:
                    r, g, b = 1.0, 1.0, 1.0
                color_btn = QtWidgets.QPushButton()
                color_btn.setFixedSize(60, 24)
                color_btn.setStyleSheet("background-color: rgb(%d, %d, %d);" % (int(r * 255), int(g * 255), int(b * 255)))
                row.addWidget(color_btn)
                row.addStretch()

            elif ct == 'optionMenu':
                enum_items = (dval or 'A:B:C').split(':')
                combo = QtWidgets.QComboBox()
                combo.addItems([item.strip() for item in enum_items])
                row.addWidget(combo, 1)

            self.preview_layout.addLayout(row)

        self.preview_layout.addStretch()

    def add_attributes_to_selection(self):
        """为选择添加属性"""
        selection = cmds.ls(selection=True)
        if not selection:
            cmds.warning("请先选择对象")
            self.log("[警告] 没有选择对象")
            return

        defs = self.parse_definitions()
        if not defs:
            self.log("[警告] 没有有效的属性定义")
            return

        callback_code = self.callback_code_field.toPlainText()
        tool = AttributeHolderTool()

        total_added = 0
        for node in selection:
            self.log("\n处理对象: %s" % node)
            for attr_def in defs:
                if tool.add_attribute_to_node(node, attr_def):
                    total_added += 1
                    if callback_code.strip():
                        tool.create_attribute_callback(node, attr_def['attrName'], callback_code)

        self.log("\n=== 完成 ===")
        self.log("处理对象数: %d" % len(selection))
        self.log("添加属性数: %d" % total_added)

    def browse_custom_attributes(self):
        """读取自定义属性"""
        selection = cmds.ls(selection=True)
        if not selection:
            cmds.warning("请先选择对象")
            self.log("[警告] 没有选择对象")
            return

        attr_set = set()
        for node in selection:
            user_attrs = cmds.listAttr(node, userDefined=True) or []
            attr_set.update(user_attrs)

        self.attr_list_widget.clear()

        if not attr_set:
            self.log("[提示] 选中物体上没有自定义属性")
            return

        for attr_name in sorted(attr_set):
            try:
                val = cmds.getAttr("%s.%s" % (selection[0], attr_name))
                hint = "  =  %s" % val
            except:
                hint = ""
            item = QtWidgets.QListWidgetItem("%s%s" % (attr_name, hint))
            item.setData(Qt.UserRole, attr_name)
            self.attr_list_widget.addItem(item)

        self.log("[读取] 共找到 %d 个自定义属性" % len(attr_set))

    def remove_checked_attributes(self):
        """删除选中的属性"""
        selection = cmds.ls(selection=True)
        if not selection:
            cmds.warning("请先选择对象")
            self.log("[警告] 没有选择对象")
            return

        selected_items = self.attr_list_widget.selectedItems()
        if not selected_items:
            self.log("[提示] 没有选择任何属性")
            return

        to_delete = [item.data(Qt.UserRole) for item in selected_items]

        total_removed = 0
        for node in selection:
            for attr_name in to_delete:
                if cmds.attributeQuery(attr_name, node=node, exists=True):
                    try:
                        cmds.deleteAttr(node, attribute=attr_name)
                        total_removed += 1
                        self.log("[删除] %s.%s" % (node, attr_name))
                    except Exception as e:
                        self.log("[错误] 删除失败 %s.%s: %s" % (node, attr_name, str(e)))

        self.log("\n=== 删除完成  共删除 %d 个属性 ===" % total_removed)
        self.browse_custom_attributes()


# 如果直接运行此脚本
if __name__ == "__main__":
    show()
