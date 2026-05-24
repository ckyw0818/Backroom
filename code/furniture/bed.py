from direct.showbase import ShowBaseGlobal
from panda3d.core import Filename, NodePath, PNMImage, Texture as PandaTexture
from ursina import Entity, Texture as UrsinaTexture, color

from map.map_data import PROJECT_DIR
from utill.textures import WALL_RGB


BED_MODEL_PATH = PROJECT_DIR / 'asset' / 'model' / 'bed.glb'
BED_MODEL_TARGET_LONG = 1.95
BED_MODEL_TARGET_SHORT = 1.10
BED_COLLIDER_H = 0.65
BED_COLLIDER_SHRINK = 0.92
BED_WALL_CLEARANCE = 0.04
BED_SHADOW_ALPHA = 85
BED_SHADOW_TEXTURE_SIZE = 96
BED_SHADOW_Y = 0.012


class BedMixin:
    def init_bed_assets(self):
        self.bed_model = self.load_bed_model()
        self.bed_model_scale = self.fit_bed_model_scale(self.bed_model)
        self.bed_model_size = self.model_size(self.bed_model, self.bed_model_scale)
        self.furniture_shadow_texture = self.create_furniture_shadow_texture()

    def load_bed_model(self):
        scene = ShowBaseGlobal.base.loader.loadModel(Filename.fromOsSpecific(str(BED_MODEL_PATH)))

        if scene.isEmpty():
            raise RuntimeError(f'Failed to load bed model: {BED_MODEL_PATH}')

        model = NodePath('bed_template')
        scene.copyTo(model)
        scene.removeNode()

        self.prepare_bed_model(model, normalize=True)
        return model

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
