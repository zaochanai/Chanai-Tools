# -*- coding: utf-8 -*-
"""
maya_batch_fbx_exporter.py  v2.5
Maya Batch FBX Exporter - Dark Qt UI (ADV style)

用法:
    import maya_batch_fbx_exporter as bfbx
    bfbx.create_ui()

Author: ZaoChaNai
"""

import os
import maya.cmds as cmds
import maya.mel as mel


# ============================================================================
# Global state dictionary (replace legacy globals)
# ============================================================================
_STATE = {
    "skin_objects":   [],
    "bone_objects":   [],
    "anim_files":     [],
    "skin_files":     [],
    "clean_invalid":  False,
    "fbx_shapes":     True,
    "fbx_embed":      False,
    "fbx_children":   False,
    "fbx_input_conn": False,
    "fbx_up_axis":    "Y",
    "fbx_auto_units": True,
    "fbx_file_units": "cm",
    "add_root":       False,
    "adv_to_ue":      False,
}

_LANG_OPT = "ADV_BatchFBX_Lang"
_LANG = "CN"
_LANG_TXT = {
    "title": {"CN": u"批量 FBX 导出工具", "EN": u"Batch FBX Exporter"},
    "sec_file_queue": {"CN": u"文件队列", "EN": u"File Queue"},
    "anim_group": {"CN": u"动画文件  (Animation)", "EN": u"Anim Files  (Animation)"},
    "skin_group": {"CN": u"Skin 文件  (Skin + Bone)", "EN": u"Skin Files  (Skin + Bone)"},
    "anim_pick": {"CN": u"选择动画 Maya 文件", "EN": u"Select animation Maya files"},
    "skin_pick": {"CN": u"选择 Skin Maya 文件", "EN": u"Select skin Maya files"},
    "btn_add": {"CN": u"+ 添加", "EN": u"+ Add"},
    "btn_remove": {"CN": u"移除", "EN": u"Remove"},
    "btn_clear": {"CN": u"清空", "EN": u"Clear"},
    "sec_scene": {"CN": u"场景记录", "EN": u"Scene Records"},
    "grp_scene": {"CN": u"记录场景对象（在当前打开的参考场景中操作）", "EN": u"Record scene objects (in current opened ref scene)"},
    "not_recorded": {"CN": u"尚未记录", "EN": u"Not recorded"},
    "btn_record": {"CN": u"记录（按当前选择）", "EN": u"Record (from selection)"},
    "btn_select": {"CN": u"选中", "EN": u"Select"},
    "warn_select_first": {"CN": u"请先选择对象", "EN": u"Please select objects first"},
    "warn_missing_recorded": {"CN": u"场景中不存在已记录对象", "EN": u"Recorded objects do not exist in scene"},
    "tip_skin_rec": {"CN": u"选中 Skin 网格后点击", "EN": u"Select skin meshes then click"},
    "tip_skin_sel": {"CN": u"选中已记录的 Skin 对象", "EN": u"Select recorded skin objects"},
    "tip_bone_rec": {"CN": u"选中骨骼后点击", "EN": u"Select bones then click"},
    "tip_bone_sel": {"CN": u"选中已记录的 Bone 对象", "EN": u"Select recorded bone objects"},
    "sec_out": {"CN": u"输出路径模板", "EN": u"Output Path Template"},
    "grp_out": {"CN": u"输出路径模板", "EN": u"Output Path Template"},
    "tag_name": {"CN": u"文件名", "EN": u"FileName"},
    "tag_parent": {"CN": u"父文件夹", "EN": u"ParentFolder"},
    "tag_proj": {"CN": u"工程名", "EN": u"ProjectName"},
    "btn_browse": {"CN": u"浏览", "EN": u"Browse"},
    "tip_insert": {"CN": u"插入: ", "EN": u"Insert: "},
    "tip_choose_out": {"CN": u"选择输出目录", "EN": u"Choose output folder"},
    "dlg_choose_out": {"CN": u"选择输出文件夹", "EN": u"Choose output folder"},
    "sec_fbx": {"CN": u"FBX 导出设置", "EN": u"FBX Export Settings"},
    "grp_fbx": {"CN": u"导出选项", "EN": u"Export Options"},
    "shapes": {"CN": u"变形模型", "EN": u"Shapes"},
    "embed": {"CN": u"镶入媒体", "EN": u"Embed Media"},
    "children": {"CN": u"包含子对象", "EN": u"Include Children"},
    "input": {"CN": u"输入链接", "EN": u"Input Connections"},
    "up_axis": {"CN": u"上轴:", "EN": u"Up Axis:"},
    "auto_units": {"CN": u"自动单位", "EN": u"Auto Units"},
    "manual_units": {"CN": u"手动单位:", "EN": u"Manual Units:"},
    "add_root": {"CN": u"添加 Root", "EN": u"Add Root"},
    "adv_to_ue": {"CN": u"ADV -> UE", "EN": u"ADV -> UE"},
    "clean_invalid": {"CN": u"清理无效骨骼", "EN": u"Clean Invalid Bones"},
    "tip_add_root": {"CN": u"导出时临时插入 root 根骨骼（优先 ADV 接口）", "EN": u"Insert temporary root joint on export (prefer ADV API)"},
    "tip_adv_ue": {"CN": u"调用 ADV asExportRenameToUnreal 转 UE 命名", "EN": u"Use ADV asExportRenameToUnreal to rename bones for UE mannequin"},
    "tip_clean_invalid": {"CN": u"Skin 导出时移除 skinCluster 中无权重骨骼", "EN": u"Remove zero-weight influences from skinCluster during skin export"},
    "log": {"CN": u"日志", "EN": u"Log"},
    "clear_log": {"CN": u"清空日志", "EN": u"Clear Log"},
    "export_all": {"CN": u"▶   输出全部 FBX", "EN": u"▶   Export All FBX"},
    "tip_export_all": {"CN": u"开始批量导出所有队列文件", "EN": u"Start batch export for all queued files"},
    "lang": {"CN": u"语言", "EN": u"Lang"},
    "error_set_output": {"CN": u"[错误] 请设置输出路径模板", "EN": u"[Error] Please set output path template"},
    "error_qt_missing": {"CN": u"未找到 PySide2/PySide6，无法启动 Qt UI", "EN": u"PySide2/PySide6 not found, cannot launch Qt UI"},
    "error_empty_queue": {"CN": u"[错误] 文件队列为空", "EN": u"[Error] File queue is empty"},
    "error_record_bone": {"CN": u"[错误] 请先记录 Bone 对象", "EN": u"[Error] Please record Bone objects first"},
    "start_batch": {"CN": u"开始批量导出", "EN": u"Start batch export"},
    "anim_tag": {"CN": u"动画", "EN": u"Anim"},
    "skin_tag": {"CN": u"Skin", "EN": u"Skin"},
    "no_bones": {"CN": u"未找到骨骼，跳过", "EN": u"No bones found, skipped"},
    "no_skin_bone": {"CN": u"未找到 Skin/Bone，跳过", "EN": u"No Skin/Bone found, skipped"},
    "no_export_obj": {"CN": u"未找到导出对象", "EN": u"No export objects found"},
    "fbx_failed": {"CN": u"FBX 导出失败", "EN": u"FBX export failed"},
    "exception": {"CN": u"异常", "EN": u"Exception"},
    "done": {"CN": u"完成  成功:%d  失败:%d  (动画:%d / Skin:%d)", "EN": u"Done  OK:%d  FAIL:%d  (Anim:%d / Skin:%d)"},
    "dlg_done_title": {"CN": u"导出完成", "EN": u"Export Finished"},
    "dlg_done_msg": {"CN": u"全部完成！\n\n动画: %d 个\nSkin: %d 个\n成功: %d  失败: %d", "EN": u"All done!\n\nAnim: %d items\nSkin: %d items\nOK: %d  FAIL: %d"},
    "dlg_issue_title": {"CN": u"导出完成（有问题）", "EN": u"Export Finished (With Issues)"},
    "dlg_issue_msg": {"CN": u"动画: %d 个  Skin: %d 个\n成功: %d  失败: %d", "EN": u"Anim: %d items  Skin: %d items\nOK: %d  FAIL: %d"},
    "dlg_more": {"CN": u"\n... 还有 %d 个问题", "EN": u"\n... and %d more issues"},
    "started": {"CN": u"批量 FBX 导出工具 v2.5 已启动", "EN": u"Batch FBX Exporter v2.5 started"},
}

_REF_BONES = []
_UI_REFS   = {}   # {"log": QTextEdit widget}


def _lang_get():
    global _LANG
    try:
        if cmds.optionVar(exists=_LANG_OPT):
            v = str(cmds.optionVar(q=_LANG_OPT) or "").upper()
            if v in ("CN", "EN"):
                _LANG = v
    except Exception:
        pass
    return _LANG


def _lang_set(v):
    global _LANG
    nv = str(v or "").upper()
    if nv not in ("CN", "EN"):
        return
    _LANG = nv
    try:
        cmds.optionVar(sv=(_LANG_OPT, nv))
    except Exception:
        pass


def _t(key):
    lang = _lang_get()
    data = _LANG_TXT.get(key, {})
    return data.get(lang, data.get("EN", key))


def _fmt_files(n):
    if _lang_get() == "CN":
        return u"%d 个文件" % int(n)
    return u"%d files" % int(n)


def _fmt_objs(n):
    if _lang_get() == "CN":
        return u"%d 个对象" % int(n)
    return u"%d objects" % int(n)


def _clamp01(v):
    try:
        x = float(v)
    except Exception:
        x = 0.0
    if x > 1.0:
        x = x / 255.0
    if x < 0.0:
        x = 0.0
    if x > 1.0:
        x = 1.0
    return x


def _rgb_to_hex(rgb):
    r = int(_clamp01(rgb[0]) * 255)
    g = int(_clamp01(rgb[1]) * 255)
    b = int(_clamp01(rgb[2]) * 255)
    return "#%02X%02X%02X" % (r, g, b)


def _optvar_rgb(name, default_rgb):
    try:
        if cmds.optionVar(exists=name):
            val = cmds.optionVar(q=name)
            if isinstance(val, (list, tuple)) and len(val) >= 3:
                return (float(val[0]), float(val[1]), float(val[2]))
    except Exception:
        pass
    return tuple(default_rgb)


def _adv_qstyle_palette():
    return {
        "bg": _rgb_to_hex(_optvar_rgb("ADV_QStyleBgColor", (0.18, 0.19, 0.21))),
        "accent": _rgb_to_hex(_optvar_rgb("ADV_QStyleAccentColor", (0.184, 0.502, 0.929))),
        # Use much brighter button colors for better visibility (matching left panel style)
        "btn": "#4A4F5B",  # Much brighter base button color
        "btn_hover": "#5A6170",  # Brighter hover state
        "btn_pressed": "#3A3D46",  # Pressed state
    }


def _adv_fast_qss(root_object_name):
    """Prefer reusing ADV Fast Select's exact QStyle stylesheet."""
    try:
        import sys
        here = os.path.abspath(__file__)
        base_dir = os.path.dirname(os.path.dirname(here))
        if base_dir and base_dir not in sys.path:
            sys.path.insert(0, base_dir)
    except Exception:
        pass

    mod = None
    try:
        import sys
        mod = sys.modules.get("ADV_fast_select")
    except Exception:
        mod = None
    if mod is None:
        try:
            import ADV_fast_select as mod  # noqa: F401
        except Exception:
            mod = None
    if mod is None:
        return ""

    fn = getattr(mod, "_adv_qstyle_stylesheet", None)
    if not callable(fn):
        return ""

    try:
        return str(fn(root_object_name=str(root_object_name), allow_bg_image=False) or "")
    except TypeError:
        try:
            return str(fn(root_object_name=str(root_object_name)) or "")
        except Exception:
            return ""
    except Exception:
        return ""


# ============================================================================
# 日志
# ============================================================================
def _log(msg):
    print(msg)
    try:
        w = _UI_REFS.get("log")
        if w is not None:
            w.append(str(msg))
            sb = w.verticalScrollBar()
            sb.setValue(sb.maximum())
    except Exception:
        pass


# ============================================================================
# 核心工具函数
# ============================================================================
def _load_fbx_plugin():
    if not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
        try:
            cmds.loadPlugin("fbxmaya")
        except Exception:
            _log(u"[错误] 无法加载 FBX 插件")
            return False
    return True


def _scene_name():
    path = cmds.file(query=True, sceneName=True) or ""
    name = os.path.basename(path)
    for ext in (".ma", ".mb", ".MA", ".MB"):
        name = name.replace(ext, "")
    return name or "untitled"


def _resolve_objects(names):
    out, seen = [], set()
    for n in (names or []):
        if n in seen:
            continue
        if cmds.objExists(n):
            out.append(n); seen.add(n); continue
        short = n.split("|")[-1]
        matches = cmds.ls(short, long=True) or []
        if matches and matches[0] not in seen:
            out.append(matches[0]); seen.add(matches[0])
    return out


def _find_root(joint):
    root = joint
    while cmds.objExists(root):
        parents = cmds.listRelatives(root, parent=True, fullPath=True) or []
        if not parents or cmds.nodeType(parents[0]) != "joint":
            break
        root = parents[0]
    return root


def _joints_from_roots(roots):
    out, seen = [], set()
    for r in (roots or []):
        if not cmds.objExists(r):
            continue
        if r not in seen:
            out.append(r); seen.add(r)
        for d in (cmds.listRelatives(r, allDescendents=True, type="joint", fullPath=True) or []):
            if d not in seen:
                out.append(d); seen.add(d)
    return out


def _expand_skeleton(joints):
    if not joints:
        return []
    roots, seen_r = [], set()
    for j in joints:
        r = _find_root(j)
        if r not in seen_r:
            roots.append(r); seen_r.add(r)
    return _joints_from_roots(roots)


def _resolve_bones():
    resolved = _resolve_objects(_STATE["bone_objects"])
    joints = []
    for obj in resolved:
        try:
            if cmds.nodeType(obj) == "joint":
                joints.append(obj)
            else:
                joints.extend(cmds.listRelatives(obj, allDescendents=True, type="joint", fullPath=True) or [])
        except Exception:
            pass
    return _expand_skeleton(joints)


# ============================================================================
# ADV / Root helpers
# ============================================================================
def _adv_ok():
    try:
        return mel.eval("exists asCreateGameEngineRootMotion") == 1
    except Exception:
        return False


def _has_root():
    return cmds.objExists("root") and cmds.nodeType("root") == "joint"


def _add_root():
    if _has_root():
        _log(u"[Root] root 已存在，跳过"); return None, False
    if _adv_ok():
        try:
            mel.eval("asCreateGameEngineRootMotion")
            _log(u"[Root] ADV 官方创建成功"); return "root", True
        except Exception as e:
            _log(u"[Root] ADV failed, fallback to builtin: " + str(e))
    cmds.select(clear=True)
    root = cmds.joint(name="root")
    for a in ("jointOrientX", "jointOrientY", "jointOrientZ"):
        cmds.setAttr(root + "." + a, 0)
    ds = next((x for x in ("DeformationSystem", "|Group|DeformationSystem") if cmds.objExists(x)), None)
    if ds:
        kids = cmds.listRelatives(ds, children=True, type="joint") or []
        cmds.parent(root, ds)
        for k in kids:
            try: cmds.parent(k, root)
            except Exception: pass
    else:
        for j in (cmds.ls(type="joint", long=True) or []):
            if j == "|root": continue
            p = cmds.listRelatives(j, parent=True, fullPath=True)
            if not p or cmds.nodeType(p[0]) != "joint":
                try: cmds.parent(j, root)
                except Exception: pass
    _log(u"[Root] 内置实现完成"); return root, False


def _remove_root(use_adv=False):
    if not cmds.objExists("root"): return
    if use_adv and _adv_ok():
        try: mel.eval("asDeleteGameEngineRootMotion"); return
        except Exception: pass
    ds = next((x for x in ("DeformationSystem", "|Group|DeformationSystem") if cmds.objExists(x)), None)
    for c in (cmds.listRelatives("root", children=True, type="joint", fullPath=True) or []):
        try:
            if ds and cmds.objExists(ds): cmds.parent(c, ds)
            else: cmds.parent(c, world=True)
        except Exception: pass
    cmds.delete("root")


def _adv_ue_rename():
    if not _adv_ok(): return False
    try: mel.eval("asExportRenameToUnreal"); return True
    except Exception: return False


def _adv_ue_restore():
    if not _adv_ok(): return
    try: mel.eval("asExportRenameRestore")
    except Exception: pass


# ============================================================================
# FBX 导出核心
# ============================================================================
def _export_fbx(objects, filepath, with_anim=False, start=None, end=None):
    if not objects:
        _log(u"[错误] 无可导出对象"); return False
    cmds.select(objects, replace=True)
    s = _STATE
    mel.eval("FBXExportIncludeChildren -v %s" % ("true" if s["fbx_children"] else "false"))
    mel.eval("FBXExportInputConnections -v %s" % ("true" if s["fbx_input_conn"] else "false"))
    mel.eval("FBXExportEmbeddedTextures -v %s" % ("true" if s["fbx_embed"] else "false"))
    mel.eval("FBXExportUpAxis %s" % s["fbx_up_axis"])
    if s["fbx_auto_units"]:
        mel.eval('FBXExportConvertUnitString "cm"')
        mel.eval("FBXExportScaleFactor 1")
    else:
        mel.eval('FBXExportConvertUnitString "%s"' % s["fbx_file_units"])
    if with_anim:
        mel.eval("FBXExportBakeComplexAnimation -v true")
        mel.eval("FBXExportBakeComplexStart -v %d" % int(start))
        mel.eval("FBXExportBakeComplexEnd -v %d" % int(end))
        mel.eval("FBXExportBakeComplexStep -v 1")
        mel.eval("FBXExportBakeResampleAnimation -v true")
        mel.eval("FBXExportAnimationOnly -v false")
        mel.eval("FBXExportSkins -v false")
        mel.eval("FBXExportShapes -v false")
    else:
        mel.eval("FBXExportBakeComplexAnimation -v false")
        mel.eval("FBXExportAnimationOnly -v false")
        mel.eval("FBXExportSkins -v true")
        mel.eval("FBXExportShapes -v %s" % ("true" if s["fbx_shapes"] else "false"))
    fp = filepath.replace("\\", "/")
    try:
        mel.eval('FBXExport -f "%s" -s' % fp)
        _log(u"  [OK] " + filepath); return True
    except Exception as e:
        _log(u"  [FAIL] " + str(e)); return False


def _parse_path(pattern, source):
    file_name = os.path.splitext(os.path.basename(source))[0]
    parent    = os.path.dirname(source)
    proj      = file_name.split("@")[0] if "@" in file_name else file_name
    p = pattern.replace("<%FileName%>", file_name)
    p = p.replace("<%ParentFolder%>", parent)
    p = p.replace("<%ProjectName%>", proj)
    return p


# ============================================================================
# Batch export core
# ============================================================================
def run_export_all(output_pattern):
    global _REF_BONES
    if not _load_fbx_plugin():
        return
    if not output_pattern.strip():
        _log(_t("error_set_output"))
        return
    if not _STATE["anim_files"] and not _STATE["skin_files"]:
        _log(_t("error_empty_queue"))
        return
    if not _STATE["bone_objects"]:
        _log(_t("error_record_bone"))
        return

    _REF_BONES = []
    ok_cnt = fail_cnt = anim_cnt = skin_cnt = 0
    problems = []
    _log(u"\n" + "=" * 48)
    _log(_t("start_batch"))
    _log(u"=" * 48)

    for fp in _STATE["anim_files"]:
        _log(u"\n[%s] %s" % (_t("anim_tag"), os.path.basename(fp)))
        try:
            cmds.file(fp, open=True, force=True)
            sn = _scene_name()
            joints = _resolve_bones()
            if not joints:
                _log(u"  " + _t("no_bones"))
                problems.append((sn, _t("anim_tag"), _t("no_bones")))
                fail_cnt += 1
                continue

            sf = cmds.playbackOptions(query=True, minTime=True)
            ef = cmds.playbackOptions(query=True, maxTime=True)
            out_dir = _parse_path(output_pattern, fp)
            if not os.path.exists(out_dir):
                os.makedirs(out_dir)
            fbx_path = os.path.join(out_dir, sn + ".fbx")

            renamed = False
            if _STATE["adv_to_ue"]:
                renamed = _adv_ue_rename()
            if renamed:
                joints = _resolve_bones()

            rc = aru = None
            if _STATE["add_root"] and not _has_root():
                rc, aru = _add_root()
                if rc:
                    joints = _resolve_bones()
                    if rc not in joints:
                        joints = [rc] + list(joints)

            success = _export_fbx(joints, fbx_path, with_anim=True, start=sf, end=ef)
            if rc:
                _remove_root(aru)
            if renamed:
                _adv_ue_restore()

            if success:
                ok_cnt += 1
                anim_cnt += 1
            else:
                fail_cnt += 1
                problems.append((sn, _t("anim_tag"), _t("fbx_failed")))
        except Exception as e:
            _log(u"  %s: %s" % (_t("exception"), str(e)))
            problems.append((os.path.basename(fp), _t("anim_tag"), str(e)))
            fail_cnt += 1

    for fp in _STATE["skin_files"]:
        _log(u"\n[%s] %s" % (_t("skin_tag"), os.path.basename(fp)))
        try:
            cmds.file(fp, open=True, force=True)
            sn = _scene_name()
            skins = _resolve_objects(_STATE["skin_objects"])
            joints = _resolve_bones()
            if not skins and not joints:
                _log(u"  " + _t("no_skin_bone"))
                problems.append((sn, _t("skin_tag"), _t("no_export_obj")))
                fail_cnt += 1
                continue

            if _STATE["clean_invalid"] and skins:
                for mesh in skins:
                    try:
                        for sh in (cmds.listRelatives(mesh, shapes=True, fullPath=True) or []):
                            hist = cmds.listHistory(sh, pruneDagObjects=True) or []
                            for sc in (cmds.ls(hist, type="skinCluster") or []):
                                cmds.skinCluster(sc, edit=True, removeUnusedInfluence=True)
                    except Exception:
                        pass

            out_dir = _parse_path(output_pattern, fp)
            if not os.path.exists(out_dir):
                os.makedirs(out_dir)
            fbx_path = os.path.join(out_dir, sn + ".fbx")

            renamed = False
            if _STATE["adv_to_ue"]:
                renamed = _adv_ue_rename()
            if renamed:
                joints = _resolve_bones()

            rc = aru = None
            if _STATE["add_root"] and not _has_root():
                rc, aru = _add_root()
                if rc:
                    joints = _resolve_bones()

            exp_objs = list(skins) + list(joints)
            if rc and rc not in exp_objs:
                exp_objs = [rc] + exp_objs

            success = _export_fbx(exp_objs, fbx_path, with_anim=False)
            if rc:
                _remove_root(aru)
            if renamed:
                _adv_ue_restore()

            if success:
                ok_cnt += 1
                skin_cnt += 1
            else:
                fail_cnt += 1
                problems.append((sn, _t("skin_tag"), _t("fbx_failed")))
        except Exception as e:
            _log(u"  %s: %s" % (_t("exception"), str(e)))
            problems.append((os.path.basename(fp), _t("skin_tag"), str(e)))
            fail_cnt += 1

    _log(u"\n" + "=" * 48)
    _log(_t("done") % (ok_cnt, fail_cnt, anim_cnt, skin_cnt))
    _log(u"=" * 48)
    _show_result_dialog(ok_cnt, fail_cnt, anim_cnt, skin_cnt, problems)


def _show_result_dialog(ok, fail, anim, skin, problems):
    try:
        from PySide2 import QtWidgets
    except ImportError:
        from PySide6 import QtWidgets

    if not problems:
        QtWidgets.QMessageBox.information(
            None,
            _t("dlg_done_title"),
            _t("dlg_done_msg") % (anim, skin, ok, fail),
        )
    else:
        detail = u"\n".join(u"[%s] %s  -> %s" % t for t in problems[:30])
        if len(problems) > 30:
            detail += _t("dlg_more") % (len(problems) - 30)
        box = QtWidgets.QMessageBox(None)
        box.setWindowTitle(_t("dlg_issue_title"))
        box.setText(_t("dlg_issue_msg") % (anim, skin, ok, fail))
        box.setDetailedText(detail)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.exec_()


def create_ui():
    """Create and show dark Qt UI (ADV style)"""
    _lang_get()
    print("=" * 60)
    print("DEBUG: maya_batch_fbx_exporter v2.5 - UI LOADING")
    print("DEBUG: Code version with ADV/Biped style palette")
    print("=" * 60)

    try:
        from PySide2 import QtWidgets, QtCore
        import shiboken2 as _sb
    except ImportError:
        try:
            from PySide6 import QtWidgets, QtCore
            import shiboken6 as _sb
        except ImportError:
            cmds.warning(u"[BatchFBX] " + _t("error_qt_missing"))
            return

    from maya import OpenMayaUI as omui

    WIN_OBJ = "AdvBatchFBXQtWin"

    def _maya_win():
        ptr = omui.MQtUtil.mainWindow()
        return _sb.wrapInstance(int(ptr), QtWidgets.QWidget) if ptr else None

    # Close existing window safely
    for w in QtWidgets.QApplication.allWidgets():
        if w.objectName() == WIN_OBJ:
            try:
                w.close()
                w.deleteLater()
            except Exception:
                pass

    # Get DPI scale safely
    _scale = 1.0
    try:
        app = QtWidgets.QApplication.instance()
        if app:
            scr = app.primaryScreen()
            if scr:
                dpi = scr.logicalDotsPerInch()
                if dpi:
                    _scale = max(1.0, min(2.0, dpi / 96.0))
    except Exception:
        _scale = 1.0

    def px(v):
        return max(1, int(round(v * _scale)))

    _pal = _adv_qstyle_palette()
    BG = _pal["bg"]
    BG_D = "#1F2127"
    BORDER = "#14151A"
    BTN = _pal["btn"]
    BTN_H = _pal["btn_hover"]
    BTN_P = _pal["btn_pressed"]
    ACC = _pal["accent"]
    ACC2 = _pal["accent"]
    TEXT = "#D8D8D8"
    SUBTEXT = "#9AA0AA"
    SEP = "#3A3D46"

    SS = """
    QDialog, QWidget {{ background: {bg}; color: {tx}; font-size: {fs}px; }}
    QLabel  {{ background: transparent; color: {tx}; }}
    QLabel#TitleLbl {{ font-size: {fsh}px; font-weight: 700; }}
    QLabel#SecLbl   {{ font-size: {fsb}px; font-weight: 600; color: {acc}; padding: 2px 0; }}
    QLabel#SubLbl   {{ color: {sub}; font-size: {fss}px; }}
    QGroupBox {{
        border: 1px solid {sep}; border-radius: {r}px;
        margin-top: {gm}px; padding-top: {gp}px;
        font-weight: 600; color: {tx}; background: transparent;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: {r}px; padding: 0 4px; background: transparent; }}
    QPushButton {{
        background: {btn};
        border: 1px solid #1E2026; border-radius: {r}px;
        padding: 6px 10px; min-height: {bh}px; color: {tx};
    }}
    QPushButton:hover   {{
        background: {btn_h};
    }}
    QPushButton:pressed {{
        background: {btn_p};
    }}
    QPushButton:disabled {{ color: {sub}; background: {bg_d}; }}
    QListWidget {{
        background: {bg_d}; border: 1px solid {border}; border-radius: {r}px;
        color: {tx}; outline: 0;
    }}
    QListWidget::item {{ padding: 2px 4px; }}
    QListWidget::item:selected {{ background: {acc2}; color: #fff; }}
    QListWidget::item:hover    {{ background: {btn_h}; }}
    QLineEdit {{
        background: {bg_d}; border: 1px solid {border}; border-radius: {r}px;
        padding: 3px 6px; color: {tx};
    }}
    QLineEdit:focus {{ border: 1px solid {acc}; }}
    QCheckBox {{ spacing: 6px; background: transparent; color: {tx}; }}
    QCheckBox::indicator {{
        width: 13px; height: 13px; border-radius: 7px;
        border: 1px solid {sep}; background: transparent;
    }}
    QCheckBox::indicator:checked {{ background: {acc2}; border: 1px solid {acc2}; }}
    QComboBox {{
        background: {bg_d}; border: 1px solid {border}; border-radius: {r}px;
        padding: 3px 6px; color: {tx}; min-height: {bh}px;
    }}
    QComboBox:hover {{ border: 1px solid {acc}; }}
    QComboBox::drop-down {{ border: 0; width: 20px; }}
    QComboBox QAbstractItemView {{
        background: {bg_d}; color: {tx};
        selection-background-color: {acc2}; selection-color: #fff; outline: 0;
    }}
    QTextEdit#LogBox {{
        background: {bg_d}; border: 1px solid {border}; border-radius: {r}px;
        color: {sub}; font-family: Consolas, monospace; font-size: {fss}px;
    }}
    QScrollBar:vertical   {{ background: transparent; width: {sb}px; margin: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: {sb}px; margin: 0; }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: {btn_h}; border-radius: {sbr}px; min-height: 20px; min-width: 20px;
    }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: {sub}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ height: 0; width: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}
    QFrame#Sep {{ background: {sep}; }}
    QScrollArea {{ border: none; background: {bg}; }}
    """.format(
        bg=BG, bg_d=BG_D, border=BORDER,
        btn=BTN, btn_h=BTN_H, btn_p=BTN_P,
        acc=ACC, acc2=ACC2, tx=TEXT, sub=SUBTEXT, sep=SEP,
        r=px(8), gm=px(14), gp=px(8),
        bh=px(22), ebh=px(22), sb=px(10), sbr=px(5),
        fs=max(11, px(12)), fsb=max(12, px(13)),
        fsh=max(14, px(15)), fss=max(10, px(11)),
    )

    # Always use our own stylesheet to ensure proper button visibility
    # The ADV stylesheet may not apply correctly to this dialog
    # So we keep our own complete stylesheet with proper button colors

    win = QtWidgets.QDialog(_maya_win())
    win.setObjectName(WIN_OBJ)
    win.setWindowTitle(_t("title") + u"  v2.5")
    try:
        fl = win.windowFlags() | QtCore.Qt.Window
        for f in ("WindowMinimizeButtonHint", "WindowMaximizeButtonHint", "WindowCloseButtonHint"):
            if hasattr(QtCore.Qt, f):
                fl |= getattr(QtCore.Qt, f)
        win.setWindowFlags(fl)
        if hasattr(QtCore.Qt, "WindowContextHelpButtonHint"):
            win.setWindowFlag(QtCore.Qt.WindowContextHelpButtonHint, False)
    except Exception:
        pass
    win.setMinimumSize(px(440), px(540))
    win.resize(px(560), px(800))

    win.setStyleSheet(SS)

    def _sep():
        f = QtWidgets.QFrame()
        f.setObjectName("Sep")
        f.setFrameShape(QtWidgets.QFrame.HLine)
        f.setFixedHeight(1)
        return f

    def _sec(txt):
        lb = QtWidgets.QLabel(txt)
        lb.setObjectName("SecLbl")
        return lb

    def _lbl(txt, obj=None):
        lb = QtWidgets.QLabel(txt)
        if obj:
            lb.setObjectName(obj)
        return lb

    def _btn(txt, obj=None, tip=""):
        b = QtWidgets.QPushButton(txt)
        if obj:
            b.setObjectName(obj)
        if tip:
            b.setToolTip(tip)
        return b

    def _sub(txt):
        lb = QtWidgets.QLabel(txt)
        lb.setObjectName("SubLbl")
        return lb

    def _switch_lang(idx):
        try:
            i = int(idx)
        except Exception:
            i = 0
        _lang_set("CN" if i == 0 else "EN")
        try:
            win.close()
            win.deleteLater()
        except Exception:
            pass
        # Use QTimer to delay UI recreation to avoid crash
        try:
            from PySide2.QtCore import QTimer
        except ImportError:
            from PySide6.QtCore import QTimer
        QTimer.singleShot(100, create_ui)

    root_vl = QtWidgets.QVBoxLayout(win)
    root_vl.setContentsMargins(px(12), px(10), px(12), px(10))
    root_vl.setSpacing(px(8))

    hdr = QtWidgets.QHBoxLayout()
    t = _lbl(_t("title"), "TitleLbl")
    hdr.addWidget(t)
    hdr.addStretch()
    hdr.addWidget(_sub(_t("lang") + u":"))
    lang_cmb = QtWidgets.QComboBox()
    lang_cmb.setFixedWidth(px(86))
    lang_cmb.addItem(u"中文")
    lang_cmb.addItem(u"English")
    lang_cmb.blockSignals(True)
    lang_cmb.setCurrentIndex(0 if _lang_get() == "CN" else 1)
    lang_cmb.blockSignals(False)
    lang_cmb.currentIndexChanged.connect(_switch_lang)
    hdr.addWidget(lang_cmb)
    hdr.addSpacing(px(6))
    hdr.addWidget(_sub(u"v2.5  by ZaoChaNai"))
    root_vl.addLayout(hdr)
    root_vl.addWidget(_sep())

    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

    body = QtWidgets.QWidget()
    body.setStyleSheet("background: %s;" % BG)
    body_vl = QtWidgets.QVBoxLayout(body)
    body_vl.setContentsMargins(px(2), px(4), px(4), px(4))
    body_vl.setSpacing(px(10))
    scroll.setWidget(body)
    root_vl.addWidget(scroll, 1)

    body_vl.addWidget(_sec(_t("sec_file_queue")))

    def _make_queue_group(title, state_key, add_caption):
        grp = QtWidgets.QGroupBox(title)
        vl = QtWidgets.QVBoxLayout(grp)
        vl.setSpacing(px(5))

        lst = QtWidgets.QListWidget()
        lst.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        lst.setMinimumHeight(px(80))
        lst.setMaximumHeight(px(120))
        vl.addWidget(lst)

        stat = _sub(_fmt_files(0))
        vl.addWidget(stat)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(px(5))
        b_add = _btn(_t("btn_add"), "AddBtn", add_caption)
        b_rem = _btn(_t("btn_remove"), "RemBtn", _t("btn_remove"))
        b_clr = _btn(_t("btn_clear"), "ClrBtn", _t("btn_clear"))
        row.addWidget(b_add, 2)
        row.addWidget(b_rem, 1)
        row.addWidget(b_clr, 1)
        vl.addLayout(row)

        def _refresh():
            lst.clear()
            files = _STATE[state_key]
            for f in files:
                lst.addItem(os.path.basename(f))
            stat.setText(_fmt_files(len(files)))

        def _add():
            chosen = cmds.fileDialog2(
                fileFilter="Maya Files (*.ma *.mb);;All Files (*.*)",
                dialogStyle=2,
                fileMode=4,
                caption=add_caption,
            ) or []
            for f in chosen:
                if f not in _STATE[state_key]:
                    _STATE[state_key].append(f)
            _refresh()

        def _remove():
            idxs = sorted({i.row() for i in lst.selectedIndexes()}, reverse=True)
            for i in idxs:
                if 0 <= i < len(_STATE[state_key]):
                    _STATE[state_key].pop(i)
            _refresh()

        def _clear():
            _STATE[state_key].clear()
            _refresh()

        b_add.clicked.connect(_add)
        b_rem.clicked.connect(_remove)
        b_clr.clicked.connect(_clear)
        return grp, _refresh

    grp_anim, _ref_anim = _make_queue_group(
        _t("anim_group"), "anim_files", _t("anim_pick")
    )
    grp_skin, _ref_skin = _make_queue_group(
        _t("skin_group"), "skin_files", _t("skin_pick")
    )
    body_vl.addWidget(grp_anim)
    body_vl.addWidget(grp_skin)
    body_vl.addWidget(_sep())

    body_vl.addWidget(_sec(_t("sec_scene")))
    obj_grp = QtWidgets.QGroupBox(_t("grp_scene"))
    obj_vl = QtWidgets.QVBoxLayout(obj_grp)
    obj_vl.setSpacing(px(8))

    skin_lbl = _sub(u"Skin:  " + _t("not_recorded"))
    bone_lbl = _sub(u"Bone:  " + _t("not_recorded"))
    _obj_refresh_cb = [None]

    def _make_obj_row(lbl_widget, rec_tip, sel_tip, state_key):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(px(5))
        row.addWidget(lbl_widget, 1)
        b_rec = _btn(_t("btn_record"), "RecBtn", rec_tip)
        b_sel = _btn(_t("btn_select"), "SelBtn", sel_tip)
        b_clr = _btn(_t("btn_clear"), "ClrBtn")
        row.addWidget(b_rec, 2)
        row.addWidget(b_sel)
        row.addWidget(b_clr)

        def _upd():
            n = len(_STATE[state_key])
            name = state_key.split("_")[0].capitalize()
            lbl_widget.setText((u"%s:  %s" % (name, _fmt_objs(n))) if n else (u"%s:  %s" % (name, _t("not_recorded"))))
            lbl_widget.setStyleSheet("color: %s;" % (TEXT if n else SUBTEXT))
            if _obj_refresh_cb[0]:
                _obj_refresh_cb[0]()

        def _rec():
            sel = cmds.ls(selection=True, long=True) or []
            if not sel:
                cmds.warning(_t("warn_select_first"))
                return
            _STATE[state_key][:] = sel
            _log(u"Recorded %d %s objects" % (len(sel), state_key.split("_")[0]))
            _upd()

        def _sel():
            objs = [o for o in _STATE[state_key] if cmds.objExists(o)]
            if objs:
                cmds.select(objs, replace=True)
            else:
                cmds.warning(_t("warn_missing_recorded"))

        def _clr():
            _STATE[state_key].clear()
            _upd()

        b_rec.clicked.connect(_rec)
        b_sel.clicked.connect(_sel)
        b_clr.clicked.connect(_clr)
        return row

    obj_vl.addLayout(_make_obj_row(skin_lbl, _t("tip_skin_rec"), _t("tip_skin_sel"), "skin_objects"))
    obj_vl.addLayout(_make_obj_row(bone_lbl, _t("tip_bone_rec"), _t("tip_bone_sel"), "bone_objects"))

    lists_row = QtWidgets.QHBoxLayout()
    lists_row.setSpacing(px(8))
    skin_list_lbl = _sub(u"Skin")
    bone_list_lbl = _sub(u"Bone")
    skin_lst = QtWidgets.QListWidget()
    skin_lst.setMinimumHeight(px(70)); skin_lst.setMaximumHeight(px(90))
    bone_lst = QtWidgets.QListWidget()
    bone_lst.setMinimumHeight(px(70)); bone_lst.setMaximumHeight(px(90))
    for lbl_w, lst_w in ((skin_list_lbl, skin_lst), (bone_list_lbl, bone_lst)):
        col_vl = QtWidgets.QVBoxLayout()
        col_vl.setSpacing(px(2))
        col_vl.addWidget(lbl_w)
        col_vl.addWidget(lst_w)
        lists_row.addLayout(col_vl)
    obj_vl.addLayout(lists_row)

    def _refresh_obj_lists():
        skin_lst.clear()
        for o in _STATE["skin_objects"]:
            skin_lst.addItem(o.split("|")[-1])
        bone_lst.clear()
        for o in _STATE["bone_objects"]:
            bone_lst.addItem(o.split("|")[-1])

    _obj_refresh_cb[0] = _refresh_obj_lists
    _refresh_obj_lists()

    body_vl.addWidget(obj_grp)
    body_vl.addWidget(_sep())

    body_vl.addWidget(_sec(_t("sec_out")))
    path_grp = QtWidgets.QGroupBox(_t("grp_out"))
    path_vl = QtWidgets.QVBoxLayout(path_grp)
    path_vl.setSpacing(px(6))

    path_edit = QtWidgets.QLineEdit()
    path_edit.setPlaceholderText(u"C:\\ExportFBX\\<%ProjectName%>\\")
    path_edit.setText(u"C:\\ExportFBX\\<%ProjectName%>\\")
    path_vl.addWidget(path_edit)

    tag_row = QtWidgets.QHBoxLayout()
    tag_row.setSpacing(px(4))

    def _make_tag_btn(lbl, tag, edit_widget):
        b = _btn(lbl, "TagBtn", _t("tip_insert") + tag)
        def _insert():
            edit_widget.setText(edit_widget.text() + tag)
        b.clicked.connect(_insert)
        return b

    for lbl, tag in ((_t("tag_name"), "<%FileName%>"), (_t("tag_parent"), "<%ParentFolder%>"), (_t("tag_proj"), "<%ProjectName%>"), (u"/", "/"), (u"_", "_")):
        tag_row.addWidget(_make_tag_btn(lbl, tag, path_edit))

    b_browse = _btn(_t("btn_browse"), "BrowseBtn", _t("tip_choose_out"))

    def _browse():
        folder = cmds.fileDialog2(fileMode=3, caption=_t("dlg_choose_out"))
        if folder:
            path_edit.setText(folder[0].replace("/", "\\") + "\\")

    b_browse.clicked.connect(_browse)
    tag_row.addWidget(b_browse)
    path_vl.addLayout(tag_row)
    body_vl.addWidget(path_grp)
    body_vl.addWidget(_sep())

    body_vl.addWidget(_sec(_t("sec_fbx")))
    fbx_grp = QtWidgets.QGroupBox(_t("grp_fbx"))
    fbx_vl = QtWidgets.QVBoxLayout(fbx_grp)
    fbx_vl.setSpacing(px(7))

    row1 = QtWidgets.QHBoxLayout(); row1.setSpacing(px(16))
    cb_shapes = QtWidgets.QCheckBox(_t("shapes")); cb_shapes.setChecked(True)
    cb_embed = QtWidgets.QCheckBox(_t("embed"))
    cb_children = QtWidgets.QCheckBox(_t("children"))
    cb_input = QtWidgets.QCheckBox(_t("input"))
    for w in (cb_shapes, cb_embed, cb_children, cb_input):
        row1.addWidget(w)
    row1.addStretch()
    fbx_vl.addLayout(row1)
    cb_shapes.toggled.connect(lambda v: _STATE.update({"fbx_shapes": v}))
    cb_embed.toggled.connect(lambda v: _STATE.update({"fbx_embed": v}))
    cb_children.toggled.connect(lambda v: _STATE.update({"fbx_children": v}))
    cb_input.toggled.connect(lambda v: _STATE.update({"fbx_input_conn": v}))

    row2 = QtWidgets.QHBoxLayout(); row2.setSpacing(px(10))
    row2.addWidget(_sub(_t("up_axis")))
    cmb_axis = QtWidgets.QComboBox(); cmb_axis.addItems(["Y", "Z"]); cmb_axis.setFixedWidth(px(58))
    cmb_axis.currentTextChanged.connect(lambda v: _STATE.update({"fbx_up_axis": v}))
    row2.addWidget(cmb_axis)
    row2.addSpacing(px(8))
    cb_auto = QtWidgets.QCheckBox(_t("auto_units")); cb_auto.setChecked(True)
    row2.addWidget(cb_auto)
    row2.addWidget(_sub(_t("manual_units")))
    cmb_unit = QtWidgets.QComboBox(); cmb_unit.setFixedWidth(px(76)); cmb_unit.setEnabled(False)
    cmb_unit.addItems([u"cm", u"mm", u"dm", u"m", u"km", u"ft", u"yd"])
    _UM = {u"cm": "cm", u"mm": "mm", u"dm": "dm", u"m": "m", u"km": "km", u"ft": "ft", u"yd": "yd"}
    cmb_unit.currentTextChanged.connect(lambda v: _STATE.update({"fbx_file_units": _UM.get(v, "cm")}))
    cb_auto.toggled.connect(lambda v: [_STATE.update({"fbx_auto_units": v}), cmb_unit.setEnabled(not v)])
    row2.addWidget(cmb_unit)
    row2.addStretch()
    fbx_vl.addLayout(row2)

    row3 = QtWidgets.QHBoxLayout(); row3.setSpacing(px(16))
    cb_root = QtWidgets.QCheckBox(_t("add_root"))
    cb_root.setToolTip(_t("tip_add_root"))
    cb_ue = QtWidgets.QCheckBox(_t("adv_to_ue"))
    cb_ue.setToolTip(_t("tip_adv_ue"))
    cb_clean = QtWidgets.QCheckBox(_t("clean_invalid"))
    cb_clean.setToolTip(_t("tip_clean_invalid"))
    for w in (cb_root, cb_ue, cb_clean):
        row3.addWidget(w)
    row3.addStretch()
    fbx_vl.addLayout(row3)
    cb_root.toggled.connect(lambda v: _STATE.update({"add_root": v}))
    cb_ue.toggled.connect(lambda v: _STATE.update({"adv_to_ue": v}))
    cb_clean.toggled.connect(lambda v: _STATE.update({"clean_invalid": v}))

    body_vl.addWidget(fbx_grp)
    body_vl.addWidget(_sep())

    body_vl.addWidget(_sec(_t("log")))
    log_box = QtWidgets.QTextEdit()
    log_box.setObjectName("LogBox")
    log_box.setReadOnly(True)
    log_box.setMinimumHeight(px(90))
    log_box.setMaximumHeight(px(150))
    body_vl.addWidget(log_box)

    log_btnrow = QtWidgets.QHBoxLayout()
    log_btnrow.addStretch()
    b_clr_log = _btn(_t("clear_log"), "ClrBtn")
    b_clr_log.setFixedWidth(px(76))
    b_clr_log.clicked.connect(log_box.clear)
    log_btnrow.addWidget(b_clr_log)
    body_vl.addLayout(log_btnrow)
    body_vl.addStretch()

    _UI_REFS["log"] = log_box

    root_vl.addWidget(_sep())
    exp_btn = _btn(_t("export_all"), "ExpBtn", _t("tip_export_all"))

    def _do_export():
        run_export_all(path_edit.text())

    exp_btn.clicked.connect(_do_export)
    root_vl.addWidget(exp_btn)

    def _cleanup():
        _UI_REFS.pop("log", None)

    win.finished.connect(_cleanup)
    win.show()

    _log(_t("started"))
    return win


# Compatible aliases
show_ui     = create_ui
show_ui_qt  = create_ui
run         = create_ui
