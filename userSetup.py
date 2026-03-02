# -*- coding: utf-8 -*-
"""
早茶奈工具箱自动启动脚本
将此文件复制到 Maya 的 scripts 目录以启用自动启动
"""

def _chanai_toolbox_auto_start():
    """检查设置后自动启动早茶奈工具箱"""
    try:
        import os
        import json
        import sys

        # 获取工具箱路径
        toolbox_dir = os.path.dirname(os.path.abspath(__file__))
        json_dir = os.path.join(toolbox_dir, "json")
        settings_file = os.path.join(json_dir, "settings.json")

        # 默认不自动启动
        auto_start = False

        # 读取设置
        if os.path.exists(settings_file):
            try:
                with open(settings_file, "r") as f:
                    settings = json.load(f)
                    auto_start = settings.get("chanai_tools_auto_start", False)
            except Exception:
                pass

        # 如果启用自动启动
        if auto_start:
            # 确保路径在 sys.path 中
            if toolbox_dir not in sys.path:
                sys.path.insert(0, toolbox_dir)

            # 导入并启动工具箱
            import chanai_toolbox
            chanai_toolbox.main()

            import maya.cmds as cmds
            cmds.warning(u"早茶奈工具箱已自动启动")
    except Exception as e:
        import maya.cmds as cmds
        cmds.warning(u"早茶奈工具箱自动启动失败: " + str(e))

# 延迟启动，确保 Maya 完全加载
import maya.cmds as cmds
cmds.evalDeferred("_chanai_toolbox_auto_start()")

