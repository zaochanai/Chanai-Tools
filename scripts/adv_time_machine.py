# -*- coding: utf-8 -*-
import io
u"""
时光机 v2.0 (Maya版) - 快速打开Maya文件
Author: Bullet.S
Compatibility: Maya 2018+ (PySide2/PySide6)
Based on BsOpenToolsPy for 3ds Max
"""

import os
import sys
import json
import datetime
import re
import subprocess
import ctypes
from ctypes import wintypes
from functools import partial

# PySide 兼容性处理
try:
    from PySide2 import QtWidgets, QtCore, QtGui
    from PySide2.QtWidgets import *
    from PySide2.QtCore import *
    from PySide2.QtGui import *
except ImportError:
    from PySide6 import QtWidgets, QtCore, QtGui
    from PySide6.QtWidgets import *
    from PySide6.QtCore import *
    from PySide6.QtGui import *

import maya.cmds as cmds
import maya.mel as mel


def _get_maya_main_window():
    """Return Maya main Qt window as QWidget (or None)."""
    try:
        import maya.OpenMayaUI as omui
        ptr = omui.MQtUtil.mainWindow()
        if ptr is None:
            return None
        try:
            from shiboken2 import wrapInstance
        except Exception:
            from shiboken6 import wrapInstance
        return wrapInstance(int(ptr), QtWidgets.QWidget)
    except Exception:
        return None

VERSION = "2.0"

# Windows API for embedding (仅Windows有效)
if sys.platform == 'win32':
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    SetParent = user32.SetParent
    SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    SetParent.restype = wintypes.HWND
    ShowWindow = user32.ShowWindow
    ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    SetWindowPos = user32.SetWindowPos
    SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    EnumWindows = user32.EnumWindows
    GetAncestor = user32.GetAncestor
    GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    GetAncestor.restype = wintypes.HWND
    
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        GetWindowLongX = user32.GetWindowLongPtrW
        SetWindowLongX = user32.SetWindowLongPtrW
    else:
        GetWindowLongX = user32.GetWindowLongW
        SetWindowLongX = user32.SetWindowLongW

    GWL_STYLE = -16
    WS_CHILD = 0x40000000
    WS_POPUP = 0x80000000
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    SWP_NOZORDER = 0x0004
    SWP_FRAMECHANGED = 0x0020
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SW_SHOW = 5
    GA_ROOT = 2

STYLE = """
* { font-family: "Microsoft YaHei", "Segoe UI"; font-size: 11px; color: #ddd; }
QWidget { background: #3c3c3c; color: #ddd; }
QGroupBox { 
    border: 1px solid #555; border-radius: 3px; 
    margin-top: 10px; padding: 3px; padding-top: 14px;
    font-weight: bold; color: #8cf;
}
QGroupBox::title { subcontrol-origin: margin; left: 6px; padding: 0 4px; color: #8cf; }
QPushButton, QToolButton {
    background: #4a4a4a; border: 1px solid #555; border-radius: 2px;
    padding: 3px 8px; min-height: 20px; color: #ddd;
}
QPushButton:hover, QToolButton:hover { background: #555; border-color: #7af; color: #fff; }
QPushButton:pressed { background: #333; color: #fff; }
QPushButton:checked { background: #357; border-color: #7af; color: #fff; }
QLineEdit {
    background: #333; border: 1px solid #555; border-radius: 2px;
    padding: 3px 5px; selection-background-color: #357; color: #ddd;
    selection-color: #fff;
}
QLineEdit:focus { border-color: #7af; color: #fff; }
QLineEdit:read-only { background: #2d2d2d; color: #999; }
QListWidget {
    background: #2d2d2d; border: 1px solid #555; border-radius: 2px; outline: none;
    color: #ddd;
}
QListWidget::item { padding: 4px; border-radius: 2px; color: #ddd; }
QListWidget::item:selected { background: #357; color: #fff; }
QListWidget::item:hover:!selected { background: #444; color: #fff; }
QLabel { color: #ddd; }
QCheckBox { spacing: 6px; color: #ddd; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 2px solid #666; border-radius: 3px;
    background: #2d2d2d;
}
QCheckBox::indicator:checked {
    background: #5af; border-color: #5af;
}
QCheckBox::indicator:hover { border-color: #8cf; }
QRadioButton { spacing: 6px; color: #ddd; }
QRadioButton::indicator {
    width: 14px; height: 14px;
    border: 2px solid #666; border-radius: 8px;
    background: #2d2d2d;
}
QRadioButton::indicator:checked {
    background: #5af; border-color: #5af;
}
QRadioButton::indicator:hover { border-color: #8cf; }
QMenu { background: #444; border: 1px solid #555; color: #ddd; }
QMenu::item { padding: 5px 20px; color: #ddd; }
QMenu::item:selected { background: #357; color: #fff; }
QSplitter::handle { background: #555; }
QSplitter::handle:horizontal { width: 3px; }
QToolTip { background: #444; color: #fff; border: 1px solid #555; padding: 4px; }
"""

# FBX嵌入容器
class FbxEmbedArea(QWidget):
    u"""用于嵌入FBX Review窗口的容器"""
    resized = Signal()
    
    def __init__(self, parent=None):
        super(FbxEmbedArea, self).__init__(parent)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setMinimumSize(200, 150)
        self.setStyleSheet("background: #202020; border: 1px solid #444;")
    
    def resizeEvent(self, e):
        super(FbxEmbedArea, self).resizeEvent(e)
        self.resized.emit()

def get_hwnd_from_widget(widget):
    u"""获取Qt Widget的Windows句柄"""
    try:
        return int(widget.winId())
    except:
        return None

def get_root_windows_by_pid(pid):
    u"""获取指定进程的所有顶层窗口"""
    if sys.platform != 'win32': return []
    out = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lParam):
        lpdwPid = wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(lpdwPid))
        if lpdwPid.value == pid:
            root = GetAncestor(hwnd, GA_ROOT)
            if root == hwnd:
                out.append(hwnd)
        return True
    EnumWindows(cb, 0)
    return out

def make_child_style(hwnd):
    u"""将窗口设置为子窗口样式"""
    if sys.platform != 'win32': return
    style = GetWindowLongX(hwnd, GWL_STYLE)
    style &= ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME)
    style |= WS_CHILD
    SetWindowLongX(hwnd, GWL_STYLE, style)
    SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)

class Config:
    def __init__(self):
        self.path = self._get_path()
        self.data = self._load()
    
    def _get_path(self):
        return os.path.join(cmds.internalVar(userAppDir=True), "MayaFileBrowser_v2.json")
    
    def _load(self):
        defaults = {
            "pos": [100, 100], "size": [580, 420], "favorites": [], "filters": [],
            "file_type": 0, "desktop": "", "silent": True, "reverse": False,
            "auto_fbx": True, "preview": False, "selected_fav": 0,
            "font_size": 12
        }
        if os.path.exists(self.path):
            try:
                try:
                    with io.open(self.path, 'r', encoding='utf-8') as f:
                        d = json.load(f)
                        for k, v in defaults.items():
                            if k not in d: d[k] = v
                        return d
                except TypeError:
                    with open(self.path, 'r') as f:
                        d = json.load(f)
                        for k, v in defaults.items():
                            if k not in d: d[k] = v
                        return d
            except: pass
        return defaults
    
    def save(self):
        try:
            try:
                with io.open(self.path, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, indent=2, ensure_ascii=False)
            except TypeError:
                with open(self.path, 'w') as f:
                    json.dump(self.data, f, indent=2, ensure_ascii=False)
        except: pass
    
    def get(self, k, d=None): return self.data.get(k, d)
    def set(self, k, v): self.data[k] = v

class FileOps:
    @staticmethod
    def natural_key(s):
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]
    
    @staticmethod
    def get_folders(path):
        if not os.path.isdir(path): return []
        try:
            items = [os.path.join(path, x) for x in os.listdir(path) if os.path.isdir(os.path.join(path, x))]
            return sorted(items, key=lambda x: FileOps.natural_key(os.path.basename(x)))
        except: return []
    
    @staticmethod
    def get_files(path, ext):
        if not os.path.isdir(path): return []
        try:
            items = []
            for x in os.listdir(path):
                fp = os.path.join(path, x)
                if os.path.isfile(fp):
                    _, e = os.path.splitext(x.lower())
                    if ext.endswith('*'):
                        if e.startswith(ext[:-1]): items.append(fp)
                    elif e == ext.lower(): items.append(fp)
            return sorted(items, key=lambda x: FileOps.natural_key(os.path.basename(x)))
        except: return []
    
    @staticmethod
    def get_parent(p): return os.path.dirname(p.rstrip(os.sep))
    
    @staticmethod
    def fmt_size(s):
        if s >= 1048576: return "%.1f MB" % (s / 1048576.0)
        if s >= 1024: return "%.1f KB" % (s / 1024.0)
        return "%d B" % s
    
    @staticmethod
    def get_info(p):
        if not os.path.exists(p): return {}
        s = os.stat(p)
        return {'size': FileOps.fmt_size(s.st_size), 
                'time': datetime.datetime.fromtimestamp(s.st_mtime).strftime('%Y/%m/%d %H:%M')}
    
    @staticmethod
    def get_recent():
        recent_files = []
        try:
            if cmds.optionVar(exists='RecentFilesList'):
                files = cmds.optionVar(query='RecentFilesList')
                if isinstance(files, str): files = [files]
                for f in files:
                    if os.path.exists(f) and f not in recent_files:
                        recent_files.append(f)
        except: pass
        return recent_files

class MayaOps:
    @staticmethod
    def open_maya(p, quiet=True):
        if not os.path.exists(p): return
        
        if not quiet and cmds.file(q=True, modified=True):
            result = cmds.confirmDialog(
                title=u"保存更改",
                message=u"当前场景已修改,是否保存?",
                button=[u"保存", u"不保存", u"取消"],
                defaultButton=u"保存",
                cancelButton=u"取消",
                dismissString=u"取消"
            )
            if result == u"保存":
                cmds.file(save=True)
            elif result == u"取消":
                return
        
        try:
            cmds.file(p, open=True, force=True)
            print(u"已打开: " + p)
        except Exception as e:
            print(u"打开失败: " + str(e))
    
    @staticmethod
    def import_fbx(p):
        try:
            if not cmds.pluginInfo('fbxmaya', query=True, loaded=True):
                cmds.loadPlugin('fbxmaya')
            mel.eval('FBXImport -f "{}"'.format(p.replace("\\", "/")))
            print(u"已导入FBX: " + p)
        except Exception as e:
            print(u"导入FBX失败: " + str(e))
    
    @staticmethod
    def run_script(p):
        try:
            if p.endswith('.py'):
                try:
                    with io.open(p, 'r', encoding='utf-8') as f:
                        exec(f.read(), {"__name__": "__main__"})
                except TypeError:
                    with open(p, 'r') as f:
                        exec(f.read(), {"__name__": "__main__"})
            elif p.endswith('.mel'):
                mel.eval('source "{}"'.format(p.replace("\\", "/")))
            print(u"已执行脚本: " + p)
        except Exception as e:
            print(u"执行脚本失败: " + str(e))
    
    @staticmethod
    def get_path():
        scene = cmds.file(q=True, sceneName=True)
        if scene:
            return os.path.dirname(scene)
        return ""
    
    @staticmethod
    def get_scripts():
        return cmds.internalVar(userScriptDir=True)
    
    @staticmethod
    def get_project():
        return cmds.workspace(q=True, rootDirectory=True)
    
    @staticmethod
    def get_fbxreview_path():
        paths = [
            r"C:\Program Files\Autodesk\FBX\FBX Review\fbxreview.exe",
            r"C:\Program Files (x86)\Autodesk\FBX\FBX Review\fbxreview.exe",
        ]
        # 检查脚本目录下的Res文件夹
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            local_fbx = os.path.join(script_dir, "Res", "fbxreview.exe")
            paths.insert(0, local_fbx)
        except:
            pass
        for p in paths:
            if os.path.isfile(p):
                return p
        return None

class FileItem(QListWidgetItem):
    def __init__(self, path, is_folder=False, exists=True):
        super(FileItem, self).__init__()
        self.path = path
        self.is_folder = is_folder
        name = os.path.basename(path)
        if is_folder:
            self.setText(u"📁 " + name)
        elif not exists:
            self.setText(u"❌ " + name)
        else:
            self.setText(u"📄 " + name)
        self.setToolTip(path)

class MayaFileBrowser(QDialog):
    closed = Signal()
    
    def __init__(self, parent=None):
        super(MayaFileBrowser, self).__init__(parent)
        
        self.cfg = Config()
        self.path = ""
        self.ext = ".ma"
        self.folders = []
        self.files = []
        self.recent_mode = False
        self.fbx_process = None
        self.current_preview_file = ""
        self.sort_by_name = True
        self._resizing = False
        
        self._ui()
        self._connect()
        self._load()
        self._init_path()
    
    def _ui(self):
        self.setWindowTitle(u"时光机 v" + VERSION + u" - Maya")
        # 作为 Maya 的 Tool 窗口（parent 到 Maya 主窗口），保持在 Maya 前面但不全局置顶。
        self.setWindowFlags(Qt.Tool | Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setStyleSheet(STYLE)
        
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        
        # === 左侧主面板 ===
        left = QVBoxLayout()
        left.setSpacing(4)
        
        # 路径栏
        path_row = QHBoxLayout()
        path_row.setSpacing(3)
        
        self.btn_refresh = QPushButton(u"刷新")
        self.btn_refresh.setFixedWidth(40)
        self.btn_refresh.setToolTip(u"刷新目录\n右键: 重置场景")
        path_row.addWidget(self.btn_refresh)
        
        self.btn_browse = QPushButton("...")
        self.btn_browse.setFixedWidth(28)
        self.btn_browse.setToolTip(u"选择目录")
        path_row.addWidget(self.btn_browse)
        
        self.edt_path = QLineEdit()
        self.edt_path.setReadOnly(True)
        path_row.addWidget(self.edt_path, 1)
        
        self.btn_add_fav = QPushButton(u"★")
        self.btn_add_fav.setFixedWidth(28)
        self.btn_add_fav.setToolTip(u"收藏当前目录")
        path_row.addWidget(self.btn_add_fav)
        
        self.btn_explorer = QPushButton(u"📂")
        self.btn_explorer.setFixedWidth(28)
        self.btn_explorer.setToolTip(u"在资源管理器中打开")
        path_row.addWidget(self.btn_explorer)
        
        self.btn_settings = QPushButton(u"⚙")
        self.btn_settings.setFixedWidth(28)
        self.btn_settings.setToolTip(u"设置")
        path_row.addWidget(self.btn_settings)
        
        left.addLayout(path_row)
        
        # 内容区
        content = QHBoxLayout()
        content.setSpacing(4)
        
        # 左侧边栏容器 (固定宽度)
        sidebar_widget = QWidget()
        sidebar_widget.setFixedWidth(150)
        sidebar = QVBoxLayout(sidebar_widget)
        sidebar.setContentsMargins(0, 0, 0, 0)
        sidebar.setSpacing(4)
        
        # 收藏目录
        grp_fav = QGroupBox(u"收藏目录 (右键操作)")
        lay_fav = QVBoxLayout(grp_fav)
        lay_fav.setContentsMargins(3, 3, 3, 3)
        lay_fav.setSpacing(2)
        
        self.lst_fav = QListWidget()
        self.lst_fav.setMinimumHeight(100)
        self.lst_fav.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lst_fav.setToolTip(u"右键: 添加/删除收藏")
        lay_fav.addWidget(self.lst_fav)
        sidebar.addWidget(grp_fav, 3)
        
        # 过滤词缀
        grp_filter = QGroupBox(u"过滤词缀")
        lay_filter = QVBoxLayout(grp_filter)
        lay_filter.setContentsMargins(3, 3, 3, 3)
        lay_filter.setSpacing(2)
        
        filter_input = QHBoxLayout()
        filter_input.setSpacing(2)
        self.edt_filter = QLineEdit()
        self.edt_filter.setPlaceholderText(u"输入后回车添加...")
        filter_input.addWidget(self.edt_filter)
        self.btn_filter_add = QPushButton(u"＋")
        self.btn_filter_add.setFixedSize(22, 22)
        self.btn_filter_add.setToolTip(u"添加过滤词")
        filter_input.addWidget(self.btn_filter_add)
        lay_filter.addLayout(filter_input)
        
        self.lst_filter = QListWidget()
        self.lst_filter.setMinimumHeight(80)
        self.lst_filter.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lst_filter.setToolTip(u"点击应用过滤 | 右键删除")
        lay_filter.addWidget(self.lst_filter)
        
        filter_btns = QHBoxLayout()
        filter_btns.setSpacing(2)
        self.btn_filter_clear = QPushButton(u"显示全部")
        self.btn_filter_clear.setToolTip(u"取消过滤，显示全部文件")
        filter_btns.addWidget(self.btn_filter_clear)
        lay_filter.addLayout(filter_btns)
        
        sidebar.addWidget(grp_filter, 2)
        
        # 快捷按钮
        grp_quick = QGroupBox(u"快捷操作")
        lay_quick = QVBoxLayout(grp_quick)
        lay_quick.setContentsMargins(3, 3, 3, 3)
        lay_quick.setSpacing(3)
        
        self.btn_recent = QPushButton(u"最近打开")
        self.btn_scripts = QPushButton(u"脚本目录")
        self.btn_project = QPushButton(u"项目目录")
        for b in [self.btn_recent, self.btn_scripts, self.btn_project]:
            lay_quick.addWidget(b)
        sidebar.addWidget(grp_quick)
        
        self.silent_mode = True
        
        content.addWidget(sidebar_widget)
        
        # 文件列表
        grp_files = QGroupBox(u"文件列表")
        lay_files = QVBoxLayout(grp_files)
        lay_files.setContentsMargins(3, 3, 3, 3)
        lay_files.setSpacing(3)
        
        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        
        self.grp_type = QButtonGroup(self)
        self.rb_ma = QRadioButton(".ma")
        self.rb_mb = QRadioButton(".mb")
        self.rb_mamb = QRadioButton("ma/mb")
        self.rb_fbx = QRadioButton(".fbx")
        self.rb_py = QRadioButton(".py")

        # 固定 id：兼容旧配置（0 ma / 1 mb / 2 fbx / 3 py），新增 4 为 ma/mb。
        self.grp_type.addButton(self.rb_ma, 0)
        self.grp_type.addButton(self.rb_mb, 1)
        self.grp_type.addButton(self.rb_fbx, 2)
        self.grp_type.addButton(self.rb_py, 3)
        self.grp_type.addButton(self.rb_mamb, 4)

        self.rb_ma.setChecked(True)
        for r in [self.rb_ma, self.rb_mb, self.rb_mamb, self.rb_fbx, self.rb_py]:
            toolbar.addWidget(r)
        
        toolbar.addStretch()
        
        self.cmb_sort = QPushButton(u"名称▼")
        self.cmb_sort.setFixedWidth(55)
        self.cmb_sort.setToolTip(u"切换排序方式：按名称/按时间")
        toolbar.addWidget(self.cmb_sort)
        
        self.chk_rev = QCheckBox(u"倒序")
        toolbar.addWidget(self.chk_rev)
        
        self.btn_up = QPushButton(u"上层")
        self.btn_up.setFixedWidth(40)
        toolbar.addWidget(self.btn_up)
        
        self.btn_preview = QPushButton(u"预览 >>")
        self.btn_preview.setCheckable(True)
        self.btn_preview.setFixedWidth(60)
        toolbar.addWidget(self.btn_preview)
        
        lay_files.addLayout(toolbar)
        
        self.lst_files = QListWidget()
        self.lst_files.setContextMenuPolicy(Qt.CustomContextMenu)
        self._update_list_font_size()  # 应用字体大小
        lay_files.addWidget(self.lst_files)
        
        # 状态栏
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        
        self.lbl_status = QLabel(u"文件: 0")
        self.lbl_status.setStyleSheet("color: #888;")
        status_row.addWidget(self.lbl_status)
        
        status_row.addStretch()
        
        now = datetime.datetime.now()
        weekdays = [u"一", u"二", u"三", u"四", u"五", u"六", u"日"]
        date_str = u"%d/%d/%d 周%s" % (now.year, now.month, now.day, weekdays[now.weekday()])
        self.lbl_date = QLabel(date_str)
        self.lbl_date.setStyleSheet("color: #666; font-size: 10px;")
        status_row.addWidget(self.lbl_date)
        
        sep = QLabel("|")
        sep.setStyleSheet("color: #555; font-size: 10px;")
        status_row.addWidget(sep)
        
        self.lbl_author = QLabel(u'<a href="#" style="color:#7af; text-decoration:none;">Bullet.S</a>')
        self.lbl_author.setStyleSheet("font-size: 10px;")
        self.lbl_author.setCursor(Qt.PointingHandCursor)
        self.lbl_author.setToolTip(u"点击访问作者B站主页")
        self.lbl_author.linkActivated.connect(self._show_help)
        status_row.addWidget(self.lbl_author)
        
        lay_files.addLayout(status_row)
        
        content.addWidget(grp_files, 1)
        left.addLayout(content)
        root.addLayout(left, 1)
        
        # === 右侧预览面板 ===
        self.preview_panel = QWidget()
        self.preview_panel.setFixedWidth(365)
        self.preview_panel.setVisible(False)
        
        prev_lay = QVBoxLayout(self.preview_panel)
        prev_lay.setContentsMargins(5, 0, 0, 0)
        prev_lay.setSpacing(4)
        
        grp_prev = QGroupBox(u"预览窗口 (FBX会内嵌预览)")
        lay_prev = QVBoxLayout(grp_prev)
        lay_prev.setContentsMargins(4, 4, 4, 4)
        lay_prev.setSpacing(4)
        
        self.preview_container = QWidget()
        self.preview_container.setFixedSize(350, 263)
        self.preview_container.setStyleSheet("background: #202020; border: 1px solid #444;")
        preview_lay = QVBoxLayout(self.preview_container)
        preview_lay.setContentsMargins(0, 0, 0, 0)
        preview_lay.setSpacing(0)
        
        self.lbl_thumb = QLabel()
        self.lbl_thumb.setAlignment(Qt.AlignCenter)
        self.lbl_thumb.setText(u"选择文件预览")
        self.lbl_thumb.setStyleSheet("background: transparent; border: none; color: #888;")
        preview_lay.addWidget(self.lbl_thumb)
        
        # FBX嵌入容器
        self.fbx_embed = FbxEmbedArea(self.preview_container)
        self.fbx_embed.setGeometry(0, 0, 350, 263)
        self.fbx_embed.hide()
        self.fbx_embed.resized.connect(self._resize_fbx_child)
        self.fbx_process = None
        self.fbx_child_hwnd = None
        
        lay_prev.addWidget(self.preview_container)
        prev_lay.addWidget(grp_prev)
        
        grp_info = QGroupBox(u"文件属性")
        lay_info = QVBoxLayout(grp_info)
        lay_info.setContentsMargins(4, 2, 4, 2)
        lay_info.setSpacing(0)
        
        self.lbl_info = QLabel()
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.lbl_info.setStyleSheet("color: #ccc; font-size: 10px; line-height: 1.2;")
        lay_info.addWidget(self.lbl_info)
        
        prev_lay.addWidget(grp_info)
        
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.btn_copy_path = QPushButton(u"复制路径")
        self.btn_copy_path.setFixedWidth(85)
        self.btn_copy_name = QPushButton(u"复制文件名")
        self.btn_copy_name.setFixedWidth(85)
        self.btn_fbx_external = QPushButton(u"外部预览")
        self.btn_fbx_external.setFixedWidth(70)
        self.btn_fbx_external.setToolTip(u"在独立窗口中打开FBX预览")
        self.btn_fbx_external.setVisible(False)
        self.chk_auto_fbx = QCheckBox(u"自动预览")
        self.chk_auto_fbx.setChecked(True)
        self.chk_auto_fbx.setToolTip(u"自动预览FBX文件")
        btn_row.addWidget(self.btn_copy_path)
        btn_row.addWidget(self.btn_copy_name)
        btn_row.addWidget(self.btn_fbx_external)
        btn_row.addWidget(self.chk_auto_fbx)
        btn_row.addStretch()
        prev_lay.addLayout(btn_row)
        
        root.addWidget(self.preview_panel)
        
        self.resize(580, 420)
    
    def _connect(self):
        self.btn_refresh.clicked.connect(self._refresh_path)
        self.btn_refresh.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_refresh.customContextMenuRequested.connect(self._reset_scene)
        self.btn_browse.clicked.connect(self._browse_dir)
        self.btn_add_fav.clicked.connect(self._add_current_fav)
        self.btn_explorer.clicked.connect(self._open_explorer)
        
        self.lst_fav.itemClicked.connect(self._on_fav_click)
        self.lst_fav.customContextMenuRequested.connect(self._fav_menu)
        
        self.btn_filter_add.clicked.connect(self._add_filter)
        self.btn_filter_clear.clicked.connect(self._clear_filter)
        self.edt_filter.returnPressed.connect(self._add_filter)
        self.lst_filter.itemClicked.connect(self._on_filter_click)
        self.lst_filter.customContextMenuRequested.connect(self._filter_menu)
        
        self.btn_recent.clicked.connect(self._show_recent)
        self.btn_scripts.clicked.connect(self._go_scripts)
        self.btn_project.clicked.connect(self._go_project)
        self.btn_settings.clicked.connect(self._show_settings)
        
        self.grp_type.buttonClicked.connect(self._on_type_change)
        self.cmb_sort.clicked.connect(self._toggle_sort_mode)
        self.chk_rev.stateChanged.connect(self._refresh_list)
        self.btn_up.clicked.connect(self._go_up)
        self.btn_preview.toggled.connect(self._toggle_preview)
        
        self.lst_files.itemClicked.connect(self._on_file_click)
        self.lst_files.itemDoubleClicked.connect(self._on_file_dbl)
        self.lst_files.customContextMenuRequested.connect(self._file_menu)
        
        self.btn_copy_path.clicked.connect(self._copy_path)
        self.btn_copy_name.clicked.connect(self._copy_name)
        self.btn_fbx_external.clicked.connect(self._open_fbx_external)
    
    def _load(self):
        pos = self.cfg.get("pos", [100, 100])
        size = self.cfg.get("size", [580, 420])
        self.move(pos[0], pos[1])
        self.resize(size[0], size[1])
        
        for fav in reversed(self.cfg.get("favorites", [])):
            if isinstance(fav, dict) and os.path.isdir(fav.get("dir", "")):
                item = QListWidgetItem(fav.get("name", ""))
                item.setData(Qt.UserRole, fav.get("dir"))
                item.setToolTip(fav.get("dir"))
                self.lst_fav.addItem(item)
        
        for f in reversed(self.cfg.get("filters", [])):
            self.lst_filter.addItem(f)
        
        self.silent_mode = self.cfg.get("silent", True)
        self.chk_rev.setChecked(self.cfg.get("reverse", False))
        self.chk_auto_fbx.setChecked(self.cfg.get("auto_fbx", True))
        
        idx = self.cfg.get("file_type", 0)
        id_to_btn = {
            0: self.rb_ma,
            1: self.rb_mb,
            2: self.rb_fbx,
            3: self.rb_py,
            4: self.rb_mamb,
        }
        btn = id_to_btn.get(idx, self.rb_ma)
        btn.setChecked(True)
        self._update_ext(self.grp_type.id(btn))
        
        sel = self.cfg.get("selected_fav", 0)
        if 0 <= sel < self.lst_fav.count():
            self.lst_fav.setCurrentRow(sel)
    
    def _save(self):
        self.cfg.set("pos", [self.x(), self.y()])
        w = self.width()
        if self.preview_panel.isVisible():
            w -= 371
        self.cfg.set("size", [w, self.height()])
        
        favs = []
        for i in range(self.lst_fav.count()):
            item = self.lst_fav.item(i)
            favs.append({"name": item.text(), "dir": item.data(Qt.UserRole)})
        self.cfg.set("favorites", list(reversed(favs)))
        
        filters = [self.lst_filter.item(i).text() for i in range(self.lst_filter.count())]
        self.cfg.set("filters", list(reversed(filters)))
        
        self.cfg.set("silent", self.silent_mode)
        self.cfg.set("reverse", self.chk_rev.isChecked())
        self.cfg.set("auto_fbx", self.chk_auto_fbx.isChecked())
        self.cfg.set("file_type", self.grp_type.checkedId())
        self.cfg.set("selected_fav", self.lst_fav.currentRow())
        self.cfg.set("preview", self.btn_preview.isChecked())
        self.cfg.save()
    
    def _update_ext(self, idx):
        if idx == 0:
            self.ext = ".ma"
        elif idx == 1:
            self.ext = ".mb"
        elif idx == 2:
            self.ext = ".fbx"
        elif idx == 3:
            self.ext = ".py"
        elif idx == 4:
            self.ext = (".ma", ".mb")
        else:
            self.ext = ".ma"
    
    def _init_path(self):
        p = MayaOps.get_path()
        if p and os.path.isdir(p):
            self._go_path(p)
        elif self.lst_fav.count() > 0:
            self.lst_fav.setCurrentRow(0)
            self._on_fav_click(self.lst_fav.currentItem())
    
    def _go_path(self, p):
        if not os.path.isdir(p): return
        self.path = p
        self.edt_path.setText(p)
        self.recent_mode = False
        self._refresh_list()
        
        for i in range(self.lst_fav.count()):
            if self.lst_fav.item(i).data(Qt.UserRole) == p:
                self.lst_fav.setCurrentRow(i)
                return
        self.lst_fav.clearSelection()
    
    def _refresh_list(self):
        if self.recent_mode: return
        self.lst_files.clear()
        self.folders = FileOps.get_folders(self.path)
        if isinstance(self.ext, (tuple, list, set)):
            all_files = []
            seen = set()
            for ext in self.ext:
                for fp in FileOps.get_files(self.path, ext):
                    if fp not in seen:
                        all_files.append(fp)
                        seen.add(fp)
        else:
            all_files = FileOps.get_files(self.path, self.ext)
        
        flt = self.edt_filter.text().strip()
        if not flt and self.lst_filter.currentItem():
            flt = self.lst_filter.currentItem().text()
        
        self.files = [f for f in all_files if flt.lower() in os.path.basename(f).lower()] if flt else all_files
        
        if self.sort_by_name:
            self.folders.sort(key=lambda x: os.path.basename(x).lower())
            self.files.sort(key=lambda x: os.path.basename(x).lower())
        else:
            self.folders.sort(key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0)
            self.files.sort(key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0)
        
        items = [FileItem(f, is_folder=True) for f in self.folders] + [FileItem(f) for f in self.files]
        if self.chk_rev.isChecked(): items.reverse()
        
        # 获取字体大小并应用到每个item
        font_size = self.cfg.get("font_size", 12)
        font = QFont("Microsoft YaHei", font_size)
        for item in items:
            item.setFont(font)
            self.lst_files.addItem(item)
        
        self.lbl_status.setText(u"文件夹: %d | 文件: %d" % (len(self.folders), len(self.files)))
    
    def _toggle_sort_mode(self):
        self.sort_by_name = not self.sort_by_name
        if self.sort_by_name:
            self.cmb_sort.setText(u"名称▼")
            self.cmb_sort.setToolTip(u"当前：按名称排序\n点击切换为按修改时间排序")
        else:
            self.cmb_sort.setText(u"时间▼")
            self.cmb_sort.setToolTip(u"当前：按修改时间排序\n点击切换为按名称排序")
        self._refresh_list()
    
    def _show_help(self):
        import webbrowser
        webbrowser.open("https://space.bilibili.com/2031113")
    
    def _refresh_path(self):
        p = MayaOps.get_path()
        if p and os.path.isdir(p): self._go_path(p)
        elif self.path: self._refresh_list()
    
    def _reset_scene(self):
        if QMessageBox.question(self, u"确认", u"重置当前场景？") == QMessageBox.Yes:
            cmds.file(new=True, force=True)
    
    def _browse_dir(self):
        p = QFileDialog.getExistingDirectory(self, u"选择目录", self.path)
        if p: self._go_path(p)
    
    def _add_current_fav(self):
        if not self.path: return
        for i in range(self.lst_fav.count()):
            if self.lst_fav.item(i).data(Qt.UserRole) == self.path:
                QMessageBox.information(self, u"提示", u"该目录已收藏")
                return
        name, ok = QInputDialog.getText(self, u"添加收藏", u"名称:", text=os.path.basename(self.path))
        if ok and name:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, self.path)
            item.setToolTip(self.path)
            self.lst_fav.insertItem(0, item)
            self.lst_fav.setCurrentRow(0)
            self._save()
    
    def _open_explorer(self):
        if self.path and os.path.isdir(self.path):
            if sys.platform == 'win32':
                os.startfile(self.path)
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))
    
    def _show_settings(self):
        menu = QMenu(self)
        act_silent = menu.addAction(u"静默打开 (不弹对话框)")
        act_silent.setCheckable(True)
        act_silent.setChecked(self.silent_mode)
        act_silent.triggered.connect(self._toggle_silent)
        
        menu.addSeparator()
        font_menu = menu.addMenu(u"文件列表字体大小")
        current_size = self.cfg.get("font_size", 12)
        for size in [9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32]:
            act = font_menu.addAction(u"%d pt" % size)
            act.setCheckable(True)
            act.setChecked(size == current_size)
            act.triggered.connect(partial(self._set_font_size, size))
        font_menu.addSeparator()
        act_custom = font_menu.addAction(u"自定义...")
        act_custom.triggered.connect(self._custom_font_size)
        
        menu.exec_(self.btn_settings.mapToGlobal(self.btn_settings.rect().bottomLeft()))
    
    def _toggle_silent(self):
        self.silent_mode = not self.silent_mode
        self._save()
    
    def _set_font_size(self, size):
        self.cfg.set("font_size", size)
        self._update_list_font_size()
        self._save()
    
    def _custom_font_size(self):
        current = self.cfg.get("font_size", 12)
        size, ok = QInputDialog.getInt(self, u"自定义字体大小", u"输入字体大小 (8-48 pt):", current, 8, 48)
        if ok:
            self._set_font_size(size)
    
    def _update_list_font_size(self):
        # 更新所有现有item的字体
        font_size = self.cfg.get("font_size", 12)
        font = QFont("Microsoft YaHei", font_size)
        for i in range(self.lst_files.count()):
            item = self.lst_files.item(i)
            if item:
                item.setFont(font)
    
    def _add_fav(self):
        p = QFileDialog.getExistingDirectory(self, u"选择收藏目录")
        if p:
            for i in range(self.lst_fav.count()):
                if self.lst_fav.item(i).data(Qt.UserRole) == p: return
            name, ok = QInputDialog.getText(self, u"添加收藏", u"名称:", text=os.path.basename(p))
            if ok and name:
                item = QListWidgetItem(name)
                item.setData(Qt.UserRole, p)
                item.setToolTip(p)
                self.lst_fav.insertItem(0, item)
                self._save()
    
    def _del_fav(self):
        row = self.lst_fav.currentRow()
        if row >= 0:
            self.lst_fav.takeItem(row)
            self._save()
    
    def _on_fav_click(self, item):
        if item:
            p = item.data(Qt.UserRole)
            if os.path.isdir(p): self._go_path(p)
    
    def _fav_menu(self, pos):
        menu = QMenu(self)
        menu.addAction(u"添加当前目录").triggered.connect(self._add_current_fav)
        menu.addAction(u"浏览添加...").triggered.connect(self._add_fav)
        item = self.lst_fav.itemAt(pos)
        if item:
            menu.addSeparator()
            menu.addAction(u"删除").triggered.connect(self._del_fav)
            menu.addAction(u"打开目录").triggered.connect(
                lambda: self._open_explorer_path(item.data(Qt.UserRole)))
        menu.exec_(self.lst_fav.mapToGlobal(pos))
    
    def _open_explorer_path(self, path):
        if path and os.path.isdir(path):
            if sys.platform == 'win32':
                os.startfile(path)
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _filter_menu(self, pos):
        item = self.lst_filter.itemAt(pos)
        menu = QMenu(self)
        menu.addAction(u"显示全部").triggered.connect(self._clear_filter)
        if item:
            menu.addSeparator()
            menu.addAction(u"删除").triggered.connect(self._del_filter)
        menu.exec_(self.lst_filter.mapToGlobal(pos))
    
    def _add_filter(self):
        t = self.edt_filter.text().strip()
        if t:
            for i in range(self.lst_filter.count()):
                if self.lst_filter.item(i).text() == t: return
            self.lst_filter.insertItem(0, t)
            self.lst_filter.setCurrentRow(0)
            self._refresh_list()
            self._save()
    
    def _del_filter(self):
        row = self.lst_filter.currentRow()
        if row >= 0:
            self.lst_filter.takeItem(row)
            self._refresh_list()
            self._save()
    
    def _clear_filter(self):
        self.edt_filter.clear()
        self.lst_filter.setCurrentRow(-1)
        self._refresh_list()
    
    def _on_filter_click(self, item):
        if item:
            self.edt_filter.setText(item.text())
            self._refresh_list()
    
    def _show_recent(self):
        self.recent_mode = True
        self.lst_files.clear()
        self.edt_path.setText(u"( 最近打开文件 )")
        font_size = self.cfg.get("font_size", 12)
        font = QFont("Microsoft YaHei", font_size)
        for p in FileOps.get_recent():
            item = FileItem(p, exists=os.path.exists(p))
            item.setFont(font)
            self.lst_files.addItem(item)
        self.lbl_status.setText(u"最近文件: %d" % self.lst_files.count())
    
    def _go_scripts(self):
        p = MayaOps.get_scripts()
        if p and os.path.isdir(p):
            self.rb_py.setChecked(True)
            self._update_ext(3)
            self._go_path(p)
    
    def _go_project(self):
        p = MayaOps.get_project()
        if p and os.path.isdir(p):
            self.rb_ma.setChecked(True)
            self._update_ext(0)
            self._go_path(p)
    
    def _on_type_change(self, btn):
        self._update_ext(self.grp_type.id(btn))
        self._refresh_list()
    
    def _go_up(self):
        if self.path:
            parent = FileOps.get_parent(self.path)
            if parent and os.path.isdir(parent): self._go_path(parent)
    
    def _toggle_preview(self, on):
        PREVIEW_WIDTH = 371
        self._resizing = True
        
        if on:
            self._left_width = self.width()
            self.preview_panel.setVisible(True)
            self.btn_preview.setText(u"预览 <<")
            self.resize(self._left_width + PREVIEW_WIDTH, self.height())
            item = self.lst_files.currentItem()
            if isinstance(item, FileItem) and not item.is_folder:
                self._update_preview(item.path)
        else:
            target_width = getattr(self, '_left_width', self.width() - PREVIEW_WIDTH)
            self.preview_panel.setVisible(False)
            self.btn_preview.setText(u"预览 >>")
            self.layout().invalidate()
            self.layout().activate()
            self.setMinimumWidth(0)
            self.resize(target_width, self.height())
        
        self._resizing = False
    
    def _on_file_click(self, item):
        if isinstance(item, FileItem) and not item.is_folder:
            if self.btn_preview.isChecked():
                self._update_preview(item.path)
    
    def _update_preview(self, p):
        self.current_preview_file = p
        self._cleanup_fbx_preview()
        self.fbx_embed.hide()
        self.lbl_thumb.show()
        self.btn_fbx_external.setVisible(False)
        
        if not p or not os.path.exists(p):
            self.lbl_thumb.setText(u"文件不存在")
            self.lbl_info.setText("")
            return
        
        file_info = FileOps.get_info(p)
        ext = os.path.splitext(p)[1].lower()
        
        if ext == ".fbx":
            txt = u"FBX文件属性:\n文件类型: FBX格式\n\n"
            txt += u"文件大小: %s  ||  修改时间: %s" % (file_info.get('size', '?'), file_info.get('time', '?'))
            self.lbl_info.setText(txt)
            self.btn_fbx_external.setVisible(True)
            
            if self.chk_auto_fbx.isChecked():
                QTimer.singleShot(200, lambda: self._start_fbx_embed(p))
            else:
                self.lbl_thumb.setText(u"FBX文件\n\n勾选'自动预览'启用内嵌预览\n或点击'外部预览'打开独立窗口")
        else:
            self.lbl_thumb.setText(ext.upper() + u" 文件")
            txt = u"文件属性:\n文件类型: %s\n\n" % ext.upper()
            txt += u"文件大小: %s  ||  修改时间: %s" % (file_info.get('size', '?'), file_info.get('time', '?'))
            self.lbl_info.setText(txt)
    
    def _on_file_dbl(self, item):
        if not isinstance(item, FileItem): return
        if item.is_folder:
            self._go_path(item.path)
        else:
            ext = os.path.splitext(item.path)[1].lower()
            if ext in [".ma", ".mb"]: MayaOps.open_maya(item.path, self.silent_mode)
            elif ext == ".fbx": MayaOps.import_fbx(item.path)
            elif ext in [".py", ".mel"]: MayaOps.run_script(item.path)
            
            if self.recent_mode and os.path.exists(item.path):
                self._go_path(os.path.dirname(item.path))
    
    def _file_menu(self, pos):
        item = self.lst_files.itemAt(pos)
        menu = QMenu(self)
        if item and isinstance(item, FileItem):
            if not item.is_folder:
                menu.addAction(u"打开").triggered.connect(lambda: self._on_file_dbl(item))
                menu.addAction(u"复制路径").triggered.connect(lambda: self._clip(item.path))
                menu.addAction(u"复制文件名").triggered.connect(lambda: self._clip(os.path.basename(item.path)))
                menu.addSeparator()
            menu.addAction(u"打开所在目录").triggered.connect(
                lambda: self._open_explorer_path(item.path if item.is_folder else os.path.dirname(item.path)))
            menu.addSeparator()
        menu.addAction(u"返回上层").triggered.connect(self._go_up)
        menu.addAction(u"刷新").triggered.connect(self._refresh_list)
        menu.exec_(self.lst_files.mapToGlobal(pos))
    
    def _clip(self, t):
        app = QApplication.instance()
        if app: app.clipboard().setText(t)
    
    def _copy_path(self):
        item = self.lst_files.currentItem()
        if isinstance(item, FileItem): self._clip(item.path)
    
    def _copy_name(self):
        item = self.lst_files.currentItem()
        if isinstance(item, FileItem): self._clip(os.path.basename(item.path))
    
    def _start_fbx_embed(self, file_path):
        if sys.platform != 'win32': return
        fbx_exe = MayaOps.get_fbxreview_path()
        if not fbx_exe or not os.path.isfile(fbx_exe):
            self.lbl_thumb.setText(u"未找到FBX Review\n请安装Autodesk FBX Review")
            return
        
        try:
            self._cleanup_fbx_preview()
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            self.fbx_process = subprocess.Popen([fbx_exe, file_path], startupinfo=si)
            self.lbl_thumb.setText(u"正在加载FBX预览...")
            QTimer.singleShot(500, self._try_embed_fbx)
        except Exception as e:
            self.lbl_thumb.setText(u"FBX预览失败:\n%s" % str(e))
    
    def _try_embed_fbx(self, retry=0):
        if not self.fbx_process: return
        try:
            wins = get_root_windows_by_pid(self.fbx_process.pid)
            if wins:
                hwnd = wins[0]
                container_hwnd = get_hwnd_from_widget(self.fbx_embed)
                if container_hwnd:
                    SetParent(hwnd, container_hwnd)
                    make_child_style(hwnd)
                    self.fbx_child_hwnd = hwnd
                    w, h = self.fbx_embed.width(), self.fbx_embed.height()
                    SetWindowPos(hwnd, None, 0, 0, w, h, SWP_NOZORDER)
                    ShowWindow(hwnd, SW_SHOW)
                    self.lbl_thumb.hide()
                    self.fbx_embed.show()
                    return
            if retry < 20:
                QTimer.singleShot(500, lambda: self._try_embed_fbx(retry + 1))
            else:
                self.lbl_thumb.setText(u"FBX预览超时")
                self._cleanup_fbx_preview()
        except Exception as e:
            self.lbl_thumb.setText(u"嵌入失败:\n%s" % str(e))
    
    def _resize_fbx_child(self):
        if self.fbx_child_hwnd:
            w, h = self.fbx_embed.width(), self.fbx_embed.height()
            SetWindowPos(self.fbx_child_hwnd, None, 0, 0, w, h, SWP_NOZORDER)
    
    def _cleanup_fbx_preview(self):
        self.fbx_child_hwnd = None
        if self.fbx_process:
            try:
                self.fbx_process.terminate()
                self.fbx_process.wait(timeout=1)
            except:
                try: self.fbx_process.kill()
                except: pass
            self.fbx_process = None
    
    def _open_fbx_external(self):
        if not hasattr(self, 'current_preview_file') or not self.current_preview_file: return
        p = self.current_preview_file
        if not os.path.exists(p): return
        
        self._cleanup_fbx_preview()
        self.fbx_embed.hide()
        self.lbl_thumb.show()
        self.lbl_thumb.setText(u"FBX已在外部窗口打开")
        
        fbx_exe = MayaOps.get_fbxreview_path()
        if fbx_exe and os.path.isfile(fbx_exe):
            try: subprocess.Popen([fbx_exe, p])
            except: pass
    
    def resizeEvent(self, e):
        super(MayaFileBrowser, self).resizeEvent(e)
        if getattr(self, '_resizing', False): return
        if hasattr(self, 'cfg') and hasattr(self, 'preview_panel'):
            w = self.width()
            if self.preview_panel.isVisible(): w -= 371
            self.cfg.set("size", [w, self.height()])
            self.cfg.save()
    
    def moveEvent(self, e):
        super(MayaFileBrowser, self).moveEvent(e)
        if hasattr(self, 'cfg'):
            self.cfg.set("pos", [self.x(), self.y()])
            self.cfg.save()
    
    def closeEvent(self, e):
        self._cleanup_fbx_preview()
        self._save()
        self.closed.emit()
        super(MayaFileBrowser, self).closeEvent(e)
    
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape: self.close()
        elif e.key() == Qt.Key_Backspace: self._go_up()
        elif e.key() == Qt.Key_F5: self._refresh_list()
        else: super(MayaFileBrowser, self).keyPressEvent(e)

def show_maya_file_browser():
    global maya_file_browser_window
    try:
        if maya_file_browser_window:
            maya_file_browser_window.close()
            maya_file_browser_window.deleteLater()
    except: pass
    
    maya_file_browser_window = MayaFileBrowser(parent=_get_maya_main_window())
    maya_file_browser_window.show()
    try:
        maya_file_browser_window.raise_()
        maya_file_browser_window.activateWindow()
    except Exception:
        pass
    return maya_file_browser_window

maya_file_browser_window = None

if __name__ == "__main__":
    show_maya_file_browser()

