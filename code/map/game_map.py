import collections
import math

from ursina import Entity

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


class MapRenderer(DoorMixin, MeshBuilderMixin):
    def __init__(self, player, light_system, textures, start_room_cell):
        self.player = player
        self.light_system = light_system
        self.textures = textures
        self.start_room_cell = start_room_cell
        self.prebuilt_cells = {}
        self.prebuilt_rooms = {}
        self.prebuilt_lights = {}
        self._visible_cells = set()
        self._visible_rooms = set()
        self._visible_lights = set()
        self._collision_cells = set()
        self._collision_rooms = set()
        self.door_states = {}
        self.door_lock_states = {}
        self.drawer_states = {}
        self.active_doors = {}
        self.active_drawers = {}
        self.active_keypads = {}
        self.init_door_assets()

        self.walkable_cells = {
            (r, c)
            for r in range(ROWS)
            for c in range(COLS)
            if LAYOUT[r][c] == 0
        }
        self.build_door_lookup()

        self._raycast_cache_key = None
        self._ray_offsets = self.build_ray_offsets()

        self._hide_cell_queue = collections.deque()
        self._hide_room_queue = collections.deque()
        self._hide_light_queue = collections.deque()

        self.floor_collider = Entity(
            model='cube',
            visible=False,
            position=((COLS - 1) * CELL / 2, -0.06, (ROWS - 1) * CELL / 2),
            scale=(COLS * CELL, 0.1, ROWS * CELL),
            collider='box',
        )

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

    def collision_cells_near_player(self, center):
        cells = self.cells_near(center, COLLISION_ACTIVE_RADIUS)
        raw_cell = self.player_cell()

        if raw_cell != center:
            cells |= self.cells_near(raw_cell, COLLISION_ACTIVE_RADIUS)

        return cells

    def active_room_collision_cells(self, collision_cells):
        rooms = self.room_candidates_for_cells(collision_cells)
        raw_cell = self.player_cell()

        if raw_cell in self.prebuilt_rooms:
            rooms.add(raw_cell)

        return rooms

    def is_collision_entity(self, entity):
        return getattr(entity, '_collision_entity', False)

    def set_render_enabled(self, entities, enabled):
        for entity in entities:
            if not self.is_collision_entity(entity):
                entity.enabled = enabled

    def set_collision_enabled(self, entities, enabled):
        for entity in entities:
            if self.is_collision_entity(entity):
                entity.enabled = enabled

    def active_collision_entities(self):
        seen = set()

        for cell in self._collision_cells:
            for entity in self.prebuilt_cells.get(cell, ()):
                if not self.is_collision_entity(entity):
                    continue

                entity_id = id(entity)
                if entity_id not in seen:
                    seen.add(entity_id)
                    yield entity

        for room_cell in self._collision_rooms:
            for entity in self.prebuilt_rooms.get(room_cell, ()):
                if not self.is_collision_entity(entity):
                    continue

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
        player_half = self.player_collision_half_width()
        epsilon = 0.004

        for _ in range(4):
            moved = False
            px = self.player.x
            pz = self.player.z

            for entity in self.active_collision_entities():
                if not getattr(entity, 'enabled', True) or getattr(entity, 'collider', None) is None:
                    continue

                ex = float(entity.x)
                ez = float(entity.z)
                hx = self.collider_axis_value(entity, 'scale_x', 0, 0.0) * 0.5
                hz = self.collider_axis_value(entity, 'scale_z', 2, 0.0) * 0.5
                dx = px - ex
                dz = pz - ez
                overlap_x = player_half + hx - abs(dx)
                overlap_z = player_half + hz - abs(dz)

                if overlap_x <= 0 or overlap_z <= 0:
                    continue

                if overlap_x < overlap_z:
                    px += (1 if dx >= 0 else -1) * (overlap_x + epsilon)
                else:
                    pz += (1 if dz >= 0 else -1) * (overlap_z + epsilon)

                moved = True

            if not moved:
                return

            self.player.x = px
            self.player.z = pz

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

    def visible_cells_raycast(self, center):
        if center not in self.walkable_cells:
            return set()

        visible = {center}
        fx, fz = self.player_forward_xz()
        max_dist = RAY_RENDER_DISTANCE
        layout = LAYOUT
        half_cell = CELL * 0.5
        door_set = self._door_set

        ray_ox, ray_oz = self.player.x, self.player.z

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
        cache_key = (current, self.visibility_position_bucket(), self.visibility_heading_bucket(fx, fz))

        if not force and cache_key == self._raycast_cache_key:
            return

        self._raycast_cache_key = cache_key
        wanted_cells = self.visible_cells_raycast(current)
        wanted_cells |= self.cells_near(current, 2)
        wanted_rooms = self.room_candidates_for_cells(wanted_cells)
        wanted_lights = wanted_cells & self.light_system.cell_set
        collision_cells = self.collision_cells_near_player(current)
        collision_rooms = self.active_room_collision_cells(collision_cells)

        if force:
            for cell in self._visible_cells - wanted_cells:
                self.set_render_enabled(self.prebuilt_cells.get(cell, []), False)
            for cell in wanted_cells - self._visible_cells:
                self.set_render_enabled(self.prebuilt_cells.get(cell, []), True)
            for room_cell in self._visible_rooms - wanted_rooms:
                self.set_render_enabled(self.prebuilt_rooms.get(room_cell, []), False)
            for room_cell in wanted_rooms - self._visible_rooms:
                self.set_render_enabled(self.prebuilt_rooms.get(room_cell, []), True)
            for cell in self._visible_lights - wanted_lights:
                for entity in self.prebuilt_lights.get(cell, []):
                    entity.enabled = False
            for cell in wanted_lights - self._visible_lights:
                for entity in self.prebuilt_lights.get(cell, []):
                    entity.enabled = True
        else:
            for cell in self._visible_cells - wanted_cells:
                self._hide_cell_queue.append(cell)
            for cell in wanted_cells - self._visible_cells:
                self.set_render_enabled(self.prebuilt_cells.get(cell, []), True)
            for room_cell in self._visible_rooms - wanted_rooms:
                self._hide_room_queue.append(room_cell)
            for room_cell in wanted_rooms - self._visible_rooms:
                self.set_render_enabled(self.prebuilt_rooms.get(room_cell, []), True)
            for cell in self._visible_lights - wanted_lights:
                self._hide_light_queue.append(cell)
            for cell in wanted_lights - self._visible_lights:
                for entity in self.prebuilt_lights.get(cell, []):
                    entity.enabled = True

        for cell in self._collision_cells - collision_cells:
            self.set_collision_enabled(self.prebuilt_cells.get(cell, []), False)

        for cell in collision_cells - self._collision_cells:
            self.set_collision_enabled(self.prebuilt_cells.get(cell, []), True)

        for room_cell in self._collision_rooms - collision_rooms:
            self.set_collision_enabled(self.prebuilt_rooms.get(room_cell, []), False)

        for room_cell in collision_rooms - self._collision_rooms:
            self.set_collision_enabled(self.prebuilt_rooms.get(room_cell, []), True)

        self._visible_cells = wanted_cells
        self._visible_rooms = wanted_rooms
        self._visible_lights = wanted_lights
        self._collision_cells = collision_cells
        self._collision_rooms = collision_rooms

    def process_queues(self):
        visible_cells = self._visible_cells
        visible_rooms = self._visible_rooms
        visible_lights = self._visible_lights

        remaining = SHOW_PER_FRAME
        while self._hide_cell_queue and remaining > 0:
            cell = self._hide_cell_queue.popleft()
            if cell not in visible_cells:
                self.set_render_enabled(self.prebuilt_cells.get(cell, []), False)
            remaining -= 1

        remaining = SHOW_PER_FRAME
        while self._hide_room_queue and remaining > 0:
            room_cell = self._hide_room_queue.popleft()
            if room_cell not in visible_rooms:
                self.set_render_enabled(self.prebuilt_rooms.get(room_cell, []), False)
            remaining -= 1

        while self._hide_light_queue:
            cell = self._hide_light_queue.popleft()
            if cell not in visible_lights:
                for entity in self.prebuilt_lights.get(cell, []):
                    entity.enabled = False

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
