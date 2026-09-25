"""Minimal normal-state dashboard pet prototype."""
from functools import lru_cache
from pathlib import Path
import random
import sys

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject


NORMAL_FRAMES = Path(__file__).resolve().parents[2] / "assets/pet/normal-2"
JUMP_FRAMES = Path(__file__).resolve().parents[2] / "assets/pet/jump"
RESTING_FRAMES = Path(__file__).resolve().parents[2] / "assets/pet/resting"
SLEEP_Z_FRAMES = Path(__file__).resolve().parents[2] / "assets/pet/sleep-z"
WORKING_FRAMES = Path(__file__).resolve().parents[2] / "assets/pet/working"
PET_HEIGHT = 72
PET_CANVAS_X_OFFSET = -14
JUMP_CANVAS_X_OFFSET = -18
RESTING_CANVAS_X_OFFSET = -12
WORKING_CANVAS_X_OFFSET = -10
IDLE_FRAME_INDEX = 0
BLINK_DELAY_MIN_MS = 2000
BLINK_DELAY_MAX_MS = 5000
TAIL_DELAY_MIN_MS = 3500
TAIL_DELAY_MAX_MS = 8000
BLINK_PROBABILITY = .72
EVENT_FRAME_INTERVAL_MS = 90
JUMP_DURATION_MS = 650
JUMP_TIMER_INTERVAL_MS = 16
JUMP_ARC_HEIGHT = 38.4
DOCK_TARGET = "__bottom_right__"
SLEEP_DELAY_MS = 65000
SLEEP_TRANSITION_INTERVAL_MS = 180
SLEEP_Z_INTERVAL_MS = 400
SLEEP_BODY_FRAME = 4
FOCUS_DURATION_MS = 30 * 60 * 1000
FOCUS_TIMER_INTERVAL_MS = 250
WORKING_FRAME_INTERVAL_MS = 400
FOCUS_HUD_WIDTH = 74
FOCUS_HUD_HEIGHT = 23
ATTENTION_BUBBLE_WIDTH = 154
ATTENTION_BUBBLE_HEIGHT = 29

# Columns two and three in Normal_State_2 place the whole pet progressively
# farther left. Align them to the neutral first column before scaling so a
# blink or tail twitch does not look like the pet is sliding sideways.
FRAME_X_ALIGNMENT = (0, 35, 40, 0, 35, 40)

# The new sheet has one neutral pose, two blink poses, and three restrained
# tail poses. Both events finish on the canonical neutral frame.
IDLE_EVENTS = {
    "blink": (1, 2, 1, 0),
    "tail": (3, 4, 5, 3, 0),
}


@lru_cache(maxsize=2)
def normal_frames(height=PET_HEIGHT):
    """Load and scale the fixed-canvas frames once for all graph refreshes."""
    frames = []
    paths = sorted(NORMAL_FRAMES.glob("*.png"))
    canvas_width = 0
    sources = []
    for index, path in enumerate(paths):
        source = QPixmap(str(path))
        if not source.isNull():
            offset = (FRAME_X_ALIGNMENT[index]
                      if index < len(FRAME_X_ALIGNMENT) else 0)
            sources.append((source, offset))
            canvas_width = max(canvas_width, source.width() + offset)
    for source, offset in sources:
        aligned = QPixmap(canvas_width, source.height())
        aligned.fill(Qt.GlobalColor.transparent)
        painter = QPainter(aligned)
        painter.drawPixmap(offset, 0, source)
        painter.end()
        frames.append(aligned.scaledToHeight(
            height, Qt.TransformationMode.SmoothTransformation))
    return tuple(frames)


@lru_cache(maxsize=4)
def jump_frames(height=PET_HEIGHT, mirrored=False):
    """Load the fixed-canvas jump once, mirroring only in memory when needed."""
    frames = []
    transform = QTransform().scale(-1, 1)
    for path in sorted(JUMP_FRAMES.glob("*.png")):
        source = QPixmap(str(path))
        if source.isNull():
            continue
        frame = source.scaledToHeight(
            height, Qt.TransformationMode.SmoothTransformation)
        if mirrored:
            frame = frame.transformed(
                transform, Qt.TransformationMode.SmoothTransformation)
        frames.append(frame)
    return tuple(frames)


@lru_cache(maxsize=2)
def resting_frames(height=PET_HEIGHT):
    """Load the aligned falling-asleep frames and fixed sleeping body once."""
    frames = []
    for path in sorted(RESTING_FRAMES.glob("*.png")):
        source = QPixmap(str(path))
        if not source.isNull():
            frames.append(source.scaledToHeight(
                height, Qt.TransformationMode.SmoothTransformation))
    return tuple(frames)


@lru_cache(maxsize=2)
def sleep_z_frames(height=PET_HEIGHT):
    """Load transparent Z-only overlays for the fixed sleeping body."""
    frames = []
    for path in sorted(SLEEP_Z_FRAMES.glob("*.png")):
        source = QPixmap(str(path))
        if not source.isNull():
            frames.append(source.scaledToHeight(
                height, Qt.TransformationMode.SmoothTransformation))
    return tuple(frames)


@lru_cache(maxsize=2)
def working_frames(height=PET_HEIGHT):
    """Load the fixed-canvas focus-session animation once."""
    frames = []
    for path in sorted(WORKING_FRAMES.glob("*.png")):
        source = QPixmap(str(path))
        if not source.isNull():
            frames.append(source.scaledToHeight(
                height, Qt.TransformationMode.SmoothTransformation))
    return tuple(frames)


class PetGraphicsItem(QGraphicsObject):
    """A mostly-still pet with brief, randomized normal-state expressions."""
    def __init__(self, accent="#5fae76", background="#f5f2ed", parent=None):
        super().__init__(parent)
        self.frames = normal_frames()
        self.jump_frames = jump_frames()
        self.mirrored_jump_frames = jump_frames(mirrored=True)
        self.resting_frames = resting_frames()
        self.sleep_z_frames = sleep_z_frames()
        self.working_frames = working_frames()
        self.frame_index = IDLE_FRAME_INDEX
        self.burst_frames = []
        self.active_event = None
        self.next_event = None
        self.next_idle_delay_ms = None
        self.current_output = None
        self.latest_focused_output = None
        self.target_output = None
        self.pending_output = None
        self.output_anchors = {}
        self.dock_anchor = None
        self.is_docked = False
        self.is_jumping = False
        self.jump_mirrored = False
        self.jump_frame_index = 0
        self.jump_start = QPointF()
        self.jump_end = QPointF()
        self.jump_source_docked = False
        self.sleep_state = "awake"
        self.sleep_frame_index = 0
        self.sleep_z_index = 0
        self.focus_active = False
        self.attention_cue = None
        self.focus_seconds_remaining = FOCUS_DURATION_MS // 1000
        self.working_frame_index = 0
        self.hud_accent = QColor(accent)
        self.hud_background = QColor(background)
        self.hud_text = QColor(accent).lighter(145)
        self.ui_scale = 1.0
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(20)

        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(self.start_idle_burst)
        self.burst_timer = QTimer(self)
        self.burst_timer.setInterval(EVENT_FRAME_INTERVAL_MS)
        self.burst_timer.timeout.connect(self.advance_burst)
        self.jump_clock = QElapsedTimer()
        self.jump_timer = QTimer(self)
        self.jump_timer.setInterval(JUMP_TIMER_INTERVAL_MS)
        self.jump_timer.timeout.connect(self.advance_jump)
        self.sleep_delay_timer = QTimer(self)
        self.sleep_delay_timer.setSingleShot(True)
        self.sleep_delay_timer.setInterval(SLEEP_DELAY_MS)
        self.sleep_delay_timer.timeout.connect(self.start_falling_asleep)
        self.sleep_animation_timer = QTimer(self)
        self.sleep_animation_timer.timeout.connect(self.advance_sleep_animation)
        self.working_timer = QTimer(self)
        self.working_timer.setInterval(WORKING_FRAME_INTERVAL_MS)
        self.working_timer.timeout.connect(self.advance_working_frame)
        self.focus_clock = QElapsedTimer()
        self.focus_timer = QTimer(self)
        self.focus_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.focus_timer.setInterval(FOCUS_TIMER_INTERVAL_MS)
        self.focus_timer.timeout.connect(self.update_focus_countdown)
        if len(self.frames) > 1:
            self.schedule_next_idle()
        if self.resting_frames:
            self.sleep_delay_timer.start()

    def motionRect(self):
        """Pet travel bounds, excluding the focus HUD above her."""
        if not self.frames:
            return QRectF()
        left = min(PET_CANVAS_X_OFFSET, JUMP_CANVAS_X_OFFSET)
        right = PET_CANVAS_X_OFFSET + self.frames[0].width()
        if self.jump_frames:
            right = max(right, JUMP_CANVAS_X_OFFSET + self.jump_frames[0].width())
        if self.resting_frames:
            left = min(left, RESTING_CANVAS_X_OFFSET)
            right = max(right, RESTING_CANVAS_X_OFFSET +
                        self.resting_frames[0].width())
        if self.working_frames:
            left = min(left, WORKING_CANVAS_X_OFFSET)
            right = max(right, WORKING_CANVAS_X_OFFSET +
                        self.working_frames[0].width())
        return QRectF(left, 0, right - left, self.frames[0].height())

    def set_ui_scale(self, scale):
        """Scale pet artwork and its attached HUD with dashboard UI density."""
        scale = max(0.1, float(scale))
        if scale != self.ui_scale:
            self.ui_scale = scale
            self.setScale(scale)

    def scaled_motion_rect(self):
        rect = self.motionRect()
        return QRectF(rect.x() * self.ui_scale, rect.y() * self.ui_scale,
                      rect.width() * self.ui_scale,
                      rect.height() * self.ui_scale)

    def focusHudRect(self):
        body = self.motionRect()
        return QRectF(body.center().x() - FOCUS_HUD_WIDTH / 2,
                      -FOCUS_HUD_HEIGHT - 5,
                      FOCUS_HUD_WIDTH, FOCUS_HUD_HEIGHT)

    def attentionBubbleRect(self):
        return QRectF(self.motionRect().left() + 8,
                      -ATTENTION_BUBBLE_HEIGHT - 8,
                      ATTENTION_BUBBLE_WIDTH, ATTENTION_BUBBLE_HEIGHT)

    @property
    def attention_active(self):
        return self.attention_cue is not None

    def boundingRect(self):
        return (self.motionRect().united(self.focusHudRect())
                .united(self.attentionBubbleRect()))

    def shape(self):
        """Keep the timer display visual-only; clicks must land on the pet."""
        path = QPainterPath()
        path.addRect(self.motionRect())
        return path

    def paint(self, painter, option, widget=None):
        if not self.frames:
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.is_jumping and self.jump_frames:
            frames = (self.mirrored_jump_frames
                      if self.jump_mirrored else self.jump_frames)
            painter.drawPixmap(JUMP_CANVAS_X_OFFSET, 0,
                               frames[self.jump_frame_index])
        elif self.focus_active and not self.attention_active and self.working_frames:
            painter.drawPixmap(WORKING_CANVAS_X_OFFSET, 0,
                               self.working_frames[self.working_frame_index])
        elif self.sleep_state == "falling" and self.resting_frames:
            painter.drawPixmap(RESTING_CANVAS_X_OFFSET, 0,
                               self.resting_frames[self.sleep_frame_index])
        elif self.sleep_state == "sleeping" and self.resting_frames:
            painter.drawPixmap(RESTING_CANVAS_X_OFFSET, 0,
                               self.resting_frames[SLEEP_BODY_FRAME])
            if self.sleep_z_frames:
                painter.drawPixmap(RESTING_CANVAS_X_OFFSET, 0,
                                   self.sleep_z_frames[self.sleep_z_index])
        else:
            painter.drawPixmap(PET_CANVAS_X_OFFSET, 0,
                               self.frames[self.frame_index])
        if self.attention_active:
            self.paint_attention_bubble(painter)
        elif self.focus_active:
            self.paint_focus_hud(painter)

    def paint_attention_bubble(self, painter):
        rect = self.attentionBubbleRect()
        accent = QColor(self.hud_accent)
        background = QColor(self.hud_background)
        background.setAlpha(238)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(accent, 1))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 9, 9)
        tail_x = rect.left() + 23
        tail = QPainterPath()
        tail.moveTo(tail_x, rect.bottom())
        tail.lineTo(tail_x + 7, rect.bottom() + 6)
        tail.lineTo(tail_x + 13, rect.bottom())
        painter.drawPath(tail)
        number = str(self.attention_cue.number)
        painter.setFont(QFont("monospace", 9, QFont.Weight.DemiBold))
        badge_width = max(26, painter.fontMetrics().horizontalAdvance(number) + 10)
        badge = QRectF(rect.left() + 7, rect.top() + 5,
                       badge_width, rect.height() - 10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(badge, 5, 5)
        painter.setPen(self.hud_background)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, number)
        label_rect = rect.adjusted(13 + badge_width, 2, -7, -2)
        painter.setFont(QFont("Sans Serif", 9, QFont.Weight.DemiBold))
        label = painter.fontMetrics().elidedText(
            self.attention_cue.label, Qt.TextElideMode.ElideRight,
            int(label_rect.width()))
        painter.setPen(self.hud_text)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter |
                         Qt.AlignmentFlag.AlignLeft, label)

    def paint_focus_hud(self, painter):
        rect = self.focusHudRect()
        accent = QColor(self.hud_accent)
        background = QColor(self.hud_background)
        background.setAlpha(218)
        glow = QColor(accent)
        glow.setAlpha(42)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 6, 6)
        painter.setPen(QPen(accent, 1))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 5, 5)
        painter.setFont(QFont("monospace", 9, QFont.Weight.DemiBold))
        text_color = QColor(accent).lighter(145)
        painter.setPen(text_color)
        minutes, seconds = divmod(self.focus_seconds_remaining, 60)
        painter.drawText(rect.adjusted(0, -2, 0, -1),
                         Qt.AlignmentFlag.AlignCenter,
                         f"{minutes:02d}:{seconds:02d}")
        progress = self.focus_seconds_remaining / (FOCUS_DURATION_MS / 1000)
        track = QRectF(rect.left() + 5, rect.bottom() - 4,
                       rect.width() - 10, 2)
        track_color = QColor(accent)
        track_color.setAlpha(50)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, 1, 1)
        painter.setBrush(accent)
        painter.drawRoundedRect(QRectF(track.left(), track.top(),
                                      track.width() * progress, track.height()),
                                1, 1)

    def set_hud_colors(self, accent, background, text=None):
        accent = QColor(accent)
        background = QColor(background)
        text = QColor(text) if text is not None else accent.lighter(145)
        if (accent != self.hud_accent or background != self.hud_background or
                text != self.hud_text):
            self.hud_accent = accent
            self.hud_background = background
            self.hud_text = text
            if self.focus_active or self.attention_active:
                self.update()

    def set_attention(self, cue):
        if cue == self.attention_cue:
            return
        was_active = self.attention_active
        self.attention_cue = cue
        if cue is not None and was_active:
            self.update()
            return
        if cue is not None:
            if self.is_jumping:
                self.jump_timer.stop()
                self.is_jumping = False
                self.target_output = None
                self.pending_output = None
                self.jump_frame_index = 0
                if self.jump_source_docked and self.dock_anchor is not None:
                    self.is_docked = True
                    self.setPos(self.dock_anchor)
                elif self.current_output in self.output_anchors:
                    self.is_docked = False
                    self.setPos(self.output_anchors[self.current_output])
            self.wake_up()
            self.sleep_delay_timer.stop()
            self.working_timer.stop()
            if not self.idle_timer.isActive() and not self.burst_timer.isActive():
                self.schedule_next_idle()
        elif was_active:
            self.idle_timer.stop()
            self.burst_timer.stop()
            self.active_event = None
            self.burst_frames = []
            self.set_frame(IDLE_FRAME_INDEX)
            if self.focus_active:
                if len(self.working_frames) > 1:
                    self.working_timer.start()
            else:
                if self.resting_frames:
                    self.sleep_delay_timer.start(SLEEP_DELAY_MS)
                self.schedule_next_idle()
            QTimer.singleShot(0, self._resume_after_attention)
        self.update()

    def _resume_after_attention(self):
        if (not self.attention_active and not self.is_docked and
                not self.is_jumping and
                self.latest_focused_output in self.output_anchors and
                self.latest_focused_output != self.current_output):
            self.start_jump(self.latest_focused_output)

    def set_frame(self, index):
        if self.frames and 0 <= index < len(self.frames) and index != self.frame_index:
            self.frame_index = index
            self.update()

    def schedule_next_idle(self):
        if (self.is_jumping or self.sleep_state != "awake" or
                (self.focus_active and not self.attention_active)):
            return
        self.next_event = "blink" if random.random() < BLINK_PROBABILITY else "tail"
        delay_range = ((BLINK_DELAY_MIN_MS, BLINK_DELAY_MAX_MS)
                       if self.next_event == "blink"
                       else (TAIL_DELAY_MIN_MS, TAIL_DELAY_MAX_MS))
        self.next_idle_delay_ms = random.randint(*delay_range)
        self.idle_timer.start(self.next_idle_delay_ms)

    def start_idle_burst(self):
        if (self.is_jumping or self.sleep_state != "awake" or
                (self.focus_active and not self.attention_active) or
                self.burst_timer.isActive() or not self.frames):
            return
        self.idle_timer.stop()
        event = self.next_event or "blink"
        sequence = IDLE_EVENTS[event]
        if max(sequence, default=0) >= len(self.frames):
            self.schedule_next_idle()
            return
        self.active_event = event
        self.next_event = None
        self.burst_frames = list(sequence[1:])
        self.set_frame(sequence[0])
        self.burst_timer.start()

    def advance_burst(self):
        if self.burst_frames:
            self.set_frame(self.burst_frames.pop(0))
        if not self.burst_frames:
            self.burst_timer.stop()
            self.set_frame(IDLE_FRAME_INDEX)
            self.active_event = None
            self.schedule_next_idle()

    def set_output_anchors(self, anchors, focused_output=None):
        """Update graph-relative output anchors and react only to real focus."""
        self.output_anchors = {name: QPointF(point) for name, point in anchors.items()}
        if focused_output in self.output_anchors:
            output_changed = (self.latest_focused_output is not None and
                              focused_output != self.latest_focused_output)
            self.latest_focused_output = focused_output
            if output_changed and not self.attention_active:
                self.wake_up()
        if not self.output_anchors:
            return
        if self.current_output is None:
            initial = (focused_output if focused_output in self.output_anchors
                       else next(iter(self.output_anchors)))
            self.current_output = initial
            self.latest_focused_output = initial
            self.setPos(self.output_anchors[initial])
            return
        if self.attention_active:
            if not self.is_docked and self.current_output in self.output_anchors:
                self.setPos(self.output_anchors[self.current_output])
            return
        if self.is_docked:
            return
        if self.is_jumping:
            if self.target_output == DOCK_TARGET:
                return
            if self.target_output in self.output_anchors:
                self.jump_end = QPointF(self.output_anchors[self.target_output])
            if focused_output in self.output_anchors:
                self.pending_output = focused_output
            return
        if focused_output in self.output_anchors and focused_output != self.current_output:
            self.start_jump(focused_output)
            return
        if self.current_output in self.output_anchors:
            self.setPos(self.output_anchors[self.current_output])
        elif focused_output in self.output_anchors:
            self.current_output = focused_output
            self.setPos(self.output_anchors[focused_output])

    def start_jump(self, output):
        if self.attention_active or output not in self.output_anchors:
            return
        if self.is_jumping:
            self.pending_output = output
            return
        if output == self.current_output:
            return
        ordered_outputs = sorted(
            self.output_anchors,
            key=lambda name: self.output_anchors[name].x())
        if self.current_output not in self.output_anchors:
            self.current_output = output
            self.setPos(self.output_anchors[output])
            return
        current_index = ordered_outputs.index(self.current_output)
        destination_index = ordered_outputs.index(output)
        direction = 1 if destination_index > current_index else -1
        next_output = ordered_outputs[current_index + direction]
        self.begin_jump(next_output, self.output_anchors[next_output], output,
                        self.current_output)

    def set_dock_anchor(self, anchor):
        self.dock_anchor = QPointF(anchor)
        if self.is_docked:
            self.setPos(self.dock_anchor)
        elif self.is_jumping and self.target_output == DOCK_TARGET:
            self.jump_end = QPointF(self.dock_anchor)

    def toggle_dock(self):
        if self.attention_active or self.is_jumping or self.dock_anchor is None:
            return
        self.wake_up()
        if self.is_docked:
            output = self.latest_focused_output
            if output not in self.output_anchors:
                output = (self.current_output if self.current_output in self.output_anchors
                          else next(iter(self.output_anchors), None))
            if output is None:
                return
            self.is_docked = False
            self.begin_jump(output, self.output_anchors[output], output, "dock")
        else:
            self.begin_jump(DOCK_TARGET, self.dock_anchor, None,
                            self.current_output)

    def begin_jump(self, target, endpoint, pending, source_label):
        self.jump_source_docked = source_label == "dock"
        self.idle_timer.stop()
        self.burst_timer.stop()
        self.active_event = None
        self.burst_frames = []
        self.set_frame(IDLE_FRAME_INDEX)
        self.target_output = target
        self.pending_output = pending
        self.jump_start = QPointF(self.pos())
        self.jump_end = QPointF(endpoint)
        self.jump_mirrored = self.jump_end.x() < self.jump_start.x()
        self.jump_frame_index = 0
        self.is_jumping = True
        self.jump_clock.start()
        self.jump_timer.start()
        self.update()
        target_label = "dock" if target == DOCK_TARGET else target
        print(f"Pet jump: {source_label} -> {target_label}", file=sys.stderr)

    def advance_jump(self, progress=None):
        if not self.is_jumping:
            return
        if progress is None:
            progress = self.jump_clock.elapsed() / JUMP_DURATION_MS
        progress = max(0.0, min(1.0, float(progress)))
        frame_count = len(self.jump_frames)
        if frame_count:
            self.jump_frame_index = min(frame_count - 1,
                                        int(progress * frame_count))
        x = self.jump_start.x() + (self.jump_end.x() - self.jump_start.x()) * progress
        linear_y = (self.jump_start.y() +
                    (self.jump_end.y() - self.jump_start.y()) * progress)
        arc_scale = 1.0
        if (self.flags() & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations and
                self.scene() and self.scene().views()):
            arc_scale = max(0.01, self.scene().views()[0].transform().m11())
        y = (linear_y - 4 * JUMP_ARC_HEIGHT * self.ui_scale / arc_scale *
             progress * (1 - progress))
        self.setPos(x, y)
        self.update()
        if progress >= 1.0:
            self.finish_jump()

    def finish_jump(self):
        self.jump_timer.stop()
        landed_output = self.target_output
        if landed_output == DOCK_TARGET and self.dock_anchor is not None:
            self.setPos(self.dock_anchor)
        elif landed_output in self.output_anchors:
            self.setPos(self.output_anchors[landed_output])
        else:
            self.setPos(self.jump_end)
        if landed_output == DOCK_TARGET:
            self.is_docked = True
        else:
            self.current_output = landed_output
        latest_output = self.pending_output
        self.target_output = None
        self.pending_output = None
        self.is_jumping = False
        self.jump_frame_index = 0
        self.jump_mirrored = False
        self.set_frame(IDLE_FRAME_INDEX)
        self.update()
        if landed_output == DOCK_TARGET:
            if len(self.frames) > 1 and not self.focus_active:
                self.schedule_next_idle()
        elif (latest_output in self.output_anchors and
                latest_output != self.current_output):
            self.start_jump(latest_output)
        elif len(self.frames) > 1 and not self.focus_active:
            self.schedule_next_idle()

    def start_falling_asleep(self):
        if self.focus_active or self.attention_active:
            self.sleep_delay_timer.stop()
            return
        if self.is_jumping or not self.resting_frames:
            self.sleep_delay_timer.start()
            return
        self.idle_timer.stop()
        self.burst_timer.stop()
        self.active_event = None
        self.burst_frames = []
        self.set_frame(IDLE_FRAME_INDEX)
        self.sleep_state = "falling"
        self.sleep_frame_index = 0
        self.sleep_z_index = 0
        self.sleep_animation_timer.setInterval(SLEEP_TRANSITION_INTERVAL_MS)
        self.sleep_animation_timer.start()
        self.update()

    def advance_sleep_animation(self):
        if self.sleep_state == "falling":
            if self.sleep_frame_index < SLEEP_BODY_FRAME:
                self.sleep_frame_index += 1
            else:
                self.sleep_state = "sleeping"
                self.sleep_z_index = 0
                self.sleep_animation_timer.setInterval(SLEEP_Z_INTERVAL_MS)
        elif self.sleep_state == "sleeping":
            if self.sleep_z_frames:
                self.sleep_z_index = ((self.sleep_z_index + 1) %
                                      len(self.sleep_z_frames))
        self.update()

    def wake_up(self):
        was_sleeping = self.sleep_state != "awake"
        self.sleep_animation_timer.stop()
        self.sleep_state = "awake"
        self.sleep_frame_index = 0
        self.sleep_z_index = 0
        self.set_frame(IDLE_FRAME_INDEX)
        if self.resting_frames and not self.focus_active and not self.attention_active:
            self.sleep_delay_timer.start(SLEEP_DELAY_MS)
        if was_sleeping and not self.is_jumping and not self.focus_active:
            self.schedule_next_idle()
        self.update()

    def toggle_focus_session(self):
        if self.attention_active:
            return
        if self.focus_active:
            self.stop_focus_session()
        else:
            self.start_focus_session()

    def start_focus_session(self):
        self.idle_timer.stop()
        self.burst_timer.stop()
        self.sleep_delay_timer.stop()
        self.sleep_animation_timer.stop()
        self.active_event = None
        self.burst_frames = []
        self.sleep_state = "awake"
        self.sleep_frame_index = 0
        self.sleep_z_index = 0
        self.set_frame(IDLE_FRAME_INDEX)
        self.focus_active = True
        self.focus_seconds_remaining = FOCUS_DURATION_MS // 1000
        self.working_frame_index = 0
        self.focus_clock.start()
        self.focus_timer.start()
        if len(self.working_frames) > 1:
            self.working_timer.start()
        self.update()

    def stop_focus_session(self):
        if not self.focus_active:
            return
        self.focus_timer.stop()
        self.working_timer.stop()
        self.focus_active = False
        self.focus_seconds_remaining = FOCUS_DURATION_MS // 1000
        self.working_frame_index = 0
        self.set_frame(IDLE_FRAME_INDEX)
        if self.resting_frames and not self.attention_active:
            self.sleep_delay_timer.start(SLEEP_DELAY_MS)
        if not self.is_jumping and len(self.frames) > 1:
            self.schedule_next_idle()
        self.update()

    def update_focus_countdown(self, elapsed_ms=None):
        if not self.focus_active:
            return
        elapsed = self.focus_clock.elapsed() if elapsed_ms is None else int(elapsed_ms)
        remaining_ms = max(0, FOCUS_DURATION_MS - elapsed)
        remaining_seconds = (remaining_ms + 999) // 1000
        if remaining_seconds != self.focus_seconds_remaining:
            self.focus_seconds_remaining = remaining_seconds
            self.update()
        if remaining_ms <= 0:
            self.stop_focus_session()

    def advance_working_frame(self):
        if not self.focus_active or not self.working_frames:
            self.working_timer.stop()
            return
        self.working_frame_index = ((self.working_frame_index + 1) %
                                    len(self.working_frames))
        if not self.is_jumping:
            self.update()
