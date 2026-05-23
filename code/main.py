from ursina import *
try:
    from ursina.shaders import lit_with_shadows_shader
except ImportError:
    lit_with_shadows_shader = None

from pathlib import Path

from panda3d.core import AmbientLight as Panda3dAmbientLight

from game_map import CELL, LAYOUT, WALL_H, MapRenderer
from light import LightSystem
from minimap import MINIMAP_ENABLED, Minimap
from monster import MonsterAI
from player_controller import CAMERA_FOV, RUN_SPEED, HeadBob, create_player
from post_effects import PostEffects
from textures import DARK_COLOR, load_environment_textures


HEARTBEAT_IDLE_VOLUME = 0.3
HEARTBEAT_IDLE_RATE = 0.72
HEARTBEAT_CHASE_MIN_VOLUME = 0.4
HEARTBEAT_CHASE_MAX_VOLUME = 2.4
HEARTBEAT_CHASE_MIN_RATE = 0.9
HEARTBEAT_CHASE_MAX_RATE = 2.3
HEARTBEAT_MIN_DISTANCE = 2.0
HEARTBEAT_MAX_DISTANCE = 16.0
HEARTBEAT_SMOOTHING = 4.5


def rgba(r, g, b, a):
    return color.Color(r/255, g/255, b/255, a/255)


def smoothstep01(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def set_audio_rate(sound, rate):
    for attr in ('pitch', 'play_rate', 'rate'):
        if hasattr(sound, attr):
            try:
                setattr(sound, attr, rate)
                return
            except Exception:
                pass

    for attr in ('sound', '_sound', 'audio', '_audio'):
        inner = getattr(sound, attr, None)

        if inner and hasattr(inner, 'setPlayRate'):
            try:
                inner.setPlayRate(rate)
                return
            except Exception:
                pass


def heartbeat_targets(monster):
    if monster.state != 'chase':
        return HEARTBEAT_IDLE_VOLUME, HEARTBEAT_IDLE_RATE

    dist = monster.distance_to_player()
    close = 1.0 - (
        (dist - HEARTBEAT_MIN_DISTANCE)
        / (HEARTBEAT_MAX_DISTANCE - HEARTBEAT_MIN_DISTANCE)
    )
    close = smoothstep01(close)

    volume = HEARTBEAT_CHASE_MIN_VOLUME + (HEARTBEAT_CHASE_MAX_VOLUME - HEARTBEAT_CHASE_MIN_VOLUME) * close
    rate = HEARTBEAT_CHASE_MIN_RATE + (HEARTBEAT_CHASE_MAX_RATE - HEARTBEAT_CHASE_MIN_RATE) * close
    return volume, rate


app = Ursina(title='The Backrooms', size=(1280, 720))
PROJECT_DIR = Path(__file__).resolve().parent.parent
application.asset_folder = PROJECT_DIR

render_root = app.render
render_root.setShaderAuto()
render_root.clearLight()

window.exit_button.visible = False
window.fps_counter.enabled = False
window.entity_counter.enabled = False
window.collider_counter.enabled = False
window.fullscreen = True

WORLD_SHADER = lit_with_shadows_shader

camera.background_color = DARK_COLOR
camera.fov = CAMERA_FOV
scene.fog_color = DARK_COLOR
scene.fog_density = 0

textures = load_environment_textures()
light_system = LightSystem(LAYOUT, CELL, WALL_H)
player = create_player(CELL)
footstep_sounds = [
    Audio(f'asset/sound/foot{i}.wav', autoplay=False, volume=0.60)
    for i in range(1, 4)
]
head_bob = HeadBob(player, footstep_sounds)
map_renderer = MapRenderer(player, light_system, textures)
monster_specs = [
    ('asset/texture/obunga.png', (13, 18)),
    ('asset/texture/obunga2.png', (11, 14)),
    ('asset/texture/obunga3.png', (9, 17)),
]
monsters = [
    MonsterAI(
        player,
        LAYOUT,
        CELL,
        PROJECT_DIR,
        spawn_cell=spawn_cell,
        texture=texture,
        chase_speed=RUN_SPEED * 0.95,
    )
    for texture, spawn_cell in monster_specs
]
minimap = Minimap(LAYOUT, CELL, player, monsters, map_renderer._cell_door_rooms, enabled=MINIMAP_ENABLED)

_amb = Panda3dAmbientLight('ambient')
_amb.setColor((0.0, 0.0, 0.0, 1.0))
render_root.setLight(render_root.attachNewNode(_amb))

Text(
    text='THE BACKROOMS  |  WASD: Move   Mouse: Look   E: Door   ESC: Quit',
    origin=(0, 0),
    position=(0, -0.46),
    scale=0.65,
    color=rgba(210, 195, 95, 110),
)

post_effects = PostEffects()
vent_ambience = Audio('asset/sound/vent.wav', loop=True, autoplay=True, volume=0.80)
sonar_sound = Audio('asset/sound/sonar.wav', autoplay=False, volume=0.78)
heartbeat_sound = Audio('asset/sound/heartbeat.wav', loop=True, autoplay=True, volume=HEARTBEAT_IDLE_VOLUME)
heartbeat_rate = HEARTBEAT_IDLE_RATE
set_audio_rate(heartbeat_sound, heartbeat_rate)
minimap_scan_was_down = False
minimap_tab_was_down = False
minimap_visible = False


map_renderer.initial_render()


def update():
    global heartbeat_rate, minimap_scan_was_down, minimap_tab_was_down, minimap_visible

    map_renderer.update_rendered_scene()
    map_renderer.process_queues()
    map_renderer.update_doors()

    for monster in monsters:
        monster.update()

    minimap_scan_down = held_keys['r']
    if minimap_scan_down and not minimap_scan_was_down:
        sonar_sound.play()
        minimap.scan()
        for monster in monsters:
            monster.investigate_noise(monster.player_cell())
    minimap_scan_was_down = minimap_scan_down

    minimap_tab_down = held_keys['tab']
    if minimap_tab_down and not minimap_tab_was_down:
        minimap_visible = not minimap_visible
        minimap.set_enabled(minimap_visible)
    minimap_tab_was_down = minimap_tab_down

    minimap.update()
    active_monster = min(monsters, key=lambda monster: monster.distance_to_player())
    target_heartbeat_volume, target_heartbeat_rate = heartbeat_targets(active_monster)
    heartbeat_lerp = min(1.0, time.dt * HEARTBEAT_SMOOTHING)
    heartbeat_sound.volume += (target_heartbeat_volume - heartbeat_sound.volume) * heartbeat_lerp
    heartbeat_rate += (target_heartbeat_rate - heartbeat_rate) * heartbeat_lerp
    set_audio_rate(heartbeat_sound, heartbeat_rate)

    if post_effects:
        if active_monster.state == 'chase':
            dist = active_monster.distance_to_player()
            close = 1.0 - min(1.0, max(0.0, (dist - 2.0) / 14.0))
            post_effects.set_threat(0.45 + close * 0.55)
        elif active_monster.state == 'alert':
            post_effects.set_threat(0.65)
        elif active_monster.state == 'investigate':
            dist = active_monster.distance_to_player()
            close = 1.0 - min(1.0, max(0.0, (dist - 3.0) / 9.0))
            post_effects.set_threat(close * 0.25)
        elif active_monster.state == 'lost':
            post_effects.set_threat(0.35)
        else:
            post_effects.set_threat(0.0)
        post_effects.update()
    head_bob.update()
    camera.fov = CAMERA_FOV

    if held_keys['escape']:
        application.quit()


def input(key):
    if key == 'e':
        map_renderer.toggle_nearest_door()


app.run()
