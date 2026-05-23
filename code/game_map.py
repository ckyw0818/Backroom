import math
from pathlib import Path

from direct.showbase import ShowBaseGlobal
from panda3d.core import Filename, NodePath
from ursina import Audio, Entity, Mesh, color, time

from textures import BASEBOARD_RGB, CEIL_RGB, FLOOR_RGB, WALL_RGB


LAYOUT = [
    [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
    [1,0,0,0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0,1],
    [1,0,1,1,0,1,0,1,0,1,1,1,0,1,0,1,0,1,0,1],
    [1,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,1],
    [1,0,1,0,1,1,0,1,1,1,0,1,1,1,0,1,0,1,0,1],
    [1,0,0,0,1,0,0,0,0,1,0,1,0,0,0,1,0,0,0,1],
    [1,1,1,0,1,0,1,0,0,0,0,0,0,1,0,1,0,1,1,1],
    [1,0,0,0,0,0,1,0,1,1,0,1,1,0,0,0,0,0,0,1],
    [1,0,1,1,1,0,0,0,1,0,0,0,1,0,1,1,1,1,0,1],
    [1,0,0,0,1,0,1,0,0,0,1,0,0,0,1,0,0,0,0,1],
    [1,1,0,0,0,0,1,1,1,0,1,0,1,1,1,0,1,0,1,1],
    [1,0,0,1,0,0,0,0,0,0,1,0,0,0,0,0,1,0,0,1],
    [1,0,1,1,0,1,1,0,1,0,0,0,1,0,1,1,0,1,0,1],
    [1,0,0,0,0,0,1,0,1,1,0,1,1,0,0,0,0,0,0,1],
    [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
]

ROWS = len(LAYOUT)
COLS = len(LAYOUT[0])
CELL = 4
WALL_H = 2.45
T = 0.42
WALL_COLLIDER_T = 0.20
BASEBOARD_H = 0.22
BASEBOARD_OUT = 0.10
ROOM_WALL_INSET = 0.08
WALL_COLLIDER_LEN = CELL - 0.28
MESH_STEPS = 6
RAY_RENDER_DISTANCE = CELL * 15
RAY_FOV_DEGREES = 120
RAY_COUNT = 180
RAY_STEP = CELL * 0.20
BUILD_PER_FRAME = 3
FLOOR_TEX_SCALE = 1.35
CEIL_TEX_SCALE = 1.35
WALL_TEX_SCALE = 1.15
BASEBOARD_TEX_SCALE = 0.55
PROJECT_DIR = Path(__file__).resolve().parent.parent
DOOR_MODEL_PATH = PROJECT_DIR / 'asset' / 'model' / 'door.glb'
DOOR_MODEL_TARGET_H = 1.92
DOOR_MODEL_TARGET_W = 1.05
DOOR_INSET = 0.08
DOOR_WALL_GAP = DOOR_MODEL_TARGET_W - 0.08
DOOR_BASEBOARD_GAP = DOOR_MODEL_TARGET_W
DOOR_THRESHOLD_W = DOOR_MODEL_TARGET_W + 0.20
DOOR_DENSITY = 11
DOOR_OPEN_ANGLE = 82
DOOR_OPEN_DISTANCE = CELL * 1.25
DOOR_OPEN_SPEED = 9.0
DOOR_INTERACT_RAY_DISTANCE = CELL * 0.7
DOOR_INTERACT_HALF_WIDTH = DOOR_MODEL_TARGET_W * 0.58
DOOR_FACE_SALTS = {
    'north': 3,
    'south': 7,
    'west': 5,
    'east': 9,
}
DOOR_FACE_ROTATIONS = {
    'north': 0,
    'south': 180,
    'west': 90,
    'east': -90,
}
DOOR_OPEN_SIGN = 1
DOOR_MODEL_ROOT = 'Null'
DOOR_MOVING_NODES = ('door',)



class MapRenderer:
    def __init__(self, player, light_system, textures):
        self.player = player
        self.light_system = light_system
        self.textures = textures
        self.prebuilt_cells = {}
        self.prebuilt_rooms = {}
        self.prebuilt_lights = {}
        self._visible_cells = set()
        self._visible_rooms = set()
        self._visible_lights = set()
        self.door_states = {}
        self.active_doors = {}
        self.door_model = self.load_door_model()
        self.door_model_scale = self.fit_door_model_scale(self.door_model)
        self.door_open_sound = Audio('asset/sound/door_open.wav', autoplay=False, volume=0.5)
        self.door_close_sound = Audio('asset/sound/door_close.wav', autoplay=False, volume=0.68)

        self.walkable_cells = {
            (r, c)
            for r in range(ROWS)
            for c in range(COLS)
            if LAYOUT[r][c] == 0
        }

        self._door_set = frozenset(
            (r, c, face)
            for r in range(ROWS) for c in range(COLS)
            if LAYOUT[r][c] == 0
            for face in ('north', 'south', 'west', 'east')
            if not (r <= 1 and c <= 2)
            and (r * 17 + c * 31 + DOOR_FACE_SALTS[face]) % DOOR_DENSITY == 0
        )

        self._cell_door_rooms = {}
        for _r, _c in self.walkable_cells:
            _rooms = set()
            for _face in ('north', 'south', 'west', 'east'):
                if (_r, _c, _face) not in self._door_set:
                    continue
                (_rr, _rc), _ = self.door_room_for_face(_r, _c, _face)
                if 0 <= _rr < ROWS and 0 <= _rc < COLS and LAYOUT[_rr][_rc] == 1:
                    _rooms.add((_rr, _rc))
            if _rooms:
                self._cell_door_rooms[(_r, _c)] = _rooms

        self._raycast_cache_key = None

        self.floor_collider = Entity(
            model='cube',
            visible=False,
            position=((COLS - 1) * CELL / 2, -0.06, (ROWS - 1) * CELL / 2),
            scale=(COLS * CELL, 0.1, ROWS * CELL),
            collider='box',
        )

    def load_door_model(self):
        scene = ShowBaseGlobal.base.loader.loadModel(Filename.fromOsSpecific(str(DOOR_MODEL_PATH)))

        if scene.isEmpty():
            raise RuntimeError(f'Failed to load door model: {DOOR_MODEL_PATH}')

        keep = scene.find(f'**/{DOOR_MODEL_ROOT}')
        if keep.isEmpty():
            raise RuntimeError(f'Door root not found: {DOOR_MODEL_ROOT}')

        model = NodePath('door_template')
        keep.copyTo(model)
        scene.removeNode()

        self.prepare_door_model(model)
        return model

    def prepare_door_model(self, model):
        model.setTwoSided(True)
        self.attach_door_handles(model)

        for np in model.findAllMatches('**'):
            if np.isEmpty():
                continue

            np.setTwoSided(True)

    def attach_door_handles(self, model):
        for door_name, handle_name in (('door', 'handel'), ('door_2', 'handel_2')):
            door = model.find(f'**/{door_name}')
            handle = model.find(f'**/{handle_name}')

            if door.isEmpty() or handle.isEmpty() or handle.getParent() == door:
                continue

            handle.wrtReparentTo(door)

    def fit_door_model_scale(self, model):
        bounds = model.getTightBounds()

        if not bounds:
            return 1.0

        mn, mx = bounds
        height = max(mx.z - mn.z, mx.y - mn.y, 0.001)
        width = max(mx.x - mn.x, 0.001)
        return min(DOOR_MODEL_TARGET_H / height, DOOR_MODEL_TARGET_W / width)

    def player_cell(self):
        return (
            int((self.player.z + CELL / 2) // CELL),
            int((self.player.x + CELL / 2) // CELL),
        )

    def effective_player_cell(self):
        cell = self.player_cell()
        if cell in self.walkable_cells:
            return cell
        r, c = cell
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            neighbor = (r + dr, c + dc)
            if neighbor in self.walkable_cells:
                return neighbor
        return cell

    def cells_near(self, center, radius):
        cr, cc = center
        cells = set()
        layout = LAYOUT
        r0 = max(0, cr - radius)
        r1 = min(ROWS, cr + radius + 1)
        c0 = max(0, cc - radius)
        c1 = min(COLS, cc + radius + 1)

        for r in range(r0, r1):
            ar = abs(r - cr)
            for c in range(c0, c1):
                if layout[r][c] == 0 and max(ar, abs(c - cc)) <= radius:
                    cells.add((r, c))

        return cells

    def expand_cells(self, cells, radius=1):
        out = set(cells)

        for cr, cc in cells:
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    r = cr + dr
                    c = cc + dc

                    if 0 <= r < ROWS and 0 <= c < COLS and LAYOUT[r][c] == 0:
                        out.add((r, c))

        return out

    def cell_center(self, cell):
        r, c = cell
        return c * CELL, r * CELL

    def door_room_for_face(self, r, c, face):
        if face == 'north':
            return (r - 1, c), 'south'
        if face == 'south':
            return (r + 1, c), 'north'
        if face == 'west':
            return (r, c - 1), 'east'
        return (r, c + 1), 'west'

    def room_openings(self, room_cell):
        rr, rc = room_cell
        openings = set()

        checks = (
            (rr + 1, rc, 'north', 'south'),
            (rr - 1, rc, 'south', 'north'),
            (rr, rc + 1, 'west', 'east'),
            (rr, rc - 1, 'east', 'west'),
        )

        for r, c, door_face, room_face in checks:
            if 0 <= r < ROWS and 0 <= c < COLS and LAYOUT[r][c] == 0 and self.should_add_door(r, c, door_face):
                openings.add(room_face)

        return openings

    def room_candidates_for_cells(self, cells):
        rooms = set()
        cell_door_rooms = self._cell_door_rooms
        for cell in cells:
            entry = cell_door_rooms.get(cell)
            if entry:
                rooms |= entry
        return rooms

    def player_forward_xz(self):
        forward = self.player.forward
        fx = forward.x
        fz = forward.z
        length = max((fx * fx + fz * fz) ** 0.5, 0.001)
        return fx / length, fz / length

    def visible_cells_raycast(self, center):
        if center not in self.walkable_cells:
            return set()

        visible = {center}
        fx, fz = self.player_forward_xz()
        half_fov = RAY_FOV_DEGREES * 0.5
        ray_count = max(1, RAY_COUNT)
        max_dist = RAY_RENDER_DISTANCE
        layout = LAYOUT
        half_cell = CELL * 0.5
        door_set = self._door_set

        ray_ox, ray_oz = self.player.x, self.player.z

        for i in range(ray_count):
            if ray_count == 1:
                angle = 0.0
            else:
                angle = -half_fov + (RAY_FOV_DEGREES * i / (ray_count - 1))

            rad = math.radians(angle)
            ca = math.cos(rad)
            sa = math.sin(rad)
            dx = fx * ca - fz * sa
            dz = fx * sa + fz * ca

            r = int((ray_oz + half_cell) // CELL)
            c = int((ray_ox + half_cell) // CELL)

            step_c = 1 if dx >= 0 else -1
            step_r = 1 if dz >= 0 else -1

            if abs(dx) < 1e-9:
                t_max_x = float('inf')
                t_delta_x = float('inf')
                face_x = 'east'
            else:
                t_max_x = ((c + (0.5 if dx > 0 else -0.5)) * CELL - ray_ox) / dx
                t_delta_x = CELL / abs(dx)
                face_x = 'east' if dx > 0 else 'west'

            if abs(dz) < 1e-9:
                t_max_z = float('inf')
                t_delta_z = float('inf')
                face_z = 'south'
            else:
                t_max_z = ((r + (0.5 if dz > 0 else -0.5)) * CELL - ray_oz) / dz
                t_delta_z = CELL / abs(dz)
                face_z = 'south' if dz > 0 else 'north'

            if 0 <= r < ROWS and 0 <= c < COLS:
                if layout[r][c] == 0:
                    visible.add((r, c))
                else:
                    for _ndr in range(-1, 2):
                        for _ndc in range(-1, 2):
                            _nr, _nc = r + _ndr, c + _ndc
                            if 0 <= _nr < ROWS and 0 <= _nc < COLS and layout[_nr][_nc] == 0:
                                visible.add((_nr, _nc))

            prev_r, prev_c, prev_face = r, c, face_x

            while True:
                if t_max_x <= t_max_z:
                    if t_max_x >= max_dist:
                        break
                    prev_r, prev_c, prev_face = r, c, face_x
                    t_max_x += t_delta_x
                    c += step_c
                else:
                    if t_max_z >= max_dist:
                        break
                    prev_r, prev_c, prev_face = r, c, face_z
                    t_max_z += t_delta_z
                    r += step_r

                if r < 0 or r >= ROWS or c < 0 or c >= COLS:
                    break

                if layout[r][c] == 1:
                    for dr in range(-1, 2):
                        for dc in range(-1, 2):
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < ROWS and 0 <= nc < COLS and layout[nr][nc] == 0:
                                visible.add((nr, nc))
                    if layout[prev_r][prev_c] == 0 and (prev_r, prev_c, prev_face) in door_set:
                        pass  # 도어 면 - ray가 도어룸 안으로 진입
                    else:
                        break  # 일반 벽 면 - 중단
                else:
                    visible.add((r, c))

        return self.expand_cells(visible, 1)

    def new_mesh_data(self):
        textures = self.textures

        return {
            'floor': {'vertices': [], 'triangles': [], 'uvs': [], 'colors': [], 'texture': textures['floor']},
            'ceil': {'vertices': [], 'triangles': [], 'uvs': [], 'colors': [], 'texture': textures['ceil']},
            'wall': {'vertices': [], 'triangles': [], 'uvs': [], 'colors': [], 'texture': textures['wall']},
            'baseboard': {'vertices': [], 'triangles': [], 'uvs': [], 'colors': [], 'texture': textures['baseboard']},
        }

    def add_quad(self, mesh_data, kind, vertices, uvs, base_rgb, near_lights):
        data = mesh_data[kind]
        start = len(data['vertices'])
        data['vertices'].extend(vertices)

        tris = data['triangles']
        tris.extend((start, start + 1, start + 2, start, start + 2, start + 3))

        if kind == 'wall' or kind == 'baseboard':
            tris.extend((start + 2, start + 1, start, start + 3, start + 2, start))

        data['uvs'].extend(uvs)

        ls = self.light_system
        light_at = ls.light_at
        shaded_color = ls.shaded_color
        colors = data['colors']
        min_light = {
            'floor': 0.085,
            'ceil': 0.075,
            'baseboard': 0.065,
        }.get(kind, 0.055)

        for x, y, z in vertices:
            colors.append(shaded_color(base_rgb, light_at(x, y, z, near_lights, kind), min_light))

    def add_subdivided_floor_region(self, mesh_data, x0, z0, x1, z1, near_lights):
        steps = MESH_STEPS
        width = x1 - x0
        depth = z1 - z0

        for iz in range(steps):
            za = z0 + depth * iz / steps
            zb = z0 + depth * (iz + 1) / steps

            for ix in range(steps):
                xa = x0 + width * ix / steps
                xb = x0 + width * (ix + 1) / steps

                self.add_quad(
                    mesh_data,
                    'floor',
                    [(xa, 0, za), (xb, 0, za), (xb, 0, zb), (xa, 0, zb)],
                    [
                        (xa / FLOOR_TEX_SCALE, za / FLOOR_TEX_SCALE),
                        (xb / FLOOR_TEX_SCALE, za / FLOOR_TEX_SCALE),
                        (xb / FLOOR_TEX_SCALE, zb / FLOOR_TEX_SCALE),
                        (xa / FLOOR_TEX_SCALE, zb / FLOOR_TEX_SCALE),
                    ],
                    FLOOR_RGB,
                    near_lights,
                )

                self.add_quad(
                    mesh_data,
                    'ceil',
                    [(xa, WALL_H, zb), (xb, WALL_H, zb), (xb, WALL_H, za), (xa, WALL_H, za)],
                    [
                        (xa / CEIL_TEX_SCALE, zb / CEIL_TEX_SCALE),
                        (xb / CEIL_TEX_SCALE, zb / CEIL_TEX_SCALE),
                        (xb / CEIL_TEX_SCALE, za / CEIL_TEX_SCALE),
                        (xa / CEIL_TEX_SCALE, za / CEIL_TEX_SCALE),
                    ],
                    CEIL_RGB,
                    near_lights,
                )

    def add_subdivided_floor(self, mesh_data, r, c, near_lights):
        x0 = c * CELL - CELL / 2
        z0 = r * CELL - CELL / 2
        self.add_subdivided_floor_region(mesh_data, x0, z0, x0 + CELL, z0 + CELL, near_lights)

    def add_wall_face(self, mesh_data, x0, z0, x1, z1, near_lights, y_bottom=0, y_top=None):
        if y_top is None:
            y_top = WALL_H
        dx = x1 - x0
        dz = z1 - z0
        wall_len = max((dx * dx + dz * dz) ** 0.5, 0.001)
        steps = MESH_STEPS
        h = y_top - y_bottom

        for i in range(steps):
            a0 = i / steps
            a1 = (i + 1) / steps

            xa = x0 + dx * a0
            za = z0 + dz * a0
            xb = x0 + dx * a1
            zb = z0 + dz * a1

            u0 = wall_len * a0 / WALL_TEX_SCALE
            u1 = wall_len * a1 / WALL_TEX_SCALE

            for j in range(steps):
                y0 = y_bottom + h * j / steps
                y1 = y_bottom + h * (j + 1) / steps
                v0 = y0 / WALL_TEX_SCALE
                v1 = y1 / WALL_TEX_SCALE

                self.add_quad(
                    mesh_data,
                    'wall',
                    [(xa, y0, za), (xb, y0, zb), (xb, y1, zb), (xa, y1, za)],
                    [(u0, v0), (u1, v0), (u1, v1), (u0, v1)],
                    WALL_RGB,
                    near_lights,
                )

    def add_baseboard_face(self, mesh_data, x0, z0, x1, z1, out_x, out_z, near_lights, extend_ends=True):
        steps = MESH_STEPS
        dx = x1 - x0
        dz = z1 - z0
        length = max((dx * dx + dz * dz) ** 0.5, 0.001)
        dir_x = dx / length
        dir_z = dz / length

        if extend_ends:
            x0 -= dir_x * BASEBOARD_OUT
            z0 -= dir_z * BASEBOARD_OUT
            x1 += dir_x * BASEBOARD_OUT
            z1 += dir_z * BASEBOARD_OUT

        dx = x1 - x0
        dz = z1 - z0

        for i in range(steps):
            a0 = i / steps
            a1 = (i + 1) / steps

            back_a_x = x0 + dx * a0
            back_a_z = z0 + dz * a0
            back_b_x = x0 + dx * a1
            back_b_z = z0 + dz * a1

            front_a_x = back_a_x + out_x
            front_a_z = back_a_z + out_z
            front_b_x = back_b_x + out_x
            front_b_z = back_b_z + out_z

            u0 = length * a0 / BASEBOARD_TEX_SCALE
            u1 = length * a1 / BASEBOARD_TEX_SCALE
            vh = BASEBOARD_H / BASEBOARD_TEX_SCALE
            vo = BASEBOARD_OUT / BASEBOARD_TEX_SCALE

            self.add_quad(
                mesh_data,
                'baseboard',
                [
                    (front_a_x, 0, front_a_z),
                    (front_b_x, 0, front_b_z),
                    (front_b_x, BASEBOARD_H, front_b_z),
                    (front_a_x, BASEBOARD_H, front_a_z),
                ],
                [(u0, 0), (u1, 0), (u1, vh), (u0, vh)],
                BASEBOARD_RGB,
                near_lights,
            )

            self.add_quad(
                mesh_data,
                'baseboard',
                [
                    (back_a_x, BASEBOARD_H, back_a_z),
                    (back_b_x, BASEBOARD_H, back_b_z),
                    (front_b_x, BASEBOARD_H, front_b_z),
                    (front_a_x, BASEBOARD_H, front_a_z),
                ],
                [(u0, 0), (u1, 0), (u1, vo), (u0, vo)],
                BASEBOARD_RGB,
                near_lights,
            )

        vh = BASEBOARD_H / BASEBOARD_TEX_SCALE
        vo = BASEBOARD_OUT / BASEBOARD_TEX_SCALE

        for end_x, end_z, sign in ((x0, z0, 0), (x1, z1, 1)):
            front_x = end_x + out_x
            front_z = end_z + out_z

            self.add_quad(
                mesh_data,
                'baseboard',
                [
                    (end_x, 0, end_z),
                    (front_x, 0, front_z),
                    (front_x, BASEBOARD_H, front_z),
                    (end_x, BASEBOARD_H, end_z),
                ],
                [(sign, 0), (sign + vo, 0), (sign + vo, vh), (sign, vh)],
                BASEBOARD_RGB,
                near_lights,
            )

    def add_wall_with_baseboard(self, mesh_data, x0, z0, x1, z1, out_x, out_z, near_lights, extend_baseboard=True):
        self.add_wall_face(mesh_data, x0, z0, x1, z1, near_lights)
        self.add_baseboard_face(mesh_data, x0, z0, x1, z1, out_x, out_z, near_lights, extend_baseboard)

    def add_wall_with_baseboard_gap(self, mesh_data, x0, z0, x1, z1, out_x, out_z, near_lights, extend_baseboard=True):
        dx = x1 - x0
        dz = z1 - z0
        length = max((dx * dx + dz * dz) ** 0.5, 0.001)

        def at(t):
            return x0 + dx * t, z0 + dz * t

        # wall: left and right strips (full height) + top center above door
        wg = min(0.92, DOOR_WALL_GAP / length)
        wg0 = max(0.0, 0.5 - wg / 2)
        wg1 = min(1.0, 0.5 + wg / 2)

        if wg0 > 0.01:
            self.add_wall_face(mesh_data, x0, z0, *at(wg0), near_lights)
        if wg1 < 0.99:
            self.add_wall_face(mesh_data, *at(wg1), x1, z1, near_lights)
        self.add_wall_face(mesh_data, *at(wg0), *at(wg1), near_lights, y_bottom=DOOR_MODEL_TARGET_H)

        # baseboard: left and right of door (slightly wider gap)
        gap = min(0.92, DOOR_BASEBOARD_GAP / length)
        gap0 = max(0.0, 0.5 - gap / 2)
        gap1 = min(1.0, 0.5 + gap / 2)

        if gap0 > 0.02:
            ax, az = at(0.0)
            bx, bz = at(gap0)
            self.add_baseboard_face(mesh_data, ax, az, bx, bz, out_x, out_z, near_lights, extend_baseboard)

        if gap1 < 0.98:
            ax, az = at(gap1)
            bx, bz = at(1.0)
            self.add_baseboard_face(mesh_data, ax, az, bx, bz, out_x, out_z, near_lights, extend_baseboard)

    def add_wall_with_door_gap(self, mesh_data, x0, z0, x1, z1, near_lights):
        dx = x1 - x0
        dz = z1 - z0
        length = max((dx * dx + dz * dz) ** 0.5, 0.001)

        def at(t):
            return x0 + dx * t, z0 + dz * t

        wg = min(0.92, DOOR_WALL_GAP / length)
        wg0 = max(0.0, 0.5 - wg / 2)
        wg1 = min(1.0, 0.5 + wg / 2)

        if wg0 > 0.01:
            self.add_wall_face(mesh_data, x0, z0, *at(wg0), near_lights)
        if wg1 < 0.99:
            self.add_wall_face(mesh_data, *at(wg1), x1, z1, near_lights)
        self.add_wall_face(mesh_data, *at(wg0), *at(wg1), near_lights, y_bottom=DOOR_MODEL_TARGET_H)

    def add_room_door_threshold(self, mesh_data, cx, cz, face, west_x, north_z, east_x, south_z, near_lights):
        half_gap = min(DOOR_THRESHOLD_W, CELL - ROOM_WALL_INSET * 2) * 0.5

        if face in ('north', 'south'):
            x0 = max(west_x, cx - half_gap)
            x1 = min(east_x, cx + half_gap)

            if face == 'north':
                z0 = cz - CELL / 2
                z1 = north_z
            else:
                z0 = south_z
                z1 = cz + CELL / 2
        else:
            z0 = max(north_z, cz - half_gap)
            z1 = min(south_z, cz + half_gap)

            if face == 'west':
                x0 = cx - CELL / 2
                x1 = west_x
            else:
                x0 = east_x
                x1 = cx + CELL / 2

        if x1 - x0 > 0.01 and z1 - z0 > 0.01:
            self.add_subdivided_floor_region(mesh_data, x0, z0, x1, z1, near_lights)

    def add_wall_collider(self, pos, sc):
        return Entity(model='cube', visible=False, position=pos, scale=sc, collider='box')

    def add_door_wall_colliders(self, entities, x, z, face):
        gap = min(DOOR_MODEL_TARGET_W + 0.18, CELL - 0.36)
        side_len = max((WALL_COLLIDER_LEN - gap) * 0.5, 0.05)
        side_offset = gap * 0.5 + side_len * 0.5

        if face in ('north', 'south'):
            wall_z = z - CELL / 2 if face == 'north' else z + CELL / 2
            side_scale = (side_len, WALL_H, WALL_COLLIDER_T)

            entities.append(self.add_wall_collider((x - side_offset, WALL_H / 2, wall_z), side_scale))
            entities.append(self.add_wall_collider((x + side_offset, WALL_H / 2, wall_z), side_scale))
            return self.add_wall_collider((x, WALL_H / 2, wall_z), (gap, WALL_H, WALL_COLLIDER_T))

        wall_x = x - CELL / 2 if face == 'west' else x + CELL / 2
        side_scale = (WALL_COLLIDER_T, WALL_H, side_len)

        entities.append(self.add_wall_collider((wall_x, WALL_H / 2, z - side_offset), side_scale))
        entities.append(self.add_wall_collider((wall_x, WALL_H / 2, z + side_offset), side_scale))
        return self.add_wall_collider((wall_x, WALL_H / 2, z), (WALL_COLLIDER_T, WALL_H, gap))

    def build_door_room(self, room_cell):
        cr, cc = room_cell
        skip_faces = self.room_openings(room_cell)

        if not skip_faces:
            return []

        cx = cc * CELL
        cz = cr * CELL
        closet_light = (cx, WALL_H - 0.16, cz)
        lit_near = [closet_light]
        mesh_data = self.new_mesh_data()
        entities = []

        north_z = cz - CELL / 2 + ROOM_WALL_INSET
        south_z = cz + CELL / 2 - ROOM_WALL_INSET
        west_x = cx - CELL / 2 + ROOM_WALL_INSET
        east_x = cx + CELL / 2 - ROOM_WALL_INSET
        wall_len = CELL - ROOM_WALL_INSET * 2

        self.add_subdivided_floor_region(mesh_data, west_x, north_z, east_x, south_z, lit_near)

        if 'north' not in skip_faces:
            self.add_wall_face(mesh_data, west_x, north_z, east_x, north_z, lit_near)
            entities.append(self.add_wall_collider((cx, WALL_H/2, north_z), (wall_len, WALL_H, WALL_COLLIDER_T)))
        else:
            self.add_wall_with_door_gap(mesh_data, west_x, north_z, east_x, north_z, lit_near)
            self.add_room_door_threshold(mesh_data, cx, cz, 'north', west_x, north_z, east_x, south_z, lit_near)

        if 'south' not in skip_faces:
            self.add_wall_face(mesh_data, east_x, south_z, west_x, south_z, lit_near)
            entities.append(self.add_wall_collider((cx, WALL_H/2, south_z), (wall_len, WALL_H, WALL_COLLIDER_T)))
        else:
            self.add_wall_with_door_gap(mesh_data, east_x, south_z, west_x, south_z, lit_near)
            self.add_room_door_threshold(mesh_data, cx, cz, 'south', west_x, north_z, east_x, south_z, lit_near)

        if 'west' not in skip_faces:
            self.add_wall_face(mesh_data, west_x, south_z, west_x, north_z, lit_near)
            entities.append(self.add_wall_collider((west_x, WALL_H/2, cz), (WALL_COLLIDER_T, WALL_H, wall_len)))
        else:
            self.add_wall_with_door_gap(mesh_data, west_x, south_z, west_x, north_z, lit_near)
            self.add_room_door_threshold(mesh_data, cx, cz, 'west', west_x, north_z, east_x, south_z, lit_near)

        if 'east' not in skip_faces:
            self.add_wall_face(mesh_data, east_x, north_z, east_x, south_z, lit_near)
            entities.append(self.add_wall_collider((east_x, WALL_H/2, cz), (WALL_COLLIDER_T, WALL_H, wall_len)))
        else:
            self.add_wall_with_door_gap(mesh_data, east_x, north_z, east_x, south_z, lit_near)
            self.add_room_door_threshold(mesh_data, cx, cz, 'east', west_x, north_z, east_x, south_z, lit_near)

        for data in mesh_data.values():
            entity = self.add_mesh_entity(data)
            if entity:
                entities.append(entity)

        entities.append(Entity(
            model='cube',
            color=color.Color(1.0, 0.98, 0.92, 1.0),
            unlit=True,
            position=(cx, WALL_H - 0.035, cz),
            scale=(0.8, 0.025, 0.8),
        ))

        return entities

    def should_add_door(self, r, c, face):
        return (r, c, face) in self._door_set

    def door_key(self, r, c, face):
        return r, c, face

    def door_world_position(self, x, z, face):
        if face == 'north':
            return x, 0, z - CELL / 2 + DOOR_INSET
        if face == 'south':
            return x, 0, z + CELL / 2 - DOOR_INSET
        if face == 'west':
            return x - CELL / 2 + DOOR_INSET, 0, z
        return x + CELL / 2 - DOOR_INSET, 0, z

    def door_moving_nodes(self, entity):
        out = []

        for name in DOOR_MOVING_NODES:
            node = entity.find(f'**/{name}')
            if node and not node.isEmpty():
                out.append((node, node.getH()))

        return out

    def add_door_decoration(self, entities, x, z, face, near_lights, wall_collider=None):
        key = self.door_key(round(z / CELL), round(x / CELL), face)
        pos = self.door_world_position(x, z, face)
        rotation_y = DOOR_FACE_ROTATIONS[face]
        open_amount = 1.0 if self.door_states.get(key, False) else 0.0

        light_val = self.light_system.light_at(pos[0], WALL_H * 0.5, pos[2], near_lights)
        tint = self.light_system.shaded_color(WALL_RGB, light_val)
        entity = Entity(
            position=pos,
            rotation=(0, rotation_y, 0),
            scale=self.door_model_scale,
        )

        model = self.door_model.copyTo(entity)
        self.prepare_door_model(model)
        model.setColorScale(tint.r, tint.g, tint.b, 1.0)
        moving_nodes = self.door_moving_nodes(entity)

        for node, base_h in moving_nodes:
            node.setH(base_h + DOOR_OPEN_SIGN * DOOR_OPEN_ANGLE * open_amount)

        if wall_collider and open_amount > 0.5:
            wall_collider.collider = None

        entities.append(entity)
        self.active_doors[key] = {
            'entity': entity,
            'moving_nodes': moving_nodes,
            'open': open_amount,
            'target': open_amount,
            'face': face,
            'position': pos,
            'wall_collider': wall_collider,
        }

    def toggle_nearest_door(self):
        nearest_key = None
        nearest_t = DOOR_INTERACT_RAY_DISTANCE
        ray_x, ray_z = self.player_forward_xz()

        for key, door in self.active_doors.items():
            x, _, z = door['position']
            dx = x - self.player.x
            dz = z - self.player.z
            t = dx * ray_x + dz * ray_z

            if t < 0 or t > nearest_t:
                continue

            perp = abs(dx * ray_z - dz * ray_x)

            if perp > DOOR_INTERACT_HALF_WIDTH:
                continue

            nearest_key = key
            nearest_t = t

        if nearest_key is None:
            return False

        is_open = self.door_states.get(nearest_key, False)
        self.door_states[nearest_key] = not is_open
        self.active_doors[nearest_key]['target'] = 1.0 if not is_open else 0.0

        sound = self.door_close_sound if is_open else self.door_open_sound
        sound.stop()

        if not is_open:
            sound.play(start=0.3)
        else:
            sound.play()

        return True

    def update_doors(self):
        for key, door in list(self.active_doors.items()):
            target = 1.0 if self.door_states.get(key, False) else 0.0
            current = door['open'] + (target - door['open']) * min(1.0, time.dt * DOOR_OPEN_SPEED)
            door['open'] = current
            door['target'] = target

            for node, base_h in door['moving_nodes']:
                node.setH(base_h + DOOR_OPEN_SIGN * DOOR_OPEN_ANGLE * current)

            collider = door.get('wall_collider')
            if collider:
                if current > 0.5 and collider.collider is not None:
                    collider.collider = None
                elif current <= 0.5 and collider.collider is None:
                    collider.collider = 'box'

    def add_mesh_entity(self, data):
        if not data['vertices']:
            return None

        entity = Entity(
            model=Mesh(
                vertices=data['vertices'],
                triangles=data['triangles'],
                uvs=data['uvs'],
                colors=data['colors'],
                mode='triangle',
            ),
            unlit=True,
        )
        entity.model.setTexture(data['texture'], 1)
        return entity

    def build_cell(self, r, c):
        if r < 0 or r >= ROWS or c < 0 or c >= COLS or LAYOUT[r][c] != 0:
            return []

        entities = []
        mesh_data = self.new_mesh_data()
        x = c * CELL
        z = r * CELL
        near_lights = self.light_system.cell_cache.get((r, c), self.light_system.positions)
        layout = LAYOUT

        self.add_subdivided_floor(mesh_data, r, c, near_lights)

        if r == 0 or layout[r - 1][c] == 1:
            has_door = self.should_add_door(r, c, 'north')
            add_wall = self.add_wall_with_baseboard_gap if has_door else self.add_wall_with_baseboard
            add_wall(
                mesh_data,
                x - CELL / 2,
                z - CELL / 2,
                x + CELL / 2,
                z - CELL / 2,
                0,
                BASEBOARD_OUT,
                near_lights,
                not has_door,
            )
            if has_door:
                wc = self.add_door_wall_colliders(entities, x, z, 'north')
                entities.append(wc)
                self.add_door_decoration(entities, x, z, 'north', near_lights, wc)
            else:
                entities.append(self.add_wall_collider((x, WALL_H / 2, z - CELL / 2), (WALL_COLLIDER_LEN, WALL_H, WALL_COLLIDER_T)))

        if r == ROWS - 1 or layout[r + 1][c] == 1:
            has_door = self.should_add_door(r, c, 'south')
            add_wall = self.add_wall_with_baseboard_gap if has_door else self.add_wall_with_baseboard
            add_wall(
                mesh_data,
                x + CELL / 2,
                z + CELL / 2,
                x - CELL / 2,
                z + CELL / 2,
                0,
                -BASEBOARD_OUT,
                near_lights,
                not has_door,
            )
            if has_door:
                wc = self.add_door_wall_colliders(entities, x, z, 'south')
                entities.append(wc)
                self.add_door_decoration(entities, x, z, 'south', near_lights, wc)
            else:
                entities.append(self.add_wall_collider((x, WALL_H / 2, z + CELL / 2), (WALL_COLLIDER_LEN, WALL_H, WALL_COLLIDER_T)))

        if c == 0 or layout[r][c - 1] == 1:
            has_door = self.should_add_door(r, c, 'west')
            add_wall = self.add_wall_with_baseboard_gap if has_door else self.add_wall_with_baseboard
            add_wall(
                mesh_data,
                x - CELL / 2,
                z + CELL / 2,
                x - CELL / 2,
                z - CELL / 2,
                BASEBOARD_OUT,
                0,
                near_lights,
                not has_door,
            )
            if has_door:
                wc = self.add_door_wall_colliders(entities, x, z, 'west')
                entities.append(wc)
                self.add_door_decoration(entities, x, z, 'west', near_lights, wc)
            else:
                entities.append(self.add_wall_collider((x - CELL / 2, WALL_H / 2, z), (WALL_COLLIDER_T, WALL_H, WALL_COLLIDER_LEN)))

        if c == COLS - 1 or layout[r][c + 1] == 1:
            has_door = self.should_add_door(r, c, 'east')
            add_wall = self.add_wall_with_baseboard_gap if has_door else self.add_wall_with_baseboard
            add_wall(
                mesh_data,
                x + CELL / 2,
                z - CELL / 2,
                x + CELL / 2,
                z + CELL / 2,
                -BASEBOARD_OUT,
                0,
                near_lights,
                not has_door,
            )
            if has_door:
                wc = self.add_door_wall_colliders(entities, x, z, 'east')
                entities.append(wc)
                self.add_door_decoration(entities, x, z, 'east', near_lights, wc)
            else:
                entities.append(self.add_wall_collider((x + CELL / 2, WALL_H / 2, z), (WALL_COLLIDER_T, WALL_H, WALL_COLLIDER_LEN)))

        for data in mesh_data.values():
            entity = self.add_mesh_entity(data)
            if entity:
                entities.append(entity)

        return entities

    def update_rendered_scene(self, force=False):
        current = self.effective_player_cell()
        fx, fz = self.player_forward_xz()
        cache_key = (int(self.player.x * 2), int(self.player.z * 2), int(fx * 40), int(fz * 40))

        if not force and cache_key == self._raycast_cache_key:
            return

        self._raycast_cache_key = cache_key
        wanted_cells = self.visible_cells_raycast(current)
        wanted_rooms = self.room_candidates_for_cells(wanted_cells)
        wanted_lights = wanted_cells & self.light_system.cell_set

        for cell in self._visible_cells - wanted_cells:
            for entity in self.prebuilt_cells.get(cell, []):
                entity.enabled = False

        for cell in wanted_cells - self._visible_cells:
            for entity in self.prebuilt_cells.get(cell, []):
                entity.enabled = True

        for room_cell in self._visible_rooms - wanted_rooms:
            for entity in self.prebuilt_rooms.get(room_cell, []):
                entity.enabled = False

        for room_cell in wanted_rooms - self._visible_rooms:
            for entity in self.prebuilt_rooms.get(room_cell, []):
                entity.enabled = True

        for cell in self._visible_lights - wanted_lights:
            for entity in self.prebuilt_lights.get(cell, []):
                entity.enabled = False

        for cell in wanted_lights - self._visible_lights:
            for entity in self.prebuilt_lights.get(cell, []):
                entity.enabled = True

        self._visible_cells = wanted_cells
        self._visible_rooms = wanted_rooms
        self._visible_lights = wanted_lights

    def process_queues(self):
        pass

    def initial_render(self):
        all_room_cells = set()
        for r in range(ROWS):
            for c in range(COLS):
                if LAYOUT[r][c] != 0:
                    continue
                entities = self.build_cell(r, c)
                self.prebuilt_cells[(r, c)] = entities
                for entity in entities:
                    entity.enabled = False
                for room_cell in self._cell_door_rooms.get((r, c), set()):
                    all_room_cells.add(room_cell)

        for room_cell in all_room_cells:
            entities = self.build_door_room(room_cell)
            self.prebuilt_rooms[room_cell] = entities
            for entity in entities:
                entity.enabled = False

        for cell in self.light_system.cell_set:
            r, c = cell
            entities = self.light_system.add_fixture(r, c)
            self.prebuilt_lights[cell] = entities
            for entity in entities:
                entity.enabled = False

        self.update_rendered_scene(force=True)
