import math
import random

from ursina import Button, Entity, Text, application, camera, color, time


def rgba(r, g, b, a):
    return color.Color(r / 255, g / 255, b / 255, a / 255)


HELP_ROWS = (
    ('WASD', 'Move'),
    ('Mouse', 'Look'),
    ('Shift + WASD', 'Run'),
    ('E', 'Interact'),
    ('TAB', 'Minimap'),
    ('R', 'Refresh minimap'),
    ('Z', 'Zoom'),
    ('ESC', 'Pause'),
)
HELP_TEXT = '\n'.join(f'{key} - {action}' for key, action in HELP_ROWS)

LOADING_HINTS = (
    'Hiding is not always safe.',
    'A door sound might be loud enough for them to find you.',
    'Is this place real?',
    'If they hear you, keep moving.',
    'Find the way out.',
    'Do not call them too often.',
)

class TextMenuButton:
    def __init__(self, parent, text, y, callback):
        self.button = Button(
            parent=parent,
            text='',
            position=(0, y, -1.2),
            scale=(0.36, 0.082),
            color=rgba(0, 0, 0, 0),
            highlight_color=rgba(0, 0, 0, 0),
            pressed_color=rgba(0, 0, 0, 0),
            on_click=callback,
        )
        self.button.collider = 'box'
        self.button.always_on_top = True
        self.label = Text(
            parent=parent,
            text=f'[ {text} ]',
            origin=(0, 0),
            position=(0, y + 0.002, -1.3),
            scale=1.35,
            color=rgba(235, 231, 205, 255),
        )
        self.label.always_on_top = True

    def as_pair(self):
        return self.button, self.label


class MainMenu:
    def __init__(self, start_callback):
        self.start_callback = start_callback
        self.root = Entity(parent=camera.ui)
        self.anim_time = 0.0
        self.background_root = Entity(parent=self.root, position=(0, 0, 0.8))
        self.background_layers = []
        for offset, alpha in (
            ((0.000, 0.000), 150),
            ((0.012, 0.006), 52),
            ((-0.012, -0.006), 52),
            ((0.006, -0.012), 42),
            ((-0.006, 0.012), 42),
        ):
            layer = Entity(
                parent=self.background_root,
                model='quad',
                texture='asset/menu_background.png',
                color=rgba(135, 135, 135, alpha),
                position=(offset[0], offset[1], 0),
                scale=(2.45, 1.38),
            )
            self.background_layers.append((layer, offset))

        self.background_dim = Entity(
            parent=self.root,
            model='quad',
            color=rgba(0, 0, 0, 105),
            position=(0, 0, 0.7),
            scale=(2.1, 2.1),
        )
        self.title = Entity(
            parent=self.root,
            model='quad',
            texture='asset/escape_nobackground.png',
            position=(0, 0.30, -1.1),
            scale=(0.62, 0.18),
        )
        self.buttons = []
        self.help_items = []
        self.credit_items = []
        self.loading_items = []
        self.footer = Text(
            parent=self.root,
            text='Find the way out. Do not stay too long.',
            origin=(0, 0),
            position=(0, -0.39, -1.1),
            scale=0.75,
            color=rgba(210, 205, 170, 180),
        )
        self.footer.always_on_top = True
        self.loading_text = Text(
            parent=self.root,
            text='Loading...',
            origin=(0, 0),
            position=(0, 0.055, -1.3),
            scale=1.65,
            color=rgba(235, 231, 205, 255),
            enabled=False,
        )
        self.loading_text.always_on_top = True
        self.loading_hint = Text(
            parent=self.root,
            text=random.choice(LOADING_HINTS),
            origin=(0, 0),
            position=(0, -0.060, -1.3),
            scale=0.72,
            color=rgba(210, 205, 176, 210),
            enabled=False,
        )
        self.loading_hint.always_on_top = True
        self.loading_items.extend((
            self.loading_text,
            self.loading_hint,
        ))

        self.add_menu_button('Start', 0.09, self.start_callback)
        self.add_menu_button('Help', -0.005, lambda: self.set_mode('help'))
        self.add_menu_button('Credit', -0.10, lambda: self.set_mode('credit'))
        self.add_menu_button('Quit', -0.195, application.quit)
        self.build_help()
        self.build_credit()
        self.set_mode('main')

    def update(self):
        self.anim_time += time.dt
        drift_x = math.sin(self.anim_time * 0.24) * 0.075 + math.sin(self.anim_time * 0.09 + 2.1) * 0.030
        drift_y = math.sin(self.anim_time * 0.18 + 1.7) * 0.050 + math.sin(self.anim_time * 0.07) * 0.020
        self.background_root.position = (drift_x, drift_y, 0.8)

        pulse = 1.0 + math.sin(self.anim_time * 0.13) * 0.030
        for layer, offset in self.background_layers:
            layer.position = (offset[0], offset[1], 0)
            layer.scale = (2.45 * pulse, 1.38 * pulse)

        for button, label in self._all_buttons():
            if not button.enabled:
                continue
            label.color = rgba(246, 214, 122, 255) if button.hovered else rgba(235, 231, 205, 255)

    def add_menu_button(self, text, y, callback):
        button, label = TextMenuButton(self.root, text, y, callback).as_pair()
        self.buttons.append((button, label))
        return button, label

    def add_panel_text(self, store, text, y, scale=0.62):
        item = Text(
            parent=self.root,
            text=text,
            origin=(0, 0),
            position=(0, y, -1.1),
            scale=scale,
            color=rgba(235, 231, 205, 235),
        )
        item.always_on_top = True
        store.append(item)
        return item

    def add_left_text(self, store, text, x, y, scale, text_color):
        item = Text(
            parent=self.root,
            text=text,
            origin=(-1, 0),
            position=(x, y, -1.1),
            scale=scale,
            color=text_color,
        )
        item.always_on_top = True
        store.append(item)
        return item

    def add_right_text(self, store, text, x, y, scale, text_color):
        item = Text(
            parent=self.root,
            text=text,
            origin=(1, 0),
            position=(x, y, -1.1),
            scale=scale,
            color=text_color,
        )
        item.always_on_top = True
        store.append(item)
        return item

    def add_help_row(self, y, key_text, action_text):
        key_color = rgba(248, 221, 138, 250)
        action_color = rgba(232, 228, 203, 235)
        key = self.add_right_text(self.help_items, key_text, -0.060, y, 0.94, key_color)
        action = self.add_left_text(self.help_items, action_text, 0.065, y, 0.82, action_color)
        return key, action

    def build_help(self):
        self.add_panel_text(self.help_items, 'HELP', 0.270, 1.38).color = rgba(248, 221, 138, 250)
        self.add_panel_text(self.help_items, 'Controls', 0.188, 0.66).color = rgba(210, 205, 176, 190)

        y = 0.110
        for key_text, action_text in HELP_ROWS:
            self.add_help_row(y, key_text, action_text)
            y -= 0.058

        self.help_back = self.add_menu_button('Back', -0.390, lambda: self.set_mode('main'))
        self.buttons.remove(self.help_back)
        self.help_items.extend(self.help_back)

    def build_credit(self):
        self.add_panel_text(self.credit_items, 'CREDIT', 0.300, 1.12).color = rgba(248, 221, 138, 250)
        self.add_panel_text(self.credit_items, 'A GAME BY', 0.222, 0.55).color = rgba(210, 205, 176, 185)
        self.add_panel_text(self.credit_items, 'Choi Yeonwoo / Seoyoon Son', 0.176, 0.76).color = rgba(235, 231, 205, 240)
        self.add_panel_text(self.credit_items, 'Made with Python, Ursina, Panda3D', 0.115, 0.50).color = rgba(226, 222, 196, 205)

        self.add_panel_text(self.credit_items, '3D MODEL ASSETS', 0.040, 0.52).color = rgba(248, 221, 138, 230)
        assets = (
            ('door_ white_ wooden _Old - 4MB', 'Mehdi Shahsavan'),
            ('Lowpoly Bed', 'Mohamed199'),
            ('Vintage Wooden Drawer 01 4k', 'mohamedhussien'),
            ('Simple metal key', 'Herrah'),
            ('Low poly emergency exit sign', 'Mckai'),
            ('Keypad', 'Spellkaze'),
        )
        y = -0.025
        for name, author in assets:
            self.add_right_text(self.credit_items, name, -0.045, y, 0.345, rgba(235, 231, 205, 230))
            self.add_left_text(self.credit_items, f'by {author}', 0.050, y, 0.345, rgba(210, 205, 176, 190))
            y -= 0.046

        self.add_panel_text(self.credit_items, 'Source: Sketchfab  |  License: CC BY', -0.318, 0.43).color = rgba(210, 205, 176, 185)

        self.credit_back = self.add_menu_button('Back', -0.385, lambda: self.set_mode('main'))
        self.buttons.remove(self.credit_back)
        self.credit_items.extend(self.credit_back)

    def set_mode(self, mode):
        showing_main = mode == 'main'
        showing_help = mode == 'help'
        showing_credit = mode == 'credit'
        showing_loading = mode == 'loading'
        if showing_loading:
            self.loading_hint.text = random.choice(LOADING_HINTS)
        self.title.enabled = showing_main
        self.footer.enabled = showing_main

        for button, label in self.buttons:
            button.enabled = showing_main
            label.enabled = showing_main
        for item in self.help_items:
            item.enabled = showing_help
        for item in self.credit_items:
            item.enabled = showing_credit
        for item in self.loading_items:
            item.enabled = showing_loading

    def handle_key(self, key):
        if key == 'escape':
            self.set_mode('main')
            return True
        return False

    def _all_buttons(self):
        result = list(self.buttons)
        result.append(self.help_back)
        result.append(self.credit_back)
        return result

    def set_visible(self, visible):
        self.root.enabled = visible
        if visible:
            self.set_mode('main')
        else:
            for btn, _lbl in self._all_buttons():
                btn.enabled = False


class PauseMenu:
    def __init__(self, resume_callback, quit_callback):
        self.resume_callback = resume_callback
        self.root = Entity(parent=camera.ui, enabled=False)
        self.mode = 'main'
        self.dim = Entity(
            parent=self.root,
            model='quad',
            color=rgba(0, 0, 0, 135),
            position=(0, 0, 0.4),
            scale=(2.1, 2.1),
        )
        self.dim.always_on_top = True
        self.dim.setBin('fixed', 120)
        self.dim.setDepthWrite(False)
        self.dim.setDepthTest(False)
        self.title = Text(
            parent=self.root,
            text='PAUSED',
            origin=(0, 0),
            position=(0, 0.12, -1.3),
            scale=1.25,
            color=rgba(235, 231, 205, 230),
        )
        self.title.always_on_top = True
        self.title.setBin('fixed', 130)
        self.title.setDepthWrite(False)
        self.title.setDepthTest(False)
        self.buttons = [
            TextMenuButton(self.root, 'Resume', 0.00, resume_callback).as_pair(),
            TextMenuButton(self.root, 'Help', -0.105, lambda: self.set_mode('help')).as_pair(),
            TextMenuButton(self.root, 'Quit Game', -0.210, quit_callback).as_pair(),
        ]
        self.help_items = []
        for button, label in self.buttons:
            button.setBin('fixed', 130)
            button.setDepthWrite(False)
            button.setDepthTest(False)
            label.setBin('fixed', 130)
            label.setDepthWrite(False)
            label.setDepthTest(False)
        self.build_help()
        self.set_visible(False)

    def update(self):
        for button, label in self._all_buttons():
            if not button.enabled:
                continue
            label.color = rgba(246, 214, 122, 255) if button.hovered else rgba(235, 231, 205, 255)

    def handle_key(self, key):
        if key == 'escape':
            if self.mode == 'help':
                self.set_mode('main')
            else:
                self.resume_callback()
            return True
        return False

    def add_panel_text(self, store, text, y, scale=0.62):
        item = Text(
            parent=self.root,
            text=text,
            origin=(0, 0),
            position=(0, y, -1.3),
            scale=scale,
            color=rgba(235, 231, 205, 235),
        )
        item.always_on_top = True
        item.setBin('fixed', 130)
        item.setDepthWrite(False)
        item.setDepthTest(False)
        store.append(item)
        return item

    def add_left_text(self, store, text, x, y, scale, text_color):
        item = Text(
            parent=self.root,
            text=text,
            origin=(-1, 0),
            position=(x, y, -1.3),
            scale=scale,
            color=text_color,
        )
        item.always_on_top = True
        item.setBin('fixed', 130)
        item.setDepthWrite(False)
        item.setDepthTest(False)
        store.append(item)
        return item

    def add_right_text(self, store, text, x, y, scale, text_color):
        item = Text(
            parent=self.root,
            text=text,
            origin=(1, 0),
            position=(x, y, -1.3),
            scale=scale,
            color=text_color,
        )
        item.always_on_top = True
        item.setBin('fixed', 130)
        item.setDepthWrite(False)
        item.setDepthTest(False)
        store.append(item)
        return item

    def add_help_row(self, y, key_text, action_text):
        key_color = rgba(248, 221, 138, 250)
        action_color = rgba(232, 228, 203, 235)
        self.add_right_text(self.help_items, key_text, -0.060, y, 0.94, key_color)
        self.add_left_text(self.help_items, action_text, 0.065, y, 0.82, action_color)

    def build_help(self):
        self.add_panel_text(self.help_items, 'HELP', 0.270, 1.38).color = rgba(248, 221, 138, 250)
        self.add_panel_text(self.help_items, 'Controls', 0.188, 0.66).color = rgba(210, 205, 176, 190)

        y = 0.110
        for key_text, action_text in HELP_ROWS:
            self.add_help_row(y, key_text, action_text)
            y -= 0.058

        self.help_back = TextMenuButton(self.root, 'Back', -0.390, lambda: self.set_mode('main')).as_pair()
        for button, label in (self.help_back,):
            button.setBin('fixed', 130)
            button.setDepthWrite(False)
            button.setDepthTest(False)
            label.setBin('fixed', 130)
            label.setDepthWrite(False)
            label.setDepthTest(False)
        self.help_items.extend(self.help_back)

    def set_mode(self, mode):
        self.mode = mode
        showing_main = mode == 'main'
        showing_help = mode == 'help'
        self.title.enabled = showing_main
        for button, label in self.buttons:
            button.enabled = showing_main and self.root.enabled
            label.enabled = showing_main and self.root.enabled
        for item in self.help_items:
            item.enabled = showing_help and self.root.enabled

    def _all_buttons(self):
        result = list(self.buttons)
        result.append(self.help_back)
        return result

    def set_visible(self, visible):
        self.root.enabled = visible
        if visible:
            self.set_mode('main')
        else:
            for button, label in self._all_buttons():
                button.enabled = False
                label.enabled = False
