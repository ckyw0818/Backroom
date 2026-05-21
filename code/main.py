from ursina import *
try:
    from ursina.shaders import lit_with_shadows_shader
except ImportError:
    lit_with_shadows_shader = None

from panda3d.core import AmbientLight as Panda3dAmbientLight

from game_map import CELL, LAYOUT, WALL_H, MapRenderer
from light import LightSystem
from player_controller import CAMERA_FOV, HeadBob, create_player
from post_effects import PostEffects
from textures import DARK_COLOR, load_environment_textures


def rgba(r, g, b, a):
    return color.Color(r/255, g/255, b/255, a/255)


app = Ursina(title='The Backrooms', size=(1280, 720))

render_root = app.render
render_root.setShaderAuto()
render_root.clearLight()

window.exit_button.visible = False
window.fps_counter.enabled = False
window.fullscreen = True

WORLD_SHADER = lit_with_shadows_shader

camera.background_color = DARK_COLOR
camera.fov = CAMERA_FOV
scene.fog_color = DARK_COLOR
scene.fog_density = 0

textures = load_environment_textures()
light_system = LightSystem(LAYOUT, CELL, WALL_H)
player = create_player(CELL)
head_bob = HeadBob(player)
map_renderer = MapRenderer(player, light_system, textures)

_amb = Panda3dAmbientLight('ambient')
_amb.setColor((0.0, 0.0, 0.0, 1.0))
render_root.setLight(render_root.attachNewNode(_amb))

Text(
    text='THE BACKROOMS  |  WASD: Move   Mouse: Look   ESC: Quit',
    origin=(0, 0),
    position=(0, -0.46),
    scale=0.65,
    color=rgba(210, 195, 95, 110),
)

post_effects = PostEffects()


map_renderer.initial_render()


def update():
    map_renderer.update_rendered_scene()
    map_renderer.process_queues()
    post_effects.update()

    if post_effects:
        post_effects.update()
    head_bob.update()
    camera.fov = CAMERA_FOV

    if held_keys['escape']:
        application.quit()


app.run()
