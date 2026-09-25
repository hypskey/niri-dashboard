import os
import unittest
from copy import deepcopy
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsItem

from niridashboard.backend import demo_state
from niridashboard.main import Dashboard
from niridashboard.overlay import OverlayWindow
from niridashboard.controller import DashboardController
from niridashboard.pet import (
    BLINK_DELAY_MAX_MS, BLINK_DELAY_MIN_MS, BLINK_PROBABILITY,
    DOCK_TARGET, EVENT_FRAME_INTERVAL_MS, FRAME_X_ALIGNMENT, IDLE_EVENTS,
    FOCUS_DURATION_MS, FOCUS_TIMER_INTERVAL_MS,
    IDLE_FRAME_INDEX, JUMP_ARC_HEIGHT, JUMP_DURATION_MS, JUMP_FRAMES,
    JUMP_TIMER_INTERVAL_MS, NORMAL_FRAMES, PET_HEIGHT, TAIL_DELAY_MAX_MS,
    TAIL_DELAY_MIN_MS, RESTING_FRAMES, SLEEP_DELAY_MS,
    SLEEP_BODY_FRAME, SLEEP_TRANSITION_INTERVAL_MS, SLEEP_Z_FRAMES,
    SLEEP_Z_INTERVAL_MS, WORKING_FRAME_INTERVAL_MS, WORKING_FRAMES,
    PetGraphicsItem, jump_frames, normal_frames, resting_frames,
    sleep_z_frames, working_frames,
)


class PetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_extracted_frames_share_rgba_canvas_and_baseline(self):
        paths = sorted(NORMAL_FRAMES.glob("*.png"))
        self.assertEqual(NORMAL_FRAMES.name, "normal-2")
        self.assertEqual(len(paths), 6)
        baselines = set()
        for path in paths:
            image = QImage(str(path))
            self.assertEqual(image.size(), QSize(512, 512))
            self.assertTrue(image.hasAlphaChannel())
            self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
            visible_rows = [y for y in range(image.height())
                            if any(image.pixelColor(x, y).alpha() >= 8 for x in range(image.width()))]
            baselines.add(max(visible_rows))
        self.assertEqual(baselines, {503})

    def test_animation_uses_cached_frames_and_stays_idle_until_burst(self):
        normal_frames.cache_clear()
        with (patch("niridashboard.pet.random.random", return_value=0),
              patch("niridashboard.pet.random.randint", return_value=BLINK_DELAY_MIN_MS)):
            first = PetGraphicsItem()
            second = PetGraphicsItem()
        self.assertIs(first.frames, second.frames)
        self.assertEqual(len(first.frames), 6)
        self.assertEqual(first.frame_index, IDLE_FRAME_INDEX)
        self.assertEqual(first.burst_timer.interval(), EVENT_FRAME_INTERVAL_MS)
        self.assertEqual(first.next_event, "blink")
        self.assertTrue(first.idle_timer.isSingleShot())
        self.assertTrue(first.idle_timer.isActive())
        QTest.qWait(EVENT_FRAME_INTERVAL_MS + 20)
        self.assertEqual(first.frame_index, IDLE_FRAME_INDEX)
        first.idle_timer.stop()
        second.idle_timer.stop()

    def test_rendered_frames_are_aligned_on_one_fixed_canvas(self):
        normal_frames.cache_clear()
        frames = normal_frames()
        self.assertEqual(FRAME_X_ALIGNMENT, (0, 35, 40, 0, 35, 40))
        self.assertEqual(len({frame.size() for frame in frames}), 1)
        self.assertGreater(frames[0].width(), frames[0].height())
        blink_bounds = []
        for frame in frames[:3]:
            image = frame.toImage()
            visible = [(x, y) for y in range(image.height())
                       for x in range(image.width())
                       if image.pixelColor(x, y).alpha() >= 8]
            blink_bounds.append((min(x for x, _ in visible),
                                 min(y for _, y in visible),
                                 max(x for x, _ in visible),
                                 max(y for _, y in visible)))
        for coordinates in zip(*blink_bounds):
            self.assertLessEqual(max(coordinates) - min(coordinates), 1)

    def test_random_burst_returns_to_idle_before_rescheduling(self):
        sequence = IDLE_EVENTS["blink"]
        with (patch("niridashboard.pet.random.random", side_effect=[0.1, 0.9]),
              patch("niridashboard.pet.random.randint", side_effect=[5000, 9000]) as delay):
            pet = PetGraphicsItem()
            self.assertEqual(pet.next_idle_delay_ms, 5000)
            self.assertEqual(pet.next_event, "blink")
            pet.start_idle_burst()
            self.assertTrue(pet.burst_timer.isActive())
            self.assertEqual(pet.active_event, "blink")
            self.assertEqual(pet.frame_index, sequence[0])
            pending = list(pet.burst_frames)
            pet.start_idle_burst()
            self.assertEqual(pet.burst_frames, pending)
            while pet.burst_timer.isActive():
                pet.advance_burst()
            self.assertEqual(pet.frame_index, IDLE_FRAME_INDEX)
            self.assertEqual(pet.next_idle_delay_ms, 9000)
            self.assertEqual(pet.next_event, "tail")
            self.assertIsNone(pet.active_event)
            self.assertTrue(pet.idle_timer.isActive())
            self.assertEqual(delay.call_count, 2)
            pet.idle_timer.stop()

    def test_idle_timing_constants_match_restrained_target(self):
        self.assertEqual((BLINK_DELAY_MIN_MS, BLINK_DELAY_MAX_MS), (2000, 5000))
        self.assertEqual((TAIL_DELAY_MIN_MS, TAIL_DELAY_MAX_MS), (3500, 8000))
        self.assertGreater(BLINK_PROBABILITY, .5)
        self.assertEqual(EVENT_FRAME_INTERVAL_MS, 90)
        self.assertEqual(IDLE_EVENTS["blink"], (1, 2, 1, 0))
        self.assertEqual(IDLE_EVENTS["tail"], (3, 4, 5, 3, 0))
        durations = {name: (len(sequence) - 1) * EVENT_FRAME_INTERVAL_MS
                     for name, sequence in IDLE_EVENTS.items()}
        self.assertEqual(durations, {"blink": 270, "tail": 360})
        self.assertTrue(all(sequence[-1] == IDLE_FRAME_INDEX
                            for sequence in IDLE_EVENTS.values()))

    def test_jump_frames_are_fixed_canvas_rgba_assets(self):
        paths = sorted(JUMP_FRAMES.glob("*.png"))
        self.assertEqual(len(paths), 11)
        for path in paths:
            image = QImage(str(path))
            self.assertEqual(image.size(), QSize(320, 270))
            self.assertTrue(image.hasAlphaChannel())
            self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        jump_frames.cache_clear()
        normal = jump_frames()
        mirrored = jump_frames(mirrored=True)
        self.assertEqual(len(normal), 11)
        self.assertEqual(len(mirrored), 11)
        self.assertEqual(len({frame.size() for frame in normal + mirrored}), 1)

    def test_resting_frames_are_fixed_canvas_rgba_assets(self):
        paths = sorted(RESTING_FRAMES.glob("*.png"))
        self.assertEqual(len(paths), 9)
        for path in paths:
            image = QImage(str(path))
            self.assertEqual(image.size(), QSize(300, 310))
            self.assertTrue(image.hasAlphaChannel())
            self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        resting_frames.cache_clear()
        frames = resting_frames()
        self.assertEqual(len(frames), 9)
        self.assertEqual(len({frame.size() for frame in frames}), 1)

        z_paths = sorted(SLEEP_Z_FRAMES.glob("*.png"))
        self.assertEqual(len(z_paths), 4)
        for path in z_paths:
            image = QImage(str(path))
            self.assertEqual(image.size(), QSize(300, 310))
            self.assertTrue(image.hasAlphaChannel())
            self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
            visible_rows = [
                y for y in range(image.height())
                if any(image.pixelColor(x, y).alpha()
                       for x in range(image.width()))
            ]
            # These assets contain only the floating sleep letters. Keeping
            # every visible pixel above the pet prevents an accidental body
            # fragment from moving as the overlay cycles.
            self.assertTrue(visible_rows)
            self.assertLess(max(visible_rows), 160)
        sleep_z_frames.cache_clear()
        overlays = sleep_z_frames()
        self.assertEqual(len(overlays), 4)
        self.assertEqual(len({frame.size() for frame in overlays}), 1)

    def test_working_frames_are_aligned_fixed_canvas_rgba_assets(self):
        paths = sorted(WORKING_FRAMES.glob("*.png"))
        self.assertEqual(len(paths), 8)
        baselines = set()
        for path in paths:
            image = QImage(str(path))
            self.assertEqual(image.size(), QSize(300, 310))
            self.assertTrue(image.hasAlphaChannel())
            self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
            visible_rows = [
                y for y in range(image.height())
                if any(image.pixelColor(x, y).alpha()
                       for x in range(image.width()))
            ]
            baselines.add(max(visible_rows))
        self.assertEqual(baselines, {302})
        working_frames.cache_clear()
        frames = working_frames()
        self.assertEqual(len(frames), 8)
        self.assertEqual(len({frame.size() for frame in frames}), 1)

    def test_focus_session_uses_deadline_blocks_sleep_and_restores_idle(self):
        pet = PetGraphicsItem()
        self.assertEqual(FOCUS_DURATION_MS, 30 * 60 * 1000)
        self.assertEqual(pet.focus_timer.interval(), FOCUS_TIMER_INTERVAL_MS)
        self.assertEqual(pet.working_timer.interval(), WORKING_FRAME_INTERVAL_MS)

        pet.start_falling_asleep()
        self.assertEqual(pet.sleep_state, "falling")
        pet.toggle_focus_session()
        self.assertTrue(pet.focus_active)
        self.assertEqual(pet.sleep_state, "awake")
        self.assertFalse(pet.sleep_delay_timer.isActive())
        self.assertFalse(pet.sleep_animation_timer.isActive())
        self.assertFalse(pet.idle_timer.isActive())
        self.assertTrue(pet.focus_timer.isActive())
        self.assertTrue(pet.working_timer.isActive())
        self.assertEqual(pet.focus_seconds_remaining, 30 * 60)

        pet.start_falling_asleep()
        self.assertEqual(pet.sleep_state, "awake")
        self.assertFalse(pet.sleep_delay_timer.isActive())
        pet.update_focus_countdown(1000)
        self.assertEqual(pet.focus_seconds_remaining, 29 * 60 + 59)
        pet.update_focus_countdown(FOCUS_DURATION_MS - 1)
        self.assertEqual(pet.focus_seconds_remaining, 1)
        pet.update_focus_countdown(FOCUS_DURATION_MS)
        self.assertFalse(pet.focus_active)
        self.assertFalse(pet.focus_timer.isActive())
        self.assertFalse(pet.working_timer.isActive())
        self.assertTrue(pet.sleep_delay_timer.isActive())
        self.assertTrue(pet.idle_timer.isActive())
        pet.sleep_delay_timer.stop()
        pet.idle_timer.stop()

    def test_control_click_toggles_focus_without_moving_pet(self):
        dashboard = Dashboard(demo=True, start_backend=False)
        dashboard.resize(1440, 900)
        dashboard.show()
        dashboard.receive_state(demo_state())
        self.app.processEvents()
        view = dashboard.view
        pet = view.pet_item
        start = QPointF(pet.pos())
        click = view.mapFromScene(
            pet.mapToScene(pet.motionRect().center()))

        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier, click)
        self.assertTrue(pet.focus_active)
        self.assertFalse(pet.is_jumping)
        self.assertEqual(pet.pos(), start)
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier, click)
        self.assertFalse(pet.focus_active)
        self.assertFalse(pet.is_jumping)
        self.assertEqual(pet.pos(), start)
        pet.sleep_delay_timer.stop()
        pet.idle_timer.stop()
        dashboard.close()

    def test_sleep_transition_keeps_body_still_and_loops_only_z_overlay(self):
        anchor_y = 4 - PET_HEIGHT
        anchors = {
            "DP-4": QPointF(36, anchor_y),
            "DP-3": QPointF(466, anchor_y),
        }
        pet = PetGraphicsItem()
        pet.set_output_anchors(anchors, "DP-4")
        self.assertEqual(SLEEP_DELAY_MS, 65000)
        self.assertTrue(pet.sleep_delay_timer.isSingleShot())
        self.assertEqual(pet.sleep_delay_timer.interval(), SLEEP_DELAY_MS)
        self.assertTrue(pet.sleep_delay_timer.isActive())

        pet.start_falling_asleep()
        self.assertEqual(pet.sleep_state, "falling")
        self.assertEqual(pet.sleep_frame_index, 0)
        self.assertEqual(pet.sleep_animation_timer.interval(),
                         SLEEP_TRANSITION_INTERVAL_MS)
        self.assertFalse(pet.idle_timer.isActive())
        for expected in range(1, SLEEP_BODY_FRAME + 1):
            pet.advance_sleep_animation()
            self.assertEqual(pet.sleep_frame_index, expected)
        pet.advance_sleep_animation()
        self.assertEqual(pet.sleep_state, "sleeping")
        self.assertEqual(pet.sleep_frame_index, SLEEP_BODY_FRAME)
        self.assertEqual(pet.sleep_z_index, 0)
        self.assertEqual(pet.sleep_animation_timer.interval(),
                         SLEEP_Z_INTERVAL_MS)
        z_cycle = []
        for _ in range(4):
            pet.advance_sleep_animation()
            z_cycle.append(pet.sleep_z_index)
            self.assertEqual(pet.sleep_frame_index, SLEEP_BODY_FRAME)
        self.assertEqual(z_cycle, [1, 2, 3, 0])
        self.assertTrue(pet.sleep_animation_timer.isActive())

        pet.set_output_anchors(anchors, "DP-4")
        self.assertEqual(pet.sleep_state, "sleeping")
        pet.set_output_anchors(anchors, "DP-3")
        self.assertEqual(pet.sleep_state, "awake")
        self.assertEqual(pet.frame_index, IDLE_FRAME_INDEX)
        self.assertFalse(pet.sleep_animation_timer.isActive())
        self.assertTrue(pet.sleep_delay_timer.isActive())
        self.assertTrue(pet.is_jumping)
        pet.jump_timer.stop()
        pet.sleep_delay_timer.stop()
        pet.idle_timer.stop()

    def test_jump_pauses_idle_follows_arc_and_resumes_at_exact_anchor(self):
        self.assertEqual(PET_HEIGHT, 72)
        self.assertAlmostEqual(JUMP_ARC_HEIGHT, 38.4)
        self.assertEqual(JUMP_DURATION_MS, 650)
        self.assertEqual(JUMP_TIMER_INTERVAL_MS, 16)
        anchor_y = 4 - PET_HEIGHT
        anchors = {
            "DP-4": QPointF(36, anchor_y),
            "DP-3": QPointF(466, anchor_y),
            "HDMI-A-5": QPointF(896, anchor_y),
        }
        pet = PetGraphicsItem()
        pet.set_output_anchors(anchors, "DP-4")
        self.assertEqual(pet.current_output, "DP-4")
        pet.set_output_anchors(anchors, "DP-3")
        self.assertTrue(pet.is_jumping)
        self.assertEqual(pet.target_output, "DP-3")
        self.assertFalse(pet.jump_mirrored)
        self.assertFalse(pet.idle_timer.isActive())
        pet.advance_jump(.5)
        self.assertAlmostEqual(pet.pos().x(), 251)
        self.assertAlmostEqual(pet.pos().y(), anchor_y - JUMP_ARC_HEIGHT)
        pet.advance_jump(1)
        self.assertFalse(pet.is_jumping)
        self.assertEqual(pet.current_output, "DP-3")
        self.assertEqual(pet.pos(), anchors["DP-3"])
        self.assertEqual(pet.frame_index, IDLE_FRAME_INDEX)
        self.assertTrue(pet.idle_timer.isActive())
        pet.set_output_anchors(anchors, "DP-3")
        self.assertFalse(pet.is_jumping)
        pet.idle_timer.stop()

    def test_rapid_focus_keeps_only_latest_target_and_mirrors_leftward(self):
        anchor_y = 4 - PET_HEIGHT
        anchors = {
            "DP-4": QPointF(36, anchor_y),
            "DP-3": QPointF(466, anchor_y),
            "HDMI-A-5": QPointF(896, anchor_y),
        }
        pet = PetGraphicsItem()
        pet.set_output_anchors(anchors, "DP-4")
        pet.set_output_anchors(anchors, "DP-3")
        pet.set_output_anchors(anchors, "HDMI-A-5")
        self.assertEqual(pet.pending_output, "HDMI-A-5")
        pet.advance_jump(1)
        self.assertEqual(pet.current_output, "DP-3")
        self.assertEqual(pet.target_output, "HDMI-A-5")
        pet.set_output_anchors(anchors, "DP-4")
        pet.advance_jump(1)
        self.assertEqual(pet.current_output, "HDMI-A-5")
        self.assertEqual(pet.target_output, "DP-3")
        self.assertTrue(pet.jump_mirrored)
        pet.advance_jump(1)
        self.assertEqual(pet.current_output, "DP-3")
        self.assertEqual(pet.target_output, "DP-4")
        self.assertTrue(pet.jump_mirrored)
        pet.advance_jump(1)
        self.assertEqual(pet.current_output, "DP-4")
        self.assertFalse(pet.is_jumping)
        pet.idle_timer.stop()

    def test_jump_visits_every_monitor_between_source_and_destination(self):
        anchor_y = 4 - PET_HEIGHT
        anchors = {
            "DP-4": QPointF(36, anchor_y),
            "DP-3": QPointF(466, anchor_y),
            "HDMI-A-5": QPointF(896, anchor_y),
        }
        pet = PetGraphicsItem()
        pet.set_output_anchors(anchors, "DP-4")
        pet.set_output_anchors(anchors, "HDMI-A-5")
        self.assertEqual(pet.target_output, "DP-3")
        self.assertEqual(pet.pending_output, "HDMI-A-5")
        pet.advance_jump(1)
        self.assertEqual(pet.current_output, "DP-3")
        self.assertEqual(pet.target_output, "HDMI-A-5")
        pet.advance_jump(1)
        self.assertEqual(pet.current_output, "HDMI-A-5")
        self.assertFalse(pet.is_jumping)

        pet.set_output_anchors(anchors, "DP-4")
        self.assertEqual(pet.target_output, "DP-3")
        self.assertTrue(pet.jump_mirrored)
        pet.advance_jump(1)
        self.assertEqual(pet.current_output, "DP-3")
        self.assertEqual(pet.target_output, "DP-4")
        self.assertTrue(pet.jump_mirrored)
        pet.advance_jump(1)
        self.assertEqual(pet.current_output, "DP-4")
        self.assertFalse(pet.is_jumping)
        pet.idle_timer.stop()

    def test_click_toggles_bottom_right_dock_and_focus_waits_while_idle(self):
        dashboard = Dashboard(demo=True, start_backend=False)
        dashboard.resize(1440, 900)
        dashboard.show()
        state = demo_state()
        dashboard.receive_state(state)
        self.app.processEvents()
        view = dashboard.view
        pet = view.pet_item
        transform = view.transform()
        scene_rect = view.sceneRect()
        self.assertIsNotNone(pet.dock_anchor)
        click = view.mapFromScene(pet.sceneBoundingRect().center())
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, click)
        self.assertTrue(pet.is_jumping)
        self.assertEqual(pet.target_output, DOCK_TARGET)
        self.assertGreater(pet.zValue(), max(node.zValue()
                                             for node in view.nodes.values()))
        pet.advance_jump(1)
        self.assertTrue(pet.is_docked)
        self.assertTrue(pet.idle_timer.isActive())
        self.assertEqual(pet.pos(), pet.dock_anchor)
        pet.start_falling_asleep()
        for _ in range(SLEEP_BODY_FRAME + 1):
            pet.advance_sleep_animation()
        self.assertEqual(pet.sleep_state, "sleeping")
        dock_bottom = view.mapFromScene(
            pet.pos() + pet.boundingRect().bottomRight())
        self.assertLessEqual(dock_bottom.y(), view.viewport().height() - 10)

        changed = deepcopy(state)
        target_workspace = next(
            workspace for workspace in changed["workspaces"]
            if workspace["output"] == "DP-2" and
            any(window["workspace_id"] == workspace["id"]
                for window in changed["windows"]))
        target = next(window for window in changed["windows"]
                      if window["workspace_id"] == target_workspace["id"])
        for window in changed["windows"]:
            window["is_focused"] = window["id"] == target["id"]
        dashboard.receive_state(changed)
        self.app.processEvents()
        self.assertTrue(pet.is_docked)
        self.assertFalse(pet.is_jumping)
        self.assertEqual(pet.latest_focused_output, "DP-2")
        self.assertEqual(pet.sleep_state, "awake")

        click = view.mapFromScene(pet.sceneBoundingRect().center())
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, click)
        self.assertTrue(pet.is_jumping)
        self.assertEqual(pet.target_output, "DP-2")
        pet.advance_jump(1)
        self.assertFalse(pet.is_docked)
        self.assertEqual(pet.current_output, "DP-2")
        self.assertEqual(view.transform(), transform)
        self.assertEqual(view.sceneRect(), scene_rect)
        pet.idle_timer.stop()
        dashboard.close()

    def test_graph_refresh_preserves_pet_and_uses_focused_window_output(self):
        dashboard = Dashboard(demo=True, start_backend=False)
        state = demo_state()
        dashboard.receive_state(state)
        pet = dashboard.view.pet_item
        transform = dashboard.view.transform()
        scene_rect = dashboard.view.sceneRect()
        horizontal_scroll = dashboard.view.horizontalScrollBar().value()
        vertical_scroll = dashboard.view.verticalScrollBar().value()
        self.assertEqual(pet.current_output, "DP-1")
        changed = deepcopy(state)
        target_workspace = next(
            workspace for workspace in changed["workspaces"]
            if workspace["output"] == "DP-2" and
            any(window["workspace_id"] == workspace["id"]
                for window in changed["windows"]))
        target = next(window for window in changed["windows"]
                      if window["workspace_id"] == target_workspace["id"])
        for window in changed["windows"]:
            window["is_focused"] = window["id"] == target["id"]
        dashboard.receive_state(changed)
        self.assertIs(dashboard.view.pet_item, pet)
        self.assertTrue(pet.is_jumping)
        self.assertEqual(pet.target_output, "DP-2")
        self.assertEqual(dashboard.view.transform(), transform)
        self.assertEqual(dashboard.view.sceneRect(), scene_rect)
        self.assertEqual(dashboard.view.horizontalScrollBar().value(),
                         horizontal_scroll)
        self.assertEqual(dashboard.view.verticalScrollBar().value(),
                         vertical_scroll)
        pet.advance_jump(.5)
        self.assertEqual(dashboard.view.transform(), transform)
        self.assertEqual(dashboard.view.sceneRect(), scene_rect)
        pet.advance_jump(1)
        self.assertEqual(dashboard.view.transform(), transform)
        self.assertEqual(dashboard.view.sceneRect(), scene_rect)
        pet.idle_timer.stop()
        dashboard.close()

    def test_pet_is_screen_overlay_in_dashboard_and_absent_from_overlay(self):
        dashboard = Dashboard(demo=True, start_backend=False)
        dashboard.receive_state(demo_state())
        self.assertIsNotNone(dashboard.view.pet_item)
        pet = dashboard.view.pet_item
        self.assertTrue(pet.flags() &
                        QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        anchor_before = dashboard.view.mapFromScene(pet.pos())
        dashboard.view.zoom(1.15)
        self.assertLessEqual((dashboard.view.mapFromScene(pet.pos()) - anchor_before).manhattanLength(), 2)

        controller = DashboardController(demo=True, start_backend=False)
        overlay = OverlayWindow(controller)
        overlay.view.render(demo_state())
        self.assertFalse(overlay.view.show_pet)
        self.assertIsNone(overlay.view.pet_item)
        dashboard.close()
        overlay.shutdown()
        overlay.deleteLater()


if __name__ == "__main__":
    unittest.main()
