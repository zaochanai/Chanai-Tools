#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ADV - 构图辅助

把“构图辅助插件”以可 import 的模块形式集成到 ADV Fast Select。
入口：show() / show_composition_helper()

说明：该脚本会在所选相机上创建 imagePlane 作为构图参考。
"""

from __future__ import absolute_import, print_function

import json
import math
import os
import sys
import tempfile

import maya.cmds as cmds

try:
    from PySide2.QtCore import Qt, QTimer, QRectF, QPointF
    from PySide2.QtGui import QColor, QImage, QPainter, QPen, QPainterPath
    from PySide2.QtWidgets import (
        QWidget,
        QDialog,
        QVBoxLayout,
        QHBoxLayout,
        QGridLayout,
        QFormLayout,
        QFrame,
        QLabel,
        QPushButton,
        QCheckBox,
        QTabWidget,
        QGroupBox,
        QSpinBox,
        QSlider,
        QMenu,
        QComboBox,
        QDoubleSpinBox,
        QColorDialog,
    )
    from shiboken2 import wrapInstance
except Exception:
    try:
        from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
        from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPainterPath
        from PySide6.QtWidgets import (
            QWidget,
            QDialog,
            QVBoxLayout,
            QHBoxLayout,
            QGridLayout,
            QFormLayout,
            QFrame,
            QLabel,
            QPushButton,
            QCheckBox,
            QTabWidget,
            QGroupBox,
            QSpinBox,
            QSlider,
            QMenu,
            QComboBox,
            QDoubleSpinBox,
            QColorDialog,
        )
        from shiboken6 import wrapInstance
    except Exception:
        from PySide.QtCore import Qt, QTimer, QRectF, QPointF
        from PySide.QtGui import (
            QColor,
            QImage,
            QPainter,
            QPen,
            QPainterPath,
            QWidget,
            QDialog,
            QVBoxLayout,
            QHBoxLayout,
            QGridLayout,
            QFormLayout,
            QFrame,
            QLabel,
            QPushButton,
            QCheckBox,
            QTabWidget,
            QGroupBox,
            QSpinBox,
            QSlider,
            QMenu,
            QComboBox,
            QDoubleSpinBox,
            QColorDialog,
        )
        from shiboken import wrapInstance


GOLDEN_RATIO = 1.6180339887


def get_maya_main_window():
    try:
        import maya.OpenMayaUI as omui

        ptr = omui.MQtUtil.mainWindow()
        if ptr is not None:
            return wrapInstance(int(ptr), QWidget)
    except Exception:
        pass
    return None


class CompositionImageGenerator(object):
    def __init__(self):
        self.temp_dir = tempfile.gettempdir()
        self.current_image_plane = None

        self.show_thirds = False
        self.show_golden = False
        self.show_cross = False
        self.show_diagonals = False
        self.show_spiral = False
        self.show_triangle = False
        self.show_diag_thirds = False
        self.show_custom = False

        self.color_thirds = (1.0, 1.0, 0.0)
        self.color_golden = (1.0, 0.43, 0.0)
        self.color_cross = (0.0, 0.69, 1.0)
        self.color_diagonals = (1.0, 0.0, 0.0)
        self.color_spiral = (1.0, 1.0, 1.0)
        self.color_triangle = (0.0, 1.0, 0.69)
        self.color_diag_thirds = (1.0, 0.0, 1.0)
        self.color_custom = (0.0, 1.0, 0.0)

        self.line_width_thirds = 2
        self.line_width_golden = 2
        self.line_width_cross = 2
        self.line_width_diagonals = 2
        self.line_width_spiral = 2
        self.line_width_triangle = 2
        self.line_width_diag_thirds = 2
        self.line_width_custom = 2

        self.custom_x_divs = 4
        self.custom_y_divs = 4

        self.spiral_zoom = 0
        self.spiral_shift_x = 0
        self.spiral_shift_y = 0
        self.spiral_unlocked = False
        self.spiral_mode = 0
        self.triangle_mode = 0

    def create_composition_for_camera(self, camera=None):
        try:
            if not camera:
                selected = cmds.ls(selection=True)
                if not selected:
                    cmds.warning(u"请先选择一个相机")
                    return False
                camera = selected[0]

            # 检查对象是否存在
            if not cmds.objExists(camera):
                return False

            if cmds.nodeType(camera) == 'transform':
                shapes = cmds.listRelatives(camera, shapes=True, type='camera')
                if not shapes:
                    cmds.warning(u"选中的对象不是相机")
                    return False
            elif cmds.nodeType(camera) != 'camera':
                cmds.warning(u"选中的对象不是相机")
                return False
        except Exception:
            return False

        render_width = cmds.getAttr('defaultResolution.width')
        render_height = cmds.getAttr('defaultResolution.height')

        image_path = self.generate_composition_image(render_width, render_height)
        if not image_path:
            return False

        self.remove_existing_composition()

        try:
            image_plane_result = cmds.imagePlane(camera=camera)
            image_plane_name = image_plane_result[1]

            cmds.setAttr('%s.imageName' % image_plane_name, image_path, type='string')
            cmds.setAttr('%s.displayOnlyIfCurrent' % image_plane_name, True)
            cmds.setAttr('%s.depth' % image_plane_name, 0.1)
            cmds.setAttr('%s.coverageX' % image_plane_name, render_width)
            cmds.setAttr('%s.coverageY' % image_plane_name, render_height)
            cmds.setAttr('%s.alphaGain' % image_plane_name, 1.0)

            self.current_image_plane = image_plane_name
            return True
        except Exception as e:
            print(u"创建imagePlane失败: %s" % e)
            return False

    def generate_composition_image(self, width, height):
        try:
            image = QImage(width, height, QImage.Format_RGBA8888)
            image.fill(QColor(0, 0, 0, 0))

            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing)

            if self.show_thirds:
                self.draw_thirds(painter, 0, 0, width, height)
            if self.show_golden:
                self.draw_golden_ratio(painter, 0, 0, width, height)
            if self.show_cross:
                self.draw_cross(painter, 0, 0, width, height)
            if self.show_diagonals:
                self.draw_diagonals(painter, 0, 0, width, height)
            if self.show_diag_thirds:
                self.draw_diag_thirds(painter, 0, 0, width, height)
            if self.show_triangle:
                self.draw_golden_triangle(painter, 0, 0, width, height)
            if self.show_custom:
                self.draw_custom_lines(painter, 0, 0, width, height)
            if self.show_spiral:
                self.draw_golden_spiral(painter, 0, 0, width, height)

            painter.end()

            image_path = os.path.join(self.temp_dir, 'adv_composition_guide.png')
            if image.save(image_path):
                return image_path
            print(u"保存构图图片失败")
            return None
        except Exception as e:
            print(u"生成构图图片失败: %s" % e)
            return None

    def remove_existing_composition(self):
        if self.current_image_plane and cmds.objExists(self.current_image_plane):
            try:
                cmds.delete(self.current_image_plane)
            except Exception:
                pass
        self.current_image_plane = None

    def toggle_composition_visibility(self):
        if self.current_image_plane and cmds.objExists(self.current_image_plane):
            current_alpha = cmds.getAttr('%s.alphaGain' % self.current_image_plane)
            new_alpha = 0.0 if current_alpha > 0.0 else 1.0
            cmds.setAttr('%s.alphaGain' % self.current_image_plane, new_alpha)

    def draw_thirds(self, painter, x, y, width, height):
        color = QColor(int(self.color_thirds[0] * 255), int(self.color_thirds[1] * 255), int(self.color_thirds[2] * 255))
        pen = QPen(color, self.line_width_thirds)
        painter.setPen(pen)

        x1 = x + width / 3
        x2 = x + width * 2 / 3
        painter.drawLine(x1, y, x1, y + height)
        painter.drawLine(x2, y, x2, y + height)

        y1 = y + height / 3
        y2 = y + height * 2 / 3
        painter.drawLine(x, y1, x + width, y1)
        painter.drawLine(x, y2, x + width, y2)

    def draw_golden_ratio(self, painter, x, y, width, height):
        color = QColor(int(self.color_golden[0] * 255), int(self.color_golden[1] * 255), int(self.color_golden[2] * 255))
        pen = QPen(color, self.line_width_golden)
        painter.setPen(pen)

        gld_x = width / GOLDEN_RATIO
        gld_y = height / GOLDEN_RATIO

        painter.drawLine(x + gld_x, y, x + gld_x, y + height)
        painter.drawLine(x + width - gld_x, y, x + width - gld_x, y + height)
        painter.drawLine(x, y + gld_y, x + width, y + gld_y)
        painter.drawLine(x, y + height - gld_y, x + width, y + height - gld_y)

    def draw_cross(self, painter, x, y, width, height):
        color = QColor(int(self.color_cross[0] * 255), int(self.color_cross[1] * 255), int(self.color_cross[2] * 255))
        pen = QPen(color, self.line_width_cross)
        painter.setPen(pen)

        center_x = x + width / 2
        center_y = y + height / 2

        painter.drawLine(center_x, y, center_x, y + height)
        painter.drawLine(x, center_y, x + width, center_y)

    def draw_diagonals(self, painter, x, y, width, height):
        color = QColor(int(self.color_diagonals[0] * 255), int(self.color_diagonals[1] * 255), int(self.color_diagonals[2] * 255))
        pen = QPen(color, self.line_width_diagonals)
        painter.setPen(pen)

        painter.drawLine(x, y, x + width, y + height)
        painter.drawLine(x, y + height, x + width, y)

    def draw_diag_thirds(self, painter, x, y, width, height):
        color = QColor(int(self.color_diag_thirds[0] * 255), int(self.color_diag_thirds[1] * 255), int(self.color_diag_thirds[2] * 255))
        pen = QPen(color, self.line_width_diag_thirds)
        painter.setPen(pen)

        x1 = x + width / 3
        x2 = x + width * 2 / 3

        painter.drawLine(x1, y, x + width, y + height)
        painter.drawLine(x2, y, x, y + height)
        painter.drawLine(x, y, x2, y + height)
        painter.drawLine(x + width, y, x1, y + height)

    def draw_golden_triangle(self, painter, x, y, width, height):
        color = QColor(int(self.color_triangle[0] * 255), int(self.color_triangle[1] * 255), int(self.color_triangle[2] * 255))
        pen = QPen(color, self.line_width_triangle)
        painter.setPen(pen)

        if self.triangle_mode == 0:
            painter.drawLine(x, y + height, x + width, y)

            c1 = math.sqrt(width ** 2 + height ** 2)
            h1 = (height * width) / c1
            c2 = math.sqrt(max(width ** 2 - h1 ** 2, 0.0))
            ratio = c2 / c1 if c1 else 0.0

            pt1_x = x + width * ratio
            pt1_y = y + height * (1 - ratio)
            pt2_x = x + width * (1 - ratio)
            pt2_y = y + height * ratio

            painter.drawLine(x + width, y + height, pt1_x, pt1_y)
            painter.drawLine(x, y, pt2_x, pt2_y)
        else:
            painter.drawLine(x + width, y + height, x, y)

            c1 = math.sqrt(width ** 2 + height ** 2)
            h1 = (height * width) / c1
            c2 = math.sqrt(max(width ** 2 - h1 ** 2, 0.0))
            ratio = c2 / c1 if c1 else 0.0

            pt1_x = x + width * (1 - ratio)
            pt1_y = y + height * (1 - ratio)
            pt2_x = x + width * ratio
            pt2_y = y + height * ratio

            painter.drawLine(x, y + height, pt1_x, pt1_y)
            painter.drawLine(x + width, y, pt2_x, pt2_y)

    def draw_custom_lines(self, painter, x, y, width, height):
        color = QColor(int(self.color_custom[0] * 255), int(self.color_custom[1] * 255), int(self.color_custom[2] * 255))
        pen = QPen(color, self.line_width_custom)
        painter.setPen(pen)

        if self.custom_x_divs > 0:
            step_x = width / float(self.custom_x_divs + 1)
            for i in range(1, self.custom_x_divs + 1):
                line_x = x + step_x * i
                painter.drawLine(line_x, y, line_x, y + height)

        if self.custom_y_divs > 0:
            step_y = height / float(self.custom_y_divs + 1)
            for i in range(1, self.custom_y_divs + 1):
                line_y = y + step_y * i
                painter.drawLine(x, line_y, x + width, line_y)

    def draw_golden_spiral(self, painter, x, y, width, height):
        self.draw_golden_rectangles(painter, x, y, width, height)

        color = QColor(int(self.color_spiral[0] * 255), int(self.color_spiral[1] * 255), int(self.color_spiral[2] * 255))
        pen = QPen(color, self.line_width_spiral)
        painter.setPen(pen)

        num_points = 300
        turns = 2.5

        phi = GOLDEN_RATIO
        k = math.log(phi) / (math.pi / 2)

        scale = (self.spiral_zoom + 100) / 100.0
        shift_x = (self.spiral_shift_x / 100.0) * width
        shift_y = (self.spiral_shift_y / 100.0) * height

        base_size = min(width, height) * 0.08
        alpha = base_size * scale

        center_x = x + width / 2 + shift_x
        center_y = y + height / 2 + shift_y

        start_angle_offset = self.spiral_mode * (math.pi / 2)
        direction = 1 if self.spiral_mode % 2 == 0 else -1

        points = []
        for i in range(num_points):
            t = i / float(num_points - 1)
            phi_angle = (t * turns * 2 * math.pi) * direction + start_angle_offset
            rho = alpha * math.exp(t * turns * 2 * math.pi * k)

            point_x = center_x + rho * math.cos(phi_angle)
            point_y = center_y + rho * math.sin(phi_angle)
            points.append(QPointF(point_x, point_y))

        if len(points) > 1:
            path = QPainterPath()
            path.moveTo(points[0])
            for i in range(1, len(points)):
                if i < len(points) - 1:
                    control_point = QPointF(
                        (points[i].x() + points[i - 1].x()) / 2,
                        (points[i].y() + points[i - 1].y()) / 2,
                    )
                    path.quadTo(control_point, points[i])
                else:
                    path.lineTo(points[i])
            painter.drawPath(path)

    def draw_golden_rectangles(self, painter, x, y, width, height):
        light_color = QColor(int(self.color_spiral[0] * 100), int(self.color_spiral[1] * 100), int(self.color_spiral[2] * 100))
        light_pen = QPen(light_color, 1, Qt.DashLine)
        painter.setPen(light_pen)

        scale = (self.spiral_zoom + 100) / 100.0
        shift_x = (self.spiral_shift_x / 100.0) * width
        shift_y = (self.spiral_shift_y / 100.0) * height

        if not self.spiral_unlocked:
            if float(width) / float(height) > GOLDEN_RATIO:
                rect_height = height * 0.6 * scale
                rect_width = rect_height * GOLDEN_RATIO
            else:
                rect_width = width * 0.6 * scale
                rect_height = rect_width / GOLDEN_RATIO
        else:
            rect_width = width * 0.6 * scale
            rect_height = height * 0.6 * scale

        center_x = x + width / 2 + shift_x
        center_y = y + height / 2 + shift_y

        fibonacci = [1, 1, 2, 3, 5, 8, 13, 21]

        for i in range(min(6, len(fibonacci) - 1)):
            fib_ratio = fibonacci[i + 1] / float(fibonacci[-1])
            current_width = rect_width * fib_ratio
            current_height = rect_height * fib_ratio

            if self.spiral_mode == 0:
                rect_x = center_x - current_width / 2 + (i * current_width * 0.1)
                rect_y = center_y - current_height / 2 + (i * current_height * 0.1)
            elif self.spiral_mode == 1:
                rect_x = center_x - current_width / 2 - (i * current_width * 0.1)
                rect_y = center_y - current_height / 2 + (i * current_height * 0.1)
            elif self.spiral_mode == 2:
                rect_x = center_x - current_width / 2 - (i * current_width * 0.1)
                rect_y = center_y - current_height / 2 - (i * current_height * 0.1)
            else:
                rect_x = center_x - current_width / 2 + (i * current_width * 0.1)
                rect_y = center_y - current_height / 2 - (i * current_height * 0.1)

            rect = QRectF(rect_x, rect_y, current_width, current_height)
            painter.drawRect(rect)


class CompositionHelperUI(QDialog):
    def __init__(self, parent=None):
        super(CompositionHelperUI, self).__init__(parent or get_maya_main_window())

        self.setWindowTitle(u"构图辅助")
        self.setMinimumWidth(300)
        self.setWindowFlags(Qt.Tool)

        self.config_file = os.path.join(cmds.internalVar(userPrefDir=True), 'adv_composition_helper_config.json')
        self.generator = CompositionImageGenerator()

        self.aspect_ratios = [1.414, 1, 1.25, 1.333, 1.5, 1.7, 1.6, 1.37, 1.85, 2, 2.35, 2.39, 2.76]
        self.aspect_names = ["A4/A3", "1:1", "5:4", "4:3", "3:2", "16:9", "16:10", "1.37:1", "1.85:1", "2:1", "2.35:1", "2.39:1", "2.76:1"]

        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.auto_update_composition)
        self.update_timer.setSingleShot(True)

        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)

        title_widget = QWidget()
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(0, 0, 0, 0)

        title_label = QLabel(u"构图辅助工具")
        title_label.setStyleSheet("QLabel { font-size: 14px; font-weight: bold; color: #2E7D32; }")

        author_label = QLabel(u"ADV 集成")
        author_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        author_label.setStyleSheet("QLabel { font-size: 10px; color: #666; font-style: italic; }")

        title_layout.addWidget(title_label)
        title_layout.addStretch()
        title_layout.addWidget(author_label)

        main_layout.addWidget(title_widget)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("QFrame { color: #ddd; }")
        main_layout.addWidget(line)

        camera_group = QGroupBox(u"相机操作")
        camera_layout = QVBoxLayout(camera_group)

        self.camera_info_label = QLabel(u"请选择一个相机")
        self.camera_info_label.setStyleSheet("QLabel { color: #666; font-style: italic; }")
        camera_layout.addWidget(self.camera_info_label)

        button_layout = QHBoxLayout()
        self.create_btn = QPushButton(u"生成构图辅助")
        self.create_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 8px; }")
        self.toggle_btn = QPushButton(u"显示/隐藏")
        self.remove_btn = QPushButton(u"删除")

        button_layout.addWidget(self.create_btn)
        button_layout.addWidget(self.toggle_btn)
        button_layout.addWidget(self.remove_btn)
        camera_layout.addLayout(button_layout)

        self.auto_update_cb = QCheckBox(u"实时更新")
        self.auto_update_cb.setChecked(True)
        self.auto_update_cb.setToolTip(u"修改参数时自动更新构图辅助")
        camera_layout.addWidget(self.auto_update_cb)

        main_layout.addWidget(camera_group)

        tab_widget = QTabWidget()
        main_layout.addWidget(tab_widget)

        tab_widget.addTab(self.create_style_tab(), u"构图样式")
        tab_widget.addTab(self.create_width_tab(), u"线条粗细")
        tab_widget.addTab(self.create_aspect_tab(), u"长宽比")

        bottom_layout = QHBoxLayout()
        self.refresh_btn = QPushButton(u"刷新选择")
        self.close_btn = QPushButton(u"关闭")

        bottom_layout.addWidget(self.refresh_btn)
        bottom_layout.addWidget(self.close_btn)
        main_layout.addLayout(bottom_layout)

        self.create_btn.clicked.connect(self.create_composition)
        self.toggle_btn.clicked.connect(self.toggle_composition)
        self.remove_btn.clicked.connect(self.remove_composition)
        self.refresh_btn.clicked.connect(self.refresh_camera_info)
        self.close_btn.clicked.connect(self.close)

        self.refresh_camera_info()

    def create_style_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        comp_group = QGroupBox(u"构图选项")
        comp_layout = QGridLayout(comp_group)

        self.thirds_cb = QCheckBox(u"三分构图")
        self.thirds_color = QPushButton()
        self.thirds_color.setFixedSize(30, 20)
        self.thirds_color.setStyleSheet("background-color: rgb(255,255,0)")

        self.golden_cb = QCheckBox(u"黄金分割")
        self.golden_color = QPushButton()
        self.golden_color.setFixedSize(30, 20)
        self.golden_color.setStyleSheet("background-color: rgb(255,110,0)")

        self.cross_cb = QCheckBox(u"十字交叉")
        self.cross_color = QPushButton()
        self.cross_color.setFixedSize(30, 20)
        self.cross_color.setStyleSheet("background-color: rgb(0,175,255)")

        self.diagonals_cb = QCheckBox(u"对角线式")
        self.diagonals_color = QPushButton()
        self.diagonals_color.setFixedSize(30, 20)
        self.diagonals_color.setStyleSheet("background-color: rgb(255,0,0)")

        self.triangle_cb = QCheckBox(u"黄金三角")
        self.triangle_color = QPushButton()
        self.triangle_color.setFixedSize(30, 20)
        self.triangle_color.setStyleSheet("background-color: rgb(0,255,175)")

        self.spiral_cb = QCheckBox(u"黄金螺旋")
        self.spiral_color = QPushButton()
        self.spiral_color.setFixedSize(30, 20)
        self.spiral_color.setStyleSheet("background-color: rgb(255,255,255)")

        self.diag_thirds_cb = QCheckBox(u"对角线三分")
        self.diag_thirds_color = QPushButton()
        self.diag_thirds_color.setFixedSize(30, 20)
        self.diag_thirds_color.setStyleSheet("background-color: rgb(255,0,255)")

        self.custom_cb = QCheckBox(u"自定义")
        self.custom_color = QPushButton()
        self.custom_color.setFixedSize(30, 20)
        self.custom_color.setStyleSheet("background-color: rgb(0,255,0)")

        row = 0
        for cb, color_btn in [
            (self.thirds_cb, self.thirds_color),
            (self.golden_cb, self.golden_color),
            (self.cross_cb, self.cross_color),
            (self.diagonals_cb, self.diagonals_color),
            (self.triangle_cb, self.triangle_color),
            (self.spiral_cb, self.spiral_color),
            (self.diag_thirds_cb, self.diag_thirds_color),
            (self.custom_cb, self.custom_color),
        ]:
            comp_layout.addWidget(color_btn, row, 0)
            comp_layout.addWidget(cb, row, 1)
            cb.stateChanged.connect(self.on_setting_changed)
            row += 1

        layout.addWidget(comp_group)

        custom_group = QGroupBox(u"自定义设置")
        custom_layout = QFormLayout(custom_group)

        self.x_divs_spin = QSpinBox()
        self.x_divs_spin.setRange(0, 20)
        self.x_divs_spin.setValue(4)
        self.x_divs_spin.valueChanged.connect(self.on_setting_changed)

        self.y_divs_spin = QSpinBox()
        self.y_divs_spin.setRange(0, 20)
        self.y_divs_spin.setValue(4)
        self.y_divs_spin.valueChanged.connect(self.on_setting_changed)

        custom_layout.addRow(u"X分段数:", self.x_divs_spin)
        custom_layout.addRow(u"Y分段数:", self.y_divs_spin)

        layout.addWidget(custom_group)

        spiral_group = QGroupBox(u"黄金螺旋设置")
        spiral_layout = QFormLayout(spiral_group)

        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(-200, 500)
        self.zoom_spin.setValue(0)
        self.zoom_spin.valueChanged.connect(self.on_setting_changed)

        self.shift_x_spin = QSpinBox()
        self.shift_x_spin.setRange(-100, 100)
        self.shift_x_spin.setValue(0)
        self.shift_x_spin.valueChanged.connect(self.on_setting_changed)

        self.shift_y_spin = QSpinBox()
        self.shift_y_spin.setRange(-100, 100)
        self.shift_y_spin.setValue(0)
        self.shift_y_spin.valueChanged.connect(self.on_setting_changed)

        self.unlock_spiral_cb = QCheckBox(u"解锁螺旋比例")
        self.unlock_spiral_cb.stateChanged.connect(self.on_setting_changed)

        spiral_layout.addRow(u"缩放:", self.zoom_spin)
        spiral_layout.addRow(u"X偏移:", self.shift_x_spin)
        spiral_layout.addRow(u"Y偏移:", self.shift_y_spin)
        spiral_layout.addRow("", self.unlock_spiral_cb)

        layout.addWidget(spiral_group)

        self.thirds_color.clicked.connect(lambda: self.choose_color('thirds'))
        self.golden_color.clicked.connect(lambda: self.choose_color('golden'))
        self.cross_color.clicked.connect(lambda: self.choose_color('cross'))
        self.diagonals_color.clicked.connect(lambda: self.choose_color('diagonals'))
        self.triangle_color.clicked.connect(lambda: self.choose_color('triangle'))
        self.spiral_color.clicked.connect(lambda: self.choose_color('spiral'))
        self.diag_thirds_color.clicked.connect(lambda: self.choose_color('diag_thirds'))
        self.custom_color.clicked.connect(lambda: self.choose_color('custom'))

        self.triangle_cb.setContextMenuPolicy(Qt.CustomContextMenu)
        self.triangle_cb.customContextMenuRequested.connect(self.triangle_context_menu)

        self.spiral_cb.setContextMenuPolicy(Qt.CustomContextMenu)
        self.spiral_cb.customContextMenuRequested.connect(self.spiral_context_menu)

        return widget

    def create_width_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        width_group = QGroupBox(u"线条粗细设置")
        width_layout = QFormLayout(width_group)

        def _add_slider_row(label_text, attr_name):
            slider = QSlider(Qt.Horizontal)
            slider.setRange(1, 10)
            slider.setValue(2)
            value_label = QLabel('2')
            slider.valueChanged.connect(lambda v: value_label.setText(str(v)))
            slider.valueChanged.connect(self.on_setting_changed)

            row_layout = QHBoxLayout()
            row_layout.addWidget(slider)
            row_layout.addWidget(value_label)
            width_layout.addRow(label_text, row_layout)
            return slider

        self.width_thirds_slider = _add_slider_row(u"三分构图:", 'line_width_thirds')
        self.width_golden_slider = _add_slider_row(u"黄金分割:", 'line_width_golden')
        self.width_cross_slider = _add_slider_row(u"十字交叉:", 'line_width_cross')
        self.width_diagonals_slider = _add_slider_row(u"对角线式:", 'line_width_diagonals')
        self.width_triangle_slider = _add_slider_row(u"黄金三角:", 'line_width_triangle')
        self.width_spiral_slider = _add_slider_row(u"黄金螺旋:", 'line_width_spiral')
        self.width_diag_thirds_slider = _add_slider_row(u"对角线三分:", 'line_width_diag_thirds')
        self.width_custom_slider = _add_slider_row(u"自定义:", 'line_width_custom')

        layout.addWidget(width_group)

        reset_btn = QPushButton(u"重置所有线条粗细")
        reset_btn.clicked.connect(self.reset_all_widths)
        layout.addWidget(reset_btn)

        return widget

    def reset_all_widths(self):
        for slider in [
            self.width_thirds_slider,
            self.width_golden_slider,
            self.width_cross_slider,
            self.width_diagonals_slider,
            self.width_triangle_slider,
            self.width_spiral_slider,
            self.width_diag_thirds_slider,
            self.width_custom_slider,
        ]:
            slider.setValue(2)
        self.on_setting_changed()

    def triangle_context_menu(self, position):
        menu = QMenu()
        action1 = menu.addAction(u"模式 1")
        action2 = menu.addAction(u"模式 2")

        action = menu.exec_(self.triangle_cb.mapToGlobal(position))
        if action == action1:
            self.generator.triangle_mode = 0
            self.on_setting_changed()
        elif action == action2:
            self.generator.triangle_mode = 1
            self.on_setting_changed()

    def spiral_context_menu(self, position):
        menu = QMenu()
        action1 = menu.addAction(u"模式 1 (右下开始)")
        action2 = menu.addAction(u"模式 2 (左下开始)")
        action3 = menu.addAction(u"模式 3 (左上开始)")
        action4 = menu.addAction(u"模式 4 (右上开始)")

        action = menu.exec_(self.spiral_cb.mapToGlobal(position))
        if action == action1:
            self.generator.spiral_mode = 0
            self.on_setting_changed()
        elif action == action2:
            self.generator.spiral_mode = 1
            self.on_setting_changed()
        elif action == action3:
            self.generator.spiral_mode = 2
            self.on_setting_changed()
        elif action == action4:
            self.generator.spiral_mode = 3
            self.on_setting_changed()

    def create_aspect_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        aspect_group = QGroupBox(u"长宽比设置")
        aspect_layout = QVBoxLayout(aspect_group)

        self.aspect_combo = QComboBox()
        self.aspect_combo.addItems(self.aspect_names)
        aspect_layout.addWidget(self.aspect_combo)

        custom_aspect_layout = QHBoxLayout()
        self.aspect_x_spin = QDoubleSpinBox()
        self.aspect_x_spin.setRange(0.1, 10.0)
        self.aspect_x_spin.setValue(16.0)

        custom_aspect_layout.addWidget(QLabel(u"宽:"))
        custom_aspect_layout.addWidget(self.aspect_x_spin)
        custom_aspect_layout.addWidget(QLabel(u":"))

        self.aspect_y_spin = QDoubleSpinBox()
        self.aspect_y_spin.setRange(0.1, 10.0)
        self.aspect_y_spin.setValue(9.0)
        custom_aspect_layout.addWidget(self.aspect_y_spin)

        aspect_layout.addLayout(custom_aspect_layout)

        button_layout = QHBoxLayout()
        self.add_aspect_btn = QPushButton(u"添加")
        self.remove_aspect_btn = QPushButton(u"删除")
        self.reset_aspect_btn = QPushButton(u"重置")
        button_layout.addWidget(self.add_aspect_btn)
        button_layout.addWidget(self.remove_aspect_btn)
        button_layout.addWidget(self.reset_aspect_btn)
        aspect_layout.addLayout(button_layout)

        self.portrait_btn = QPushButton(u"横向/纵向切换")
        aspect_layout.addWidget(self.portrait_btn)

        layout.addWidget(aspect_group)

        self.aspect_combo.currentIndexChanged.connect(self.apply_aspect_ratio)
        self.add_aspect_btn.clicked.connect(self.add_custom_aspect)
        self.remove_aspect_btn.clicked.connect(self.remove_aspect)
        self.reset_aspect_btn.clicked.connect(self.reset_aspects)
        self.portrait_btn.clicked.connect(self.toggle_portrait)

        return widget

    def choose_color(self, color_type):
        color = QColorDialog.getColor()
        if color.isValid():
            button = getattr(self, '%s_color' % color_type)
            button.setStyleSheet('background-color: %s' % color.name())

            color_tuple = (color.red() / 255.0, color.green() / 255.0, color.blue() / 255.0)
            setattr(self.generator, 'color_%s' % color_type, color_tuple)
            self.on_setting_changed()

    def on_setting_changed(self):
        if self.auto_update_cb.isChecked() and self.generator.current_image_plane:
            self.update_timer.stop()
            self.update_timer.start(200)

    def auto_update_composition(self):
        try:
            # 检查窗口是否还存在
            if not self or not hasattr(self, 'generator'):
                if hasattr(self, 'update_timer') and self.update_timer:
                    self.update_timer.stop()
                return

            self.update_generator_settings()
            selected = cmds.ls(selection=True)
            if selected and cmds.objExists(selected[0]):
                self.generator.create_composition_for_camera(selected[0])
        except RuntimeError:
            # 窗口已关闭，停止定时器
            if hasattr(self, 'update_timer') and self.update_timer:
                try:
                    self.update_timer.stop()
                except:
                    pass
        except Exception:
            pass

    def refresh_camera_info(self):
        selected = cmds.ls(selection=True)
        if selected:
            camera = selected[0]
            is_camera = False
            if cmds.nodeType(camera) == 'transform':
                shapes = cmds.listRelatives(camera, shapes=True, type='camera')
                if shapes:
                    is_camera = True
            elif cmds.nodeType(camera) == 'camera':
                is_camera = True
                camera = cmds.listRelatives(camera, parent=True)[0]

            if is_camera:
                self.camera_info_label.setText(u"已选择相机: %s" % camera)
                self.camera_info_label.setStyleSheet("QLabel { color: #2E7D32; font-weight: bold; }")
                self.create_btn.setEnabled(True)
            else:
                self.camera_info_label.setText(u"选中的对象不是相机: %s" % camera)
                self.camera_info_label.setStyleSheet("QLabel { color: #D32F2F; }")
                self.create_btn.setEnabled(False)
        else:
            self.camera_info_label.setText(u"请选择一个相机")
            self.camera_info_label.setStyleSheet("QLabel { color: #666; font-style: italic; }")
            self.create_btn.setEnabled(False)

    def update_generator_settings(self):
        self.generator.show_thirds = self.thirds_cb.isChecked()
        self.generator.show_golden = self.golden_cb.isChecked()
        self.generator.show_cross = self.cross_cb.isChecked()
        self.generator.show_diagonals = self.diagonals_cb.isChecked()
        self.generator.show_triangle = self.triangle_cb.isChecked()
        self.generator.show_spiral = self.spiral_cb.isChecked()
        self.generator.show_diag_thirds = self.diag_thirds_cb.isChecked()
        self.generator.show_custom = self.custom_cb.isChecked()

        self.generator.line_width_thirds = self.width_thirds_slider.value()
        self.generator.line_width_golden = self.width_golden_slider.value()
        self.generator.line_width_cross = self.width_cross_slider.value()
        self.generator.line_width_diagonals = self.width_diagonals_slider.value()
        self.generator.line_width_triangle = self.width_triangle_slider.value()
        self.generator.line_width_spiral = self.width_spiral_slider.value()
        self.generator.line_width_diag_thirds = self.width_diag_thirds_slider.value()
        self.generator.line_width_custom = self.width_custom_slider.value()

        self.generator.custom_x_divs = self.x_divs_spin.value()
        self.generator.custom_y_divs = self.y_divs_spin.value()

        self.generator.spiral_zoom = self.zoom_spin.value()
        self.generator.spiral_shift_x = self.shift_x_spin.value()
        self.generator.spiral_shift_y = self.shift_y_spin.value()
        self.generator.spiral_unlocked = self.unlock_spiral_cb.isChecked()

    def create_composition(self):
        selected = cmds.ls(selection=True)
        if not selected:
            cmds.warning(u"请先选择一个相机")
            return

        self.update_generator_settings()
        self.generator.create_composition_for_camera(selected[0])

    def toggle_composition(self):
        self.generator.toggle_composition_visibility()

    def remove_composition(self):
        self.generator.remove_existing_composition()

    def apply_aspect_ratio(self):
        if self.aspect_combo.currentIndex() < len(self.aspect_ratios):
            ratio = self.aspect_ratios[self.aspect_combo.currentIndex()]
            current_width = cmds.getAttr('defaultResolution.width')
            new_height = int(current_width / ratio)

            cmds.setAttr('defaultResolution.height', new_height)
            cmds.setAttr('defaultResolution.deviceAspectRatio', ratio)

    def add_custom_aspect(self):
        x = self.aspect_x_spin.value()
        y = self.aspect_y_spin.value()
        ratio = x / y
        name = '%s:%s' % (x, y)

        self.aspect_ratios.insert(0, ratio)
        self.aspect_names.insert(0, name)

        self.aspect_combo.insertItem(0, name)
        self.aspect_combo.setCurrentIndex(0)
        self.apply_aspect_ratio()

    def remove_aspect(self):
        current_index = self.aspect_combo.currentIndex()
        if current_index >= 0 and len(self.aspect_ratios) > 1:
            self.aspect_ratios.pop(current_index)
            self.aspect_names.pop(current_index)
            self.aspect_combo.removeItem(current_index)

    def reset_aspects(self):
        self.aspect_ratios = [1.414, 1, 1.25, 1.333, 1.5, 1.7, 1.6, 1.37, 1.85, 2, 2.35, 2.39, 2.76]
        self.aspect_names = ["A4/A3", "1:1", "5:4", "4:3", "3:2", "16:9", "16:10", "1.37:1", "1.85:1", "2:1", "2.35:1", "2.39:1", "2.76:1"]

        self.aspect_combo.clear()
        self.aspect_combo.addItems(self.aspect_names)
        self.aspect_x_spin.setValue(16.0)
        self.aspect_y_spin.setValue(9.0)

    def toggle_portrait(self):
        current_width = cmds.getAttr('defaultResolution.width')
        current_height = cmds.getAttr('defaultResolution.height')

        cmds.setAttr('defaultResolution.width', current_height)
        cmds.setAttr('defaultResolution.height', current_width)

        new_ratio = float(current_height) / float(current_width) if current_width else 1.0
        cmds.setAttr('defaultResolution.deviceAspectRatio', new_ratio)

    def load_settings(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    settings = json.load(f)

                self.thirds_cb.setChecked(settings.get('thirds', False))
                self.golden_cb.setChecked(settings.get('golden', False))
                self.cross_cb.setChecked(settings.get('cross', False))
                self.diagonals_cb.setChecked(settings.get('diagonals', False))
                self.triangle_cb.setChecked(settings.get('triangle', False))
                self.spiral_cb.setChecked(settings.get('spiral', False))
                self.diag_thirds_cb.setChecked(settings.get('diag_thirds', False))
                self.custom_cb.setChecked(settings.get('custom', False))

                self.width_thirds_slider.setValue(settings.get('width_thirds', 2))
                self.width_golden_slider.setValue(settings.get('width_golden', 2))
                self.width_cross_slider.setValue(settings.get('width_cross', 2))
                self.width_diagonals_slider.setValue(settings.get('width_diagonals', 2))
                self.width_triangle_slider.setValue(settings.get('width_triangle', 2))
                self.width_spiral_slider.setValue(settings.get('width_spiral', 2))
                self.width_diag_thirds_slider.setValue(settings.get('width_diag_thirds', 2))
                self.width_custom_slider.setValue(settings.get('width_custom', 2))

                self.x_divs_spin.setValue(settings.get('x_divs', 4))
                self.y_divs_spin.setValue(settings.get('y_divs', 4))
                self.zoom_spin.setValue(settings.get('zoom', 0))
                self.shift_x_spin.setValue(settings.get('shift_x', 0))
                self.shift_y_spin.setValue(settings.get('shift_y', 0))
                self.unlock_spiral_cb.setChecked(settings.get('unlock_spiral', False))
                self.auto_update_cb.setChecked(settings.get('auto_update', True))

                if 'aspect_ratios' in settings:
                    self.aspect_ratios = settings['aspect_ratios']
                if 'aspect_names' in settings:
                    self.aspect_names = settings['aspect_names']
                    self.aspect_combo.clear()
                    self.aspect_combo.addItems(self.aspect_names)
            except Exception as e:
                print(u"加载设置失败: %s" % e)

    def save_settings(self):
        settings = {
            'thirds': self.thirds_cb.isChecked(),
            'golden': self.golden_cb.isChecked(),
            'cross': self.cross_cb.isChecked(),
            'diagonals': self.diagonals_cb.isChecked(),
            'triangle': self.triangle_cb.isChecked(),
            'spiral': self.spiral_cb.isChecked(),
            'diag_thirds': self.diag_thirds_cb.isChecked(),
            'custom': self.custom_cb.isChecked(),
            'width_thirds': self.width_thirds_slider.value(),
            'width_golden': self.width_golden_slider.value(),
            'width_cross': self.width_cross_slider.value(),
            'width_diagonals': self.width_diagonals_slider.value(),
            'width_triangle': self.width_triangle_slider.value(),
            'width_spiral': self.width_spiral_slider.value(),
            'width_diag_thirds': self.width_diag_thirds_slider.value(),
            'width_custom': self.width_custom_slider.value(),
            'x_divs': self.x_divs_spin.value(),
            'y_divs': self.y_divs_spin.value(),
            'zoom': self.zoom_spin.value(),
            'shift_x': self.shift_x_spin.value(),
            'shift_y': self.shift_y_spin.value(),
            'unlock_spiral': self.unlock_spiral_cb.isChecked(),
            'auto_update': self.auto_update_cb.isChecked(),
            'aspect_ratios': self.aspect_ratios,
            'aspect_names': self.aspect_names,
        }

        try:
            with open(self.config_file, 'w') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(u"保存设置失败: %s" % e)

    def closeEvent(self, event):
        # 停止定时器
        if hasattr(self, 'update_timer') and self.update_timer:
            try:
                self.update_timer.stop()
            except:
                pass
        self.save_settings()
        event.accept()


composition_helper_ui = None


def show_composition_helper():
    global composition_helper_ui

    try:
        if composition_helper_ui:
            try:
                composition_helper_ui.close()
            except Exception:
                pass
            composition_helper_ui = None

        composition_helper_ui = CompositionHelperUI()
        composition_helper_ui.show()
        return composition_helper_ui
    except Exception as e:
        print(u"创建构图辅助界面失败: %s" % e)
        return None


def show():
    return show_composition_helper()
