import collections
import math

from ursina import Entity, color

from furniture.door import DoorMixin
from map.map_data import (
    BASEBOARD_OUT,
    CELL,
    COLS,
    COLLISION_ACTIVE_RADIUS,
    LAYOUT,
    RAY_COUNT,
    RAY_FOV_DEGREES,
    RAY_RENDER_DISTANCE,
    ROWS,
    SHOW_PER_FRAME,
    VISIBILITY_HEADING_BUCKETS,
    VISIBILITY_POSITION_BUCKETS,
    WALL_COLLIDER_LEN,
    WALL_COLLIDER_T,
    WALL_H,
)
from map.mesh_builder import MeshBuilderMixin


VISIBILITY_CACHE_LIMIT = 192
STATIC_CHUNK_SIZE = 4


class MapRenderer(DoorMixin, MeshBuilderMixin):
    def __init__(self, player, light_system, textures, start_room_cell):
        self.player = player
        self.light_system = light_system
        self.textures = textures
        self.start_room_cell = start_room_cell
        self.prebuilt_cells = {}
        self.prebuilt_rooms = {}
        self.prebuilt_static_chunks = {}
        self.prebuilt_light_chunks = {}
        self.prebuilt_cell_render_entities = {}
        self.prebuilt_cell_collision_entities = {}
        self.prebuilt_room_render_entities = {}
        self.prebuilt_room_collision_entities = {}
        self._visible_cells = set()
        self._visible_rooms = set()
        self._debug_light_fixtures_disabled = False
        self._collision_cells = set()
        self._collision_rooms = set()
        self.door_states = {}
        self.door_lock_states = {}
        self.drawer_states = {}
        self.active_doors = {}
        self.active_drawers = {}
        self.active_keypads = {}
        self.active_doors_by_cell = collections.defaultdict(list)
        self.active_drawers_by_cell = collections.defaultdict(list)
        self.active_keypads_by_cell = collections.defaultdict(list)
        self._moving_door_keys = set()
        self._moving_drawer_keys = set()
        self._interaction_cache_result = None
        self._interaction_cache_pose = None
        self._interaction_cache_time = -999.0
        self._active_key_glow_key = None
        self.init_door_assets()

        self.walkable_cells = {
            (r, c)
            for r in range(ROWS)
            for c in range(COLS)
            if LAYOUT[r][c] == 0
        }
        self.door_room_cells = set()
        self.build_door_lookup()

        self._raycast_cache_key = None
        self._visibility_cache = collections.OrderedDict()
        self._ray_offsets = self.build_ray_offsets()
        self._open_neighbors = self.build_open_neighbor_cache()
        self._cells_near_cache = {}

        self._hide_cell_queue = collections.deque()
        self._hide_room_queue = collections.deque()
        self._hide_cell_queued = set()
        self._hide_room_queued = set()

        self.floor_collider = Entity(
            model='cube',
            visible=False,
            position=((COLS - 1) * CELL / 2, -0.06, (ROWS - 1) * CELL / 2),
            scale=(COLS * CELL, 0.1, ROWS * CELL),
            collider='box',
        )
        self.static_entities = []

    def wall_at(self, r, c):
        return r < 0 or r >= ROWS or c < 0 or c >= COLS or LAYOUT[r][c] != 0

    def build_static_world(self):
        layout = LAYOUT
        chunk_mesh_data = {}
        light_chunk_mesh_data = {}

        for r in range(ROWS):
            for c in range(COLS):
                if layout[r][c] != 0:
                    continue

                chunk = (r // STATIC_CHUNK_SIZE, c // STATIC_CHUNK_SIZE)
                mesh_data = chunk_mesh_data.get(chunk)
                if mesh_data is None:
                    mesh_data = self.new_mesh_data()
                    chunk_mesh_data[chunk] = mesh_data

                near_lights = self.light_system.cell_cache.get((r, c), self.light_system.positions)
                self.add_subdivided_floor(mesh_data, r, c, near_lights)
                self.add_static_light_fixture(light_chunk_mesh_data, chunk, r, c)

                x0 = c * CELL - CELL / 2
                x1 = c * CELL + CELL / 2
                z0 = r * CELL - CELL / 2
                z1 = r * CELL + CELL / 2

                if self.wall_at(r - 1, c):
                    has_door = self.should_add_door(r, c, 'north')
                    add_wall = self.add_wall_with_baseboard_gap if has_door else self.add_wall_with_baseboard
                    add_wall(mesh_data, x0, z0, x1, z0, 0, BASEBOARD_OUT, near_lights, not has_door)

                if self.wall_at(r + 1, c):
                    has_door = self.should_add_door(r, c, 'south')
                    add_wall = self.add_wall_with_baseboard_gap if has_door else self.add_wall_with_baseboard
                    add_wall(mesh_data, x1, z1, x0, z1, 0, -BASEBOARD_OUT, near_lights, not has_door)

                if self.wall_at(r, c - 1):
                    has_door = self.should_add_door(r, c, 'west')
                    add_wall = self.add_wall_with_baseboard_gap if has_door else self.add_wall_with_baseboard
                    add_wall(mesh_data, x0, z1, x0, z0, BASEBOARD_OUT, 0, near_lights, not has_door)

                if self.wall_at(r, c + 1):
                    has_door = self.should_add_door(r, c, 'east')
                    add_wall = self.add_wall_with_baseboard_gap if has_door else self.add_wall_with_baseboard
                    add_wall(mesh_data, x1, z0, x1, z1, -BASEBOARD_OUT, 0, near_lights, not has_door)

        chunk_items = list(chunk_mesh_data.items())
        for chunk, mesh_data in chunk_items:
            entities = []
            for data in mesh_data.values():
                entity = self.add_mesh_entity(data)
                if entity:
                    entities.append(entity)
                    self.static_entities.append(entity)

            if entities:
                self.prebuilt_static_chunks[chunk] = tuple(entities)

        for chunk, mesh_data in light_chunk_mesh_data.items():
            entities = []
            for data in mesh_data.values():
                entity = self.add_mesh_entity(data)
                if entity:
                    entities.append(entity)
                    self.static_entities.append(entity)

            if entities:
                self.prebuilt_light_chunks[chunk] = tuple(entities)

    def add_static_light_fixture(self, chunk_mesh_data, chunk, r, c):
        mesh_data = chunk_mesh_data.get(chunk)
        if mesh_data is None:
            mesh_data = self.new_mesh_data()
            chunk_mesh_data[chunk] = mesh_data

        data = mesh_data['fixture']
        x = c * CELL
        y = WALL_H - 0.035
        z = r * CELL
        hx = 0.78 * 0.5
        hy = 0.025 * 0.5
        hz = 0.78 * 0.5
        color_value = color.Color(1.0, 1.0, 245 / 255, 1.0)

        corners = {
            'lbn': (x - hx, y - hy, z - hz),
            'rbn': (x + hx, y - hy, z - hz),
            'rtn': (x + hx, y + hy, z - hz),
            'ltn': (x - hx, y + hy, z - hz),
            'lbf': (x - hx, y - hy, z + hz),
            'rbf': (x + hx, y - hy, z + hz),
            'rtf': (x + hx, y + hy, z + hz),
            'ltf': (x - hx, y + hy, z + hz),
        }
        faces = (
            ('lbn', 'rbn', 'rtn', 'ltn'),
            ('rbf', 'lbf', 'ltf', 'rtf'),
            ('lbf', 'lbn', 'ltn', 'ltf'),
            ('rbn', 'rbf', 'rtf', 'rtn'),
            ('ltn', 'rtn', 'rtf', 'ltf'),
            ('lbf', 'rbf', 'rbn', 'lbn'),
        )

        for face in faces:
            start = len(data['vertices'])
            data['vertices'].extend(corners[key] for key in face)
            data['triangles'].extend((start, start + 1, start + 2, start, start + 2, start + 3))
            data['triangles'].extend((start + 2, start + 1, start, start + 3, start + 2, start))
            data['uvs'].extend(((0, 0), (1, 0), (1, 1), (0, 1)))
            data['colors'].extend((color_value,) * 4)

    def _build_door_entities(self, r, c):
        entities = []
        x = c * CELL
        z = r * CELL
        near_lights = self.light_system.cell_cache.get((r, c), self.light_system.positions)
        layout = LAYOUT

        for face, (tr, tc) in (
            ('north', (r - 1, c)),
            ('south', (r + 1, c)),
            ('west',  (r, c - 1)),
            ('east',  (r, c + 1)),
        ):
            has_wall = tr < 0 or tr >= ROWS or tc < 0 or tc >= COLS or layout[tr][tc] == 1
            if not has_wall:
                continue
            if not self.should_add_door(r, c, face):
                continue
            wc = self.add_door_wall_colliders(entities, x, z, face)
            entities.append(wc)
            self.add_door_decoration(entities, x, z, face, near_lights, wc)

        return entities

    def _active_interactive_colliders(self):
        seen = set()

        for cell_entities in self.prebuilt_cells.values():
            for entity in cell_entities:
                if not self.is_collision_entity(entity):
                    continue
                eid = id(entity)
                if eid not in seen:
                    seen.add(eid)
                    yield entity

        for room_entities in self.prebuilt_rooms.values():
            for entity in room_entities:
                if not self.is_collision_entity(entity):
                    continue
                eid = id(entity)
                if eid not in seen:
                    seen.add(eid)
                    yield entity

    def index_active_object(self, index, key, position):
        cell = (
            int((position[2] + CELL / 2) // CELL),
            int((position[0] + CELL / 2) // CELL),
        )
        index[cell].append(key)

    def active_items_near(self, items, index, max_distance):
        max_dist_sq = max_distance * max_distance
        radius_cells = max(1, int(math.ceil(max_distance / CELL)))
        seen = set()
        pr, pc = self.player_cell()

        for r in range(max(0, pr - radius_cells), min(ROWS, pr + radius_cells + 1)):
            for c in range(max(0, pc - radius_cells), min(COLS, pc + radius_cells + 1)):
                cell = (r, c)
                for key in index.get(cell, ()):
                    if key in seen:
                        continue
                    seen.add(key)
                    item = items.get(key)
                    if not item:
                        continue

                    entity = item.get('entity')
                    if entity is not None and not getattr(entity, 'enabled', True):
                        continue

                    x, _, z = item['position'] if 'position' in item else entity.position
                    dx = x - self.player.x
                    dz = z - self.player.z
                    if dx * dx + dz * dz <= max_dist_sq:
                        yield key, item

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
        cache_key = (center, radius)
        cached = self._cells_near_cache.get(cache_key)
        if cached is not None:
            return set(cached)

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

        self._cells_near_cache[cache_key] = frozenset(cells)
        return cells

    def collision_cells_near_player(self, center):
        cells = self.cells_near(center, COLLISION_ACTIVE_RADIUS)
        raw_cell = self.player_cell()

        if raw_cell != center:
            cells |= self.cells_near(raw_cell, COLLISION_ACTIVE_RADIUS)

        return cells

    def active_room_collision_cells(self, collision_cells):
        rooms = self.room_candidates_for_cells(collision_cells)
        raw_cell = self.player_cell()

        if raw_cell in self.door_room_cells:
            rooms.add(raw_cell)

        return rooms

    def preload_room_cells_near_player(self, center):
        cells = self.cells_near(center, 1)
        cells.add(self.player_cell())
        return self.room_candidates_for_cells(cells)

    def is_collision_entity(self, entity):
        return getattr(entity, '_collision_entity', False)

    def set_scene_attached(self, entity, attached):
        if getattr(entity, 'enabled', not attached) == attached:
            return
        entity.enabled = attached

    def split_entity_group(self, entities):
        render_entities = []
        collision_entities = []

        for entity in entities:
            if self.is_collision_entity(entity):
                collision_entities.append(entity)
            else:
                render_entities.append(entity)

        return tuple(render_entities), tuple(collision_entities)

    def ensure_dynamic_cell(self, cell):
        if cell in self.prebuilt_cells:
            return

        r, c = cell
        entities = tuple(self._build_door_entities(r, c))
        render_entities, collision_entities = self.split_entity_group(entities)

        self.prebuilt_cells[cell] = entities
        self.prebuilt_cell_render_entities[cell] = render_entities
        self.prebuilt_cell_collision_entities[cell] = collision_entities
        self.set_render_enabled(render_entities, False)

    def ensure_dynamic_room(self, room_cell):
        if room_cell in self.prebuilt_rooms:
            return

        entities = tuple(self.build_door_room(room_cell))
        render_entities, collision_entities = self.split_entity_group(entities)

        self.prebuilt_rooms[room_cell] = entities
        self.prebuilt_room_render_entities[room_cell] = render_entities
        self.prebuilt_room_collision_entities[room_cell] = collision_entities
        self.set_render_enabled(render_entities, False)

    def ensure_dynamic_content(self, cells, rooms):
        for cell in cells:
            self.ensure_dynamic_cell(cell)

        for room_cell in rooms:
            self.ensure_dynamic_room(room_cell)

    def set_render_enabled(self, entities, enabled):
        for entity in entities:
            self.set_scene_attached(entity, enabled)

    def set_cell_render_enabled(self, cell, enabled):
        self.set_render_enabled(self.prebuilt_cell_render_entities.get(cell, ()), enabled)

    def static_chunk_for_cell(self, cell):
        r, c = cell
        return r // STATIC_CHUNK_SIZE, c // STATIC_CHUNK_SIZE

    def active_collision_entities(self):
        seen = set()

        for cell in self._collision_cells:
            for entity in self.prebuilt_cell_collision_entities.get(cell, ()):
                entity_id = id(entity)
                if entity_id not in seen:
                    seen.add(entity_id)
                    yield entity

        for room_cell in self._collision_rooms:
            for entity in self.prebuilt_room_collision_entities.get(room_cell, ()):
                entity_id = id(entity)
                if entity_id not in seen:
                    seen.add(entity_id)
                    yield entity

    def collider_axis_value(self, entity, attr, index, fallback):
        value = getattr(entity, attr, None)
        if value is not None:
            return abs(float(value))

        scale = getattr(entity, 'scale', None)
        if scale is not None:
            try:
                return abs(float(scale[index]))
            except (TypeError, IndexError, ValueError):
                pass

        return fallback

    def player_collision_half_width(self):
        collider = getattr(self.player, 'collider', None)
        size = getattr(collider, 'size', None)

        if size is not None:
            sx = getattr(size, 'x', None)
            sz = getattr(size, 'z', None)

            if sx is not None and sz is not None:
                return max(float(sx), float(sz)) * 0.5

            try:
                return max(float(size[0]), float(size[2])) * 0.5
            except (TypeError, IndexError, ValueError):
                pass

        return 0.21

    def resolve_player_collision(self):
        HALF_W = self.player_collision_half_width()
        epsilon = 0.012
        half_cell = CELL * 0.5
        layout = LAYOUT

        collision_entities = [
            (float(e.x), float(e.z),
             self.collider_axis_value(e, 'scale_x', 0, 0.0) * 0.5,
             self.collider_axis_value(e, 'scale_z', 2, 0.0) * 0.5)
            for e in self.active_collision_entities()
            if getattr(e, 'enabled', True) and getattr(e, 'collider', None) is not None
        ]

        for _ in range(8):
            moved = False
            px = self.player.x
            pz = self.player.z

            cell_c = int((px + half_cell) // CELL)
            cell_r = int((pz + half_cell) // CELL)

            for dr in range(-1, 2):
                for dc in range(-1, 2):
                    r = cell_r + dr
                    c = cell_c + dc
                    if not (0 <= r < ROWS and 0 <= c < COLS):
                        continue
                    if (r, c) in self.door_room_cells:
                        continue
                    if layout[r][c] == 0:
                        continue

                    wall_cx = c * CELL
                    wall_cz = r * CELL
                    dx = px - wall_cx
                    dz = pz - wall_cz
                    overlap_x = HALF_W + half_cell - abs(dx)
                    overlap_z = HALF_W + half_cell - abs(dz)

                    if overlap_x <= 0 or overlap_z <= 0:
                        continue

                    if overlap_x < overlap_z:
                        px += (1 if dx >= 0 else -1) * (overlap_x + epsilon)
                    else:
                        pz += (1 if dz >= 0 else -1) * (overlap_z + epsilon)

                    moved = True

            for ex, ez, hx, hz in collision_entities:
                dx = px - ex
                dz = pz - ez
                overlap_x = HALF_W + hx - abs(dx)
                overlap_z = HALF_W + hz - abs(dz)

                if overlap_x <= 0 or overlap_z <= 0:
                    continue

                if overlap_x < overlap_z:
                    push = 1 if dx >= 0 else -1
                    px = ex + push * (HALF_W + hx + epsilon)
                else:
                    push = 1 if dz >= 0 else -1
                    pz = ez + push * (HALF_W + hz + epsilon)

                moved = True

            if not moved:
                return

            self.player.x = px
            self.player.z = pz

    def expand_cells(self, cells, radius=1):
        if radius == 1:
            out = set()
            for cell in cells:
                out.update(self._open_neighbors.get(cell, ()))
            return out

        out = set(cells)

        for cr, cc in cells:
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    r = cr + dr
                    c = cc + dc

                    if 0 <= r < ROWS and 0 <= c < COLS and LAYOUT[r][c] == 0:
                        out.add((r, c))

        return out

    def build_open_neighbor_cache(self):
        neighbors = {}

        for r in range(ROWS):
            for c in range(COLS):
                visible = []

                for dr in (-1, 0, 1):
                    nr = r + dr
                    if nr < 0 or nr >= ROWS:
                        continue

                    for dc in (-1, 0, 1):
                        nc = c + dc
                        if 0 <= nc < COLS and LAYOUT[nr][nc] == 0:
                            visible.append((nr, nc))

                neighbors[(r, c)] = tuple(visible)

        return neighbors

    def cell_center(self, cell):
        r, c = cell
        return c * CELL, r * CELL

    def player_forward_xz(self):
        forward = self.player.forward
        fx = forward.x
        fz = forward.z
        length = max((fx * fx + fz * fz) ** 0.5, 0.001)
        return fx / length, fz / length

    def build_ray_offsets(self):
        ray_count = max(1, RAY_COUNT)

        if ray_count == 1:
            return [(1.0, 0.0)]

        half_fov = RAY_FOV_DEGREES * 0.5
        offsets = []

        for i in range(ray_count):
            angle = -half_fov + (RAY_FOV_DEGREES * i / (ray_count - 1))
            rad = math.radians(angle)
            offsets.append((math.cos(rad), math.sin(rad)))

        return offsets

    def visibility_heading_bucket(self, fx, fz):
        step = math.tau / VISIBILITY_HEADING_BUCKETS
        return int(round(math.atan2(fz, fx) / step)) % VISIBILITY_HEADING_BUCKETS

    def visibility_position_bucket(self):
        raw_cell = self.player_cell()
        r, c = raw_cell
        local_x = (self.player.x - (c * CELL - CELL * 0.5)) / CELL
        local_z = (self.player.z - (r * CELL - CELL * 0.5)) / CELL
        bx = max(0, min(VISIBILITY_POSITION_BUCKETS - 1, int(local_x * VISIBILITY_POSITION_BUCKETS)))
        bz = max(0, min(VISIBILITY_POSITION_BUCKETS - 1, int(local_z * VISIBILITY_POSITION_BUCKETS)))
        return bx, bz

    def visibility_bucket_origin(self, center, position_bucket):
        r, c = center
        bx, bz = position_bucket
        bucket_size = CELL / VISIBILITY_POSITION_BUCKETS
        x = c * CELL - CELL * 0.5 + (bx + 0.5) * bucket_size
        z = r * CELL - CELL * 0.5 + (bz + 0.5) * bucket_size
        return x, z

    def visibility_bucket_forward(self, heading_bucket):
        step = math.tau / VISIBILITY_HEADING_BUCKETS
        angle = heading_bucket * step
        return math.cos(angle), math.sin(angle)

    def visible_cells_raycast(self, center, origin=None, forward=None):
        if center not in self.walkable_cells:
            return set()

        visible = {center}
        fx, fz = forward if forward is not None else self.player_forward_xz()
        max_dist = RAY_RENDER_DISTANCE
        layout = LAYOUT
        half_cell = CELL * 0.5
        door_set = self._door_set
        open_neighbors = self._open_neighbors

        ray_ox, ray_oz = origin if origin is not None else (self.player.x, self.player.z)

        for ca, sa in self._ray_offsets:
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
                    visible.update(open_neighbors[(r, c)])

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
                    visible.update(open_neighbors[(r, c)])
                    if layout[prev_r][prev_c] == 0 and (prev_r, prev_c, prev_face) in door_set:
                        pass
                    else:
                        break
                else:
                    visible.add((r, c))

        return self.expand_cells(visible, 1)

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
        position_bucket = self.visibility_position_bucket()
        heading_bucket = self.visibility_heading_bucket(fx, fz)
        cache_key = (current, position_bucket, heading_bucket)

        if not force and cache_key == self._raycast_cache_key:
            return

        self._raycast_cache_key = cache_key
        cached_visibility = self._visibility_cache.get(cache_key)
        if cached_visibility is None:
            origin = self.visibility_bucket_origin(current, position_bucket)
            forward = self.visibility_bucket_forward(heading_bucket)
            wanted_cells = set(self.visible_cells_raycast(current, origin, forward))
            wanted_cells |= self.cells_near(current, 2)
            cached_visibility = (
                frozenset(wanted_cells),
                frozenset(self.room_candidates_for_cells(wanted_cells)),
            )
            self._visibility_cache[cache_key] = cached_visibility
            if len(self._visibility_cache) > VISIBILITY_CACHE_LIMIT:
                self._visibility_cache.popitem(last=False)
        else:
            self._visibility_cache.move_to_end(cache_key)

        cached_cells, cached_rooms = cached_visibility
        wanted_cells = set(cached_cells)
        wanted_rooms = set(cached_rooms)
        wanted_rooms |= self.preload_room_cells_near_player(current)
        collision_cells = self.collision_cells_near_player(current)
        collision_rooms = self.active_room_collision_cells(collision_cells)
        wanted_dynamic_cells = wanted_cells | collision_cells
        wanted_dynamic_rooms = wanted_rooms | collision_rooms
        render_cells = wanted_cells
        render_rooms = wanted_rooms

        self.ensure_dynamic_content(wanted_dynamic_cells, wanted_dynamic_rooms)

        if force:
            for cell in self._visible_cells - render_cells:
                self.set_cell_render_enabled(cell, False)
            for cell in render_cells - self._visible_cells:
                self.set_cell_render_enabled(cell, True)
            for room_cell in self._visible_rooms - render_rooms:
                self.set_render_enabled(self.prebuilt_room_render_entities.get(room_cell, ()), False)
            for room_cell in render_rooms - self._visible_rooms:
                self.set_render_enabled(self.prebuilt_room_render_entities.get(room_cell, ()), True)
        else:
            for cell in self._visible_cells - render_cells:
                if cell not in self._hide_cell_queued:
                    self._hide_cell_queue.append(cell)
                    self._hide_cell_queued.add(cell)
            for cell in render_cells - self._visible_cells:
                self._hide_cell_queued.discard(cell)
                self.set_cell_render_enabled(cell, True)
            for room_cell in self._visible_rooms - render_rooms:
                if room_cell not in self._hide_room_queued:
                    self._hide_room_queue.append(room_cell)
                    self._hide_room_queued.add(room_cell)
            for room_cell in render_rooms - self._visible_rooms:
                self._hide_room_queued.discard(room_cell)
                self.set_render_enabled(self.prebuilt_room_render_entities.get(room_cell, ()), True)

        self._visible_cells = render_cells
        self._visible_rooms = render_rooms
        self._collision_cells = collision_cells
        self._collision_rooms = collision_rooms

    def process_queues(self):
        visible_cells = self._visible_cells
        visible_rooms = self._visible_rooms

        remaining = SHOW_PER_FRAME
        while self._hide_cell_queue and remaining > 0:
            cell = self._hide_cell_queue.popleft()
            self._hide_cell_queued.discard(cell)
            if cell not in visible_cells:
                self.set_cell_render_enabled(cell, False)
            remaining -= 1

        remaining = SHOW_PER_FRAME
        while self._hide_room_queue and remaining > 0:
            room_cell = self._hide_room_queue.popleft()
            self._hide_room_queued.discard(room_cell)
            if room_cell not in visible_rooms:
                self.set_render_enabled(self.prebuilt_room_render_entities.get(room_cell, ()), False)
            remaining -= 1

    def split_entity_groups(self, groups):
        render_groups = {}
        collision_groups = {}

        for key, entities in groups.items():
            render_entities = []
            collision_entities = []

            for entity in entities:
                if self.is_collision_entity(entity):
                    collision_entities.append(entity)
                else:
                    render_entities.append(entity)

            render_groups[key] = tuple(render_entities)
            collision_groups[key] = tuple(collision_entities)

        return render_groups, collision_groups

    def disable_prebuilt_dynamic_entities(self):
        for entities in self.prebuilt_cell_render_entities.values():
            self.set_render_enabled(entities, False)
        for entities in self.prebuilt_room_render_entities.values():
            self.set_render_enabled(entities, False)

    def set_light_fixtures_debug_enabled(self, enabled):
        self._debug_light_fixtures_disabled = not enabled
        for entities in self.prebuilt_light_chunks.values():
            self.set_render_enabled(entities, enabled)
        self.update_rendered_scene(force=True)

    def initial_render(self):
        self.build_static_world()
        self.disable_prebuilt_dynamic_entities()
        self.update_rendered_scene(force=True)
