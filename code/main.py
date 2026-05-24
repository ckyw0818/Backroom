from ursina import *
try:
    from ursina.shaders import lit_with_shadows_shader
except ImportError:
    lit_with_shadows_shader = None

from pathlib import Path

from direct.showbase import ShowBaseGlobal
from panda3d.core import AmbientLight as Panda3dAmbientLight, Point2

from character.monster import MonsterAI
from character.player_controller import CAMERA_FOV, RUN_SPEED, HeadBob, create_player
from map.game_map import MapRenderer
from map.light import LightSystem
from map.map_data import CELL, LAYOUT, START_ROOM_CELL, WALL_H
from map.minimap import MINIMAP_ENABLED, Minimap
from utill.post_effects import PostEffects
from utill.textures import DARK_COLOR, load_environment_textures


HEARTBEAT_IDLE_VOLUME = 0.3
HEARTBEAT_IDLE_RATE = 0.72
HEARTBEAT_CHASE_MIN_VOLUME = 0.4
HEARTBEAT_CHASE_MAX_VOLUME = 2.4
HEARTBEAT_CHASE_MIN_RATE = 0.9
HEARTBEAT_CHASE_MAX_RATE = 2.3
HEARTBEAT_MIN_DISTANCE = 2.0
HEARTBEAT_MAX_DISTANCE = 16.0
HEARTBEAT_SMOOTHING = 4.5
CROSSHAIR_SIZE = 0.010
CROSSHAIR_DOOR_SIZE = 0.017
CROSSHAIR_SMOOTHING = 14.0
NOISE_SONAR_STRENGTH = 1.0
NOISE_DOOR_STRENGTH = 0.7
NOISE_FOOTSTEP_STRENGTH = 0.3
JUMPSCARE_SCREEN_PAD = 0.08
JUMPSCARE_PLAY_TIME = 3
JUMPSCARE_MIN_DISTANCE = 1.0
JUMPSCARE_MAX_DISTANCE = 14.0
JUMPSCARE_MIN_VOLUME = 0.65
JUMPSCARE_MAX_VOLUME = 3.0


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


def emit_noise(strength):
    cell = player_noise_cell()
    for monster in monsters:
        monster.investigate_noise(cell, strength)


def player_noise_cell():
    cell = (
        int((player.z + CELL / 2) // CELL),
        int((player.x + CELL / 2) // CELL),
    )
    r, c = cell

    if 0 <= r < len(LAYOUT) and 0 <= c < len(LAYOUT[0]) and LAYOUT[r][c] == 0:
        return cell

    for dr, dc in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        nr = r + dr
        nc = c + dc
        if 0 <= nr < len(LAYOUT) and 0 <= nc < len(LAYOUT[0]) and LAYOUT[nr][nc] == 0:
            return nr, nc

    return cell


def monster_on_screen(monster):
    if not getattr(monster.entity, 'enabled', True):
        return False

    point = Point2()
    base = ShowBaseGlobal.base
    monster_pos = monster.entity.getPos(render_root)
    camera_space_pos = base.cam.getRelativePoint(render_root, monster_pos)

    if camera_space_pos.y <= 0:
        return False

    if not base.camLens.project(camera_space_pos, point):
        return False

    return (
        -1.0 - JUMPSCARE_SCREEN_PAD <= point.x <= 1.0 + JUMPSCARE_SCREEN_PAD
        and -1.0 - JUMPSCARE_SCREEN_PAD <= point.y <= 1.0 + JUMPSCARE_SCREEN_PAD
    )


def update_jumpscares():
    global jumpscare_timer, jumpscare_monster

    if jumpscare_timer > 0.0 and jumpscare_monster:
        jumpscare_sound.volume = jumpscare_volume_for(jumpscare_monster)

    for monster in monsters:
        if monster.state != 'chase':
            continue
        if monster.jumpscare_seen_this_chase:
            continue
        if not monster_on_screen(monster):
            continue
        if not monster.has_line_of_sight_to_player():
            continue

        monster.jumpscare_seen_this_chase = True
        jumpscare_sound.stop()
        jumpscare_sound.volume = jumpscare_volume_for(monster)
        jumpscare_sound.play()
        jumpscare_timer = JUMPSCARE_PLAY_TIME
        jumpscare_monster = monster
        break

    if jumpscare_timer > 0.0:
        jumpscare_timer -= time.dt
        if jumpscare_timer <= 0.0:
            jumpscare_sound.stop()
            jumpscare_monster = None


def jumpscare_volume_for(monster):
    close = 1.0 - (
        (monster.distance_to_player() - JUMPSCARE_MIN_DISTANCE)
        / (JUMPSCARE_MAX_DISTANCE - JUMPSCARE_MIN_DISTANCE)
    )
    close = smoothstep01(close)
    return JUMPSCARE_MIN_VOLUME + (JUMPSCARE_MAX_VOLUME - JUMPSCARE_MIN_VOLUME) * close


class DoorCrosshair:
    def __init__(self):
        self.outer = Entity(
            parent=camera.ui,
            model='circle',
            color=rgba(245, 235, 190, 115),
            position=(0, 0, -0.70),
            scale=CROSSHAIR_SIZE,
        )
        self.inner = Entity(
            parent=camera.ui,
            model='circle',
            color=rgba(8, 8, 6, 82),
            position=(0, 0, -0.71),
            scale=CROSSHAIR_SIZE * 0.52,
        )

    def set_visible(self, visible):
        self.outer.enabled = visible
        self.inner.enabled = visible

    def update(self, door_ready, hidden):
        self.set_visible(not hidden)

        if hidden:
            return

        target = CROSSHAIR_DOOR_SIZE if door_ready else CROSSHAIR_SIZE
        k = min(1.0, time.dt * CROSSHAIR_SMOOTHING)
        scale = self.outer.scale_x + (target - self.outer.scale_x) * k
        self.outer.scale = scale
        self.inner.scale = scale * 0.52
        self.outer.color = rgba(255, 236, 165, 175 if door_ready else 115)


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
player = create_player(CELL, *START_ROOM_CELL)
footstep_sounds = [
    Audio(f'asset/sound/foot{i}.wav', autoplay=False, volume=0.60)
    for i in range(1, 4)
]
head_bob = HeadBob(player, footstep_sounds, lambda: emit_noise(NOISE_FOOTSTEP_STRENGTH))
map_renderer = MapRenderer(player, light_system, textures)
monster_specs = [
    ('asset/texture/obunga.png', (25, 25)),
    ('asset/texture/obunga2.png', (21, 25)),
    ('asset/texture/obunga3.png', (7, 23)),
    ('asset/texture/obunga4.png', (27, 23)),
]
monsters = [
    MonsterAI(
        player,
        LAYOUT,
        CELL,
        PROJECT_DIR,
        spawn_cell=spawn_cell,
        texture=texture,
        chase_speed=RUN_SPEED * 3.5,
    )
    for texture, spawn_cell in monster_specs
]
post_effects = PostEffects()

minimap = Minimap(
    LAYOUT,
    CELL,
    player,
    monsters,
    map_renderer._cell_door_rooms,
    highlighted_room_cells=map_renderer.exit_room_cells,
    enabled=MINIMAP_ENABLED,
)
crosshair = DoorCrosshair()

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
vent_ambience = Audio('asset/sound/vent.wav', loop=True, autoplay=True, volume=0.60)
sonar_sound = Audio('asset/sound/sonar.wav', autoplay=False, volume=0.78)
heartbeat_sound = Audio('asset/sound/heartbeat.wav', loop=True, autoplay=True, volume=HEARTBEAT_IDLE_VOLUME)
jumpscare_sound = Audio('asset/sound/jumpscare.wav', autoplay=False, volume=2.5)
jumpscare_timer = 0.0
jumpscare_monster = None
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
    map_renderer.update_drawers()

    for monster in monsters:
        monster.update()

    update_jumpscares()

    minimap_scan_down = held_keys['r']
    if minimap_scan_down and not minimap_scan_was_down:
        sonar_sound.play()
        minimap.scan()
        emit_noise(NOISE_SONAR_STRENGTH)
    minimap_scan_was_down = minimap_scan_down

    minimap_tab_down = held_keys['tab']
    if minimap_tab_down and not minimap_tab_was_down:
        minimap_visible = not minimap_visible
        minimap.set_enabled(minimap_visible)
    minimap_tab_was_down = minimap_tab_down

    minimap.update()
    crosshair.update(map_renderer.can_interact(), minimap_visible)
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
        else:
            post_effects.set_threat(0.0)
        post_effects.update()
    head_bob.update()
    camera.fov = CAMERA_FOV

    if held_keys['escape']:
        application.quit()


def input(key):
    if key == 'e':
        interaction = map_renderer.nearest_interaction()
        if map_renderer.interact_nearest() and interaction and interaction[0] == 'door':
            emit_noise(NOISE_DOOR_STRENGTH)


app.run()
