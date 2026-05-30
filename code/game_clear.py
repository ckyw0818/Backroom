import math
from pathlib import Path

from panda3d.core import Filename, PNMImage
from ursina import Audio, Entity, Text, Vec2, camera, color, time


GAME_CLEAR_AUDIO_FADE_TIME = 4.0
GAME_CLEAR_MUSIC_FADE_TIME = 3.0
GAME_CLEAR_MUSIC_VOLUME = 0.85
GAME_CLEAR_CREDIT_FADE_DELAY = 1.0
GAME_CLEAR_CREDIT_SCROLL_TIME = 58.0
GAME_CLEAR_AUTOWALK_TIME = 2.2
GAME_CLEAR_AUTOWALK_DISTANCE_CELLS = 0.5
PROJECT_DIR = Path(__file__).resolve().parent.parent
IMAGE_UI_PIXELS_PER_UNIT = 720.0
IMAGE_VERTICAL_PADDING = 0.080
CREDIT_START_Y = -1.08
CREDIT_END_SCREEN_Y = 0.78
CREDIT_TEXT_SCALE_MULTIPLIER = 1.4
ENDING_CREDITS = (
    ('image', 'asset/ending_credit/main.png', 0.36, 0.36),
    ('spacer', ''),
    ('section', 'A GAME BY'),
    ('name', 'Choi Yeonwoo / Seoyoon Son'),
    ('spacer', ''),
    ('section', 'CORE DEVELOPMENT'),
    ('pair', 'Director', 'Choi Yeonwoo / Seoyoon Son'),
    ('pair', 'Game Design', 'Choi Yeonwoo / Seoyoon Son'),
    ('pair', 'Programming', 'Choi Yeonwoo / Seoyoon Son'),
    ('pair', 'Level Design', 'Choi Yeonwoo'),
    ('pair', 'Scenario / Writing', 'Choi Yeonwoo'),
    ('pair', 'Map Design', 'Choi Yeonwoo'),
    ('pair', 'Monster AI', 'Choi Yeonwoo'),
    ('pair', 'Lighting System', 'Choi Yeonwoo'),
    ('pair', 'Sound Design', 'Pixabay Royalty-free sound effects and music'),
    ('spacer', ''),
    ('section', 'MADE WITH'),
    ('item', 'Python'),
    ('image', 'asset/ending_credit/python.png', 0.22, 0.22),
    ('item', 'Ursina Engine'),
    ('image', 'asset/ending_credit/ursina.png', 0.22, 0.22),
    ('item', 'Panda3D'),
    ('spacer', ''),
    ('section', '3D MODEL ASSETS'),
    ('asset', 'door_ white_ wooden _Old - 4MB', 'Mehdi Shahsavan'),
    ('asset', 'Lowpoly Bed', 'Mohamed199'),
    ('asset', 'Vintage Wooden Drawer 01 4k', 'mohamedhussien'),
    ('asset', 'Simple metal key', 'Herrah'),
    ('asset', 'Low poly emergency exit sign', 'Mckai'),
    ('asset', 'Keypad', 'Spellkaze'),
    ('source', 'Source: Sketchfab'),
    ('source', 'License: CC BY'),
    ('spacer', ''),
    ('section', 'SPECIAL THANKS'),
    ('item', 'GSHS Computer Science teacher and classmates'),
    ('spacer', ''),
    ('thanks', 'Thank you for playing.'),
    ('copyright', '24111 Choi Yeonwoo / 24056 Seoyoon Son'),
    ('image', 'asset/ending_credit/gshs.png', 0.22, 0.22),
)


def rgba(r, g, b, a):
    return color.Color(r / 255, g / 255, b / 255, a / 255)


def smoothstep01(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


class EndingCredits:
    def __init__(self):
        self.root = Entity(parent=camera.ui, enabled=False)
        self.items = []
        self.root.y = CREDIT_START_Y
        self.scroll_distance = 3.20
        self.build_credits()

    def build_credits(self):
        y = 0.60

        for entry in ENDING_CREDITS:
            kind = entry[0]

            if kind == 'spacer':
                y -= 0.070 * CREDIT_TEXT_SCALE_MULTIPLIER
                continue

            if kind == 'title':
                self.add_credit_text(entry[1], (0, y, -1.2), 2.2)
                y -= 0.125 * CREDIT_TEXT_SCALE_MULTIPLIER
            elif kind == 'image':
                width_percent = entry[2] if len(entry) > 2 else 0.25
                height_percent = entry[3] if len(entry) > 3 else width_percent
                scale = self.image_scale(entry[1], width_percent, height_percent)
                image_y = y - (scale[1] * 0.5)
                self.add_image(entry[1], (0, image_y, -1.2), scale)
                y = image_y - (scale[1] * 0.5) - IMAGE_VERTICAL_PADDING
            elif kind == 'subtitle':
                self.add_credit_text(entry[1], (0, y, -1.2), 1.12)
                y -= 0.135 * CREDIT_TEXT_SCALE_MULTIPLIER
            elif kind == 'section':
                self.add_credit_text(entry[1], (0, y, -1.2), 0.74)
                y -= 0.083 * CREDIT_TEXT_SCALE_MULTIPLIER
            elif kind == 'name':
                self.add_credit_text(entry[1], (0, y, -1.2), 0.92)
                y -= 0.108 * CREDIT_TEXT_SCALE_MULTIPLIER
            elif kind == 'pair':
                self.add_credit_text(entry[1], (-0.09, y, -1.2), 0.56, origin=(1, 0))
                self.add_credit_text(entry[2], (0.09, y, -1.2), 0.56, origin=(-1, 0))
                y -= 0.071 * CREDIT_TEXT_SCALE_MULTIPLIER
            elif kind == 'asset':
                self.add_credit_text(entry[1], (0, y, -1.2), 0.50)
                y -= 0.057 * CREDIT_TEXT_SCALE_MULTIPLIER
                self.add_credit_text(f'by {entry[2]}', (0, y, -1.2), 0.44)
                y -= 0.075 * CREDIT_TEXT_SCALE_MULTIPLIER
            elif kind == 'source':
                self.add_credit_text(entry[1], (0, y, -1.2), 0.45)
                y -= 0.059 * CREDIT_TEXT_SCALE_MULTIPLIER
            elif kind == 'thanks':
                self.add_credit_text(entry[1], (0, y, -1.2), 0.78)
                y -= 0.100 * CREDIT_TEXT_SCALE_MULTIPLIER
            elif kind == 'copyright':
                self.add_credit_text(entry[1], (0, y, -1.2), 0.50)
                y -= 0.071 * CREDIT_TEXT_SCALE_MULTIPLIER
            else:
                self.add_credit_text(entry[1], (0, y, -1.2), 0.50)
                y -= 0.065 * CREDIT_TEXT_SCALE_MULTIPLIER

        end_root_y = CREDIT_END_SCREEN_Y - y
        self.scroll_distance = max(3.20, end_root_y - CREDIT_START_Y)

    def image_scale(self, texture_path, width_percent, height_percent):
        width_px, height_px = self.image_size(texture_path)
        width = (width_px * width_percent) / IMAGE_UI_PIXELS_PER_UNIT
        height = (height_px * height_percent) / IMAGE_UI_PIXELS_PER_UNIT
        return width, height

    def image_size(self, texture_path):
        path = Path(texture_path)
        if not path.is_absolute():
            path = PROJECT_DIR / path

        image = PNMImage()
        if image.read(Filename.from_os_specific(str(path))):
            return max(1, image.get_x_size()), max(1, image.get_y_size())

        return 160, 160

    def add_text(self, text, position, scale, origin=(0, 0)):
        item = Text(
            parent=self.root,
            text=text,
            origin=origin,
            position=position,
            scale=scale,
            color=rgba(20, 20, 20, 0),
        )
        item.always_on_top = True
        self.items.append((item, (20, 20, 20)))

    def add_credit_text(self, text, position, scale, origin=(0, 0)):
        self.add_text(text, position, scale * CREDIT_TEXT_SCALE_MULTIPLIER, origin)

    def add_image(self, texture_path, position, scale):
        item = Entity(
            parent=self.root,
            model='quad',
            texture=texture_path,
            position=position,
            scale=scale,
            color=rgba(255, 255, 255, 0),
        )
        item.always_on_top = True
        self.items.append((item, (255, 255, 255)))

    def set_visible(self, visible):
        self.root.enabled = visible

    def update(self, progress):
        progress = max(0.0, min(1.0, progress))
        self.set_visible(progress > 0.0)
        self.root.y = CREDIT_START_Y + progress * self.scroll_distance
        alpha = 255 if progress > 0.0 else 0

        for item, base_color in self.items:
            item.color = rgba(base_color[0], base_color[1], base_color[2], alpha)


class GameClearSequence:
    def __init__(
        self,
        player,
        map_renderer,
        cell_size,
        vent_ambience,
        heartbeat_sound,
        crosshair,
        minimap,
        fade_monster_sounds,
        update_exit_background,
        post_effects,
        guide_text=None,
    ):
        self.player = player
        self.map_renderer = map_renderer
        self.autowalk_distance = cell_size * GAME_CLEAR_AUTOWALK_DISTANCE_CELLS
        self.vent_ambience = vent_ambience
        self.heartbeat_sound = heartbeat_sound
        self.crosshair = crosshair
        self.minimap = minimap
        self.fade_monster_sounds = fade_monster_sounds
        self.update_exit_background = update_exit_background
        self.post_effects = post_effects
        self.guide_text = guide_text
        self.credits = EndingCredits()
        self.ending_credit_music = Audio(
            'asset/sound/ending_credit.wav',
            autoplay=False,
            loop=False,
            volume=0.0,
        )

        self.state = 'inactive'
        self.timer = 0.0
        self.vent_start_volume = 0.0
        self.heartbeat_start_volume = 0.0
        self.guide_text_start_alpha = 0.0
        self.ending_credit_started = False
        self.walk_start = None
        self.walk_end = None

    def is_active(self):
        return self.state != 'inactive'

    def start(self):
        if self.is_active():
            return False

        dir_x, dir_z = self.exit_forward_vector()
        self.state = 'fade_audio'
        self.timer = 0.0
        self.vent_start_volume = self.vent_ambience.volume
        self.heartbeat_start_volume = self.heartbeat_sound.volume
        self.guide_text_start_alpha = self.guide_text.color.a if self.guide_text else 0.0
        self.walk_start = (float(self.player.x), float(self.player.z))
        self.walk_end = (
            self.walk_start[0] + dir_x * self.autowalk_distance,
            self.walk_start[1] + dir_z * self.autowalk_distance,
        )
        self.player.mouse_sensitivity = Vec2(0, 0)
        self.player.rotation_y = math.degrees(math.atan2(dir_x, dir_z))
        camera.rotation = (0, 0, 0)
        self.player.speed = 0
        self.crosshair.set_visible(False)
        self.minimap.set_enabled(False)
        self.fade_monster_sounds(1.0)
        self.ending_credit_music.stop()
        self.ending_credit_music.volume = 0.0
        self.ending_credit_started = False
        self.credits.set_visible(False)
        return True

    def update(self):
        if not self.is_active():
            return False

        self.player.speed = 0
        self.timer += time.dt
        self.update_exit_background()
        self.update_autowalk()

        fade_progress = min(1.0, self.timer / GAME_CLEAR_AUDIO_FADE_TIME)
        fade_amount = 1.0 - smoothstep01(fade_progress)
        self.vent_ambience.volume = self.vent_start_volume * fade_amount
        self.heartbeat_sound.volume = self.heartbeat_start_volume * fade_amount
        self.fade_monster_sounds(fade_amount)
        self.update_guide_text(fade_amount)

        if fade_progress >= 1.0:
            self.vent_ambience.stop()
            self.heartbeat_sound.stop()
            self.update_ending_credit_music()

        credit_start = GAME_CLEAR_AUTOWALK_TIME + GAME_CLEAR_CREDIT_FADE_DELAY
        credit_progress = max(0.0, self.timer - credit_start) / GAME_CLEAR_CREDIT_SCROLL_TIME
        self.credits.update(min(1.0, credit_progress))

        if self.post_effects:
            self.post_effects.set_threat(0.0)
            self.post_effects.update()

        return True

    def update_guide_text(self, fade_amount):
        if not self.guide_text:
            return

        self.guide_text.color = color.Color(
            self.guide_text.color.r,
            self.guide_text.color.g,
            self.guide_text.color.b,
            self.guide_text_start_alpha * fade_amount,
        )

    def update_ending_credit_music(self):
        music_time = self.timer - GAME_CLEAR_AUDIO_FADE_TIME

        if music_time < 0.0:
            return

        if not self.ending_credit_started:
            self.ending_credit_music.volume = 0.0
            self.ending_credit_music.play()
            self.ending_credit_started = True

        music_progress = min(1.0, music_time / GAME_CLEAR_MUSIC_FADE_TIME)
        self.ending_credit_music.volume = GAME_CLEAR_MUSIC_VOLUME * smoothstep01(music_progress)

    def update_autowalk(self):
        if self.walk_start is None or self.walk_end is None:
            return

        progress = min(1.0, self.timer / GAME_CLEAR_AUTOWALK_TIME)
        amount = smoothstep01(progress)
        sx, sz = self.walk_start
        ex, ez = self.walk_end
        self.player.x = sx + (ex - sx) * amount
        self.player.z = sz + (ez - sz) * amount

    def exit_forward_vector(self):
        room_cell = self.map_renderer.exit_room_cell
        key = self.map_renderer.exit_sign_door_key

        if room_cell is None or key is None:
            return 0.0, 1.0

        door_r, door_c, _ = key
        room_r, room_c = room_cell
        dx = room_c - door_c
        dz = room_r - door_r
        dist = max((dx * dx + dz * dz) ** 0.5, 0.001)
        return dx / dist, dz / dist

    def check_trigger(self, can_start=True):
        if self.is_active() or not can_start:
            return False

        if self.map_renderer.player_cell() != self.map_renderer.exit_room_cell:
            return False

        return self.start()
