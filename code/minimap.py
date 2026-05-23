from math import atan2, degrees, sqrt

from ursina import Entity, Mesh, camera, color, time


MINIMAP_ENABLED = False

MINIMAP_SIZE = 0.3
MINIMAP_POSITION = (0.60, 0.27)

MINIMAP_WORLD_RANGE = 20
MINIMAP_INNER = 0.88

SCAN_RADIUS_CELLS = 4
SCAN_PULSE_TIME = 0.8
MONSTER_PULSE_TIME = 0.65

PLAYER_TRI_W = 0.017
PLAYER_TRI_H = 0.022
MONSTER_DOT_SCALE = 0.016

FLOOR_ALPHA = 235
ROOM_ALPHA = 210
FLOOR_SCALE = 0.52
EDGE_FADE = 0.28


def rgba(r, g, b, a):
    return color.Color(r / 255, g / 255, b / 255, a / 255)


class Minimap:
    def __init__(self, layout, cell_size, player, monster, cell_door_rooms=None, enabled=MINIMAP_ENABLED):
        self.layout = layout
        self.cell = cell_size
        self.player = player
        self.monsters = monster if isinstance(monster, list) else [monster]
        self.rows = len(layout)
        self.cols = len(layout[0])
        self.enabled = enabled

        self.cell_door_rooms = cell_door_rooms or {}
        self._door_room_set = frozenset(
            dr for drs in self.cell_door_rooms.values() for dr in drs
        )
        self.tiles = []
        self.room_tiles = []
        self.door_indicators = []
        self.revealed_cells = set()

        self.scanning = False
        self.scan_origin = (0, 0)
        self.scan_wave = 0.0
        self.scan_max = 0.0
        self.pending_monster_pulse_dists = [None for _ in self.monsters]

        self.has_monster_fixes = [False for _ in self.monsters]
        self.monster_fix_positions = [(0.0, 0.0) for _ in self.monsters]
        self.monster_pulse_ts = [MONSTER_PULSE_TIME for _ in self.monsters]

        self.root = Entity(
            parent=camera.ui,
            position=(*MINIMAP_POSITION, 0),
            enabled=enabled,
        )

        self.shadow = Entity(
            parent=self.root,
            model='circle',
            color=rgba(0, 0, 0, 90),
            position=(0.008, -0.008, 0.16),
            scale=MINIMAP_SIZE * 1.04,
        )

        self.bg = Entity(
            parent=self.root,
            model='circle',
            color=rgba(8, 9, 7, 230),
            position=(0, 0, 0.14),
            scale=MINIMAP_SIZE,
        )

        self.scan_pulse = Entity(
            parent=self.root,
            model='circle',
            color=rgba(178, 175, 118, 0),
            position=(0, 0, -0.03),
            scale=0.001,
            enabled=False,
        )

        self.monster_pulses = []
        for _ in self.monsters:
            self.monster_pulses.append(Entity(
                parent=self.root,
                model='circle',
                color=rgba(255, 35, 35, 0),
                position=(0, 0, -0.07),
                scale=0.001,
                enabled=False,
            ))

        self.create_tiles()

        self.player_marker = Entity(
            parent=self.root,
            model=Mesh(
                vertices=[
                    (0.0, 0.58, 0.0),
                    (-0.43, -0.36, 0.0),
                    (0.43, -0.36, 0.0),
                ],
                triangles=[(0, 1, 2)],
                mode='triangle',
            ),
            color=rgba(255, 255, 245, 255),
            position=(0, 0, -0.08),
            scale=(PLAYER_TRI_W, PLAYER_TRI_H),
        )

        self.monster_dots = []
        for _ in self.monsters:
            self.monster_dots.append(Entity(
                parent=self.root,
                model='circle',
                color=rgba(255, 35, 35, 255),
                position=(0, 0, -0.06),
                scale=MONSTER_DOT_SCALE,
                enabled=False,
            ))

    def ui_radius(self):
        return MINIMAP_SIZE * 0.5 * MINIMAP_INNER

    def world_to_local(self, dx, dz):
        r = self.ui_radius()
        x = dx / MINIMAP_WORLD_RANGE * r
        y = dz / MINIMAP_WORLD_RANGE * r
        return x, y

    def clamp_local(self, x, y, pad=0):
        r = max(0.001, self.ui_radius() - pad)
        d = sqrt(x * x + y * y)

        if d > r:
            k = r / max(d, 0.001)
            x *= k
            y *= k

        return x, y

    def tile_color(self):
        return rgba(150, 149, 117, FLOOR_ALPHA)

    def shaded_tile_color(self, edge_amount):
        shade = 0.36 + 0.64 * edge_amount
        alpha = int(FLOOR_ALPHA * edge_amount)
        return rgba(int(150 * shade), int(149 * shade), int(117 * shade), alpha)

    def shaded_room_color(self, edge_amount):
        shade = 0.36 + 0.64 * edge_amount
        alpha = int(ROOM_ALPHA * edge_amount)
        return rgba(int(88 * shade), int(105 * shade), int(128 * shade), alpha)

    def create_tiles(self):
        r = self.ui_radius()
        base = r * 2.0 * (self.cell / MINIMAP_WORLD_RANGE)
        s = base * FLOOR_SCALE

        for y, row in enumerate(self.layout):
            for x, v in enumerate(row):
                if v == 0:
                    tile = Entity(
                        parent=self.root,
                        model='quad',
                        color=self.tile_color(),
                        scale=(s, s),
                        position=(0, 0, 0.05),
                        enabled=False,
                    )
                    self.tiles.append((y, x, tile))
                elif (y, x) in self._door_room_set:
                    tile = Entity(
                        parent=self.root,
                        model='quad',
                        color=self.shaded_room_color(1.0),
                        scale=(s * 0.72, s * 0.72),
                        position=(0, 0, 0.04),
                        enabled=False,
                    )
                    self.room_tiles.append((y, x, tile))

        for (fr, fc), rooms in self.cell_door_rooms.items():
            for (rr, rc) in rooms:
                dr_ = rr - fr
                dc_ = rc - fc
                ind_wx = (fc + dc_ * 0.5) * self.cell
                ind_wz = (fr + dr_ * 0.5) * self.cell
                if dr_ != 0:
                    ind_scale = (s * 0.68, s * 0.22)
                else:
                    ind_scale = (s * 0.22, s * 0.68)
                indicator = Entity(
                    parent=self.root,
                    model='quad',
                    color=rgba(255, 215, 40, 220),
                    scale=ind_scale,
                    position=(0, 0, 0.03),
                    enabled=False,
                )
                self.door_indicators.append((fr, fc, ind_wx, ind_wz, indicator))

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.root.enabled = enabled

    def player_cell(self):
        return (
            int((self.player.z + self.cell / 2) // self.cell),
            int((self.player.x + self.cell / 2) // self.cell),
        )

    def scan(self):
        pr, pc = self.player_cell()

        self.scan_origin = (pr, pc)
        self.scan_wave = 0.0
        self.scan_max = SCAN_RADIUS_CELLS
        self.scanning = True
        self.pending_monster_pulse_dists = [None for _ in self.monsters]

        self.scan_pulse.enabled = True
        self.scan_pulse.scale = 0.001
        self.scan_pulse.color = rgba(178, 175, 118, 95)

        scan_x = pc * self.cell
        scan_z = pr * self.cell
        for i, monster in enumerate(self.monsters):
            monster_dx = monster.entity.x - scan_x
            monster_dz = monster.entity.z - scan_z
            monster_dist_cells = sqrt(monster_dx * monster_dx + monster_dz * monster_dz) / self.cell

            if monster_dist_cells <= SCAN_RADIUS_CELLS:
                self.has_monster_fixes[i] = True
                self.monster_fix_positions[i] = (monster.entity.x, monster.entity.z)
                self.pending_monster_pulse_dists[i] = monster_dist_cells
                self.update_monster_dot(i)

    def update_scan_wave(self):
        if not self.scanning:
            self.scan_pulse.enabled = False
            return

        pr, pc = self.scan_origin
        old_wave = self.scan_wave
        self.scan_wave += time.dt / max(0.001, SCAN_PULSE_TIME) * self.scan_max

        for r in range(pr - SCAN_RADIUS_CELLS, pr + SCAN_RADIUS_CELLS + 1):
            for c in range(pc - SCAN_RADIUS_CELLS, pc + SCAN_RADIUS_CELLS + 1):
                if r < 0 or r >= self.rows or c < 0 or c >= self.cols:
                    continue

                dr = r - pr
                dc = c - pc
                d = sqrt(dr * dr + dc * dc)

                if d <= SCAN_RADIUS_CELLS and old_wave <= d <= self.scan_wave:
                    self.revealed_cells.add((r, c))
                    for door_room in self.cell_door_rooms.get((r, c), ()):
                        self.revealed_cells.add(door_room)

        for i, pulse_dist in enumerate(self.pending_monster_pulse_dists):
            if pulse_dist is not None and pulse_dist <= self.scan_wave:
                self.monster_pulse_ts[i] = 0.0
                self.monster_pulses[i].enabled = True
                self.pending_monster_pulse_dists[i] = None

        k = min(1.0, self.scan_wave / max(0.001, self.scan_max))
        self.scan_pulse.scale = self.ui_radius() * 2.0 * k
        self.scan_pulse.color = rgba(178, 175, 118, int(95 * (1.0 - k)))

        if self.scan_wave >= self.scan_max:
            self.scanning = False
            self.scan_pulse.enabled = False

    def update_tiles(self):
        rr = self.ui_radius()

        for r, c, tile in self.tiles:
            if (r, c) not in self.revealed_cells:
                tile.enabled = False
                continue

            wx = c * self.cell
            wz = r * self.cell
            dx = wx - self.player.x
            dz = wz - self.player.z

            x, y = self.world_to_local(dx, dz)
            d = sqrt(x * x + y * y)

            if d > rr:
                tile.enabled = False
                continue

            edge_amount = min(1.0, max(0.0, (rr - d) / max(0.001, rr * EDGE_FADE)))
            tile.enabled = True
            tile.position = (x, y, tile.z)
            tile.color = self.shaded_tile_color(edge_amount)

        for r, c, tile in self.room_tiles:
            if (r, c) not in self.revealed_cells:
                tile.enabled = False
                continue

            wx = c * self.cell
            wz = r * self.cell
            dx = wx - self.player.x
            dz = wz - self.player.z

            x, y = self.world_to_local(dx, dz)
            d = sqrt(x * x + y * y)

            if d > rr:
                tile.enabled = False
                continue

            edge_amount = min(1.0, max(0.0, (rr - d) / max(0.001, rr * EDGE_FADE)))
            tile.enabled = True
            tile.position = (x, y, tile.z)
            tile.color = self.shaded_room_color(edge_amount)

        for floor_r, floor_c, ind_wx, ind_wz, indicator in self.door_indicators:
            if (floor_r, floor_c) not in self.revealed_cells:
                indicator.enabled = False
                continue

            dx = ind_wx - self.player.x
            dz = ind_wz - self.player.z
            x, y = self.world_to_local(dx, dz)
            d = sqrt(x * x + y * y)

            if d > rr:
                indicator.enabled = False
                continue

            indicator.enabled = True
            indicator.position = (x, y, indicator.z)

    def update_monster_dot(self, i):
        dot = self.monster_dots[i]
        pulse = self.monster_pulses[i]

        if not self.has_monster_fixes[i]:
            dot.enabled = False
            return

        dot.enabled = True

        fix_x, fix_z = self.monster_fix_positions[i]
        dx = fix_x - self.player.x
        dz = fix_z - self.player.z

        x, y = self.world_to_local(dx, dz)
        x, y = self.clamp_local(x, y, pad=MONSTER_DOT_SCALE * 0.8)

        dot.position = (x, y, -0.06)
        pulse.position = (x, y, -0.07)

    def update_player_marker(self):
        forward = self.player.forward
        fx = forward.x
        fz = forward.z
        length = max((fx * fx + fz * fz) ** 0.5, 0.001)
        fx /= length
        fz /= length

        self.player_marker.position = (0, 0, -0.08)
        self.player_marker.rotation_z = degrees(atan2(fx, fz))

    def update_pulse(self, pulse, t, duration, start_scale, end_scale, base_rgb, max_alpha):
        if t >= duration:
            pulse.enabled = False
            return duration

        t += time.dt
        k = min(1.0, t / duration)
        eased = 1.0 - (1.0 - k) * (1.0 - k)
        scale = start_scale + (end_scale - start_scale) * eased
        alpha = int(max_alpha * (1.0 - k))

        pulse.enabled = True
        pulse.scale = scale
        pulse.color = rgba(base_rgb[0], base_rgb[1], base_rgb[2], alpha)
        return t

    def update_monster_pulse(self, i):
        self.monster_pulse_ts[i] = self.update_pulse(
            self.monster_pulses[i],
            self.monster_pulse_ts[i],
            MONSTER_PULSE_TIME,
            MONSTER_DOT_SCALE * 1.2,
            MONSTER_DOT_SCALE * 5.5,
            (255, 35, 35),
            110,
        )

    def update(self):
        self.update_scan_wave()

        if not self.enabled:
            for i in range(len(self.monsters)):
                self.update_monster_pulse(i)
            return

        self.update_tiles()
        for i in range(len(self.monsters)):
            self.update_monster_dot(i)
            self.update_monster_pulse(i)
        self.update_player_marker()
