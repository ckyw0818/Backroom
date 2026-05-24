import sys
from pathlib import Path

from panda3d.core import (
    AmbientLight,
    DirectionalLight,
    Filename,
    NodePath,
    OrthographicLens,
    Point3,
    TextureStage,
    Vec3,
    Vec4,
    loadPrcFileData,
)


PROJECT_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = PROJECT_DIR / 'asset' / 'model' / 'key.glb'
DEFAULT_OUTPUT_PATH = PROJECT_DIR / 'asset' / 'model' / 'key_preview.png'
IMAGE_SIZE = 768
MODEL_FILL = 1.72
CAMERA_DISTANCE = 5.0
AUX_TEXTURE_WORDS = (
    'normal',
    'roughness',
    'metallic',
    'occlusion',
    'emissive',
    'height',
    'gloss',
    'specular',
)
AUX_TEXTURE_MODES = tuple(
    getattr(TextureStage, attr)
    for attr in ('MNormal', 'MNormalHeight', 'MHeight', 'MGloss', 'MGlow', 'MModulateGloss', 'MModulateGlow')
    if hasattr(TextureStage, attr)
)


loadPrcFileData('', 'window-type offscreen')
loadPrcFileData('', f'win-size {IMAGE_SIZE} {IMAGE_SIZE}')
loadPrcFileData('', 'framebuffer-alpha true')
loadPrcFileData('', 'textures-power-2 none')
loadPrcFileData('', 'audio-library-name null')


def is_aux_texture_stage(stage):
    name = stage.getName().lower()
    return any(word in name for word in AUX_TEXTURE_WORDS) or stage.getMode() in AUX_TEXTURE_MODES


def model_bounds_info(model):
    bounds = model.getTightBounds()

    if not bounds:
        return None

    mn, mx = bounds
    center = (mn + mx) * 0.5
    size = mx - mn
    return center, size


def normalize_model(model):
    info = model_bounds_info(model)

    if not info:
        return Vec3(0, 0, 0)

    center, size = info
    longest = max(size.x, size.y, size.z, 0.001)
    model.setPos(-center)
    model.setScale(MODEL_FILL / longest)
    return size


def prepare_model(model):
    for np in (model, *model.findAllMatches('**')):
        if np.isEmpty():
            continue

        np.setTwoSided(True)
        np.setShaderOff(1)

        for stage in list(np.findAllTextureStages()):
            if is_aux_texture_stage(stage):
                np.clearTexture(stage)


def add_lights(render_root):
    ambient = AmbientLight('key_png_ambient')
    ambient.setColor(Vec4(0.52, 0.48, 0.36, 1.0))
    render_root.setLight(render_root.attachNewNode(ambient))

    key_light = DirectionalLight('key_png_directional')
    key_light.setColor(Vec4(1.0, 0.92, 0.65, 1.0))
    key_light_np = render_root.attachNewNode(key_light)
    key_light_np.setHpr(-35, -45, 0)
    render_root.setLight(key_light_np)


def frame_camera(base, original_size):
    axes = (
        ('x', original_size.x),
        ('y', original_size.y),
        ('z', original_size.z),
    )
    view_axis = min(axes, key=lambda item: item[1])[0]

    if view_axis == 'x':
        base.camera.setPos(CAMERA_DISTANCE, 0, 0)
        base.camera.lookAt(Point3(0, 0, 0), Vec3(0, 0, 1))
    elif view_axis == 'y':
        base.camera.setPos(0, -CAMERA_DISTANCE, 0)
        base.camera.lookAt(Point3(0, 0, 0), Vec3(0, 0, 1))
    else:
        base.camera.setPos(0, 0, CAMERA_DISTANCE)
        base.camera.lookAt(Point3(0, 0, 0), Vec3(0, 1, 0))

    return view_axis


def render_key_png(output_path):
    from direct.showbase.ShowBase import ShowBase

    base = ShowBase(windowType='offscreen')
    base.win.setClearColor(Vec4(0, 0, 0, 0))
    base.render.clearLight()

    scene = base.loader.loadModel(Filename.fromOsSpecific(str(MODEL_PATH)))

    if scene.isEmpty():
        raise RuntimeError(f'Failed to load key model: {MODEL_PATH}')

    model = NodePath('key_png_model')
    scene.copyTo(model)
    scene.removeNode()
    model.reparentTo(base.render)
    original_size = normalize_model(model)
    prepare_model(model)

    lens = OrthographicLens()
    lens.setFilmSize(2.1, 2.1)
    base.cam.node().setLens(lens)
    view_axis = frame_camera(base, original_size)

    add_lights(base.render)

    for _ in range(3):
        base.graphicsEngine.renderFrame()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ok = base.win.saveScreenshot(Filename.fromOsSpecific(str(output_path)))
    base.destroy()

    if not ok:
        raise RuntimeError(f'Failed to save PNG: {output_path}')

    print(f'Rendered key from thinnest axis: {view_axis}')


def main():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(MODEL_PATH)

    output_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_OUTPUT_PATH
    render_key_png(output_path)
    print(f'Saved transparent key PNG: {output_path}')


if __name__ == '__main__':
    main()
