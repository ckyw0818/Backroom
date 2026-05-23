import math
import random

from ursina import BoxCollider, Vec2, Vec3, camera, held_keys, time
from ursina.prefabs.first_person_controller import FirstPersonController

PLAYER_H = 1.15
PLAYER_COLLIDER_W = 0.42
CAMERA_FOV = 80
WALK_SPEED = 3.0
RUN_SPEED = 5.2
MOVE_ACCEL = 5.5
MOVE_DECEL = 8.0


def create_player(cell_size, spawn_r=1, spawn_c=1):
    player = FirstPersonController(
        position=(spawn_c * cell_size, 0, spawn_r * cell_size),
        speed=0,
        mouse_sensitivity=Vec2(35, 35),
    )
    player.jump_height = 0
    player.jump_duration = 0
    player.gravity = 0
    player.height = PLAYER_H
    player.camera_pivot.y = PLAYER_H
    player.collider = BoxCollider(
        player,
        center=Vec3(0, PLAYER_H / 2, 0),
        size=Vec3(PLAYER_COLLIDER_W, PLAYER_H, PLAYER_COLLIDER_W),
    )
    player.cursor.visible = False
    return player


def player_cell(player, cell_size):
    return (
        int((player.z + cell_size / 2) // cell_size),
        int((player.x + cell_size / 2) // cell_size),
    )


class HeadBob:
    def __init__(self, player, footstep_sounds=None):
        self.player = player
        self.footstep_sounds = footstep_sounds or []
        self.base_pivot_y = player.camera_pivot.y
        self.t = random.uniform(0, 10)
        self.last_step_index = self.step_index(self.t)
        self.jitter_x = 0.0
        self.jitter_y = 0.0
        self.roll = 0.0
        self.pitch = 0.0
        self.yaw = 0.0
        self.run_blend = 0.0
        self.current_speed = 0.0

    def step_index(self, t):
        phase = t * 1.75
        return math.floor((phase - math.pi * 1.5) / (math.pi * 2.0))

    def play_footstep(self):
        if not self.footstep_sounds:
            return

        sound = random.choice(self.footstep_sounds)
        sound.volume = 0.60 + self.run_blend * 0.20
        sound.play()

    def update(self):
        moving = held_keys['w'] or held_keys['a'] or held_keys['s'] or held_keys['d']
        running = moving and held_keys['shift']
        dt = time.dt
        target_speed = RUN_SPEED if running else WALK_SPEED if moving else 0.0
        accel = MOVE_ACCEL if target_speed > self.current_speed else MOVE_DECEL
        self.current_speed += (target_speed - self.current_speed) * min(1.0, dt * accel)
        self.player.speed = self.current_speed

        self.run_blend += ((1.0 if running else 0.0) - self.run_blend) * min(1.0, dt * 7)
        move_blend = min(1.0, self.current_speed / WALK_SPEED)
        intensity = move_blend * (1.0 + self.run_blend * 0.85)

        self.t += dt * (1.4 + move_blend * (3.5 + self.run_blend * 2.8))
        current_step_index = self.step_index(self.t)

        if self.current_speed > 0.35 and current_step_index > self.last_step_index:
            self.play_footstep()

        self.last_step_index = current_step_index

        bob_y = math.sin(self.t * 1.75) * 0.026 * intensity
        bob_x = math.sin(self.t * 0.82 + 0.8) * 0.010 * intensity
        dirty_step = math.sin(self.t * 2.4 + math.sin(self.t * 0.55)) * 0.005 * intensity

        self.jitter_x += (random.uniform(-0.004, 0.004) * intensity - self.jitter_x) * min(1.0, dt * 14)
        self.jitter_y += (random.uniform(-0.007, 0.007) * intensity - self.jitter_y) * min(1.0, dt * 12)
        self.roll += (random.uniform(-0.32, 0.32) * intensity - self.roll) * min(1.0, dt * 4.5)
        self.pitch += (random.uniform(-0.18, 0.18) * intensity - self.pitch) * min(1.0, dt * 5.0)
        self.yaw += (random.uniform(-0.14, 0.14) * intensity - self.yaw) * min(1.0, dt * 5.0)

        self.player.camera_pivot.y = self.base_pivot_y + bob_y + dirty_step + self.jitter_y
        self.player.camera_pivot.x = bob_x + self.jitter_x
        camera.rotation_x = self.pitch + math.sin(self.t * 1.20) * 0.18 * intensity
        camera.rotation_y = self.yaw + math.sin(self.t * 0.95 + 1.4) * 0.14 * intensity
        camera.rotation_z = self.roll + math.sin(self.t * 0.72) * 0.28 * intensity
