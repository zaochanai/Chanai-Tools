# -*- coding: utf-8 -*-
"""World transform lock tool (rotation + translation).

Integrated for ADV Fast Select.
Original author credit kept: 一方狂三

Usage: import adv_world_transform_lock; adv_world_transform_lock.show()
"""

import time

import maya.cmds as cmds


class WorldRotationLocker:
    def __init__(self):
        # Rotation
        self.tracked_object = None
        self.original_rotation = {}  # {frame: [rx, ry, rz]}
        self.script_job_ids = []
        self.is_locked = False
        self.suspend_restore = False
        self.suspend_time = 0

        # Translation
        self.tracked_translate_object = None
        self.original_translation = {}  # {frame: [tx, ty, tz]}
        self.translate_script_job_ids = []
        self.is_translate_locked = False

        self.window_name = "worldRotationLockerUI"

        self.record_button = None
        self.translate_record_button = None
        self.temp_unlock_button = None

    def create_ui(self):
        if cmds.window(self.window_name, exists=True):
            cmds.deleteUI(self.window_name)

        window = cmds.window(
            self.window_name,
            title=u"世界变换锁定工具",
            widthHeight=(300, 280),
            sizeable=True,
            minimizeButton=True,
            maximizeButton=True,
        )

        cmds.columnLayout(adjustableColumn=True)
        cmds.separator(height=10, style="none")

        # Rotation
        cmds.text(label=u"世界旋转锁定", align="center")
        cmds.separator(height=8)

        self.record_button = cmds.button(
            label=u"选择物体并记录旋转",
            command=self.lock_object_rotation,
            height=35,
            backgroundColor=[0.4, 0.6, 0.8],
        )

        cmds.separator(height=8)
        cmds.button(
            label=u"取消旋转记录",
            command=self.unlock_object_rotation,
            height=35,
            backgroundColor=[0.8, 0.4, 0.4],
        )

        # Temp unlock
        cmds.separator(height=8)
        self.temp_unlock_button = cmds.button(
            label=u"临时解除锁定(撤回父级操作)",
            command=self.temporarily_unlock,
            height=30,
            backgroundColor=[0.9, 0.7, 0.2],
            enable=False,
        )

        cmds.separator(height=15)

        # Translation
        cmds.text(label=u"世界位移锁定", align="center")
        cmds.separator(height=8)

        self.translate_record_button = cmds.button(
            label=u"选择物体并记录位移",
            command=self.lock_object_translation,
            height=35,
            backgroundColor=[0.4, 0.8, 0.6],
        )

        cmds.separator(height=8)
        cmds.button(
            label=u"取消位移记录",
            command=self.unlock_object_translation,
            height=35,
            backgroundColor=[0.8, 0.6, 0.4],
        )

        cmds.separator(height=10, style="none")
        cmds.text(label=u"by: 一方狂三", align="center", font="smallPlainLabelFont")
        cmds.separator(height=5, style="none")

        cmds.showWindow(window)

    def temporarily_unlock(self, *args):
        """Temporarily disable restore for 2 seconds (useful for undo/parent edits)."""
        if not self.is_locked and not self.is_translate_locked:
            cmds.warning(u"没有激活的锁定需要解除")
            return

        self.suspend_restore = True
        self.suspend_time = time.time()
        try:
            cmds.button(
                self.temp_unlock_button,
                edit=True,
                label=u"锁定已临时解除(2秒)",
                backgroundColor=[0.2, 0.8, 0.2],
            )
        except Exception:
            pass
        cmds.refresh()

        def restore_lock():
            if time.time() - self.suspend_time >= 2:
                self.suspend_restore = False
                try:
                    cmds.button(
                        self.temp_unlock_button,
                        edit=True,
                        label=u"临时解除锁定(撤回父级操作)",
                        backgroundColor=[0.9, 0.7, 0.2],
                    )
                except Exception:
                    pass
            else:
                cmds.evalDeferred(restore_lock, lowPriority=True)

        cmds.evalDeferred(restore_lock, lowPriority=True)

    def handle_undo_redo(self):
        if self.is_locked or self.is_translate_locked:
            self.temporarily_unlock()
            cmds.warning(u"检测到撤回操作，已临时解除锁定2秒")

    # ===== Rotation lock =====
    def lock_object_rotation(self, *args):
        selection = cmds.ls(selection=True)
        if not selection:
            cmds.warning(u"请先选择一个物体")
            return
        if len(selection) > 1:
            cmds.warning(u"请只选择一个物体")
            return

        obj = selection[0]
        parents = cmds.listRelatives(obj, parent=True)
        if not parents:
            cmds.confirmDialog(title=u"错误", message=u"请选择带有父级的物体", button=[u"确定"])
            return

        if self.is_locked:
            self.unlock_object_rotation()

        start_frame = int(cmds.playbackOptions(query=True, minTime=True))
        end_frame = int(cmds.playbackOptions(query=True, maxTime=True))

        rotation_data = {}
        current_frame = cmds.currentTime(query=True)
        try:
            cmds.refresh(suspend=True)
            for frame in range(start_frame, end_frame + 1):
                cmds.currentTime(frame)
                world_rotation = cmds.xform(obj, query=True, worldSpace=True, rotation=True)
                rotation_data[frame] = world_rotation[:]
        finally:
            cmds.currentTime(current_frame)
            cmds.refresh(suspend=False)

        self.tracked_object = obj
        self.original_rotation = rotation_data
        self.is_locked = True

        try:
            button_label = u"已记录旋转: %s (%d-%d帧)" % (obj, start_frame, end_frame)
            cmds.button(self.record_button, edit=True, label=button_label)
        except Exception:
            pass

        self.create_rotation_monitor()

    def create_rotation_monitor(self):
        self.clear_rotation_monitor()
        if not self.is_locked or not self.tracked_object:
            return

        try:
            rotate_attrs = [".rotateX", ".rotateY", ".rotateZ"]
            for attr in rotate_attrs:
                full_attr = self.tracked_object + attr
                job_id = cmds.scriptJob(attributeChange=[full_attr, self.restore_rotation])
                self.script_job_ids.append(job_id)

            for event in ["timeChanged", "idle", "SelectionChanged", "playbackRangeChanged", "SceneOpened"]:
                try:
                    job_id = cmds.scriptJob(event=[event, self.restore_rotation])
                    self.script_job_ids.append(job_id)
                except Exception:
                    pass

            undo_job = cmds.scriptJob(event=["Undo", self.handle_undo_redo])
            redo_job = cmds.scriptJob(event=["Redo", self.handle_undo_redo])
            self.script_job_ids.extend([undo_job, redo_job])

            parents = cmds.listRelatives(self.tracked_object, parent=True)
            if parents:
                parent = parents[0]
                parent_attrs = [
                    ".translateX",
                    ".translateY",
                    ".translateZ",
                    ".rotateX",
                    ".rotateY",
                    ".rotateZ",
                    ".scaleX",
                    ".scaleY",
                    ".scaleZ",
                ]
                for attr in parent_attrs:
                    try:
                        full_attr = parent + attr
                        job_id = cmds.scriptJob(attributeChange=[full_attr, self.restore_rotation])
                        self.script_job_ids.append(job_id)
                    except Exception:
                        pass

            try:
                cmds.button(self.temp_unlock_button, edit=True, enable=True)
            except Exception:
                pass

        except Exception as e:
            try:
                cmds.warning(u"创建旋转监控失败: %s" % str(e))
            except Exception:
                pass

    def restore_rotation(self):
        if self.suspend_restore:
            return
        if not self.is_locked or not self.tracked_object:
            return
        if not cmds.objExists(self.tracked_object):
            self.unlock_object_rotation()
            return

        try:
            # Ctrl held: skip restore
            if cmds.getModifiers() & 4:
                return

            current_frame = int(cmds.currentTime(query=True))
            target_rotation = self.original_rotation.get(current_frame)
            if target_rotation is None:
                return

            current_rotation = cmds.xform(self.tracked_object, query=True, worldSpace=True, rotation=True)

            tolerance = 0.001
            needs_restore = any(abs(current_rotation[i] - target_rotation[i]) > tolerance for i in range(3))
            if needs_restore:
                cmds.xform(self.tracked_object, worldSpace=True, rotation=target_rotation)
                cmds.refresh()
        except Exception:
            pass

    # ===== Translation lock =====
    def lock_object_translation(self, *args):
        selection = cmds.ls(selection=True)
        if not selection:
            cmds.warning(u"请先选择一个物体")
            return
        if len(selection) > 1:
            cmds.warning(u"请只选择一个物体")
            return

        obj = selection[0]
        parents = cmds.listRelatives(obj, parent=True)
        if not parents:
            cmds.confirmDialog(title=u"错误", message=u"请选择带有父级的物体", button=[u"确定"])
            return

        if self.is_translate_locked:
            self.unlock_object_translation()

        start_frame = int(cmds.playbackOptions(query=True, minTime=True))
        end_frame = int(cmds.playbackOptions(query=True, maxTime=True))

        translation_data = {}
        current_frame = cmds.currentTime(query=True)

        try:
            cmds.refresh(suspend=True)
            for frame in range(start_frame, end_frame + 1):
                cmds.currentTime(frame)
                world_translation = cmds.xform(obj, query=True, worldSpace=True, translation=True)
                translation_data[frame] = world_translation[:]
        finally:
            cmds.currentTime(current_frame)
            cmds.refresh(suspend=False)

        self.tracked_translate_object = obj
        self.original_translation = translation_data
        self.is_translate_locked = True

        try:
            button_label = u"已记录位移: %s (%d-%d帧)" % (obj, start_frame, end_frame)
            cmds.button(self.translate_record_button, edit=True, label=button_label)
        except Exception:
            pass

        self.create_translation_monitor()

    def create_translation_monitor(self):
        self.clear_translation_monitor()
        if not self.is_translate_locked or not self.tracked_translate_object:
            return

        try:
            translate_attrs = [".translateX", ".translateY", ".translateZ"]
            for attr in translate_attrs:
                full_attr = self.tracked_translate_object + attr
                job_id = cmds.scriptJob(attributeChange=[full_attr, self.restore_translation])
                self.translate_script_job_ids.append(job_id)

            for event in ["timeChanged", "idle", "SelectionChanged", "playbackRangeChanged", "SceneOpened"]:
                try:
                    job_id = cmds.scriptJob(event=[event, self.restore_translation])
                    self.translate_script_job_ids.append(job_id)
                except Exception:
                    pass

            undo_job = cmds.scriptJob(event=["Undo", self.handle_undo_redo])
            redo_job = cmds.scriptJob(event=["Redo", self.handle_undo_redo])
            self.translate_script_job_ids.extend([undo_job, redo_job])

            parents = cmds.listRelatives(self.tracked_translate_object, parent=True)
            if parents:
                parent = parents[0]
                parent_attrs = [
                    ".translateX",
                    ".translateY",
                    ".translateZ",
                    ".rotateX",
                    ".rotateY",
                    ".rotateZ",
                    ".scaleX",
                    ".scaleY",
                    ".scaleZ",
                ]
                for attr in parent_attrs:
                    try:
                        full_attr = parent + attr
                        job_id = cmds.scriptJob(attributeChange=[full_attr, self.restore_translation])
                        self.translate_script_job_ids.append(job_id)
                    except Exception:
                        pass

            try:
                cmds.button(self.temp_unlock_button, edit=True, enable=True)
            except Exception:
                pass

        except Exception as e:
            try:
                cmds.warning(u"创建位移监控失败: %s" % str(e))
            except Exception:
                pass

    def restore_translation(self):
        if self.suspend_restore:
            return
        if not self.is_translate_locked or not self.tracked_translate_object:
            return
        if not cmds.objExists(self.tracked_translate_object):
            self.unlock_object_translation()
            return

        try:
            if cmds.getModifiers() & 4:
                return

            current_frame = int(cmds.currentTime(query=True))
            target_translation = self.original_translation.get(current_frame)
            if target_translation is None:
                return

            current_translation = cmds.xform(self.tracked_translate_object, query=True, worldSpace=True, translation=True)

            tolerance = 0.001
            needs_restore = any(abs(current_translation[i] - target_translation[i]) > tolerance for i in range(3))
            if needs_restore:
                cmds.xform(self.tracked_translate_object, worldSpace=True, translation=target_translation)
                cmds.refresh()
        except Exception:
            pass

    # ===== Common =====
    def clear_rotation_monitor(self):
        for job_id in list(self.script_job_ids):
            try:
                if cmds.scriptJob(exists=job_id):
                    cmds.scriptJob(kill=job_id)
            except Exception:
                pass
        self.script_job_ids = []

    def clear_translation_monitor(self):
        for job_id in list(self.translate_script_job_ids):
            try:
                if cmds.scriptJob(exists=job_id):
                    cmds.scriptJob(kill=job_id)
            except Exception:
                pass
        self.translate_script_job_ids = []

    def unlock_object_rotation(self, *args):
        self.clear_rotation_monitor()
        self.tracked_object = None
        self.original_rotation = {}
        self.is_locked = False
        try:
            cmds.button(self.temp_unlock_button, edit=True, enable=False)
        except Exception:
            pass
        try:
            if self.record_button and cmds.button(self.record_button, exists=True):
                cmds.button(self.record_button, edit=True, label=u"选择物体并记录旋转")
        except Exception:
            pass

    def unlock_object_translation(self, *args):
        self.clear_translation_monitor()
        self.tracked_translate_object = None
        self.original_translation = {}
        self.is_translate_locked = False
        try:
            if self.translate_record_button and cmds.button(self.translate_record_button, exists=True):
                cmds.button(self.translate_record_button, edit=True, label=u"选择物体并记录位移")
        except Exception:
            pass


_world_locker = None


def show_world_rotation_locker():
    global _world_locker
    _world_locker = WorldRotationLocker()
    _world_locker.create_ui()
    return _world_locker


def show():
    return show_world_rotation_locker()
