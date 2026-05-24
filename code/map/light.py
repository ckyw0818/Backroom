from ursina import Entity, color


LIGHT_COLOR = color.Color(1.0, 0.96, 0.55, 1)
LIGHT_RADIUS = 6.8
LIGHT_POWER = 2.0
LIGHT_PANEL_SAMPLES = (
    (0.0, 0.0),
    (-0.62, 0.0),
    (0.62, 0.0),
    (0.0, -0.22),
    (0.0, 0.22),
)


def rgba(r, g, b, a):
    return color.Color(r / 255, g / 255, b / 255, a / 255)


class LightSystem:
    def __init__(self, layout, cell_size, wall_height):
        self.layout = layout
        self.rows = len(layout)
        self.cols = len(layout[0])
        self.cell = cell_size
        self.wall_height = wall_height
        self.radius = LIGHT_RADIUS
        self.radius2 = self.radius * self.radius
        self.power = LIGHT_POWER

        self.cells = [
            (r, c)
            for r in range(self.rows)
            for c in range(self.cols)
            if layout[r][c] == 0 and (r + c) % 1 == 0
        ]

        self.cell_set = set(self.cells)

        self.pos_map = {
            (r, c): (
                c * self.cell,
                self.wall_height - 0.16,
                r * self.cell,
            )
            for r, c in self.cells
        }

        self.positions = list(self.pos_map.values())
        self.cell_cache = self._build_cell_light_cache()

        self._block_cache = {}
        self._light_cache = {}
        self._shade_cache = {}

    def _build_cell_light_cache(self):
        cache = {}
        radius_cells = int(self.radius / self.cell) + 1

        for r in range(self.rows):
            for c in range(self.cols):
                if self.layout[r][c] != 0:
                    continue

                near = []

                for lr, lc in self.cells:
                    if abs(r - lr) > radius_cells:
                        continue
                    if abs(c - lc) > radius_cells:
                        continue

                    near.append(self.pos_map[(lr, lc)])

                cache[(r, c)] = near

        return cache

    def layout_at_world(self, x, z):
        c = int((x + self.cell / 2) // self.cell)
        r = int((z + self.cell / 2) // self.cell)

        if r < 0 or r >= self.rows or c < 0 or c >= self.cols:
            return 1

        return self.layout[r][c]

    def cell_at_world(self, x, z):
        return (
            int((z + self.cell / 2) // self.cell),
            int((x + self.cell / 2) // self.cell),
        )

    def blocked_by_wall(self, light_x, light_z, x, z):
        k = (
            int(light_x * 1024),
            int(light_z * 1024),
            int(x * 1024),
            int(z * 1024),
        )

        v = self._block_cache.get(k)
        if v is not None:
            return v

        dx = x - light_x
        dz = z - light_z
        dist2 = dx * dx + dz * dz

        if dist2 < 0.01:
            self._block_cache[k] = False
            return False

        if self.cell_at_world(light_x, light_z) == self.cell_at_world(x, z):
            self._block_cache[k] = False
            return False

        dist = dist2 ** 0.5
        steps = max(2, int(dist / 0.32))
        inv = 1.0 / steps
        layout_at_world = self.layout_at_world

        for i in range(1, steps):
            t = i * inv

            if t > 0.97:
                break

            px = light_x + dx * t
            pz = light_z + dz * t

            if layout_at_world(px, pz) == 1:
                self._block_cache[k] = True
                return True

        self._block_cache[k] = False
        return False

    def light_at(self, x, y, z, near_lights, surface='wall'):
        k = (
            int(x * 1024),
            int(y * 1024),
            int(z * 1024),
            id(near_lights),
            surface,
        )

        v = self._light_cache.get(k)
        if v is not None:
            return v

        total = 0.0
        radius = self.radius
        radius2 = self.radius2
        power = self.power
        wall_height = self.wall_height
        blocked_by_wall = self.blocked_by_wall
        samples = LIGHT_PANEL_SAMPLES if surface in ('floor', 'ceil') else ((0.0, 0.0),)

        if surface == 'floor':
            falloff_exp = 1.75
            surface_boost = 1.45
            vertical_bias = 0.55
        elif surface == 'ceil':
            falloff_exp = 1.55
            surface_boost = 0.72
            vertical_bias = 0.10
        elif surface == 'baseboard':
            falloff_exp = 2.15
            surface_boost = 1.12
            vertical_bias = 0.25
        else:
            falloff_exp = 2.35
            surface_boost = 1.0
            vertical_bias = 0.25

        for lx, ly, lz in near_lights:
            sample_power = power / len(samples)

            for off_x, off_z in samples:
                sx = lx + off_x
                sz = lz + off_z
                dx = x - sx
                dy = (y - ly) * vertical_bias
                dz = z - sz
                dist2 = dx * dx + dy * dy + dz * dz

                if dist2 >= radius2:
                    continue

                if blocked_by_wall(sx, sz, x, z):
                    continue

                dist = dist2 ** 0.5
                falloff = 1.0 - dist / radius

                ceiling_edge_soften = 0.88 if y > wall_height * 0.90 else 1.0
                total += (falloff ** falloff_exp) * sample_power * surface_boost * ceiling_edge_soften

        self._light_cache[k] = total
        return total

    def shaded_color(self, base, amount, minimum=0.055):
        k = (base, round(amount, 6), minimum)

        v = self._shade_cache.get(k)
        if v is not None:
            return v

        amount = max(minimum, amount)

        br = base[0] / 255
        bg = base[1] / 255
        bb = base[2] / 255

        exposure = amount

        r = br * exposure * 1.00
        g = bg * exposure * 0.91
        b = bb * exposure * 0.42

        r = r / (1.0 + r)
        g = g / (1.0 + g)
        b = b / (1.0 + b)

        gamma = 1 / 1.28

        r = r ** gamma
        g = g ** gamma
        b = b ** gamma

        r = min(1.0, r)
        g = min(0.97, g)
        b = min(0.58, b)

        col = color.Color(r, g, b, 1)
        self._shade_cache[k] = col
        return col

    def add_fixture(self, r, c):
        x = c * self.cell
        z = r * self.cell

        tube = Entity(
            model='cube',
            color=rgba(255, 255, 245, 255),
            unlit=True,
            position=(x, self.wall_height - 0.035, z),
            scale=(0.78, 0.025, 0.78),
        )

        return [tube]
