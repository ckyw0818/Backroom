"""Cinematic teaser mode.

Press the backtick (`) key during gameplay to toggle a CCTV-style auto-tour of
the map. The camera starts up in a hallway ceiling corner (like a security
camera) and glides toward the hallway center over a few seconds, then cuts to
another hallway and repeats. Useful for recording teaser footage.

The mode hijacks the existing `camera` (which lives under the player's
camera_pivot) by reparenting it to a free-flying rig, and restores everything
when toggled off.
"""

import math
import random

from ursina import Entity, Vec3, camera, time

from map.map_data import CELL, LAYOUT, WALL_H


# How long each shot lasts before cutting to a new hallway (seconds).
SHOT_DURATION = 7.0
# How high under the ceiling the "camera" sits at the start of a shot.
CEILING_DROP = 0.35
# Eye height the shot drifts toward (matches roughly head height).
CENTER_EYE_HEIGHT = WALL_H * 0.55
# How far past the hallway center the camera keeps drifting (world units).
DRIFT_OVERSHOOT = CELL * 0.55
# How far down the corridor the camera looks. Larger = flatter (less tilt),
# because the look target sits farther away and nearer to eye height.
LOOK_AHEAD_CELLS = 4.5


def _open(r, c):
    return (
        0 <= r < len(LAYOUT)
        and 0 <= c < len(LAYOUT[0])
        and LAYOUT[r][c] == 0
    )


def _open_neighbors(r, c):
    return [
        (r + dr, c + dc)
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
        if _open(r + dr, c + dc)
    ]


def _hallway_cells():
    """Open cells that look like a straight hallway segment.

    A hallway cell has exactly two open neighbors that are opposite each other
    (a corridor running N-S or E-W), so the camera glide reads as moving down a
    corridor rather than across a wide room.
    """
    cells = []
    for r, row in enumerate(LAYOUT):
        for c, value in enumerate(row):
            if value != 0:
                continue
            neighbors = _open_neighbors(r, c)
            if len(neighbors) != 2:
                continue
            (r1, c1), (r2, c2) = neighbors
            # Opposite neighbors => straight corridor.
            if (r1 + r2, c1 + c2) == (2 * r, 2 * c):
                cells.append((r, c))
    return cells


def _cell_to_world(r, c):
    return c * CELL, r * CELL


class CinematicMode:
    def __init__(self):
        self.active = False
        # Free-flying rig the camera is reparented to while active.
        self.rig = None

        # Saved camera/player state for restoring on exit.
        self._saved_parent = None
        self._saved_local_pos = None
        self._saved_local_rot = None
        self._saved_fov = None
        self._player = None
        self._player_was_enabled = False
        self._map_renderer = None
        self._crosshair = None
        self._saved_player_pos = None
        self._saved_player_rot_y = None

        # Per-shot state.
        self._hallways = _hallway_cells()
        self._shot_timer = 0.0
        self._start_pos = Vec3(0, 0, 0)
        self._end_pos = Vec3(0, 0, 0)
        self._look_target = Vec3(0, 0, 0)
        self._last_cell = None

    # --- lifecycle -------------------------------------------------------
    def toggle(self, player, map_renderer=None, crosshair=None):
        if self.active:
            self.stop()
        else:
            self.start(player, map_renderer, crosshair)

    def start(self, player, map_renderer=None, crosshair=None):
        if self.active or not self._hallways:
            return

        self.active = True
        self._player = player
        self._map_renderer = map_renderer
        self._crosshair = crosshair

        # Hide the gameplay crosshair for clean teaser footage.
        if crosshair is not None:
            crosshair.set_visible(False)

        # Park the player so gameplay systems (head-bob, look) stop fighting us.
        self._player_was_enabled = getattr(player, 'enabled', True)
        self._saved_player_pos = Vec3(player.position)
        self._saved_player_rot_y = float(player.rotation_y)
        player.enabled = False
        player.speed = 0

        if self.rig is None:
            self.rig = Entity()

        # Save and hijack the camera.
        self._saved_parent = camera.parent
        self._saved_local_pos = Vec3(camera.position)
        self._saved_local_rot = Vec3(camera.rotation)
        self._saved_fov = camera.fov
        camera.parent = self.rig
        camera.position = (0, 0, 0)
        camera.rotation = (0, 0, 0)

        self._last_cell = None
        self._begin_shot(force=True)

    def stop(self):
        if not self.active:
            return

        self.active = False

        # Restore the camera onto the player rig.
        if self._saved_parent is not None:
            camera.parent = self._saved_parent
            camera.position = self._saved_local_pos
            camera.rotation = self._saved_local_rot
            camera.fov = self._saved_fov

        # Restore the gameplay crosshair.
        if self._crosshair is not None:
            self._crosshair.set_visible(True)
        self._crosshair = None

        if self._player is not None:
            # Restore the player where they were before the tour took over.
            if self._saved_player_pos is not None:
                self._player.position = self._saved_player_pos
            if self._saved_player_rot_y is not None:
                self._player.rotation_y = self._saved_player_rot_y
            self._player.enabled = self._player_was_enabled
            # Force a render refresh at the player's real spot.
            if self._map_renderer is not None:
                self._map_renderer._raycast_cache_key = None
                self._map_renderer.update_rendered_scene(force=True)
        self._player = None
        self._map_renderer = None

    # --- shot selection --------------------------------------------------
    def _pick_hallway(self):
        # Avoid repeating the immediately previous cell.
        choices = self._hallways
        if len(choices) > 1 and self._last_cell is not None:
            choices = [cell for cell in choices if cell != self._last_cell]
        return random.choice(choices)

    def _begin_shot(self, force=False):
        r, c = self._pick_hallway()
        self._last_cell = (r, c)

        neighbors = _open_neighbors(r, c)
        # Corridor axis: direction from this cell toward a randomly chosen open
        # neighbor, so the camera drifts left->right as often as right->left
        # (and up/down) instead of always the same way.
        (nr, nc) = random.choice(neighbors)
        axis_r, axis_c = nr - r, nc - c

        cx, cz = _cell_to_world(r, c)
        # Ceiling corner: high up, pushed toward a wall corner of the cell so it
        # reads as a security camera tucked in the corner.
        side = random.choice((-1, 1))
        corner_off = CELL * 0.32
        # Offset perpendicular to the corridor axis toward a wall, plus a small
        # backward offset along the corridor.
        perp_r, perp_c = axis_c, axis_r  # perpendicular in grid space
        start_x = cx + perp_c * corner_off * side - axis_c * corner_off
        start_z = cz + perp_r * corner_off * side - axis_r * corner_off
        start_y = WALL_H - CEILING_DROP

        # Glide target: drift through the hallway center toward the far neighbor.
        end_x = cx + axis_c * DRIFT_OVERSHOOT
        end_z = cz + axis_r * DRIFT_OVERSHOOT
        end_y = CENTER_EYE_HEIGHT

        self._start_pos = Vec3(start_x, start_y, start_z)
        self._end_pos = Vec3(end_x, end_y, end_z)
        # Look far down the corridor toward where we're drifting. Keeping the
        # target far away and near eye height keeps the camera close to level
        # instead of tilting sharply down at the floor.
        self._look_target = Vec3(
            cx + axis_c * CELL * LOOK_AHEAD_CELLS,
            CENTER_EYE_HEIGHT,
            cz + axis_r * CELL * LOOK_AHEAD_CELLS,
        )

        self._shot_timer = 0.0
        self.rig.position = self._start_pos
        self._aim_rig()

    def _aim_rig(self):
        # Aim by computing yaw/pitch directly and forcing roll to 0, so the
        # horizon stays level. ursina's look_at() can introduce roll that makes
        # the camera appear to fly sideways/upside down.
        dx = self._look_target.x - self.rig.x
        dy = self._look_target.y - self.rig.y
        dz = self._look_target.z - self.rig.z
        horizontal = max((dx * dx + dz * dz) ** 0.5, 1e-6)
        yaw = math.degrees(math.atan2(dx, dz))
        pitch = -math.degrees(math.atan2(dy, horizontal))
        self.rig.rotation = (pitch, yaw, 0)

    # --- per-frame update ------------------------------------------------
    def update(self):
        if not self.active:
            return

        dt = time.dt
        self._shot_timer += dt
        progress = min(1.0, self._shot_timer / SHOT_DURATION)

        # Ease-in-out glide from ceiling corner toward hallway center.
        eased = progress * progress * (3.0 - 2.0 * progress)
        self.rig.position = self._start_pos + (self._end_pos - self._start_pos) * eased
        self._aim_rig()

        # Drive the map renderer from the cinematic viewpoint so geometry the
        # player never visited still gets built and shown. The player entity is
        # disabled, so we can safely teleport it to the camera position and
        # point it down the corridor to feed the visibility raycast.
        if self._map_renderer is not None and self._player is not None:
            self._player.x = self.rig.x
            self._player.z = self.rig.z
            self._player.rotation_y = self.rig.rotation_y
            self._map_renderer.update_rendered_scene()
            self._map_renderer.process_queues()

        # Cut straight to the next shot, no fade.
        if self._shot_timer >= SHOT_DURATION:
            self._begin_shot()


