import json
import struct
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = PROJECT_DIR / 'asset' / 'model' / 'door.glb'


def read_glb_json(path):
    with open(path, 'rb') as f:
        magic, version, total_length = struct.unpack('<4sII', f.read(12))

        if magic != b'glTF':
            raise ValueError(f'Not a GLB file: {path}')

        chunks = []
        read = 12

        while read < total_length:
            chunk_length, chunk_type = struct.unpack('<II', f.read(8))
            chunk_data = f.read(chunk_length)
            read += 8 + chunk_length
            chunks.append((chunk_type, chunk_data))

    for chunk_type, chunk_data in chunks:
        if chunk_type == 0x4E4F534A:
            return json.loads(chunk_data.rstrip(b'\x00 ').decode('utf-8'))

    raise ValueError('GLB JSON chunk not found')


def name_of(items, index, fallback):
    if index is None:
        return None
    if not items or index >= len(items):
        return f'{fallback}[{index}]'
    return items[index].get('name') or f'{fallback}[{index}]'


def print_glb_summary(path):
    data = read_glb_json(path)
    nodes = data.get('nodes', [])
    meshes = data.get('meshes', [])
    materials = data.get('materials', [])
    scenes = data.get('scenes', [])
    default_scene = data.get('scene', 0)

    print('=' * 72)
    print(f'GLB: {path}')
    print(f'asset generator: {data.get("asset", {}).get("generator", "unknown")}')
    print(f'scenes={len(scenes)} nodes={len(nodes)} meshes={len(meshes)} materials={len(materials)}')
    print(f'animations={len(data.get("animations", []))} skins={len(data.get("skins", []))}')
    print('=' * 72)

    for scene_index, gltf_scene in enumerate(scenes):
        marker = 'default' if scene_index == default_scene else ''
        roots = gltf_scene.get('nodes', [])
        root_names = [name_of(nodes, i, 'node') for i in roots]
        print(f'Scene {scene_index} {marker}: roots={root_names}')

    print('\nNodes:')
    for i, node in enumerate(nodes):
        mesh_name = name_of(meshes, node.get('mesh'), 'mesh')
        children = [name_of(nodes, child, 'node') for child in node.get('children', [])]
        trs = []

        if 'translation' in node:
            trs.append(f'translation={node["translation"]}')
        if 'rotation' in node:
            trs.append(f'rotation={node["rotation"]}')
        if 'scale' in node:
            trs.append(f'scale={node["scale"]}')

        print(
            f'  [{i}] {node.get("name", "(unnamed)")}'
            f' mesh={mesh_name}'
            f' children={children}'
            f' {" ".join(trs)}'
        )

    print('\nMeshes:')
    for i, mesh in enumerate(meshes):
        print(f'  [{i}] {mesh.get("name", "(unnamed)")} primitives={len(mesh.get("primitives", []))}')
        for j, primitive in enumerate(mesh.get('primitives', [])):
            material = name_of(materials, primitive.get('material'), 'material')
            attrs = ', '.join(sorted(primitive.get('attributes', {}).keys()))
            print(f'       primitive[{j}] material={material} attrs={attrs}')

    print('\nMaterials:')
    for i, material in enumerate(materials):
        pbr = material.get('pbrMetallicRoughness', {})
        print(
            f'  [{i}] {material.get("name", "(unnamed)")}'
            f' baseColorFactor={pbr.get("baseColorFactor")}'
            f' baseColorTexture={pbr.get("baseColorTexture")}'
        )

    likely_door_nodes = [
        node.get('name', '')
        for node in nodes
        if any(word in node.get('name', '').lower() for word in ('door', 'frame', 'hinge', 'leaf', 'panel'))
    ]
    print('\nLikely separable door/frame nodes:')
    if likely_door_nodes:
        for node_name in likely_door_nodes:
            print(f'  - {node_name}')
    else:
        print('  No obvious node names. Check mesh/node list above.')

    print('=' * 72)


def print_panda_tree(node_path, indent=0):
    print('  ' * indent + node_path.getName())
    for child in node_path.getChildren():
        print_panda_tree(child, indent + 1)


def main():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(MODEL_PATH)

    print_glb_summary(MODEL_PATH)

    if '--inspect' in sys.argv:
        return

    from ursina import (
        AmbientLight,
        DirectionalLight,
        EditorCamera,
        Entity,
        Text,
        Ursina,
        application,
        camera,
        color,
        held_keys,
        time,
        window,
    )
    from panda3d.core import AmbientLight as Panda3dAmbientLight, Filename, TextureStage

    game_render = '--game-render' in sys.argv
    apply_fix   = '--fix' in sys.argv

    app = Ursina(title='door.glb test viewer', size=(1280, 720))
    application.asset_folder = PROJECT_DIR
    window.color = color.rgb(18, 18, 18)
    camera.position = (0, 1.1, -4.0)
    camera.rotation = (12, 0, 0)

    if game_render:
        render_root = app.render
        render_root.setShaderAuto()
        render_root.clearLight()
        _amb = Panda3dAmbientLight('ambient')
        _amb.setColor((0.0, 0.0, 0.0, 1.0))
        render_root.setLight(render_root.attachNewNode(_amb))

    panda_model = loader.loadModel(Filename.fromOsSpecific(str(MODEL_PATH)))

    if panda_model.isEmpty():
        raise RuntimeError(f'Panda3D failed to load model: {MODEL_PATH}')

    model = Entity(
        model=panda_model,
        position=(0, 0, 0),
        scale=1,
        rotation=(0, 180, 0),
    )

    if game_render and apply_fix:
        _aux_keywords = ('normal', 'roughness', 'metallic', 'occlusion', 'emissive', 'height', 'gloss', 'specular')
        _aux_modes = [
            getattr(TextureStage, attr)
            for attr in ('MNormal', 'MNormalHeight', 'MHeight', 'MGloss', 'MGlow', 'MModulateGloss', 'MModulateGlow')
            if hasattr(TextureStage, attr)
        ]

        def _is_aux(stage):
            name = stage.getName().lower()
            return any(w in name for w in _aux_keywords) or stage.getMode() in _aux_modes

        for np in [model] + list(model.findAllMatches('**')):
            if np.isEmpty():
                continue
            np.setTwoSided(True)
            np.setShaderOff(1)
            np.setMaterialOff(1)
            for stage in list(np.findAllTextureStages()):
                if _is_aux(stage):
                    np.clearTexture(stage)

        _door_amb = Panda3dAmbientLight('door_amb')
        _door_amb.setColor((0.7, 0.64, 0.29, 1.0))
        model.setLight(model.attachNewNode(_door_amb))

    Entity(model='plane', scale=4, color=color.rgba(70, 70, 70, 120), y=-0.01)

    if not game_render:
        DirectionalLight(rotation=(45, -35, 35), color=color.rgb(255, 244, 210))
        AmbientLight(color=color.rgba(90, 90, 90, 255))

    EditorCamera(rotation_smoothing=2, panning_speed=0.08)

    mode_label = 'game-render+fix' if (game_render and apply_fix) else ('game-render' if game_render else 'default')
    Text(
        text=f'[{mode_label}]  drag: orbit  wheel: zoom  A/D: rotate  W/S: scale  ESC: quit',
        origin=(0, 0),
        position=(0, -0.46),
        scale=0.7,
        color=color.rgba(230, 230, 210, 180),
    )

    print('\nPanda3D loaded scene tree:')
    print_panda_tree(model)
    print('=' * 72)

    def update():
        if held_keys['a']:
            model.rotation_y -= 75 * time.dt
        if held_keys['d']:
            model.rotation_y += 75 * time.dt
        if held_keys['w']:
            model.scale *= 1 + time.dt
        if held_keys['s']:
            model.scale *= max(0.1, 1 - time.dt)
        if held_keys['escape']:
            application.quit()

    app.run()


if __name__ == '__main__':
    main()
