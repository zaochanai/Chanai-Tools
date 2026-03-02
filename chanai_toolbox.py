# -*- coding: utf-8 -*-
"""
早茶奈 Maya 工具箱  Chanai_Tools
===================================
- 半透明自绘悬浮图标（鼠标离开 30% 透明，移入完全不透明，带缩放动画）
- 点击弹出/收起深色网格工具面板
- 工具分 Tab 分类，4 列网格，支持图标

使用：
    import sys, importlib
    sys.path.insert(0, r'<Chanai_Tools目录>')
    import chanai_toolbox as ct; importlib.reload(ct); ct.main()
或直接拖入 Maya 视口。
"""

from __future__ import print_function, unicode_literals
import os, sys, traceback, json, webbrowser, shutil
from io import open as _io_open
import datetime

# ── PySide  (Maya 2018=PySide2/Qt5, Maya 2025+=PySide6/Qt6) ──
try:
    from PySide2 import QtWidgets, QtCore, QtGui
    from PySide2.QtCore import Qt, Signal, Property, QPropertyAnimation, QEasingCurve
    _PYSIDE_VER = 2
except ImportError:
    try:
        from PySide6 import QtWidgets, QtCore, QtGui
        from PySide6.QtCore import Qt, Signal, Property, QPropertyAnimation, QEasingCurve
        _PYSIDE_VER = 6
    except ImportError:
        # PySide (Qt4) — Maya 2016 以前极老版本
        from PySide import QtWidgets, QtCore, QtGui  # type: ignore
        from PySide.QtCore import Qt, Signal, Property, QPropertyAnimation, QEasingCurve  # type: ignore
        _PYSIDE_VER = 1

# ── Qt 枚举兼容：PySide6 把枚举值移进了嵌套命名空间 ─────────
# 用 getattr 做软降级，保证 PySide2 / PySide6 都能取到
def _qt(obj, *names):
    """依次试取属性，返回第一个存在的值"""
    for n in names:
        v = obj
        try:
            for part in n.split('.'):
                v = getattr(v, part)
            return v
        except AttributeError:
            pass
    raise AttributeError("Qt compat: none of %s found on %s" % (names, obj))

_AlignCenter   = _qt(Qt, 'AlignCenter')
_AlignHCenter  = _qt(Qt, 'AlignHCenter')
_TextWordWrap  = _qt(Qt, 'TextWordWrap', 'TextFlag.TextWordWrap')
_LeftButton    = _qt(Qt, 'LeftButton',   'MouseButton.LeftButton')
_RightButton   = _qt(Qt, 'RightButton',  'MouseButton.RightButton')
_PointingHand  = _qt(Qt, 'PointingHandCursor', 'CursorShape.PointingHandCursor')
_ScrollOff     = _qt(Qt, 'ScrollBarAlwaysOff', 'ScrollBarPolicy.ScrollBarAlwaysOff')
_WA_Translucent = _qt(Qt, 'WA_TranslucentBackground', 'WidgetAttribute.WA_TranslucentBackground')
_OutCubic      = _qt(QEasingCurve, 'OutCubic', 'Type.OutCubic')
_OutBack       = _qt(QEasingCurve, 'OutBack',  'Type.OutBack')
_KeepAspect    = _qt(Qt, 'KeepAspectRatio', 'AspectRatioMode.KeepAspectRatio')
_SmoothXform   = _qt(Qt, 'SmoothTransformation', 'TransformationMode.SmoothTransformation')
_Tool          = _qt(Qt, 'Tool',                  'WindowType.Tool')
_Frameless     = _qt(Qt, 'FramelessWindowHint',   'WindowType.FramelessWindowHint')
_Antialiasing  = _qt(QtGui.QPainter, 'Antialiasing', 'RenderHint.Antialiasing')


def _global_pos(event):
    """兼容 PySide2 (globalPos) / PySide6 (globalPosition().toPoint())"""
    try:
        return event.globalPosition().toPoint()
    except AttributeError:
        return event.globalPos()


def _screen_geometry():
    """安全获取主屏幕可用区域，兼容所有 Qt 版本"""
    try:
        scr = QtWidgets.QApplication.primaryScreen()
        if scr is not None:
            return scr.availableGeometry()
    except Exception:
        pass
    try:
        return QtWidgets.QApplication.desktop().availableGeometry()
    except Exception:
        pass
    return QtCore.QRect(0, 0, 1920, 1080)


# ── Maya ─────────────────────────────────────────────────────
try:
    import maya.cmds as cmds
    import maya.OpenMayaUI as omui
    def _maya_win():
        ptr = omui.MQtUtil.mainWindow()
        if ptr is None:
            return None
        try:
            from shiboken2 import wrapInstance
        except ImportError:
            try:
                from shiboken6 import wrapInstance
            except ImportError:
                from shiboken import wrapInstance  # type: ignore
        return wrapInstance(int(ptr), QtWidgets.QWidget)
except Exception:
    def _maya_win(): return None

# ── 路径 ──────────────────────────────────────────────────────
_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
_PKG_PARENT_DIR = os.path.dirname(_THIS_DIR)
_X8_TOOLS  = os.path.normpath(
    os.path.join(_PKG_PARENT_DIR, "..", "x8_floating_toolset", "tools"))

# ── 图标路径 ──────────────────────────────────────────────────
_ICONS_DIR = os.path.join(_THIS_DIR, "icons")
_UI_DIR = os.path.join(_THIS_DIR, "UI")
_X8_SHELF  = os.path.join(os.path.dirname(_X8_TOOLS), "icons", "x8_shelf.png")
_CHANAI_ICON = os.path.join(_UI_DIR, "Chanai.png")

# ── JSON配置文件路径 ──────────────────────────────────────────
_JSON_DIR = os.path.join(_THIS_DIR, "json")

# 确保 json 文件夹存在
if not os.path.exists(_JSON_DIR):
    os.makedirs(_JSON_DIR)

def _migrate_json_files():
    """迁移根目录的 JSON 文件到 json 文件夹"""
    json_files = ["custom_tools.json", "removed_tools.json", "settings.json", "tool_order.json"]
    for filename in json_files:
        old_path = os.path.join(_THIS_DIR, filename)
        new_path = os.path.join(_JSON_DIR, filename)
        # 如果根目录有文件，且 json 文件夹中不存在，则迁移
        if os.path.exists(old_path) and not os.path.exists(new_path):
            try:
                import shutil
                shutil.move(old_path, new_path)
                print("[ChanaiTools] 已迁移 %s 到 json 文件夹" % filename)
            except Exception as e:
                print("[ChanaiTools] 迁移 %s 失败: %s" % (filename, e))

# 执行迁移
_migrate_json_files()


def _ico(name):
    """返回 icons/ 下的图标路径，不存在则 None"""
    p = os.path.join(_ICONS_DIR, name)
    return p if os.path.exists(p) else None


# ═══════════════════════════════════════════════════════════════
#  全局设置（持久化到 settings.json）
# ═══════════════════════════════════════════════════════════════

_SETTINGS_FILE = os.path.join(_JSON_DIR, "settings.json")

_DEFAULT_SETTINGS = {
    "font_size":    9,
    "bg_color":     [28, 28, 32],
    "btn_color":    [52, 55, 62],
    "btn_alpha":    255,
    "icon_opacity": 0.5,
    "qt_style":     True,         # Qt 风格（仅影响本工具箱）
    "language":     "CN",        # "CN" / "EN"
    "chanai_tools_auto_start": False,   # 早茶奈工具箱自动启动（默认关闭）
}

def _load_settings():
    s = dict(_DEFAULT_SETTINGS)
    if os.path.exists(_SETTINGS_FILE):
        try:
            with _io_open(_SETTINGS_FILE, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            s.update(d)
        except Exception:
            pass
    return s

def _save_settings(s):
    try:
        with _io_open(_SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(s, fh, ensure_ascii=False, indent=2)
    except Exception:
        print("[ChanaiTools] 保存设置失败")

_SETTINGS = _load_settings()

_AUTOSTART_BLOCK_BEGIN = "# >>> ChanaiToolbox AutoStart >>>"
_AUTOSTART_BLOCK_END   = "# <<< ChanaiToolbox AutoStart <<<"
_SAVE_REMINDER_ENABLED_VAR = "X8_SaveReminderEnabled"
_SAVE_REMINDER_FIRST_MIN_VAR = "X8_SaveReminderFirstMin"
_SAVE_REMINDER_REPEAT_MIN_VAR = "X8_SaveReminderRepeatMin"


def _get_maya_user_setup_path():
    """Return Maya userSetup.py absolute path."""
    scripts_dir = ""
    try:
        import maya.cmds as cmds
        scripts_dir = cmds.internalVar(userScriptDir=True) or ""
    except Exception:
        pass

    if not scripts_dir:
        scripts_dir = os.path.join(os.path.expanduser("~"), "Documents", "maya", "scripts")
    scripts_dir = os.path.normpath(scripts_dir)
    try:
        if not os.path.isdir(scripts_dir):
            os.makedirs(scripts_dir)
    except Exception:
        pass
    return os.path.join(scripts_dir, "userSetup.py")


def _build_autostart_block():
    p = _THIS_DIR.replace("\\", "\\\\")
    return (
        _AUTOSTART_BLOCK_BEGIN + "\n"
        "def _chanai_toolbox_autostart_boot():\n"
        "    try:\n"
        "        import sys, importlib\n"
        "        p = r'" + p + "'\n"
        "        if p not in sys.path:\n"
        "            sys.path.insert(0, p)\n"
        "        import chanai_toolbox as _ct\n"
        "        try:\n"
        "            importlib.reload(_ct)\n"
        "        except Exception:\n"
        "            try:\n"
        "                reload(_ct)\n"
        "            except Exception:\n"
        "                pass\n"
        "        _ct.main()\n"
        "    except Exception:\n"
        "        pass\n"
        "try:\n"
        "    import maya.utils as _mu\n"
        "    _mu.executeDeferred(_chanai_toolbox_autostart_boot)\n"
        "except Exception:\n"
        "    _chanai_toolbox_autostart_boot()\n"
        + _AUTOSTART_BLOCK_END + "\n"
    )


def _strip_autostart_block(text):
    s = str(text or "")
    b = s.find(_AUTOSTART_BLOCK_BEGIN)
    e = s.find(_AUTOSTART_BLOCK_END)
    if b >= 0 and e >= 0 and e > b:
        e2 = e + len(_AUTOSTART_BLOCK_END)
        # eat following newline
        if e2 < len(s) and s[e2:e2 + 1] in ("\n", "\r"):
            e2 += 1
            if e2 < len(s) and s[e2:e2 + 1] == "\n":
                e2 += 1
        s = s[:b] + s[e2:]
    return s


def _set_autostart_usersetup(enabled):
    """Install/remove managed autostart block in Maya userSetup.py."""
    user_setup = _get_maya_user_setup_path()
    txt = ""
    if os.path.exists(user_setup):
        try:
            with _io_open(user_setup, "r", encoding="utf-8") as fh:
                txt = fh.read()
        except Exception:
            try:
                with _io_open(user_setup, "r") as fh:
                    txt = fh.read()
            except Exception:
                txt = ""

    txt = _strip_autostart_block(txt)
    if enabled:
        if txt and (not txt.endswith("\n")):
            txt += "\n"
        txt += _build_autostart_block()

    with _io_open(user_setup, "w", encoding="utf-8") as fh:
        fh.write(txt)
    return user_setup


def _tb_normpath(p):
    try:
        return os.path.normcase(os.path.normpath(p))
    except Exception:
        return p


def _tb_save_reminder_service_file():
    try:
        return os.path.normpath(os.path.join(
            _THIS_DIR, "..", "..", "x8_floating_toolset",
            "tools", "backstage", "script_editor_auto_clear",
            "script_editor_auto_clear.py"
        ))
    except Exception:
        return ""


def _tb_find_loaded_module_by_file(file_path):
    want = _tb_normpath(file_path)
    for m in list(sys.modules.values()):
        if not m:
            continue
        try:
            fp = getattr(m, "__file__", None)
            if not fp:
                continue
            if _tb_normpath(fp) == want:
                return m
        except Exception:
            continue
    return None


def _tb_load_module_from_file(module_name, file_path):
    if sys.version_info[0] >= 3:
        import importlib.util as ilu
        spec = ilu.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError("cannot create spec for module: " + str(module_name))
        mod = ilu.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod
    import imp
    return imp.load_source(module_name, file_path)


def _tb_reload_module(mod):
    try:
        import importlib
        if hasattr(importlib, "reload"):
            return importlib.reload(mod)
    except Exception:
        pass
    try:
        return reload(mod)  # type: ignore  # noqa: F821 (py2 fallback)
    except Exception:
        return mod


def _tb_get_save_reminder_service_module():
    file_path = _tb_save_reminder_service_file()
    if not file_path or (not os.path.exists(file_path)):
        return None

    loaded = _tb_find_loaded_module_by_file(file_path)
    if loaded and hasattr(loaded, "start_save_reminder"):
        return loaded

    module_name = "chanai_tools_service__script_editor_auto_clear"
    if module_name in sys.modules:
        try:
            return _tb_reload_module(sys.modules[module_name])
        except Exception:
            try:
                sys.modules.pop(module_name, None)
            except Exception:
                pass

    try:
        return _tb_load_module_from_file(module_name, file_path)
    except Exception:
        return None


def _tb_get_save_reminder_enabled():
    try:
        import maya.cmds as cmds
        if not cmds.optionVar(exists=_SAVE_REMINDER_ENABLED_VAR):
            cmds.optionVar(intValue=(_SAVE_REMINDER_ENABLED_VAR, 0))
        return bool(int(cmds.optionVar(q=_SAVE_REMINDER_ENABLED_VAR)))
    except Exception:
        return False


def _tb_set_save_reminder_enabled(enabled):
    try:
        import maya.cmds as cmds
        cmds.optionVar(intValue=(_SAVE_REMINDER_ENABLED_VAR, 1 if enabled else 0))
    except Exception:
        pass


def _tb_get_save_reminder_interval_min():
    try:
        import maya.cmds as cmds
        if not cmds.optionVar(exists=_SAVE_REMINDER_FIRST_MIN_VAR):
            cmds.optionVar(intValue=(_SAVE_REMINDER_FIRST_MIN_VAR, 5))
        if not cmds.optionVar(exists=_SAVE_REMINDER_REPEAT_MIN_VAR):
            cmds.optionVar(intValue=(_SAVE_REMINDER_REPEAT_MIN_VAR, 5))
        v = int(cmds.optionVar(q=_SAVE_REMINDER_REPEAT_MIN_VAR))
        return max(1, v)
    except Exception:
        return 5


def _tb_set_save_reminder_interval_min(v):
    try:
        import maya.cmds as cmds
        vv = max(1, int(v))
        cmds.optionVar(intValue=(_SAVE_REMINDER_FIRST_MIN_VAR, vv))
        cmds.optionVar(intValue=(_SAVE_REMINDER_REPEAT_MIN_VAR, vv))
    except Exception:
        pass


def _tb_get_save_reminder_first_min():
    # 兼容旧调用：统一返回“间隔分钟”
    return _tb_get_save_reminder_interval_min()


def _tb_get_save_reminder_repeat_min():
    # 兼容旧调用：统一返回“间隔分钟”
    return _tb_get_save_reminder_interval_min()


def _tb_set_save_reminder_first_min(v):
    # 兼容旧调用：统一写入 first/repeat 为同一值
    _tb_set_save_reminder_interval_min(v)


def _tb_set_save_reminder_repeat_min(v):
    # 兼容旧调用：统一写入 first/repeat 为同一值
    _tb_set_save_reminder_interval_min(v)


def _tb_apply_save_reminder_state(enabled):
    mod = _tb_get_save_reminder_service_module()
    if not mod:
        return False
    try:
        if enabled and hasattr(mod, "start_save_reminder"):
            mod.start_save_reminder()
            return True
        if (not enabled) and hasattr(mod, "stop_save_reminder"):
            mod.stop_save_reminder()
            return True
    except Exception:
        return False
    return False


# Keep Maya userSetup hook in sync with saved setting.
try:
    _set_autostart_usersetup(bool(_SETTINGS.get("chanai_tools_auto_start", False)))
except Exception:
    pass

# Keep save-reminder service in sync with existing X8 optionVar.
try:
    _tb_apply_save_reminder_state(_tb_get_save_reminder_enabled())
except Exception:
    pass

# ── 国际化 ────────────────────────────────────────────────────

_I18N = {
    "CN": {
        "title":          u"\U0001f375  \u65e9\u8336\u5948\u5de5\u5177\u96c6",
        "default_tools":  u"\u9ed8\u8ba4\u5de5\u5177",
        "custom_tools":   u"\u81ea\u5b9a\u4e49\u5de5\u5177",
        "settings":       u"\u8bbe\u7f6e",
        "refresh_ui":     u"\u5237\u65b0\u754c\u9762",
        "font_size":      u"\u5b57\u4f53\u5927\u5c0f",
        "bg_color":       u"\u80cc\u666f\u989c\u8272",
        "btn_color":      u"\u6309\u94ae\u989c\u8272",
        "language":       u"\u5207\u6362\u8bed\u8a00",
        "chanai_tools_auto_start": u"\u5de5\u5177\u7bb1\u81ea\u52a8\u542f\u52a8",
        "rename":         u"\u4fee\u6539\u547d\u540d",
        "delete":         u"\u5220\u9664",
        "rename_title":   u"\u4fee\u6539\u547d\u540d",
        "rename_prompt":  u"\u8f93\u5165\u65b0\u540d\u79f0\uff1a",
        "pick_script":    u"\u9009\u62e9\u811a\u672c",
        "add_tip":        u"\u70b9\u51fb\u6dfb\u52a0\u81ea\u5b9a\u4e49\u5de5\u5177",
        "btn_alpha":      u"\u900f\u660e\u5ea6",
        "icon_opacity":   u"\u56fe\u6807\u900f\u660e\u5ea6",
        "qt_style":       u"Qt\u98ce\u683c",
        "save_reminder":  u"\u81ea\u52a8\u4fdd\u5b58\u63d0\u9192",
        "save_interval_min": u"\u95f4\u9694(\u5206)",
        "save_first_min": u"\u9996\u6b21(\u5206)",
        "save_repeat_min": u"\u95f4\u9694(\u5206)",
        "reset":          u"\u91cd\u7f6e\u9ed8\u8ba4",
        "camera_status":  u"\u6444\u5f71\u673a",
        "camera_projection": u"\u6295\u5f71",
        "camera_proj_persp": u"\u900f\u89c6",
        "camera_proj_ortho": u"\u6b63\u4ea4",
        "camera_reset":   u"\u91cd\u7f6e\u6444\u5f71\u673a",
        "uninstall":      u"\u5378\u8f7d",
    },
    "EN": {
        "title":          u"\U0001f375  Zhaochanai Tools",
        "default_tools":  u"Default Tools",
        "custom_tools":   u"Custom Tools",
        "settings":       u"Settings",
        "refresh_ui":     u"Refresh UI",
        "font_size":      u"Font Size",
        "bg_color":       u"Background Color",
        "btn_color":      u"Button Color",
        "language":       u"Switch Lang",
        "chanai_tools_auto_start": u"Toolbox Auto Start",
        "rename":         u"Rename",
        "delete":         u"Delete",
        "rename_title":   u"Rename",
        "rename_prompt":  u"Enter new name:",
        "pick_script":    u"Select Script",
        "add_tip":        u"Click to add custom tool",
        "btn_alpha":      u"Opacity",
        "icon_opacity":   u"Icon Opacity",
        "qt_style":       u"Qt Style",
        "save_reminder":  u"Auto Save Reminder",
        "save_interval_min": u"Interval(min)",
        "save_first_min": u"First(min)",
        "save_repeat_min": u"Repeat(min)",
        "reset":          u"Reset Defaults",
        "camera_status":  u"Camera",
        "camera_projection": u"Projection",
        "camera_proj_persp": u"Perspective",
        "camera_proj_ortho": u"Orthographic",
        "camera_reset":   u"Reset Camera",
        "uninstall":      u"Uninstall",
    },
}

def _tr(key):
    lang = _SETTINGS.get("language", "CN")
    return _I18N.get(lang, _I18N["CN"]).get(key, key)


def _today_cn_text():
    try:
        now = datetime.datetime.now()
        week = [u"周一", u"周二", u"周三", u"周四", u"周五", u"周六", u"周日"]
        return u"%d/%d/%d %s" % (now.year, now.month, now.day, week[now.weekday()])
    except Exception:
        return u""


def _tb_qstyle_is_enabled(default=True):
    try:
        return bool(_SETTINGS.get("qt_style", default))
    except Exception:
        return bool(default)


# ═══════════════════════════════════════════════════════════════
#  工具注册表
# ═══════════════════════════════════════════════════════════════

def _t(label, cat, path=None, func="main", icon=None, tip="", action=None, **kwargs):
    d = dict(label=label, category=cat, module_path=path, func=func,
             icon=icon, tooltip=tip, action=action)
    if kwargs:
        d.update(kwargs)
    return d


_ADV_S = os.path.join(_THIS_DIR, "scripts")   # 本地 scripts/ 子目录
_X8_AT = r"F:\SAFE MATERIAL\scripts\Maya Py\x8_floating_toolset\tools\anim_tools"

def _s(f):  return os.path.join(_ADV_S, f)
def _x(f):  return os.path.join(_X8_AT, f)

TOOL_REGISTRY = [
    # ── 默认工具 ──────────────────────────────────────────────
    _t("构图辅助",       "默认工具", _s("adv_composition_helper.py"),    func="show"),
    _t("暴力粘贴",       "默认工具", _s("暴力粘贴Maya.py"),              func="show_cptools_python"),
    _t("时光机",         "默认工具", _s("adv_time_machine.py"),          func="show_maya_file_browser"),
    _t("飘带解算",       "默认工具", _x("spring_solver")),
    _t("运动轨迹",       "默认工具", _x("motion_trail")),
    _t("Bip帧标记",      "默认工具", _s("time_slider_bip.py"),           func="show"),
    _t("导出FBX",        "默认工具", _s("maya_batch_fbx_exporter.py"),   func="create_ui"),
    _t("属性添加器",     "默认工具", _s("attribute_holder_tool.py"),     func="show"),

    # ── 动画工具 ──────────────────────────────────────────────
    _t("武器约束",       "默认工具", _s("weapon_constraint_switcher.py"), func="show_ui"),
    _t("SDK录制",        "默认工具", _s("facial_driver_recorder_tool.py"), func="show_ui"),
    _t("自动曲线",       "默认工具", _s("adv_curve_debugger.py"),        func="show_ui"),
    _t("世界变换锁定",   "默认工具", _s("adv_world_transform_lock.py"),  func="show"),
    _t("对齐工具",       "默认工具", _s("adv_align_tool.py"),            func="show"),
    _t("关键帧工具",     "默认工具", _s("adv_keyframe_tools.py"),        func="show"),

    # ── 蒙皮工具 ───────────────────────��──────────────────────
    _t("Skin镜像",       "默认工具", _s("skinWeightMirrorTool.py"),      func="show_qt"),
]




# ═══════════════════════════════════════════════════════════════
#  工具执行
# ═══════════════════════════════════════════════════════════════

def _as_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [x for x in v if x]
    return [v]


def _tb_text(v):
    """Best-effort unicode text conversion (Py2/3 safe)."""
    if v is None:
        return u""
    try:
        text_type = unicode  # type: ignore # noqa: F821
    except Exception:
        text_type = str
    try:
        if isinstance(v, text_type):
            return v
    except Exception:
        pass
    try:
        if isinstance(v, bytes):
            try:
                return v.decode("utf-8")
            except Exception:
                try:
                    return v.decode("gbk")
                except Exception:
                    return v.decode("latin1", "ignore")
    except Exception:
        pass
    try:
        return text_type(v)
    except Exception:
        try:
            return u"%s" % v
        except Exception:
            return u""


def _mel_norm_path(p):
    return os.path.normpath(str(p)).replace("\\", "/")


def _mel_escape_string(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _mel_source_file(mel_mod, p):
    mel_mod.eval('source "%s"' % _mel_escape_string(_mel_norm_path(p)))


def _mel_proc_exists(mel_mod, proc_name):
    n = str(proc_name or "").strip()
    if not n:
        return False
    try:
        return bool(int(mel_mod.eval('exists "%s"' % _mel_escape_string(n))))
    except Exception:
        try:
            return bool(mel_mod.eval('exists "%s"' % _mel_escape_string(n)))
        except Exception:
            return False


def _resolve_mel_bootstrap_paths(info, main_mel_path):
    out = []
    for k in ("bootstrap_mel", "pre_mel"):
        for p in _as_list(info.get(k)):
            pp = os.path.normpath(str(p))
            if pp and os.path.exists(pp) and pp not in out:
                out.append(pp)

    # 通用兼容：如果主 mel 同目录存在 install.mel，则默认先 source install。
    try:
        auto_install = bool(info.get("auto_bootstrap_install", True))
    except Exception:
        auto_install = True
    try:
        base = os.path.basename(main_mel_path).lower()
        if auto_install and base != "install.mel":
            install_mel = os.path.join(os.path.dirname(main_mel_path), "install.mel")
            install_mel = os.path.normpath(install_mel)
            if os.path.exists(install_mel) and install_mel not in out:
                out.insert(0, install_mel)
    except Exception:
        pass

    # 内置加强：AdvancedSkeleton 继续强制优先 install。
    try:
        if os.path.basename(main_mel_path).lower() == "advancedskeleton.mel":
            install_mel = os.path.join(os.path.dirname(main_mel_path), "install.mel")
            install_mel = os.path.normpath(install_mel)
            if os.path.exists(install_mel) and install_mel not in out:
                out.insert(0, install_mel)
    except Exception:
        pass
    return out


def _guess_main_mel_from_install(install_mel_path):
    """Given install.mel, try to infer the runnable main mel file in same folder."""
    try:
        d = os.path.dirname(os.path.normpath(install_mel_path))
        if not os.path.isdir(d):
            return None
        files = []
        for f in os.listdir(d):
            if not f.lower().endswith(".mel"):
                continue
            if f.startswith("_"):
                continue
            if f.lower() == "install.mel":
                continue
            p = os.path.join(d, f)
            if os.path.isfile(p):
                files.append(os.path.normpath(p))
        if not files:
            return None

        # Priority 1: exact folder name match
        folder_name = os.path.basename(d).strip().lower()
        for p in files:
            if os.path.splitext(os.path.basename(p))[0].strip().lower() == folder_name:
                return p

        # Priority 2: canonical main names
        for name in ("main.mel", "start.mel", "startup.mel", "launch.mel", "run.mel"):
            for p in files:
                if os.path.basename(p).strip().lower() == name:
                    return p

        # Priority 3: if single candidate, use it
        if len(files) == 1:
            return files[0]

        # Priority 4: shortest basename (often package root proc)
        files_sorted = sorted(files, key=lambda p: (len(os.path.basename(p)), os.path.basename(p).lower()))
        return files_sorted[0] if files_sorted else None
    except Exception:
        return None


def _resolve_dotted_attr(root_obj, dotted_name):
    obj = root_obj
    for part in str(dotted_name or "").split("."):
        p = part.strip()
        if not p:
            continue
        obj = getattr(obj, p, None)
        if obj is None:
            return None
    return obj


def _resolve_python_entry_callable(mod, requested_name):
    """Resolve a callable Python entry with pragmatic fallbacks."""
    tried = []

    def _try_name(name):
        n = str(name or "").strip()
        if not n or n in tried:
            return None, None
        tried.append(n)
        fn = _resolve_dotted_attr(mod, n)
        if callable(fn):
            return fn, n
        return None, None

    # 1) Explicit requested entry first.
    fn, used = _try_name(requested_name)
    if fn:
        return fn, used, tried

    # 2) Common entry points across tools.
    fallback_names = [
        "main", "show", "show_ui", "create_ui", "run", "launch", "start",
        # ADV Fast Select full main window entry.
        "create_hierarchy_selection_ui",
        "open", "open_ui", "open_window",
        "ui.show",
        # Common names in ADV ecosystem.
        "open_adv_sr_groups_window_qt",
        "open_adv_ikfk_bake_window",
        "open_sync_key_groups_window_qt",
        "open_hotkey_mapping_window_qt",
        "open_hotkey_mapping_window",
        "open_hotkey_mapping_window_cmds",
        "open_macro_menu_qt",
        "open_macro_menu",
        "open_macro_menu_cmds",
    ]
    for n in fallback_names:
        fn, used = _try_name(n)
        if fn:
            return fn, used, tried

    return None, None, tried


def _is_switchruntime_package_dir(d):
    try:
        if not d or not os.path.isdir(d):
            return False
        req = ("__init__.py", "ui.py", "tools.py")
        for n in req:
            if not os.path.isfile(os.path.join(d, n)):
                return False
        return True
    except Exception:
        return False


def _find_switchruntime_package_dir(path):
    p = os.path.normpath(str(path or ""))
    if not p:
        return None
    if os.path.isdir(p):
        return p if _is_switchruntime_package_dir(p) else None
    if os.path.isfile(p):
        d = os.path.dirname(p)
        if _is_switchruntime_package_dir(d):
            return d
    return None


def _run_switchruntime_from_package(pkg_dir, fname):
    """Load switchRuntime package from arbitrary folder name, then execute entry."""
    import importlib

    init_py = os.path.join(pkg_dir, "__init__.py")
    if not os.path.isfile(init_py):
        return False

    # Purge previous package modules to force-reload from the selected location.
    try:
        stale = [k for k in list(sys.modules.keys()) if k == "switchRuntime" or k.startswith("switchRuntime.")]
        for k in stale:
            sys.modules.pop(k, None)
    except Exception:
        pass

    if sys.version_info[0] >= 3:
        import importlib.util as ilu
        spec = ilu.spec_from_file_location("switchRuntime", init_py, submodule_search_locations=[pkg_dir])
        if spec is None or spec.loader is None:
            return False
        mod = ilu.module_from_spec(spec)
        sys.modules["switchRuntime"] = mod
        spec.loader.exec_module(mod)
    else:
        # Py2.7: use imp package loader so relative imports inside package still work.
        import imp
        mod = imp.load_module("switchRuntime", None, pkg_dir, ("", "", imp.PKG_DIRECTORY))
        sys.modules["switchRuntime"] = mod

    entry = str(fname or "").strip()
    if not entry or entry.lower() in ("main", "show", "show_ui", "ui", "ui.show"):
        entry = "ui.show"

    fn = _resolve_dotted_attr(mod, entry)
    if not callable(fn):
        try:
            ui_mod = importlib.import_module("switchRuntime.ui")
            fn = getattr(ui_mod, "show", None)
        except Exception:
            fn = None
    if callable(fn):
        fn()
        return True
    return False

def _run_tool(info):
    action = info.get("action")
    if callable(action):
        try: action()
        except Exception: print(traceback.format_exc())
        return
    path  = info.get("module_path") or info.get("path") or ""
    fname = info.get("func") or "main"

    # Package-mode compat: switchRuntime uses relative imports and expects package import.
    pkg_dir = _find_switchruntime_package_dir(path)
    if pkg_dir:
        try:
            if _run_switchruntime_from_package(pkg_dir, fname):
                print("[ChanaiTools] switchRuntime 启动成功: " + pkg_dir)
                return
        except Exception:
            print("[ChanaiTools] switchRuntime 启动失败:\n" + traceback.format_exc())
            return

    # 如果是目录，尝试查找入口文件
    if os.path.isdir(path):
        base  = os.path.basename(path)
        # 优先查找同名 .py 文件
        cand_py = os.path.join(path, base + ".py")
        # 其次查找同名 .mel 文件
        cand_mel = os.path.join(path, base + ".mel")
        if os.path.exists(cand_py):
            path = cand_py
        elif os.path.exists(cand_mel):
            path = cand_mel
        else:
            # 查找第一个非下划线开头的 .py 或 .mel 文件
            path = next(
                (os.path.join(path, f) for f in os.listdir(path)
                 if (f.endswith(".py") or f.endswith(".mel")) and not f.startswith("_")), "")

    # 直接执行用户自定义脚本片段（高级入口）
    py_code = (info.get("run_python") or info.get("python_code") or "").strip()
    mel_inline = (info.get("run_mel") or info.get("mel_command") or "").strip()
    has_valid_path = bool(path and os.path.exists(path))
    if not has_valid_path:
        if py_code:
            try:
                exec(py_code, {"__name__": "__main__", "__file__": str(path or __file__)}, {})
                return
            except Exception:
                print("[ChanaiTools] Python 启动命令运行失败:\n" + traceback.format_exc())
                return
        if mel_inline:
            try:
                import maya.mel as mel
                mel.eval(mel_inline)
                print("[ChanaiTools] MEL 启动命令执行成功")
            except Exception:
                print("[ChanaiTools] MEL 启动命令运行失败:\n" + traceback.format_exc())
            return
        missing_path = path or (info.get("module_path") or info.get("path") or "")
        _handle_missing_tool_entry(info, missing_path)
        return

    if py_code:
        try:
            exec(py_code, {"__name__": "__main__", "__file__": path}, {})
            return
        except Exception:
            print("[ChanaiTools] Python 启动命令运行失败:\n" + traceback.format_exc())
            return

    # 处理 MEL 脚本
    if path.endswith(".mel"):
        try:
            import maya.mel as mel
            for bp in _resolve_mel_bootstrap_paths(info, path):
                _mel_source_file(mel, bp)

            _mel_source_file(mel, path)

            # 高级入口：run_mel / mel_command 可写完整 MEL 命令
            mel_cmd = (info.get("run_mel") or info.get("mel_command") or "").strip()
            if mel_cmd:
                mel.eval(mel_cmd)
                print("[ChanaiTools] MEL 启动命令执行成功")
                return

            # 兼容旧逻辑：优先执行 func；若不存在则回退到脚本同名 proc
            proc_name = str(fname or "").strip()
            if proc_name and proc_name.lower() != "main":
                if _mel_proc_exists(mel, proc_name):
                    mel.eval(proc_name + "()")
                else:
                    fallback_proc = os.path.splitext(os.path.basename(path))[0]
                    if fallback_proc and _mel_proc_exists(mel, fallback_proc):
                        print("[ChanaiTools] MEL 入口 %s 不存在，回退到 %s()" % (proc_name, fallback_proc))
                        mel.eval(fallback_proc + "()")
                    else:
                        print("[ChanaiTools] MEL 入口不存在: %s" % proc_name)
            else:
                # 特殊兼容：AdvancedSkeleton 仅 source 不会弹主 UI，自动调用同名入口。
                if os.path.basename(path).lower() == "advancedskeleton.mel":
                    fallback_proc = os.path.splitext(os.path.basename(path))[0]
                    if _mel_proc_exists(mel, fallback_proc):
                        mel.eval(fallback_proc + "()")
            print("[ChanaiTools] MEL 脚本执行成功: " + path)
        except Exception:
            print("[ChanaiTools] MEL 脚本运行失败:\n" + traceback.format_exc())
        return

    # 处理 Python 脚本
    d = os.path.dirname(path)
    if d not in sys.path: sys.path.insert(0, d)
    mname = "chanai_tools_tb__" + os.path.splitext(os.path.basename(path))[0]
    try:
        sys.modules.pop(mname, None)
        if sys.version_info[0] >= 3:
            import importlib.util as ilu
            sp = ilu.spec_from_file_location(mname, path)
            m  = ilu.module_from_spec(sp)
            sys.modules[mname] = m
            sp.loader.exec_module(m)
        else:
            import imp; m = imp.load_source(mname, path)
        fn, used_name, tried = _resolve_python_entry_callable(m, fname)
        if callable(fn):
            fn()
        else:
            try:
                avail = []
                for n in dir(m):
                    if n.startswith("_"):
                        continue
                    try:
                        if callable(getattr(m, n, None)):
                            avail.append(n)
                    except Exception:
                        pass
                avail = sorted(avail)[:30]
                print("[ChanaiTools] 找不到函数: %s | 已尝试: %s | 可用函数(部分): %s"
                      % (str(fname), ",".join(tried), ",".join(avail)))
            except Exception:
                print("[ChanaiTools] 找不到函数: " + str(fname))
    except Exception: print("[ChanaiTools] 运行失败:\n" + traceback.format_exc())


def _is_default_tool_label(label):
    """Whether a label belongs to TOOL_REGISTRY (default tools page)."""
    lab = _tb_text(label).strip()
    if not lab:
        return False
    try:
        for t in TOOL_REGISTRY:
            if _tb_text(t.get("label", "")).strip() == lab:
                return True
    except Exception:
        return False
    return False


def _refresh_live_panel_ui():
    """Refresh current opened panel if any."""
    try:
        try:
            import builtins as _b
        except ImportError:
            import __builtin__ as _b
        icon = _b.__dict__.get(_KEY)
        if not icon:
            return
        pan = getattr(icon, "_panel", None)
        if pan is None:
            return
        if hasattr(pan, "_rebuild_ui"):
            pan._rebuild_ui()
        try:
            pan.update()
        except Exception:
            pass
    except Exception:
        pass


def _handle_missing_tool_entry(info, missing_path):
    """Warn missing script and auto-hide missing default tool button."""
    miss = _tb_text(missing_path).strip()
    label = _tb_text(info.get("label", "")).strip()
    msg = u"[ChanaiTools] 找不到脚本: %s" % (miss or u"<empty>")
    print(msg)
    try:
        from maya import cmds
        cmds.warning(msg)
    except Exception:
        pass

    # Only auto-remove default tools. Custom slots should be managed manually.
    if not _is_default_tool_label(label):
        return

    try:
        removed = _load_removed_tools()
    except Exception:
        removed = []

    if label and (label not in removed):
        removed.append(label)
        _save_removed_tools(removed)
        _refresh_live_panel_ui()


_STARTUP_BOOTSTRAP_KEY = "__ChanaiToolsStartupBootstrap_v1__"


def _get_session_dict():
    try:
        import builtins as _b
    except ImportError:
        import __builtin__ as _b
    return _b.__dict__


def _startup_bootstrap_done():
    try:
        return bool(_get_session_dict().get(_STARTUP_BOOTSTRAP_KEY))
    except Exception:
        return False


def _mark_startup_bootstrap_done():
    try:
        _get_session_dict()[_STARTUP_BOOTSTRAP_KEY] = True
    except Exception:
        pass


def _resolve_tool_entry_path(path):
    p = os.path.normpath(str(path or ""))
    if not p:
        return ""
    if not os.path.isdir(p):
        return p
    base = os.path.basename(p)
    cand_py = os.path.join(p, base + ".py")
    cand_mel = os.path.join(p, base + ".mel")
    if os.path.exists(cand_py):
        return cand_py
    if os.path.exists(cand_mel):
        return cand_mel
    for f in os.listdir(p):
        if (f.endswith(".py") or f.endswith(".mel")) and (not f.startswith("_")):
            return os.path.join(p, f)
    return ""


def _run_tool_bootstrap(info):
    path = _resolve_tool_entry_path(info.get("module_path") or info.get("path") or "")
    if not path or (not os.path.exists(path)):
        return False

    # MEL: source bootstrap chain (install.mel first if存在)
    if path.endswith(".mel"):
        try:
            import maya.mel as mel
            for bp in _resolve_mel_bootstrap_paths(info, path):
                _mel_source_file(mel, bp)
            if os.path.basename(path).lower() == "install.mel":
                _mel_source_file(mel, path)
            run_mel = (info.get("bootstrap_run_mel") or "").strip()
            if run_mel:
                mel.eval(run_mel)
            return True
        except Exception:
            print("[ChanaiTools] 启动 bootstrap(MEL) 失败:\n" + traceback.format_exc())
            return False

    # Python: call bootstrap_func (default=bootstrap) without opening UI.
    try:
        d = os.path.dirname(path)
        if d not in sys.path:
            sys.path.insert(0, d)
        mname = "chanai_tools_tb_boot__" + os.path.splitext(os.path.basename(path))[0]
        sys.modules.pop(mname, None)
        if sys.version_info[0] >= 3:
            import importlib.util as ilu
            sp = ilu.spec_from_file_location(mname, path)
            m = ilu.module_from_spec(sp)
            sys.modules[mname] = m
            sp.loader.exec_module(m)
        else:
            import imp
            m = imp.load_source(mname, path)

        fn_name = str(info.get("bootstrap_func") or "bootstrap").strip()
        fn = _resolve_dotted_attr(m, fn_name)
        if callable(fn):
            ret = fn()
            return True if ret is None else bool(ret)
        return False
    except Exception:
        print("[ChanaiTools] 启动 bootstrap(Python) 失败:\n" + traceback.format_exc())
        return False


def _run_startup_bootstrap():
    if _startup_bootstrap_done():
        return
    _mark_startup_bootstrap_done()
    try:
        tools = _get_ordered_tools()
        for info in tools:
            if not bool(info.get("bootstrap_on_start")):
                continue
            _run_tool_bootstrap(info)
    except Exception:
        print("[ChanaiTools] 启动自动引导失败:\n" + traceback.format_exc())


def _schedule_startup_bootstrap():
    if _startup_bootstrap_done():
        return
    try:
        QtCore.QTimer.singleShot(0, _run_startup_bootstrap)
    except Exception:
        _run_startup_bootstrap()


# ═══════════════════════════════════════════════════════════════
#  颜色 / 样式常量（部分从设置读取）
# ═══════════════════════════════════════════════════════════════

def _color_from_list(lst, alpha=255):
    return QtGui.QColor(lst[0], lst[1], lst[2], alpha)

def _cur_bg():     return _color_from_list(_SETTINGS.get("bg_color",  [28,28,32]), 245)
def _cur_btn():    return _color_from_list(_SETTINGS.get("btn_color", [52,55,62]),
                                           _SETTINGS.get("btn_alpha", 255))
def _cur_font():   return _SETTINGS.get("font_size", 9)

_C_TITLE    = QtGui.QColor(36,  36,  42,  255)
_C_BORDER   = QtGui.QColor(80,  80,  100, 180)
_C_ACCENT   = QtGui.QColor(74,  127, 165, 255)
_C_BTN_HV   = QtGui.QColor(74,  127, 165, 200)
_C_BTN_PR   = QtGui.QColor(40,  80,  120, 255)
_C_TEXT     = QtGui.QColor(210, 210, 215, 255)
_C_TEXT_DIM = QtGui.QColor(130, 130, 140, 255)

_TAB_STYLE = """
QTabWidget::pane { background: transparent; border: none; }
QTabBar::tab {
    background: #2c2c34; color: #aaaaaa;
    padding: 5px 14px; margin-right: 2px;
    border-top-left-radius: 5px; border-top-right-radius: 5px;
    font-size: 12px;
}
QTabBar::tab:selected   { background: #4a7fa5; color: white; }
QTabBar::tab:hover:!selected { background: #3a3a48; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 5px; background: #1a1a20; }
QScrollBar::handle:vertical { background: #555566; border-radius: 2px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
"""

_PANEL_QSTYLE_SHEET = """
QWidget { color:#d9d9df; }
QPushButton {
    background:#2f343d;
    color:#d9d9df;
    border:1px solid #4e5663;
    border-radius:4px;
    padding:2px 8px;
}
QPushButton:hover { background:#3a4657; border-color:#5a6f8d; }
QPushButton:pressed { background:#263140; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background:#1d222a;
    color:#d9d9df;
    border:1px solid #4e5663;
    border-radius:4px;
    padding:2px 6px;
}
QCheckBox { color:#d9d9df; }
QTabBar::tab {
    background:#2c2f38;
    color:#b9bcc7;
    border:1px solid #4e5663;
    border-bottom:none;
    border-top-left-radius:5px;
    border-top-right-radius:5px;
    padding:5px 14px;
}
QTabBar::tab:selected {
    background:#3f5f86;
    color:#eef3ff;
    border-color:#6884aa;
}
"""


# ═══════════════════════════════════════════════════════════════
#  工具按钮（自绘，支持拖拽交换）
# ═══════════════════════════════════════════════════════════════

# 默认工具顺序持久化
_ORDER_FILE = os.path.join(_JSON_DIR, "tool_order.json")
_REMOVED_TOOLS_FILE = os.path.join(_JSON_DIR, "removed_tools.json")

def _load_tool_order():
    if os.path.exists(_ORDER_FILE):
        try:
            with _io_open(_ORDER_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return None

def _save_tool_order(labels):
    try:
        with _io_open(_ORDER_FILE, "w", encoding="utf-8") as fh:
            json.dump(labels, fh, ensure_ascii=False)
    except Exception:
        pass

def _load_removed_tools():
    """加载已移除的工具标签列表"""
    if os.path.exists(_REMOVED_TOOLS_FILE):
        try:
            with _io_open(_REMOVED_TOOLS_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return []

def _save_removed_tools(labels):
    """保存已移除的工具标签列表"""
    try:
        with _io_open(_REMOVED_TOOLS_FILE, "w", encoding="utf-8") as fh:
            json.dump(labels, fh, ensure_ascii=False)
    except Exception:
        pass

def _get_ordered_tools():
    """按持久化顺序返回 TOOL_REGISTRY，新增工具追加末尾，过滤已移除的工具"""
    removed = set(_load_removed_tools())
    order = _load_tool_order()

    # 过滤掉已移除的工具
    available_tools = [t for t in TOOL_REGISTRY if t["label"] not in removed]

    if not order:
        return available_tools

    by_label = {t["label"]: t for t in available_tools}
    result = []
    for lab in order:
        if lab in by_label:
            result.append(by_label.pop(lab))
    # 新增的工具追加末尾
    for t in available_tools:
        if t["label"] in by_label:
            result.append(t)
    return result

def _get_ordered_tools_by_category(tools_list):
    """按持久化顺序返回指定分类的工具列表"""
    order = _load_tool_order()
    if not order:
        return list(tools_list)
    by_label = {t["label"]: t for t in tools_list}
    result = []
    for lab in order:
        if lab in by_label:
            result.append(by_label.pop(lab))
    # 新增的工具追加末尾
    for t in tools_list:
        if t["label"] in by_label:
            result.append(t)
    return result


class ToolButton(QtWidgets.QWidget):
    """单个工具网格按钮，自绘，悬停高亮，支持拖拽交换"""

    H       = 50  # 40 * 1.25 = 50 (增加25%高度)
    ANIM_MS = 80
    DRAG_THRESHOLD = 8

    def __init__(self, info, grid_page=None, parent=None):
        super(ToolButton, self).__init__(parent)
        self._info  = info
        self._hover = 0.0
        self._grid_page = grid_page   # 持有 GridPage 引用
        self._panel_ref = None  # 持有面板引用，用于刷新UI
        self.setFixedHeight(self.H)
        self.setMouseTracking(True)
        self.setCursor(_PointingHand)
        self.setToolTip(info.get("tooltip", "") or info.get("label", ""))
        self.setAcceptDrops(True)

        self._anim = QPropertyAnimation(self, b"hoverPct")
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setEasingCurve(_OutCubic)

        self._press_pos = None
        self._dragging  = False
        self._drop_highlight = False

    # ── property ────────────────────────────────────────────
    def _get_hover(self): return self._hover
    def _set_hover(self, v):
        self._hover = v
        self.update()
    hoverPct = Property(float, _get_hover, _set_hover)

    # ── events ──────────────────────────────────────────────
    def enterEvent(self, e):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def leaveEvent(self, e):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def mousePressEvent(self, e):
        if e.button() == _LeftButton:
            self._press_pos = e.pos()
            self._dragging = False
        elif e.button() == _RightButton:
            self._show_context_menu(e)

    def mouseMoveEvent(self, e):
        if self._press_pos and not self._dragging:
            if (e.pos() - self._press_pos).manhattanLength() > self.DRAG_THRESHOLD:
                self._dragging = True
                self._start_drag()

    def mouseReleaseEvent(self, e):
        if e.button() == _LeftButton and not self._dragging:
            _run_tool(self._info)
        self._press_pos = None
        self._dragging = False

    # ── 右键菜单 ────────────────────────────���───────────────
    def _show_context_menu(self, e):
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#2a2a32; color:#ddd; border:1px solid #555; font-size:12px; }"
            "QMenu::item:selected { background:#4a7fa5; }")
        act_move = menu.addAction(u"移动到自定义工具")
        act_open_path = menu.addAction(u"打开文件路径")
        chosen = menu.exec_(_global_pos(e))
        if chosen == act_move:
            self._move_to_custom()
        elif chosen == act_open_path:
            self._open_file_location()

    def _open_file_location(self):
        """在文件管理器中打开并选中脚本文件"""
        path = self._info.get("module_path") or self._info.get("path", "")
        if not path or not os.path.exists(path):
            try:
                from maya import cmds
                cmds.warning(u"文件路径不存在: {}".format(path))
            except Exception:
                pass
            return

        # 如果是目录，找到主脚本文件
        if os.path.isdir(path):
            base = os.path.basename(path)
            cand = os.path.join(path, base + ".py")
            if os.path.exists(cand):
                path = cand
            else:
                # 找第一个非下划线开头的 .py 文件
                for f in os.listdir(path):
                    if f.endswith(".py") and not f.startswith("_"):
                        path = os.path.join(path, f)
                        break

        # 使用系统命令打开文件管理器并选中文件（异步，不阻塞）
        try:
            import subprocess
            if sys.platform == "win32":
                subprocess.Popen(['explorer', '/select,', os.path.normpath(path)])
            elif sys.platform == "darwin":  # macOS
                subprocess.Popen(['open', '-R', path])
            else:  # Linux
                subprocess.Popen(['xdg-open', os.path.dirname(path)])
        except Exception as e:
            print("[ChanaiTools] 打开文件路径失败: {}".format(e))

    def _move_to_custom(self):
        """将工具从默认工具移动到自定义工具"""
        # 检查自定义工具是否已满（最多64个槽位）
        slots = _load_custom_slots()
        empty_idx = -1
        for i, slot in enumerate(slots):
            if slot is None:
                empty_idx = i
                break

        if empty_idx == -1:
            try:
                from maya import cmds
                cmds.warning(u"自定义工具已满（最多64个），无法移动更多工具")
            except Exception:
                pass
            return

        # 添加到自定义工具
        tool_info = {
            "label": self._info.get("label", ""),
            "path": self._info.get("module_path") or self._info.get("path", ""),
            "func": self._info.get("func", "main")
        }
        slots[empty_idx] = tool_info
        _save_custom_slots(slots)

        # 从默认工具中移除（添加到 removed_tools 列表）
        tool_label = self._info.get("label", "")
        removed = _load_removed_tools()
        if tool_label not in removed:
            removed.append(tool_label)
            _save_removed_tools(removed)

        # 刷新整个面板UI
        self._refresh_panel_ui()

        try:
            from maya import cmds
            cmds.inViewMessage(amg=u"<hl>已移动到自定义工具</hl>", pos='midCenter', fade=True)
        except Exception:
            pass

    def _refresh_panel_ui(self):
        """刷新整个面板UI"""
        # 向上查找到 ChanaiToolsPanel
        parent = self.parent()
        while parent:
            if isinstance(parent, ChanaiToolsPanel):
                parent._rebuild_ui()
                break
            parent = parent.parent()

    # ── drag ────────────────────────────────────────────────
    def _start_drag(self):
        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        mime.setText(self._info.get("label", ""))
        drag.setMimeData(mime)
        # 创建拖拽缩略图
        pix = QtGui.QPixmap(self.size())
        pix.fill(QtGui.QColor(0, 0, 0, 0))
        self.render(pix)
        drag.setPixmap(pix)
        drag.setHotSpot(self._press_pos)
        drag.exec_(_qt(Qt, 'MoveAction', 'DropAction.MoveAction'))

    def dragEnterEvent(self, e):
        if e.mimeData().hasText():
            e.acceptProposedAction()
            self._drop_highlight = True
            self.update()

    def dragLeaveEvent(self, e):
        self._drop_highlight = False
        self.update()

    def dropEvent(self, e):
        self._drop_highlight = False
        self.update()
        src_label = e.mimeData().text()
        dst_label = self._info.get("label", "")
        if src_label != dst_label and self._grid_page:
            self._grid_page.swap_tools(src_label, dst_label)
        e.acceptProposedAction()

    # ── paint ───────────────────────────────────────────────
    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(_Antialiasing)

        h     = self._hover
        label = self._info.get("label", "?")

        def lerp(a, b, t): return int(a + (b - a) * t)
        c_btn = _cur_btn()
        bg = QtGui.QColor(
            lerp(c_btn.red(),   _C_BTN_HV.red(),   h),
            lerp(c_btn.green(), _C_BTN_HV.green(), h),
            lerp(c_btn.blue(),  _C_BTN_HV.blue(),  h),
            lerp(c_btn.alpha(), _C_BTN_HV.alpha(), h))

        # 拖入高亮
        if self._drop_highlight:
            border = QtGui.QColor(120, 220, 255, 255)
            bg = QtGui.QColor(60, 100, 140, 200)
        else:
            border = QtGui.QColor(
                _C_ACCENT.red(), _C_ACCENT.green(), _C_ACCENT.blue(),
                lerp(60, 220, h))

        rect = QtCore.QRectF(1.5, 1.5, self.width() - 3, self.H - 3)
        p.setBrush(bg)
        p.setPen(QtGui.QPen(border, 2.0 if self._drop_highlight else 1.2))
        p.drawRoundedRect(rect, 5, 5)

        p.setPen(QtGui.QColor(255, 255, 255, int(180 + 75 * h)))
        f = QtGui.QFont()
        f.setPointSize(_cur_font())
        p.setFont(f)
        draw_rect = self.rect().adjusted(3, 1, -3, -1)
        p.drawText(draw_rect, _AlignCenter | _TextWordWrap, label)
        p.end()


# ═══════════════════════════════════════════════════════════════
#  网格面板（支持拖拽交换顺序）
# ═══════════════════════════════════════════════════════════════

class GridPage(QtWidgets.QWidget):
    """一个 Tab 页的网格，支持拖拽交换按钮顺序"""
    COLS = 4

    def __init__(self, tools=None, parent=None):
        super(GridPage, self).__init__(parent)
        self._tools = list(tools) if tools else []
        self._grid = QtWidgets.QGridLayout(self)
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._grid.setSpacing(4)
        for c in range(self.COLS):
            self._grid.setColumnStretch(c, 1)
        self._rebuild()

    def _rebuild(self):
        # 清空旧按钮
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for idx, t in enumerate(self._tools):
            r, c = divmod(idx, self.COLS)
            self._grid.addWidget(ToolButton(t, grid_page=self), r, c)

    def swap_tools(self, src_label, dst_label):
        si = di = -1
        for i, t in enumerate(self._tools):
            if t.get("label") == src_label: si = i
            if t.get("label") == dst_label: di = i
        if si >= 0 and di >= 0 and si != di:
            self._tools[si], self._tools[di] = self._tools[di], self._tools[si]
            self._rebuild()
            # 持久化新顺序
            _save_tool_order([t["label"] for t in self._tools])

    def remove_tool(self, label):
        """从默认工具中移除指定工具"""
        # 添加到已移除列表
        removed = _load_removed_tools()
        if label not in removed:
            removed.append(label)
            _save_removed_tools(removed)

        # 从当前工具列表中移除
        self._tools = [t for t in self._tools if t.get("label") != label]
        self._rebuild()


# ═══════════════════════════════════════════════════════════════
#  自定义工具持久化
# ═══════════════════════════════════════════════════════════════

_CUSTOM_CFG = os.path.join(_JSON_DIR, "custom_tools.json")
_SLOTS_PER_PAGE = 16   # 4×4
_MAX_PAGES      = 8    # 从4页扩展到8页
_CUSTOM_SLOTS   = _SLOTS_PER_PAGE * _MAX_PAGES   # 128


def _load_custom_slots():
    """从 JSON 读取自定义工具列表，返回长度=_CUSTOM_SLOTS 的 list"""
    slots = [None] * _CUSTOM_SLOTS
    if os.path.exists(_CUSTOM_CFG):
        try:
            with _io_open(_CUSTOM_CFG, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for i, item in enumerate(data.get("slots", [])):
                if i >= _CUSTOM_SLOTS:
                    break
                if item and isinstance(item, dict):
                    has_path = bool(item.get("path"))
                    has_inline = bool(
                        (item.get("run_python") or item.get("python_code") or "").strip() or
                        (item.get("run_mel") or item.get("mel_command") or "").strip()
                    )
                    if has_path or has_inline:
                        slots[i] = item
        except Exception:
            pass
    return slots


def _save_custom_slots(slots):
    """保存自定义工具列表到 JSON"""
    data = {"slots": []}
    extra_keys = (
        "bootstrap_mel", "pre_mel",
        "run_mel", "mel_command",
        "run_python", "python_code",
        "auto_call_basename",
        "auto_bootstrap_install",
        "shelf_name", "shelf_button", "source_type",
    )
    for s in slots:
        if s and isinstance(s, dict):
            item = {"label": s.get("label", ""), "path": s.get("path", ""),
                    "func": s.get("func", "main")}
            for k in extra_keys:
                if k in s:
                    item[k] = s.get(k)
            data["slots"].append(item)
        else:
            data["slots"].append(None)
    try:
        with _io_open(_CUSTOM_CFG, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception:
        print("[ChanaiTools] 保存自定义工具配置失败")


def _collect_shelf_tools():
    """Collect shelf buttons with executable commands from Maya shelf tabs."""
    out = []
    try:
        import maya.cmds as cmds_local
        import maya.mel as mel_local
    except Exception:
        return out

    try:
        shelf_top = mel_local.eval('$tmp=$gShelfTopLevel')
    except Exception:
        shelf_top = ""
    if not shelf_top:
        return out
    try:
        if not cmds_local.control(shelf_top, exists=True):
            return out
    except Exception:
        return out

    try:
        current_shelf = cmds_local.tabLayout(shelf_top, q=True, selectTab=True) or ""
    except Exception:
        current_shelf = ""
    try:
        shelves = cmds_local.tabLayout(shelf_top, q=True, childArray=True) or []
    except Exception:
        shelves = []

    for shelf in shelves:
        try:
            children = cmds_local.shelfLayout(shelf, q=True, childArray=True) or []
        except Exception:
            children = []
        for btn in children:
            try:
                if not cmds_local.control(btn, exists=True):
                    continue
                cmd = cmds_local.shelfButton(btn, q=True, command=True) or ""
            except Exception:
                continue
            cmd = _tb_text(cmd).strip()
            if not cmd:
                continue
            try:
                source_type = (cmds_local.shelfButton(btn, q=True, sourceType=True) or "mel").lower()
            except Exception:
                source_type = "mel"
            if source_type not in ("python", "mel"):
                source_type = "mel"
            try:
                label = cmds_local.shelfButton(btn, q=True, label=True) or ""
            except Exception:
                label = ""
            try:
                ann = cmds_local.shelfButton(btn, q=True, annotation=True) or ""
            except Exception:
                ann = ""
            display = (_tb_text(label).strip() or _tb_text(ann).strip() or _tb_text(btn).strip())
            out.append({
                "shelf": _tb_text(shelf),
                "button": _tb_text(btn),
                "label": _tb_text(display),
                "raw_label": _tb_text(label or ""),
                "annotation": _tb_text(ann or ""),
                "command": cmd,
                "source_type": source_type,
                "is_current": bool(_tb_text(shelf) == _tb_text(current_shelf)),
            })

    out.sort(key=lambda x: (0 if x.get("is_current") else 1, x.get("shelf", "").lower(), x.get("label", "").lower()))
    return out


# ═══════════════════════════════════════════════════════════════
#  自定义工具按钮 & 网格
# ═══════════════════════════════════════════════════════════════

class _CustomSlotButton(QtWidgets.QWidget):
    """单个自定义工具槽位：未设置时显示 "+"，已设置时显示脚本名"""

    H = 50  # 40 * 1.25 = 50 (增加25%高度)
    ANIM_MS = 80
    DRAG_THRESHOLD = 8

    slotChanged = Signal()   # 内容变化时发出

    def __init__(self, index, slot_data=None, parent=None):
        super(_CustomSlotButton, self).__init__(parent)
        self._index = index
        self._slot  = slot_data   # None 或 {"label":..,"path":..,"func":..}
        self._hover = 0.0
        self.setFixedHeight(self.H)
        self.setMouseTracking(True)
        self.setCursor(_PointingHand)
        self.setAcceptDrops(True)
        self._update_tooltip()

        self._anim = QPropertyAnimation(self, b"hoverPct")
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setEasingCurve(_OutCubic)

        self._press_pos = None
        self._dragging = False
        self._drop_highlight = False
        self._custom_page_ref = None  # 持有 CustomToolPage 引用

    def _update_tooltip(self):
        if self._slot:
            tip = (self._slot.get("path", "") or "").strip()
            if not tip:
                shelf_name = str(self._slot.get("shelf_name", "") or "").strip()
                shelf_btn = str(self._slot.get("shelf_button", "") or "").strip()
                if shelf_name or shelf_btn:
                    tip = u"[Shelf] %s / %s" % (shelf_name, shelf_btn)
                elif (self._slot.get("run_python") or self._slot.get("python_code")):
                    tip = u"[Inline Python Command]"
                elif (self._slot.get("run_mel") or self._slot.get("mel_command")):
                    tip = u"[Inline MEL Command]"
            self.setToolTip(tip)
        else:
            self.setToolTip(_tr("add_tip"))

    # property
    def _get_hover(self): return self._hover
    def _set_hover(self, v): self._hover = v; self.update()
    hoverPct = Property(float, _get_hover, _set_hover)

    def enterEvent(self, e):
        self._anim.stop(); self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0); self._anim.start()

    def leaveEvent(self, e):
        self._anim.stop(); self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0); self._anim.start()

    def mousePressEvent(self, e):
        if e.button() == _LeftButton:
            self._press_pos = e.pos()
            self._dragging = False
        elif e.button() == _RightButton:
            self._show_context_menu(e)

    def mouseMoveEvent(self, e):
        if self._press_pos and not self._dragging:
            if (e.pos() - self._press_pos).manhattanLength() > self.DRAG_THRESHOLD:
                self._dragging = True
                if self._slot:  # 只有有内容的槽位才能拖拽
                    self._start_drag()

    def mouseReleaseEvent(self, e):
        if e.button() == _LeftButton and not self._dragging:
            if self._slot:
                _run_tool(self._slot)
            else:
                self._browse()
        self._press_pos = None
        self._dragging = False

    # ── 拖拽功能 ─────────────────────────────────────────────
    def _start_drag(self):
        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        mime.setText(str(self._index))  # 传递槽位索引
        drag.setMimeData(mime)
        # 创建拖拽缩略图
        pix = QtGui.QPixmap(self.size())
        pix.fill(QtGui.QColor(0, 0, 0, 0))
        self.render(pix)
        drag.setPixmap(pix)
        drag.setHotSpot(self._press_pos)
        drag.exec_(_qt(Qt, 'MoveAction', 'DropAction.MoveAction'))

    def dragEnterEvent(self, e):
        if e.mimeData().hasText():
            e.acceptProposedAction()
            self._drop_highlight = True
            self.update()

    def dragLeaveEvent(self, e):
        self._drop_highlight = False
        self.update()

    def dropEvent(self, e):
        self._drop_highlight = False
        self.update()
        try:
            src_index = int(e.mimeData().text())
            dst_index = self._index
            if src_index != dst_index and self._custom_page_ref:
                self._custom_page_ref.swap_slots(src_index, dst_index)
        except Exception:
            pass
        e.acceptProposedAction()

    # ── 右键菜单 ─────────────────────────────────────────────
    def _show_context_menu(self, e):
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#2a2a32; color:#ddd; border:1px solid #555; font-size:12px; }"
            "QMenu::item:selected { background:#4a7fa5; }")
        act_add_shelf = menu.addAction(u"从当前工具栏添加")
        act_browse = menu.addAction(_tr("pick_script"))
        act_rename = None
        act_delete = None
        act_move = None
        act_open_path = None
        if self._slot:
            menu.addSeparator()
            act_rename = menu.addAction(_tr("rename"))
            act_delete = menu.addAction(_tr("delete"))
            act_move = menu.addAction(u"移动到默认工具")
            act_open_path = menu.addAction(u"打开文件路径")
            slot_path = str(self._slot.get("path", "") or "").strip()
            if not slot_path:
                act_move.setEnabled(False)
                act_open_path.setEnabled(False)
        chosen = menu.exec_(_global_pos(e))
        if chosen == act_add_shelf:
            self._add_from_shelf()
        elif chosen == act_browse:
            self._browse()
        elif chosen == act_rename:
            self._rename()
        elif chosen == act_delete:
            self._clear()
        elif chosen == act_move:
            self._move_to_default()
        elif chosen == act_open_path:
            self._open_file_location()

    def _add_from_shelf(self):
        items = _collect_shelf_tools()
        if not items:
            try:
                cmds.warning(u"未读取到工具栏按钮，请先打开 Maya 工具栏。")
            except Exception:
                pass
            return

        labels = []
        for it in items:
            cur_tag = u"* " if it.get("is_current") else u"  "
            labels.append(u"%s[%s] %s" % (cur_tag, it.get("shelf", ""), it.get("label", "")))

        selected, ok = QtWidgets.QInputDialog.getItem(
            self,
            u"从工具栏添加",
            u"选择一个工具栏按钮（* 为当前工具栏）",
            labels,
            0,
            False
        )
        if not ok:
            return
        sel = _tb_text(selected or "")
        if not sel:
            return
        try:
            idx = labels.index(sel)
        except ValueError:
            return
        it = items[idx]
        cmd_text = _tb_text(it.get("command", "") or "").strip()
        if not cmd_text:
            try:
                cmds.warning(u"该工具栏按钮没有可执行命令。")
            except Exception:
                pass
            return

        source_type = _tb_text(it.get("source_type", "mel") or "mel").lower()
        slot = {
            "label": _tb_text(it.get("label", "") or "ShelfTool"),
            "path": "",
            "func": "main",
            "shelf_name": _tb_text(it.get("shelf", "") or ""),
            "shelf_button": _tb_text(it.get("button", "") or ""),
            "source_type": source_type,
        }
        if source_type == "python":
            slot["run_python"] = cmd_text
        else:
            slot["run_mel"] = cmd_text
        self._slot = slot
        self._update_tooltip()
        self.update()
        self.slotChanged.emit()

    def _open_file_location(self):
        """在文件管理器中打开并选中脚本文件"""
        if not self._slot:
            return

        path = self._slot.get("path", "")
        if not path or not os.path.exists(path):
            try:
                from maya import cmds
                cmds.warning(u"文件路径不存在: {}".format(path))
            except Exception:
                pass
            return

        # 使用系统命令打开文件管理器并选中文件（异步，不阻塞）
        try:
            import subprocess
            if sys.platform == "win32":
                subprocess.Popen(['explorer', '/select,', os.path.normpath(path)])
            elif sys.platform == "darwin":  # macOS
                subprocess.Popen(['open', '-R', path])
            else:  # Linux
                subprocess.Popen(['xdg-open', os.path.dirname(path)])
        except Exception as e:
            print("[ChanaiTools] 打开文件路径失败: {}".format(e))

    def _rename(self):
        cur = self._slot.get("label", "") if self._slot else ""
        text, ok = QtWidgets.QInputDialog.getText(
            self, _tr("rename_title"), _tr("rename_prompt"),
            QtWidgets.QLineEdit.Normal, cur)
        if ok and text.strip():
            self._slot["label"] = text.strip()
            self._update_tooltip()
            self.update()
            self.slotChanged.emit()

    def _browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, _tr("pick_script"),
            os.path.expanduser("~"),
            u"Python / MEL (*.py *.mel);;Python (*.py);;MEL (*.mel)")
        if not path:
            return
        path = os.path.normpath(path)
        ext = os.path.splitext(path)[1].lower()

        if ext == ".mel":
            mel_path = path
            mel_dir = os.path.dirname(path)
            base_no_ext = os.path.splitext(os.path.basename(path))[0]
            install_mel = None

            # 通用兼容：若选的是 install.mel，尝试推断同目录主入口 mel。
            if base_no_ext.lower() == "install":
                install_mel = path
                guessed_main = _guess_main_mel_from_install(path)
                if guessed_main and os.path.exists(guessed_main):
                    mel_path = os.path.normpath(guessed_main)

            name = os.path.splitext(os.path.basename(mel_path))[0]

            # install.mel 自身通常只有安装命令，不一定有同名 proc。
            default_func = "main" if os.path.basename(mel_path).lower() == "install.mel" else name
            self._slot = {"label": name, "path": mel_path, "func": default_func}

            # 若目录中存在 install.mel（或刚选中 install.mel），自动串联为 bootstrap。
            auto_install = os.path.join(mel_dir, "install.mel")
            auto_install = os.path.normpath(auto_install)
            boot = install_mel or (auto_install if os.path.exists(auto_install) else None)
            if boot and os.path.exists(boot) and os.path.normcase(boot) != os.path.normcase(mel_path):
                self._slot["bootstrap_mel"] = [boot]
                self._slot["auto_bootstrap_install"] = True
        else:
            name = os.path.splitext(os.path.basename(path))[0]
            self._slot = {"label": name, "path": path, "func": "main"}

        self._update_tooltip()
        self.update()
        self.slotChanged.emit()

    def _clear(self):
        self._slot = None
        self._update_tooltip()
        self.update()
        self.slotChanged.emit()

    def _move_to_default(self):
        """将工具从自定义工具移动到默认工具"""
        if not self._slot:
            return

        # 检查默认工具数量（最多20个：4列×5行）
        removed = _load_removed_tools()
        current_default_count = len(TOOL_REGISTRY) - len(removed)

        if current_default_count >= 20:
            try:
                from maya import cmds
                cmds.warning(u"默认工具已满（最多20个），无法移动更多工具")
            except Exception:
                pass
            return

        # 从已移除列表中恢复（如果存在）
        tool_label = self._slot.get("label", "")
        if tool_label in removed:
            removed.remove(tool_label)
            _save_removed_tools(removed)

        # 清除当前槽位
        self._slot = None
        self._update_tooltip()
        self.update()
        self.slotChanged.emit()

        # 刷新整个面板UI
        self._refresh_panel_ui()

        try:
            from maya import cmds
            cmds.inViewMessage(amg=u"<hl>已移动到默认工具</hl>", pos='midCenter', fade=True)
        except Exception:
            pass

    def _refresh_panel_ui(self):
        """刷新整个面板UI"""
        # 向上查找到 ChanaiToolsPanel
        parent = self.parent()
        while parent:
            if hasattr(parent, '__class__') and parent.__class__.__name__ == 'ChanaiToolsPanel':
                parent._rebuild_ui()
                break
            parent = parent.parent()

    # paint
    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(_Antialiasing)
        h = self._hover

        def lerp(a, b, t): return int(a + (b - a) * t)

        # 拖入高亮
        if self._drop_highlight:
            if self._slot:
                bg = QtGui.QColor(60, 100, 140, 200)
                border = QtGui.QColor(120, 220, 255, 255)
            else:
                bg = QtGui.QColor(50, 80, 110, 180)
                border = QtGui.QColor(100, 200, 255, 255)
            label = self._slot.get("label", "?") if self._slot else "+"
        elif self._slot:
            c_btn = _cur_btn()
            bg = QtGui.QColor(lerp(c_btn.red(), _C_BTN_HV.red(), h),
                              lerp(c_btn.green(), _C_BTN_HV.green(), h),
                              lerp(c_btn.blue(), _C_BTN_HV.blue(), h),
                              lerp(c_btn.alpha(), _C_BTN_HV.alpha(), h))
            border = QtGui.QColor(_C_ACCENT.red(), _C_ACCENT.green(),
                                  _C_ACCENT.blue(), lerp(60, 220, h))
            label = self._slot.get("label", "?")
        else:
            bg = QtGui.QColor(38, 38, 44, lerp(120, 180, h))
            border = QtGui.QColor(100, 100, 120, lerp(80, 200, h))
            label = "+"

        rect = QtCore.QRectF(1.5, 1.5, self.width() - 3, self.H - 3)
        p.setBrush(bg)
        pen = QtGui.QPen(border, 2.0 if self._drop_highlight else 1.2)
        if not self._slot and not self._drop_highlight:
            pen.setStyle(_qt(QtCore.Qt, 'DashLine', 'PenStyle.DashLine'))
        p.setPen(pen)
        p.drawRoundedRect(rect, 5, 5)

        if self._slot:
            p.setPen(QtGui.QColor(255, 255, 255, int(180 + 75 * h)))
        else:
            p.setPen(QtGui.QColor(160, 160, 170, int(120 + 100 * h)))
        f = QtGui.QFont()
        f.setPointSize(_cur_font() if self._slot else 16)
        if not self._slot:
            f.setWeight(_qt(QtGui.QFont, 'Light', 'Weight.Light'))
        p.setFont(f)
        draw_rect = self.rect().adjusted(3, 1, -3, -1)
        p.drawText(draw_rect, _AlignCenter | _TextWordWrap, label)
        p.end()


# ── 翻页箭头按钮 ────────────────────────────────────────────

_ARROW_SS = """
QPushButton {
    background: #2a2a32; color: #999; border: 1px solid #444;
    border-radius: 4px; font-size: 16px; font-weight: bold;
}
QPushButton:hover { background: #4a7fa5; color: white; border-color:#5a9fc5; }
QPushButton:disabled { color: #444; border-color: #333; background: #222; }
"""


class CustomToolPage(QtWidgets.QWidget):
    """自定义工具 Tab 页：4×4 网格 × 最多4页，带左右翻页箭头"""
    COLS = 4

    def __init__(self, parent=None):
        super(CustomToolPage, self).__init__(parent)
        self._all_slots = _load_custom_slots()
        self._page = 0
        self._btns = []          # 当前页面的 16 个按钮

        # 顶层布局：左箭头 | 网格 | 右箭头
        hlay = QtWidgets.QHBoxLayout(self)
        hlay.setContentsMargins(2, 4, 2, 4)
        hlay.setSpacing(3)

        self._btn_left = QtWidgets.QPushButton(u"\u25C0")
        self._btn_left.setFixedSize(22, 80)
        self._btn_left.setStyleSheet(_ARROW_SS)
        self._btn_left.clicked.connect(self._prev_page)
        hlay.addWidget(self._btn_left)

        # 中间区域：网格 + 页码指示
        center = QtWidgets.QVBoxLayout()
        center.setSpacing(4)
        center.setContentsMargins(0, 0, 0, 0)

        self._grid_widget = QtWidgets.QWidget()
        self._grid_lay = QtWidgets.QGridLayout(self._grid_widget)
        self._grid_lay.setContentsMargins(4, 4, 4, 4)
        self._grid_lay.setSpacing(4)
        for c in range(self.COLS):
            self._grid_lay.setColumnStretch(c, 1)
        center.addWidget(self._grid_widget)

        self._page_label = QtWidgets.QLabel()
        self._page_label.setAlignment(_AlignHCenter)
        self._page_label.setStyleSheet("color:#888; font-size:10px;")
        center.addWidget(self._page_label)
        hlay.addLayout(center, 1)

        self._btn_right = QtWidgets.QPushButton(u"\u25B6")
        self._btn_right.setFixedSize(22, 80)
        self._btn_right.setStyleSheet(_ARROW_SS)
        self._btn_right.clicked.connect(self._next_page)
        hlay.addWidget(self._btn_right)

        self._rebuild_page()

    # ── 翻页 ─────────────────────────────────────────────────
    def _prev_page(self):
        if self._page > 0:
            self._page -= 1
            self._rebuild_page()

    def _next_page(self):
        if self._page < _MAX_PAGES - 1:
            self._page += 1
            self._rebuild_page()

    def _rebuild_page(self):
        # 清旧按钮
        for btn in self._btns:
            self._grid_lay.removeWidget(btn)
            btn.setParent(None)
            btn.deleteLater()
        self._btns = []

        base = self._page * _SLOTS_PER_PAGE
        for idx in range(_SLOTS_PER_PAGE):
            r, c = divmod(idx, self.COLS)
            slot_idx = base + idx
            btn = _CustomSlotButton(slot_idx, self._all_slots[slot_idx])
            btn._custom_page_ref = self  # 设置引用
            btn.slotChanged.connect(self._on_changed)
            self._grid_lay.addWidget(btn, r, c)
            self._btns.append(btn)

        self._btn_left.setEnabled(self._page > 0)
        self._btn_right.setEnabled(self._page < _MAX_PAGES - 1)
        self._page_label.setText("%d / %d" % (self._page + 1, _MAX_PAGES))

    def _on_changed(self):
        base = self._page * _SLOTS_PER_PAGE
        for i, btn in enumerate(self._btns):
            self._all_slots[base + i] = btn._slot
        _save_custom_slots(self._all_slots)

    def swap_slots(self, src_index, dst_index):
        """交换两个槽位的内容"""
        if 0 <= src_index < _CUSTOM_SLOTS and 0 <= dst_index < _CUSTOM_SLOTS:
            self._all_slots[src_index], self._all_slots[dst_index] = \
                self._all_slots[dst_index], self._all_slots[src_index]
            _save_custom_slots(self._all_slots)
            # 重新加载当前页面
            self._all_slots = _load_custom_slots()
            self._rebuild_page()


# ═══════════════════════════════════════════════════════════════
#  设置页
# ═══════════════════════════════════════════════════════════════

_SETTING_ROW_SS = (
    "QLabel { color:#ccc; font-size:14px; }"  # 12 * 1.15 ≈ 14 (放大15%)
    "QPushButton { background:#3a3a44; color:#ddd; border:1px solid #555; "
    "border-radius:4px; padding:4px 10px; font-size:13px; }"  # 11 * 1.15 ≈ 13 (放大15%)
    "QPushButton:hover { background:#4a7fa5; border-color:#6ab; }"
    "QSpinBox { background:#2a2a32; color:#ddd; border:1px solid #555; "
    "border-radius:3px; padding:2px 6px; font-size:13px; min-width:50px; }"  # 11 * 1.15 ≈ 13 (放大15%)
    "QCheckBox { color:#ccc; font-size:13px; spacing:8px; }"
    "QCheckBox::indicator { width:18px; height:18px; border:1px solid #555; border-radius:3px; background:#2a2a32; }"
    "QCheckBox::indicator:checked { background:#4a7fa5; border-color:#6ab; }"
    "QCheckBox::indicator:hover { border-color:#6ab; }"
)


class SettingsPage(QtWidgets.QWidget):
    """设置 Tab 页：字体大小 / 背景颜色 / 按钮颜色 / 语言切换 / 重置"""

    settingsChanged = Signal()

    def __init__(self, panel_ref, parent=None):
        super(SettingsPage, self).__init__(parent)
        self._panel = panel_ref     # 持有面板引用，用于实时刷新

        vlay = QtWidgets.QVBoxLayout(self)
        vlay.setContentsMargins(12, 12, 12, 12)
        vlay.setSpacing(8)
        self.setStyleSheet(_SETTING_ROW_SS)

        # ── 第一行：字体大小 + 背景颜色 + 按钮颜色 ──
        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(QtWidgets.QLabel(_tr("font_size")))
        self._spin_font = QtWidgets.QSpinBox()
        self._spin_font.setRange(7, 16)
        self._spin_font.setValue(_SETTINGS.get("font_size", 9))
        self._spin_font.setFixedWidth(50)
        self._spin_font.valueChanged.connect(self._on_font)
        row1.addWidget(self._spin_font)

        row1.addSpacing(12)
        row1.addWidget(QtWidgets.QLabel(_tr("bg_color")))
        self._btn_bg = QtWidgets.QPushButton("")
        self._btn_bg.setFixedSize(32, 20)
        self._update_bg_preview()
        self._btn_bg.clicked.connect(self._pick_bg)
        row1.addWidget(self._btn_bg)

        row1.addSpacing(12)
        row1.addWidget(QtWidgets.QLabel(_tr("btn_color")))
        self._btn_clr = QtWidgets.QPushButton("")
        self._btn_clr.setFixedSize(32, 20)
        self._update_btn_preview()
        self._btn_clr.clicked.connect(self._pick_btn)
        row1.addWidget(self._btn_clr)
        row1.addStretch()
        vlay.addLayout(row1)

        # ── 第二行：按钮透明度 + 图标透明度 ──
        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(QtWidgets.QLabel(_tr("btn_alpha")))
        self._slider_alpha = QtWidgets.QSlider(_qt(Qt, 'Horizontal', 'Orientation.Horizontal'))
        self._slider_alpha.setRange(30, 255)
        self._slider_alpha.setValue(_SETTINGS.get("btn_alpha", 255))
        self._slider_alpha.setFixedWidth(100)
        self._slider_alpha.setStyleSheet(
            "QSlider::groove:horizontal{background:#2a2a32;height:4px;border-radius:2px;}"
            "QSlider::handle:horizontal{background:#4a7fa5;width:12px;margin:-4px 0;border-radius:6px;}")
        self._slider_alpha.valueChanged.connect(self._on_alpha)
        row2.addWidget(self._slider_alpha)

        row2.addSpacing(12)
        row2.addWidget(QtWidgets.QLabel(_tr("icon_opacity")))
        self._slider_icon_op = QtWidgets.QSlider(_qt(Qt, 'Horizontal', 'Orientation.Horizontal'))
        self._slider_icon_op.setRange(10, 100)
        self._slider_icon_op.setValue(int(_SETTINGS.get("icon_opacity", 0.5) * 100))
        self._slider_icon_op.setFixedWidth(100)
        self._slider_icon_op.setStyleSheet(
            "QSlider::groove:horizontal{background:#2a2a32;height:4px;border-radius:2px;}"
            "QSlider::handle:horizontal{background:#4a7fa5;width:12px;margin:-4px 0;border-radius:6px;}")
        self._slider_icon_op.valueChanged.connect(self._on_icon_opacity)
        row2.addWidget(self._slider_icon_op)
        row2.addStretch()
        vlay.addLayout(row2)

        # ── 第三行：开关选项 ──
        row3 = QtWidgets.QHBoxLayout()
        row3.setSpacing(16)

        self._chk_x8_auto = QtWidgets.QCheckBox(_tr("chanai_tools_auto_start"))
        self._chk_x8_auto.setChecked(_SETTINGS.get("chanai_tools_auto_start", False))
        self._chk_x8_auto.stateChanged.connect(self._on_chanai_tools_auto_start)
        row3.addWidget(self._chk_x8_auto)

        self._chk_qstyle = QtWidgets.QCheckBox(_tr("qt_style"))
        self._chk_qstyle.setChecked(_tb_qstyle_is_enabled(default=True))
        self._chk_qstyle.stateChanged.connect(self._on_qstyle)
        row3.addWidget(self._chk_qstyle)

        row3.addStretch()
        vlay.addLayout(row3)

        # ── 第四行：保存提醒 + 间隔设置 ──
        row4 = QtWidgets.QHBoxLayout()
        row4.setSpacing(8)

        self._chk_save_reminder = QtWidgets.QCheckBox(_tr("save_reminder"))
        self._chk_save_reminder.setChecked(_tb_get_save_reminder_enabled())
        self._chk_save_reminder.stateChanged.connect(self._on_save_reminder)
        self._save_service_exists = os.path.isfile(_tb_save_reminder_service_file())
        if not self._save_service_exists:
            self._chk_save_reminder.setEnabled(False)
            self._chk_save_reminder.setToolTip(u"未找到 x8 的保存提醒服务文件")
        row4.addWidget(self._chk_save_reminder)

        row4.addSpacing(8)
        row4.addWidget(QtWidgets.QLabel(_tr("save_interval_min")))
        self._spin_save_interval = QtWidgets.QSpinBox()
        self._spin_save_interval.setRange(1, 999)
        self._spin_save_interval.setValue(_tb_get_save_reminder_interval_min())
        self._spin_save_interval.setFixedWidth(56)
        self._spin_save_interval.valueChanged.connect(self._on_save_interval_min)
        row4.addWidget(self._spin_save_interval)

        if not self._save_service_exists:
            self._spin_save_interval.setEnabled(False)

        self._set_save_minute_widgets_enabled(bool(self._chk_save_reminder.isChecked()))

        row4.addStretch()
        vlay.addLayout(row4)

        # ── 分隔线 ──
        vlay.addSpacing(4)
        separator = QtWidgets.QFrame()
        separator.setFrameShape(_qt(QtWidgets.QFrame, 'HLine', 'Shape.HLine'))
        separator.setStyleSheet("background:#3a3a44;")
        separator.setFixedHeight(1)
        vlay.addWidget(separator)
        vlay.addSpacing(4)

        # ── 操作按钮行 ──
        button_row = QtWidgets.QHBoxLayout()
        button_row.setSpacing(8)

        btn_lang = QtWidgets.QPushButton(_tr("language"))
        btn_lang.setFixedSize(80, 28)
        btn_lang.clicked.connect(self._toggle_lang)
        button_row.addWidget(btn_lang)

        btn_reset = QtWidgets.QPushButton(_tr("reset"))
        btn_reset.setFixedSize(80, 28)
        btn_reset.setStyleSheet(
            "QPushButton{background:#553333; color:#ddd; border:1px solid #855; "
            "border-radius:4px; padding:2px 6px; font-size:11px;}"
            "QPushButton:hover{background:#7a4444;}")
        btn_reset.clicked.connect(self._reset)
        button_row.addWidget(btn_reset)

        btn_camera_reset = QtWidgets.QPushButton(_tr("camera_reset"))
        btn_camera_reset.setFixedSize(90, 28)
        btn_camera_reset.setStyleSheet(
            "QPushButton{background:#335555; color:#ddd; border:1px solid #588; "
            "border-radius:4px; padding:2px 6px; font-size:11px;}"
            "QPushButton:hover{background:#447777;}")
        btn_camera_reset.clicked.connect(self._reset_camera)
        button_row.addWidget(btn_camera_reset)

        btn_uninstall = QtWidgets.QPushButton(_tr("uninstall"))
        btn_uninstall.setFixedSize(80, 28)
        btn_uninstall.setStyleSheet(
            "QPushButton{background:#6a2f2f; color:#f0dede; border:1px solid #a66565; "
            "border-radius:4px; padding:2px 6px; font-size:11px;}"
            "QPushButton:hover{background:#8a3b3b;}")
        btn_uninstall.clicked.connect(self._uninstall_toolbox)
        button_row.addWidget(btn_uninstall)

        button_row.addStretch()
        vlay.addLayout(button_row)

        vlay.addStretch()

    # ── 回调 ──────────────────────────────────────────────────
    def _on_font(self, val):
        _SETTINGS["font_size"] = val
        _save_settings(_SETTINGS)
        self._notify()

    def _on_alpha(self, val):
        _SETTINGS["btn_alpha"] = val
        _save_settings(_SETTINGS)
        self._notify()

    def _on_icon_opacity(self, val):
        _SETTINGS["icon_opacity"] = val / 100.0
        _save_settings(_SETTINGS)
        # 实时更新图标
        if self._panel and self._panel._icon_ref:
            ico = self._panel._icon_ref
            if not ico._pinned:
                ico._opacity = val / 100.0
                ico.update()

    def _on_chanai_tools_auto_start(self, state):
        """早茶奈工具箱自动启动开关"""
        _SETTINGS["chanai_tools_auto_start"] = bool(state)
        _save_settings(_SETTINGS)
        try:
            user_setup = _set_autostart_usersetup(bool(state))
        except Exception as e:
            user_setup = None
            print("[ChanaiTools] 更新 userSetup 失败: " + str(e))
        try:
            import maya.cmds as cmds
            if state:
                tip = u"已启用自动启动，下次打开Maya时生效"
                if user_setup:
                    tip += u"\\nuserSetup: " + user_setup.replace("\\", "/")
                cmds.inViewMessage(amg=u"<hl>%s</hl>" % tip, pos='midCenter', fade=True)
            else:
                tip = u"已关闭自动启动"
                if user_setup:
                    tip += u"\\nuserSetup: " + user_setup.replace("\\", "/")
                cmds.inViewMessage(amg=u"<hl>%s</hl>" % tip, pos='midCenter', fade=True)
        except Exception:
            pass

    def _on_qstyle(self, state):
        _SETTINGS["qt_style"] = bool(state)
        _save_settings(_SETTINGS)
        if self._panel:
            try:
                self._panel._apply_qstyle()
                self._panel.update()
            except Exception:
                pass

    def _on_save_reminder(self, state):
        enabled = bool(state)
        _tb_set_save_reminder_enabled(enabled)
        ok = _tb_apply_save_reminder_state(enabled)
        self._set_save_minute_widgets_enabled(enabled)
        try:
            import maya.cmds as cmds
            if ok:
                tip = u"自动保存提醒已%s" % (u"开启" if enabled else u"关闭")
            else:
                tip = u"保存提醒服务不可用（仅写入开关）"
            cmds.inViewMessage(amg=u"<hl>%s</hl>" % tip, pos='midCenter', fade=True)
        except Exception:
            pass

    def _set_save_minute_widgets_enabled(self, enabled):
        on = bool(enabled) and bool(getattr(self, "_save_service_exists", False))
        try:
            self._spin_save_interval.setEnabled(on)
        except Exception:
            pass

    def _on_save_interval_min(self, val):
        _tb_set_save_reminder_interval_min(val)
        if _tb_get_save_reminder_enabled():
            _tb_apply_save_reminder_state(True)

    def _pick_bg(self):
        cur = _color_from_list(_SETTINGS.get("bg_color", [28,28,32]))
        c = QtWidgets.QColorDialog.getColor(cur, self, _tr("bg_color"))
        if c.isValid():
            _SETTINGS["bg_color"] = [c.red(), c.green(), c.blue()]
            _save_settings(_SETTINGS)
            self._update_bg_preview()
            self._notify()

    def _pick_btn(self):
        cur = _color_from_list(_SETTINGS.get("btn_color", [52,55,62]))
        c = QtWidgets.QColorDialog.getColor(cur, self, _tr("btn_color"))
        if c.isValid():
            _SETTINGS["btn_color"] = [c.red(), c.green(), c.blue()]
            _save_settings(_SETTINGS)
            self._update_btn_preview()
            self._notify()

    def _toggle_lang(self):
        cur = _SETTINGS.get("language", "CN")
        _SETTINGS["language"] = "EN" if cur == "CN" else "CN"
        _save_settings(_SETTINGS)
        # 需要重建面板 UI 来刷新所有文本
        if self._panel:
            self._panel._rebuild_ui()

    def _reset(self):
        _SETTINGS.update(dict(_DEFAULT_SETTINGS))
        _save_settings(_SETTINGS)
        self._spin_font.setValue(_SETTINGS["font_size"])
        self._slider_alpha.setValue(_SETTINGS.get("btn_alpha", 255))
        self._slider_icon_op.setValue(
            int(_SETTINGS.get("icon_opacity", 0.5) * 100))
        self._chk_x8_auto.setChecked(_SETTINGS.get("chanai_tools_auto_start", False))
        self._chk_qstyle.setChecked(_tb_qstyle_is_enabled(default=True))
        self._chk_save_reminder.setChecked(False)
        _tb_set_save_reminder_interval_min(5)
        self._spin_save_interval.setValue(_tb_get_save_reminder_interval_min())
        self._update_bg_preview()
        self._update_btn_preview()
        if self._panel:
            self._panel._rebuild_ui()

    def _reset_camera(self):
        """重置 ADV 视图摄影机状态并恢复默认视角。"""
        try:
            import maya.cmds as cmds
            panel = cmds.getPanel(withFocus=True)
            if cmds.getPanel(typeOf=panel) != 'modelPanel':
                panels = cmds.getPanel(type='modelPanel') or []
                panel = panels[0] if panels else ""

            def _as_cam_transform(node):
                try:
                    n = str(node or "")
                    if not n or (not cmds.objExists(n)):
                        return ""
                    if cmds.nodeType(n) == "camera":
                        p = cmds.listRelatives(n, parent=True, fullPath=True) or []
                        return str(p[0]) if p else ""
                    return n
                except Exception:
                    return ""

            def _adv_fast_select_path():
                cands = []
                try:
                    if cmds.optionVar(exists='ADV_FastSelectScriptPath'):
                        p = cmds.optionVar(q='ADV_FastSelectScriptPath') or ''
                        if p and os.path.isfile(p):
                            cands.append(os.path.normpath(p))
                except Exception:
                    pass

                root_scripts = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", ".."))
                cands.append(os.path.normpath(os.path.join(root_scripts, "ADV Fast select 2 (2)", "ADV_fast_select.py")))
                cands.append(os.path.normpath(os.path.join(root_scripts, "ADV Fast select 2", "ADV_fast_select.py")))
                cands.append(os.path.normpath(os.path.join(root_scripts, "ADV Fast select", "ADV_fast_select.py")))

                try:
                    for d in os.listdir(root_scripts):
                        dl = str(d).lower()
                        if "adv fast select" not in dl:
                            continue
                        p = os.path.normpath(os.path.join(root_scripts, d, "ADV_fast_select.py"))
                        if os.path.isfile(p):
                            cands.append(p)
                except Exception:
                    pass

                seen = set()
                for p in cands:
                    pp = os.path.normcase(os.path.normpath(str(p)))
                    if pp in seen:
                        continue
                    seen.add(pp)
                    if os.path.isfile(p):
                        return p
                return ""

            # 1) 优先走 ADV 原生重置：会删除 ADV view/temp camera 并清理 optionVar。
            reset_by_adv = False
            try:
                adv_path = _adv_fast_select_path()
                if adv_path:
                    adv_mod = _tb_find_loaded_module_by_file(adv_path)
                    if adv_mod is None:
                        mname = "chanai_tools_tb__adv_fast_select_camera"
                        if mname in sys.modules:
                            adv_mod = _tb_reload_module(sys.modules[mname])
                        else:
                            adv_mod = _tb_load_module_from_file(mname, adv_path)

                    fn = getattr(adv_mod, "adv_ui_camera_reset", None) if adv_mod else None
                    if callable(fn):
                        fn()
                        reset_by_adv = True
            except Exception:
                reset_by_adv = False

            # 2) 兜底：本地清理 ADV 摄影机并重建默认相机姿态。
            if not reset_by_adv:
                temp_cam = ""
                try:
                    if cmds.optionVar(exists='ADV_SeamlessViewSwitchTempPerspCamera'):
                        temp_cam = _as_cam_transform(cmds.optionVar(q='ADV_SeamlessViewSwitchTempPerspCamera'))
                except Exception:
                    temp_cam = ""

                default_cams = set(["persp", "top", "front", "side", "back", "left", "bottom"])
                delete_list = []
                for shp in (cmds.ls(type='camera') or []):
                    tr = _as_cam_transform(shp)
                    if not tr:
                        continue
                    leaf = tr.split("|")[-1]
                    if leaf in default_cams:
                        continue
                    should_delete = False
                    try:
                        if leaf.startswith("ADV_View_"):
                            should_delete = True
                    except Exception:
                        pass
                    try:
                        if cmds.attributeQuery("advViewCamera", node=tr, exists=True):
                            should_delete = True
                    except Exception:
                        pass
                    if temp_cam and (tr == temp_cam):
                        should_delete = True
                    if should_delete:
                        delete_list.append(tr)

                # 先把所有视图面板切回 persp，避免正在看的 camera 被删除。
                try:
                    for p in (cmds.getPanel(type='modelPanel') or []):
                        try:
                            cam = _as_cam_transform(cmds.modelPanel(p, q=True, camera=True))
                            if (not cam) or (cam in delete_list):
                                cmds.modelPanel(p, e=True, camera='persp')
                        except Exception:
                            pass
                except Exception:
                    pass

                for tr in sorted(set([x for x in delete_list if x and cmds.objExists(x)])):
                    try:
                        cmds.delete(tr)
                    except Exception:
                        pass

                try:
                    for ov in (cmds.optionVar(list=True) or []):
                        ovn = str(ov or "")
                        if ovn.startswith("ADV_ViewCam_") and cmds.optionVar(exists=ovn):
                            cmds.optionVar(remove=ovn)
                except Exception:
                    pass
                try:
                    if cmds.optionVar(exists='ADV_SeamlessViewSwitchTempPerspCamera'):
                        cmds.optionVar(remove='ADV_SeamlessViewSwitchTempPerspCamera')
                except Exception:
                    pass

                def _safe_set_attr(attr_name, value):
                    try:
                        if cmds.getAttr(attr_name, lock=True):
                            try:
                                cmds.setAttr(attr_name, lock=False)
                            except Exception:
                                return
                        cmds.setAttr(attr_name, value)
                    except Exception:
                        pass

                def _ensure_default_camera(name, orthographic=False):
                    tr = ""
                    try:
                        if cmds.objExists(name):
                            if cmds.nodeType(name) == "transform":
                                sh = cmds.listRelatives(name, shapes=True, type='camera', fullPath=True) or []
                                if sh:
                                    tr = name
                                else:
                                    try:
                                        cmds.delete(name)
                                    except Exception:
                                        pass
                            elif cmds.nodeType(name) == "camera":
                                p = cmds.listRelatives(name, parent=True, fullPath=True) or []
                                if p:
                                    tr = p[0]
                            else:
                                try:
                                    cmds.delete(name)
                                except Exception:
                                    pass
                        if not tr:
                            created = cmds.camera(name=name, orthographic=bool(orthographic))
                            if isinstance(created, (list, tuple)) and created:
                                tr = created[0]
                            else:
                                tr = str(created)
                    except Exception:
                        tr = name if cmds.objExists(name) else ""
                    return tr

                # 重建并重置默认摄像机姿态
                persp_tr = _ensure_default_camera('persp', orthographic=False)
                front_tr = _ensure_default_camera('front', orthographic=True)
                side_tr = _ensure_default_camera('side', orthographic=True)
                top_tr = _ensure_default_camera('top', orthographic=True)

                if persp_tr and cmds.objExists(persp_tr):
                    _safe_set_attr(persp_tr + '.translateX', 28.0)
                    _safe_set_attr(persp_tr + '.translateY', 21.0)
                    _safe_set_attr(persp_tr + '.translateZ', 28.0)
                    _safe_set_attr(persp_tr + '.rotateX', -27.938)
                    _safe_set_attr(persp_tr + '.rotateY', 45.0)
                    _safe_set_attr(persp_tr + '.rotateZ', 0.0)
                if front_tr and cmds.objExists(front_tr):
                    _safe_set_attr(front_tr + '.translateX', 0.0)
                    _safe_set_attr(front_tr + '.translateY', 0.0)
                    _safe_set_attr(front_tr + '.translateZ', 1000.1)
                    _safe_set_attr(front_tr + '.rotateX', 0.0)
                    _safe_set_attr(front_tr + '.rotateY', 0.0)
                    _safe_set_attr(front_tr + '.rotateZ', 0.0)
                if side_tr and cmds.objExists(side_tr):
                    _safe_set_attr(side_tr + '.translateX', 1000.1)
                    _safe_set_attr(side_tr + '.translateY', 0.0)
                    _safe_set_attr(side_tr + '.translateZ', 0.0)
                    _safe_set_attr(side_tr + '.rotateX', 0.0)
                    _safe_set_attr(side_tr + '.rotateY', 90.0)
                    _safe_set_attr(side_tr + '.rotateZ', 0.0)
                if top_tr and cmds.objExists(top_tr):
                    _safe_set_attr(top_tr + '.translateX', 0.0)
                    _safe_set_attr(top_tr + '.translateY', 1000.1)
                    _safe_set_attr(top_tr + '.translateZ', 0.0)
                    _safe_set_attr(top_tr + '.rotateX', -90.0)
                    _safe_set_attr(top_tr + '.rotateY', 0.0)
                    _safe_set_attr(top_tr + '.rotateZ', 0.0)

                # 保障正交参数正确
                for cam in (front_tr, side_tr, top_tr):
                    try:
                        if not cam:
                            continue
                        shape = cmds.listRelatives(cam, shapes=True, type='camera', fullPath=True) or []
                        if not shape:
                            continue
                        shp = shape[0]
                        _safe_set_attr(shp + '.orthographic', 1)
                        _safe_set_attr(shp + '.orthographicWidth', 30.0)
                    except Exception:
                        pass

            # 最后切回当前面板的 persp
            try:
                if panel and cmds.getPanel(typeOf=panel) == 'modelPanel':
                    cmds.modelPanel(panel, edit=True, camera='persp')
            except Exception:
                pass

            cmds.inViewMessage(
                amg=u'<span style="color:#4a7fa5;">%s</span>' % (_tr("camera_reset") + u' 完成'),
                pos='topCenter',
                fade=True,
                fadeStayTime=1200
            )
        except Exception as e:
            print("[ChanaiTools] Reset camera failed: " + str(e))

    def _uninstall_toolbox(self):
        """卸载早茶奈工具箱（清理按钮、配置、用户脚本目录中的相关文件）。"""
        try:
            title = u"卸载确认"
            msg = (
                u"将执行卸载：\n"
                u"1) 删除 Shelf 上的 Chanai 按钮\n"
                u"2) 清理本工具配置文件\n"
                u"3) 清理 Maya 用户 scripts 目录中的早茶奈相关文件\n\n"
                u"此操作不可撤销，是否继续？"
            )
            ans = QtWidgets.QMessageBox.question(
                self, title, msg,
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )
            if ans != QtWidgets.QMessageBox.Yes:
                return
        except Exception:
            pass

        removed = []
        failed = []

        def _try_remove_path(p):
            if not p:
                return
            pp = os.path.normpath(p)
            if not os.path.exists(pp):
                return
            try:
                if os.path.isdir(pp):
                    shutil.rmtree(pp)
                else:
                    os.remove(pp)
                removed.append(pp)
            except Exception as e:
                failed.append((pp, str(e)))

        # 1) 删除 shelf 按钮并保存 shelf
        try:
            import maya.cmds as cmds
            buttons = cmds.lsUI(type='shelfButton') or []
            for b in buttons:
                try:
                    ann = cmds.shelfButton(b, q=True, annotation=True) or ""
                    lab = cmds.shelfButton(b, q=True, label=True) or ""
                    cmd = cmds.shelfButton(b, q=True, command=True) or ""
                except Exception:
                    continue
                if (
                    b == "chanaiToolsShelfBtn"
                    or "Chanai Toolbox" in ann
                    or "chanaiToolsLaunch" in cmd
                    or "chanai_toolbox.main" in cmd
                    or lab in ("Chanai", "早茶奈")
                ):
                    try:
                        cmds.deleteUI(b)
                        removed.append("shelfButton:" + b)
                    except Exception as e:
                        failed.append(("shelfButton:" + b, str(e)))
            try:
                import maya.mel as mel
                mel.eval('saveAllShelves $gShelfTopLevel;')
            except Exception:
                pass
        except Exception as e:
            failed.append(("shelf cleanup", str(e)))

        # 2) 清理本工具配置文件（仅配置，不删除当前代码仓库）
        for p in (_SETTINGS_FILE, _CUSTOM_CFG, _ORDER_FILE, _REMOVED_TOOLS_FILE):
            _try_remove_path(p)

        # 3) 清理 Maya 用户 scripts 目录中的相关文件/目录
        try:
            import maya.cmds as cmds
            user_scripts = cmds.internalVar(userScriptDir=True) or ""
            user_scripts = os.path.normpath(user_scripts)
        except Exception:
            user_scripts = ""

        if user_scripts and os.path.isdir(user_scripts):
            file_candidates = [
                os.path.join(user_scripts, "chanai_toolbox.py"),
                os.path.join(user_scripts, "启动工具箱.py"),
                os.path.join(user_scripts, "install.mel"),
            ]
            for p in file_candidates:
                _try_remove_path(p)

            # 若 userSetup.py 含本工具标记，则删除；否则尝试仅清理相关行。
            user_setup = os.path.join(user_scripts, "userSetup.py")
            if os.path.exists(user_setup):
                try:
                    with _io_open(user_setup, "r", encoding="utf-8") as fh:
                        txt = fh.read()
                except Exception:
                    txt = ""
                markers = (
                    u"早茶奈工具箱自动启动脚本",
                    "chanai_toolbox",
                    "ChanaiTools",
                )
                if any(m in txt for m in markers):
                    try:
                        # 若是专用安装脚本，直接删除；否则剔除相关行后回写
                        if u"早茶奈工具箱自动启动脚本" in txt and "chanai_toolbox" in txt:
                            os.remove(user_setup)
                            removed.append(user_setup)
                        else:
                            lines = txt.splitlines(True)
                            new_lines = []
                            changed = False
                            for ln in lines:
                                if (
                                    "chanai_toolbox" in ln
                                    or u"早茶奈工具箱" in ln
                                    or "ChanaiTools" in ln
                                ):
                                    changed = True
                                    continue
                                new_lines.append(ln)
                            if changed:
                                with _io_open(user_setup, "w", encoding="utf-8") as fh:
                                    fh.writelines(new_lines)
                                removed.append(user_setup + " (cleaned)")
                    except Exception as e:
                        failed.append((user_setup, str(e)))

            dir_candidates = [
                os.path.join(user_scripts, "Chanai_Tools"),
            ]
            for d in dir_candidates:
                _try_remove_path(d)

        # 4) 尝试关闭当前运行中的图标/面板
        try:
            try:
                import builtins as _b
            except ImportError:
                import __builtin__ as _b
            ico = _b.__dict__.get(_KEY)
            if ico is not None:
                try:
                    ico._quit()
                except Exception:
                    try:
                        ico.close()
                    except Exception:
                        pass
            _b.__dict__.pop(_KEY, None)
        except Exception:
            pass

        # 5) 清理模块缓存
        try:
            for k in list(sys.modules.keys()):
                lk = str(k).lower()
                if lk.startswith("chanai_toolbox"):
                    sys.modules.pop(k, None)
        except Exception:
            pass

        # 结果提示
        try:
            if failed:
                msg = u"卸载完成（部分失败）\n成功: %d\n失败: %d\n\n请重启 Maya 完成清理。" % (len(removed), len(failed))
                QtWidgets.QMessageBox.warning(self, u"卸载结果", msg)
            else:
                msg = u"卸载完成，共清理 %d 项。\n请重启 Maya。" % len(removed)
                QtWidgets.QMessageBox.information(self, u"卸载结果", msg)
        except Exception:
            pass

    def _update_camera_status(self):
        """更新摄像机状态显示"""
        try:
            # 检查label是否还存在
            if not hasattr(self, '_camera_name_label') or not hasattr(self, '_camera_proj_label'):
                return
            if not self._camera_name_label or not self._camera_proj_label:
                return

            import maya.cmds as cmds

            # 获取当前活动面板
            panel = cmds.getPanel(withFocus=True)
            if not panel or not cmds.getPanel(typeOf=panel) == 'modelPanel':
                panels = cmds.getPanel(type='modelPanel')
                if panels:
                    panel = panels[0]
                else:
                    return

            # 获取当前摄像机
            camera = cmds.modelPanel(panel, q=True, camera=True)
            if camera and cmds.objExists(camera):
                # 如果是shape节点，获取transform节点
                if cmds.nodeType(camera) == 'camera':
                    parents = cmds.listRelatives(camera, parent=True, fullPath=True)
                    if parents:
                        camera = parents[0]

                # 显示短名称
                camera_short = camera.split('|')[-1]
                self._camera_name_label.setText(camera_short)

                # 获取投影类型
                camera_shape = camera
                if cmds.nodeType(camera) != 'camera':
                    shapes = cmds.listRelatives(camera, shapes=True, type='camera')
                    if shapes:
                        camera_shape = shapes[0]

                if camera_shape and cmds.objExists(camera_shape):
                    is_ortho = cmds.getAttr(camera_shape + '.orthographic')
                    if is_ortho:
                        self._camera_proj_label.setText(_tr("camera_proj_ortho"))
                    else:
                        self._camera_proj_label.setText(_tr("camera_proj_persp"))
        except RuntimeError:
            # UI已被删除，停止定时器
            if hasattr(self, '_camera_timer') and self._camera_timer:
                try:
                    self._camera_timer.stop()
                except:
                    pass
        except Exception:
            pass

    def _notify(self):
        self.settingsChanged.emit()
        if self._panel:
            self._panel.update()

    # ── 颜色预览 ──────────────────────────────────────────────
    def _update_bg_preview(self):
        c = _SETTINGS.get("bg_color", [28,28,32])
        self._btn_bg.setStyleSheet(
            "QPushButton{background:rgb(%d,%d,%d); border:1px solid #888; border-radius:4px;}"
            "QPushButton:hover{border:2px solid #aaa;}" % (c[0], c[1], c[2]))

    def _update_btn_preview(self):
        c = _SETTINGS.get("btn_color", [52,55,62])
        self._btn_clr.setStyleSheet(
            "QPushButton{background:rgb(%d,%d,%d); border:1px solid #888; border-radius:4px;}"
            "QPushButton:hover{border:2px solid #aaa;}" % (c[0], c[1], c[2]))



class ChanaiToolsPanel(QtWidgets.QWidget):
    """主工具面板：自绘背景+标题栏+Tab，支持滑入/滑出动画"""

    OBJ = "ChanaiToolsPanelMain_v2"
    SLIDE_MS = 200   # 滑动动画时长

    def __init__(self, parent=None):
        super(ChanaiToolsPanel, self).__init__(
            parent, _Tool | _Frameless)
        self.setObjectName(self.OBJ)
        self.setAttribute(_WA_Translucent)
        self.setFixedWidth(530)
        self._drag = None
        self._icon_ref = None   # 由 icon 设置，拖动面板时同步图标
        self._panel_opacity = 0.0

        # 滑动动画 —— 驱动 windowOpacity
        self._slide_anim = QPropertyAnimation(self, b"panelOpacity")
        self._slide_anim.setDuration(self.SLIDE_MS)
        self._slide_anim.setEasingCurve(_OutCubic)

        self._build()

    # ── opacity 属性 ─────────────────────────────────────────
    def _get_pop(self): return self._panel_opacity
    def _set_pop(self, v):
        self._panel_opacity = v
        self.setWindowOpacity(v)
    panelOpacity = Property(float, _get_pop, _set_pop)

    def show_slide(self, px, py):
        """带淡入动画显示在 (px, py)"""
        self._slide_anim.stop()
        try: self._slide_anim.finished.disconnect()
        except Exception: pass
        self.move(px, py)
        self.setWindowOpacity(0.0)
        self._panel_opacity = 0.0
        self.show()
        self.raise_()
        self._slide_anim.setStartValue(0.0)
        self._slide_anim.setEndValue(1.0)
        self._slide_anim.start()

    def hide_slide(self):
        """带淡出动画隐藏"""
        if not self.isVisible():
            return
        self._slide_anim.stop()
        try: self._slide_anim.finished.disconnect()
        except Exception: pass
        self._slide_anim.setStartValue(self._panel_opacity)
        self._slide_anim.setEndValue(0.0)
        self._slide_anim.finished.connect(self._after_hide)
        self._slide_anim.start()

    def _after_hide(self):
        try: self._slide_anim.finished.disconnect(self._after_hide)
        except Exception: pass
        self.hide()

    # ── 构建 UI ─────────────────────────────────────────────
    def _build(self):
        vlay = QtWidgets.QVBoxLayout(self)
        vlay.setContentsMargins(8, 8, 8, 8)
        vlay.setSpacing(0)
        vlay.addWidget(self._make_title())
        self._tabs = QtWidgets.QTabWidget()
        self._tabs.setStyleSheet(_TAB_STYLE)
        vlay.addWidget(self._tabs)
        self._fill_tabs()

        # 底部帧数和速率控制
        vlay.addWidget(self._make_playback_controls())
        self._apply_qstyle()

    def _apply_qstyle(self):
        enabled = _tb_qstyle_is_enabled(default=True)
        try:
            self.setStyleSheet(_PANEL_QSTYLE_SHEET if enabled else "")
        except Exception:
            pass
        try:
            if hasattr(self, '_tabs') and self._tabs:
                self._tabs.setStyleSheet(_TAB_STYLE if enabled else "")
        except Exception:
            pass

    def _make_title(self):
        w = QtWidgets.QWidget()
        w.setFixedHeight(38)
        h = QtWidgets.QHBoxLayout(w)
        # 增加右侧留白，避免刷新按钮贴近关闭按钮和窗口边缘看不清
        h.setContentsMargins(14, 0, 16, 0)

        lbl = QtWidgets.QLabel(_tr("title"))
        lbl.setStyleSheet(
            "color:#88ccee; font-size:13px; font-weight:bold;")
        lbl.setCursor(_PointingHand)
        lbl.setToolTip("https://space.bilibili.com/101677535")
        lbl.mousePressEvent = lambda e: webbrowser.open(
            "https://space.bilibili.com/101677535?spm_id_from=333.1365.0.0")
        h.addWidget(lbl)

        date_lbl = QtWidgets.QLabel(_today_cn_text())
        date_lbl.setStyleSheet("color:#6f7480; font-size:11px;")
        h.addSpacing(8)
        h.addWidget(date_lbl)

        h.addStretch()

        # 刷新按钮
        refresh_btn = QtWidgets.QPushButton(u"\u21bb")  # ↻ 循环箭头
        refresh_btn.setFixedSize(22, 22)
        refresh_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#666;border:none;font-size:16px;}"
            "QPushButton:hover{color:#88ccee;}")
        refresh_btn.setToolTip(_tr("refresh_ui"))
        refresh_btn.clicked.connect(self._refresh_ui)
        h.addWidget(refresh_btn)
        h.addSpacing(6)

        # 关闭按钮
        btn = QtWidgets.QPushButton(u"\u2715")
        btn.setFixedSize(22, 22)
        btn.setStyleSheet(
            "QPushButton{background:transparent;color:#666;border:none;font-size:13px;}"
            "QPushButton:hover{color:#e06060;}")
        btn.clicked.connect(self.hide_slide)
        h.addWidget(btn)

        # 拖动（兼容 PySide2/PySide6 globalPos 差异）
        def _title_press(e):
            if e.button() == _LeftButton:
                self._drag = _global_pos(e) - self.frameGeometry().topLeft()
        def _title_move(e):
            if self._drag and e.buttons() & _LeftButton:
                self.move(_global_pos(e) - self._drag)
                # 面板拖动时图标也跟随
                if self._icon_ref:
                    self._icon_ref._sync_icon_to_panel()
        def _title_release(e):
            self._drag = None
        w.mousePressEvent   = _title_press
        w.mouseMoveEvent    = _title_move
        w.mouseReleaseEvent = _title_release
        return w

    def _fill_tabs(self):
        # 默认工具（按持久化顺序）
        ordered = _get_ordered_tools()
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(_ScrollOff)
        scroll.setWidget(GridPage(ordered))
        self._tabs.addTab(scroll, _tr("default_tools"))

        # ── 自定义工具 Tab ──
        cscroll = QtWidgets.QScrollArea()
        cscroll.setWidgetResizable(True)
        cscroll.setHorizontalScrollBarPolicy(_ScrollOff)
        cscroll.setWidget(CustomToolPage())
        self._tabs.addTab(cscroll, _tr("custom_tools"))

        # ── 设置 Tab ──
        sscroll = QtWidgets.QScrollArea()
        sscroll.setWidgetResizable(True)
        sscroll.setHorizontalScrollBarPolicy(_ScrollOff)
        sp = SettingsPage(self)
        sp.settingsChanged.connect(self._on_settings_changed)
        sscroll.setWidget(sp)
        self._tabs.addTab(sscroll, _tr("settings"))

    def _make_playback_controls(self):
        """创建底部播放速率和帧率控制按钮"""
        try:
            import maya.cmds as cmds
        except:
            return QtWidgets.QWidget()  # Maya 不可用时返回空控件

        w = QtWidgets.QWidget()
        w.setFixedHeight(32)
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(8, 3, 8, 3)
        lay.setSpacing(3)

        # 按钮样式 - 文本样式，悬停高亮，更紧凑
        btn_style = """
            QPushButton {
                background:transparent;
                color:#aaa;
                border:none;
                font-size:9px;
                text-align:left;
                padding:1px 3px;
            }
            QPushButton:hover {
                color:#4a7fa5;
            }
            QPushButton::menu-indicator {
                width:0px;
            }
        """

        # 辅助函数
        def _timeunit_to_fps(token):
            try:
                t = str(token or '').strip().lower()
                if t.endswith('fps'):
                    return float(t[:-3])
                mapping = {'game': 15.0, 'film': 24.0, 'pal': 25.0, 'ntsc': 30.0,
                          'show': 48.0, 'palf': 50.0, 'ntscf': 60.0}
                return float(mapping.get(t, 24.0))
            except:
                return 24.0

        def _fps_to_timeunit(fps):
            try:
                f = float(fps)
                mapping = {15.0: 'game', 24.0: 'film', 25.0: 'pal', 30.0: 'ntsc',
                          48.0: 'show', 50.0: 'palf', 60.0: 'ntscf'}
                for k, v in mapping.items():
                    if abs(float(k) - float(f)) < 1e-3:
                        return v
                return "%dfps" % int(round(float(f)))
            except:
                return "film"

        def _get_playback_speed():
            try:
                return max(0.1, min(20.0, float(cmds.playbackOptions(q=True, playbackSpeed=True))))
            except:
                return 1.0

        def _get_base_fps():
            try:
                return _timeunit_to_fps(cmds.currentUnit(q=True, time=True))
            except:
                return 24.0

        def _get_angle_unit():
            try:
                return cmds.currentUnit(q=True, angle=True)
            except:
                return "deg"

        def _get_linear_unit():
            try:
                return cmds.currentUnit(q=True, linear=True)
            except:
                return "cm"

        # 播放速率按钮（左侧开始）
        speed_btn = QtWidgets.QPushButton()
        speed_btn.setFixedHeight(22)
        speed_btn.setStyleSheet(btn_style)

        def _update_speed_btn():
            speed = _get_playback_speed()
            speed_btn.setText(u"速率:%.2fx" % speed)

        _update_speed_btn()

        speed_menu = QtWidgets.QMenu(speed_btn)
        speed_options = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]

        def _set_speed(s):
            try:
                cmds.playbackOptions(e=True, playbackSpeed=float(s))
                _update_speed_btn()
            except:
                pass

        for speed in speed_options:
            action = speed_menu.addAction("%.2fx" % speed)
            action.triggered.connect(lambda checked=False, s=speed: _set_speed(s))

        speed_btn.setMenu(speed_menu)
        lay.addWidget(speed_btn)

        # 帧率按钮
        fps_btn = QtWidgets.QPushButton()
        fps_btn.setFixedHeight(22)
        fps_btn.setStyleSheet(btn_style)

        def _update_fps_btn():
            fps = _get_base_fps()
            fps_btn.setText(u"帧率:%dfps" % int(fps))

        _update_fps_btn()

        fps_menu = QtWidgets.QMenu(fps_btn)
        fps_options = [12, 15, 24, 25, 30, 48, 50, 60, 120]

        def _set_fps(f):
            try:
                cmds.currentUnit(time=str(_fps_to_timeunit(f)))
                cmds.refresh()
                _update_fps_btn()
            except:
                pass

        for fps in fps_options:
            action = fps_menu.addAction("%dfps" % int(fps))
            action.triggered.connect(lambda checked=False, f=fps: _set_fps(f))

        fps_btn.setMenu(fps_menu)
        lay.addWidget(fps_btn)

        # 角度按钮
        angle_btn = QtWidgets.QPushButton()
        angle_btn.setFixedHeight(22)
        angle_btn.setStyleSheet(btn_style)

        def _update_angle_btn():
            unit = _get_angle_unit()
            angle_btn.setText(u"角度:%s" % unit)

        _update_angle_btn()

        angle_menu = QtWidgets.QMenu(angle_btn)
        angle_options = [("deg", u"度"), ("rad", u"弧度")]

        def _set_angle(unit):
            try:
                cmds.currentUnit(angle=unit)
                _update_angle_btn()
            except:
                pass

        for unit, label in angle_options:
            action = angle_menu.addAction(label)
            action.triggered.connect(lambda checked=False, u=unit: _set_angle(u))

        angle_btn.setMenu(angle_menu)
        lay.addWidget(angle_btn)

        # 单位按钮
        unit_btn = QtWidgets.QPushButton()
        unit_btn.setFixedHeight(22)
        unit_btn.setStyleSheet(btn_style)

        def _update_unit_btn():
            unit = _get_linear_unit()
            unit_btn.setText(u"单位:%s" % unit)

        _update_unit_btn()

        unit_menu = QtWidgets.QMenu(unit_btn)
        unit_options = [("mm", "mm"), ("cm", "cm"), ("m", "m"), ("km", "km"),
                       ("in", "in"), ("ft", "ft"), ("yd", "yd"), ("mi", "mi")]

        def _set_unit(unit):
            try:
                cmds.currentUnit(linear=unit)
                _update_unit_btn()
            except:
                pass

        for unit, label in unit_options:
            action = unit_menu.addAction(label)
            action.triggered.connect(lambda checked=False, u=unit: _set_unit(u))

        unit_btn.setMenu(unit_menu)
        lay.addWidget(unit_btn)

        # 右侧：摄像机状态显示
        lay.addSpacing(8)
        camera_label = QtWidgets.QLabel()
        camera_label.setStyleSheet("color:#aaa; font-size:9px;")
        lay.addWidget(camera_label)

        # 保存引用以便更新
        self._bottom_camera_label = camera_label

        # 启动摄像机状态更新定时器
        self._bottom_camera_timer = QtCore.QTimer()
        self._bottom_camera_timer.timeout.connect(lambda: self._update_bottom_camera_status(camera_label))
        self._bottom_camera_timer.start(500)  # 每500ms更新一次

        # 立即更新一次
        self._update_bottom_camera_status(camera_label)

        return w

    def _update_bottom_camera_status(self, label):
        """更新底部摄像机状态显示"""
        try:
            # 检查label是否还有效
            if not label or not hasattr(label, 'setText'):
                if hasattr(self, '_bottom_camera_timer') and self._bottom_camera_timer:
                    try:
                        self._bottom_camera_timer.stop()
                    except:
                        pass
                return

            import maya.cmds as cmds

            # 获取当前活动面板
            panel = cmds.getPanel(withFocus=True)
            if not panel or not cmds.getPanel(typeOf=panel) == 'modelPanel':
                panels = cmds.getPanel(type='modelPanel')
                if panels:
                    panel = panels[0]
                else:
                    label.setText(_tr("camera_status") + ": -")
                    return

            # 获取当前摄像机
            camera = cmds.modelPanel(panel, q=True, camera=True)
            if camera and cmds.objExists(camera):
                # 如果是shape节点，获取transform节点
                if cmds.nodeType(camera) == 'camera':
                    parents = cmds.listRelatives(camera, parent=True, fullPath=True)
                    if parents:
                        camera = parents[0]

                # 显示短名称
                camera_short = camera.split('|')[-1]

                # 获取投影类型
                camera_shape = camera
                if cmds.nodeType(camera) != 'camera':
                    shapes = cmds.listRelatives(camera, shapes=True, type='camera')
                    if shapes:
                        camera_shape = shapes[0]

                if camera_shape and cmds.objExists(camera_shape):
                    is_ortho = cmds.getAttr(camera_shape + '.orthographic')
                    proj_text = _tr("camera_proj_ortho") if is_ortho else _tr("camera_proj_persp")

                    # 格式：摄影机：persp  透视
                    label.setText(u"%s: %s  %s" % (_tr("camera_status"), camera_short, proj_text))
            else:
                label.setText(_tr("camera_status") + ": -")
        except RuntimeError:
            # QLabel已被删除，停止定时器
            try:
                if hasattr(self, '_bottom_camera_timer') and self._bottom_camera_timer:
                    self._bottom_camera_timer.stop()
            except:
                pass
        except Exception:
            pass

    def _on_settings_changed(self):
        """设置变化后刷新所有可见按钮"""
        self._apply_qstyle()
        self.update()   # 重绘面板背景
        # 让所有 ToolButton / _CustomSlotButton 重绘
        for btn in self.findChildren(QtWidgets.QWidget):
            if isinstance(btn, (ToolButton, _CustomSlotButton)):
                btn.update()

    def _refresh_ui(self):
        """刷新UI：重新加载自定义工具和默认工具"""
        try:
            # 记住当前 tab 索引
            cur = self._tabs.currentIndex()

            # 清空所有 tabs
            while self._tabs.count() > 0:
                self._tabs.removeTab(0)

            # 重新填充 tabs
            self._fill_tabs()

            # 恢复 tab 索引
            if cur < self._tabs.count():
                self._tabs.setCurrentIndex(cur)

            print("[ChanaiTools] UI refreshed successfully")
        except Exception:
            print("[ChanaiTools] Refresh failed:\n" + traceback.format_exc())

    def _rebuild_ui(self):
        """切换语言等需要重建全部 UI 时调用"""
        # 停止旧的定时器
        try:
            if hasattr(self, '_bottom_camera_timer'):
                self._bottom_camera_timer.stop()
                self._bottom_camera_timer.deleteLater()
        except:
            pass

        # 记住当前 tab 索引
        cur = self._tabs.currentIndex()
        # 删除旧布局内容
        lay = self.layout()
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        # 重建
        lay.addWidget(self._make_title())
        self._tabs = QtWidgets.QTabWidget()
        self._tabs.setStyleSheet(_TAB_STYLE)
        lay.addWidget(self._tabs)
        self._fill_tabs()

        # 重新创建底部控制栏
        lay.addWidget(self._make_playback_controls())

        if cur < self._tabs.count():
            self._tabs.setCurrentIndex(cur)
        self._apply_qstyle()

    # ── 自绘背景 ────────────────────────────────────────────
    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(_Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(_cur_bg())
        p.setPen(QtGui.QPen(_C_BORDER, 1))
        p.drawRoundedRect(rect, 10, 10)
        p.end()

    def __del__(self):
        """析构时停止定时器"""
        try:
            if hasattr(self, '_bottom_camera_timer') and self._bottom_camera_timer:
                self._bottom_camera_timer.stop()
        except:
            pass


# ═══════════════════════════════════════════════════════════════
#  悬浮图标（自绘，半透明动画）
# ═══════════════════════════════════════════════════════════════

class ChanaiToolsFloatIcon(QtWidgets.QWidget):
    """
    自绘悬浮图标 — 新交互:
      hover  : 面板淡入展开
      leave  : 面板淡出收起（固定模式下不收）
      click  : 切换固定 / 非固定状态
      right×2: 退出
    """

    OBJ  = "ChanaiToolsFloatIcon_v2"
    SIZE = 84   # 70 * 1.2 = 84 (放大20%)
    ICON_BASE = 55  # 42 * 1.3 ≈ 55（图标放大30%）

    # 延迟关闭面板（鼠标从图标移向面板时不会闪烁），单位 ms
    _LEAVE_DELAY_MS = 120

    def __init__(self, parent=None):
        super(ChanaiToolsFloatIcon, self).__init__(
            parent, _Tool | _Frameless)
        self.setObjectName(self.OBJ)
        self.setAttribute(_WA_Translucent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setMouseTracking(True)
        self.setCursor(_PointingHand)

        self._opacity  = _SETTINGS.get("icon_opacity", 0.5)
        self._scale    = 0.85
        self._pinned   = False   # True = 固定，不随移走收起
        self._drag_pos    = None
        self._was_dragged = False
        self._last_rclick = 0

        # 加载图标
        self._pixmap = None
        # 优先使用 Chanai.png，如果不存在则使用 x8_shelf.png
        if os.path.exists(_CHANAI_ICON):
            self._pixmap = QtGui.QPixmap(_CHANAI_ICON).scaled(
                self.ICON_BASE, self.ICON_BASE, _KeepAspect, _SmoothXform)
        elif os.path.exists(_X8_SHELF):
            self._pixmap = QtGui.QPixmap(_X8_SHELF).scaled(
                self.ICON_BASE, self.ICON_BASE, _KeepAspect, _SmoothXform)

        # 面板（延迟创建）
        self._panel = None

        # 图标透明度 / 缩放动画
        self._op_anim = QPropertyAnimation(self, b"iconOpacity")
        self._op_anim.setDuration(180)
        self._op_anim.setEasingCurve(_OutCubic)

        self._sc_anim = QPropertyAnimation(self, b"iconScale")
        self._sc_anim.setDuration(180)
        self._sc_anim.setEasingCurve(_OutBack)

        # 延迟隐藏定时器（避免鼠标从图标→面板时面板闪烁）
        self._hide_timer = QtCore.QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(self._LEAVE_DELAY_MS)
        self._hide_timer.timeout.connect(self._on_hide_timer)

    # ── Qt 属性 ─────────────────────────────────────────────
    def _get_op(self): return self._opacity
    def _set_op(self, v): self._opacity = v; self.update()
    iconOpacity = Property(float, _get_op, _set_op)

    def _get_sc(self): return self._scale
    def _set_sc(self, v): self._scale = v; self.update()
    iconScale = Property(float, _get_sc, _set_sc)

    # ── 图标动画 ────────────────────────────────────────────
    def _animate_icon_in(self):
        self._op_anim.stop()
        self._op_anim.setStartValue(self._opacity)
        self._op_anim.setEndValue(1.0)
        self._op_anim.start()
        self._sc_anim.stop()
        self._sc_anim.setStartValue(self._scale)
        self._sc_anim.setEndValue(1.0)
        self._sc_anim.start()

    def _animate_icon_out(self):
        # 固定时图标也保持亮
        base_op = _SETTINGS.get("icon_opacity", 0.5)
        end_op = 1.0 if self._pinned else base_op
        end_sc = 1.0 if self._pinned else 0.85
        self._op_anim.stop()
        self._op_anim.setStartValue(self._opacity)
        self._op_anim.setEndValue(end_op)
        self._op_anim.start()
        self._sc_anim.stop()
        self._sc_anim.setStartValue(self._scale)
        self._sc_anim.setEndValue(end_sc)
        self._sc_anim.start()

    # ── 面板位置计算 ─────────────────────────────────────────
    def _calc_panel_pos(self):
        """图标右侧弹出， Y 轴与图标顶部对齐"""
        pan = self._ensure_panel()
        ig  = self.mapToGlobal(QtCore.QPoint(0, 0))
        pw  = pan.width()
        ph  = pan.sizeHint().height()
        scr = _screen_geometry()
        GAP = 6
        px  = ig.x() + self.SIZE + GAP
        py  = ig.y()
        # 右侧放不下就改到左侧
        if px + pw > scr.right():
            px = ig.x() - pw - GAP
        px = max(scr.left(), min(px, scr.right()  - pw))
        py = max(scr.top(),  min(py, scr.bottom() - ph))
        return px, py

    # ── 面板显示/隐藏 ────────────────────────────────────────
    def _ensure_panel(self):
        if self._panel is None:
            self._panel = ChanaiToolsPanel(_maya_win())
            self._panel._icon_ref = self   # 让面板可以反向引用图标
            # 面板的鼠标进入/离开也参与控制
            self._panel.installEventFilter(self)
        return self._panel

    def _sync_icon_to_panel(self):
        """面板被拖动后，根据面板位置反推图标应在的位置"""
        if not self._panel or not self._panel.isVisible():
            return
        pg = self._panel.geometry()
        scr = _screen_geometry()
        GAP = 6
        # 默认图标在面板左侧
        ix = pg.left() - self.SIZE - GAP
        # 如果左侧放不下就放右侧
        if ix < scr.left():
            ix = pg.right() + GAP
        iy = pg.top()
        self.move(ix, iy)

    def _show_panel(self):
        self._hide_timer.stop()
        pan = self._ensure_panel()
        px, py = self._calc_panel_pos()
        pan.show_slide(px, py)

    def _request_hide_panel(self):
        """非固定状态下，延迟一小段再收起（给鼠标移向面板留时间）"""
        if self._pinned:
            return
        self._hide_timer.start()

    def _on_hide_timer(self):
        """定时器到期，真正隐藏面板"""
        if self._pinned:
            return
        pan = self._ensure_panel()
        # 如果鼠标在面板内就不收
        pan_geo = pan.geometry()
        cur = QtGui.QCursor.pos()
        if pan.isVisible() and pan_geo.contains(cur):
            return
        pan.hide_slide()

    # ── eventFilter — 监听面板的 leave ───────────────────────
    def eventFilter(self, obj, event):
        if obj is self._panel:
            if event.type() == QtCore.QEvent.Leave:
                self._request_hide_panel()
            elif event.type() == QtCore.QEvent.Enter:
                self._hide_timer.stop()
        return False

    # ── hover 动画 + 展开 ────────────────────────────────────
    def enterEvent(self, e):
        self._hide_timer.stop()
        self._animate_icon_in()
        self._show_panel()

    def leaveEvent(self, e):
        self._animate_icon_out()
        self._request_hide_panel()

    # ── 鼠标事件 ────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == _LeftButton:
            self._drag_pos    = _global_pos(e) - self.frameGeometry().topLeft()
            self._was_dragged = False
        elif e.button() == _RightButton:
            import time
            now = time.time()
            if now - self._last_rclick < 0.5:
                self._quit()
            else:
                self._last_rclick = now

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() & _LeftButton:
            gp = _global_pos(e)
            if (gp - (self.frameGeometry().topLeft() +
                      self._drag_pos)).manhattanLength() > 5:
                self._was_dragged = True
            self.move(gp - self._drag_pos)
            # 图标移动时同步更新面板位置
            if self._panel and self._panel.isVisible():
                px, py = self._calc_panel_pos()
                self._panel.move(px, py)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None
        if not self._was_dragged and e.button() == _LeftButton:
            self._toggle_pin()

    # ── 固定/解固定 ──────────────────────────────────────────
    def _toggle_pin(self):
        self._pinned = not self._pinned
        self.update()   # 重绘图标（固定时加指示环）
        if self._pinned:
            # 固定：确保面板显示
            self._show_panel()
        else:
            # 解固定：如果鼠标已不在图标上则收起
            icon_geo = self.geometry()
            cur = QtGui.QCursor.pos()
            if not icon_geo.contains(cur):
                self._request_hide_panel()

    # ── 退出 ─────────────────────────────────────────────────
    def _quit(self):
        self._hide_timer.stop()
        if self._panel:
            try: self._panel.close()
            except Exception: pass
        try:
            import builtins as _b
        except ImportError:
            import __builtin__ as _b
        _b.__dict__.pop(_KEY, None)
        self.close()
        self.deleteLater()

    # ── 自绘 ─────────────────────────────────────────────────
    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(_Antialiasing)
        p.setOpacity(self._opacity)

        s  = self._scale
        cx = self.SIZE / 2.0
        cy = self.SIZE / 2.0

        # 固定状态：图标后面淡蓝色发光圆晗
        if self._pinned:
            p.setOpacity(self._opacity)
            r_glow = self.SIZE * 0.52 * s
            glow = QtGui.QRadialGradient(cx, cy, r_glow)
            glow.setColorAt(0.0, QtGui.QColor(100, 200, 255, 180))
            glow.setColorAt(0.5, QtGui.QColor(80,  160, 255, 90))
            glow.setColorAt(1.0, QtGui.QColor(60,  120, 220, 0))
            p.setBrush(QtGui.QBrush(glow))
            p.setPen(QtCore.Qt.NoPen if hasattr(QtCore.Qt, 'NoPen')
                     else QtGui.QPen(QtCore.Qt.transparent))
            p.drawEllipse(QtCore.QRectF(cx - r_glow, cy - r_glow,
                                        r_glow * 2, r_glow * 2))

        # 图标（根据缩放比例动态居中）
        if self._pixmap:
            base = self.ICON_BASE
            iw = int(base * s)
            ih = int(base * s)
            scaled = self._pixmap.scaled(iw, ih, _KeepAspect, _SmoothXform)
            p.setOpacity(self._opacity)
            p.drawPixmap(int(cx - iw / 2), int(cy - ih / 2), scaled)
        else:
            f = QtGui.QFont()
            f.setPointSize(int(29 * s))  # 22 * 1.3 ≈ 29
            p.setFont(f)
            p.setPen(QtGui.QColor(255, 255, 255, 230))
            p.drawText(self.rect(), _AlignCenter, u"\U0001f375")

        p.end()


# ═══════════════════════════════════════════════════════════════
#  单例入口
# ═══════════════════════════════════════════════════════════════

_KEY = "__ChanaiToolsIcon_v2__"


def main():
    app = QtWidgets.QApplication.instance()

    # 清旧实例
    for w in app.topLevelWidgets():
        if w.objectName() in (ChanaiToolsFloatIcon.OBJ, ChanaiToolsPanel.OBJ):
            try: w.close(); w.deleteLater()
            except Exception: pass

    try:
        import builtins as _b
    except ImportError:
        import __builtin__ as _b
    _b.__dict__.pop(_KEY, None)

    icon = ChanaiToolsFloatIcon(_maya_win())
    scr  = _screen_geometry()
    icon.move(scr.center().x() - icon.SIZE // 2, scr.center().y() - icon.SIZE // 2)
    icon.show()
    icon.raise_()
    _b.__dict__[_KEY] = icon
    _schedule_startup_bootstrap()


def onMayaDroppedPythonFile(*args, **kwargs):
    main()


if __name__ == "__main__":
    main()
