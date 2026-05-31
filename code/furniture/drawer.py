import random

from direct.showbase import ShowBaseGlobal
from panda3d.core import CardMaker, Filename, NodePath, PNMImage, Point3, Texture, TransparencyAttrib
from ursina import Audio, Entity, Vec3, camera, color, time

from map.map_data import CELL, PROJECT_DIR


DRAWER_MODEL_PATH = PROJECT_DIR / 'asset' / 'model' / 'drawer.glb'
KEY_MODEL_PATH = PROJECT_DIR / 'asset' / 'model' / 'key.glb'
DRAWER_SHADOW_Y = 0.012
DRAWER_SHADOW_ALPHA = 70
DRAWER_MODEL_TARGET_W = 1.28
DRAWER_MODEL_TARGET_H = 1.38
DRAWER_COLLIDER_SHRINK = 0.98
DRAWER_WALL_CLEARANCE = 0.04
DRAWER_OPEN_DISTANCE = 30
DRAWER_OPEN_SPEED = 10.0
DRAWER_INTERACT_RAY_DISTANCE = CELL * 0.4
DRAWER_INTERACT_PAD = 0.025
DRAWER_AIM_TIE_DISTANCE = 0.18
DRAWER_LIGHT_RGB = (255, 228, 172)
DRAWER_LIGHT_BOOST = 1.7
DRAWER_MIN_LIGHT = 0.36
DRAWER_FACE_ROTATIONS = {
    'north': 180,
    'south': 0,
    'west': -90,
    'east': 90,
}
DRAWER_BODY_NODE = 'vintage_wooden_drawer_01_body'
KEY_DRAWER_NODE = 'vintage_wooden_drawer_01_drawer02'
KEY_MODEL_TARGET_LONG = 0.18
KEY_LIGHT_RGB = (255, 225, 100)
KEY_LIGHT_BOOST = 2.2
KEY_MIN_LIGHT = 0.75
KEY_GLOW_SCALE = 1.01
KEY_PICKUP_MIN_OPEN = 0.45
KEY_INTERACT_PAD = 0.12
HELD_KEY_TEXTURE = 'asset/model/key_preview.png'
HELD_KEY_POS = (0.62, -0.35, -0.8)
HELD_KEY_SCALE = (0.16, 0.16)
HELD_KEY_ROT_Z = -45
KEY_GET_VOLUME = 1.0
PAPER_GET_VOLUME = 1.0
HELD_NOTE_START_POS = (-0.66, -0.40, -0.80)
HELD_NOTE_SPACING = 0.118
HELD_NOTE_SCALE = (0.1, 0.1)
START_ROOM_WALL_NOTE_SIZE = (0.25, 0.25)
START_ROOM_WALL_NOTE_Y = 1.15
START_ROOM_WALL_NOTE_OFFSET = 0.035
START_ROOM_WALL_NOTES = (
    ('asset/texture/note1.png', -0.34, -0.04, -18),
    ('asset/texture/note2.png', 0.00, 0.08, 9),
    ('asset/texture/note3.png', 0.34, -0.03, 24),
)
NOTE_PICKUP_MIN_OPEN = 0.45
NOTE_COUNT = 5
NOTE_DRAWER_NAMES = (
    'vintage_wooden_drawer_01_drawer01',
    'vintage_wooden_drawer_01_drawer02',
    'vintage_wooden_drawer_01_drawer03',
    'vintage_wooden_drawer_01_drawer04',
    'vintage_wooden_drawer_01_drawer05',
    'vintage_wooden_drawer_01_drawer06',
)
NOTE_NUMBER_CHOICES = tuple(str(number) for number in range(1, 10))
NOTE_SIZE = 0.08
NOTE_BLOOD_SIZE_MIN = 0.26
NOTE_BLOOD_SIZE_MAX = 0.5
NOTE_BLOOD_MARGIN = 0.025
NOTE_LIGHT_RGB = (255, 244, 208)
NOTE_LIGHT_BOOST = 1.55
NOTE_MIN_LIGHT = 0.58
NOTE_ROTATIONS = (-7, 5, -3, 8, -5)
NOTE_SURFACE_LIFT = 0.01
NOTE_POSITION_JITTER = 0.08
NOTE_ROTATION_JITTER = 60.0


class DrawerMixin:
    def init_drawer_assets(self):
        self.drawer_model = self.load_drawer_model()
        self.drawer_model_scale = self.fit_drawer_model_scale(self.drawer_model)
        self.drawer_model_size = self.model_size(self.drawer_model, self.drawer_model_scale)
        self.key_model = self.load_key_model()
        self.key_model_scale = self.fit_key_model_scale(self.key_model)
        self.note_placements = []
        self.note_placement_lookup = {}
        self.note_textures = {}
        self.has_key = False
        self.held_key_entity = None
        self.collected_notes = set()
        self.held_note_entities = {}
        self.held_note_placeholders = []
        self.key_get_sound = Audio('asset/sound/key_get.wav', autoplay=False, volume=KEY_GET_VOLUME)
        self.paper_get_sound = Audio('asset/sound/paper.wav', autoplay=False, volume=PAPER_GET_VOLUME)

    def set_sound_volume(self, sound, volume):
        try:
            sound.volume = volume
        except Exception:
            pass

        for attr in ('sound', '_sound', 'audio', '_audio'):
            inner = getattr(sound, attr, None)

            if inner and hasattr(inner, 'setVolume'):
                try:
                    inner.setVolume(volume)
                except Exception:
                    pass

    def play_sound(self, sound, volume=None, start=None):
        if volume is not None:
            self.set_sound_volume(sound, volume)

        sound.stop()

        if start is None:
            sound.play()
        else:
            sound.play(start=start)

    def load_drawer_model(self):
        scene = ShowBaseGlobal.base.loader.loadModel(Filename.fromOsSpecific(str(DRAWER_MODEL_PATH)))

        if scene.isEmpty():
            raise RuntimeError(f'Failed to load drawer model: {DRAWER_MODEL_PATH}')

        model = NodePath('drawer_template')
        scene.copyTo(model)
        scene.removeNode()

        self.prepare_drawer_model(model, normalize=True)
        return model

    def load_key_model(self):
        scene = ShowBaseGlobal.base.loader.loadModel(Filename.fromOsSpecific(str(KEY_MODEL_PATH)))

        if scene.isEmpty():
            raise RuntimeError(f'Failed to load key model: {KEY_MODEL_PATH}')

        model = NodePath('key_template')
        scene.copyTo(model)
        scene.removeNode()

        self.prepare_key_model(model, normalize=True)
        return model

    def choose_note_placements(self):
        room_cells = sorted({
            room_cell
            for rooms in self._cell_door_rooms.values()
            for room_cell in rooms
            if room_cell != self.start_room_cell
        })
        selected_rooms = random.sample(room_cells, min(NOTE_COUNT, len(room_cells)))
        numbers = random.sample(NOTE_NUMBER_CHOICES, len(selected_rooms))
        self.note_placements = []
        self.note_placement_lookup = {}

        for index, (room_cell, number) in enumerate(zip(selected_rooms, numbers), start=1):
            drawer_name = random.choice(NOTE_DRAWER_NAMES)
            key = (room_cell, drawer_name)
            placement = {
                'key': key,
                'room_cell': room_cell,
                'drawer_name': drawer_name,
                'number': number,
                'blood_count': index,
            }
            self.note_placements.append(placement)
            self.note_placement_lookup[key] = placement

        self.note_textures = self.load_note_textures()

    def note_keypad_code(self):
        return ''.join(
            placement['number']
            for placement in sorted(self.note_placements, key=lambda item: item['blood_count'])
        )

    def load_note_textures(self):
        textures = {}
        blood_path = PROJECT_DIR / 'asset' / 'texture' / 'blood.png'
        blood_image = PNMImage()

        if not blood_image.read(Filename.fromOsSpecific(str(blood_path))):
            return textures

        for placement in self.note_placements:
            number = placement['number']
            path = PROJECT_DIR / 'asset' / 'texture' / f'{number}.png'
            note_image = PNMImage()

            if not note_image.read(Filename.fromOsSpecific(str(path))):
                continue

            rng = random.Random(f'note_texture:{placement["key"]}:{number}')
            self.multiply_blood_onto_note(note_image, blood_image, placement['blood_count'], rng)
            texture = Texture(f'note_{placement["room_cell"]}_{placement["drawer_name"]}_{number}')
            texture.load(note_image)
            textures[placement['key']] = texture

        return textures

    def multiply_blood_onto_note(self, note_image, blood_image, count, rng):
        spots = self.non_overlapping_blood_spots(
            count,
            min(note_image.getXSize(), note_image.getYSize()),
            rng,
        )

        for center_x, center_y, size in spots:
            self.multiply_blood_spot(note_image, blood_image, center_x, center_y, size)

    def multiply_blood_spot(self, note_image, blood_image, center_x, center_y, size):
        note_w = note_image.getXSize()
        note_h = note_image.getYSize()
        blood_w = blood_image.getXSize()
        blood_h = blood_image.getYSize()
        half = size * 0.5
        x0 = max(0, int(center_x - half))
        y0 = max(0, int(center_y - half))
        x1 = min(note_w - 1, int(center_x + half))
        y1 = min(note_h - 1, int(center_y + half))

        if size <= 0:
            return

        for y in range(y0, y1 + 1):
            blood_y = int(((y - (center_y - half)) / size) * (blood_h - 1))
            blood_y = max(0, min(blood_h - 1, blood_y))

            for x in range(x0, x1 + 1):
                blood_x = int(((x - (center_x - half)) / size) * (blood_w - 1))
                blood_x = max(0, min(blood_w - 1, blood_x))
                blood_alpha = blood_image.getAlpha(blood_x, blood_y) if blood_image.hasAlpha() else 1.0

                if blood_alpha <= 0.01:
                    continue

                note_rgb = note_image.getXel(x, y)
                blood_rgb = blood_image.getXel(blood_x, blood_y)
                amount = blood_alpha * 0.95
                multiplied = (
                    note_rgb.x * blood_rgb.x,
                    note_rgb.y * blood_rgb.y,
                    note_rgb.z * blood_rgb.z,
                )
                note_image.setXel(
                    x,
                    y,
                    note_rgb.x * (1.0 - amount) + multiplied[0] * amount,
                    note_rgb.y * (1.0 - amount) + multiplied[1] * amount,
                    note_rgb.z * (1.0 - amount) + multiplied[2] * amount,
                )

    def non_overlapping_blood_spots(self, count, base_size, rng):
        spots = []

        for _ in range(count):
            size = rng.uniform(NOTE_BLOOD_SIZE_MIN, NOTE_BLOOD_SIZE_MAX) * base_size
            margin = NOTE_BLOOD_MARGIN * base_size + size * 0.5
            min_x = margin
            max_x = base_size - margin
            min_y = margin
            max_y = base_size - margin
            candidate = None

            if min_x > max_x or min_y > max_y:
                continue

            for _ in range(80):
                x = rng.uniform(min_x, max_x)
                y = rng.uniform(min_y, max_y)

                if all(
                    ((x - px) ** 2 + (y - py) ** 2) ** 0.5 >= (size + psize) * 0.48
                    for px, py, psize in spots
                ):
                    candidate = (x, y, size)
                    break

            if candidate is None:
                grid = (
                    (0.28, 0.28), (0.72, 0.28), (0.50, 0.50),
                    (0.28, 0.72), (0.72, 0.72),
                )
                gx, gy = grid[len(spots) % len(grid)]
                candidate = (base_size * gx, base_size * gy, size)

            spots.append(candidate)

        return spots

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

    def prepare_key_model(self, model, normalize=False):
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
                    -(mn.y + mx.y) * 0.5,
                    -(mn.z + mx.z) * 0.5,
                )

    def fit_drawer_model_scale(self, model):
        bounds = model.getTightBounds()

        if not bounds:
            return 1.0

        mn, mx = bounds
        width = max(mx.x - mn.x, mx.z - mn.z, 0.001)
        height = max(mx.y - mn.y, 0.001)
        return min(DRAWER_MODEL_TARGET_W / width, DRAWER_MODEL_TARGET_H / height)

    def fit_key_model_scale(self, model):
        bounds = model.getTightBounds()

        if not bounds:
            return 1.0

        mn, mx = bounds
        longest = max(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z, 0.001)
        return KEY_MODEL_TARGET_LONG / longest

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

        self.add_start_room_wall_note(entities, cx, cz, face, west_x, north_z, east_x, south_z, near_lights)

        moving_nodes = self.drawer_moving_nodes(entity)
        body_node = self.drawer_body_node(entity)
        open_offset = self.drawer_open_offset(entity)

        for drawer_name, node, base_pos, bounds_min, bounds_max in moving_nodes:
            key = ('drawer', round(cz / CELL), round(cx / CELL), drawer_name)
            open_amount = 1.0 if self.drawer_states.get(key, False) else 0.0
            node.setPos(base_pos.x, base_pos.y, base_pos.z - open_offset * open_amount)
            key_data = self.add_key_to_drawer(entity, node, drawer_name, bounds_min, bounds_max, position, near_lights)
            note_data = self.add_note_to_drawer(entity, node, drawer_name, bounds_min, bounds_max, position, near_lights)
            self.active_drawers[key] = {
                'entity': entity,
                'node': node,
                'key': key_data,
                'key_node': key_data['node'] if key_data else None,
                'note': note_data,
                'base_pos': base_pos,
                'open_offset': open_offset,
                'bounds_min': bounds_min,
                'bounds_max': bounds_max,
                'body_node': body_node,
                'open': open_amount,
                'target': open_amount,
                'face': face,
                'position': position,
                'open_sound': Audio('asset/sound/drawer_open.wav', autoplay=False, volume=1.0),
                'close_sound': Audio('asset/sound/drawer_close.wav', autoplay=False, volume=1.0),
            }

    def add_start_room_wall_note(self, entities, cx, cz, face, west_x, north_z, east_x, south_z, near_lights):
        if (round(cz / CELL), round(cx / CELL)) != self.start_room_cell:
            return

        off = START_ROOM_WALL_NOTE_OFFSET
        for texture, along_offset, y_offset, roll in START_ROOM_WALL_NOTES:
            if face == 'north':
                position = (cx + along_offset, START_ROOM_WALL_NOTE_Y + y_offset, north_z + off)
                rotation_y = 180
            elif face == 'south':
                position = (cx + along_offset, START_ROOM_WALL_NOTE_Y + y_offset, south_z - off)
                rotation_y = 0
            elif face == 'west':
                position = (west_x + off, START_ROOM_WALL_NOTE_Y + y_offset, cz - along_offset)
                rotation_y = -90
            else:
                position = (east_x - off, START_ROOM_WALL_NOTE_Y + y_offset, cz + along_offset)
                rotation_y = 90

            light_val = self.light_system.light_at(position[0], position[1], position[2], near_lights)
            tint = self.light_system.shaded_color(NOTE_LIGHT_RGB, light_val * NOTE_LIGHT_BOOST, NOTE_MIN_LIGHT)
            note = Entity(
                model='quad',
                texture=texture,
                position=position,
                rotation=(0, rotation_y, roll),
                scale=(START_ROOM_WALL_NOTE_SIZE[0], START_ROOM_WALL_NOTE_SIZE[1]),
                color=tint,
            )
            note.setTwoSided(True)
            note.setTransparency(TransparencyAttrib.MAlpha)
            entities.append(note)

    def add_key_to_drawer(self, entity, drawer_node, drawer_name, bounds_min, bounds_max, position, near_lights):
        room_cell = (round(position[2] / CELL), round(position[0] / CELL))

        if room_cell != self.start_room_cell or drawer_name != KEY_DRAWER_NODE:
            return None

        center = Point3(
            (bounds_min.x + bounds_max.x) * 0.5,
            bounds_min.y + (bounds_max.y - bounds_min.y) * 0.08,
            (bounds_min.z + bounds_max.z) * 0.5,
        )
        local_pos = drawer_node.getRelativePoint(entity, center)
        light_val = self.light_system.light_at(position[0], center.y, position[2], near_lights)
        tint = self.light_system.shaded_color(KEY_LIGHT_RGB, light_val * KEY_LIGHT_BOOST, KEY_MIN_LIGHT)

        key_node = self.key_model.copyTo(drawer_node)
        self.prepare_key_model(key_node)
        key_node.setPos(local_pos)
        key_node.setHpr(0, 0, 45)
        key_node.setScale(self.key_model_scale / max(abs(entity.scale_z), 0.001))
        key_node.setColorScale(tint.r, tint.g, tint.b, 1.0)

        glow_node = self.key_model.copyTo(drawer_node)
        self.prepare_key_model(glow_node)
        glow_node.setPos(local_pos)
        glow_node.setHpr(0, 0, 45)
        glow_node.setScale(key_node.getScale() * KEY_GLOW_SCALE)
        glow_node.setColorScale(1.0, 0.86, 0.12, 0.42)
        glow_node.setTransparency(TransparencyAttrib.MAlpha)
        glow_node.setDepthWrite(False)
        glow_node.hide()

        return {
            'node': key_node,
            'glow': glow_node,
        }

    def add_note_to_drawer(self, entity, drawer_node, drawer_name, bounds_min, bounds_max, position, near_lights):
        room_cell = (round(position[2] / CELL), round(position[0] / CELL))

        placement = self.note_placement_lookup.get((room_cell, drawer_name))

        if not placement:
            return None

        number = placement['number']
        texture = self.note_textures.get(placement['key']) if number else None

        if not texture:
            return None

        index = placement['blood_count'] - 1
        rng = random.Random(f'{room_cell}:{drawer_name}:{number}')
        x_jitter = rng.uniform(-NOTE_POSITION_JITTER, NOTE_POSITION_JITTER)
        z_jitter = rng.uniform(-NOTE_POSITION_JITTER, NOTE_POSITION_JITTER)
        rotation_jitter = rng.uniform(-NOTE_ROTATION_JITTER, NOTE_ROTATION_JITTER)
        center = Point3(
            (bounds_min.x + bounds_max.x) * 0.5 + x_jitter,
            bounds_min.y + (bounds_max.y - bounds_min.y) * 0.12 + NOTE_SURFACE_LIFT,
            (bounds_min.z + bounds_max.z) * 0.5 + z_jitter,
        )
        local_pos = drawer_node.getRelativePoint(entity, center)
        light_val = self.light_system.light_at(position[0], center.y, position[2], near_lights)
        tint = self.light_system.shaded_color(NOTE_LIGHT_RGB, light_val * NOTE_LIGHT_BOOST, NOTE_MIN_LIGHT)

        card = CardMaker(f'note_{number}')
        card.setFrame(-NOTE_SIZE * 0.5, NOTE_SIZE * 0.5, -NOTE_SIZE * 0.5, NOTE_SIZE * 0.5)
        note_node = drawer_node.attachNewNode(card.generate())
        note_node.setTexture(texture, 1)
        note_node.setTransparency(TransparencyAttrib.MAlpha)
        note_node.setTwoSided(True)
        note_node.setPos(local_pos)
        note_node.setHpr(0, 0, NOTE_ROTATIONS[index] + rotation_jitter)
        note_node.setColorScale(tint.r, tint.g, tint.b, 1.0)

        return {
            'node': note_node,
            'number': number,
            'texture': texture,
            'blood_count': placement['blood_count'],
        }

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

    def drawer_ray_box_distance(self, origin, ray, mn, mx, pad=DRAWER_INTERACT_PAD):
        t_min = 0.0
        t_max = DRAWER_INTERACT_RAY_DISTANCE

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

        return self.drawer_ray_box_distance(origin, ray, bounds[0], bounds[1], DRAWER_INTERACT_PAD)

    def drawer_aim_offset(self, drawer, origin, ray):
        bounds = self.drawer_world_bounds(drawer['node'])

        if not bounds:
            return float('inf')

        mn, mx = bounds
        cx = (mn.x + mx.x) * 0.5
        cy = (mn.y + mx.y) * 0.5
        cz = (mn.z + mx.z) * 0.5
        dx = cx - origin.x
        dy = cy - origin.y
        dz = cz - origin.z
        t = max(0.0, dx * ray.x + dy * ray.y + dz * ray.z)
        closest_x = origin.x + ray.x * t
        closest_y = origin.y + ray.y * t
        closest_z = origin.z + ray.z * t
        off_x = cx - closest_x
        off_y = cy - closest_y
        off_z = cz - closest_z
        return (off_x * off_x + off_y * off_y + off_z * off_z) ** 0.5

    def key_hit_distance(self, drawer, origin, ray):
        key_data = drawer.get('key')

        if self.has_key or not key_data or drawer.get('open', 0.0) < KEY_PICKUP_MIN_OPEN:
            return None

        key_node = key_data['node']
        if key_node.isHidden():
            return None

        bounds = self.drawer_world_bounds(key_node)

        if not bounds:
            return None

        return self.drawer_ray_box_distance(origin, ray, bounds[0], bounds[1])

    def note_hit_distance(self, drawer, origin, ray):
        note_data = drawer.get('note')

        if not note_data or drawer.get('open', 0.0) < NOTE_PICKUP_MIN_OPEN:
            return None

        note_node = note_data['node']
        if note_node.isHidden():
            return None

        bounds = self.drawer_world_bounds(note_node)

        if not bounds:
            return None

        return self.drawer_ray_box_distance(origin, ray, bounds[0], bounds[1])

    def nearest_key_ray_hit(self, origin, ray):
        nearest_key = None
        nearest_t = DRAWER_INTERACT_RAY_DISTANCE

        for key, drawer in self.active_drawers.items():
            entity = drawer['entity']

            if not entity.enabled:
                continue

            t = self.key_hit_distance(drawer, origin, ray)

            if t is not None and t < nearest_t:
                nearest_key = key
                nearest_t = t

        return nearest_key, nearest_t if nearest_key is not None else None

    def nearest_note_ray_hit(self, origin, ray):
        nearest_key = None
        nearest_t = DRAWER_INTERACT_RAY_DISTANCE

        for key, drawer in self.active_drawers.items():
            entity = drawer['entity']

            if not entity.enabled:
                continue

            t = self.note_hit_distance(drawer, origin, ray)

            if t is not None and t < nearest_t:
                nearest_key = key
                nearest_t = t

        return nearest_key, nearest_t if nearest_key is not None else None

    def update_key_glow(self, active_key):
        for key, drawer in self.active_drawers.items():
            key_data = drawer.get('key')

            if not key_data:
                continue

            glow = key_data['glow']
            if not self.has_key and key == active_key and drawer.get('open', 0.0) >= KEY_PICKUP_MIN_OPEN:
                glow.show()
            else:
                glow.hide()

    def pickup_key(self, key):
        drawer = self.active_drawers.get(key)
        key_data = drawer.get('key') if drawer else None

        if self.has_key or not key_data:
            return False

        self.has_key = True
        key_data['node'].hide()
        key_data['glow'].hide()
        self.play_sound(self.key_get_sound, KEY_GET_VOLUME)
        self.show_held_key()
        return True

    def pickup_note(self, key):
        drawer = self.active_drawers.get(key)
        note_data = drawer.get('note') if drawer else None

        if not note_data or key in self.collected_notes:
            return False

        self.collected_notes.add(key)
        note_data['node'].hide()
        self.play_sound(self.paper_get_sound, PAPER_GET_VOLUME)
        self.show_held_note(key, note_data)
        return True

    def collect_all_notes_cheat(self):
        collected_any = False
        for placement in self.note_placements:
            room_cell = placement['room_cell']
            drawer_name = placement['drawer_name']
            drawer_key = ('drawer', room_cell[0], room_cell[1], drawer_name)

            if drawer_key in self.collected_notes:
                continue

            self.collected_notes.add(drawer_key)
            collected_any = True

            drawer = self.active_drawers.get(drawer_key)
            if drawer:
                note_data = drawer.get('note')
                if note_data:
                    note_data['node'].hide()
                    self.show_held_note(drawer_key, note_data)
                    continue

            texture = self.note_textures.get(placement['key'])
            if texture:
                self.show_held_note(drawer_key, {'texture': texture})

        if collected_any:
            self.play_sound(self.paper_get_sound, PAPER_GET_VOLUME)

    def consume_key(self):
        if not self.has_key:
            return False

        self.has_key = False

        if self.held_key_entity:
            self.held_key_entity.enabled = False

        return True

    def reset_key_pickup(self):
        self.has_key = False

        if self.held_key_entity:
            self.held_key_entity.enabled = False

        for key, drawer in self.active_drawers.items():
            if key[1] == self.start_room_cell[0] and key[2] == self.start_room_cell[1]:
                self.drawer_states[key] = False
                drawer['open'] = 0.0
                drawer['target'] = 0.0
                base_pos = drawer['base_pos']
                drawer['node'].setPos(base_pos.x, base_pos.y, base_pos.z)

            note_data = drawer.get('note')

            if note_data:
                if key in self.collected_notes:
                    note_data['node'].hide()
                else:
                    note_data['node'].show()

            key_data = drawer.get('key')

            if not key_data:
                continue

            key_data['node'].show()
            key_data['glow'].hide()

    def show_held_key(self):
        if self.held_key_entity:
            self.held_key_entity.enabled = True
            return

        self.held_key_entity = Entity(
            parent=camera.ui,
            model='quad',
            texture=HELD_KEY_TEXTURE,
            position=HELD_KEY_POS,
            rotation=(0, 0, HELD_KEY_ROT_Z),
            scale=HELD_KEY_SCALE,
            color=color.white,
        )
        self.held_key_entity.always_on_top = True

    def _note_ui_node(self, name, index, texture=None, color_rgba=None, bin_sort=101):
        ux = HELD_NOTE_START_POS[0] + HELD_NOTE_SPACING * index
        uy = HELD_NOTE_START_POS[1]
        uz = HELD_NOTE_START_POS[2]
        np = Entity(
            parent=camera.ui,
            model='quad',
            position=(ux, uy, uz),
            scale=HELD_NOTE_SCALE,
            color=color.rgba(*color_rgba) if color_rgba else color.white,
        )
        if texture:
            np.model.setTexture(texture, 1)
        np.setTransparency(TransparencyAttrib.MAlpha)
        # Ursina camera.ui: x=가로, y=세로, z=렌더링순서
        # Panda3D setPos:   x=가로, y=렌더링순서, z=세로
        np.always_on_top = True
        np.setBin('fixed', bin_sort)
        np.setDepthWrite(False)
        np.setDepthTest(False)
        return np

    def ensure_note_placeholders(self):
        if self.held_note_placeholders:
            return
        for i in range(NOTE_COUNT):
            ph = self._note_ui_node(f'note_ph_{i}', i, color_rgba=(0.12, 0.12, 0.12, 0.5), bin_sort=100)
            self.held_note_placeholders.append(ph)

    def show_held_note(self, key, note_data):
        if key in self.held_note_entities:
            self.held_note_entities[key].show()
            return

        self.ensure_note_placeholders()
        index = len(self.held_note_entities)
        np = self._note_ui_node(f'held_note_{index}', index, texture=note_data['texture'], bin_sort=101)
        self.held_note_entities[key] = np

    def nearest_drawer_ray_hit(self, origin, ray):
        nearest_kind = None
        nearest_key = None
        nearest_t = DRAWER_INTERACT_RAY_DISTANCE
        nearest_aim_offset = float('inf')
        checked_bodies = set()

        for key, drawer in self.active_drawers.items():
            entity = drawer['entity']

            if not entity.enabled:
                continue

            t = self.drawer_hit_distance(drawer, origin, ray)

            if t is not None:
                aim_offset = self.drawer_aim_offset(drawer, origin, ray)
                is_better_aim = (
                    aim_offset + 1e-4 < nearest_aim_offset
                    and abs(t - nearest_t) <= DRAWER_AIM_TIE_DISTANCE
                )

                if t < nearest_t - DRAWER_AIM_TIE_DISTANCE or is_better_aim:
                    nearest_kind = 'drawer'
                    nearest_key = key
                    nearest_t = t
                    nearest_aim_offset = aim_offset

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
                nearest_aim_offset = float('inf')

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

    def nearest_interactable_drawer_key(self):
        origin, ray = self.camera_interaction_ray()
        nearest_key, _ = self.nearest_drawer_ray_hit(origin, ray)
        return nearest_key

    def toggle_drawer(self, key):
        drawer = self.active_drawers.get(key)

        if not drawer:
            return False

        is_open = self.drawer_states.get(key, False)
        self.drawer_states[key] = not is_open
        drawer['target'] = 1.0 if not is_open else 0.0

        self.play_sound(drawer['close_sound'] if is_open else drawer['open_sound'])
        return True

    def update_drawers(self):
        for key, drawer in list(self.active_drawers.items()):
            if not drawer['entity'].enabled:
                continue

            target = 1.0 if self.drawer_states.get(key, False) else 0.0
            current = drawer['open'] + (target - drawer['open']) * min(1.0, time.dt * DRAWER_OPEN_SPEED)
            drawer['open'] = current
            drawer['target'] = target

            base_pos = drawer['base_pos']
            drawer['node'].setPos(base_pos.x, base_pos.y, base_pos.z - drawer['open_offset'] * current)
