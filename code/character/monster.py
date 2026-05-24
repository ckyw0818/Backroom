import math
import random
from collections import deque
from pathlib import Path

from ursina import Audio, Entity, Vec3, color, time
from map.map_data import CELL
from character.player_controller import RUN_SPEED   


MONSTER_STATES = ('idle', 'wander', 'investigate', 'alert', 'chase')
STATE_SOUND_FILES = {
    'idle': 'monster_idle.wav',
    'wander': 'monster_wander.wav',
    'alert': 'monster_alert.wav',
    'chase': 'monster_chasing.wav',
}

CHASE_SOUND_MIN_DISTANCE = 2.0
CHASE_DETECT_DISTANCE = CELL * 8
CHASE_SOUND_MAX_DISTANCE = CELL * 6
CHASE_SOUND_MIN_VOLUME = 0.00
CHASE_SOUND_MAX_VOLUME = 1.0
NOISE_ATTRACT_RADIUS_CELLS = 26.0
MONSTER_ACCEL = 7.0
MONSTER_DIRECT_CHASE_ACCEL = 13.0
MONSTER_DECEL = 7.5
MONSTER_TURN_SPEED = 8.0
MONSTER_WAYPOINT_REACH_DIST = 0.22
DIRECT_CHASE_SPEED_MULT = 1.18

MONSTER_WANDER_SPEED = RUN_SPEED * 0.4
MONSTER_INVESTIGATE_SPEED = RUN_SPEED * 0.7

MONSTER_COLLISION_RADIUS = 0.48

class MonsterAI:
    def __init__(
        self,
        player,
        layout,
        cell_size,
        project_dir,
        spawn_cell=None,
        texture='asset/texture/obunga.png',
        chase_speed=4.94,
    ):
        self.player = player
        self.layout = layout
        self.cell = cell_size
        self.rows = len(layout)
        self.cols = len(layout[0])
        self.walkable = {
            (r, c)
            for r in range(self.rows)
            for c in range(self.cols)
            if layout[r][c] == 0
        }

        self.state = None
        self.state_time = 0.0
        self.path = []
        self.path_timer = 0.0
        self.target_cell = None
        self.investigate_cell = None
        self.chase_sound_active = False
        self.jumpscare_seen_this_chase = False
        self.texture = texture
        self.chase_speed = chase_speed
        self.velocity_x = 0.0
        self.velocity_z = 0.0
        self.facing_yaw = 0.0

        self.sounds = self.load_sounds(project_dir)

        spawn = spawn_cell or self.pick_spawn_cell()
        self.spawn_cell = spawn
        x, z = self.cell_center(spawn)

        self.entity = Entity(
            model='quad',
            texture=self.texture,
            color=color.white,
            unlit=True,
            position=(x, 1.05, z),
            scale=(2.85, 2.60, 1.0),
            double_sided=True,
        )

        self.set_state('idle')

    def reset_to_spawn(self):
        self.stop_chase_sound()
        x, z = self.cell_center(self.spawn_cell)
        self.entity.position = (x, 1.05, z)
        self.velocity_x = 0.0
        self.velocity_z = 0.0
        self.path = []
        self.path_timer = 0.0
        self.target_cell = None
        self.investigate_cell = None
        self.jumpscare_seen_this_chase = False
        self.set_state('idle')

    def load_sounds(self, project_dir):
        sound_dir = Path(project_dir) / 'asset' / 'sound'
        sounds = {}

        for state, filename in STATE_SOUND_FILES.items():
            path = sound_dir / filename

            if not path.exists():
                continue

            sounds[state] = Audio(
                f'asset/sound/{filename}',
                autoplay=False,
                loop=False,
                volume=CHASE_SOUND_MAX_VOLUME if state == 'chase' else 0.55,
            )

        return sounds

    def set_state(self, state):
        if state == self.state:
            return

        previous = self.state
        self.state = state
        self.state_time = 0.0

        if previous == 'chase' and state != 'chase':
            self.stop_chase_sound()

        sound = self.sounds.get(state)

        if state == 'chase':
            self.jumpscare_seen_this_chase = False
            self.start_chase_sound()
        elif sound:
            sound.stop()
            sound.play()

    def chase_sound_volume(self):
        dist = self.distance_to_player()

        t = 1.0 - (
            (dist - CHASE_SOUND_MIN_DISTANCE)
            / (CHASE_SOUND_MAX_DISTANCE - CHASE_SOUND_MIN_DISTANCE)
        )

        t = max(0.0, min(1.0, t))
        t = t * t * (3.0 - 2.0 * t)

        return CHASE_SOUND_MIN_VOLUME + (CHASE_SOUND_MAX_VOLUME - CHASE_SOUND_MIN_VOLUME) * t

    def start_chase_sound(self):
        if 'chase' not in self.sounds:
            return

        old_sound = self.sounds.get('chase')
        if old_sound:
            old_sound.stop()

        sound = Audio(
            'asset/sound/monster_chasing.wav',
            autoplay=False,
            loop=True,
            volume=self.chase_sound_volume(),
        )
        self.sounds['chase'] = sound
        sound.volume = self.chase_sound_volume()
        sound.play()
        self.chase_sound_active = True

    def stop_chase_sound(self):
        sound = self.sounds.get('chase')

        if not sound:
            self.chase_sound_active = False
            return

        sound.stop()
        self.chase_sound_active = False

    def update_chase_sound(self):
        sound = self.sounds.get('chase')

        if not sound:
            return

        if self.state != 'chase':
            if self.chase_sound_active:
                self.stop_chase_sound()
            return

        sound.volume = self.chase_sound_volume()

        if not self.chase_sound_active:
            self.start_chase_sound()

    def cell_from_world(self, x, z):
        return (
            int((z + self.cell / 2) // self.cell),
            int((x + self.cell / 2) // self.cell),
        )

    def cell_center(self, cell):
        r, c = cell
        return c * self.cell, r * self.cell

    def player_cell(self):
        return self.cell_from_world(self.player.x, self.player.z)

    def reachable_player_cell(self):
        cell = self.player_cell()
        if cell in self.walkable:
            return cell

        r, c = cell
        best = None
        best_dist = None

        for dr, dc in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            neighbor = (r + dr, c + dc)
            if neighbor not in self.walkable:
                continue

            x, z = self.cell_center(neighbor)
            dx = self.player.x - x
            dz = self.player.z - z
            dist = dx * dx + dz * dz

            if best is None or dist < best_dist:
                best = neighbor
                best_dist = dist

        return best or cell

    def monster_cell(self):
        return self.cell_from_world(self.entity.x, self.entity.z)

    def can_occupy(self, x, z):
        radius = MONSTER_COLLISION_RADIUS
        min_c = int((x - radius + self.cell / 2) // self.cell)
        max_c = int((x + radius + self.cell / 2) // self.cell)
        min_r = int((z - radius + self.cell / 2) // self.cell)
        max_r = int((z + radius + self.cell / 2) // self.cell)

        for r in range(min_r, max_r + 1):
            for c in range(min_c, max_c + 1):
                if r < 0 or r >= self.rows or c < 0 or c >= self.cols:
                    return False
                if self.layout[r][c] == 1:
                    return False

        return True

    def pick_spawn_cell(self):
        player_cell = self.player_cell()
        candidates = list(self.walkable)
        candidates.sort(key=lambda cell: self.grid_distance(cell, player_cell), reverse=True)
        return random.choice(candidates[:max(1, min(8, len(candidates)))])

    def grid_distance(self, a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def distance_to_player(self):
        dx = self.player.x - self.entity.x
        dz = self.player.z - self.entity.z
        return (dx * dx + dz * dz) ** 0.5

    def has_line_of_sight_to_player(self):
        dx = self.player.x - self.entity.x
        dz = self.player.z - self.entity.z
        dist = max((dx * dx + dz * dz) ** 0.5, 0.001)
        steps = max(2, int(dist / (self.cell * 0.20)))

        for i in range(1, steps):
            t = i / steps
            x = self.entity.x + dx * t
            z = self.entity.z + dz * t
            cell = self.cell_from_world(x, z)

            if cell == self.player_cell():
                return True

            r, c = cell

            if r < 0 or r >= self.rows or c < 0 or c >= self.cols:
                return False

            if self.layout[r][c] == 1:
                return False

        return True

    def find_path(self, start, goal):
        if start not in self.walkable or goal not in self.walkable:
            return []

        queue = deque([start])
        came_from = {start: None}

        while queue:
            cell = queue.popleft()

            if cell == goal:
                break

            r, c = cell
            neighbors = [
                (r - 1, c),
                (r + 1, c),
                (r, c - 1),
                (r, c + 1),
            ]

            random.shuffle(neighbors)

            for nxt in neighbors:
                if nxt in came_from or nxt not in self.walkable:
                    continue

                came_from[nxt] = cell
                queue.append(nxt)

        if goal not in came_from:
            return []

        path = []
        cell = goal

        while cell and cell != start:
            path.append(cell)
            cell = came_from[cell]

        path.reverse()
        return path

    def pick_wander_target(self):
        start = self.monster_cell()
        candidates = [
            cell for cell in self.walkable
            if 3 <= self.grid_distance(start, cell) <= 8
        ]

        return random.choice(candidates) if candidates else start

    def move_along_path(self, speed):
        if not self.path:
            self.apply_movement(0.0, 0.0, 0.0)
            return

        tx, tz = self.cell_center(self.path[0])
        dx = tx - self.entity.x
        dz = tz - self.entity.z
        dist = max((dx * dx + dz * dz) ** 0.5, 0.001)
        dir_x = dx / dist
        dir_z = dz / dist

        self.apply_movement(dir_x, dir_z, speed)

        if dist < MONSTER_WAYPOINT_REACH_DIST:
            self.path.pop(0)

    def move_towards_player_direct(self):
        dx = self.player.x - self.entity.x
        dz = self.player.z - self.entity.z
        dist = max((dx * dx + dz * dz) ** 0.5, 0.001)
        self.apply_movement(
            dx / dist,
            dz / dist,
            self.chase_speed * DIRECT_CHASE_SPEED_MULT,
            accel_override=MONSTER_DIRECT_CHASE_ACCEL,
        )

    def apply_movement(self, dir_x, dir_z, speed, accel_override=None):
        dt = time.dt
        target_vx = dir_x * speed
        target_vz = dir_z * speed
        current_speed = (self.velocity_x * self.velocity_x + self.velocity_z * self.velocity_z) ** 0.5
        target_speed = (target_vx * target_vx + target_vz * target_vz) ** 0.5
        if target_speed > current_speed:
            accel = accel_override if accel_override is not None else MONSTER_ACCEL
        else:
            accel = MONSTER_DECEL
        k = min(1.0, dt * accel)

        self.velocity_x += (target_vx - self.velocity_x) * k
        self.velocity_z += (target_vz - self.velocity_z) * k

        next_x = self.entity.x + self.velocity_x * dt
        if self.can_occupy(next_x, self.entity.z):
            self.entity.x = next_x
        else:
            self.velocity_x = 0.0

        next_z = self.entity.z + self.velocity_z * dt
        if self.can_occupy(self.entity.x, next_z):
            self.entity.z = next_z
        else:
            self.velocity_z = 0.0

        self.face_player_smooth()

    def turn_towards(self, dir_x, dir_z):
        target_yaw = math.degrees(math.atan2(dir_x, dir_z))
        diff = (target_yaw - self.facing_yaw + 180.0) % 360.0 - 180.0
        self.facing_yaw += diff * min(1.0, time.dt * MONSTER_TURN_SPEED)
        self.entity.rotation_y = self.facing_yaw

    def face_player_smooth(self):
        dx = self.player.x - self.entity.x
        dz = self.player.z - self.entity.z
        if dx * dx + dz * dz < 0.0001:
            return

        self.turn_towards(dx, dz)

    def update_path(self, goal_cell, interval):
        self.path_timer -= time.dt

        if self.path_timer > 0 and self.path:
            return

        self.path_timer = interval
        self.path = self.find_path(self.monster_cell(), goal_cell)

    def investigate_noise(self, cell, strength=1.0):
        if cell not in self.walkable:
            return

        strength = max(0.0, min(1.0, strength))
        if strength <= 0.0:
            return

        max_dist = NOISE_ATTRACT_RADIUS_CELLS * strength
        if self.grid_distance(self.monster_cell(), cell) > max_dist:
            return

        self.investigate_cell = cell
        self.target_cell = cell
        self.path = []
        self.path_timer = 0.0

        if self.state != 'chase':
            self.set_state('investigate')

    def update(self):
        self.state_time += time.dt

        sees_player = (
            self.distance_to_player() < CHASE_DETECT_DISTANCE
            and self.has_line_of_sight_to_player()
        )

        if sees_player:
            if self.state not in ('alert', 'chase'):
                self.set_state('alert')

        if self.state == 'idle':
            if self.state_time > 1.5:
                self.set_state('wander')

        elif self.state == 'wander':
            if not self.path:
                self.target_cell = self.pick_wander_target()
                self.path = self.find_path(self.monster_cell(), self.target_cell)

            self.move_along_path(MONSTER_WANDER_SPEED)

        elif self.state == 'investigate':
            if not self.investigate_cell:
                self.set_state('wander')
            else:
                self.update_path(self.investigate_cell, 0.75)
                self.move_along_path(MONSTER_INVESTIGATE_SPEED)

                if self.monster_cell() == self.investigate_cell:
                    self.investigate_cell = None
                    self.path = []
                    self.set_state('wander')

        elif self.state == 'alert':
            if self.state_time > 0.1:
                self.set_state('chase')

        elif self.state == 'chase':
            if sees_player:
                self.path = []
                self.path_timer = 0.0
                self.move_towards_player_direct()
            else:
                self.update_path(self.reachable_player_cell(), 0.25)
                self.move_along_path(self.chase_speed)

        if self.state in ('idle', 'alert') or (self.state != 'chase' and not self.path):
            self.apply_movement(0.0, 0.0, 0.0)
        else:
            self.face_player_smooth()
        self.update_chase_sound()
