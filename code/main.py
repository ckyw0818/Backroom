import math
import os
import random
import time as _t

from ursina import *
try:
    from ursina.shaders import lit_with_shadows_shader
except ImportError:
    lit_with_shadows_shader = None

from pathlib import Path

from direct.showbase import ShowBaseGlobal
from panda3d.core import AmbientLight as Panda3dAmbientLight, Point2, PStatCollector, loadPrcFileData

from character.monster import MonsterAI, NOISE_ATTRACT_RADIUS_CELLS
from character.player_controller import CAMERA_FOV, RUN_SPEED, HeadBob, create_player
from furniture.door import DOOR_DENSITY, DOOR_FACE_SALTS
from game_clear import GameClearSequence
from main_menu import MainMenu, PauseMenu
from map.game_map import MapRenderer
from map.light import LightSystem
from map.map_data import CELL, LAYOUT, START_ROOM_CELL, WALL_H
from map.minimap import MINIMAP_ENABLED, NOISE_RING_RADIUS_CELLS, SCAN_RADIUS_CELLS, Minimap
from utill.post_effects import PostEffects
from utill.textures import DARK_COLOR, load_environment_textures


HEARTBEAT_IDLE_VOLUME = 0.5
HEARTBEAT_IDLE_RATE = 0.72
HEARTBEAT_CHASE_MIN_VOLUME = 0.5
HEARTBEAT_CHASE_MAX_VOLUME = 2.4
HEARTBEAT_CHASE_MIN_RATE = 0.9
HEARTBEAT_CHASE_MAX_RATE = 2.3
HEARTBEAT_MIN_DISTANCE = 2.0
HEARTBEAT_MAX_DISTANCE = 1000
HEARTBEAT_SMOOTHING = 4.5
CROSSHAIR_SIZE = 0.010
CROSSHAIR_DOOR_SIZE = 0.017
CROSSHAIR_SMOOTHING = 14.0
NOISE_SONAR_STRENGTH = SCAN_RADIUS_CELLS / NOISE_ATTRACT_RADIUS_CELLS
NOISE_DOOR_STRENGTH = NOISE_RING_RADIUS_CELLS / NOISE_ATTRACT_RADIUS_CELLS
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
MONSTER_SPAWN_COUNT = 3
MONSTER_SPAWN_MIN_DISTANCE = 20
MONSTER_SPAWN_MIN_SEPARATION = 8
MONSTER_FINAL_NOTE_SPEED_MULTIPLIER = 1.25
ZOOM_KEYS = ('control', 'left control', 'right control')
ZOOM_TIME = 0.5
ZOOM_FOV = CAMERA_FOV * 0.5
POST_EFFECT_STRENGTH_MIN = 0.0
POST_EFFECT_STRENGTH_MAX = 1.5


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

    target = 1.0 if active and any(held_keys[key] for key in ZOOM_KEYS) else 0.0
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
    if all_monsters_active_cheat:
        note_count = collected_note_count()
        speed_multiplier = MONSTER_FINAL_NOTE_SPEED_MULTIPLIER if note_count >= 5 else 1.0
        for monster in monsters:
            set_monster_active(monster, True)
            monster.set_speed_multiplier(speed_multiplier)
        return

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


def activate_all_monsters_cheat():
    global all_monsters_active_cheat

    all_monsters_active_cheat = True
    update_monster_pressure()
    print('cheat: all monsters active')


def emit_noise(strength):
    cell = player_noise_cell()
    for monster in active_monsters():
        monster.investigate_noise(cell, strength)


def emit_noise_to_monsters(target_monsters, strength):
    cell = player_noise_cell()
    for monster in target_monsters:
        if monster_active(monster):
            monster.investigate_noise(cell, strength)


def emit_noise_in_radius(radius_cells, strength):
    cell = player_noise_cell()
    for monster in active_monsters():
        if monster.grid_distance(monster.monster_cell(), cell) <= radius_cells:
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
    global death_overlay_alpha

    if death_overlay is None:
        return

    alpha = max(0.0, min(1.0, alpha))
    enabled = alpha > 0.0
    alpha_byte = int(255 * alpha)
    state = (enabled, alpha_byte)
    if death_overlay_alpha == state:
        return

    death_overlay_alpha = state
    death_overlay.enabled = enabled
    death_overlay.color = rgba(0, 0, 0, alpha_byte)


def set_death_screen_visible(visible):
    if death_screen:
        death_screen.set_visible(visible)


def set_held_notes_visible(visible):
    if map_renderer and hasattr(map_renderer, 'set_held_notes_visible'):
        map_renderer.set_held_notes_visible(visible)


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
            set_held_notes_visible(False)
            player.enabled = False
            player.cursor.visible = False
            crosshair.set_visible(False)
            minimap.set_enabled(False)
            set_system_cursor_visible(True)
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
        self._visible = True
        self._door_ready = None

    def set_visible(self, visible):
        if self._visible == visible:
            return
        self._visible = visible
        self.outer.enabled = visible
        self.inner.enabled = visible

    def update(self, door_ready, hidden):
        self.set_visible(not hidden)

        if hidden:
            return

        target = CROSSHAIR_DOOR_SIZE if door_ready else CROSSHAIR_SIZE
        k = min(1.0, time.dt * CROSSHAIR_SMOOTHING)
        scale = self.outer.scale_x + (target - self.outer.scale_x) * k
        if abs(scale - self.outer.scale_x) > 1e-6:
            self.outer.scale = scale
            self.inner.scale = scale * 0.52
        if self._door_ready != door_ready:
            self._door_ready = door_ready
            self.outer.color = rgba(255, 236, 165, 175 if door_ready else 115)


class DeathScreen:
    HEART_TEXTURE = 'asset/texture/heart.png'
    HEART_LOST_TEXTURE = 'asset/texture/heart_gray.png'
    HEART_TINT = (255, 255, 255)
    HEART_SCALE = 0.13

    def __init__(self, restart_callback=None, main_menu_callback=None):
        self.restart_callback = restart_callback
        self.main_menu_callback = main_menu_callback
        self.root = Entity(parent=camera.ui, enabled=False)
        self.hearts = []
        self.game_over_buttons = []

        for index, x in enumerate((-0.18, 0.0, 0.18)):
            heart_root = Entity(
                parent=self.root,
                origin=(0, 0),
                position=(x, 0.03, -1.2),
                scale=self.HEART_SCALE,
            )
            heart_full = Entity(
                parent=heart_root,
                model='quad',
                texture=self.HEART_TEXTURE,
                origin=(0, 0),
                color=rgba(*self.HEART_TINT, 255),
            )
            heart_lost = Entity(
                parent=heart_root,
                model='quad',
                texture=self.HEART_LOST_TEXTURE,
                origin=(0, 0),
                position=(0, 0, -0.001),
                color=rgba(*self.HEART_TINT, 0),
            )
            heart_full.always_on_top = True
            heart_lost.always_on_top = True
            self.hearts.append({
                'root': heart_root,
                'full': heart_full,
                'lost': heart_lost,
            })

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
        self.game_over.setBin('fixed', 140)
        self.game_over.setDepthWrite(False)
        self.game_over.setDepthTest(False)

        self.restart_button = self.add_game_over_button('Restart Game', -0.300, self.restart_callback)
        self.main_menu_button = self.add_game_over_button('Main Menu', -0.405, self.main_menu_callback)

    def set_visible(self, visible):
        self.root.enabled = visible

    def add_game_over_button(self, text, y, callback):
        button = Button(
            parent=self.root,
            text='',
            position=(0, y, -1.2),
            scale=(0.42, 0.082),
            color=rgba(0, 0, 0, 0),
            highlight_color=rgba(0, 0, 0, 0),
            pressed_color=rgba(0, 0, 0, 0),
            on_click=callback,
            enabled=False,
        )
        button.collider = 'box'
        button.always_on_top = True
        button.setBin('fixed', 140)
        button.setDepthWrite(False)
        button.setDepthTest(False)

        label = Text(
            parent=self.root,
            text=f'[ {text} ]',
            origin=(0, 0),
            position=(0, y + 0.002, -1.3),
            scale=1.08,
            color=rgba(235, 231, 205, 0),
            enabled=False,
        )
        label.always_on_top = True
        label.setBin('fixed', 141)
        label.setDepthWrite(False)
        label.setDepthTest(False)

        self.game_over_buttons.append((button, label))
        return button, label

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
            heart['root'].scale = self.HEART_SCALE
            full_alpha = 255
            lost_alpha = 0

            if lost_index == index:
                amount = smoothstep01(anim_progress)
                full_alpha = int(255 * (1.0 - amount))
                lost_alpha = int(255 * amount)
                pulse = 1.0 + 0.18 * math.sin(min(1.0, anim_progress) * math.pi)
                heart['root'].scale = self.HEART_SCALE * pulse
            elif lost:
                full_alpha = 0
                lost_alpha = 255

            if heart.get('_full_alpha') != full_alpha:
                heart['full'].color = rgba(*self.HEART_TINT, full_alpha)
                heart['_full_alpha'] = full_alpha
            if heart.get('_lost_alpha') != lost_alpha:
                heart['lost'].color = rgba(*self.HEART_TINT, lost_alpha)
                heart['_lost_alpha'] = lost_alpha

        self.game_over.enabled = show_game_over
        if show_game_over:
            fade = min(1.0, max(0.0, game_over_progress))
            game_over_alpha = int(255 * fade)
            if getattr(self, '_game_over_alpha', -1) != game_over_alpha:
                self.game_over.color = rgba(230, 230, 230, game_over_alpha)
                self._game_over_alpha = game_over_alpha
            for button, label in self.game_over_buttons:
                button.enabled = fade >= 0.85
                label.enabled = True
                alpha = int(255 * fade)
                hovered = button.hovered
                prev = getattr(label, '_color_state', None)
                new_state = (hovered, alpha)
                if prev != new_state:
                    label.color = rgba(246, 214, 122, alpha) if hovered else rgba(235, 231, 205, alpha)
                    label._color_state = new_state
        else:
            for button, label in self.game_over_buttons:
                button.enabled = False
                label.enabled = False


if os.environ.get('BACKROOM_PSTATS') == '1':
    loadPrcFileData('', '''
want-pstats true
pstats-tasks true
pstats-gpu-timing true
''')

loadPrcFileData('', 'garbage-collect-states-rate 6')

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
post_effect_strength = 1.0
minimap = None
crosshair = None
death_overlay = None
death_overlay_alpha = None
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
minimap_debug_disabled = False
held_hud_debug_disabled = False
light_fixtures_debug_disabled = False
all_monsters_active_cheat = False
exit_background_visible = False


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
    global death_overlay, death_overlay_alpha, death_screen, game_clear_sequence, guide_text
    global vent_ambience, sonar_sound, heartbeat_sound, jumpscare_sound
    global death_state, death_timer, player_hearts, death_lost_heart_index
    global jumpscare_timer, jumpscare_monster, jumpscare_look_timer, heartbeat_rate

    if game_clear_sequence is not None:
        return

    textures = load_environment_textures()
    light_system = LightSystem(LAYOUT, CELL, WALL_H)
    START_ROOM_CELL_RUNTIME = random_start_room_cell()
    player = create_player(CELL, *START_ROOM_CELL_RUNTIME, spawn_yaw=-90)
    footstep_sounds = [f'asset/sound/foot{i}.wav' for i in range(1, 4)]
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
            chase_speed=RUN_SPEED * 5.4,
        )
        for texture, spawn_cell in monster_specs
    ]
    for monster in monsters:
        monster.set_door_system(map_renderer, MONSTER_SPAWN_MIN_DISTANCE)
    update_monster_pressure()
    post_effects = PostEffects(effect_strength=post_effect_strength)

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
    death_overlay_alpha = None
    death_screen = DeathScreen(restart_game_from_game_over, return_to_main_menu_from_game_over)
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


def update_exit_background(force=False):
    global exit_background_visible

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
    if not force and show_exit_background == exit_background_visible:
        return show_exit_background

    exit_background_visible = show_exit_background
    background = EXIT_BACKGROUND if show_exit_background else DARK_COLOR
    camera.background_color = background
    scene.fog_color = background
    window.color = background
    return show_exit_background


def get_post_effect_strength():
    return post_effect_strength


def set_post_effect_strength(value):
    global post_effect_strength

    post_effect_strength = max(POST_EFFECT_STRENGTH_MIN, min(POST_EFFECT_STRENGTH_MAX, value))
    post_effect_strength = round(post_effect_strength, 2)

    if post_effects:
        post_effects.set_effect_strength(post_effect_strength)
        post_effects.set_inputs()


def stop_audio_persistent(sound):
    if not sound:
        return

    try:
        sound.stop(destroy=False)
    except TypeError:
        sound.stop()


def reset_game_clear_sequence():
    if not game_clear_sequence:
        return

    game_clear_sequence.state = 'inactive'
    game_clear_sequence.timer = 0.0
    game_clear_sequence.ending_credit_started = False
    game_clear_sequence.walk_start = None
    game_clear_sequence.walk_end = None
    game_clear_sequence.credits.set_visible(False)
    game_clear_sequence.ending_credit_music.volume = 0.0
    stop_audio_persistent(game_clear_sequence.ending_credit_music)


def reset_map_progress():
    if not map_renderer:
        return

    map_renderer.door_states.clear()
    map_renderer.door_lock_states.clear()
    map_renderer.drawer_states.clear()
    map_renderer.collected_notes.clear()
    map_renderer.has_key = False
    map_renderer.key_taken = False
    map_renderer._moving_door_keys.clear()
    map_renderer._moving_drawer_keys.clear()
    map_renderer._active_key_glow_key = None

    if map_renderer.held_key_entity:
        map_renderer.held_key_entity.enabled = False
    for note in map_renderer.held_note_entities.values():
        note.enabled = False
    for note in getattr(map_renderer, 'held_note_slots', ()):
        note.enabled = False
    for placeholder in map_renderer.held_note_placeholders:
        placeholder.enabled = False
    map_renderer.held_note_entities.clear()

    for door in map_renderer.active_doors.values():
        door['open'] = 0.0

    for drawer_key, drawer in map_renderer.active_drawers.items():
        drawer['open'] = 0.0
        key_data = drawer.get('key')
        if key_data:
            key_data['node'].show()
            key_data['glow'].hide()
        note_data = drawer.get('note')
        if note_data:
            note_data['node'].show()

    for keypad in map_renderer.active_keypads.values():
        keypad['input'] = ''
        keypad['message_timer'] = 0.0
        keypad['pending_result_sound'] = None
        keypad['pending_unlock'] = False
        map_renderer.set_keypad_display_text(keypad, '')

    map_renderer.reset_start_room_lock_and_key()
    map_renderer._raycast_cache_key = None
    map_renderer.update_rendered_scene(force=True)
    map_renderer.process_queues()


def reset_game_run():
    global death_state, death_timer, player_hearts, death_lost_heart_index
    global minimap_visible, heartbeat_rate, jumpscare_timer, jumpscare_monster, jumpscare_look_timer
    global all_monsters_active_cheat

    reset_game_clear_sequence()
    reset_map_progress()
    all_monsters_active_cheat = False
    player_hearts = MAX_PLAYER_HEARTS
    death_lost_heart_index = None
    death_state = 'alive'
    death_timer = 0.0
    jumpscare_timer = 0.0
    jumpscare_monster = None
    jumpscare_look_timer = 0.0
    jumpscare_sound.stop()
    reset_run_after_death()
    player_hearts = MAX_PLAYER_HEARTS
    death_lost_heart_index = None
    death_state = 'alive'
    death_timer = 0.0
    heartbeat_rate = HEARTBEAT_IDLE_RATE
    heartbeat_sound.volume = 0.0
    set_audio_rate(heartbeat_sound, heartbeat_rate)
    fade_monster_sounds(0.0)
    set_death_screen_visible(False)
    minimap_visible = False
    minimap.set_enabled(False)


def restart_game_from_game_over():
    global game_state

    reset_game_run()
    game_state = 'playing'
    pause_menu.set_visible(False)
    main_menu.set_visible(False)
    player.enabled = True
    player.speed = RUN_SPEED
    player.mouse_sensitivity = Vec2(35, 35)
    player.cursor.visible = False
    set_system_cursor_visible(False)
    start_game_fadein()


def return_to_main_menu_from_game_over():
    global game_state

    reset_game_run()
    game_state = 'menu'
    pause_menu.set_visible(False)
    main_menu.set_visible(True)
    suspend_gameplay_for_menu()
    set_death_overlay_alpha(0.0)
    start_menu_music()


main_menu = MainMenu(start_game, get_post_effect_strength, set_post_effect_strength)
pause_menu = PauseMenu(resume_game, application.quit, get_post_effect_strength, set_post_effect_strength)
suspend_gameplay_for_menu()
start_menu_music()


_prof_t = 0.0
_prof_frames = 0
_sect = {}
_pstat_collectors = {}
_pressure_frame = 0
_state_probe_done = False


def _pstat_collector(name):
    collector = _pstat_collectors.get(name)
    if collector is None:
        collector = PStatCollector(f'App:Backroom:{name}')
        _pstat_collectors[name] = collector
    return collector


def _tm(name, fn, *a, **k):
    collector = _pstat_collector(name)
    start = _t.perf_counter()
    collector.start()
    try:
        return fn(*a, **k)
    finally:
        collector.stop()
        _sect[name] = _sect.get(name, 0.0) + (_t.perf_counter() - start)


import gc
from panda3d.core import RenderState, TransformState

def dbg():
    from ursina import scene
    f = max(1, _prof_frames)
    dt_ms = (_sect.pop('frame_dt', 0.0) / f) * 1000
    update_ms = (_sect.get('update_py', 0.0) / f) * 1000
    engine_gap = max(0.0, dt_ms - update_ms)
    top = sorted(_sect.items(), key=lambda x: -x[1])[:8]
    ms = ', '.join(f'{n}={v/f*1000:.2f}' for n, v in top)
    drawn = sum(1 for e in scene.entities
                if getattr(e, 'enabled', False) and getattr(e, 'model', None) is not None)
    active_count = len(active_monsters()) if monsters else 0
    if map_renderer:
        cache_count = len(getattr(map_renderer, '_visibility_cache', ()))
        vis = (
            len(map_renderer.prebuilt_static_chunks),
            len(map_renderer._visible_cells),
            len(map_renderer._visible_rooms),
            len(map_renderer.prebuilt_light_chunks),
        )
    else:
        cache_count = 0
        vis = (0, 0, 0, 0)
    pyobj = len(gc.get_objects())          # Python 힙 누수 감지 (설치 불필요)
    try:
        import psutil, os
        ram = psutil.Process(os.getpid()).memory_info().rss / 1e6
    except Exception:
        ram = -1.0
    print(
        f'fps={_prof_frames} dt={dt_ms:.1f}ms engine~={engine_gap:.1f}ms | {ms} | '
        f'drawn={drawn} monsters={active_count}/{len(monsters)} cache={cache_count} '
        f'static/cells/rooms/lights={vis[0]}/{vis[1]}/{vis[2]}/{vis[3]} '
        f'post={post_effects is not None} mini_off={minimap_debug_disabled} '
        f'held_off={held_hud_debug_disabled} lights_off={light_fixtures_debug_disabled} '
        f'pyobj={pyobj} ram={ram:.0f}MB'
    )
    print('states r/t=', RenderState.getNumStates(), TransformState.getNumStates())
    global _state_probe_done
    if not _state_probe_done and RenderState.getNumStates() > 20000:
        _state_probe_done = True
        from collections import Counter
        hist = Counter()
        for st in RenderState.getStates():
            if st is None:
                continue
            try:
                names = [a.getType().getName() for a in st.attribs.values()]
            except Exception:
                names = [w for w in str(st).replace(':', ' ').split()
                         if w.endswith('Attrib')]
            hist[tuple(sorted(names))] += 1
        print('=== RenderState attribute histogram (top 10) ===')
        for attrs, count in hist.most_common(10):
            print(f'  {count:6d}  {attrs}')
    _sect.clear()

def update():
    global heartbeat_rate, minimap_scan_was_down, minimap_tab_was_down, minimap_visible

    frame_start = _t.perf_counter()
    _sect['frame_dt'] = _sect.get('frame_dt', 0.0) + time.dt
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

    _tm('scene', map_renderer.update_rendered_scene)
    _tm('queues', map_renderer.process_queues)
    _tm('doors', map_renderer.update_doors)
    _tm('drawers', map_renderer.update_drawers)
    _tm('head', head_bob.update)
    _tm('coll', map_renderer.resolve_player_collision)
    _tm('exitbg', update_exit_background)
    if _tm('clear_check', game_clear_sequence.check_trigger, death_state == 'alive'):
        _tm('clear', game_clear_sequence.update)
        return

    global _pressure_frame
    _pressure_frame += 1
    if _pressure_frame >= 6:
        _pressure_frame = 0
        _tm('pressure', update_monster_pressure)

    active = active_monsters()
    monster_start = _t.perf_counter()
    monster_collector = _pstat_collector('monsters')
    monster_collector.start()
    try:
        for monster in active:
            monster.update()
    finally:
        monster_collector.stop()
        _sect['monsters'] = _sect.get('monsters', 0.0) + (_t.perf_counter() - monster_start)

    _tm('jumps', update_jumpscares)
    _tm('caught', update_player_caught)
    if death_state != 'alive':
        update_camera_zoom(False)
        return

    minimap_scan_down = held_keys['r']
    if minimap_scan_down and not minimap_scan_was_down:
        detected_monsters = minimap.scan()
        if detected_monsters is not None:
            emit_noise_to_monsters(detected_monsters, NOISE_SONAR_STRENGTH)
            sonar_sound.play()
    minimap_scan_was_down = minimap_scan_down

    minimap_tab_down = held_keys['tab']
    if minimap_tab_down and not minimap_tab_was_down:
        minimap_visible = not minimap_visible
        if not minimap_debug_disabled:
            minimap.set_enabled(minimap_visible)
    minimap_tab_was_down = minimap_tab_down

    if minimap_debug_disabled:
        minimap.set_enabled(False)
    else:
        _tm('mini', minimap.update)
    if held_hud_debug_disabled:
        set_held_hud_debug_visible(False)
    interact_ready = _tm('interact', map_renderer.can_interact)
    crosshair.update(interact_ready, minimap_visible)
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
        _tm('post', post_effects.update)
    _tm('look', update_jumpscare_look)
    _tm('startfade', update_game_start_fadein)
    _tm('zoom', update_camera_zoom)
    _sect['update_py'] = _sect.get('update_py', 0.0) + (_t.perf_counter() - frame_start)
    global _prof_t, _prof_frames
    _prof_t += time.dt
    _prof_frames += 1
    if _prof_t >= 1:
        dbg()
        _prof_t = 0
        _prof_frames = 0


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


def teleport_to_monster_front_debug():
    active = active_monsters()
    if not active:
        print('debug: no active monster')
        return False

    monster = min(active, key=lambda item: item.distance_to_player())
    yaw_rad = math.radians(float(monster.entity.rotation_y))
    dir_x = math.sin(yaw_rad)
    dir_z = math.cos(yaw_rad)

    if abs(dir_x) + abs(dir_z) < 0.001:
        dir_x, dir_z = 0.0, 1.0

    distance = max(DEATH_DISTANCE * 2.5, 2.2)
    player.position = (
        monster.entity.x + dir_x * distance,
        0,
        monster.entity.z + dir_z * distance,
    )
    player.rotation_y = math.degrees(math.atan2(monster.entity.x - player.x, monster.entity.z - player.z))
    player.speed = RUN_SPEED
    monster.set_state('chase')
    map_renderer._raycast_cache_key = None
    map_renderer.update_rendered_scene(force=True)
    print('debug: teleported player in front of monster')
    return True


def print_scene_analyze_debug():
    print('--- render.analyze() ---')
    render_root.analyze()
    try:
        geom_nodes = render_root.findAllMatches('**/+GeomNode').getNumPaths()
    except Exception:
        geom_nodes = -1
    print(
        'entities', len(scene.entities),
        'drawn', sum(1 for e in scene.entities if getattr(e, 'enabled', False) and getattr(e, 'model', None) is not None),
        'geom_nodes', geom_nodes,
    )


def disable_post_effects_debug():
    global post_effects

    if post_effects is None:
        print('debug: post effects already off')
        return

    try:
        post_effects.cleanup()
    except Exception as exc:
        print(f'debug: post cleanup failed: {exc}')
    post_effects = None
    print('debug: post effects OFF')


def toggle_minimap_debug():
    global minimap_debug_disabled

    minimap_debug_disabled = not minimap_debug_disabled
    if minimap:
        minimap.set_enabled(False if minimap_debug_disabled else minimap_visible)
    print(f'debug: minimap hard off = {minimap_debug_disabled}')


def set_held_hud_debug_visible(visible):
    if not map_renderer:
        return
    if hasattr(map_renderer, 'set_held_notes_visible'):
        map_renderer.set_held_notes_visible(visible)
    held_key = getattr(map_renderer, 'held_key_entity', None)
    if held_key:
        held_key.enabled = visible and getattr(map_renderer, 'has_key', False)


def toggle_held_hud_debug():
    global held_hud_debug_disabled

    held_hud_debug_disabled = not held_hud_debug_disabled
    set_held_hud_debug_visible(not held_hud_debug_disabled)
    print(f'debug: held hud off = {held_hud_debug_disabled}')


def toggle_light_fixtures_debug():
    global light_fixtures_debug_disabled

    light_fixtures_debug_disabled = not light_fixtures_debug_disabled
    if map_renderer and hasattr(map_renderer, 'set_light_fixtures_debug_enabled'):
        map_renderer.set_light_fixtures_debug_enabled(not light_fixtures_debug_disabled)
    print(f'debug: light fixtures off = {light_fixtures_debug_disabled}')


def print_engine_debug():
    base = ShowBaseGlobal.base
    print('--- engine debug ---')
    try:
        clock = ShowBaseGlobal.globalClock
        print('clock fps', clock.getAverageFrameRate(), 'dt', clock.getDt())
    except Exception as exc:
        print('clock unavailable', exc)

    try:
        win = base.win
        props = win.getProperties()
        print('window', props.getXSize(), props.getYSize(), 'fullscreen', props.getFullscreen())
        gsg = win.getGsg()
        if gsg:
            for label, method_name in (
                ('vendor', 'getDriverVendor'),
                ('renderer', 'getDriverRenderer'),
                ('version', 'getDriverVersion'),
            ):
                method = getattr(gsg, method_name, None)
                if method:
                    print(label, method())
    except Exception as exc:
        print('window/gsg unavailable', exc)

    try:
        task_mgr = base.taskMgr
        tasks = []
        for method_name in ('getAllTasks', 'getTasks'):
            method = getattr(task_mgr, method_name, None)
            if method:
                tasks = list(method())
                break
        print('tasks', len(tasks))
        for task in tasks[:30]:
            print(' task', getattr(task, 'name', task))
    except Exception as exc:
        print('tasks unavailable', exc)


def input(key):
    if game_state == 'paused':
        pause_menu.handle_key(key)
        return

    if game_state != 'playing':
        main_menu.handle_key(key)
        return

    if game_clear_sequence.is_active():
        return

    if death_state != 'alive':
        return

    if key == 'escape':
        pause_game()
        return

    if key in ('-', 'minus'):
        activate_all_monsters_cheat()
        return

    if key == '0':
        teleport_to_monster_front_debug()
        return

    if key == '1':
        teleport_to_exit_door_debug()
        return

    if key == '2':
        map_renderer.collect_all_notes_cheat()
        return

    if key == '3':
        print_scene_analyze_debug()
        return

    if key == '4':
        disable_post_effects_debug()
        return

    if key == '5':
        toggle_minimap_debug()
        return

    if key == '6':
        toggle_held_hud_debug()
        return

    if key == '7':
        toggle_light_fixtures_debug()
        return

    if key == '8':
        print_engine_debug()
        return

    if key == 'e':
        interaction = map_renderer.nearest_interaction()
        if map_renderer.interact_nearest() and interaction:
            if interaction[0] == 'door':
                emit_noise_in_radius(NOISE_RING_RADIUS_CELLS, NOISE_DOOR_STRENGTH)
            elif interaction[0] == 'drawer':
                emit_noise(NOISE_DRAWER_STRENGTH)


app.run()
