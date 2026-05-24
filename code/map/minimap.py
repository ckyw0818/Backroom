import random
from math import atan2, degrees, sin, sqrt

from panda3d.core import PNMImage, Texture as PandaTexture
from ursina import Audio, Entity, Mesh, Shader, Texture, Vec2, camera, color, time


MINIMAP_ENABLED = False

MINIMAP_SIZE = 0.3
MINIMAP_POSITION = (0.0, 0.0)

MINIMAP_WORLD_RANGE = 70
MINIMAP_INNER = 0.88

SCAN_RADIUS_CELLS = 14
SCAN_PULSE_TIME = 0.8
MONSTER_PULSE_TIME = 0.65

PLAYER_TRI_W = 0.017
PLAYER_TRI_H = 0.022
MONSTER_DOT_SCALE = 0.016
WARN_PITCH_STEP = 0.5
GLITCH_SCANLINES = 9
STATIC_NOISE_SIZE = 96
STATIC_NOISE_FRAMES = 10
STATIC_NOISE_FPS = 10.0
GLITCH_START_CELLS = SCAN_RADIUS_CELLS + 0.8
GLITCH_MAX_CELLS = 1.15
GLITCH_SMOOTHING = 4.5

FLOOR_ALPHA = 155
ROOM_ALPHA = 130
FLOOR_SCALE = 0.52
EDGE_FADE = 0.20


def rgba(r, g, b, a):
    return color.Color(r / 255, g / 255, b / 255, a / 255)


MINIMAP_VIGNETTE_SHADER = Shader(
    name='minimap_vignette_shader',
    language=Shader.GLSL,
    vertex='''
#version 130
uniform mat4 p3d_ModelViewProjectionMatrix;
in vec4 p3d_Vertex;
out vec2 local_pos;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    local_pos = p3d_Vertex.xy;
}
''',
    fragment='''
#version 140
in vec2 local_pos;
out vec4 fragColor;
void main() {
    float d = length(local_pos) * 2.0;
    float v = smoothstep(0.22, 1.05, d);
    v = v * v * (3.0 - 2.0 * v);
    fragColor = vec4(0.038, 0.028, 0.008, v * 0.48);
}
''',
)


MINIMAP_MAP_SHADER = Shader(
    name='minimap_map_clip_shader',
    language=Shader.GLSL,
    vertex='''
#version 130
uniform mat4 p3d_ModelViewProjectionMatrix;
in vec4 p3d_Vertex;
in vec4 p3d_Color;
out vec2 local_pos;
out vec4 vertex_color;

void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    local_pos = p3d_Vertex.xy;
    vertex_color = p3d_Color;
}
''',
    fragment='''
#version 140
uniform vec4 p3d_ColorScale;
uniform vec2 map_offset;
uniform float clip_radius;
in vec2 local_pos;
in vec4 vertex_color;
out vec4 fragColor;

void main() {
    vec2 clip_pos = local_pos + map_offset;
    if (dot(clip_pos, clip_pos) > clip_radius * clip_radius) {
        discard;
    }
    fragColor = p3d_ColorScale * vertex_color;
}
''',
    default_input={
        'map_offset': Vec2(0.0, 0.0),
        'clip_radius': 0.1,
    },
)


class Minimap:
    def __init__(
        self,
        layout,
        cell_size,
        player,
        monster,
        cell_door_rooms=None,
        highlighted_room_cells=None,
        enabled=MINIMAP_ENABLED,
    ):
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
        self.highlighted_room_cells = frozenset(highlighted_room_cells or ())
        self.tiles = []
        self.room_tiles = []
        self.door_indicators = []
        self.floor_cells = []
        self.room_cells = []
        self.door_indicator_specs = []
        self.revealed_cells = set()
        self.map_anchor = (0.0, 0.0)
        self.map_dirty = True
        self.last_map_player_cell = None

        self.scanning = False
        self.scan_origin = (0, 0)
        self.scan_wave = 0.0
        self.scan_max = 0.0
        self.pending_monster_pulse_dists = [None for _ in self.monsters]
        self.pending_monster_warn_indices = [None for _ in self.monsters]

        self.has_monster_fixes = [False for _ in self.monsters]
        self.monster_fix_positions = [(0.0, 0.0) for _ in self.monsters]
        self.monster_pulse_ts = [MONSTER_PULSE_TIME for _ in self.monsters]
        self.glitch_amount = 0.0
        self.warn_sounds = [
            Audio('asset/sound/warn.wav', autoplay=False, volume=0.78)
            for _ in self.monsters
        ]
        for i, sound in enumerate(self.warn_sounds):
            self.set_audio_pitch(sound, 1.0 + WARN_PITCH_STEP * i)
        self.warn_sound = self.warn_sounds[0] if self.warn_sounds else None

        self.root = Entity(
            parent=camera.ui,
            position=(*MINIMAP_POSITION, 0),
            enabled=enabled,
        )

        self.shadow = Entity(
            parent=self.root,
            model='circle',
            color=rgba(5, 4, 2, 60),
            position=(0, 0, 0.20),
            scale=MINIMAP_SIZE * 1.10,
        )

        self.rim = Entity(
            parent=self.root,
            model='circle',
            color=rgba(172, 148, 48, 65),
            position=(0, 0, 0.156),
            scale=MINIMAP_SIZE * 1.02,
        )

        self.bg = Entity(
            parent=self.root,
            model='circle',
            color=rgba(10, 9, 5, 145),
            position=(0, 0, 0.14),
            scale=MINIMAP_SIZE * 0.972,
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
        self.map_mesh = Mesh(vertices=[], triangles=[], colors=[], mode='triangle', static=False)
        self.map_layer = Entity(
            parent=self.root,
            model=self.map_mesh,
            color=rgba(255, 255, 255, 255),
            position=(0, 0, 0.05),
            shader=MINIMAP_MAP_SHADER,
        )
        self.map_layer.set_shader_input('clip_radius', self.ui_radius())
        self.map_layer.set_shader_input('map_offset', Vec2(0.0, 0.0))

        self.vignette = Entity(
            parent=self.root,
            model='circle',
            color=rgba(255, 255, 255, 255),
            position=(0, 0, 0.01),
            scale=MINIMAP_SIZE * 0.972,
            shader=MINIMAP_VIGNETTE_SHADER,
        )

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
            color=rgba(255, 245, 200, 255),
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

        self.glitch_overlay = Entity(
            parent=self.root,
            model='circle',
            color=rgba(255, 255, 245, 0),
            position=(0, 0, -0.12),
            scale=self.map_diameter(),
            enabled=False,
        )

        self.glitch_lines = []
        for _ in range(GLITCH_SCANLINES):
            self.glitch_lines.append(Entity(
                parent=self.root,
                model='quad',
                color=rgba(255, 255, 245, 0),
                position=(0, 0, -0.13),
                scale=(MINIMAP_SIZE * 0.7, MINIMAP_SIZE * 0.008),
                enabled=False,
            ))

        self.static_noise_textures = self.create_static_noise_textures()
        self.static_noise_frame = 0
        self.static_noise = Entity(
            parent=self.root,
            model='quad',
            texture=self.static_noise_textures[0] if self.static_noise_textures else None,
            color=rgba(255, 255, 255, 255),
            position=(0, 0, -0.22),
            scale=(self.map_diameter(), self.map_diameter()),
            enabled=False,
        )
        self.static_noise.always_on_top = True

    def ui_radius(self):
        return MINIMAP_SIZE * 0.5 * MINIMAP_INNER

    def map_diameter(self):
        return self.ui_radius() * 2.0

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

    def chase_monster_distance_cells(self):
        best = None

        for monster in self.monsters:
            if monster.state != 'chase':
                continue

            dx = monster.entity.x - self.player.x
            dz = monster.entity.z - self.player.z
            dist = sqrt(dx * dx + dz * dz) / self.cell
            best = dist if best is None else min(best, dist)

        return best

    def target_glitch_amount(self):
        dist = self.chase_monster_distance_cells()

        if dist is None:
            return 0.0

        t = 1.0 - ((dist - GLITCH_MAX_CELLS) / max(0.001, GLITCH_START_CELLS - GLITCH_MAX_CELLS))
        t = min(1.0, max(0.0, t))
        return t * t * (3.0 - 2.0 * t)

    def glitch_offset(self, seed, amount=None):
        if amount is None:
            amount = self.glitch_amount

        if amount <= 0.01:
            return 0.0, 0.0

        t = time.time() * (15.0 + amount * 34.0)
        x = sin(t + seed * 12.989) * MINIMAP_SIZE * 0.014 * amount
        y = sin(t * 1.37 + seed * 78.233) * MINIMAP_SIZE * 0.009 * amount
        return x, y

    def tile_color(self):
        return rgba(148, 138, 88, FLOOR_ALPHA)

    def shaded_tile_color(self, edge_amount):
        shade = 0.32 + 0.68 * edge_amount
        alpha = int(FLOOR_ALPHA * edge_amount)
        return rgba(int(148 * shade), int(138 * shade), int(88 * shade), alpha)

    def shaded_room_color(self, edge_amount):
        shade = 0.32 + 0.68 * edge_amount
        alpha = int(ROOM_ALPHA * edge_amount)
        return rgba(int(90 * shade), int(80 * shade), int(50 * shade), alpha)

    def shaded_highlighted_room_color(self, edge_amount):
        shade = 0.36 + 0.64 * edge_amount
        alpha = int(180 * edge_amount)
        return rgba(int(58 * shade), int(135 * shade), int(190 * shade), alpha)

    def door_indicator_color(self, highlighted):
        if highlighted:
            return rgba(82, 165, 225, 170)

        return rgba(210, 188, 62, 145)

    def create_tiles(self):
        r = self.ui_radius()
        base = r * 2.0 * (self.cell / MINIMAP_WORLD_RANGE)
        s = base * FLOOR_SCALE

        for y, row in enumerate(self.layout):
            for x, v in enumerate(row):
                if v == 0:
                    self.floor_cells.append((y, x))
                elif (y, x) in self._door_room_set:
                    self.room_cells.append((y, x))

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
                highlighted = (rr, rc) in self.highlighted_room_cells
                self.door_indicator_specs.append((fr, fc, ind_wx, ind_wz, ind_scale, highlighted))

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.root.enabled = enabled

    def player_cell(self):
        return (
            int((self.player.z + self.cell / 2) // self.cell),
            int((self.player.x + self.cell / 2) // self.cell),
        )

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

    def play_warn_sound(self, index):
        if index is None or index < 0 or index >= len(self.warn_sounds):
            return

        sound = self.warn_sounds[index]
        sound.stop()
        sound.play()

    def scan(self):
        pr, pc = self.player_cell()

        self.scan_origin = (pr, pc)
        self.scan_wave = 0.0
        self.scan_max = SCAN_RADIUS_CELLS
        self.scanning = True
        self.pending_monster_pulse_dists = [None for _ in self.monsters]
        self.pending_monster_warn_indices = [None for _ in self.monsters]

        self.scan_pulse.enabled = True
        self.scan_pulse.scale = 0.001
        self.scan_pulse.color = rgba(178, 175, 118, 95)

        scan_x = pc * self.cell
        scan_z = pr * self.cell
        observed_monster_count = 0
        for i, monster in enumerate(self.monsters):
            monster_dx = monster.entity.x - scan_x
            monster_dz = monster.entity.z - scan_z
            monster_dist_cells = sqrt(monster_dx * monster_dx + monster_dz * monster_dz) / self.cell

            if monster_dist_cells <= SCAN_RADIUS_CELLS:
                warn_index = observed_monster_count
                observed_monster_count += 1
                self.has_monster_fixes[i] = True
                self.monster_fix_positions[i] = (monster.entity.x, monster.entity.z)
                self.pending_monster_pulse_dists[i] = monster_dist_cells
                self.pending_monster_warn_indices[i] = warn_index
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
                    before = len(self.revealed_cells)
                    self.revealed_cells.add((r, c))
                    for door_room in self.cell_door_rooms.get((r, c), ()):
                        self.revealed_cells.add(door_room)
                    if len(self.revealed_cells) != before:
                        self.map_dirty = True

        for i, pulse_dist in enumerate(self.pending_monster_pulse_dists):
            if pulse_dist is not None and pulse_dist <= self.scan_wave:
                self.monster_pulse_ts[i] = 0.0
                self.monster_pulses[i].enabled = True
                self.play_warn_sound(self.pending_monster_warn_indices[i])
                self.pending_monster_pulse_dists[i] = None
                self.pending_monster_warn_indices[i] = None

        k = min(1.0, self.scan_wave / max(0.001, self.scan_max))
        self.scan_pulse.scale = self.map_diameter() * k
        self.scan_pulse.color = rgba(178, 175, 118, int(95 * (1.0 - k)))

        if self.scan_wave >= self.scan_max:
            self.scanning = False
            self.scan_pulse.enabled = False

    def update_tiles(self):
        player_cell = self.player_cell()

        if self.map_dirty or player_cell != self.last_map_player_cell:
            self.rebuild_map_mesh()
            self.map_dirty = False
            self.last_map_player_cell = player_cell

        anchor_x, anchor_z = self.map_anchor
        x, y = self.world_to_local(anchor_x - self.player.x, anchor_z - self.player.z)
        self.map_layer.position = (x, y, 0.05)
        self.map_layer.set_shader_input('map_offset', Vec2(x, y))

    def rebuild_map_mesh(self):
        rr = self.ui_radius()
        base = rr * 2.0 * (self.cell / MINIMAP_WORLD_RANGE)
        tile_size = base * FLOOR_SCALE
        self.map_anchor = (self.player.x, self.player.z)
        anchor_x, anchor_z = self.map_anchor
        vertices = []
        triangles = []
        colors = []

        def add_rect(local_x, local_y, width, height, tile_color):
            i = len(vertices)
            hw = width * 0.5
            hh = height * 0.5
            vertices.extend((
                (local_x - hw, local_y - hh, 0.0),
                (local_x + hw, local_y - hh, 0.0),
                (local_x + hw, local_y + hh, 0.0),
                (local_x - hw, local_y + hh, 0.0),
            ))
            triangles.extend(((i, i + 1, i + 2), (i, i + 2, i + 3)))
            colors.extend((tile_color, tile_color, tile_color, tile_color))

        def world_to_anchor(wx, wz):
            return self.world_to_local(wx - anchor_x, wz - anchor_z)

        for r, c in self.floor_cells:
            if (r, c) not in self.revealed_cells:
                continue

            wx = c * self.cell
            wz = r * self.cell
            x, y = world_to_anchor(wx, wz)
            d = sqrt(x * x + y * y)

            if d > rr + tile_size:
                continue

            edge_amount = min(1.0, max(0.0, (rr - d) / max(0.001, rr * EDGE_FADE)))
            if edge_amount <= 0:
                continue
            add_rect(x, y, tile_size, tile_size, self.shaded_tile_color(edge_amount))

        for r, c in self.room_cells:
            if (r, c) not in self.revealed_cells:
                continue

            wx = c * self.cell
            wz = r * self.cell
            x, y = world_to_anchor(wx, wz)
            d = sqrt(x * x + y * y)

            if d > rr + tile_size:
                continue

            edge_amount = min(1.0, max(0.0, (rr - d) / max(0.001, rr * EDGE_FADE)))
            if edge_amount <= 0:
                continue
            room_color = (
                self.shaded_highlighted_room_color(edge_amount)
                if (r, c) in self.highlighted_room_cells
                else self.shaded_room_color(edge_amount)
            )
            add_rect(x, y, tile_size * 0.72, tile_size * 0.72, room_color)

        for floor_r, floor_c, ind_wx, ind_wz, ind_scale, highlighted in self.door_indicator_specs:
            if (floor_r, floor_c) not in self.revealed_cells:
                continue

            x, y = world_to_anchor(ind_wx, ind_wz)
            d = sqrt(x * x + y * y)

            if d > rr + max(ind_scale):
                continue

            add_rect(x, y, ind_scale[0], ind_scale[1], self.door_indicator_color(highlighted))

        self.map_layer.model = Mesh(
            vertices=vertices,
            triangles=triangles,
            colors=colors,
            mode='triangle',
            static=False,
        )

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

        if self.glitch_amount > 0.02:
            gx, gy = self.glitch_offset(i * 43 + 5, self.glitch_amount)
            x += gx
            y += gy
            flicker = 0.35 + 0.65 * abs(sin(time.time() * (18.0 + self.glitch_amount * 28.0) + i))
            dot.color = rgba(255, 35, 35, int(255 * (1.0 - self.glitch_amount * 0.45) * flicker))

        dot.position = (x, y, -0.06)
        pulse.position = (x, y, -0.07)

    def reset_monster_fixes(self):
        self.has_monster_fixes = [False for _ in self.monsters]
        self.monster_fix_positions = [(0.0, 0.0) for _ in self.monsters]
        self.pending_monster_pulse_dists = [None for _ in self.monsters]
        self.pending_monster_warn_indices = [None for _ in self.monsters]
        self.monster_pulse_ts = [MONSTER_PULSE_TIME for _ in self.monsters]

        for dot in self.monster_dots:
            dot.enabled = False

        for pulse in self.monster_pulses:
            pulse.enabled = False

    def update_player_marker(self):
        forward = self.player.forward
        fx = forward.x
        fz = forward.z
        length = max((fx * fx + fz * fz) ** 0.5, 0.001)
        fx /= length
        fz /= length

        gx, gy = self.glitch_offset(101, self.glitch_amount * 0.7)
        self.player_marker.position = (gx, gy, -0.08)
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

    def create_static_noise_textures(self):
        textures = []
        size = STATIC_NOISE_SIZE
        center = (size - 1) * 0.5
        radius = center
        radius2 = radius * radius

        for frame in range(STATIC_NOISE_FRAMES):
            image = PNMImage(size, size, 4)
            texture = PandaTexture(f'minimap_static_noise_{frame}')

            for y in range(size):
                dy = y - center
                for x in range(size):
                    dx = x - center

                    if dx * dx + dy * dy > radius2:
                        image.setXel(x, y, 0, 0, 0)
                        image.setAlpha(x, y, 0)
                        continue

                    shade = random.random()
                    alpha = random.uniform(0.25, 1.0)
                    image.setXel(x, y, shade, shade, shade)
                    image.setAlpha(x, y, alpha)

            texture.load(image)
            textures.append(Texture(texture))

        return textures

    def update_static_noise_texture(self, amount):
        if not self.static_noise_textures:
            return

        frame = int(time.time() * STATIC_NOISE_FPS * (1.0 + amount * 1.4)) % len(self.static_noise_textures)
        if frame != self.static_noise_frame:
            self.static_noise.texture = self.static_noise_textures[frame]
            self.static_noise_frame = frame

        self.static_noise.color = rgba(255, 255, 255, int(28 + amount * 82))

    def update_glitch(self):
        target = self.target_glitch_amount()
        self.glitch_amount += (target - self.glitch_amount) * min(1.0, time.dt * GLITCH_SMOOTHING)
        amount = self.glitch_amount

        if amount <= 0.015 or not self.enabled:
            self.root.position = (*MINIMAP_POSITION, 0)
            self.glitch_overlay.enabled = False
            for line in self.glitch_lines:
                line.enabled = False
            self.static_noise.enabled = False
            return

        rx, ry = self.glitch_offset(211, min(1.0, amount * 0.25))
        self.root.position = (MINIMAP_POSITION[0] + rx, MINIMAP_POSITION[1] + ry, 0)

        self.glitch_overlay.enabled = False
        for line in self.glitch_lines:
            line.enabled = False

        self.static_noise.enabled = True
        self.update_static_noise_texture(amount)

    def update(self):
        self.update_scan_wave()
        self.update_glitch()

        if not self.enabled:
            for i in range(len(self.monsters)):
                self.update_monster_pulse(i)
            return

        self.update_tiles()
        for i in range(len(self.monsters)):
            self.update_monster_dot(i)
            self.update_monster_pulse(i)
        self.update_player_marker()
