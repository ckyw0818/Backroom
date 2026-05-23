import random
from collections import deque
from pathlib import Path

from ursina import Audio, Entity, Vec3, color, time


MONSTER_STATES = ('idle', 'wander', 'investigate', 'alert', 'chase', 'lost')
STATE_SOUND_FILES = {
    'idle': 'monster_idle.wav',
    'wander': 'monster_wander.wav',
    'alert': 'monster_alert.wav',
    'chase': 'monster_chasing.wav',
    'lost': 'monster_lost.wav',
}

CHASE_SOUND_MIN_DISTANCE = 2.0
CHASE_SOUND_MAX_DISTANCE = 18.0
CHASE_SOUND_MIN_VOLUME = 0.2
CHASE_SOUND_MAX_VOLUME = 1.0
CHASE_LOST_TIME = 8.0

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
        self.last_seen_cell = None
        self.lost_timer = 0.0
        self.chase_sound_active = False
        self.texture = texture
        self.chase_speed = chase_speed

        self.sounds = self.load_sounds(project_dir)

        spawn = spawn_cell or self.pick_spawn_cell()
        x, z = self.cell_center(spawn)

        self.entity = Entity(
            model='quad',
            texture=self.texture,
            color=color.white,
            unlit=True,
            position=(x, 1.05, z),
            scale=(2.35, 2.15, 1.0),
            double_sided=True,
        )

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

    def monster_cell(self):
        return self.cell_from_world(self.entity.x, self.entity.z)

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
            return

        tx, tz = self.cell_center(self.path[0])
        dx = tx - self.entity.x
        dz = tz - self.entity.z
        dist = max((dx * dx + dz * dz) ** 0.5, 0.001)
        step = min(dist, speed * time.dt)

        self.entity.x += dx / dist * step
        self.entity.z += dz / dist * step

        if dist < 0.08:
            self.path.pop(0)

    def face_player(self):
        self.entity.look_at(Vec3(self.player.x, self.entity.y, self.player.z))

    def update_path(self, goal_cell, interval):
        self.path_timer -= time.dt

        if self.path_timer > 0 and self.path:
            return

        self.path_timer = interval
        self.path = self.find_path(self.monster_cell(), goal_cell)

    def investigate_noise(self, cell):
        if cell not in self.walkable:
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
            self.distance_to_player() < 16
            and self.has_line_of_sight_to_player()
        )

        if sees_player:
            self.last_seen_cell = self.player_cell()
            self.lost_timer = 0.0

            if self.state not in ('alert', 'chase'):
                self.set_state('alert')

        if self.state == 'idle':
            if self.state_time > 1.5:
                self.set_state('wander')

        elif self.state == 'wander':
            if not self.path:
                self.target_cell = self.pick_wander_target()
                self.path = self.find_path(self.monster_cell(), self.target_cell)

            self.move_along_path(1.05)

        elif self.state == 'investigate':
            if not self.investigate_cell:
                self.set_state('wander')
            else:
                self.update_path(self.investigate_cell, 0.75)
                self.move_along_path(1.35)

                if self.monster_cell() == self.investigate_cell:
                    self.investigate_cell = None
                    self.path = []
                    self.set_state('wander')

        elif self.state == 'alert':
            if self.state_time > 0.1:
                self.set_state('chase')

        elif self.state == 'chase':
            if sees_player:
                self.update_path(self.player_cell(), 0.25)
                self.move_along_path(self.chase_speed)
            else:
                self.lost_timer += time.dt

                if self.last_seen_cell:
                    self.update_path(self.last_seen_cell, 0.35)
                    self.move_along_path(self.chase_speed * 0.7)

                if self.lost_timer > CHASE_LOST_TIME:
                    self.set_state('lost')

        elif self.state == 'lost':
            if self.state_time > 1.2:
                self.path = []
                self.set_state('wander')

        self.face_player()
        self.update_chase_sound()
