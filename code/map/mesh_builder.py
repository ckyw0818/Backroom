from ursina import Entity, Mesh

from map.map_data import (
    BASEBOARD_H,
    BASEBOARD_OUT,
    BASEBOARD_TEX_SCALE,
    CELL,
    CEIL_TEX_SCALE,
    FLOOR_TEX_SCALE,
    MESH_STEPS,
    WALL_H,
    WALL_TEX_SCALE,
)
from utill.textures import BASEBOARD_RGB, CEIL_RGB, FLOOR_RGB, WALL_RGB


class MeshBuilderMixin:
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
