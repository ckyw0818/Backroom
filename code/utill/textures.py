import random
from pathlib import Path

from PIL import Image
from direct.showbase import ShowBaseGlobal
from panda3d.core import Filename, SamplerState, Texture
from ursina import color


WALL_RGB = (151, 145, 36)
BASEBOARD_RGB = (177, 171, 55)
FLOOR_RGB = (116, 105, 35)
CEIL_RGB = (104, 99, 27)
DARK_COLOR = color.Color(0, 0, 0, 1)
PROJECT_DIR = Path(__file__).resolve().parents[2]
TEXTURE_DIR = PROJECT_DIR / 'asset' / 'texture'


def make_noise(path, base, amp=18, force=False):
    path = Path(path)
    if path.exists() and not force:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new('RGB', (256, 256), base)
    px = img.load()

    for y in range(256):
        for x in range(256):
            n = random.randint(-amp, amp)
            px[x, y] = (
                max(0, min(255, base[0] + n)),
                max(0, min(255, base[1] + n)),
                max(0, min(255, base[2] + n)),
            )

    img.save(path)


def load_image_texture(path):
    path = Path(path)
    panda_path = Filename.fromOsSpecific(str(path))
    tex = ShowBaseGlobal.base.loader.loadTexture(panda_path)
    if tex is None:
        normalized_path = path.with_name(f'{path.stem}_runtime.png')
        Image.open(path).convert('RGB').save(normalized_path)
        panda_path = Filename.fromOsSpecific(str(normalized_path))
        tex = ShowBaseGlobal.base.loader.loadTexture(panda_path)

    if tex is None:
        raise RuntimeError(f'Failed to load texture: {path}')

    tex.setWrapU(Texture.WM_repeat)
    tex.setWrapV(Texture.WM_repeat)
    tex.setMinfilter(SamplerState.FT_linear_mipmap_linear)
    tex.setMagfilter(SamplerState.FT_linear)
    tex.setAnisotropicDegree(4)
    return tex


def load_environment_textures():
    wall_path = TEXTURE_DIR / 'wall.png'
    floor_path = TEXTURE_DIR / 'floor.png'
    ceil_path = TEXTURE_DIR / 'ceil.png'
    baseboard_path = TEXTURE_DIR / 'baseboard.png'
    noise_path = TEXTURE_DIR / 'noise.png'
    outdoor_path = TEXTURE_DIR / 'outdoor.png'
    indoor_path = TEXTURE_DIR / 'indoor.png'

    make_noise(wall_path, WALL_RGB, 22)
    make_noise(floor_path, FLOOR_RGB, 18)
    make_noise(ceil_path, CEIL_RGB, 16)
    make_noise(baseboard_path, BASEBOARD_RGB, 12)
    make_noise(noise_path, (128, 128, 128), 80)

    return {
        'wall': load_image_texture(wall_path),
        'floor': load_image_texture(floor_path),
        'ceil': load_image_texture(ceil_path),
        'baseboard': load_image_texture(baseboard_path),
        'noise': load_image_texture(noise_path),
        'outdoor': load_image_texture(outdoor_path),
        'indoor': load_image_texture(indoor_path),
    }
