import math
import random

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
from furniture.door import DOOR_DENSITY, DOOR_FACE_SALTS
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
NOISE_DRAWER_STRENGTH = 0.45
NOISE_FOOTSTEP_STRENGTH = 0.3
JUMPSCARE_SCREEN_PAD = 0.08
JUMPSCARE_PLAY_TIME = 3
JUMPSCARE_MIN_DISTANCE = 1.0
JUMPSCARE_MAX_DISTANCE = 14.0
JUMPSCARE_MIN_VOLUME = 0.65
JUMPSCARE_MAX_VOLUME = 3.0
DEATH_DISTANCE = CELL * 0.2
DEATH_BLACK_TIME = 3.5
RESPAWN_FADE_TIME = 1.0
RESPAWN_YAW = -90
MAX_PLAYER_HEARTS = 3
DEATH_HEART_ANIM_TIME = 1.0
DEATH_GAME_OVER_DELAY = 0.45
VENT_VOLUME = 0.60
MONSTER_SPAWN_COUNT = 4
MONSTER_SPAWN_MIN_DISTANCE = 12
MONSTER_SPAWN_MIN_SEPARATION = 8


def rgba(r, g, b, a):
    return color.Color(r/255, g/255, b/255, a/255)


def smoothstep01(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def lerp_color(start, end, amount):
    amount = smoothstep01(amount)
    return rgba(
        int(start[0] + (end[0] - start[0]) * amount),
        int(start[1] + (end[1] - start[1]) * amount),
        int(start[2] + (end[2] - start[2]) * amount),
        int(start[3] + (end[3] - start[3]) * amount),
    )


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


def set_death_overlay_alpha(alpha):
    alpha = max(0.0, min(1.0, alpha))
    death_overlay.enabled = alpha > 0.0
    death_overlay.color = rgba(0, 0, 0, int(255 * alpha))


def set_death_screen_visible(visible):
    if death_screen:
        death_screen.set_visible(visible)


def reset_player_to_start():
    player.position = (START_ROOM_CELL_RUNTIME[1] * CELL, 0, START_ROOM_CELL_RUNTIME[0] * CELL)
    player.rotation_y = RESPAWN_YAW
    player.speed = 0
    player.camera_pivot.x = 0
    player.camera_pivot.y = head_bob.base_pivot_y
    camera.rotation = (0, 0, 0)
    head_bob.current_speed = 0.0
    head_bob.run_blend = 0.0
    head_bob.jitter_x = 0.0
    head_bob.jitter_y = 0.0


def reset_run_after_death():
    global jumpscare_timer, jumpscare_monster, heartbeat_rate, minimap_visible

    jumpscare_timer = 0.0
    jumpscare_monster = None
    jumpscare_sound.stop()
    vent_ambience.volume = 0.0
    vent_ambience.stop()
    vent_ambience.play()
    heartbeat_rate = HEARTBEAT_IDLE_RATE
    heartbeat_sound.volume = HEARTBEAT_IDLE_VOLUME
    set_audio_rate(heartbeat_sound, heartbeat_rate)

    reset_player_to_start()
    map_renderer.reset_start_room_lock_and_key()

    for monster, spawn_cell in zip(monsters, pick_monster_spawn_cells(len(monsters))):
        monster.reset_to_cell(spawn_cell)
        monster.silence_all_sounds()

    minimap.reset_monster_fixes()
    minimap_visible = False
    minimap.set_enabled(False)
    map_renderer.update_rendered_scene(force=True)


def start_death_sequence():
    global death_state, death_timer, death_lost_heart_index, player_hearts

    if death_state != 'alive':
        return

    player_hearts = max(0, player_hearts - 1)
    death_lost_heart_index = MAX_PLAYER_HEARTS - player_hearts - 1
    death_state = 'black'
    death_timer = DEATH_BLACK_TIME
    player.speed = 0
    vent_ambience.stop()
    fade_monster_sounds(1.0)
    set_death_overlay_alpha(1.0)


def fade_monster_sounds(amount):
    volume = max(0.0, min(1.0, amount))

    jumpscare_sound.volume = JUMPSCARE_MAX_VOLUME * volume

    for monster in monsters:
        monster.set_sound_volume_scale(volume)
        if volume <= 0.0:
            monster.silence_all_sounds()


def update_death_sequence():
    global death_state, death_timer

    if death_state == 'alive':
        return False

    player.speed = 0

    if death_state == 'game_over':
        death_timer += time.dt
        set_death_overlay_alpha(1.0)
        fade_monster_sounds(0.0)
        death_screen.update(
            player_hearts,
            death_lost_heart_index,
            1.0,
            show_game_over=True,
            game_over_progress=min(1.0, death_timer / 0.65),
        )
        return True

    death_timer -= time.dt

    if death_state == 'black':
        set_death_overlay_alpha(1.0)
        fade_monster_sounds(death_timer / DEATH_BLACK_TIME)
        black_elapsed = DEATH_BLACK_TIME - death_timer
        heart_progress = min(1.0, black_elapsed / DEATH_HEART_ANIM_TIME)
        death_screen.update(player_hearts, death_lost_heart_index, heart_progress)

        if player_hearts <= 0 and black_elapsed >= DEATH_HEART_ANIM_TIME + DEATH_GAME_OVER_DELAY:
            death_state = 'game_over'
            death_timer = 0.0
            return True

        if death_timer <= 0.0:
            set_death_screen_visible(False)
            reset_run_after_death()
            death_state = 'fade_in'
            death_timer = RESPAWN_FADE_TIME
        return True

    if death_state == 'fade_in':
        set_death_screen_visible(False)
        alpha = max(0.0, death_timer / RESPAWN_FADE_TIME)
        set_death_overlay_alpha(alpha)
        vent_ambience.volume = VENT_VOLUME * (1.0 - alpha)

        if death_timer <= 0.0:
            death_state = 'alive'
            death_timer = 0.0
            vent_ambience.volume = VENT_VOLUME
            fade_monster_sounds(1.0)
            set_death_overlay_alpha(0.0)
        return True

    return False


def update_player_caught():
    if map_renderer.closed_door_for_room_cell(map_renderer.player_cell())[0] is not None:
        return

    for monster in monsters:
        if monster.distance_to_player() <= DEATH_DISTANCE:
            start_death_sequence()
            return


def cell_open_neighbor_count(cell):
    r, c = cell
    return sum(
        1
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
        if 0 <= r + dr < len(LAYOUT)
        and 0 <= c + dc < len(LAYOUT[0])
        and LAYOUT[r + dr][c + dc] == 0
    )


def cell_grid_distance(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def door_room_for_face(r, c, face):
    if face == 'north':
        return r - 1, c
    if face == 'south':
        return r + 1, c
    if face == 'west':
        return r, c - 1
    return r, c + 1


def random_start_room_cell():
    candidates = []

    for r, row in enumerate(LAYOUT):
        for c, value in enumerate(row):
            if value != 0:
                continue

            for face in ('north', 'south', 'west', 'east'):
                if (r * 17 + c * 31 + DOOR_FACE_SALTS[face]) % DOOR_DENSITY != 0:
                    continue

                room_cell = door_room_for_face(r, c, face)
                rr, rc = room_cell

                if (
                    0 <= rr < len(LAYOUT)
                    and 0 <= rc < len(LAYOUT[0])
                    and LAYOUT[rr][rc] == 1
                ):
                    candidates.append(room_cell)

    return random.choice(candidates) if candidates else START_ROOM_CELL


def pick_monster_spawn_cells(count):
    base_candidates = [
        (r, c)
        for r, row in enumerate(LAYOUT)
        for c, value in enumerate(row)
        if value == 0
        and cell_open_neighbor_count((r, c)) >= 3
    ]
    candidates = [
        cell
        for cell in base_candidates
        if cell_grid_distance(cell, START_ROOM_CELL_RUNTIME) >= MONSTER_SPAWN_MIN_DISTANCE
    ]
    if not candidates:
        candidates = base_candidates[:]
    random.shuffle(candidates)

    picked = []
    for cell in candidates:
        if all(cell_grid_distance(cell, other) >= MONSTER_SPAWN_MIN_SEPARATION for other in picked):
            picked.append(cell)

            if len(picked) >= count:
                return picked

    remaining = [cell for cell in candidates if cell not in picked]
    return picked + remaining[:max(0, count - len(picked))]


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


class DeathScreen:
    HEART_TEXT = '♥'
    HEART_FULL = (215, 24, 48, 255)
    HEART_LOST = (38, 38, 38, 255)

    def __init__(self):
        self.root = Entity(parent=camera.ui, enabled=False)
        self.hearts = []

        for index, x in enumerate((-0.18, 0.0, 0.18)):
            heart = Text(
                parent=self.root,
                text=self.HEART_TEXT,
                origin=(0, 0),
                position=(x, 0.03, -1.2),
                scale=4.2,
                color=rgba(*self.HEART_FULL),
            )
            heart.always_on_top = True
            self.hearts.append(heart)

        self.game_over = Text(
            parent=self.root,
            text='GAME OVER',
            origin=(0, 0),
            position=(0, -0.16, -1.2),
            scale=2.1,
            color=rgba(230, 230, 230, 0),
            enabled=False,
        )
        self.game_over.always_on_top = True

    def set_visible(self, visible):
        self.root.enabled = visible

    def update(
        self,
        lives,
        lost_index=None,
        anim_progress=1.0,
        show_game_over=False,
        game_over_progress=1.0,
    ):
        self.set_visible(True)

        for index, heart in enumerate(self.hearts):
            lost = index < MAX_PLAYER_HEARTS - lives
            heart.scale = 4.2

            if lost_index == index:
                heart.color = lerp_color(self.HEART_FULL, self.HEART_LOST, anim_progress)
                pulse = 1.0 + 0.18 * math.sin(min(1.0, anim_progress) * math.pi)
                heart.scale = 4.2 * pulse
            elif lost:
                heart.color = rgba(*self.HEART_LOST)
            else:
                heart.color = rgba(*self.HEART_FULL)

        self.game_over.enabled = show_game_over
        if show_game_over:
            fade = min(1.0, max(0.0, game_over_progress))
            self.game_over.color = rgba(230, 230, 230, int(255 * fade))


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
START_ROOM_CELL_RUNTIME = random_start_room_cell()
player = create_player(CELL, *START_ROOM_CELL_RUNTIME, spawn_yaw=-90)
footstep_sounds = [
    Audio(f'asset/sound/foot{i}.wav', autoplay=False, volume=0.60)
    for i in range(1, 4)
]
head_bob = HeadBob(player, footstep_sounds, lambda: emit_noise(NOISE_FOOTSTEP_STRENGTH))
map_renderer = MapRenderer(player, light_system, textures, START_ROOM_CELL_RUNTIME)
monster_textures = [
    'asset/texture/obunga.png',
    'asset/texture/obunga2.png',
    'asset/texture/obunga3.png',
    'asset/texture/obunga4.png',
]
monster_specs = list(zip(monster_textures, pick_monster_spawn_cells(MONSTER_SPAWN_COUNT)))
monsters = [
    MonsterAI(
        player,
        LAYOUT,
        CELL,
        PROJECT_DIR,
        spawn_cell=spawn_cell,
        texture=texture,
        chase_speed=RUN_SPEED * 8,
    )
    for texture, spawn_cell in monster_specs
]
for monster in monsters:
    monster.set_door_system(map_renderer, MONSTER_SPAWN_MIN_DISTANCE)
post_effects = PostEffects()

minimap = Minimap(
    LAYOUT,
    CELL,
    player,
    monsters,
    map_renderer._cell_door_rooms,
    enabled=MINIMAP_ENABLED,
)
crosshair = DoorCrosshair()
death_overlay = Entity(
    parent=camera.ui,
    model='quad',
    color=rgba(0, 0, 0, 0),
    position=(0, 0, -0.95),
    scale=(2.2, 2.2),
    enabled=False,
)
death_overlay.always_on_top = True
death_screen = DeathScreen()
death_state = 'alive'
death_timer = 0.0
player_hearts = MAX_PLAYER_HEARTS
death_lost_heart_index = None

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
vent_ambience = Audio('asset/sound/vent.wav', loop=True, autoplay=True, volume=VENT_VOLUME)
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

    if update_death_sequence():
        if held_keys['escape']:
            application.quit()
        return

    map_renderer.update_rendered_scene()
    map_renderer.process_queues()
    map_renderer.update_doors()
    map_renderer.update_drawers()

    for monster in monsters:
        monster.update()

    update_player_caught()
    if death_state != 'alive':
        return

    update_jumpscares()

    minimap_scan_down = held_keys['r']
    if minimap_scan_down and not minimap_scan_was_down:
        emit_noise(NOISE_SONAR_STRENGTH)
        if minimap.scan():
            sonar_sound.play()
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
        if map_renderer.interact_nearest() and interaction:
            if interaction[0] == 'door':
                emit_noise(NOISE_DOOR_STRENGTH)
            elif interaction[0] == 'drawer':
                emit_noise(NOISE_DRAWER_STRENGTH)


app.run()
