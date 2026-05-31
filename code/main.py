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
from game_clear import GameClearSequence
from main_menu import MainMenu, PauseMenu
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
EXIT_BACKGROUND = color.Color(1.0, 1.0, 1.0, 1.0)
NOISE_FOOTSTEP_STRENGTH = 0.3
JUMPSCARE_SCREEN_PAD = 0.08
JUMPSCARE_PLAY_TIME = 3
JUMPSCARE_LOOK_TIME = 0.10
JUMPSCARE_MIN_DISTANCE = 1.0
JUMPSCARE_MAX_DISTANCE = 14.0
JUMPSCARE_MIN_VOLUME = 0.65
JUMPSCARE_MAX_VOLUME = 3.0
DEATH_DISTANCE = CELL * 0.2
JUMPSCARE_PROXIMITY_DISTANCE = DEATH_DISTANCE * 1.5
DEATH_BLACK_TIME = 3.5
RESPAWN_FADE_TIME = 1.0
RESPAWN_YAW = -90
MAX_PLAYER_HEARTS = 3
DEATH_HEART_ANIM_TIME = 1.0
DEATH_GAME_OVER_DELAY = 0.45
VENT_VOLUME = 0.60
MENU_MUSIC_VOLUME = 0.72
MENU_MUSIC_FADE_TIME = 2.0
GAME_START_FADE_TIME = 1.6
MONSTER_SPAWN_COUNT = 4
MONSTER_SPAWN_MIN_DISTANCE = 20
MONSTER_SPAWN_MIN_SEPARATION = 8
MONSTER_FINAL_NOTE_SPEED_MULTIPLIER = 1.25
ZOOM_KEY = 'z'
ZOOM_TIME = 0.5
ZOOM_FOV = CAMERA_FOV * 0.5


def rgba(r, g, b, a):
    return color.Color(r/255, g/255, b/255, a/255)


def smoothstep01(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def move_towards(current, target, step):
    if current < target:
        return min(target, current + step)
    return max(target, current - step)


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


def update_camera_zoom(active=True):
    global zoom_amount

    target = 1.0 if active and held_keys[ZOOM_KEY] else 0.0
    zoom_amount = move_towards(zoom_amount, target, time.dt / ZOOM_TIME)
    amount = smoothstep01(zoom_amount)
    camera.fov = CAMERA_FOV + (ZOOM_FOV - CAMERA_FOV) * amount


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


def monster_active(monster):
    return getattr(monster.entity, 'enabled', True)


def active_monsters():
    return [monster for monster in monsters if monster_active(monster)]


def collected_note_count():
    return len(getattr(map_renderer, 'collected_notes', ()))


def target_active_monster_count(note_count):
    return min(MONSTER_SPAWN_COUNT, max(1, note_count))


def set_monster_active(monster, active):
    if monster_active(monster) == active:
        return

    monster.entity.enabled = active

    if active:
        monster.reset_to_spawn()
    else:
        monster.silence_all_sounds()


def start_door_opened():
    if map_renderer is None:
        return False
    key = getattr(map_renderer, '_first_lockable_door_key', None)
    if key is None:
        return True
    return map_renderer.door_states.get(key, False)


def update_monster_pressure():
    if not start_door_opened():
        for monster in monsters:
            set_monster_active(monster, False)
        return

    note_count = collected_note_count()
    active_count = target_active_monster_count(note_count)
    speed_multiplier = MONSTER_FINAL_NOTE_SPEED_MULTIPLIER if note_count >= 5 else 1.0

    for index, monster in enumerate(monsters):
        set_monster_active(monster, index < active_count)
        monster.set_speed_multiplier(speed_multiplier)


def emit_noise(strength):
    cell = player_noise_cell()
    for monster in active_monsters():
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

    for monster in active_monsters():
        if monster.state != 'chase':
            continue
        if monster.jumpscare_seen_this_chase:
            continue
        seen_trigger = monster_on_screen(monster) and monster.has_line_of_sight_to_player()
        close_trigger = (
            monster.distance_to_player() <= JUMPSCARE_PROXIMITY_DISTANCE
            and not monster.player_hidden_behind_closed_door()
        )

        if not (seen_trigger or close_trigger):
            continue

        monster.jumpscare_seen_this_chase = True
        jumpscare_sound.stop()
        jumpscare_sound.volume = jumpscare_volume_for(monster)
        jumpscare_sound.play()
        jumpscare_timer = JUMPSCARE_PLAY_TIME
        jumpscare_monster = monster
        if close_trigger and not seen_trigger:
            start_jumpscare_look(monster)
        break

    if jumpscare_timer > 0.0:
        jumpscare_timer -= time.dt
        if jumpscare_timer <= 0.0:
            jumpscare_sound.stop()
            jumpscare_monster = None


def shortest_angle_delta(target, current):
    return (target - current + 180.0) % 360.0 - 180.0


def camera_pivot_pitch():
    return float(getattr(player.camera_pivot, 'rotation_x', 0.0))


def monster_look_angles(monster):
    dx = monster.entity.x - player.x
    dz = monster.entity.z - player.z
    horizontal = max((dx * dx + dz * dz) ** 0.5, 0.001)
    camera_y = player.y + getattr(player.camera_pivot, 'y', 1.15)
    dy = monster.entity.y - camera_y
    yaw = math.degrees(math.atan2(dx, dz))
    pitch = -math.degrees(math.atan2(dy, horizontal))
    return yaw, max(-88.0, min(88.0, pitch))


def start_jumpscare_look(monster):
    global jumpscare_look_timer, jumpscare_look_start_yaw, jumpscare_look_target_yaw
    global jumpscare_look_start_pitch, jumpscare_look_target_pitch

    target_yaw, target_pitch = monster_look_angles(monster)
    jumpscare_look_timer = JUMPSCARE_LOOK_TIME
    jumpscare_look_start_yaw = float(player.rotation_y)
    jumpscare_look_target_yaw = jumpscare_look_start_yaw + shortest_angle_delta(target_yaw, jumpscare_look_start_yaw)
    jumpscare_look_start_pitch = camera_pivot_pitch()
    jumpscare_look_target_pitch = target_pitch


def update_jumpscare_look():
    global jumpscare_look_timer

    if jumpscare_look_timer <= 0.0:
        return

    elapsed = JUMPSCARE_LOOK_TIME - jumpscare_look_timer
    amount = smoothstep01(elapsed / JUMPSCARE_LOOK_TIME)
    player.rotation_y = jumpscare_look_start_yaw + (jumpscare_look_target_yaw - jumpscare_look_start_yaw) * amount
    player.camera_pivot.rotation_x = jumpscare_look_start_pitch + (
        jumpscare_look_target_pitch - jumpscare_look_start_pitch
    ) * amount

    jumpscare_look_timer = max(0.0, jumpscare_look_timer - time.dt)
    if jumpscare_look_timer <= 0.0:
        player.rotation_y = jumpscare_look_target_yaw
        player.camera_pivot.rotation_x = jumpscare_look_target_pitch


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
    x, z, yaw = player_start_pose()
    player.position = (x, 0, z)
    player.rotation_y = yaw
    player.speed = 0
    player.camera_pivot.x = 0
    player.camera_pivot.y = head_bob.base_pivot_y
    player.camera_pivot.rotation_x = 0
    camera.rotation = (0, 0, 0)
    head_bob.current_speed = 0.0
    head_bob.run_blend = 0.0
    head_bob.jitter_x = 0.0
    head_bob.jitter_y = 0.0


def player_start_pose():
    room_r, room_c = START_ROOM_CELL_RUNTIME
    room_x = room_c * CELL
    room_z = room_r * CELL
    door_key = getattr(map_renderer, '_first_lockable_door_key', None)

    if door_key is None:
        return room_x, room_z, RESPAWN_YAW

    door_r, door_c, door_face = door_key
    door_room_cell = map_renderer.door_room_for_face(door_r, door_c, door_face)[0]

    if door_room_cell != START_ROOM_CELL_RUNTIME:
        return room_x, room_z, RESPAWN_YAW

    door_x, _, door_z = map_renderer.door_world_position(door_c * CELL, door_r * CELL, door_face)
    dx = door_x - room_x
    dz = door_z - room_z
    dist = max((dx * dx + dz * dz) ** 0.5, 0.001)
    dir_x = dx / dist
    dir_z = dz / dist
    away_from_door = CELL * 0.24
    spawn_x = room_x - dir_x * away_from_door
    spawn_z = room_z - dir_z * away_from_door
    yaw = math.degrees(math.atan2(door_x - spawn_x, door_z - spawn_z))
    return spawn_x, spawn_z, yaw


def reset_run_after_death():
    global jumpscare_timer, jumpscare_monster, heartbeat_rate, minimap_visible, jumpscare_look_timer

    jumpscare_timer = 0.0
    jumpscare_monster = None
    jumpscare_look_timer = 0.0
    jumpscare_sound.stop()
    vent_ambience.volume = 0.0
    vent_ambience.stop()
    vent_ambience.play()
    heartbeat_rate = HEARTBEAT_IDLE_RATE
    heartbeat_sound.volume = HEARTBEAT_IDLE_VOLUME
    set_audio_rate(heartbeat_sound, heartbeat_rate)

    reset_player_to_start()
    map_renderer.reset_start_room_lock_and_key()
    map_renderer._raycast_cache_key = None
    map_renderer.update_rendered_scene(force=True)
    map_renderer.process_queues()

    for monster, spawn_cell in zip(monsters, pick_monster_spawn_cells(len(monsters))):
        monster.reset_to_cell(spawn_cell)
        monster.silence_all_sounds()

    update_monster_pressure()
    minimap.reset_monster_fixes()
    minimap_visible = False
    minimap.set_enabled(False)


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

    for monster in active_monsters():
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

    for monster in active_monsters():
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
                if r <= 1 and c <= 2:
                    continue
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


def pick_monster_spawn_cells(count, start_cell=None):
    start_cell = start_cell or START_ROOM_CELL_RUNTIME
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
        if cell_grid_distance(cell, start_cell) >= MONSTER_SPAWN_MIN_DISTANCE
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

textures = None
light_system = None
START_ROOM_CELL_RUNTIME = START_ROOM_CELL
player = None
footstep_sounds = []
head_bob = None
map_renderer = None
monsters = []
post_effects = None
minimap = None
crosshair = None
death_overlay = None
death_screen = None
death_state = 'alive'
death_timer = 0.0
player_hearts = MAX_PLAYER_HEARTS
death_lost_heart_index = None
game_clear_sequence = None
game_state = 'menu'
menu_music = None
menu_music_fade_timer = 0.0
game_start_fade_timer = 0.0
game_start_fade_active = False
zoom_amount = 0.0

_amb = Panda3dAmbientLight('ambient')
_amb.setColor((0.0, 0.0, 0.0, 1.0))
render_root.setLight(render_root.attachNewNode(_amb))

guide_text = None
vent_ambience = None
sonar_sound = None
heartbeat_sound = None
jumpscare_sound = None
jumpscare_timer = 0.0
jumpscare_monster = None
jumpscare_look_timer = 0.0
jumpscare_look_start_yaw = 0.0
jumpscare_look_target_yaw = 0.0
jumpscare_look_start_pitch = 0.0
jumpscare_look_target_pitch = 0.0
heartbeat_rate = HEARTBEAT_IDLE_RATE
minimap_scan_was_down = False
minimap_tab_was_down = False
minimap_visible = False


def set_system_cursor_visible(visible):
    mouse.locked = not visible
    mouse.visible = visible

    window_cursor = getattr(window, 'cursor', None)
    if window_cursor is not None and hasattr(window_cursor, 'visible'):
        window_cursor.visible = visible


def start_menu_music():
    global menu_music

    if menu_music is None:
        menu_music = Audio('asset/sound/mainmenu.wav', loop=True, autoplay=False, volume=MENU_MUSIC_VOLUME)

    menu_music.volume = MENU_MUSIC_VOLUME
    menu_music.play()


def start_menu_music_fadeout():
    global menu_music_fade_timer

    menu_music_fade_timer = MENU_MUSIC_FADE_TIME


def update_menu_music_fade():
    global menu_music_fade_timer

    if menu_music_fade_timer <= 0.0 or menu_music is None:
        return

    menu_music_fade_timer = max(0.0, menu_music_fade_timer - time.dt)
    amount = menu_music_fade_timer / MENU_MUSIC_FADE_TIME
    menu_music.volume = MENU_MUSIC_VOLUME * smoothstep01(amount)

    if menu_music_fade_timer <= 0.0:
        menu_music.stop()


def start_game_fadein():
    global game_start_fade_timer, game_start_fade_active

    game_start_fade_timer = GAME_START_FADE_TIME
    game_start_fade_active = True
    set_death_overlay_alpha(1.0)


def update_game_start_fadein():
    global game_start_fade_timer, game_start_fade_active

    if not game_start_fade_active:
        return

    game_start_fade_timer = max(0.0, game_start_fade_timer - min(time.dt, 1 / 20))
    alpha = game_start_fade_timer / GAME_START_FADE_TIME
    set_death_overlay_alpha(alpha)

    fade_in = 1.0 - alpha
    if vent_ambience:
        vent_ambience.volume = VENT_VOLUME * fade_in
    if heartbeat_sound:
        heartbeat_sound.volume = HEARTBEAT_IDLE_VOLUME * fade_in

    if game_start_fade_timer <= 0.0:
        game_start_fade_active = False
        set_death_overlay_alpha(0.0)
        if vent_ambience:
            vent_ambience.volume = VENT_VOLUME
        if heartbeat_sound:
            heartbeat_sound.volume = HEARTBEAT_IDLE_VOLUME


def initialize_game():
    global textures, light_system, START_ROOM_CELL_RUNTIME, player, footstep_sounds
    global head_bob, map_renderer, monsters, post_effects, minimap, crosshair
    global death_overlay, death_screen, game_clear_sequence, guide_text
    global vent_ambience, sonar_sound, heartbeat_sound, jumpscare_sound
    global death_state, death_timer, player_hearts, death_lost_heart_index
    global jumpscare_timer, jumpscare_monster, jumpscare_look_timer, heartbeat_rate

    if game_clear_sequence is not None:
        return

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
    reset_player_to_start()

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
            chase_speed=RUN_SPEED * 5,
        )
        for texture, spawn_cell in monster_specs
    ]
    for monster in monsters:
        monster.set_door_system(map_renderer, MONSTER_SPAWN_MIN_DISTANCE)
    update_monster_pressure()
    post_effects = PostEffects()

    minimap = Minimap(
        LAYOUT,
        CELL,
        player,
        monsters,
        map_renderer._cell_door_rooms,
        enabled=False,
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
    jumpscare_timer = 0.0
    jumpscare_monster = None
    jumpscare_look_timer = 0.0
    heartbeat_rate = HEARTBEAT_IDLE_RATE

    guide_text = Text(
        text='THE BACKROOMS  |  WASD: Move   Mouse: Look   E: Door   ESC: Pause',
        origin=(0, 0),
        position=(0, -0.46),
        scale=0.975,
        color=rgba(210, 195, 95, 110),
        enabled=False,
    )
    vent_ambience = Audio('asset/sound/vent.wav', loop=True, autoplay=False, volume=0.0)
    sonar_sound = Audio('asset/sound/sonar.wav', autoplay=False, volume=0.78)
    heartbeat_sound = Audio('asset/sound/heartbeat.wav', loop=True, autoplay=False, volume=0.0)
    jumpscare_sound = Audio('asset/sound/jumpscare.wav', autoplay=False, volume=2.5)
    set_audio_rate(heartbeat_sound, heartbeat_rate)

    map_renderer.initial_render()

    game_clear_sequence = GameClearSequence(
        player,
        map_renderer,
        CELL,
        vent_ambience,
        heartbeat_sound,
        crosshair,
        minimap,
        fade_monster_sounds,
        update_exit_background,
        post_effects,
        guide_text,
    )

    vent_ambience.play()
    heartbeat_sound.play()


def suspend_gameplay_for_menu():
    if player is None:
        set_system_cursor_visible(True)
        return

    player.enabled = False
    player.speed = 0
    head_bob.current_speed = 0.0
    player.mouse_sensitivity = Vec2(0, 0)
    set_system_cursor_visible(True)
    player.cursor.visible = False
    crosshair.set_visible(False)
    minimap.set_enabled(False)


def start_game():
    global game_state

    if game_state == 'loading':
        return

    game_state = 'loading'
    main_menu.set_mode('loading')
    set_system_cursor_visible(True)
    start_menu_music_fadeout()
    invoke(finish_start_game, delay=0.35)


def finish_start_game():
    global game_state

    initialize_game()
    update_camera_zoom(False)
    game_state = 'playing'
    main_menu.set_visible(False)
    player.enabled = True
    player.mouse_sensitivity = Vec2(35, 35)
    set_system_cursor_visible(False)
    player.cursor.visible = False
    minimap.set_enabled(minimap_visible)
    start_game_fadein()


def pause_game():
    global game_state

    if player is None:
        return

    update_camera_zoom(False)
    game_state = 'paused'
    player.enabled = False
    player.speed = 0
    head_bob.current_speed = 0.0
    player.mouse_sensitivity = Vec2(0, 0)
    set_system_cursor_visible(True)
    player.cursor.visible = False
    crosshair.set_visible(False)
    minimap.set_enabled(False)
    pause_menu.set_visible(True)


def resume_game():
    global game_state

    if player is None:
        return

    update_camera_zoom(False)
    game_state = 'playing'
    pause_menu.set_visible(False)
    player.enabled = True
    player.mouse_sensitivity = Vec2(35, 35)
    set_system_cursor_visible(False)
    player.cursor.visible = False
    minimap.set_enabled(minimap_visible)


def update_exit_background():
    player_cell = map_renderer.player_cell()
    in_exit = player_cell == map_renderer.exit_room_cell
    sees_open_exit = False

    if map_renderer.exit_sign_door_key is not None:
        door_r, door_c, _ = map_renderer.exit_sign_door_key
        exit_door = map_renderer.active_doors.get(map_renderer.exit_sign_door_key)
        exit_door_visible_open = (
            map_renderer.door_states.get(map_renderer.exit_sign_door_key, False)
            or (exit_door is not None and exit_door.get('open', 0.0) > 0.02)
        )
        sees_open_exit = (
            player_cell == (door_r, door_c)
            and exit_door_visible_open
        )

    show_exit_background = in_exit or sees_open_exit
    background = EXIT_BACKGROUND if show_exit_background else DARK_COLOR
    camera.background_color = background
    scene.fog_color = background
    window.color = background
    return show_exit_background


main_menu = MainMenu(start_game)
pause_menu = PauseMenu(resume_game, application.quit)
suspend_gameplay_for_menu()
start_menu_music()


def update():
    global heartbeat_rate, minimap_scan_was_down, minimap_tab_was_down, minimap_visible

    update_menu_music_fade()

    if game_state == 'paused':
        update_camera_zoom(False)
        pause_menu.update()
        return

    if game_state != 'playing':
        update_camera_zoom(False)
        main_menu.update()
        return

    if game_clear_sequence.update():
        update_camera_zoom(False)
        if held_keys['escape']:
            application.quit()
        return

    if update_death_sequence():
        update_camera_zoom(False)
        if held_keys['escape']:
            application.quit()
        return

    map_renderer.update_rendered_scene()
    map_renderer.process_queues()
    map_renderer.update_doors()
    map_renderer.update_drawers()
    map_renderer.resolve_player_collision()
    update_exit_background()
    if game_clear_sequence.check_trigger(death_state == 'alive'):
        game_clear_sequence.update()
        return

    update_monster_pressure()

    for monster in active_monsters():
        monster.update()

    update_jumpscares()
    update_player_caught()
    if death_state != 'alive':
        update_camera_zoom(False)
        return

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
    active = active_monsters()
    nearest_monster = min(active if active else monsters, key=lambda monster: monster.distance_to_player())
    target_heartbeat_volume, target_heartbeat_rate = heartbeat_targets(nearest_monster)
    heartbeat_lerp = min(1.0, time.dt * HEARTBEAT_SMOOTHING)
    if not game_start_fade_active:
        heartbeat_sound.volume += (target_heartbeat_volume - heartbeat_sound.volume) * heartbeat_lerp
    heartbeat_rate += (target_heartbeat_rate - heartbeat_rate) * heartbeat_lerp
    set_audio_rate(heartbeat_sound, heartbeat_rate)

    if post_effects:
        if nearest_monster.state == 'chase':
            dist = nearest_monster.distance_to_player()
            close = 1.0 - min(1.0, max(0.0, (dist - 2.0) / 14.0))
            post_effects.set_threat(0.45 + close * 0.55)
        elif nearest_monster.state == 'alert':
            post_effects.set_threat(0.65)
        elif nearest_monster.state == 'investigate':
            dist = nearest_monster.distance_to_player()
            close = 1.0 - min(1.0, max(0.0, (dist - 3.0) / 9.0))
            post_effects.set_threat(close * 0.25)
        else:
            post_effects.set_threat(0.0)
        post_effects.update()
    head_bob.update()
    update_jumpscare_look()
    update_game_start_fadein()
    update_camera_zoom()


def teleport_to_exit_door_debug():
    key = getattr(map_renderer, 'exit_sign_door_key', None)

    if key is None:
        return False

    door = map_renderer.active_doors.get(key)
    r, c, _ = key
    spawn_x = c * CELL
    spawn_z = r * CELL
    player.position = (spawn_x, 0, spawn_z)

    if door:
        door_x, _, door_z = door['position']
        player.rotation_y = math.degrees(math.atan2(door_x - spawn_x, door_z - spawn_z))

    map_renderer.debug_unlock_exit_door()
    return True


def input(key):
    if game_state == 'paused':
        pause_menu.handle_key(key)
        return

    if game_state != 'playing':
        main_menu.handle_key(key)
        return

    if game_clear_sequence.is_active():
        return

    if key == 'escape':
        pause_game()
        return

    if key == '1':
        teleport_to_exit_door_debug()
        return

    if key == '2':
        map_renderer.collect_all_notes_cheat()
        return

    if key == 'e':
        interaction = map_renderer.nearest_interaction()
        if map_renderer.interact_nearest() and interaction:
            if interaction[0] == 'door':
                emit_noise(NOISE_DOOR_STRENGTH)
            elif interaction[0] == 'drawer':
                emit_noise(NOISE_DRAWER_STRENGTH)


app.run()
