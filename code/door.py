from direct.showbase import ShowBaseGlobal
from panda3d.core import Filename, NodePath, PNMImage, Texture as PandaTexture
from ursina import Audio, Entity, Texture as UrsinaTexture, Vec3, camera, color, time

from map_data import (
    BASEBOARD_OUT,
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
from textures import WALL_RGB


DOOR_MODEL_PATH = PROJECT_DIR / 'asset' / 'model' / 'door.glb'
BED_MODEL_PATH = PROJECT_DIR / 'asset' / 'model' / 'bed.glb'
DRAWER_MODEL_PATH = PROJECT_DIR / 'asset' / 'model' / 'drawer.glb'
DOOR_MODEL_TARGET_H = 1.92
DOOR_MODEL_TARGET_W = 1.05
BED_MODEL_TARGET_LONG = 1.95
BED_MODEL_TARGET_SHORT = 1.10
BED_COLLIDER_H = 0.65
BED_COLLIDER_SHRINK = 0.92
BED_WALL_CLEARANCE = 0.04
BED_SHADOW_ALPHA = 85
BED_SHADOW_TEXTURE_SIZE = 96
BED_SHADOW_Y = 0.012
DRAWER_SHADOW_Y = 0.012
DRAWER_SHADOW_ALPHA = 70
DRAWER_MODEL_TARGET_W = 1.28
DRAWER_MODEL_TARGET_H = 1.38
DRAWER_COLLIDER_SHRINK = 0.98
DRAWER_WALL_CLEARANCE = 0.04
DRAWER_OPEN_DISTANCE = 30
DRAWER_OPEN_SPEED = 10.0
DRAWER_INTERACT_RAY_DISTANCE = CELL * 0.4
DRAWER_INTERACT_PAD = 0.01
DRAWER_LIGHT_RGB = (255, 228, 172)
DRAWER_LIGHT_BOOST = 1.7
DRAWER_MIN_LIGHT = 0.36
DOOR_INSET = 0.08
DOOR_WALL_GAP = DOOR_MODEL_TARGET_W - 0.08
DOOR_BASEBOARD_GAP = DOOR_MODEL_TARGET_W
DOOR_COLLIDER_GAP = DOOR_MODEL_TARGET_W + 0.70
DOOR_THRESHOLD_W = DOOR_MODEL_TARGET_W + 0.20
DOOR_DENSITY = 11
DOOR_OPEN_ANGLE = 82
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
DRAWER_FACE_ROTATIONS = {
    'north': 180,
    'south': 0,
    'west': -90,
    'east': 90,
}
DOOR_OPEN_SIGN = 1
DOOR_MODEL_ROOT = 'Null'
DOOR_MOVING_NODES = ('door',)
DRAWER_BODY_NODE = 'vintage_wooden_drawer_01_body'


class DoorMixin:
    def init_door_assets(self):
        self.door_model = self.load_door_model()
        self.door_model_scale = self.fit_door_model_scale(self.door_model)
        self.bed_model = self.load_bed_model()
        self.bed_model_scale = self.fit_bed_model_scale(self.bed_model)
        self.bed_model_size = self.model_size(self.bed_model, self.bed_model_scale)
        self.furniture_shadow_texture = self.create_furniture_shadow_texture()
        self.drawer_model = self.load_drawer_model()
        self.drawer_model_scale = self.fit_drawer_model_scale(self.drawer_model)
        self.drawer_model_size = self.model_size(self.drawer_model, self.drawer_model_scale)
        self.door_open_sound = Audio('asset/sound/door_open.wav', autoplay=False, volume=0.5)
        self.door_close_sound = Audio('asset/sound/door_close.wav', autoplay=False, volume=0.68)

    def build_door_lookup(self):
        self._door_set = frozenset(
            (r, c, face)
            for r in range(ROWS) for c in range(COLS)
            if LAYOUT[r][c] == 0
            for face in ('north', 'south', 'west', 'east')
            if not (r <= 1 and c <= 2)
            and (r * 17 + c * 31 + DOOR_FACE_SALTS[face]) % DOOR_DENSITY == 0
        )

        self._cell_door_rooms = {}
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

    def load_bed_model(self):
        scene = ShowBaseGlobal.base.loader.loadModel(Filename.fromOsSpecific(str(BED_MODEL_PATH)))

        if scene.isEmpty():
            raise RuntimeError(f'Failed to load bed model: {BED_MODEL_PATH}')

        model = NodePath('bed_template')
        scene.copyTo(model)
        scene.removeNode()

        self.prepare_bed_model(model, normalize=True)
        return model

    def load_drawer_model(self):
        scene = ShowBaseGlobal.base.loader.loadModel(Filename.fromOsSpecific(str(DRAWER_MODEL_PATH)))

        if scene.isEmpty():
            raise RuntimeError(f'Failed to load drawer model: {DRAWER_MODEL_PATH}')

        model = NodePath('drawer_template')
        scene.copyTo(model)
        scene.removeNode()

        self.prepare_drawer_model(model, normalize=True)
        return model

    def prepare_door_model(self, model):
        model.setTwoSided(True)
        self.attach_door_handles(model)

        for np in model.findAllMatches('**'):
            if np.isEmpty():
                continue

            np.setTwoSided(True)

    def prepare_bed_model(self, model, normalize=False):
        model.setTwoSided(True)

        for np in model.findAllMatches('**'):
            if np.isEmpty():
                continue

            np.setTwoSided(True)

        if normalize:
            bounds = model.getTightBounds()

            if bounds:
                mn, mx = bounds
                model.setPos(
                    -(mn.x + mx.x) * 0.5,
                    -mn.y,
                    -(mn.z + mx.z) * 0.5,
                )

    def create_furniture_shadow_texture(self):
        size = BED_SHADOW_TEXTURE_SIZE
        center = (size - 1) * 0.5
        image = PNMImage(size, size, 4)
        texture = PandaTexture('furniture_soft_shadow')

        for y in range(size):
            ny = (y - center) / center
            for x in range(size):
                nx = (x - center) / center
                dx = 1.0 - abs(nx)
                dy = 1.0 - abs(ny)
                tx = min(1.0, dx / 0.6)
                ty = min(1.0, dy / 0.6)
                ax = tx * tx * (3.0 - 2.0 * tx)
                ay = ty * ty * (3.0 - 2.0 * ty)
                alpha = ax * ay

                image.setXel(x, y, 1, 1, 1)
                image.setAlpha(x, y, alpha)

        texture.load(image)
        return UrsinaTexture(texture)

    def prepare_drawer_model(self, model, normalize=False):
        model.setTwoSided(True)

        for np in model.findAllMatches('**'):
            if np.isEmpty():
                continue

            np.setTwoSided(True)

        if normalize:
            bounds = model.getTightBounds()

            if bounds:
                mn, mx = bounds
                model.setPos(
                    -(mn.x + mx.x) * 0.5,
                    -mn.y,
                    -(mn.z + mx.z) * 0.5,
                )

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

    def fit_bed_model_scale(self, model):
        bounds = model.getTightBounds()

        if not bounds:
            return 1.0

        mn, mx = bounds
        dims = sorted((
            max(mx.x - mn.x, 0.001),
            max(mx.y - mn.y, 0.001),
            max(mx.z - mn.z, 0.001),
        ), reverse=True)
        return min(BED_MODEL_TARGET_LONG / dims[0], BED_MODEL_TARGET_SHORT / dims[1])

    def fit_drawer_model_scale(self, model):
        bounds = model.getTightBounds()

        if not bounds:
            return 1.0

        mn, mx = bounds
        width = max(mx.x - mn.x, mx.z - mn.z, 0.001)
        height = max(mx.y - mn.y, 0.001)
        return min(DRAWER_MODEL_TARGET_W / width, DRAWER_MODEL_TARGET_H / height)

    def model_size(self, model, scale):
        bounds = model.getTightBounds()

        if not bounds:
            return BED_MODEL_TARGET_SHORT, BED_COLLIDER_H, BED_MODEL_TARGET_LONG

        mn, mx = bounds
        return (
            max((mx.x - mn.x) * scale, 0.001),
            max((mx.y - mn.y) * scale, 0.001),
            max((mx.z - mn.z) * scale, 0.001),
        )

    def bed_wall_offset(self):
        return self.bed_model_size[2] * 0.5 + BED_WALL_CLEARANCE

    def bed_collider_scale(self, face):
        width, _, depth = self.bed_model_size
        width *= BED_COLLIDER_SHRINK
        depth *= BED_COLLIDER_SHRINK

        if face in ('north', 'south'):
            return width, BED_COLLIDER_H, depth

        return depth, BED_COLLIDER_H, width

    def drawer_wall_offset(self):
        return self.drawer_model_size[2] * 0.5 + DRAWER_WALL_CLEARANCE

    def drawer_collider_height(self):
        return self.drawer_model_size[1] * DRAWER_COLLIDER_SHRINK

    def drawer_collider_scale(self, face):
        width, _, depth = self.drawer_model_size
        width *= DRAWER_COLLIDER_SHRINK
        depth *= DRAWER_COLLIDER_SHRINK
        height = self.drawer_collider_height()

        if face in ('north', 'south'):
            return width, height, depth

        return depth, height, width

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

        _, _, bed_face = self.add_bed_decoration(entities, cx, cz, skip_faces, west_x, north_z, east_x, south_z, lit_near)
        self.add_drawer_decoration(entities, cx, cz, skip_faces, bed_face, west_x, north_z, east_x, south_z, lit_near)

        return entities

    def bed_pose_for_room(self, cx, cz, skip_faces, west_x, north_z, east_x, south_z):
        wall_offset = self.bed_wall_offset()

        for face in ('north', 'south', 'west', 'east'):
            if face not in skip_faces:
                if face == 'north':
                    return (cx, 0, north_z + wall_offset), 0, face
                if face == 'south':
                    return (cx, 0, south_z - wall_offset), 180, face
                if face == 'west':
                    return (west_x + wall_offset, 0, cz), 90, face
                return (east_x - wall_offset, 0, cz), -90, face

        return (cx, 0, cz), 0, 'north'

    def add_bed_decoration(self, entities, cx, cz, skip_faces, west_x, north_z, east_x, south_z, near_lights):
        position, rotation_y, face = self.bed_pose_for_room(cx, cz, skip_faces, west_x, north_z, east_x, south_z)
        light_val = self.light_system.light_at(position[0], BED_COLLIDER_H * 0.5, position[2], near_lights)
        tint = self.light_system.shaded_color(WALL_RGB, light_val)
        entity = Entity(
            position=position,
            rotation=(0, rotation_y, 0),
            scale=self.bed_model_scale,
        )

        model = self.bed_model.copyTo(entity)
        self.prepare_bed_model(model)
        model.setColorScale(tint.r, tint.g, tint.b, 1.0)
        entities.append(entity)

        shadow_scale = self.bed_collider_scale(face)
        shadow = Entity(
            model='plane',
            position=(position[0], BED_SHADOW_Y, position[2]),
            rotation=(0, rotation_y, 0),
            scale=(shadow_scale[0], 1, shadow_scale[2]),
            texture=self.furniture_shadow_texture,
            color=color.rgba(0, 0, 0, BED_SHADOW_ALPHA),
        )
        entities.append(shadow)

        collider = Entity(
            model='cube',
            visible=False,
            position=(position[0], BED_COLLIDER_H * 0.5, position[2]),
            scale=self.bed_collider_scale(face),
            collider='box',
        )
        collider._collision_entity = True
        entities.append(collider)
        return position, rotation_y, face

    def drawer_pose_for_room(self, cx, cz, skip_faces, bed_face, west_x, north_z, east_x, south_z):
        wall_offset = self.drawer_wall_offset()

        for face in ('south', 'east', 'west', 'north'):
            if face in skip_faces or face == bed_face:
                continue

            if face == 'north':
                return (cx, 0, north_z + wall_offset), DRAWER_FACE_ROTATIONS[face], face
            if face == 'south':
                return (cx, 0, south_z - wall_offset), DRAWER_FACE_ROTATIONS[face], face
            if face == 'west':
                return (west_x + wall_offset, 0, cz), DRAWER_FACE_ROTATIONS[face], face
            return (east_x - wall_offset, 0, cz), DRAWER_FACE_ROTATIONS[face], face

        return None, None, None

    def add_drawer_decoration(self, entities, cx, cz, skip_faces, bed_face, west_x, north_z, east_x, south_z, near_lights):
        position, rotation_y, face = self.drawer_pose_for_room(cx, cz, skip_faces, bed_face, west_x, north_z, east_x, south_z)

        if position is None:
            return

        collider_h = self.drawer_collider_height()
        light_val = self.light_system.light_at(position[0], collider_h * 0.5, position[2], near_lights)
        tint = self.light_system.shaded_color(DRAWER_LIGHT_RGB, light_val * DRAWER_LIGHT_BOOST, DRAWER_MIN_LIGHT)
        entity = Entity(
            position=position,
            rotation=(0, rotation_y, 0),
            scale=self.drawer_model_scale,
        )

        model = self.drawer_model.copyTo(entity)
        self.prepare_drawer_model(model)
        model.setColorScale(tint.r, tint.g, tint.b, 1.0)
        entities.append(entity)

        shadow = Entity(
            model='plane',
            position=(position[0], DRAWER_SHADOW_Y, position[2]),
            rotation=(0, rotation_y, 0),
            scale=(
                self.drawer_model_size[0] * DRAWER_COLLIDER_SHRINK,
                1,
                self.drawer_model_size[2] * DRAWER_COLLIDER_SHRINK,
            ),
            texture=self.furniture_shadow_texture,
            color=color.rgba(0, 0, 0, DRAWER_SHADOW_ALPHA),
        )
        entities.append(shadow)

        collider = Entity(
            model='cube',
            visible=False,
            position=(position[0], collider_h * 0.5, position[2]),
            scale=self.drawer_collider_scale(face),
            collider='box',
        )
        collider._collision_entity = True
        entities.append(collider)

        moving_nodes = self.drawer_moving_nodes(entity)
        body_node = self.drawer_body_node(entity)
        open_offset = self.drawer_open_offset(entity)

        for drawer_name, node, base_pos, bounds_min, bounds_max in moving_nodes:
            key = ('drawer', round(cz / CELL), round(cx / CELL), drawer_name)
            open_amount = 1.0 if self.drawer_states.get(key, False) else 0.0
            node.setPos(base_pos.x, base_pos.y, base_pos.z - open_offset * open_amount)
            self.active_drawers[key] = {
                'entity': entity,
                'node': node,
                'base_pos': base_pos,
                'open_offset': open_offset,
                'bounds_min': bounds_min,
                'bounds_max': bounds_max,
                'body_node': body_node,
                'open': open_amount,
                'target': open_amount,
                'face': face,
                'position': position,
            }

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

    def drawer_moving_nodes(self, entity):
        out = []

        for i in range(1, 7):
            drawer_name = f'vintage_wooden_drawer_01_drawer{i:02d}'
            node = entity.find(f'**/{drawer_name}')
            if node and not node.isEmpty():
                bounds = self.drawer_node_bounds(entity, node)
                if bounds:
                    out.append((drawer_name, node, node.getPos(), *bounds))

        return out

    def drawer_node_bounds(self, entity, node):
        try:
            bounds = node.getTightBounds(entity)
        except TypeError:
            bounds = node.getTightBounds()

        if bounds:
            return bounds

        return None

    def drawer_body_node(self, entity):
        node = entity.find(f'**/{DRAWER_BODY_NODE}')

        if node and not node.isEmpty():
            return node

        return None

    def drawer_world_bounds(self, node):
        try:
            bounds = node.getTightBounds(ShowBaseGlobal.base.render)
        except TypeError:
            bounds = node.getTightBounds()

        if bounds:
            return bounds

        return None

    def drawer_ray_box_distance(self, origin, ray, mn, mx):
        t_min = 0.0
        t_max = DRAWER_INTERACT_RAY_DISTANCE
        pad = DRAWER_INTERACT_PAD

        for origin_value, ray_value, min_value, max_value in (
            (origin.x, ray.x, mn.x - pad, mx.x + pad),
            (origin.y, ray.y, mn.y - pad, mx.y + pad),
            (origin.z, ray.z, mn.z - pad, mx.z + pad),
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

        if t_min < 0 or t_min > DRAWER_INTERACT_RAY_DISTANCE:
            return None

        return t_min

    def drawer_hit_distance(self, drawer, origin, ray):
        bounds = self.drawer_world_bounds(drawer['node'])

        if not bounds:
            return None

        return self.drawer_ray_box_distance(origin, ray, bounds[0], bounds[1])

    def nearest_drawer_ray_hit(self, origin, ray):
        nearest_kind = None
        nearest_key = None
        nearest_t = DRAWER_INTERACT_RAY_DISTANCE
        checked_bodies = set()

        for key, drawer in self.active_drawers.items():
            entity = drawer['entity']

            if not entity.enabled:
                continue

            t = self.drawer_hit_distance(drawer, origin, ray)

            if t is not None and t < nearest_t:
                nearest_kind = 'drawer'
                nearest_key = key
                nearest_t = t

            body_node = drawer.get('body_node')

            if body_node is None or id(entity) in checked_bodies:
                continue

            checked_bodies.add(id(entity))
            body_bounds = self.drawer_world_bounds(body_node)

            if not body_bounds:
                continue

            body_t = self.drawer_ray_box_distance(origin, ray, body_bounds[0], body_bounds[1])

            if body_t is not None and body_t < nearest_t:
                nearest_kind = 'body'
                nearest_key = None
                nearest_t = body_t

        if nearest_kind == 'drawer':
            return nearest_key, nearest_t

        return None, None

    def camera_interaction_ray(self):
        render = ShowBaseGlobal.base.render
        pos = camera.getPos(render)
        forward = camera.getQuat(render).getForward()
        length = max((forward.x * forward.x + forward.y * forward.y + forward.z * forward.z) ** 0.5, 0.001)
        return Vec3(pos.x, pos.y, pos.z), Vec3(forward.x / length, forward.y / length, forward.z / length)

    def drawer_open_offset(self, entity):
        return DRAWER_OPEN_DISTANCE / max(abs(entity.scale_z), 0.001)

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

        if wall_collider:
            self.set_door_wall_collision(wall_collider, open_amount <= 0.5)

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

    def set_door_wall_collision(self, wall_collider, closed):
        wall_collider.collider = 'box' if closed else None

        for collider in getattr(wall_collider, '_door_side_colliders', ()):
            collider.collider = 'box'

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

    def nearest_interactable_drawer_key(self):
        origin, ray = self.camera_interaction_ray()
        nearest_key, _ = self.nearest_drawer_ray_hit(origin, ray)
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
        drawer_key, drawer_t = self.nearest_drawer_ray_hit(origin, ray)

        if drawer_key is not None and drawer_t < nearest_t:
            nearest = ('drawer', drawer_key)
            nearest_t = drawer_t

        return nearest

    def can_interact_with_door(self):
        return self.nearest_interactable_door_key() is not None

    def can_interact(self):
        return self.nearest_interaction() is not None

    def toggle_nearest_door(self):
        nearest_key = self.nearest_interactable_door_key()

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

    def toggle_drawer(self, key):
        drawer = self.active_drawers.get(key)

        if not drawer:
            return False

        is_open = self.drawer_states.get(key, False)
        self.drawer_states[key] = not is_open
        drawer['target'] = 1.0 if not is_open else 0.0
        return True

    def interact_nearest(self):
        interaction = self.nearest_interaction()

        if interaction is None:
            return False

        kind, key = interaction

        if kind == 'door':
            is_open = self.door_states.get(key, False)
            self.door_states[key] = not is_open
            self.active_doors[key]['target'] = 1.0 if not is_open else 0.0

            sound = self.door_close_sound if is_open else self.door_open_sound
            sound.stop()

            if not is_open:
                sound.play(start=0.3)
            else:
                sound.play()

            return True

        return self.toggle_drawer(key)

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
                self.set_door_wall_collision(collider, current <= 0.5)

    def update_drawers(self):
        for key, drawer in list(self.active_drawers.items()):
            target = 1.0 if self.drawer_states.get(key, False) else 0.0
            current = drawer['open'] + (target - drawer['open']) * min(1.0, time.dt * DRAWER_OPEN_SPEED)
            drawer['open'] = current
            drawer['target'] = target

            base_pos = drawer['base_pos']
            drawer['node'].setPos(base_pos.x, base_pos.y, base_pos.z - drawer['open_offset'] * current)
