# -*- coding: utf-8 -*-
"""ADV 打开文件管理

历史上本模块用于“拖拽弹窗”。现在同时承担：
- Ctrl+O：弹 Qt 打开窗口（默认定位到当前/上次目录），取消即取消
- Ctrl+Shift+S：弹 Qt 另存为窗口
- 兜底：Windows native 级吞键，避免 Maya 默认 Open 再弹系统窗口
"""

import json
import os
import sys
import time

import maya.cmds as cmds
import maya.mel as mel
import maya.utils

try:
    from PySide2 import QtWidgets, QtCore, QtGui  # type: ignore
except ImportError:
    try:
        from PySide6 import QtWidgets, QtCore, QtGui  # type: ignore
    except ImportError:
        from PySide import QtWidgets, QtCore, QtGui  # type: ignore


# 确保无论以何种方式加载，本模块都能被 runTimeCommand 稳定复用
try:
    sys.modules['adv_path_manager'] = sys.modules.get('adv_path_manager', sys.modules[__name__])
except Exception:
    pass


_OPTIONVAR_ENABLED = 'ADV_PathManagerEnabled'
_OPTIONVAR_BACKUP_PREFIX = 'ADV_PathManagerBackup_'
_OPTIONVAR_LAST_DIR = 'ADV_PathManagerLastDir'
_OPTIONVAR_MODULE_PATH = 'ADV_PathManagerModulePath'
_OPTIONVAR_LAST_ERROR = 'ADV_PathManagerLastError'
_OPTIONVAR_MENU_BACKUP = 'ADV_PathManagerMenuBackup'
_OPTIONVAR_HOTKEY_BACKUP = 'ADV_PathManagerHotkeyBackup'
_OPTIONVAR_HOTKEYSET_BACKUP = 'ADV_PathManagerHotkeySetBackup'
_OPTIONVAR_DIALOG_STYLE = 'ADV_PathManagerDialogStyle'

_STATE = {
    'enabled': False,
    'drop_filter': None,
    'drop_target': None,
    'menu_hooked': False,
    'hotkeys_hooked': False,
    'qt_shortcuts': {},
    'qt_key_filter': None,
    'native_key_filter': None,
    'in_open': False,
    'in_save_as': False,
    'last_key_intercept': None,
    'last_qt_error': None,
    'last_trigger_ts': {'open': 0.0, 'save_as': 0.0},
    'native_suppress_keyup': {'open': False, 'save_as': False},
}

_DIALOG_DEFAULT_SIZE = (1352, 936)
_TRIGGER_COOLDOWN_SEC = 0.6
_LAST_QT_SELECTED_FILTER = None


def _main_qwidget():
    try:
        from maya import OpenMayaUI as omui
        try:
            import shiboken2 as shiboken  # type: ignore
        except Exception:
            import shiboken6 as shiboken  # type: ignore
        mw = omui.MQtUtil.mainWindow()
        if mw:
            try:
                return shiboken.wrapInstance(int(mw), QtWidgets.QWidget)
            except Exception:
                try:
                    return shiboken.wrapInstance(long(mw), QtWidgets.QWidget)  # type: ignore[name-defined]
                except Exception:
                    return None
    except Exception:
        pass
    return None


def _qt_resize_dialog(dlg):
    try:
        w, h = _DIALOG_DEFAULT_SIZE
    except Exception:
        w, h = 1352, 936

    try:
        dlg.resize(int(w), int(h))
    except Exception:
        pass
    try:
        dlg.setMinimumSize(int(min(w, 1000)), int(min(h, 700)))
    except Exception:
        pass


def _should_ignore_trigger(which):
    try:
        now = time.time()
        last = float((_STATE.get('last_trigger_ts') or {}).get(which, 0.0))
        if (now - last) < float(_TRIGGER_COOLDOWN_SEC):
            return True
        _STATE['last_trigger_ts'][which] = now
        return False
    except Exception:
        return False


def _prompt_save_if_modified():
    try:
        if not cmds.file(q=True, modified=True):
            return True
    except Exception:
        return True

    # Prefer Qt dialog (consistent with Qt file dialogs)
    try:
        parent = _main_qwidget()
        box = QtWidgets.QMessageBox(parent)
        box.setWindowTitle(u"场景未保存")
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setText(u"当前场景有未保存修改，是否先保存？")
        btn_save = box.addButton(u"保存并继续", QtWidgets.QMessageBox.AcceptRole)
        btn_no = box.addButton(u"不保存继续", QtWidgets.QMessageBox.DestructiveRole)
        btn_cancel = box.addButton(u"取消", QtWidgets.QMessageBox.RejectRole)
        try:
            box.setDefaultButton(btn_save)
        except Exception:
            pass
        try:
            box.setEscapeButton(btn_cancel)
        except Exception:
            pass

        box.exec_()
        clicked = box.clickedButton()
        if clicked == btn_save:
            smart_save()
            return True
        if clicked == btn_no:
            return True
        return False
    except Exception:
        # Fallback to Maya confirmDialog
        try:
            res = cmds.confirmDialog(
                title=u"场景未保存",
                message=u"当前场景有未保存修改，是否先保存？",
                button=[u"保存并继续", u"不保存继续", u"取消"],
                defaultButton=u"保存并继续",
                cancelButton=u"取消",
                dismissString=u"取消",
            )
            if res == u"保存并继续":
                smart_save()
                return True
            if res == u"不保存继续":
                return True
            return False
        except Exception:
            return False


def _qt_pick_existing_file(caption, start_dir, name_filter=None):
    try:
        _STATE['last_qt_error'] = None
    except Exception:
        pass

    try:
        parent = _main_qwidget()

        sd = start_dir
        try:
            if sd:
                sd_native = os.path.normpath(sd)
                if not os.path.isdir(sd_native):
                    sd = None
        except Exception:
            sd = None

        dlg = QtWidgets.QFileDialog(parent, caption, sd or '')
        dlg.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        dlg.setViewMode(QtWidgets.QFileDialog.Detail)
        try:
            dlg.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        except Exception:
            pass
        # Support multi-filters so user can switch ma/mb display
        if name_filter:
            try:
                if isinstance(name_filter, (list, tuple)):
                    dlg.setNameFilters([str(x) for x in name_filter if x])
                elif ';;' in str(name_filter):
                    dlg.setNameFilters([x for x in str(name_filter).split(';;') if x])
                else:
                    dlg.setNameFilter(str(name_filter))
            except Exception:
                pass

        _qt_resize_dialog(dlg)

        if dlg.exec_():
            files = dlg.selectedFiles() or []
            if files:
                try:
                    global _LAST_QT_SELECTED_FILTER
                    _LAST_QT_SELECTED_FILTER = dlg.selectedNameFilter()
                except Exception:
                    pass
                return files[0]
    except Exception as e:
        try:
            _STATE['last_qt_error'] = str(e)
        except Exception:
            pass
    return None


def _qt_pick_save_file(caption, start_dir, name_filter=None, default_name=None):
    try:
        _STATE['last_qt_error'] = None
    except Exception:
        pass

    try:
        parent = _main_qwidget()

        sd = start_dir
        try:
            if sd:
                sd_native = os.path.normpath(sd)
                if not os.path.isdir(sd_native):
                    sd = None
        except Exception:
            sd = None

        dlg = QtWidgets.QFileDialog(parent, caption, sd or '')
        dlg.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)
        dlg.setFileMode(QtWidgets.QFileDialog.AnyFile)
        dlg.setViewMode(QtWidgets.QFileDialog.Detail)
        try:
            dlg.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        except Exception:
            pass
        if name_filter:
            try:
                if isinstance(name_filter, (list, tuple)):
                    dlg.setNameFilters([str(x) for x in name_filter if x])
                elif ';;' in str(name_filter):
                    dlg.setNameFilters([x for x in str(name_filter).split(';;') if x])
                else:
                    dlg.setNameFilter(str(name_filter))
            except Exception:
                pass
        if default_name:
            try:
                dlg.selectFile(str(default_name))
            except Exception:
                pass

        # Update default suffix when user changes filter
        try:
            def _on_filter_selected(f):
                fl = str(f).lower()
                if '.mb' in fl:
                    dlg.setDefaultSuffix('mb')
                elif '.ma' in fl:
                    dlg.setDefaultSuffix('ma')
            dlg.filterSelected.connect(_on_filter_selected)
        except Exception:
            pass

        _qt_resize_dialog(dlg)

        if dlg.exec_():
            files = dlg.selectedFiles() or []
            if files:
                try:
                    global _LAST_QT_SELECTED_FILTER
                    _LAST_QT_SELECTED_FILTER = dlg.selectedNameFilter()
                except Exception:
                    pass
                return files[0]
    except Exception as e:
        try:
            _STATE['last_qt_error'] = str(e)
        except Exception:
            pass
    return None


def _trigger_open():
    if _should_ignore_trigger('open'):
        return
    if _STATE.get('in_open'):
        return
    _STATE['in_open'] = True

    def _run():
        try:
            open_scene_dialog()
        finally:
            _STATE['in_open'] = False

    try:
        maya.utils.executeDeferred(_run)
    except Exception:
        try:
            _run()
        except Exception:
            _STATE['in_open'] = False


def _trigger_save_as():
    if _should_ignore_trigger('save_as'):
        return
    if _STATE.get('in_save_as'):
        return
    _STATE['in_save_as'] = True

    def _run():
        try:
            smart_save_as()
        finally:
            _STATE['in_save_as'] = False

    try:
        maya.utils.executeDeferred(_run)
    except Exception:
        try:
            _run()
        except Exception:
            _STATE['in_save_as'] = False


def _install_qshortcuts():
    parent = _main_qwidget()
    if parent is None:
        return False

    _remove_qshortcuts()
    _remove_qkey_filter()

    try:
        sc_open = QtWidgets.QShortcut(QtGui.QKeySequence('Ctrl+O'), parent)
        sc_open.setContext(QtCore.Qt.ApplicationShortcut)
        sc_open.setAutoRepeat(False)
        sc_open.activated.connect(lambda: (_trigger_open(), None)[1])

        sc_save_as = QtWidgets.QShortcut(QtGui.QKeySequence('Ctrl+Shift+S'), parent)
        sc_save_as.setContext(QtCore.Qt.ApplicationShortcut)
        sc_save_as.setAutoRepeat(False)
        sc_save_as.activated.connect(lambda: (_trigger_save_as(), None)[1])

        _STATE['qt_shortcuts'] = {'ctrl_o': sc_open, 'ctrl_shift_s': sc_save_as}
    except Exception as e:
        try:
            _STATE['last_qt_error'] = str(e)
        except Exception:
            pass
        _STATE['qt_shortcuts'] = {}
        return False

    try:
        _install_qkey_filter()
    except Exception:
        pass

    try:
        _install_native_key_filter()
    except Exception:
        pass
    return True


def _remove_qshortcuts():
    try:
        for _, sc in list((_STATE.get('qt_shortcuts') or {}).items()):
            try:
                sc.setEnabled(False)
            except Exception:
                pass
            try:
                sc.deleteLater()
            except Exception:
                pass
    except Exception:
        pass
    _STATE['qt_shortcuts'] = {}


def _install_qkey_filter():
    app = QtWidgets.QApplication.instance()
    if app is None:
        return False

    mgr = _STATE

    class _KeyFilter(QtCore.QObject):
        def eventFilter(self, obj, event):
            try:
                if event.type() != QtCore.QEvent.KeyPress:
                    return False
            except Exception:
                return False

            try:
                if event.isAutoRepeat():
                    return False
            except Exception:
                pass

            try:
                key = event.key()
                mods = event.modifiers()
            except Exception:
                return False

            # Avoid triggering when a modal dialog is already open
            try:
                if QtWidgets.QApplication.activeModalWidget() is not None:
                    return False
            except Exception:
                pass

            # Ctrl+O
            if key == QtCore.Qt.Key_O and (mods & QtCore.Qt.ControlModifier) and not (mods & QtCore.Qt.ShiftModifier) and not (mods & QtCore.Qt.AltModifier):
                mgr['last_key_intercept'] = 'Ctrl+O'
                _trigger_open()
                try:
                    event.accept()
                except Exception:
                    pass
                return True

            # Ctrl+Shift+S
            if key == QtCore.Qt.Key_S and (mods & QtCore.Qt.ControlModifier) and (mods & QtCore.Qt.ShiftModifier) and not (mods & QtCore.Qt.AltModifier):
                mgr['last_key_intercept'] = 'Ctrl+Shift+S'
                _trigger_save_as()
                try:
                    event.accept()
                except Exception:
                    pass
                return True

            return False

    _remove_qkey_filter()
    f = _KeyFilter(app)
    app.installEventFilter(f)
    _STATE['qt_key_filter'] = f
    return True


def _remove_qkey_filter():
    try:
        app = QtWidgets.QApplication.instance()
        f = _STATE.get('qt_key_filter')
        if app is not None and f is not None:
            try:
                app.removeEventFilter(f)
            except Exception:
                pass
    except Exception:
        pass
    _STATE['qt_key_filter'] = None


def _install_native_key_filter():
    # Only meaningful on Windows
    try:
        if os.name != 'nt':
            return False
    except Exception:
        return False

    _remove_native_key_filter()

    try:
        import ctypes
        import ctypes.wintypes as wintypes
    except Exception:
        return False

    user32 = ctypes.windll.user32
    VK_CONTROL = 0x11
    VK_SHIFT = 0x10
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105
    VK_O = 0x4F
    VK_S = 0x53
    NC_OPEN = 'ADV_PathMgr_OpenScene_NC'
    NC_SAVE_AS = 'ADV_PathMgr_SaveAs_NC'

    def _hotkeys_already_hooked():
        try:
            n_open = _hotkey_get('o', ctrl=True)
            n_save_as = _hotkey_get('s', ctrl=True, shift=True)
            return (str(n_open) == str(NC_OPEN)) and (str(n_save_as) == str(NC_SAVE_AS))
        except Exception:
            return False

    class _NativeFilter(QtCore.QAbstractNativeEventFilter):
        def nativeEventFilter(self, eventType, message):
            try:
                if eventType not in ('windows_generic_MSG', 'windows_dispatcher_MSG', b'windows_generic_MSG', b'windows_dispatcher_MSG'):
                    return (False, 0)

                msg = wintypes.MSG.from_address(int(message))
                if msg.message not in (WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP):
                    return (False, 0)

                wparam = int(msg.wParam)
                ctrl_down = (user32.GetKeyState(VK_CONTROL) & 0x8000) != 0
                shift_down = (user32.GetKeyState(VK_SHIFT) & 0x8000) != 0

                try:
                    if _hotkeys_already_hooked():
                        return (False, 0)
                except Exception:
                    pass

                # Swallow the matching KEYUP if we previously handled KEYDOWN.
                if msg.message in (WM_KEYUP, WM_SYSKEYUP):
                    try:
                        if wparam == VK_O and (_STATE.get('native_suppress_keyup') or {}).get('open'):
                            _STATE['native_suppress_keyup']['open'] = False
                            return (True, 0)
                        if wparam == VK_S and (_STATE.get('native_suppress_keyup') or {}).get('save_as'):
                            _STATE['native_suppress_keyup']['save_as'] = False
                            return (True, 0)
                    except Exception:
                        return (False, 0)
                    return (False, 0)

                # Ctrl+O
                if wparam == VK_O and ctrl_down and (not shift_down):
                    _STATE['last_key_intercept'] = 'native Ctrl+O'
                    try:
                        _STATE['native_suppress_keyup']['open'] = True
                    except Exception:
                        pass

                    def _run():
                        _trigger_open()

                    try:
                        maya.utils.executeDeferred(_run)
                    except Exception:
                        try:
                            _run()
                        except Exception:
                            pass
                    return (True, 0)

                # Ctrl+Shift+S
                if wparam == VK_S and ctrl_down and shift_down:
                    _STATE['last_key_intercept'] = 'native Ctrl+Shift+S'
                    try:
                        _STATE['native_suppress_keyup']['save_as'] = True
                    except Exception:
                        pass

                    def _run2():
                        _trigger_save_as()

                    try:
                        maya.utils.executeDeferred(_run2)
                    except Exception:
                        try:
                            _run2()
                        except Exception:
                            pass
                    return (True, 0)

                return (False, 0)
            except Exception:
                return (False, 0)

    app = QtWidgets.QApplication.instance()
    if app is None:
        return False

    nf = _NativeFilter()
    try:
        app.installNativeEventFilter(nf)
        _STATE['native_key_filter'] = nf
        return True
    except Exception:
        _STATE['native_key_filter'] = None
        return False


def _remove_native_key_filter():
    try:
        app = QtWidgets.QApplication.instance()
        nf = _STATE.get('native_key_filter')
        if app is not None and nf is not None:
            try:
                app.removeNativeEventFilter(nf)
            except Exception:
                pass
    except Exception:
        pass
    _STATE['native_key_filter'] = None


def _norm_dir(path):
    try:
        return os.path.dirname(path).replace('\\', '/')
    except Exception:
        return None


def _scene_dir():
    try:
        p = cmds.file(q=True, sceneName=True) or ''
    except Exception:
        p = ''
    if p:
        d = _norm_dir(p)
        if d and os.path.isdir(d):
            return d
    return None


def _project_dir():
    try:
        proj = cmds.workspace(q=True, rootDirectory=True) or ''
        proj = proj.replace('\\', '/')
        if proj and os.path.isdir(proj):
            return proj
    except Exception:
        pass
    return None


def _last_dir():
    try:
        if cmds.optionVar(exists=_OPTIONVAR_LAST_DIR):
            p = cmds.optionVar(q=_OPTIONVAR_LAST_DIR) or ''
            p = str(p).replace('\\', '/')
            if p and os.path.isdir(p):
                return p
    except Exception:
        pass
    return None


def _set_last_dir_from_path(path):
    try:
        d = _norm_dir(path)
        if d and os.path.isdir(d):
            cmds.optionVar(sv=(_OPTIONVAR_LAST_DIR, d))
    except Exception:
        pass


def _preferred_start_dir():
    # 未保存场景时优先使用“上次目录”，避免总回到项目目录
    return _scene_dir() or _last_dir() or _project_dir() or ''


def _save_backup(name, value):
    try:
        key = _OPTIONVAR_BACKUP_PREFIX + name
        if value is None:
            if cmds.optionVar(exists=key):
                cmds.optionVar(remove=key)
        else:
            cmds.optionVar(sv=(key, str(value)))
    except Exception:
        pass


def _load_backup(name):
    try:
        key = _OPTIONVAR_BACKUP_PREFIX + name
        if cmds.optionVar(exists=key):
            return cmds.optionVar(q=key)
    except Exception:
        pass
    return None


def is_enabled():
    try:
        return bool(cmds.optionVar(q=_OPTIONVAR_ENABLED)) if cmds.optionVar(exists=_OPTIONVAR_ENABLED) else False
    except Exception:
        return False


def set_enabled(enabled):
    enabled = bool(enabled)
    try:
        cmds.optionVar(iv=(_OPTIONVAR_ENABLED, 1 if enabled else 0))
    except Exception:
        pass

    if enabled:
        enable()
    else:
        disable()


def enable():
    if _STATE.get('enabled'):
        return

    # 让 runTimeCommand 在任何 sys.path 情况下都能定位到本模块
    try:
        cmds.optionVar(sv=(_OPTIONVAR_MODULE_PATH, str(__file__).replace('\\', '/')))
    except Exception:
        pass

    # 旧版本可能接管过 File 菜单/热键，这里统一尝试恢复，避免残留影响 Maya 默认行为
    try:
        _restore_file_menu()
    except Exception:
        pass
    try:
        _restore_hotkeys()
    except Exception:
        pass

    # Install file manager hooks (Ctrl+O / Ctrl+Shift+S) and keep drag-drop handler.
    hk_ok = False
    try:
        hk_ok = bool(_hook_hotkeys())
    except Exception:
        hk_ok = False

    # Only install Qt-level shortcuts/filters as a fallback.
    # If we successfully hooked Maya hotkeys, extra Qt interception can cause duplicate triggers
    # or modal-dialog conflicts on some Maya versions (e.g. Maya 2025).
    if not hk_ok:
        try:
            _install_qshortcuts()
        except Exception:
            pass
    else:
        try:
            _remove_qshortcuts()
            _remove_qkey_filter()
        except Exception:
            pass
        try:
            _install_native_key_filter()
        except Exception:
            pass

    _install_drop_handler()
    _STATE['menu_hooked'] = False
    _STATE['enabled'] = True


def disable():
    # 仍然做一次 best-effort 恢复（兼容旧版本残留）
    try:
        _restore_file_menu()
    except Exception:
        pass
    try:
        _restore_hotkeys()
    except Exception:
        pass
    try:
        _remove_qshortcuts()
        _remove_qkey_filter()
        _remove_native_key_filter()
    except Exception:
        pass

    _uninstall_drop_handler()
    _STATE['enabled'] = False
def _py_entry(func_name):
    return (
        "import sys, imp, maya.cmds as cmds; "
        "p=(cmds.optionVar(q='%s') if cmds.optionVar(exists='%s') else ''); "
        "m=sys.modules.get('adv_path_manager'); "
        "m=(m if m else (imp.load_source('adv_path_manager', p) if p else None)); "
        "m and getattr(m, '%s')()"
    ) % (_OPTIONVAR_MODULE_PATH, _OPTIONVAR_MODULE_PATH, func_name)


def _mel_escape(s):
    try:
        s = str(s)
    except Exception:
        return ''
    return s.replace('\\', '\\\\').replace('"', '\\"')


def _ensure_mel_procs():
    """创建用于 hotkey/nameCommand 的 MEL 过程，避免把长 python(...) 字符串直接塞进 nameCommand。"""
    try:
        mel_script = (
            'global proc ADV_PathMgr_OpenScene() { python("%s"); }\n'
            'global proc ADV_PathMgr_SaveScene() { python("%s"); }\n'
            'global proc ADV_PathMgr_SaveSceneAs() { python("%s"); }\n'
        ) % (
            _mel_escape(_py_entry('open_scene_dialog')),
            _mel_escape(_py_entry('smart_save')),
            _mel_escape(_py_entry('smart_save_as')),
        )
        mel.eval(mel_script)
        return True, ''
    except Exception as e:
        return False, str(e)


def _name_command_ensure(nc_name, mel_command, annotation=''):
    """确保 nameCommand 存在且指向指定 MEL 命令名。"""
    try:
        # Use cmds.deleteUI so missing objects don't print MEL errors to Script Editor.
        cmds.deleteUI(str(nc_name))
    except Exception:
        pass
    try:
        cmds.nameCommand(nc_name, annotation=annotation, command=str(mel_command))
        return True, ''
    except Exception as e1:
        # 兜底：直接走 MEL nameCommand
        try:
            a = _mel_escape(annotation or '')
            c = _mel_escape(mel_command or '')
            mel.eval('catch(`nameCommand -annotation "%s" -command "%s" %s`);' % (a, c, str(nc_name)))
            try:
                out = cmds.nameCommand(nc_name, q=True, annotation=True)
                if out is not None:
                    return True, ''
            except Exception:
                pass
        except Exception as e2:
            return False, '%s | %s' % (str(e1), str(e2))
        return False, str(e1)


def _ensure_editable_hotkey_set():
    """尽量确保当前 hotkeySet 可写（某些环境默认热键集不可编辑）。"""
    try:
        cur = cmds.hotkeySet(q=True, current=True) or ''
    except Exception:
        return False

    try:
        if cur and (not cmds.optionVar(exists=_OPTIONVAR_HOTKEYSET_BACKUP)):
            cmds.optionVar(sv=(_OPTIONVAR_HOTKEYSET_BACKUP, cur))
    except Exception:
        pass

    cur_lower = cur.lower() if isinstance(cur, str) else str(cur).lower()
    if cur_lower.startswith('maya_default'):
        target = 'ADV_PathMgr_HotkeySet'
        try:
            if not cmds.hotkeySet(target, exists=True):
                cmds.hotkeySet(target, source=cur)
            cmds.hotkeySet(target, e=True, current=True)
            return True
        except Exception:
            return False

    return True


def _hotkey_get(key, ctrl=False, shift=False, alt=False):
    try:
        return cmds.hotkey(k=str(key), q=True, name=True, alt=alt, ctl=ctrl, sht=shift) or ''
    except Exception:
        return ''


def _hotkey_set(key, name_cmd, ctrl=False, shift=False, alt=False):
    try:
        cmds.hotkey(k=str(key), name=str(name_cmd or ''), alt=alt, ctl=ctrl, sht=shift)
        return True
    except Exception:
        pass

    # 兜底：用 MEL hotkey（参考常见安装脚本做法）
    try:
        flags = []
        if ctrl:
            flags.append('-ctl')
        if shift:
            flags.append('-sht')
        if alt:
            flags.append('-alt')
        mel.eval('hotkey -keyShortcut "%s" %s -name "%s";' % (str(key), ' '.join(flags), _mel_escape(name_cmd or '')))
        return True
    except Exception:
        return False


def _hook_hotkeys():
    # 备份 & 覆盖 Ctrl+O / Ctrl+S / Ctrl+Shift+S
    try:
        if not cmds.optionVar(exists=_OPTIONVAR_HOTKEY_BACKUP):
            backup = {
                'ctrl_o': _hotkey_get('o', ctrl=True),
                'ctrl_s': _hotkey_get('s', ctrl=True),
                'ctrl_shift_s': _hotkey_get('s', ctrl=True, shift=True),
            }
            cmds.optionVar(sv=(_OPTIONVAR_HOTKEY_BACKUP, json.dumps(backup)))
    except Exception:
        pass

    ok = True
    fail = []

    if not _ensure_editable_hotkey_set():
        fail.append('hotkeySet not editable')

    mel_ok, mel_err = _ensure_mel_procs()
    if not mel_ok:
        ok = False
        fail.append('mel procs: %s' % mel_err)

    ok_nc, err = _name_command_ensure('ADV_PathMgr_OpenScene_NC', 'ADV_PathMgr_OpenScene', annotation='ADV PathMgr Open')
    if not ok_nc:
        ok = False
        fail.append('nameCommand Open: %s' % err)
    ok_nc, err = _name_command_ensure('ADV_PathMgr_SaveScene_NC', 'ADV_PathMgr_SaveScene', annotation='ADV PathMgr Save')
    if not ok_nc:
        ok = False
        fail.append('nameCommand Save: %s' % err)
    ok_nc, err = _name_command_ensure('ADV_PathMgr_SaveAs_NC', 'ADV_PathMgr_SaveSceneAs', annotation='ADV PathMgr Save As')
    if not ok_nc:
        ok = False
        fail.append('nameCommand SaveAs: %s' % err)

    if not _hotkey_set('o', 'ADV_PathMgr_OpenScene_NC', ctrl=True):
        ok = False
        fail.append('hotkey Ctrl+O')
    if not _hotkey_set('s', 'ADV_PathMgr_SaveScene_NC', ctrl=True):
        ok = False
        fail.append('hotkey Ctrl+S')
    if not _hotkey_set('s', 'ADV_PathMgr_SaveAs_NC', ctrl=True, shift=True):
        ok = False
        fail.append('hotkey Ctrl+Shift+S')

    _STATE['hotkeys_hooked'] = bool(ok)
    if not ok:
        try:
            cmds.optionVar(sv=(_OPTIONVAR_LAST_ERROR, 'Failed to hook hotkeys: %s' % ', '.join(fail)))
        except Exception:
            pass
    return bool(ok)


def _restore_hotkeys():
    try:
        if not cmds.optionVar(exists=_OPTIONVAR_HOTKEY_BACKUP):
            _STATE['hotkeys_hooked'] = False
            return False
        raw = cmds.optionVar(q=_OPTIONVAR_HOTKEY_BACKUP) or ''
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}

    ok = True
    ok = _hotkey_set('o', data.get('ctrl_o', ''), ctrl=True) and ok
    ok = _hotkey_set('s', data.get('ctrl_s', ''), ctrl=True) and ok
    ok = _hotkey_set('s', data.get('ctrl_shift_s', ''), ctrl=True, shift=True) and ok

    try:
        cmds.optionVar(remove=_OPTIONVAR_HOTKEY_BACKUP)
    except Exception:
        pass

    try:
        if cmds.optionVar(exists=_OPTIONVAR_HOTKEYSET_BACKUP):
            hs = cmds.optionVar(q=_OPTIONVAR_HOTKEYSET_BACKUP) or ''
            if hs:
                try:
                    cmds.hotkeySet(hs, e=True, current=True)
                except Exception:
                    pass
            cmds.optionVar(remove=_OPTIONVAR_HOTKEYSET_BACKUP)
    except Exception:
        pass

    _STATE['hotkeys_hooked'] = False
    return bool(ok)


def _get_main_file_menu():
    # 避免用 mel.eval 读 $gMainFileMenu（部分环境会在 Script Editor 打 MEL Syntax error）
    for cand in ('mainFileMenu', 'mainFileMenu1'):
        try:
            if cmds.menu(cand, exists=True):
                return cand
        except Exception:
            pass

    # 兜底：从 MayaWindow 的顶层菜单里按 label 查找
    try:
        menus = cmds.window('MayaWindow', q=True, menuArray=True) or []
    except Exception:
        menus = []

    for mn in menus:
        try:
            lab = cmds.menu(mn, q=True, label=True) or ''
        except Exception:
            continue
        nl = _norm_label(lab)
        if nl in ('file', u'文件'):
            return mn
    return None


def _norm_label(label):
    try:
        s = str(label)
    except Exception:
        return ''
    s = s.split('\t', 1)[0]
    s = s.replace(u'…', '...')
    return s.strip().lower()


def _find_file_menu_items():
    menu = _get_main_file_menu()
    if not menu:
        return {}
    try:
        items = cmds.menu(menu, q=True, ia=True) or []
    except Exception:
        items = []

    open_labels = {u'open scene...', u'open scene', u'open...', u'打开场景...', u'打开场景', u'打开...'}
    save_labels = {u'save scene', u'保存场景', u'保存'}
    saveas_labels = {u'save scene as...', u'save as...', u'场景另存为', u'另存为...', u'另存为'}

    found = {}
    for it in items:
        try:
            if not cmds.menuItem(it, q=True, exists=True):
                continue
            lab = cmds.menuItem(it, q=True, label=True)
        except Exception:
            continue
        nl = _norm_label(lab)
        if not nl:
            continue
        if 'open' not in found and nl in set([x.lower() for x in open_labels]):
            found['open'] = it
            continue
        if 'saveas' not in found and nl in set([x.lower() for x in saveas_labels]):
            found['saveas'] = it
            continue
        if 'save' not in found and nl in set([x.lower() for x in save_labels]):
            found['save'] = it
            continue
    return found


def _menuitem_get(it):
    try:
        cmd = cmds.menuItem(it, q=True, command=True)
    except Exception:
        cmd = None
    try:
        st = cmds.menuItem(it, q=True, sourceType=True)
    except Exception:
        st = None
    return {'cmd': cmd, 'st': st}


def _menuitem_set(it, cmd, st):
    try:
        cmds.menuItem(it, e=True, command=cmd, sourceType=st)
        return True
    except Exception:
        return False


def _hook_file_menu():
    found = _find_file_menu_items()
    if not found:
        try:
            cmds.optionVar(sv=(_OPTIONVAR_LAST_ERROR, 'File menu not found'))
        except Exception:
            pass
        return False

    # 备份一次
    try:
        if not cmds.optionVar(exists=_OPTIONVAR_MENU_BACKUP):
            backup = {}
            for k, it in found.items():
                backup[k] = {'item': it, 'data': _menuitem_get(it)}
            cmds.optionVar(sv=(_OPTIONVAR_MENU_BACKUP, json.dumps(backup)))
    except Exception:
        pass

    ok = True
    if 'open' in found:
        ok = _menuitem_set(found['open'], _py_entry('open_scene_dialog'), 'python') and ok
    if 'save' in found:
        ok = _menuitem_set(found['save'], _py_entry('smart_save'), 'python') and ok
    if 'saveas' in found:
        ok = _menuitem_set(found['saveas'], _py_entry('smart_save_as'), 'python') and ok

    _STATE['menu_hooked'] = bool(ok)
    if not ok:
        try:
            cmds.optionVar(sv=(_OPTIONVAR_LAST_ERROR, 'Failed to hook one or more File menu items'))
        except Exception:
            pass
    return bool(ok)


def _restore_file_menu():
    try:
        if not cmds.optionVar(exists=_OPTIONVAR_MENU_BACKUP):
            return False
        raw = cmds.optionVar(q=_OPTIONVAR_MENU_BACKUP) or ''
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}

    any_ok = False
    for _, info in (data or {}).items():
        try:
            it = info.get('item')
            d = info.get('data') or {}
            if it and cmds.menuItem(it, q=True, exists=True):
                if _menuitem_set(it, d.get('cmd'), d.get('st') or 'mel'):
                    any_ok = True
        except Exception:
            continue

    try:
        cmds.optionVar(remove=_OPTIONVAR_MENU_BACKUP)
    except Exception:
        pass

    _STATE['menu_hooked'] = False
    return any_ok


def debug_runtime_commands():
    """保留接口：返回 File 菜单 hook 状态（runTimeCommand 在部分版本不可改）。"""
    out = {
        'menu_hooked': bool(_STATE.get('menu_hooked')),
        'hotkeys_hooked': bool(_STATE.get('hotkeys_hooked')),
        'qt_shortcuts': sorted(list((_STATE.get('qt_shortcuts') or {}).keys())),
        'qt_key_filter': bool(_STATE.get('qt_key_filter') is not None),
        'native_key_filter': bool(_STATE.get('native_key_filter') is not None),
        'last_key_intercept': _STATE.get('last_key_intercept'),
        'last_qt_error': _STATE.get('last_qt_error'),
        'dialog_default_size': _DIALOG_DEFAULT_SIZE,
    }
    try:
        out['file_menu'] = _get_main_file_menu()
        out['file_menu_items'] = _find_file_menu_items()
    except Exception:
        pass
    try:
        out['hotkeySet_current'] = cmds.hotkeySet(q=True, current=True) or ''
    except Exception:
        out['hotkeySet_current'] = ''
    try:
        out['hotkeySet_backup'] = cmds.optionVar(q=_OPTIONVAR_HOTKEYSET_BACKUP) if cmds.optionVar(exists=_OPTIONVAR_HOTKEYSET_BACKUP) else ''
    except Exception:
        out['hotkeySet_backup'] = ''
    try:
        if cmds.optionVar(exists=_OPTIONVAR_LAST_ERROR):
            out['last_error'] = cmds.optionVar(q=_OPTIONVAR_LAST_ERROR)
    except Exception:
        pass
    return out


def open_scene_dialog():
    start_dir = _preferred_start_dir()

    picked = _qt_pick_existing_file(
        caption=u'打开场景',
        start_dir=start_dir,
        name_filter=['Maya ASCII Files (*.ma)', 'Maya Binary Files (*.mb)', 'Maya Files (*.ma *.mb)'],
    )

    # User cancelled -> stop here (do not fall back)
    if not picked and not (_STATE.get('last_qt_error') or ''):
        return None

    if not picked:
        try:
            sel = cmds.fileDialog2(
                fileMode=1,
                caption=u'打开场景',
                fileFilter='Maya Files (*.ma *.mb);;Maya ASCII Files (*.ma);;Maya Binary Files (*.mb);;All Files (*.*)',
                startingDirectory=start_dir,
                dialogStyle=int(cmds.optionVar(q=_OPTIONVAR_DIALOG_STYLE)) if cmds.optionVar(exists=_OPTIONVAR_DIALOG_STYLE) else 2,
            )
        except Exception:
            sel = None

        if not sel:
            return None

        picked = sel[0]
        if not picked:
            return None

    path = picked

    # Maya-like: only prompt when user actually chose a file to open
    if path and not _prompt_save_if_modified():
        return None

    _set_last_dir_from_path(path)

    return open_scene(path)


def open_scene(path):
    try:
        cmds.file(path, o=True, f=True, prompt=False)
        return path
    except Exception as e:
        try:
            cmds.warning(u'打开失败: %s' % str(e))
        except Exception:
            pass
        return None


def smart_save():
    try:
        current_file = cmds.file(q=True, sceneName=True) or ''
    except Exception:
        current_file = ''

    if current_file:
        try:
            cmds.file(save=True)
            return current_file
        except Exception as e:
            try:
                cmds.warning(u'保存失败: %s' % str(e))
            except Exception:
                pass
            return None

    return smart_save_as()


def smart_save_as():
    start_dir = _preferred_start_dir()

    picked = _qt_pick_save_file(
        caption=u'场景另存为',
        start_dir=start_dir,
        name_filter=['Maya ASCII Files (*.ma)', 'Maya Binary Files (*.mb)', 'Maya Files (*.ma *.mb)'],
        default_name=None,
    )

    # User cancelled -> stop here (do not fall back)
    if not picked and not (_STATE.get('last_qt_error') or ''):
        return None

    if not picked:
        try:
            sel = cmds.fileDialog2(
                fileMode=0,
                caption=u'场景另存为',
                fileFilter='Maya ASCII Files (*.ma);;Maya Binary Files (*.mb);;All Files (*.*)',
                startingDirectory=start_dir,
                dialogStyle=int(cmds.optionVar(q=_OPTIONVAR_DIALOG_STYLE)) if cmds.optionVar(exists=_OPTIONVAR_DIALOG_STYLE) else 2,
            )
        except Exception:
            sel = None

        if not sel:
            return None

        picked = sel[0]
        if not picked:
            return None

    path = picked

    # Apply extension based on selected filter if user didn't type one
    try:
        pl = str(path).lower()
        if not (pl.endswith('.ma') or pl.endswith('.mb')):
            sf = str(_LAST_QT_SELECTED_FILTER or '').lower()
            if '.mb' in sf:
                path += '.mb'
            else:
                path += '.ma'
    except Exception:
        pass

    _set_last_dir_from_path(path)

    path_l = path.lower()
    if path_l.endswith('.mb'):
        file_type = 'mayaBinary'
    else:
        if not path_l.endswith('.ma'):
            path += '.ma'
        file_type = 'mayaAscii'

    try:
        cmds.file(rename=path)
        cmds.file(save=True, type=file_type)
        return path
    except Exception as e:
        try:
            cmds.warning(u'另存为失败: %s' % str(e))
        except Exception:
            pass
        return None


class _DropFilter(QtCore.QObject):
    def eventFilter(self, obj, event):
        try:
            et = event.type()
        except Exception:
            return False

        if et not in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove, QtCore.QEvent.Drop):
            return False

        mime = getattr(event, 'mimeData', None)
        if not callable(mime):
            return False
        md = event.mimeData()
        if not md or not md.hasUrls():
            return False

        paths = []
        for url in md.urls() or []:
            try:
                if not url.isLocalFile():
                    continue
                p = url.toLocalFile()
                if not p:
                    continue
                pl = p.lower()
                if pl.endswith('.ma') or pl.endswith('.mb'):
                    paths.append(p)
            except Exception:
                continue

        if not paths:
            return False

        # 只要是 ma/mb，我们就接管
        if et in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove):
            try:
                event.acceptProposedAction()
            except Exception:
                pass
            return True

        # Drop
        try:
            choice = _show_drop_menu(paths)
        except Exception as e:
            try:
                cmds.warning(u'文件拖拽菜单弹出失败: %s' % str(e))
            except Exception:
                pass
            choice = None
        if choice == 'open':
            open_scene(paths[0])
        elif choice == 'import':
            for p in paths:
                _import_scene(p)
        else:
            # 用户取消：什么也不做
            pass

        try:
            event.acceptProposedAction()
        except Exception:
            pass
        return True


def _import_scene(path):
    try:
        cmds.file(path, i=True, type='mayaAscii' if path.lower().endswith('.ma') else 'mayaBinary', ignoreVersion=True, ra=True, mergeNamespacesOnClash=False, namespace=':')
        return path
    except Exception as e:
        try:
            cmds.warning(u'导入失败: %s' % str(e))
        except Exception:
            pass
        return None


def _show_drop_menu(paths):
    # 多文件拖入时，Open 仅对第一个生效。
    app = QtWidgets.QApplication.instance()

    if app is not None:
        try:
            pos = QtGui.QCursor.pos()
        except Exception:
            pos = QtCore.QPoint(0, 0)

        try:
            menu = QtWidgets.QMenu()
            # Keep English labels to match existing behavior.
            a_open = menu.addAction('Open File')
            a_import = menu.addAction('Import File')
            act = menu.exec_(pos)

            if act == a_open:
                return 'open'
            if act == a_import:
                return 'import'
            return None
        except Exception:
            pass

    # Fallback when Qt menu cannot pop in current drag-drop context.
    try:
        b_open = u'Open File'
        b_import = u'Import File'
        b_cancel = u'Cancel'
        res = cmds.confirmDialog(
            title=u'文件拖拽',
            message=u'请选择操作：Open File 或 Import File',
            button=[b_open, b_import, b_cancel],
            defaultButton=b_open,
            cancelButton=b_cancel,
            dismissString=b_cancel
        )
        if res == b_open:
            return 'open'
        if res == b_import:
            return 'import'
    except Exception:
        pass
    return None


def _is_cn():
    try:
        lang = cmds.about(uiLanguage=True) or ''
        lang = str(lang).lower()
        return ('zh' in lang) or ('chinese' in lang)
    except Exception:
        return True


def _install_drop_handler():
    # 避免重复安装
    if _STATE.get('drop_filter') is not None:
        return

    app = QtWidgets.QApplication.instance()
    if not app:
        return

    try:
        from shiboken2 import wrapInstance
    except Exception:
        try:
            from shiboken6 import wrapInstance  # type: ignore
        except Exception:
            try:
                from shiboken import wrapInstance  # type: ignore
            except Exception:
                wrapInstance = None

    try:
        import maya.OpenMayaUI as omui
        ptr = omui.MQtUtil.mainWindow()
    except Exception:
        ptr = None

    if not ptr or wrapInstance is None:
        return

    try:
        main = wrapInstance(int(ptr), QtWidgets.QWidget)
    except Exception:
        try:
            main = wrapInstance(long(ptr), QtWidgets.QWidget)  # type: ignore[name-defined]
        except Exception:
            return

    try:
        main.setAcceptDrops(True)
    except Exception:
        pass

    f = _DropFilter(app)
    try:
        app.installEventFilter(f)
    except Exception:
        return

    _STATE['drop_filter'] = f
    _STATE['drop_target'] = app


def _uninstall_drop_handler():
    f = _STATE.get('drop_filter')
    w = _STATE.get('drop_target')
    if f is None or w is None:
        _STATE['drop_filter'] = None
        _STATE['drop_target'] = None
        return

    try:
        w.removeEventFilter(f)
    except Exception:
        pass

    _STATE['drop_filter'] = None
    _STATE['drop_target'] = None


