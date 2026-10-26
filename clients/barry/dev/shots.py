#!/usr/bin/env python3
"""Dev only (not packed): runs the app offscreen in Barry Simulator's Qt against the
mock server, drives it with a script of steps, and saves PNGs.

  PYTHONPATH=<Simulator>/Resources/site-packages <Simulator>/MacOS/python dev/shots.py OUT_DIR [SCALE] [SCRIPT.json]

Steps (JSON list): {"wait": ms} {"call": "push", "args": [..]} {"click": objectName}
{"type": "text"} {"hold": objectName, "ms": 700} {"clickAt": [x, y]} {"drag": [x1, y1, x2, y2]} {"shot": "name"}
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(APP))
SIM = os.environ.get("BARRY_SIM_RES", "/Applications/Barry Simulator.app/Contents/Resources")
TOOLS = os.path.join(SIM, "sim")
sys.path.insert(0, TOOLS)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if not os.environ.get("ONI_COMPANION_REAL"):
    os.environ["ONI_COMPANION_MOCK"] = REPO
import barry_apps  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtCore import Q_ARG, QMetaObject, QObject, QPointF, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QFontDatabase, QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickWindow  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
import shiboken6  # noqa: E402

out = os.path.abspath(sys.argv[1])
scale = float(sys.argv[2]) if len(sys.argv) > 2 else 0.75
script = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else []
os.makedirs(out, exist_ok=True)
data = os.path.join(out, "data")
os.makedirs(data, exist_ok=True)

m = barry_apps.read_manifest(APP)
service, url, token = barry_apps.start_service(APP, m["service"], dict(os.environ), None)
argv = [sys.argv[0], "--", APP, m["main"], m["id"], m["name"], data, "windowed", url, token]
app = QGuiApplication(argv)
fonts = os.path.join(SIM, "fonts")
if os.path.isdir(fonts):
    for f in sorted(os.listdir(fonts)):
        if f.endswith((".ttf", ".otf")):
            QFontDatabase.addApplicationFont(os.path.join(fonts, f))
engine = QQmlApplicationEngine()
engine.load(QUrl.fromLocalFile(os.path.join(TOOLS, "AppHost.qml")))
win = shiboken6.wrapInstance(shiboken6.getCppPointer(engine.rootObjects()[0])[0], QQuickWindow)
if os.environ.get("SHOTS_HIDDEN"):      # real GPU rendering (ShaderEffect needs it) without a visible window
    win.setFlags(Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus | Qt.Tool)
    win.setOpacity(0.0)
win.setWidth(round(1240 * scale))
win.setHeight(round(1080 * scale))
win.show()


def find(name):
    todo = [win.contentItem()]
    while todo:
        it = todo.pop()
        if it.objectName() == name and it.isVisible():
            return it
        todo.extend(it.childItems())
    return None


def run(steps):
    if not steps:
        barry_apps.stop_service(service)
        app.quit()
        return
    st, rest = steps[0], steps[1:]
    delay = 0
    if "wait" in st:
        delay = st["wait"]
    elif "call" in st:
        root = find("oniRoot")
        qargs = [Q_ARG("QVariant", a) for a in st.get("args", [])]
        ok = QMetaObject.invokeMethod(root, st["call"], *qargs)
        print("call", st["call"], st.get("args"), ok, flush=True)
        delay = 400
    elif "pushfile" in st:
        root = find("oniRoot")
        obj = json.load(open(os.path.join(REPO, st["pushfile"])))
        entry = {"type": "screen", "path": st.get("path", "nope"), "cache": obj}
        QMetaObject.invokeMethod(root, "push", Q_ARG("QVariant", entry))
        delay = 600
    elif "resize" in st:
        win.setWidth(st["resize"][0])
        win.setHeight(st["resize"][1])
        delay = 600
    elif "click" in st:
        it = find(st["click"])
        if it is None:
            print("NO ITEM", st["click"], flush=True)
        else:
            c = it.mapToScene(QPointF(it.width() / 2, it.height() / 2)).toPoint()
            QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, c)
            print("click", st["click"], c, flush=True)
        delay = 400
    elif "hold" in st:     # {"hold": objectName, "ms": 700}: press, wait, release (a long press)
        it = find(st["hold"])
        if it is None:
            print("NO ITEM", st["hold"], flush=True)
        else:
            c = it.mapToScene(QPointF(it.width() / 2, it.height() / 2)).toPoint()
            QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, c)
            print("hold", st["hold"], c, flush=True)

            def release(c=c):
                QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, c)
                QTimer.singleShot(400, lambda: run(rest))
            QTimer.singleShot(st.get("ms", 700), release)
            return
        delay = 400
    elif "clickAt" in st:  # scene coordinates
        c = QPointF(st["clickAt"][0], st["clickAt"][1]).toPoint()
        QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, c)
        delay = 400
    elif "drag" in st:     # {"drag": [x1, y1, x2, y2]} in scene coordinates: a finger drag (scrolls a page)
        a = QPointF(st["drag"][0], st["drag"][1]).toPoint()
        b = QPointF(st["drag"][2], st["drag"][3]).toPoint()
        QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, a)
        for i in range(1, 13):
            QTest.mouseMove(win, QPointF(a.x() + (b.x() - a.x()) * i / 12, a.y() + (b.y() - a.y()) * i / 12).toPoint())
        QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, b)
        delay = 900
    elif "type" in st:
        for ch in st["type"]:
            for typ in (QEvent.KeyPress, QEvent.KeyRelease):
                QGuiApplication.sendEvent(win, QKeyEvent(typ, ord(ch.upper()), Qt.NoModifier, ch))
        delay = 600
    elif "shot" in st:
        p = os.path.join(out, st["shot"] + ".png")
        print("shot", p, win.grabWindow().save(p), flush=True)
    QTimer.singleShot(delay, lambda: run(rest))


QTimer.singleShot(1500, lambda: run(script))
app.exec()
barry_apps.stop_service(service)
