import math
import random
from collections import deque
from pathlib import Path

from ursina import Audio, Entity, Vec3, color, time
from map.map_data import CELL
from character.player_controller import RUN_SPEED   


MONSTER_STATES = ('idle', 'wander', 'investigate', 'alert', 'chase', 'door_stalk')
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
DOOR_STALK_TRIGGER_DISTANCE = CELL * 2
DOOR_STALK_WAIT_TIME = 3.0
DOOR_STALK_DOOR_REACH_DIST = CELL * 0.56
DOOR_STALK_ROOM_REACH_DIST = CELL * 0.18
DOOR_STALK_RETREAT_TIME = 3.0
DOOR_STALK_COOLDOWN = 10.0
DOOR_STALK_CORRIDOR_MAX_DIST = 2
ROAR_SOUND_MIN_DISTANCE = 2.0
ROAR_SOUND_MAX_DISTANCE = CELL * 6
ROAR_SOUND_MIN_VOLUME = 0.20
ROAR_SOUND_MAX_VOLUME = 1.00
NOISE_DOOR_BREACH_REACH_DIST = DOOR_STALK_DOOR_REACH_DIST

MONSTER_WANDER_SPEED = RUN_SPEED * 0.2
MONSTER_INVESTIGATE_SPEED = RUN_SPEED * 0.4
MONSTER_DOOR_STALK_SPEED = RUN_SPEED * 0.75

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
        self.roar_sound_active = False
        self.sound_volume_scale = 1.0
        self.door_system = None
        self.respawn_min_distance_from_start = 28
        self.door_stalk_key = None
        self.door_stalk_door = None
        self.door_stalk_phase = None
        self.door_stalk_timer = 0.0
        self.door_stalk_noise_heard = False
        self.door_stalk_entry_cell = None
        self.door_stalk_cooldown = 0.0
        self.jumpscare_seen_this_chase = False
        self.texture = texture
        self.chase_speed = chase_speed
        self.speed_multiplier = 1.0
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

    def set_door_system(self, door_system, respawn_min_distance_from_start=28):
        self.door_system = door_system
        self.respawn_min_distance_from_start = respawn_min_distance_from_start

    def set_sound_volume_scale(self, scale):
        self.sound_volume_scale = max(0.0, min(1.0, scale))

        if self.sound_volume_scale <= 0.02:
            self.stop_chase_sound()
            self.stop_roar_sound()
            return

        if self.chase_sound_active and self.sounds.get('chase'):
            self.sounds['chase'].volume = self.chase_sound_volume()

        if self.roar_sound_active and self.sounds.get('roar'):
            self.sounds['roar'].volume = self.roar_sound_volume()

    def set_speed_multiplier(self, multiplier):
        self.speed_multiplier = max(0.01, multiplier)

    def reset_to_spawn(self):
        self.reset_to_cell(self.spawn_cell)

    def reset_to_cell(self, cell, state='idle'):
        self.stop_chase_sound()
        self.stop_roar_sound()
        x, z = self.cell_center(cell)
        self.entity.position = (x, 1.05, z)
        self.velocity_x = 0.0
        self.velocity_z = 0.0
        self.path = []
        self.path_timer = 0.0
        self.target_cell = None
        self.investigate_cell = None
        self.door_stalk_key = None
        self.door_stalk_door = None
        self.door_stalk_phase = None
        self.door_stalk_timer = 0.0
        self.door_stalk_noise_heard = False
        self.door_stalk_entry_cell = None
        self.door_stalk_cooldown = 0.0
        self.jumpscare_seen_this_chase = False
        self.set_state(state)

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

        for roar_filename in ('roar.wav', 'roar.mp3'):
            roar_path = sound_dir / roar_filename
            if roar_path.exists():
                sounds['roar'] = Audio(f'asset/sound/{roar_filename}', autoplay=False, loop=True, volume=0.0)
                break

        return sounds

    def set_state(self, state):
        if state == self.state:
            return

        previous = self.state
        self.state = state
        self.state_time = 0.0

        if previous == 'chase' and state != 'chase':
            self.stop_chase_sound()
        if previous == 'door_stalk' and state != 'door_stalk':
            self.stop_roar_sound()

        sound = self.sounds.get(state)

        if state == 'chase':
            self.jumpscare_seen_this_chase = False
            self.start_chase_sound()
        elif sound:
            sound.stop()
            sound.volume = 0.55 * self.sound_volume_scale
            sound.play()

    def chase_sound_volume(self):
        dist = self.distance_to_player()

        t = 1.0 - (
            (dist - CHASE_SOUND_MIN_DISTANCE)
            / (CHASE_SOUND_MAX_DISTANCE - CHASE_SOUND_MIN_DISTANCE)
        )

        t = max(0.0, min(1.0, t))
        t = t * t * (3.0 - 2.0 * t)

        volume = CHASE_SOUND_MIN_VOLUME + (CHASE_SOUND_MAX_VOLUME - CHASE_SOUND_MIN_VOLUME) * t
        return volume * self.sound_volume_scale

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
        sound.volume = 0.0
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

    def roar_sound_volume(self):
        if self.sound_volume_scale <= 0.02:
            return 0.0

        dist = self.distance_to_player()
        t = 1.0 - (
            (dist - ROAR_SOUND_MIN_DISTANCE)
            / (ROAR_SOUND_MAX_DISTANCE - ROAR_SOUND_MIN_DISTANCE)
        )
        t = max(0.0, min(1.0, t))
        t = t * t * (3.0 - 2.0 * t)

        return max(ROAR_SOUND_MIN_VOLUME, ROAR_SOUND_MAX_VOLUME * t) * self.sound_volume_scale

    def start_roar_sound(self):
        if 'roar' not in self.sounds:
            return

        old_sound = self.sounds.get('roar')
        if old_sound:
            old_sound.volume = 0.0
            old_sound.stop()

        sound = Audio(
            'asset/sound/roar.wav',
            autoplay=False,
            loop=True,
            volume=self.roar_sound_volume(),
        )

        self.sounds['roar'] = sound
        sound.volume = self.roar_sound_volume()
        sound.play()
        self.roar_sound_active = True

    def stop_roar_sound(self):
        sound = self.sounds.get('roar')

        if sound:
            sound.volume = 0.0
            sound.stop()

        self.roar_sound_active = False

    def stop_all_looping_sounds(self):
        self.stop_chase_sound()
        self.stop_roar_sound()

    def silence_all_sounds(self):
        for sound in self.sounds.values():
            if not sound:
                continue
            sound.volume = 0.0
            sound.stop()

        self.chase_sound_active = False
        self.roar_sound_active = False

    def update_roar_sound(self):
        sound = self.sounds.get('roar')

        if not sound:
            return

        if self.state != 'door_stalk':
            if self.roar_sound_active:
                self.stop_roar_sound()
            return

        sound.volume = self.roar_sound_volume()

        if not self.roar_sound_active:
            self.start_roar_sound()

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

    def player_closed_room_door(self):
        if not self.door_system:
            return None, None

        player_cell = self.player_cell()
        key, door = self.door_system.closed_door_for_room_cell(player_cell)
        return key, door

    def player_hidden_behind_closed_door(self):
        key, door = self.player_closed_room_door()
        return key is not None and door is not None

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
                if (
                    self.layout[r][c] == 1
                    and not ((r, c) == self.player_cell() and not self.player_hidden_behind_closed_door())
                ):
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
        if self.player_hidden_behind_closed_door():
            return False

        dx = self.player.x - self.entity.x
        dz = self.player.z - self.entity.z
        dist = max((dx * dx + dz * dz) ** 0.5, 0.001)
        steps = max(2, int(dist / (self.cell * 0.20)))

        for i in range(1, steps):
            t = i / steps
            x = self.entity.x + dx * t
            z = self.entity.z + dz * t
            cell = self.cell_from_world(x, z)

            r, c = cell

            if r < 0 or r >= self.rows or c < 0 or c >= self.cols:
                return False

            if cell == self.player_cell():
                return True

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
        speed *= self.speed_multiplier
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
        if self.handle_closed_room_noise(cell, strength):
            return

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

        if self.state not in ('chase', 'door_stalk'):
            self.set_state('investigate')

    def noise_reaches_monster(self, cell, strength):
        if cell not in self.walkable:
            return False

        strength = max(0.0, min(1.0, strength))
        if strength <= 0.0:
            return False

        max_dist = NOISE_ATTRACT_RADIUS_CELLS * strength
        return self.grid_distance(self.monster_cell(), cell) <= max_dist

    def handle_closed_room_noise(self, cell, strength):
        if not self.noise_reaches_monster(cell, strength):
            return False

        key, door = self.player_closed_room_door()
        if key is None or door is None:
            return False

        if self.state != 'door_stalk' or self.door_stalk_key != key:
            return False

        self.door_stalk_noise_heard = True
        return True

    def begin_door_stalk(self, key, door):
        self.door_stalk_key = key
        self.door_stalk_door = door
        self.door_stalk_phase = 'approach'
        self.door_stalk_timer = 0.0
        self.door_stalk_noise_heard = False
        self.door_stalk_entry_cell = None
        self.target_cell = (key[0], key[1])
        self.path = []
        self.path_timer = 0.0
        self.set_state('door_stalk')
        self.start_roar_sound()

    def breach_stalked_door(self):
        self.stop_roar_sound()

        entry_cell = None
        if self.door_system and self.door_stalk_key is not None:
            entry_cell, _ = self.door_system.door_room_for_face(*self.door_stalk_key)
            self.door_system.open_door_by_key(self.door_stalk_key)

        self.door_stalk_entry_cell = entry_cell or self.player_cell()
        self.door_stalk_phase = 'enter_room'
        self.door_stalk_timer = 0.0
        self.door_stalk_noise_heard = False
        self.path = []
        self.path_timer = 0.0
        self.target_cell = self.door_stalk_entry_cell

    def reached_stalked_door(self, door_dist):
        if door_dist <= NOISE_DOOR_BREACH_REACH_DIST:
            return True

        if self.door_stalk_key and self.monster_cell() == (self.door_stalk_key[0], self.door_stalk_key[1]):
            return True

        return False

    def teleport_far_from_start(self):
        start_room_cell = getattr(self.door_system, 'start_room_cell', self.player_cell())
        candidates = [
            cell for cell in self.walkable
            if self.grid_distance(cell, start_room_cell) >= self.respawn_min_distance_from_start
        ]

        if not candidates:
            candidates = list(self.walkable)

        cell = random.choice(candidates)
        x, z = self.cell_center(cell)
        self.entity.position = (x, 1.05, z)
        self.velocity_x = 0.0
        self.velocity_z = 0.0
        self.path = []
        self.path_timer = 0.0
        self.target_cell = None
        self.investigate_cell = None
        self.door_stalk_key = None
        self.door_stalk_door = None
        self.door_stalk_phase = None
        self.door_stalk_timer = 0.0
        self.door_stalk_noise_heard = False
        self.set_state('wander')

    def pick_retreat_target(self):
        start = self.monster_cell()
        player_cell = self.player_cell()
        candidates = [
            cell for cell in self.walkable
            if 4 <= self.grid_distance(start, cell) <= 12
        ]

        if not candidates:
            return self.pick_wander_target()

        candidates.sort(key=lambda cell: self.grid_distance(cell, player_cell), reverse=True)
        return random.choice(candidates[:max(1, min(6, len(candidates)))])

    def finish_door_stalk_retreat(self):
        self.door_stalk_key = None
        self.door_stalk_door = None
        self.door_stalk_phase = None
        self.door_stalk_entry_cell = None
        self.door_stalk_timer = 0.0
        self.door_stalk_noise_heard = False
        self.door_stalk_cooldown = DOOR_STALK_COOLDOWN
        self.path = []
        self.path_timer = 0.0
        self.target_cell = None
        self.apply_movement(0.0, 0.0, 0.0)
        self.set_state('wander')

    def update_door_stalk(self):
        if self.door_stalk_phase == 'enter_room':
            pass
        elif not self.door_stalk_key or not self.door_stalk_door:
            self.set_state('wander')
            return

        if (
            self.door_stalk_phase != 'enter_room'
            and self.door_system
            and self.door_system.door_states.get(self.door_stalk_key, False)
        ):
            self.breach_stalked_door()
            return

        door_dist = 0.0
        if self.door_stalk_door:
            door_x, _, door_z = self.door_stalk_door['position']
            dx = door_x - self.entity.x
            dz = door_z - self.entity.z
            door_dist = (dx * dx + dz * dz) ** 0.5

        if self.door_stalk_noise_heard and self.door_stalk_phase not in ('breach', 'enter_room'):
            self.door_stalk_phase = 'breach'
            self.door_stalk_timer = 0.0
            self.target_cell = (self.door_stalk_key[0], self.door_stalk_key[1])
            self.path = []
            self.path_timer = 0.0

        if self.door_stalk_phase == 'approach':
            self.update_path((self.door_stalk_key[0], self.door_stalk_key[1]), 0.25)
            self.move_along_path(MONSTER_DOOR_STALK_SPEED)

            if door_dist <= DOOR_STALK_DOOR_REACH_DIST:
                self.door_stalk_phase = 'wait'
                self.door_stalk_timer = DOOR_STALK_WAIT_TIME
                self.apply_movement(0.0, 0.0, 0.0)
            return

        if self.door_stalk_phase == 'wait':
            self.door_stalk_timer = max(0.0, self.door_stalk_timer - time.dt)
            self.apply_movement(0.0, 0.0, 0.0)

            if self.door_stalk_timer <= 0.0:
                self.door_stalk_phase = 'retreat'
                self.door_stalk_timer = DOOR_STALK_RETREAT_TIME
                self.target_cell = self.pick_retreat_target()
                self.path = self.find_path(self.monster_cell(), self.target_cell)
                self.path_timer = 0.0
            return

        if self.door_stalk_phase == 'retreat':
            self.door_stalk_timer = max(0.0, self.door_stalk_timer - time.dt)

            if self.distance_to_player() >= ROAR_SOUND_MAX_DISTANCE or self.door_stalk_timer <= 0.0:
                self.teleport_far_from_start()
                return

            if not self.path:
                self.teleport_far_from_start()
                return

            self.move_along_path(MONSTER_WANDER_SPEED)

            if not self.path:
                self.teleport_far_from_start()
            return

        if self.door_stalk_phase == 'breach':
            self.update_path((self.door_stalk_key[0], self.door_stalk_key[1]), 0.12)
            self.move_along_path(self.chase_speed)

            door_x, _, door_z = self.door_stalk_door['position']
            dx = door_x - self.entity.x
            dz = door_z - self.entity.z
            door_dist = (dx * dx + dz * dz) ** 0.5

            if self.reached_stalked_door(door_dist):
                self.breach_stalked_door()
            return

        if self.door_stalk_phase == 'enter_room':
            if not self.door_stalk_entry_cell:
                self.set_state('chase')
                return

            tx, tz = self.cell_center(self.door_stalk_entry_cell)
            dx = tx - self.entity.x
            dz = tz - self.entity.z
            dist = max((dx * dx + dz * dz) ** 0.5, 0.001)
            self.apply_movement(
                dx / dist,
                dz / dist,
                self.chase_speed,
                accel_override=MONSTER_DIRECT_CHASE_ACCEL,
            )

            if dist <= DOOR_STALK_ROOM_REACH_DIST:
                self.door_stalk_key = None
                self.door_stalk_door = None
                self.door_stalk_phase = None
                self.door_stalk_entry_cell = None
                self.path = []
                self.path_timer = 0.0
                self.set_state('chase')
            return

    def update(self):
        self.state_time += time.dt
        self.door_stalk_cooldown = max(0.0, self.door_stalk_cooldown - time.dt)
        closed_room_key, closed_room_door = self.player_closed_room_door()
        player_hidden = closed_room_key is not None and closed_room_door is not None

        sees_player = (
            not player_hidden
            and
            self.distance_to_player() < CHASE_DETECT_DISTANCE
            and self.has_line_of_sight_to_player()
        )

        if sees_player:
            if self.state not in ('alert', 'chase'):
                self.set_state('alert')

        if (
            self.state not in ('door_stalk', 'idle')
            and player_hidden
            and self.distance_to_player() <= DOOR_STALK_TRIGGER_DISTANCE
            and self.door_stalk_cooldown <= 0.0
            and self.grid_distance(
                self.monster_cell(),
                (closed_room_key[0], closed_room_key[1]),
            ) <= DOOR_STALK_CORRIDOR_MAX_DIST
        ):
            self.begin_door_stalk(closed_room_key, closed_room_door)

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

        elif self.state == 'door_stalk':
            self.update_door_stalk()

        if self.state in ('idle', 'alert') or (self.state != 'chase' and not self.path):
            self.apply_movement(0.0, 0.0, 0.0)
        else:
            self.face_player_smooth()
        self.update_chase_sound()
        self.update_roar_sound()
