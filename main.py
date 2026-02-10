import math
import copy
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QScrollArea, QFrame,
    QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QSlider, QPushButton,
    QGroupBox,
)
from PyQt6.QtCore import Qt, QTimer, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QPainterPath, QFont

# Constants
HIT_R = 10
PT_R = 5
STEPS = 200
EMPTY_START = [[]]
DEFAULT_CANVAS_WIDTH = 800
DEFAULT_CANVAS_HEIGHT = 500
HODO_OFFSET = (80, 80)
TANGENT_SCALE = 0.15

def lerp(a, b, t):
    return {"x": (1 - t) * a["x"] + t * b["x"], "y": (1 - t) * a["y"] + t * b["y"]}

def dist(p, x, y):
    return math.hypot(p["x"] - x, p["y"] - y)

def point_to_segment_distance(p, a, b):
    vx, vy = b["x"] - a["x"], b["y"] - a["y"]
    wx, wy = p["x"] - a["x"], p["y"] - a["y"]
    c1 = vx * wx + vy * wy
    if c1 <= 0:
        return math.hypot(p["x"] - a["x"], p["y"] - a["y"])
    c2 = vx * vx + vy * vy
    if c2 <= c1:
        return math.hypot(p["x"] - b["x"], p["y"] - b["y"])
    t = c1 / c2
    proj = {"x": a["x"] + t * vx, "y": a["y"] + t * vy}
    return math.hypot(p["x"] - proj["x"], p["y"] - proj["y"])

def binom(n, k):
    r = 1
    for i in range(1, k + 1):
        r = r * (n + 1 - i) / i
    return r

def bern(n, i, t):
    return binom(n, i) * (t ** i) * ((1 - t) ** (n - i))

def de_casteljau(points, t):
    tmp = [{"x": p["x"], "y": p["y"]} for p in points]
    n = len(points)
    for r in range(1, n):
        for i in range(n - r):
            tmp[i] = lerp(tmp[i], tmp[i + 1], t)
    return tmp[0]

def de_casteljau_levels(points, t):
    levels = []
    cur = [{"x": p["x"], "y": p["y"]} for p in points]
    levels.append(cur)
    for r in range(1, len(points)):
        next_row = [lerp(cur[i], cur[i + 1], t) for i in range(len(cur) - 1)]
        levels.append(next_row)
        cur = next_row
    return levels

def hodograph_control_points(points):
    n = len(points) - 1
    if n <= 0:
        return []
    return [
        {"x": n * (points[i + 1]["x"] - points[i]["x"]),
         "y": n * (points[i + 1]["y"] - points[i]["y"])}
        for i in range(n)
    ]

def derivative(points, t):
    n = len(points) - 1
    if n <= 0:
        return {"x": 0, "y": 0}
    dx = dy = 0
    for i in range(n):
        dx += n * (points[i + 1]["x"] - points[i]["x"]) * bern(n - 1, i, t)
        dy += n * (points[i + 1]["y"] - points[i]["y"]) * bern(n - 1, i, t)
    return {"x": dx, "y": dy}

def second_derivative(points, t):
    n = len(points) - 1
    if n <= 1:
        return {"x": 0, "y": 0}
    dx = dy = 0
    for i in range(n - 1):
        dx += n * (n - 1) * (points[i + 2]["x"] - 2 * points[i + 1]["x"] + points[i]["x"]) * bern(n - 2, i, t)
        dy += n * (n - 1) * (points[i + 2]["y"] - 2 * points[i + 1]["y"] + points[i]["y"]) * bern(n - 2, i, t)
    return {"x": dx, "y": dy}

def curvature_at(points, t):
    d = derivative(points, t)
    dd = second_derivative(points, t)
    v = math.hypot(d["x"], d["y"])
    if v < 1e-9:
        return 0
    return abs(d["x"] * dd["y"] - d["y"] * dd["x"]) / (v ** 3)

def approximate_length(seg, steps=200):
    L = 0
    prev = de_casteljau(seg, 0)
    for i in range(1, steps + 1):
        tt = i / steps
        p = de_casteljau(seg, tt)
        L += math.hypot(p["x"] - prev["x"], p["y"] - prev["y"])
        prev = p
    return L


class BezierCanvas(QWidget):
    """Main canvas: control polygon, Bezier curve, hodograph, tangent, de Casteljau."""
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app = app_state
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._selected_point = None

    def size_from_state(self):
        w = getattr(self.app, "canvas_w", DEFAULT_CANVAS_WIDTH)
        h = getattr(self.app, "canvas_h", DEFAULT_CANVAS_HEIGHT)
        return w, h

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

    def _mouse_to_logical(self, pos):
        w, h = self.size_from_state()
        r = self.rect()
        sx = r.width() / w if w else 1
        sy = r.height() / h if h else 1
        return pos.x() / sx, pos.y() / sy

    def mousePressEvent(self, event):
        x, y = self._mouse_to_logical(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._add_control_point(x, y)
            self.app.redraw()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._remove_point(x, y)
            self.app.redraw()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._selected_point = self._find_closest_point(x, y)
            if self._selected_point:
                self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._selected_point is not None:
            x, y = self._mouse_to_logical(event.position().toPoint())
            self._selected_point["x"] = x
            self._selected_point["y"] = y
            self.app.redraw()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._selected_point = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def _find_closest_point(self, x, y):
        best = None
        best_d = float("inf")
        for seg in self.app.segments:
            for p in seg:
                d = dist(p, x, y)
                if d < best_d:
                    best_d = d
                    best = p
        return best if best_d <= HIT_R else None

    def _add_control_point(self, x, y):
        segments = self.app.segments
        best_seg = 0
        best_d = float("inf")
        p = {"x": x, "y": y}
        for si, seg in enumerate(segments):
            for i in range(len(seg) - 1):
                d = point_to_segment_distance(p, seg[i], seg[i + 1])
                if d < best_d:
                    best_d = d
                    best_seg = si
            if len(seg) == 1:
                d = dist(seg[0], x, y)
                if d < best_d:
                    best_d = d
                    best_seg = si
        seg = segments[best_seg]
        if len(seg) == 0:
            seg.append({"x": x, "y": y})
            return
        idx = min(range(len(seg)), key=lambda i: dist(seg[i], x, y))
        seg.insert(idx + 1, {"x": x, "y": y})

    def _remove_point(self, x, y):
        for seg in self.app.segments:
            if len(seg) <= 2:
                continue
            for i, p in enumerate(seg):
                if dist(p, x, y) < HIT_R:
                    seg.pop(i)
                    return

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        w, h = self.size_from_state()
        r = self.rect()
        painter.fillRect(r, QColor("#ffffff"))
        if w <= 0 or h <= 0:
            return
        sx = r.width() / w
        sy = r.height() / h
        painter.scale(sx, sy)

        segments = self.app.segments
        t = self.app.t
        show_casteljau = self.app.show_casteljau
        show_hodograph = self.app.show_hodograph
        ox, oy = HODO_OFFSET

        for seg in segments:
            if len(seg) < 2:
                continue
            # Per-segment point and derivative at t (for tangent vector)
            p_seg = de_casteljau(seg, t)
            d_seg = derivative(seg, t)
            # Control polygon (black)
            path = QPainterPath()
            path.moveTo(seg[0]["x"], seg[0]["y"])
            for p in seg:
                path.lineTo(p["x"], p["y"])
            painter.setPen(QPen(QColor("black"), 1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            # Control points (orange outline only)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("orange"), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for p in seg:
                painter.drawEllipse(QPointF(p["x"], p["y"]), PT_R, PT_R)
            # Bezier curve (red) — stroke only
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("red"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            prev = de_casteljau(seg, 0)
            path = QPainterPath()
            path.moveTo(prev["x"], prev["y"])
            for i in range(1, STEPS + 1):
                tt = i / STEPS
                p = de_casteljau(seg, tt)
                path.lineTo(p["x"], p["y"])
            painter.drawPath(path)

            # Tangent vector (green) — for this segment, always when segment has curve
            to_x = p_seg["x"] + d_seg["x"] * TANGENT_SCALE
            to_y = p_seg["y"] + d_seg["y"] * TANGENT_SCALE
            self._draw_arrow(painter, p_seg["x"], p_seg["y"], to_x, to_y, QColor(0, 160, 80, 242))

            # Hodograph (blue) — stroke only
            if show_hodograph and len(seg) >= 2:
                h_ctrl = hodograph_control_points(seg)
                if len(h_ctrl) >= 2:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor(0, 0, 255, 191), 1.75, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                    hp_prev = de_casteljau(h_ctrl, 0)
                    path = QPainterPath()
                    path.moveTo(hp_prev["x"] + ox, hp_prev["y"] + oy)
                    for i in range(1, STEPS + 1):
                        tt = i / STEPS
                        hp = de_casteljau(h_ctrl, tt)
                        path.lineTo(hp["x"] + ox, hp["y"] + oy)
                    painter.drawPath(path)
                    # Hodograph origin — outline only
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor(0, 0, 255, 217), 1))
                    painter.drawEllipse(QPointF(ox, oy), 3.5, 3.5)
                    painter.setPen(QPen(QColor("black")))
                    painter.setFont(QFont("Arial", 12))
                    painter.drawText(int(ox + 10), int(oy - 8), "Hodograph (B'(t))")

            # de Casteljau levels — lines and outline-only points
            if show_casteljau:
                levels = de_casteljau_levels(seg, t)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for r in range(len(levels) - 1):
                    lvl = levels[r]
                    painter.setPen(QPen(QColor(0, 0, 0, 64), 1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                    path = QPainterPath()
                    path.moveTo(lvl[0]["x"], lvl[0]["y"])
                    for p in lvl[1:]:
                        path.lineTo(p["x"], p["y"])
                    painter.drawPath(path)
                    painter.setPen(QPen(QColor(0, 0, 0, 140), 1))
                    for p in lvl:
                        painter.drawEllipse(QPointF(p["x"], p["y"]), 3.5, 3.5)
                last = levels[-1][0]
                painter.setPen(QPen(QColor(255, 0, 0, 217), 1.5))
                painter.drawEllipse(QPointF(last["x"], last["y"]), 5.5, 5.5)

    def _draw_arrow(self, painter, fx, fy, tx, ty, color):
        head_len = 8
        dx = tx - fx
        dy = ty - fy
        a = math.atan2(dy, dx)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(int(fx), int(fy), int(tx), int(ty))
        path = QPainterPath()
        path.moveTo(tx, ty)
        path.lineTo(tx - head_len * math.cos(a - math.pi / 6), ty - head_len * math.sin(a - math.pi / 6))
        path.lineTo(tx - head_len * math.cos(a + math.pi / 6), ty - head_len * math.sin(a + math.pi / 6))
        path.closeSubpath()
        painter.drawPath(path)


class AppState:
    """Shared state and redraw trigger."""
    def __init__(self, main_window):
        self.main_window = main_window
        self.segments = copy.deepcopy(EMPTY_START)
        self.t = 0.0
        self.animate = False
        self.speed = 1.0
        self.show_casteljau = True
        self.show_hodograph = True
        self.canvas_w = DEFAULT_CANVAS_WIDTH
        self.canvas_h = DEFAULT_CANVAS_HEIGHT

    def redraw(self):
        self.main_window.refresh_ui_and_canvases()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bezier curves & hodograph — de Casteljau")
        self.app = AppState(self)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animation_step)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar 
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: #24283b; border: none; }
            QWidget#sidebar { background: #24283b; }
        """)
        scroll.setFixedWidth(320)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(300)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setSpacing(12)

        # Controls
        grp = QGroupBox("Controls")
        grp.setStyleSheet("QGroupBox { font-weight: bold; color: #9aa5ce; }")
        form = QVBoxLayout(grp)
        self.chk_animate = QCheckBox("Animate along curve")
        self.chk_animate.setStyleSheet("color: #c0caf5;")
        self.chk_animate.stateChanged.connect(self._on_animate_changed)
        form.addWidget(self.chk_animate)

        form.addWidget(QLabel("Speed"))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(5, 50)  # 0.5 to 5 in 0.1 steps -> 5..50
        self.speed_slider.setValue(10)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        form.addWidget(self.speed_slider)
        self.lbl_speed = QLabel("1×")
        self.lbl_speed.setStyleSheet("color: #9aa5ce;")
        form.addWidget(self.lbl_speed)

        form.addWidget(QLabel("t"))
        self.t_slider = QSlider(Qt.Orientation.Horizontal)
        self.t_slider.setRange(0, 100)
        self.t_slider.setValue(0)
        self.t_slider.valueChanged.connect(self._on_t_changed)
        form.addWidget(self.t_slider)
        self.lbl_t = QLabel("0.00")
        self.lbl_t.setStyleSheet("color: #9aa5ce;")
        form.addWidget(self.lbl_t)

        self.chk_casteljau = QCheckBox("Show de Casteljau steps")
        self.chk_casteljau.setStyleSheet("color: #c0caf5;")
        self.chk_casteljau.setChecked(True)
        self.chk_casteljau.stateChanged.connect(lambda: self._set_bool("show_casteljau", self.chk_casteljau.isChecked()))
        form.addWidget(self.chk_casteljau)

        self.chk_hodograph = QCheckBox("Show hodograph (B′(t))")
        self.chk_hodograph.setStyleSheet("color: #c0caf5;")
        self.chk_hodograph.setChecked(True)
        self.chk_hodograph.stateChanged.connect(lambda: self._set_bool("show_hodograph", self.chk_hodograph.isChecked()))
        form.addWidget(self.chk_hodograph)

        btn_add = QPushButton("Add segment")
        btn_add.clicked.connect(self._add_segment)
        form.addWidget(btn_add)
        btn_remove = QPushButton("Remove segment")
        btn_remove.clicked.connect(self._remove_segment)
        form.addWidget(btn_remove)

        btn_reset = QPushButton("Reset")
        btn_reset.setStyleSheet("background: #7aa2f7; color: #1a1b26;")
        btn_reset.clicked.connect(self._reset)
        form.addWidget(btn_reset)

        side_layout.addWidget(grp)

        # Legend
        leg_grp = QGroupBox("Legend")
        leg_grp.setStyleSheet("QGroupBox { font-weight: bold; color: #9aa5ce; }")
        leg_layout = QVBoxLayout(leg_grp)
        for text, color in [
            ("Black line — Control polygon", "black"),
            ("Orange outline — Control points", "orange"),
            ("Red — Bezier curve", "red"),
            ("Blue — Hodograph (derivative B′(t))", "blue"),
            ("Green — Speed / tangent vector at t", "green"),
        ]:
            l = QLabel(f"  {text}")
            l.setStyleSheet(f"color: #9aa5ce;")
            leg_layout.addWidget(l)
        side_layout.addWidget(leg_grp)

        # Readout
        read_grp = QGroupBox("Readout")
        read_grp.setStyleSheet("QGroupBox { font-weight: bold; color: #9aa5ce; }")
        read_layout = QVBoxLayout(read_grp)
        self.lbl_info_t = QLabel("t = 0.00")
        self.lbl_info_len = QLabel("Length ≈ 0 px")
        for l in (self.lbl_info_t, self.lbl_info_len):
            l.setStyleSheet("color: #9aa5ce;")
            read_layout.addWidget(l)
        side_layout.addWidget(read_grp)

        # Instructions
        inst_grp = QGroupBox("Instructions")
        inst_grp.setStyleSheet("QGroupBox { font-weight: bold; color: #9aa5ce; }")
        inst_layout = QVBoxLayout(inst_grp)
        inst_text = (
            "Shift + left click → add control point\n"
            "Left click + drag → move control point\n"
            "Right click → delete nearest point (min 2 per segment)\n"
            "Reset → clear canvas (empty)"
        )
        inst_lbl = QLabel(inst_text)
        inst_lbl.setWordWrap(True)
        inst_lbl.setStyleSheet("color: #9aa5ce;")
        inst_layout.addWidget(inst_lbl)
        side_layout.addWidget(inst_grp)

        side_layout.addStretch()
        scroll.setWidget(sidebar)
        layout.addWidget(scroll)

        # Canvases (scrollable)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setStyleSheet("QScrollArea { background: #1a1b26; border: none; }")

        right = QFrame()
        right.setFrameStyle(QFrame.Shape.NoFrame)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(6)

        main_heading = QLabel("Bezier curve & hodograph")
        main_heading.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #9aa5ce; "
            "margin-bottom: 2px;"
        )
        right_layout.addWidget(main_heading)
        self.bezier_canvas = BezierCanvas(self.app)
        self.bezier_canvas.setFixedSize(DEFAULT_CANVAS_WIDTH, DEFAULT_CANVAS_HEIGHT)
        self.bezier_canvas.setStyleSheet("background: white; border: 1px solid #3b4261;")
        right_layout.addWidget(self.bezier_canvas, 1, Qt.AlignmentFlag.AlignCenter)

        right_scroll.setWidget(right)
        layout.addWidget(right_scroll)

        self.setStyleSheet("""
            QMainWindow { background: #1a1b26; }
            QWidget { background: #24283b; color: #c0caf5; }
            QGroupBox { color: #9aa5ce; }
            QPushButton { background: #22283a; color: #c0caf5; border: 1px solid #3b4261; }
            QPushButton:hover { background: #2c3550; }
            QSpinBox, QSlider { color: #c0caf5; }
        """)
        self.refresh_ui_and_canvases()

    def _set_bool(self, name, value):
        setattr(self.app, name, value)
        self.app.redraw()

    def _on_animate_changed(self):
        self.app.animate = self.chk_animate.isChecked()
        if self.app.animate:
            self._timer.start(16)  # ~60 fps
        else:
            self._timer.stop()
        self.app.redraw()

    def _on_speed_changed(self):
        v = self.speed_slider.value() / 10.0
        self.app.speed = v
        self.lbl_speed.setText(f"{v}×")
        self.app.redraw()

    def _on_t_changed(self):
        self.app.t = self.t_slider.value() / 100.0
        self.lbl_t.setText(f"{self.app.t:.2f}")
        self.app.redraw()

    def _animation_step(self):
        self.app.t += 0.002 * self.app.speed
        if self.app.t > 1:
            self.app.t = 0
        self.t_slider.setValue(int(round(self.app.t * 100)))
        self.lbl_t.setText(f"{self.app.t:.2f}")
        self.app.redraw()

    def _add_segment(self):
        self.app.segments.append([
            {"x": 150, "y": 350},
            {"x": 350, "y": 150},
            {"x": 600, "y": 350},
        ])
        self.app.redraw()

    def _remove_segment(self):
        if len(self.app.segments) > 1:
            self.app.segments.pop()
            self.app.redraw()

    def _reset(self):
        self.app.segments = copy.deepcopy(EMPTY_START)
        self.app.t = 0
        self.app.animate = False
        self.chk_animate.setChecked(False)
        self._timer.stop()
        self.t_slider.setValue(0)
        self.lbl_t.setText("0.00")
        self.app.redraw()

    def refresh_ui_and_canvases(self):
        total_len = sum(approximate_length(seg) for seg in self.app.segments if len(seg) >= 2)
        self.lbl_info_t.setText(f"t = {self.app.t:.2f}")
        self.lbl_info_len.setText(f"Length ≈ {total_len:.1f} px")
        self.bezier_canvas.update()


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
