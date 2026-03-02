# -*- coding: utf-8 -*-
"""
早茶奈工具箱 — 启动器
将此文件拖入 Maya 视口即可启动悬浮工具箱。
"""
import os, sys, importlib

# 优先使用脚本自身目录；若不可用则从 sys.path 中猜测 Chanai_Tools 目录
_DIR = ""
try:
    _DIR = os.path.dirname(os.path.abspath(__file__))
except Exception:
    _DIR = ""
if not _DIR:
    for _p in list(sys.path):
        try:
            _pp = os.path.normpath(str(_p))
            if _pp and os.path.basename(_pp).lower() == "chanai_tools":
                _DIR = _pp
                break
        except Exception:
            pass
if not _DIR:
    _DIR = os.getcwd()

if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

try:
    _reload = importlib.reload
except Exception:
    try:
        _reload = reload
    except Exception:
        _reload = None


def _launch():
    if "chanai_toolbox" in sys.modules:
        if _reload is not None:
            _reload(sys.modules["chanai_toolbox"])
    import chanai_toolbox
    chanai_toolbox.main()


# 拖入 Maya 视口时调用
def onMayaDroppedPythonFile(*args, **kwargs):
    _launch()


# 直接运行（Script Editor 执行 / 双击）
_launch()
