import math
import random

from direct.showbase import ShowBaseGlobal
from panda3d.core import Filename, NodePath, TransparencyAttrib
from ursina import Audio, Entity, Text, color, time

from furniture.bed import BedMixin
from furniture.drawer import DrawerMixin
from map.map_data import (
    CELL,
    COLS,
    LAYOUT,
    PROJECT_DIR,
    ROOM_WALL_INSET,
    ROWS,
    WALL_COLLIDER_LEN,
    WALL_COLLIDER_T,
    WALL_H,
)
from utill.textures import WALL_RGB


DOOR_MODEL_PATH = PROJECT_DIR / 'asset' / 'model' / 'door.glb'
DOOR_MODEL_TARGET_H = 1.92
DOOR_MODEL_TARGET_W = 1.05
DOOR_INSET = 0.08
DOOR_WALL_GAP = DOOR_MODEL_TARGET_W - 0.08
DOOR_BASEBOARD_GAP = DOOR_MODEL_TARGET_W
DOOR_COLLIDER_GAP = DOOR_MODEL_TARGET_W + 0.70
DOOR_THRESHOLD_W = DOOR_MODEL_TARGET_W + 0.20
DOOR_DENSITY = 35
DOOR_OPEN_ANGLE = 82
DOOR_OPEN_SPEED = 6.0
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
DOOR_RATTLE_DURATION = 0.42
DOOR_RATTLE_SWINGS = 2
DOOR_RATTLE_ANGLE = 1
DOOR_UNLOCK_OPEN_DELAY = 2.8

EXIT_SIGN_MODEL_PATH = PROJECT_DIR / 'asset' / 'model' / 'exit_sign.glb'
EXIT_SIGN_TARGET_W = 0.60
EXIT_SIGN_TARGET_H = 0.30

KEYPAD_MODEL_PATH = PROJECT_DIR / 'asset' / 'model' / 'keypad2.glb'
KEYPAD_TARGET_H = 0.385
KEYPAD_RIGHT_OFFSET = 0.86
KEYPAD_WALL_OFFSET = 0.13
KEYPAD_CENTER_Y = 1.25
KEYPAD_CODE = '12345'
KEYPAD_INTERACT_RAY_DISTANCE = CELL * 0.6
KEYPAD_PRESS_DEPTH = 0.10
KEYPAD_PRESS_TIME = 0.16
KEYPAD_RESULT_SOUND_DELAY = 0.8
KEYPAD_DISPLAY_CLEAR_TIME = 0.8
KEYPAD_BUTTON_SIZE = (0.22, 0.22, 0.035)
KEYPAD_BUTTON_Z = 0.155
KEYPAD_DEBUG_HITBOXES = False
KEYPAD_DEBUG_LABEL_SCALE = 0.22
KEYPAD_DISPLAY_Z = KEYPAD_BUTTON_Z + 0.025
KEYPAD_DISPLAY_SEGMENTS = {
    '0': 'abcdef',
    '1': 'bc',
    '2': 'abged',
    '3': 'abgcd',
    '4': 'fgbc',
    '5': 'afgcd',
    '6': 'afgecd',
    '7': 'abc',
    '8': 'abcdefg',
    '9': 'abfgcd',
    '-': 'g',
    '_': 'd',
}
KEYPAD_BUTTONS = (
    ('1', 0.597, 0.365), ('2', 0.235, 0.365), ('3', -0.126, 0.365),
    ('4', 0.597, 0.004), ('5', 0.235, 0.004), ('6', -0.126, 0.004),
    ('7', 0.597, -0.357), ('8', 0.235, -0.357), ('9', -0.126, -0.357),
    ('0', 0.235, -0.717), ('enter', -0.62, -0.10),
)
class DoorMixin(BedMixin, DrawerMixin):
    def init_door_assets(self):
        self.door_model = self.load_door_model()
        self.door_model_scale = self.fit_door_model_scale(self.door_model)
        self.exit_sign_model = self.load_exit_sign_model()
        self.exit_sign_model_scale = self.fit_exit_sign_model_scale(self.exit_sign_model)
        self.keypad_model = self.load_keypad_model()
        self.keypad_model_scale = self.fit_keypad_model_scale(self.keypad_model)
        self.init_bed_assets()
        self.init_drawer_assets()
        self.door_open_sound = Audio('asset/sound/door_open.wav', autoplay=False, volume=0.5)
        self.door_close_sound = Audio('asset/sound/door_close.wav', autoplay=False, volume=0.68)
        self.key_unlock_sound = Audio('asset/sound/key_unlock.wav', autoplay=False, volume=1.0)

    def build_door_lookup(self):
        generated_doors = {
            (r, c, face)
            for r in range(ROWS) for c in range(COLS)
            if LAYOUT[r][c] == 0
            for face in ('north', 'south', 'west', 'east')
            if not (r <= 1 and c <= 2)
            and (r * 17 + c * 31 + DOOR_FACE_SALTS[face]) % DOOR_DENSITY == 0
        }
        self._door_set = frozenset(generated_doors)

        self._cell_door_rooms = {}
        self.door_room_cells = set()
        self.exit_room_cell = self.random_edge_exit_room_cell(self.start_room_cell)
        self.exit_room_cells = frozenset((self.exit_room_cell,)) if self.exit_room_cell else frozenset()
        self.exit_sign_door_key = self.locked_room_door_key(self.exit_room_cell)
        self._first_lockable_door_key = self.locked_room_door_key(self.start_room_cell)
        for r, c in self.walkable_cells:
            rooms = set()
            for face in ('north', 'south', 'west', 'east'):
                if (r, c, face) not in self._door_set:
                    continue

                (rr, rc), _ = self.door_room_for_face(r, c, face)
                if 0 <= rr < ROWS and 0 <= rc < COLS and LAYOUT[rr][rc] == 1:
                    rooms.add((rr, rc))

            if rooms:
                self._cell_door_rooms[(r, c)] = rooms
                self.door_room_cells.update(rooms)

        self.choose_note_placements()

    def random_edge_exit_room_cell(self, start_room_cell):
        candidates = []

        for r, c, face in sorted(self._door_set):
            room_cell, _ = self.door_room_for_face(r, c, face)
            rr, rc = room_cell

            if room_cell == start_room_cell:
                continue
            if not (0 <= rr < ROWS and 0 <= rc < COLS and LAYOUT[rr][rc] == 1):
                continue
            if not (rr in (0, ROWS - 1) or rc in (0, COLS - 1)):
                continue

            candidates.append(room_cell)

        if candidates:
            return random.choice(candidates)

        return self.farthest_exit_room_cell(start_room_cell)

    def farthest_exit_room_cell(self, start_room_cell):
        candidates = []

        for r, c, face in sorted(self._door_set):
            room_cell, _ = self.door_room_for_face(r, c, face)
            rr, rc = room_cell

            if room_cell == start_room_cell:
                continue
            if not (0 <= rr < ROWS and 0 <= rc < COLS and LAYOUT[rr][rc] == 1):
                continue

            dr = rr - start_room_cell[0]
            dc = rc - start_room_cell[1]
            candidates.append((dr * dr + dc * dc, abs(dr) + abs(dc), room_cell))

        return max(candidates)[2] if candidates else None

    def locked_room_door_key(self, room_cell):
        if room_cell is None:
            return None

        for r, c, face in sorted(self._door_set):
            (rr, rc), _ = self.door_room_for_face(r, c, face)

            if (rr, rc) == room_cell:
                return self.door_key(r, c, face)

        return None

    def door_lockable(self, key):
        return key == self._first_lockable_door_key or key == self.exit_sign_door_key

    def door_locked(self, key, lockable):
        if key not in self.door_lock_states:
            self.door_lock_states[key] = lockable

        return self.door_lock_states.get(key, False)

    def reset_start_room_lock_and_key(self):
        key = self._first_lockable_door_key

        if key is not None:
            self.door_states[key] = False
            self.door_lock_states[key] = True

            door = self.active_doors.get(key)
            if door:
                door['locked'] = True
                door['open'] = 0.0
                door['target'] = 0.0
                door['rattle_timer'] = 0.0
                door['unlock_open_timer'] = 0.0
                door['pending_open'] = False

                for node, base_h in door['moving_nodes']:
                    node.setH(base_h)

                collider = door.get('wall_collider')
                if collider:
                    self.set_door_wall_collision(collider, True)

        self.reset_key_pickup()

    def exit_sign_rotation_for_face(self, face):
        return (DOOR_FACE_ROTATIONS[face]) % 360

    def keypad_position_for_door(self, x, z, face):
        if face == 'north':
            return x + KEYPAD_RIGHT_OFFSET, KEYPAD_CENTER_Y, z - CELL / 2 + KEYPAD_WALL_OFFSET
        if face == 'south':
            return x - KEYPAD_RIGHT_OFFSET, KEYPAD_CENTER_Y, z + CELL / 2 - KEYPAD_WALL_OFFSET
        if face == 'west':
            return x - CELL / 2 + KEYPAD_WALL_OFFSET, KEYPAD_CENTER_Y, z - KEYPAD_RIGHT_OFFSET
        return x + CELL / 2 - KEYPAD_WALL_OFFSET, KEYPAD_CENTER_Y, z + KEYPAD_RIGHT_OFFSET

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

    def load_exit_sign_model(self):
        scene = ShowBaseGlobal.base.loader.loadModel(Filename.fromOsSpecific(str(EXIT_SIGN_MODEL_PATH)))

        if scene.isEmpty():
            raise RuntimeError(f'Failed to load exit sign model: {EXIT_SIGN_MODEL_PATH}')

        model = NodePath('exit_sign_template')
        scene.copyTo(model)
        scene.removeNode()
        model.setTwoSided(True)

        bounds = model.getTightBounds()
        if bounds:
            mn, mx = bounds
            model.setPos(-(mn.x + mx.x) * 0.5, -(mn.y + mx.y) * 0.5, -(mn.z + mx.z) * 0.5)

        return model

    def load_keypad_model(self):
        scene = ShowBaseGlobal.base.loader.loadModel(Filename.fromOsSpecific(str(KEYPAD_MODEL_PATH)))

        if scene.isEmpty():
            raise RuntimeError(f'Failed to load keypad model: {KEYPAD_MODEL_PATH}')

        model = NodePath('keypad_template')
        scene.copyTo(model)
        scene.removeNode()
        model.setTwoSided(True)

        for np in model.findAllMatches('**'):
            if not np.isEmpty():
                np.setTwoSided(True)

        bounds = model.getTightBounds()
        if bounds:
            mn, mx = bounds
            model.setPos(-(mn.x + mx.x) * 0.5, -(mn.y + mx.y) * 0.5, -(mn.z + mx.z) * 0.5)

        return model

    def fit_exit_sign_model_scale(self, model):
        bounds = model.getTightBounds()

        if not bounds:
            return 1.0

        mn, mx = bounds
        w = max(mx.x - mn.x, mx.z - mn.z, 0.001)
        h = max(mx.y - mn.y, 0.001)
        return min(EXIT_SIGN_TARGET_W / w, EXIT_SIGN_TARGET_H / h)

    def fit_keypad_model_scale(self, model):
        bounds = model.getTightBounds()

        if not bounds:
            return 1.0

        mn, mx = bounds
        height = max(mx.z - mn.z, mx.y - mn.y, 0.001)
        return KEYPAD_TARGET_H / height

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

    def door_room_for_face(self, r, c, face):
        if face == 'north':
            return (r - 1, c), 'south'
        if face == 'south':
            return (r + 1, c), 'north'
        if face == 'west':
            return (r, c - 1), 'east'
        return (r, c + 1), 'west'

    def door_key_for_room_cell(self, room_cell):
        if room_cell is None:
            return None

        for key, door in self.active_doors.items():
            r, c, face = key
            found_room_cell, _ = self.door_room_for_face(r, c, face)

            if found_room_cell == room_cell:
                return key

        return None

    def closed_door_for_room_cell(self, room_cell):
        key = self.door_key_for_room_cell(room_cell)

        if key is None:
            return None, None

        door = self.active_doors.get(key)
        if not door or self.door_states.get(key, False):
            return None, None

        return key, door

    def open_door_by_key(self, key):
        door = self.active_doors.get(key)

        if not door:
            return False

        self.door_lock_states[key] = False
        door['locked'] = False
        door['pending_open'] = False
        door['unlock_open_timer'] = 0.0
        self.door_states[key] = True
        door['target'] = 1.0
        door['open'] = max(door.get('open', 0.0), 0.55)

        collider = door.get('wall_collider')
        if collider:
            self.set_door_wall_collision(collider, False)

        self.door_open_sound.stop()
        self.door_open_sound.play(start=0.3)
        return True

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

    def add_wall_with_baseboard_gap(self, mesh_data, x0, z0, x1, z1, out_x, out_z, near_lights, extend_baseboard=True):
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
        entity = Entity(model='cube', visible=False, position=pos, scale=sc, collider='box')
        entity._collision_entity = True
        return entity

    def add_door_wall_colliders(self, entities, x, z, face):
        gap = min(DOOR_COLLIDER_GAP, CELL - 0.36)
        side_len = max((WALL_COLLIDER_LEN - gap) * 0.5, 0.05)
        side_offset = gap * 0.5 + side_len * 0.5
        side_colliders = []

        if face in ('north', 'south'):
            wall_z = z - CELL / 2 if face == 'north' else z + CELL / 2
            side_scale = (side_len, WALL_H, WALL_COLLIDER_T)

            side_colliders.append(self.add_wall_collider((x - side_offset, WALL_H / 2, wall_z), side_scale))
            side_colliders.append(self.add_wall_collider((x + side_offset, WALL_H / 2, wall_z), side_scale))
            closed_collider = self.add_wall_collider((x, WALL_H / 2, wall_z), (gap, WALL_H, WALL_COLLIDER_T))
            closed_collider._door_side_colliders = side_colliders
            entities.extend(side_colliders)
            return closed_collider

        wall_x = x - CELL / 2 if face == 'west' else x + CELL / 2
        side_scale = (WALL_COLLIDER_T, WALL_H, side_len)

        side_colliders.append(self.add_wall_collider((wall_x, WALL_H / 2, z - side_offset), side_scale))
        side_colliders.append(self.add_wall_collider((wall_x, WALL_H / 2, z + side_offset), side_scale))
        closed_collider = self.add_wall_collider((wall_x, WALL_H / 2, z), (WALL_COLLIDER_T, WALL_H, gap))
        closed_collider._door_side_colliders = side_colliders
        entities.extend(side_colliders)
        return closed_collider

    def build_door_room(self, room_cell):
        if room_cell == self.exit_room_cell:
            return self.build_exit_plain(room_cell)

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
            entities.append(self.add_wall_collider((cx, WALL_H / 2, north_z), (wall_len, WALL_H, WALL_COLLIDER_T)))
        else:
            self.add_wall_with_door_gap(mesh_data, west_x, north_z, east_x, north_z, lit_near)
            self.add_room_door_threshold(mesh_data, cx, cz, 'north', west_x, north_z, east_x, south_z, lit_near)

        if 'south' not in skip_faces:
            self.add_wall_face(mesh_data, east_x, south_z, west_x, south_z, lit_near)
            entities.append(self.add_wall_collider((cx, WALL_H / 2, south_z), (wall_len, WALL_H, WALL_COLLIDER_T)))
        else:
            self.add_wall_with_door_gap(mesh_data, east_x, south_z, west_x, south_z, lit_near)
            self.add_room_door_threshold(mesh_data, cx, cz, 'south', west_x, north_z, east_x, south_z, lit_near)

        if 'west' not in skip_faces:
            self.add_wall_face(mesh_data, west_x, south_z, west_x, north_z, lit_near)
            entities.append(self.add_wall_collider((west_x, WALL_H / 2, cz), (WALL_COLLIDER_T, WALL_H, wall_len)))
        else:
            self.add_wall_with_door_gap(mesh_data, west_x, south_z, west_x, north_z, lit_near)
            self.add_room_door_threshold(mesh_data, cx, cz, 'west', west_x, north_z, east_x, south_z, lit_near)

        if 'east' not in skip_faces:
            self.add_wall_face(mesh_data, east_x, north_z, east_x, south_z, lit_near)
            entities.append(self.add_wall_collider((east_x, WALL_H / 2, cz), (WALL_COLLIDER_T, WALL_H, wall_len)))
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

        _, _, bed_face = self.add_bed_decoration(entities, cx, cz, skip_faces, west_x, north_z, east_x, south_z, lit_near)
        self.add_drawer_decoration(entities, cx, cz, skip_faces, bed_face, west_x, north_z, east_x, south_z, lit_near)

        return entities

    def build_exit_plain(self, room_cell):
        return []

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

    def add_keypad_debug_label(self, keypad_entity, label, x, y):
        if not KEYPAD_DEBUG_HITBOXES:
            return None

        display_label = {'enter': 'ENT'}.get(label, label)
        text = Text(
            parent=keypad_entity,
            text=display_label,
            origin=(0, 0),
            position=(x, y, KEYPAD_BUTTON_Z + 0.025),
            scale=KEYPAD_DEBUG_LABEL_SCALE,
            color=color.rgba(255, 255, 255, 235),
        )
        text.always_on_top = True
        return text

    def keypad_button_scale(self, label):
        if label == 'enter':
            return 0.38, 0.60, KEYPAD_BUTTON_SIZE[2]

        return KEYPAD_BUTTON_SIZE

    def prepare_live_keypad_model(self, keypad_node):
        keypad_node.setTwoSided(True)

    def keypad_button_color(self):
        if KEYPAD_DEBUG_HITBOXES:
            return color.rgba(75, 215, 255, 135)

        return color.rgba(0, 0, 0, 0)

    def add_keypad_display(self, keypad_entity):
        digits = []
        start_x = 0.55
        step_x = -0.16
        segment_data = {
            'a': (0.0, 0.048, 0.095, 0.018),
            'b': (0.052, 0.018, 0.018, 0.060),
            'c': (0.052, -0.048, 0.018, 0.060),
            'd': (0.0, -0.080, 0.095, 0.018),
            'e': (-0.052, -0.048, 0.018, 0.060),
            'f': (-0.052, 0.018, 0.018, 0.060),
            'g': (0.0, -0.016, 0.095, 0.018),
        }

        for digit_index in range(5):
            digit = {}
            x = start_x + digit_index * step_x

            for name, (sx, sy, sw, sh) in segment_data.items():
                segment = Entity(
                    parent=keypad_entity,
                    model='cube',
                    color=color.rgba(70, 255, 45, 0),
                    position=(x - sx, 0.705 + sy, KEYPAD_DISPLAY_Z),
                    scale=(sw, sh, 0.006),
                    unlit=True,
                )
                digit[name] = segment

            digits.append(digit)

        return {'digits': digits, 'text': ''}

    def set_keypad_display_text(self, keypad, text):
        keypad['display']['text'] = text
        shown = text[-5:].rjust(5)

        for digit, char in zip(keypad['display']['digits'], shown):
            active = KEYPAD_DISPLAY_SEGMENTS.get(char, '')

            for name, segment in digit.items():
                segment.color = color.rgba(70, 255, 45, 245 if name in active else 0)

    def add_exit_keypad(self, entities, door_key, x, z, face):
        keypad_entity = Entity(
            position=self.keypad_position_for_door(x, z, face),
            rotation=(0, DOOR_FACE_ROTATIONS[face], 0),
            scale=self.keypad_model_scale,
        )
        keypad_node = self.keypad_model.copyTo(keypad_entity)
        self.prepare_live_keypad_model(keypad_node)
        entities.append(keypad_entity)

        display = self.add_keypad_display(keypad_entity)

        buttons = {}
        for label, bx, bz in KEYPAD_BUTTONS:
            button = Entity(
                parent=keypad_entity,
                model='cube',
                color=self.keypad_button_color(),
                position=(bx, bz, KEYPAD_BUTTON_Z),
                scale=self.keypad_button_scale(label),
            )
            button.always_on_top = True
            button.base_position = (button.x, button.y, button.z)
            button.debug_label = self.add_keypad_debug_label(keypad_entity, label, bx, bz)
            buttons[label] = button

        self.active_keypads[door_key] = {
            'entity': keypad_entity,
            'display': display,
            'buttons': buttons,
            'input': '',
            'message_timer': 0.0,
            'pending_result_sound': None,
            'result_sound_timer': 0.0,
            'pending_unlock': False,
            'door_key': door_key,
        }

    def add_door_decoration(self, entities, x, z, face, near_lights, wall_collider=None):
        key = self.door_key(round(z / CELL), round(x / CELL), face)
        pos = self.door_world_position(x, z, face)
        rotation_y = DOOR_FACE_ROTATIONS[face]
        open_amount = 1.0 if self.door_states.get(key, False) else 0.0
        lockable = self.door_lockable(key)
        locked = self.door_locked(key, lockable)

        wall_off = 0.04
        light_y = DOOR_MODEL_TARGET_H + 0.15
        if face in ('north', 'south'):
            lx = x
            lz = (z - CELL / 2 + wall_off) if face == 'north' else (z + CELL / 2 - wall_off)
            light_sc = (0.45, 0.12, 0.04)
        else:
            lx = (x - CELL / 2 + wall_off) if face == 'west' else (x + CELL / 2 - wall_off)
            lz = z
            light_sc = (0.04, 0.12, 0.45)
        door_near = list(near_lights) + [(lx, light_y, lz)]

        light_val = self.light_system.light_at(pos[0], WALL_H * 0.5, pos[2], door_near)
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

        if wall_collider:
            self.set_door_wall_collision(wall_collider, open_amount <= 0.5)

        entities.append(entity)

        if key == self.exit_sign_door_key:
            sign_rot = self.exit_sign_rotation_for_face(face)
            sign_entity = Entity(
                position=(lx, light_y, lz),
                rotation=(0, sign_rot, 0),
                scale=self.exit_sign_model_scale,
            )
            sign_node = self.exit_sign_model.copyTo(sign_entity)
            sign_node.setTwoSided(True)
            sign_node.setColorScale(0.4, 2.5, 0.6, 1.0)
            glow = self.exit_sign_model.copyTo(sign_entity)
            glow.setTwoSided(True)
            glow.setScale(1.06)
            glow.setColorScale(0.2, 1.2, 0.3, 0.3)
            glow.setTransparency(TransparencyAttrib.MAlpha)
            glow.setDepthWrite(False)
            entities.append(sign_entity)
            self.add_exit_keypad(entities, key, x, z, face)
        else:
            entities.append(Entity(
                model='cube',
                color=color.Color(1.0, 0.95, 0.72, 1.0),
                unlit=True,
                position=(lx, light_y, lz),
                scale=light_sc,
            ))

        self.active_doors[key] = {
            'entity': entity,
            'moving_nodes': moving_nodes,
            'open': open_amount,
            'target': open_amount,
            'face': face,
            'position': pos,
            'wall_collider': wall_collider,
            'lockable': lockable,
            'locked': locked,
            'rattle_timer': 0.0,
            'unlock_open_timer': 0.0,
            'pending_open': False,
        }

    def set_door_wall_collision(self, wall_collider, closed):
        wall_collider.collider = 'box' if closed else None

        for collider in getattr(wall_collider, '_door_side_colliders', ()):
            collider.collider = 'box'

    def keypad_ray_box_distance(self, origin, ray, mn, mx):
        t_min = 0.0
        t_max = KEYPAD_INTERACT_RAY_DISTANCE

        for origin_value, ray_value, min_value, max_value in (
            (origin.x, ray.x, mn.x, mx.x),
            (origin.y, ray.y, mn.y, mx.y),
            (origin.z, ray.z, mn.z, mx.z),
        ):
            if abs(ray_value) < 1e-6:
                if origin_value < min_value or origin_value > max_value:
                    return None
                continue

            inv = 1.0 / ray_value
            near = (min_value - origin_value) * inv
            far = (max_value - origin_value) * inv

            if near > far:
                near, far = far, near

            t_min = max(t_min, near)
            t_max = min(t_max, far)

            if t_min > t_max:
                return None

        if t_min < 0 or t_min > KEYPAD_INTERACT_RAY_DISTANCE:
            return None

        return t_min

    def nearest_keypad_button_ray_hit(self, origin, ray):
        nearest = None
        nearest_t = KEYPAD_INTERACT_RAY_DISTANCE
        render = ShowBaseGlobal.base.render

        for keypad_key, keypad in self.active_keypads.items():
            if not keypad['entity'].enabled:
                continue

            for label, button in keypad['buttons'].items():
                bounds = button.getTightBounds(render)

                if not bounds:
                    continue

                t = self.keypad_ray_box_distance(origin, ray, bounds[0], bounds[1])

                if t is not None and t < nearest_t:
                    nearest = (keypad_key, label)
                    nearest_t = t

        if nearest is None:
            return None, None

        return nearest, nearest_t

    def press_keypad_button(self, keypad_key, label):
        keypad = self.active_keypads.get(keypad_key)

        if not keypad:
            return False

        print(f'keypad button pressed: {label}')
        beep = Audio('asset/sound/keypad_beep.wav', autoplay=True, volume=0.9)
        if label == 'enter':
            self.set_audio_pitch(beep, 1.28)
        button = keypad['buttons'].get(label)
        if button:
            button.press_timer = KEYPAD_PRESS_TIME

        if label == 'enter':
            keypad_code = self.note_keypad_code() or KEYPAD_CODE
            blank_display = '_' * len(keypad_code)

            if keypad['input'] == keypad_code:
                keypad['pending_result_sound'] = 'success'
                keypad['result_sound_timer'] = KEYPAD_RESULT_SOUND_DELAY
                keypad['pending_unlock'] = True
                keypad['input'] = ''
                keypad['message_timer'] = 0.0
                self.set_keypad_display_text(keypad, blank_display)
            else:
                keypad['pending_result_sound'] = 'fail'
                keypad['result_sound_timer'] = KEYPAD_RESULT_SOUND_DELAY
                keypad['pending_unlock'] = False
                keypad['input'] = ''
                keypad['message_timer'] = KEYPAD_DISPLAY_CLEAR_TIME
                self.set_keypad_display_text(keypad, blank_display)
            return True

        if label.isdigit():
            keypad_code = self.note_keypad_code() or KEYPAD_CODE
            keypad['input'] = (keypad['input'] + label)[-len(keypad_code):]
            keypad['message_timer'] = 0.0
            self.set_keypad_display_text(keypad, keypad['input'])
            return True

        return False

    def set_audio_pitch(self, sound, pitch):
        for attr in ('pitch', 'play_rate', 'rate'):
            if hasattr(sound, attr):
                try:
                    setattr(sound, attr, pitch)
                    return
                except Exception:
                    pass

        for attr in ('sound', '_sound', 'audio', '_audio'):
            inner = getattr(sound, attr, None)

            if inner and hasattr(inner, 'setPlayRate'):
                try:
                    inner.setPlayRate(pitch)
                    return
                except Exception:
                    pass

    def play_keypad_result_sound(self, result):
        path = 'asset/sound/keypad_success.wav' if result == 'success' else 'asset/sound/keypad_fail.wav'

        try:
            Audio(path, autoplay=True, volume=1.0)
        except Exception:
            pass

    def unlock_keypad_door(self, keypad_key):
        door = self.active_doors.get(keypad_key)
        keypad = self.active_keypads.get(keypad_key)

        if keypad:
            keypad['input'] = ''
            keypad['message_timer'] = 0.0
            self.set_keypad_display_text(keypad, '')

        if not door:
            return

        self.door_lock_states[keypad_key] = False
        door['locked'] = False
        door['pending_open'] = False
        door['unlock_open_timer'] = 0.0
        self.door_states[keypad_key] = True
        door['target'] = 1.0

        self.door_open_sound.stop()
        self.door_open_sound.play(start=0.3)

    def debug_unlock_exit_door(self):
        key = self.exit_sign_door_key

        if key is None:
            return False

        keypad = self.active_keypads.get(key)
        if keypad:
            keypad_code = self.note_keypad_code() or KEYPAD_CODE
            for label in keypad_code:
                self.press_keypad_button(key, label)
            self.press_keypad_button(key, 'enter')

        self.unlock_keypad_door(key)
        door = self.active_doors.get(key)
        if door:
            door['open'] = max(door.get('open', 0.0), 0.55)

            collider = door.get('wall_collider')
            if collider:
                self.set_door_wall_collision(collider, False)

        if keypad:
            keypad['pending_result_sound'] = None
            keypad['pending_unlock'] = False

        return True

    def update_keypads(self):
        for keypad in self.active_keypads.values():
            if keypad.get('pending_result_sound') and keypad.get('result_sound_timer', 0.0) > 0.0:
                keypad['result_sound_timer'] = max(0.0, keypad['result_sound_timer'] - time.dt)

                if keypad['result_sound_timer'] <= 0.0:
                    self.play_keypad_result_sound(keypad['pending_result_sound'])
                    if keypad.get('pending_unlock'):
                        self.unlock_keypad_door(keypad['door_key'])
                        keypad['pending_unlock'] = False
                    keypad['pending_result_sound'] = None

            if keypad.get('message_timer', 0.0) > 0.0:
                keypad['message_timer'] = max(0.0, keypad['message_timer'] - time.dt)

                if keypad['message_timer'] <= 0.0:
                    self.set_keypad_display_text(keypad, keypad['input'])

            for button in keypad['buttons'].values():
                timer = max(0.0, getattr(button, 'press_timer', 0.0) - time.dt)
                button.press_timer = timer
                progress = 1.0 - (timer / KEYPAD_PRESS_TIME if KEYPAD_PRESS_TIME > 0 else 1.0)
                press = math.sin(progress * math.pi) * KEYPAD_PRESS_DEPTH if timer > 0.0 else 0.0
                base_x, base_y, base_z = button.base_position
                button.position = (base_x, base_y, base_z - press)
                label = getattr(button, 'debug_label', None)
                if label:
                    label.position = (base_x, base_y, base_z - press + 0.025)

    def nearest_interactable_door_key(self):
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

        return nearest_key

    def nearest_interaction(self):
        nearest = None
        nearest_t = float('inf')
        ray_x, ray_z = self.player_forward_xz()

        for key, door in self.active_doors.items():
            x, _, z = door['position']
            dx = x - self.player.x
            dz = z - self.player.z
            t = dx * ray_x + dz * ray_z

            if t < 0 or t > DOOR_INTERACT_RAY_DISTANCE:
                continue

            perp = abs(dx * ray_z - dz * ray_x)

            if perp <= DOOR_INTERACT_HALF_WIDTH and t < nearest_t:
                nearest = ('door', key)
                nearest_t = t

        origin, ray = self.camera_interaction_ray()
        keypad_button, keypad_t = self.nearest_keypad_button_ray_hit(origin, ray)
        key_key, key_t = self.nearest_key_ray_hit(origin, ray)
        note_key, note_t = self.nearest_note_ray_hit(origin, ray)
        drawer_key, drawer_t = self.nearest_drawer_ray_hit(origin, ray)

        if keypad_button is not None and keypad_t is not None:
            nearest = ('keypad', keypad_button)
            nearest_t = keypad_t
        elif key_key is not None and key_t is not None and key_t < nearest_t:
            nearest = ('key', key_key)
            nearest_t = key_t
        elif note_key is not None and note_t is not None and note_t < nearest_t:
            nearest = ('note', note_key)
            nearest_t = note_t
        elif drawer_key is not None and drawer_t is not None and drawer_t < nearest_t:
            nearest = ('drawer', drawer_key)
            nearest_t = drawer_t

        self.update_key_glow(nearest[1] if nearest and nearest[0] == 'key' else None)

        return nearest

    def can_interact_with_door(self):
        return self.nearest_interactable_door_key() is not None

    def can_interact(self):
        return self.nearest_interaction() is not None

    def toggle_nearest_door(self):
        nearest_key = self.nearest_interactable_door_key()

        if nearest_key is None:
            return False

        return self.toggle_door(nearest_key)

    def toggle_door(self, key):
        door = self.active_doors.get(key)

        if not door:
            return False

        if door.get('pending_open'):
            return False

        is_open = self.door_states.get(key, False)

        if door.get('locked') and not is_open:
            if key == self.exit_sign_door_key:
                door['rattle_timer'] = DOOR_RATTLE_DURATION
                Audio('asset/sound/door_rattle.wav', autoplay=True, volume=1.0)
                return False

            if not self.consume_key():
                door['rattle_timer'] = DOOR_RATTLE_DURATION
                Audio('asset/sound/door_rattle.wav', autoplay=True, volume=1.0)
                return False

            self.door_lock_states[key] = False
            door['locked'] = False
            door['pending_open'] = True
            door['unlock_open_timer'] = DOOR_UNLOCK_OPEN_DELAY
            self.key_unlock_sound.stop()
            self.key_unlock_sound.play()
            return True

        self.door_states[key] = not is_open
        door['target'] = 1.0 if not is_open else 0.0

        sound = self.door_close_sound if is_open else self.door_open_sound
        sound.stop()

        if not is_open:
            sound.play(start=0.3)
        else:
            sound.play()

        return True

    def interact_nearest(self):
        interaction = self.nearest_interaction()

        if interaction is None:
            return False

        kind, key = interaction

        if kind == 'door':
            return self.toggle_door(key)

        if kind == 'key':
            return self.pickup_key(key)

        if kind == 'note':
            return self.pickup_note(key)

        if kind == 'keypad':
            keypad_key, label = key
            return self.press_keypad_button(keypad_key, label)

        return self.toggle_drawer(key)

    def update_doors(self):
        self.update_keypads()

        for key, door in list(self.active_doors.items()):
            if door.get('pending_open'):
                door['unlock_open_timer'] = max(0.0, door.get('unlock_open_timer', 0.0) - time.dt)

                if door['unlock_open_timer'] <= 0.0:
                    door['pending_open'] = False
                    self.door_states[key] = True
                    door['target'] = 1.0
                    self.door_open_sound.stop()
                    self.door_open_sound.play(start=0.3)

            target = 1.0 if self.door_states.get(key, False) else 0.0
            current = door['open'] + (target - door['open']) * min(1.0, time.dt * DOOR_OPEN_SPEED)
            door['open'] = current
            door['target'] = target

            rattle_angle = 0.0
            if door.get('locked') and door.get('rattle_timer', 0.0) > 0.0:
                door['rattle_timer'] = max(0.0, door['rattle_timer'] - time.dt)
                progress = 1.0 - door['rattle_timer'] / DOOR_RATTLE_DURATION
                fade = 1.0 - progress
                rattle_angle = math.sin(progress * math.tau * DOOR_RATTLE_SWINGS) * DOOR_RATTLE_ANGLE * fade

            for node, base_h in door['moving_nodes']:
                node.setH(base_h + DOOR_OPEN_SIGN * DOOR_OPEN_ANGLE * current + rattle_angle)

            collider = door.get('wall_collider')
            if collider:
                self.set_door_wall_collision(collider, current <= 0.5)
