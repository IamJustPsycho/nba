#!/usr/bin/env python

# Copyright (c) 2019 Computer Vision Center (CVC) at the Universitat Autonoma de
# Barcelona (UAB).
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.

# Allows controlling a vehicle with a keyboard. For a simpler and more
# documented example, please take a look at tutorial.py.

"""
Welcome to CARLA manual control.

Use ARROWS or WASD keys for control.
    u            : Toggle AEBS
    W            : throttle
    S            : brake
    A/D          : steer left/right
    Q            : toggle reverse
    Space        : hand-brake
    P            : toggle autopilot
    M            : toggle manual transmission
    ,/.          : gear up/down
    CTRL + W     : toggle constant velocity mode at 60 km/h

    L            : toggle next light type
    SHIFT + L    : toggle high beam
    Z/X          : toggle right/left blinker
    I            : toggle interior light

    TAB          : change sensor position
    ` or N       : next sensor
    [1-9]        : change to sensor [1-9]
    G            : toggle radar visualization
    C            : change weather (Shift+C reverse)
    Backspace    : change vehicle

    O            : open/close all doors of vehicle
    T            : toggle vehicle's telemetry

    V            : Select next map layer (Shift+V reverse)
    B            : Load current selected map layer (Shift+B to unload)

    R            : toggle recording images to disk

    CTRL + R     : toggle recording of simulation (replacing any previous)
    CTRL + P     : start replaying last recorded simulation
    CTRL + +     : increments the start time of the replay by 1 second (+SHIFT = 10 seconds)
    CTRL + -     : decrements the start time of the replay by 1 second (+SHIFT = 10 seconds)

    F1           : toggle HUD
    H/?          : toggle help
    ESC          : quit
"""

from __future__ import print_function

# ==============================================================================
# -- find carla module ---------------------------------------------------------
# ==============================================================================

import time
import glob
import os
import sys
import threading

try:
    sys.path.append(glob.glob('../carla/dist/carla-*%d.%d-%s.egg' % (
        sys.version_info.major,
        sys.version_info.minor,
        'win-amd64' if os.name == 'nt' else 'linux-x86_64'))[0])
except IndexError:
    pass

# ==============================================================================
# -- imports -------------------------------------------------------------------
# ==============================================================================


import carla
from carla import ColorConverter as cc

import argparse
import collections
import datetime
import logging
import math
import random
import re
import weakref
import cv2

try:
    import pygame
    from pygame.locals import KMOD_CTRL
    from pygame.locals import KMOD_SHIFT
    from pygame.locals import K_0
    from pygame.locals import K_9
    from pygame.locals import K_BACKQUOTE
    from pygame.locals import K_BACKSPACE
    from pygame.locals import K_COMMA
    from pygame.locals import K_DOWN
    from pygame.locals import K_ESCAPE
    from pygame.locals import K_F1
    from pygame.locals import K_LEFT
    from pygame.locals import K_PERIOD
    from pygame.locals import K_RIGHT
    from pygame.locals import K_SLASH
    from pygame.locals import K_SPACE
    from pygame.locals import K_TAB
    from pygame.locals import K_UP
    from pygame.locals import K_a
    from pygame.locals import K_b
    from pygame.locals import K_c
    from pygame.locals import K_d
    from pygame.locals import K_g
    from pygame.locals import K_h
    from pygame.locals import K_i
    from pygame.locals import K_l
    from pygame.locals import K_m
    from pygame.locals import K_n
    from pygame.locals import K_o
    from pygame.locals import K_p
    from pygame.locals import K_q
    from pygame.locals import K_r
    from pygame.locals import K_s
    from pygame.locals import K_t
    from pygame.locals import K_v
    from pygame.locals import K_w
    from pygame.locals import K_x
    from pygame.locals import K_z
    from pygame.locals import K_u
    from pygame.locals import K_MINUS
    from pygame.locals import K_EQUALS
except ImportError:
    raise RuntimeError('cannot import pygame, make sure pygame package is installed')

try:
    import numpy as np
except ImportError:
    raise RuntimeError('cannot import numpy, make sure numpy package is installed')

ACTION_THRESHOLD = 3.15
CRASH_DISTANCE = 1.35
FOCAL_LENGTH = 36.66184120297396
MAX_SECONDS_PER_EPISODE = 240
MAX_DISTANCE = 30
RGB_IMG_HEIGHT = 600
RGB_IMG_WIDTH = 800
SEMANTIC_IMG_HEIGHT = 75
SEMANTIC_IMG_WIDTH = 200

g_distance = 0
g_least_distance = 0
g_interrupt = False
g_player_action = False

pygame.init()


# ==============================================================================
# -- Global functions ----------------------------------------------------------
# ==============================================================================


def find_weather_presets():
    rgx = re.compile('.+?(?:(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|$)')
    name = lambda x: ' '.join(m.group(0) for m in rgx.finditer(x))
    presets = [x for x in dir(carla.WeatherParameters) if re.match('[A-Z].+', x)]
    return [(getattr(carla.WeatherParameters, x), name(x)) for x in presets]


def get_actor_display_name(actor, truncate=250):
    name = ' '.join(actor.type_id.replace('_', '.').title().split('.')[1:])
    return (name[:truncate - 1] + u'\u2026') if len(name) > truncate else name


def get_actor_blueprints(world, filter, generation):
    bps = world.get_blueprint_library().filter(filter)

    if generation.lower() == "all":
        return bps

    # If the filter returns only one bp, we assume that this one needed
    # and therefore, we ignore the generation
    if len(bps) == 1:
        return bps

    try:
        int_generation = int(generation)
        # Check if generation is in available generations
        if int_generation in [1, 2]:
            bps = [x for x in bps if int(x.get_attribute('generation')) == int_generation]
            return bps
        else:
            print("   Warning! Actor Generation is not valid. No actor will be spawned.")
            return []
    except:
        print("   Warning! Actor Generation is not valid. No actor will be spawned.")
        return []


# ==============================================================================
# -- World ---------------------------------------------------------------------
# ==============================================================================


class World(object):
    def __init__(self, carla_world, hud, args, client):
        self.world = carla_world
        self.sync = args.sync
        self.actor_role_name = args.rolename
        try:
            self.map = self.world.get_map()
        except RuntimeError as error:
            print('RuntimeError: {}'.format(error))
            print('  The server could not send the OpenDRIVE (.xodr) file:')
            print('  Make sure it exists, has the same name of your town, and is correct.')
            sys.exit(1)
        self.hud = hud
        self.client = client
        self.player = None
        self.player_2 = None
        self.thread_2 = None
        # self.collision_sensor = None
        # self.lane_invasion_sensor = None
        # self.gnss_sensor = None
        # self.imu_sensor = None
        # self.radar_sensor = None
        self.distance_sensor = None
        self.aebs = None
        self.camera_manager = None
        self._weather_presets = find_weather_presets()
        self._weather_index = 0
        self._actor_filter = args.filter
        self._actor_generation = args.generation
        self._gamma = args.gamma
        self.constant_velocity_enabled = False
        self.restart()
        self.world.on_tick(hud.on_world_tick)
        self.recording_enabled = False
        self.recording_start = 0
        self.constant_velocity_enabled = False
        self.show_vehicle_telemetry = False
        self.doors_are_open = False
        self.current_map_layer = 0
        self.map_layer_names = [
            carla.MapLayer.NONE,
            carla.MapLayer.Buildings,
            carla.MapLayer.Decals,
            carla.MapLayer.Foliage,
            carla.MapLayer.Ground,
            carla.MapLayer.ParkedVehicles,
            carla.MapLayer.Particles,
            carla.MapLayer.Props,
            carla.MapLayer.StreetLights,
            carla.MapLayer.Walls,
            carla.MapLayer.All
        ]

    def restart(self):
        self.player_max_speed = 1.589
        self.player_max_speed_fast = 3.713
        # Keep same camera config if the camera manager exists.
        cam_index = self.camera_manager.index if self.camera_manager is not None else 0
        cam_pos_index = self.camera_manager.transform_index if self.camera_manager is not None else 0
        # Get a random blueprint.
        blueprint = self.client.get_world().get_blueprint_library().filter('vehicle.mercedes.coupe_2020')[0]
        blueprint.set_attribute('role_name', self.actor_role_name)
        if blueprint.has_attribute('color'):
            color = random.choice(blueprint.get_attribute('color').recommended_values)
            blueprint.set_attribute('color', color)
        if blueprint.has_attribute('driver_id'):
            driver_id = random.choice(blueprint.get_attribute('driver_id').recommended_values)
            blueprint.set_attribute('driver_id', driver_id)
        if blueprint.has_attribute('is_invincible'):
            blueprint.set_attribute('is_invincible', 'true')
        # set the max speed
        if blueprint.has_attribute('speed'):
            self.player_max_speed = float(blueprint.get_attribute('speed').recommended_values[1])
            self.player_max_speed_fast = float(blueprint.get_attribute('speed').recommended_values[2])

        # Spawn the player.
        if self.player is not None:
            spawn_point = self.player.get_transform()
            spawn_point.location.z += 2.0
            spawn_point.rotation.roll = 0.0
            spawn_point.rotation.pitch = 0.0
            self.destroy()
            transform = carla.Transform(carla.Location(x=-105.881844, y=-186.788177, z=10.020110),
                                        carla.Rotation(yaw=0))
            self.player = self.world.try_spawn_actor(blueprint, transform)
            time.sleep(5)
            transform_2 = carla.Transform(carla.Location(x=0.018200, y=133.947205, z=0.019969), carla.Rotation(yaw=0))
            self.player_2 = self.world.try_spawn_actor(blueprint, transform_2)
            self.show_vehicle_telemetry = False
            self.modify_vehicle_physics(self.player)
            self.modify_vehicle_physics(self.player_2)

        while self.player is None:
            if not self.map.get_spawn_points():
                print('There are no spawn points available in your map/town.')
                print('Please add some Vehicle Spawn Point to your UE4 scene.')
                sys.exit(1)
            print("hi")
            spawn_points = self.map.get_spawn_points()
            spawn_point = random.choice(spawn_points) if spawn_points else carla.Transform()
            transform = carla.Transform(carla.Location(x=65.018200, y=133.947205, z=0.019969), carla.Rotation(yaw=180))
            self.player = self.world.try_spawn_actor(blueprint, transform)
            spawn_point_2 = random.choice(spawn_points) if spawn_points else carla.Transform()
            transform_2 = carla.Transform(carla.Location(x=45.018200, y=133.947205, z=0.019969),
                                          carla.Rotation(yaw=180))
            self.player_2 = self.world.try_spawn_actor(blueprint, transform_2)
            self.show_vehicle_telemetry = False
            self.modify_vehicle_physics(self.player)
            self.modify_vehicle_physics(self.player_2)
        # Set up the sensors.
        # self.collision_sensor = CollisionSensor(self.player, self.hud)
        # self.lane_invasion_sensor = LaneInvasionSensor(self.player, self.hud)
        # self.gnss_sensor = GnssSensor(self.player)
        # self.imu_sensor = IMUSensor(self.player)
        # self.distance_sensor = VehicleRadarSensor(self.player)
        self.obstacle_sensor = ObstacleSensor(self.player, self)
        time.sleep(.5)
        self.aebs = AEBS(self.player, self.hud, self)
        time.sleep(.2)
        self.distance_sensor = DistanceSensor(self.player, self.player_2, self.aebs)
        time.sleep(.5)
        self.camera_manager = CameraManager(self.player, self.hud, self._gamma)
        self.camera_manager.transform_index = cam_pos_index
        self.camera_manager.set_sensor(cam_index, notify=False)
        actor_type = get_actor_display_name(self.player)
        self.hud.notification(actor_type)

        # self.thread_1 = threading.Thread(target=self.create_sensor)
        # self.thread_1.start()
        self.thread_2 = threading.Thread(target=self.aebs.test)
        self.thread_2.start()

        if self.sync:
            self.world.tick()
        else:
            self.world.wait_for_tick()

    def next_weather(self, reverse=False):
        self._weather_index += -1 if reverse else 1
        self._weather_index %= len(self._weather_presets)
        preset = self._weather_presets[self._weather_index]
        self.hud.notification('Weather: %s' % preset[1])
        self.player.get_world().set_weather(preset[0])

    def next_map_layer(self, reverse=False):
        self.current_map_layer += -1 if reverse else 1
        self.current_map_layer %= len(self.map_layer_names)
        selected = self.map_layer_names[self.current_map_layer]
        self.hud.notification('LayerMap selected: %s' % selected)

    def load_map_layer(self, unload=False):
        selected = self.map_layer_names[self.current_map_layer]
        if unload:
            self.hud.notification('Unloading map layer: %s' % selected)
            self.world.unload_map_layer(selected)
        else:
            self.hud.notification('Loading map layer: %s' % selected)
            self.world.load_map_layer(selected)

    def modify_vehicle_physics(self, actor):
        try:
            physics_control = actor.get_physics_control()
            physics_control.use_sweep_wheel_collision = True
            actor.apply_physics_control(physics_control)
        except Exception:
            pass

    def tick(self, clock):
        self.hud.tick(self, clock)

    def render(self, display):
        self.camera_manager.render(display)
        self.hud.render(display)

    def destroy_sensors(self):
        self.camera_manager.sensor.destroy()
        self.camera_manager.sensor = None
        self.camera_manager.index = None

    def destroy(self):
        # self.thread_1.join()
        # self.thread_2.join()
        if self.player is not None:
            self.player.destroy()
        if self.player_2 is not None:
            self.player_2.destroy()

    def __del__(self):
        global g_interrupt
        g_interrupt = True
        if self.thread_2:
            self.thread_2.join()


# ==============================================================================
# -- KeyboardControl -----------------------------------------------------------
# ==============================================================================


class KeyboardControl(object):
    """Class that handles keyboard input."""

    def __init__(self, world, start_in_autopilot):
        self._autopilot_enabled = start_in_autopilot
        if isinstance(world.player, carla.Vehicle):
            self._control = carla.VehicleControl()
            self._lights = carla.VehicleLightState.NONE
            world.player.set_autopilot(self._autopilot_enabled)
            world.player.set_light_state(self._lights)
        elif isinstance(world.player, carla.Walker):
            self._control = carla.WalkerControl()
            self._autopilot_enabled = False
            self._rotation = world.player.get_transform().rotation
        else:
            raise NotImplementedError("Actor type not supported")
        self._steer_cache = 0.0
        world.hud.notification("Press 'H' or '?' for help.", seconds=4.0)
        self.world = world

    def parse_events(self, client, world, clock, sync_mode):
        if isinstance(self._control, carla.VehicleControl):
            current_lights = self._lights
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return True
            elif event.type == pygame.KEYUP:
                if self._is_quit_shortcut(event.key):
                    return True
                elif event.key == K_u:
                    world.aebs.toggle_aebs()
                    if world.hud.warnleuchte is not None:
                        world.hud.warnleuchte.reset(world.hud.warnleuchte)
                elif event.key == K_BACKSPACE:
                    if self._autopilot_enabled:
                        world.player.set_autopilot(False)
                        world.restart()
                        world.player.set_autopilot(True)
                    else:
                        world.restart()
                elif event.key == K_F1:
                    world.hud.toggle_info()
                elif event.key == K_v and pygame.key.get_mods() & KMOD_SHIFT:
                    world.next_map_layer(reverse=True)
                elif event.key == K_v:
                    world.next_map_layer()
                elif event.key == K_b and pygame.key.get_mods() & KMOD_SHIFT:
                    world.load_map_layer(unload=True)
                elif event.key == K_b:
                    world.load_map_layer()
                elif event.key == K_h or (event.key == K_SLASH and pygame.key.get_mods() & KMOD_SHIFT):
                    world.hud.help.toggle()
                elif event.key == K_TAB:
                    world.camera_manager.toggle_camera()
                elif event.key == K_c and pygame.key.get_mods() & KMOD_SHIFT:
                    world.next_weather(reverse=True)
                elif event.key == K_c:
                    world.next_weather()
                elif event.key == K_g:
                    # world.toggle_radar()
                    world.restart()
                elif event.key == K_BACKQUOTE:
                    world.camera_manager.next_sensor()
                elif event.key == K_n:
                    world.camera_manager.next_sensor()
                elif event.key == K_w and (pygame.key.get_mods() & KMOD_CTRL):
                    if world.constant_velocity_enabled:
                        world.player.disable_constant_velocity()
                        world.player_2.disalbe_constant_velocity()
                        world.constant_velocity_enabled = False
                        # world.hud.notification("Disabled Constant Velocity Mode")
                    else:
                        world.player.enable_constant_velocity(carla.Vector3D(10, 0, 0))
                        world.player_2.enable_constant_velocity(carla.Vector3D(7.5, 0, 0))
                        world.constant_velocity_enabled = True
                        # world.hud.notification("Enabled Constant Velocity Mode at 60 km/h")
                elif event.key == K_o:
                    try:
                        if world.doors_are_open:
                            world.hud.notification("Closing Doors")
                            world.doors_are_open = False
                            world.player.close_door(carla.VehicleDoor.All)
                        else:
                            world.hud.notification("Opening doors")
                            world.doors_are_open = True
                            world.player.open_door(carla.VehicleDoor.All)
                    except Exception:
                        pass
                elif event.key == K_t:
                    if world.show_vehicle_telemetry:
                        world.player.show_debug_telemetry(False)
                        world.show_vehicle_telemetry = False
                        world.hud.notification("Disabled Vehicle Telemetry")
                    else:
                        try:
                            world.player.show_debug_telemetry(True)
                            world.show_vehicle_telemetry = True
                            world.hud.notification("Enabled Vehicle Telemetry")
                        except Exception:
                            pass
                elif event.key > K_0 and event.key <= K_9:
                    index_ctrl = 0
                    if pygame.key.get_mods() & KMOD_CTRL:
                        index_ctrl = 9
                    world.camera_manager.set_sensor(event.key - 1 - K_0 + index_ctrl)
                elif event.key == K_r and not (pygame.key.get_mods() & KMOD_CTRL):
                    world.camera_manager.toggle_recording()
                elif event.key == K_r and (pygame.key.get_mods() & KMOD_CTRL):
                    if (world.recording_enabled):
                        client.stop_recorder()
                        world.recording_enabled = False
                        world.hud.notification("Recorder is OFF")
                    else:
                        client.start_recorder("manual_recording.rec")
                        world.recording_enabled = True
                        world.hud.notification("Recorder is ON")
                elif event.key == K_p and (pygame.key.get_mods() & KMOD_CTRL):
                    # stop recorder
                    client.stop_recorder()
                    world.recording_enabled = False
                    # work around to fix camera at start of replaying
                    current_index = world.camera_manager.index
                    world.destroy_sensors()
                    # disable autopilot
                    self._autopilot_enabled = False
                    world.player.set_autopilot(self._autopilot_enabled)
                    world.hud.notification("Replaying file 'manual_recording.rec'")
                    # replayer
                    client.replay_file("manual_recording.rec", world.recording_start, 0, 0)
                    world.camera_manager.set_sensor(current_index)
                elif event.key == K_MINUS and (pygame.key.get_mods() & KMOD_CTRL):
                    if pygame.key.get_mods() & KMOD_SHIFT:
                        world.recording_start -= 10
                    else:
                        world.recording_start -= 1
                    world.hud.notification("Recording start time is %d" % (world.recording_start))
                elif event.key == K_EQUALS and (pygame.key.get_mods() & KMOD_CTRL):
                    if pygame.key.get_mods() & KMOD_SHIFT:
                        world.recording_start += 10
                    else:
                        world.recording_start += 1
                    world.hud.notification("Recording start time is %d" % (world.recording_start))
                if isinstance(self._control, carla.VehicleControl):
                    if event.key == K_q:
                        self._control.gear = 1 if self._control.reverse else -1
                    elif event.key == K_m:
                        self._control.manual_gear_shift = not self._control.manual_gear_shift
                        self._control.gear = world.player.get_control().gear
                        world.hud.notification('%s Transmission' %
                                               ('Manual' if self._control.manual_gear_shift else 'Automatic'))
                    elif self._control.manual_gear_shift and event.key == K_COMMA:
                        self._control.gear = max(-1, self._control.gear - 1)
                    elif self._control.manual_gear_shift and event.key == K_PERIOD:
                        self._control.gear = self._control.gear + 1
                    elif event.key == K_p and not pygame.key.get_mods() & KMOD_CTRL:
                        if not self._autopilot_enabled and not sync_mode:
                            print("WARNING: You are currently in asynchronous mode and could "
                                  "experience some issues with the traffic simulation")
                        self._autopilot_enabled = not self._autopilot_enabled
                        world.player.set_autopilot(self._autopilot_enabled)
                        world.hud.notification(
                            'Autopilot %s' % ('On' if self._autopilot_enabled else 'Off'))
                    elif event.key == K_l and pygame.key.get_mods() & KMOD_CTRL:
                        current_lights ^= carla.VehicleLightState.Special1
                    elif event.key == K_l and pygame.key.get_mods() & KMOD_SHIFT:
                        current_lights ^= carla.VehicleLightState.HighBeam
                    elif event.key == K_l:
                        # Use 'L' key to switch between lights:
                        # closed -> position -> low beam -> fog
                        if not self._lights & carla.VehicleLightState.Position:
                            world.hud.notification("Position lights")
                            current_lights |= carla.VehicleLightState.Position
                        else:
                            world.hud.notification("Low beam lights")
                            current_lights |= carla.VehicleLightState.LowBeam
                        if self._lights & carla.VehicleLightState.LowBeam:
                            world.hud.notification("Fog lights")
                            current_lights |= carla.VehicleLightState.Fog
                        if self._lights & carla.VehicleLightState.Fog:
                            world.hud.notification("Lights off")
                            current_lights ^= carla.VehicleLightState.Position
                            current_lights ^= carla.VehicleLightState.LowBeam
                            current_lights ^= carla.VehicleLightState.Fog
                    elif event.key == K_i:
                        current_lights ^= carla.VehicleLightState.Interior
                    elif event.key == K_z:
                        current_lights ^= carla.VehicleLightState.LeftBlinker
                    elif event.key == K_x:
                        current_lights ^= carla.VehicleLightState.RightBlinker

        if not self._autopilot_enabled:
            if isinstance(self._control, carla.VehicleControl):
                self._parse_vehicle_keys(pygame.key.get_pressed(), clock.get_time())
                self._control.reverse = self._control.gear < 0
                # Set automatic control-related vehicle lights
                if self._control.brake:
                    current_lights |= carla.VehicleLightState.Brake
                else:  # Remove the Brake flag
                    current_lights &= ~carla.VehicleLightState.Brake
                if self._control.reverse:
                    current_lights |= carla.VehicleLightState.Reverse
                else:  # Remove the Reverse flag
                    current_lights &= ~carla.VehicleLightState.Reverse
                if current_lights != self._lights:  # Change the light state only if necessary
                    self._lights = current_lights
                    world.player.set_light_state(carla.VehicleLightState(self._lights))
            elif isinstance(self._contrakerControl):
                self._parse_walker_keys(pygame.key.get_pressed(), clock.get_time(), world)
            world.player.apply_control(self._control)

    def _parse_vehicle_keys(self, keys, milliseconds):
        if keys[K_UP] or keys[K_w]:
            g_player_action = True
            self._control.throttle = min(self._control.throttle + 0.01, .6)
        else:
            self._control.throttle = 0.0

        if keys[K_DOWN] or keys[K_s]:
            g_player_action = True
            self._control.brake = min(self._control.brake + 0.2, 1)
        else:
            self._control.brake = 0

        steer_increment = 5e-4 * milliseconds
        if keys[K_LEFT] or keys[K_a]:
            g_player_action = True
            if self._steer_cache > 0:
                self._steer_cache = 0
            else:
                self._steer_cache -= steer_increment
        elif keys[K_RIGHT] or keys[K_d]:
            g_player_action = True
            if self._steer_cache < 0:
                self._steer_cache = 0
            else:
                self._steer_cache += steer_increment
        else:
            self._steer_cache = 0.0
        self._steer_cache = min(0.7, max(-0.7, self._steer_cache))
        self._control.steer = round(self._steer_cache, 1)
        self._control.hand_brake = keys[K_SPACE]

    def _parse_walker_keys(self, keys, milliseconds, world):
        self._control.speed = 0.0
        if keys[K_DOWN] or keys[K_s]:
            self._control.speed = 0.0
        if keys[K_LEFT] or keys[K_a]:
            self._control.speed = .01
            self._rotation.yaw -= 0.08 * milliseconds
        if keys[K_RIGHT] or keys[K_d]:
            self._control.speed = .01
            self._rotation.yaw += 0.08 * milliseconds
        if keys[K_UP] or keys[K_w]:
            self._control.speed = world.player_max_speed_fast if pygame.key.get_mods() & KMOD_SHIFT else world.player_max_speed
        self._control.jump = keys[K_SPACE]
        self._rotation.yaw = round(self._rotation.yaw, 1)
        self._control.direction = self._rotation.get_forward_vector()

    @staticmethod
    def _is_quit_shortcut(key):
        return (key == K_ESCAPE) or (key == K_q and pygame.key.get_mods() & KMOD_CTRL)


# ==============================================================================
# -- Warnleuchte ---------------------------------------------------------------
# Diese Klasse simuliert eine Warnleuchte auf der imaginären Instrumententafel
# Eine Warnleuchte hat folgende Haupt-Zustände:
#   initialisiert - entspricht einem gründen Punkt am Bildschirm (unten rechts)
#   warnung(niedrig/hoch) - entspricht einem oder zwei roten Punkten auf dem Bildschirm
#   ausgeschaltet - entspricht einem schwarzen Punkt (=Warnleuchte leuchtet nicht)
#   fehlerhaft - entspricht einem orangenden Punkt (=technischer Fehler)
#
# Wichtige Instanzvariablen sind Links auf __world und __world.aebs
# Ddie Klasse World(__world) ist damit bekannt, deren Source-Code sich im der gleichen Source-Code datei befindet.
#
# Öffentliche Methoden
# void render() zeichnet die Warnleuchte am Display(rechts, unten) und erwartet surface of pygame als Parameter
# void setWorld() muss unmittelbar nach dem Initialisieren der Klasse aufgerufen werden. (wäre z.B. auch in Konstuktor angebracht)
# void reset() wird immer dann aufgerufen, wenn AEBS ein/ausgeschaltet wird.
# https://www.pygame.org/docs/ref/draw.html
# ==============================================================================
class Warnleuchte:

    __world = None #Link zu der Welt
    #__display = None #Link auf Screen, wo die Leuchte angezeigt werden soll
    #__hud = None #Link auf Anzeige-Instrumente (falls überhaupt nötig)
    #__aebs = None #Link auf das NBA, um zustände abzufrage und um benachrichtigt zu werden, fall ein Zustand sich ändert.

    #Alle möglichen Zustände der Warnleute am InstrumentenBrett
    __ZUSTAND_NOT_INIT = "zustand_not_init"
    __ZUSTAND_ERROR = "zustand_error"
    __ZUSTAND_INIT = "zustand_init"
    __ZUSTAND_AUS = "zustand_aus"
    __ZUSTAND_WARNUNG_LOW = "zustand_warnung_low"
    __ZUSTAND_WARNUNG_HIGH = "zustand_warning_high"
    __ZUSTAND_UNFALL = "zustand_unfall"
    __ZUSTAENDE_LIST = (__ZUSTAND_NOT_INIT, __ZUSTAND_ERROR, __ZUSTAND_INIT, __ZUSTAND_AUS, __ZUSTAND_WARNUNG_LOW, __ZUSTAND_WARNUNG_HIGH, __ZUSTAND_UNFALL) #tuple, zur Laufzeit unveränderbare Liste
    __zustand = __ZUSTAND_NOT_INIT #Akueller Stand im Augenblick __zustaende[0]

    __displayChecked = False
    __displayCheckedStatus = __ZUSTAND_NOT_INIT
    __displayCheckedTicker = 1

    def setWorld(self, world):
        self.__world = world

    def __init__(self):
        self.reset(self)

    def __aktualisiereZustand(self): # no return, only check and setting of the actual status value
        if self.__world is None:
            self.__zustand = self.__ZUSTAND_ERROR
            print(f"Die Warnleuchte kenn die Welt nicht. Warnleuchte-Zustand={self.__zustand}")
        elif self.__world is not None:
            if self.__world.aebs is None:
                self.__zustand = self.__ZUSTAND_ERROR
                print(f"Die Warnleuchte kenn die Welt, aber das Objekt AEBS ist nicht initialisiert. Warnleuchte-Zustand={self.__zustand}")
            else: # Welt ist bekannt, AEBS ist bekannt
                #self.__world.aebs.get_current_speed(self.__world)
                if self.__world.aebs.active == True:
                    self.__zustand = self.__ZUSTAND_INIT # AEBS ist aktiv, also ist der mindestzustand = Initialisiert

                    # HIER MÜSSTEN DIE STATUS-Werte von AEBS kommen. Aber ich nehme zunächst was an

                    self.__world.aebs.get_current_distance(self.__world) # Distance im AEBS aktualisieren
                    self.__world.aebs.get_current_speed(self.__world)  # Speed im AEBS aktualisieren self.__world.aebs

                    currentAebsSpeed = self.__world.aebs.speed

                    currentAebsDistance = self.__world.aebs.distance # Distance aus dem AEBS auslesen.

                    currentObstacleDistance = self.__world.obstacle_sensor.getCurrentObstacleDictance(1000) #maximal eine Sekunde alt, sonst 0.
                    if currentObstacleDistance>0:
                        currentAebsDistance = currentObstacleDistance # Überschreiben, weil am 21.05.2023 POC-Obstacle gemacht wird. Es scheint besser zu funktionieren als im AEBS
                    else:
                        currentAebsDistance = g_least_distance  # Distanz-aus der Karte nehmen, weil der Abstand aus AEBS NOCH nicht funktioniert

                    activeSpeed = 15 #Ab dieser Geschwindigkeit reagiert AEBS überhaupt, diese Werte sind normalerweise im AEBS kodiert. Aber zunächst hier
                    rueckwaertsgang = self.__world.player.get_control().reverse

                    if rueckwaertsgang:
                        self.__zustand = self.__ZUSTAND_AUS
                    elif currentAebsSpeed <= 0: # Im Stehen ist AEBS nicht aktiv
                        self.__zustand = self.__ZUSTAND_INIT
                    elif currentAebsSpeed < activeSpeed: # Bis 15kmh ist AEBS nicht aktiv. Erst ab 15 kmh muss der AEBS überhaupt eingreifen (hardkodiert in AEBS zur Zeit, am 21.05.2023)
                        self.__zustand = self.__ZUSTAND_INIT
                    elif currentAebsSpeed >= activeSpeed: # HIER MÜSSTEN DIE STATUS-Werte von AEBS kommen. Aber ich nehme zunächst was an

                        #Faust-Formel aus der Fahrschule
                        bremsweg = (currentAebsSpeed / 10) * (currentAebsSpeed / 10) #Fahrschul-Formel
                        reaktionsweg = (currentAebsSpeed / 10) * 3 #Fahrschul-Formel

                        # Zu Testzwecken um 50% verringern. Denn so schnell kann man in der Simulation kaum fahren.
                        bremsweg = bremsweg / 2
                        reaktionsweg = reaktionsweg / 2

                        # Zu Testzwecken um 50% verringern. (!)
                        anhalteWeg = bremsweg + reaktionsweg
                        anhalteWegWarnungLow = anhalteWeg * 1.5 # 50% mehr so viel wie benötigt
                        anhalteWegWarnungHigh = anhalteWeg * 1.2 # 20% mehr als der Faher wirklich benötigt, bald wird as Auto eingreifen und selbstständig aggieren
                        if currentAebsDistance <= 0.0: #keine Distance konnte ermittelt werden. Kein Hindernis in Sicht.
                                self.__zustand = self.__ZUSTAND_INIT
                        elif currentAebsDistance <= anhalteWegWarnungHigh:
                                self.__zustand = self.__ZUSTAND_WARNUNG_HIGH
                        elif currentAebsDistance <= anhalteWegWarnungLow:
                                self.__zustand = self.__ZUSTAND_WARNUNG_LOW
                        elif currentAebsDistance >= anhalteWegWarnungLow:
                                self.__zustand = self.__ZUSTAND_INIT
                        else:
                                self.__zustand = self.__ZUSTAND_ERROR
                                print(f"Fehler: AEBS ein, aber Abstand ist unbekannt. Status={self.__zustand}, Geschwindigkeit={currenAebsSpeed}, Abstand={currenAebsDistance}")
                        print(f"Abstand={currentAebsDistance:.2f}, Warnleuchte={self.__zustand}, Bremsweg={bremsweg:.2f}, Reaktionsweg={reaktionsweg:.2f} Anhaltweg={anhalteWeg:.2f}, AnhalteWegWarnungLow={anhalteWegWarnungLow:.2f}, anhalteWegWarnungHigh={anhalteWegWarnungHigh:.2f}, Nearly vehicles distance={g_least_distance:.2f}")
                    else:
                        self.__zustand = self.__ZUSTAND_ERROR
                        print(f"Fehler: AEBS ein, aber Abstand ist unbekannt. Status={self.__zustand}, Geschwindigkeit={currenAebsSpeed}, Abstand={currenAebsDistance}")

                else: #AEBS ist nicht aktiv
                    self.__zustand = self.__ZUSTAND_AUS # weil z.B. zu das Fahrzeug langsam

        else:
            self.__zustand = self.__ZUSTAND_ERROR
            print(f"Die Warnleuchte kann den aktuellen eigen Zustand nicht ermitteln. Der Fehler is unbekannt. Zustand={self.__zustand}")

    def reset(self):
        self.__displayChecked = False
        self.__displayCheckedStatus = self.__ZUSTAND_NOT_INIT
        self.__displayCheckedTicker = 1

    def __displayCheck(self, display): #Methode zeigt initialisiert die Leuchte und zeigt alle möglichen Zustände, bevor sie AEBS-Zustand anzeigt
        if self.__displayChecked == False:
            self.__displayCheckedTicker = self.__displayCheckedTicker + 1
            #print(f"displayCheckedTicker={self.__displayCheckedTicker}")

            # alle Leuchten leuchten für einen Augenblick auf
            ticker = 10
            if self.__displayCheckedTicker >= 0 and self.__displayCheckedTicker<ticker*2:
                self.__zustand = self.__ZUSTAND_NOT_INIT
                self.__paint(self, display)
                return
            if self.__displayCheckedTicker>=ticker*2 and self.__displayCheckedTicker<ticker*3:
                self.__zustand = self.__ZUSTAND_ERROR
                self.__paint(self, display)
                return
            if self.__displayCheckedTicker>=ticker*3 and self.__displayCheckedTicker<ticker*4:
                self.__zustand = self.__ZUSTAND_INIT
                self.__paint(self, display)
                return
            if self.__displayCheckedTicker>=ticker*4 and self.__displayCheckedTicker<ticker*5:
                self.__zustand = self.__ZUSTAND_AUS
                self.__paint(self, display)
                return
            if self.__displayCheckedTicker>=ticker*5 and self.__displayCheckedTicker<ticker*6:
                self.__zustand = self.__ZUSTAND_WARNUNG_LOW
                self.__paint(self, display)
                return
            if self.__displayCheckedTicker>=ticker*6 and self.__displayCheckedTicker<ticker*7:
                self.__zustand = self.__ZUSTAND_WARNUNG_HIGH
                self.__paint(self, display)
                return
            #if self.__displayCheckedTicker>=ticker*7 and self.__displayCheckedTicker<ticker*8: #Unfall nicht anzeigen beim Check.
            #    self.__zustand = self.__ZUSTAND_UNFALL
            #    self.__paint(self, display)
            #    return
            if self.__displayCheckedTicker>=ticker*8 and self.__displayCheckedTicker<ticker*9:
                self.__zustand = self.__ZUSTAND_NOT_INIT
                self.__paint(self, display)
                return
            self.__displayChecked = True
            return

        else: return


#    def render2(self):
#        if self.__aebs != None and  self.__hud != None and self.__surface != None:
#           self.repaint(self, self.__aebs, self.__hud, self.__surface)
#        else: print("Warning: Warnleuchte.repaint() nicht möglich")

    def render(self, display):
        if display is not None:
            if self.__displayChecked == True:
                self.__aktualisiereZustand(self) # aktuellen Zusand von AEBS holen
                self.__paint(self, display)
            else: self.__displayCheck(self, display)  #pygame.draw.rect(display, "yellow", [450, 110, 70, 40], 3, border_radius=15)  # Alex, Test-Zeichnen im Feld
        else: print("no rendering, display is  None")


    def __findColorByZusand(self, zustand):
        WHITE = (255, 255, 255)
        BLUE = (0, 0, 255)
        GREEN = (31, 94, 10) #GREEN = (0, 255, 0)
        RED = (255, 0, 0)
        ORANGE = (255,165,0)
        BLACK = TEXTCOLOR = (0, 0, 0)
        if zustand == self.__ZUSTAND_NOT_INIT:
            return WHITE
        elif zustand == self.__ZUSTAND_ERROR:
            return ORANGE
        elif zustand == self.__ZUSTAND_INIT:
            return GREEN
        elif zustand == self.__ZUSTAND_AUS:
            return BLACK
        elif zustand == self.__ZUSTAND_WARNUNG_LOW:
            return RED
        elif zustand == self.__ZUSTAND_WARNUNG_HIGH:
            return RED
        elif zustand == self.__ZUSTAND_UNFALL:
            return RED
        else:
            return ORANGE # Im Zweifel Error

    def __paint(self, display):
        (display_width, display_height) = display.get_size()
        warnleuchte_radius = 20
        (offset_x, offset_y) = (display_width-20, display_height-20) #400, 100
        if self.__zustand == self.__ZUSTAND_NOT_INIT:
            pygame.draw.circle(display, self.__findColorByZusand(self, self.__zustand), (offset_x, offset_y), warnleuchte_radius)
            return
        if self.__zustand == self.__ZUSTAND_ERROR:
            pygame.draw.circle(display, self.__findColorByZusand(self, self.__zustand), (offset_x, offset_y), warnleuchte_radius)
            return
        if self.__zustand == self.__ZUSTAND_INIT:
            pygame.draw.circle(display, self.__findColorByZusand(self, self.__zustand), (offset_x, offset_y), warnleuchte_radius)
            return
        if self.__zustand == self.__ZUSTAND_AUS:
            pygame.draw.circle(display, self.__findColorByZusand(self, self.__zustand), (offset_x, offset_y), warnleuchte_radius)
            return
        if self.__zustand == self.__ZUSTAND_WARNUNG_LOW:
            pygame.draw.circle(display, self.__findColorByZusand(self, self.__zustand), (offset_x, offset_y), warnleuchte_radius)
            return
        if self.__zustand == self.__ZUSTAND_WARNUNG_HIGH:
            pygame.draw.circle(display, self.__findColorByZusand(self, self.__zustand), (offset_x, offset_y), warnleuchte_radius)
            pygame.draw.circle(display, self.__findColorByZusand(self, self.__zustand), (offset_x, offset_y - warnleuchte_radius * 2), warnleuchte_radius)
            return
        if self.__zustand == self.__ZUSTAND_UNFALL:
            pygame.draw.circle(display, self.__findColorByZusand(self, self.__zustand), (offset_x, offset_y), warnleuchte_radius)
            pygame.draw.circle(display, self.__findColorByZusand(self, self.__zustand), (offset_x, offset_y - warnleuchte_radius * 2), warnleuchte_radius)
            pygame.draw.circle(display, self.__findColorByZusand(self, self.__zustand), (offset_x, offset_y - warnleuchte_radius * 4), warnleuchte_radius)
            return


# ==============================================================================
# -- HUD -----------------------------------------------------------------------
# ==============================================================================


class HUD(object):
    warnleuchte = None  # Anzeige der AEBS-Warnleuchte im Display(unten rechts)

    def __init__(self, width, height):
        self.dim = (width, height)
        font = pygame.font.Font(pygame.font.get_default_font(), 20)
        font_name = 'courier' if os.name == 'nt' else 'mono'
        fonts = [x for x in pygame.font.get_fonts() if font_name in x]
        default_font = 'ubuntumono'
        mono = default_font if default_font in fonts else fonts[0]
        mono = pygame.font.match_font(mono)
        self._font_mono = pygame.font.Font(mono, 12 if os.name == 'nt' else 14)
        self._notifications = FadingText(font, (width, 40), (0, height - 40))
        self.help = HelpText(pygame.font.Font(mono, 16), width, height)
        self.server_fps = 0
        self.frame = 0
        self.simulation_time = 0
        self._show_info = True
        self._info_text = []
        self._server_clock = pygame.time.Clock()

    def on_world_tick(self, timestamp):
        self._server_clock.tick()
        self.server_fps = self._server_clock.get_fps()
        self.frame = timestamp.frame
        self.simulation_time = timestamp.elapsed_seconds

    def tick(self, world, clock):

        if self.warnleuchte is None: # 1 zu 1 Relation (HUB <<<>>> Warnleuchte)
            self.warnleuchte = Warnleuchte #Erzeugen einer Instanz der Klasse für die Anzeige am Bildschirm
            self.warnleuchte.setWorld(self.warnleuchte, world) #self.warnleuchte.__world = world #Zugriff auf world ermöglichen

        self._notifications.tick(world, clock)
        if not self._show_info:
            return
        t = world.player.get_transform()
        v = world.player.get_velocity()
        c = world.player.get_control()
        # compass = world.imu_sensor.compass
        # heading = 'N' if compass > 270.5 or compass < 89.5 else ''
        # heading += 'S' if 90.5 < compass < 269.5 else ''
        # heading += 'E' if 0.5 < compass < 179.5 else ''
        # heading += 'W' if 180.5 < compass < 359.5 else ''
        # colhist = world.collision_sensor.get_collision_history()
        # collision = [colhist[x + self.frame - 200] for x in range(0, 200)]
        # max_col = max(1.0, max(collision))
        c  # ollision = [x / max_col for x in collision]
        vehicles = world.world.get_actors().filter('vehicle.*')
        world.aebs.get_current_speed(world)
        world.aebs.get_current_distance(world)
        # print(world.radar_sensor)
        self._info_text = [
            'Server:  % 16.0f FPS' % self.server_fps,
            'Client:  % 16.0f FPS' % clock.get_fps(),
            '',
            'Vehicle: % 20s' % get_actor_display_name(world.player, truncate=20),
            'Map:     % 20s' % world.map.name.split('/')[-1],
            'Simulation time: % 12s' % datetime.timedelta(seconds=int(self.simulation_time)),
            '',
            'Speed:   % 15.0f km/h' % (3.6 * math.sqrt(v.x ** 2 + v.y ** 2 + v.z ** 2)),
            # u'Compass:% 17.0f\N{DEGREE SIGN} % 2s' % (compass, heading),
            # 'Accelero: (%5.1f,%5.1f,%5.1f)' % (world.imu_sensor.accelerometer),
            # 'Gyroscop: (%5.1f,%5.1f,%5.1f)' % (world.imu_sensor.gyroscope),
            'Location:% 20s' % ('(% 5.1f, % 5.1f)' % (t.location.x, t.location.y)),
            # 'GNSS:% 24s' % ('(% 2.6f, % 3.6f)' % (world.gnss_sensor.lat, world.gnss_sensor.lon)),
            'Height:  % 18.0f m' % t.location.z,
            'AEBS: %23.0f ' % world.aebs.active,
            '']
        if isinstance(c, carla.VehicleControl):
            self._info_text += [
                ('Throttle:', c.throttle, 0.0, 1.0),
                ('Steer:', c.steer, -1.0, 1.0),
                ('Brake:', c.brake, 0.0, 1.0),
                ('Reverse:', c.reverse),
                ('Hand brake:', c.hand_brake),
                ('Manual:', c.manual_gear_shift),
                'Gear:        %s' % {-1: 'R', 0: 'N'}.get(c.gear, c.gear)]
        elif isinstance(c, carla.WalkerControl):
            self._info_text += [
                ('Speed:', c.speed, 0.0, 5.556),
                ('Jump:', c.jump)]
        # self._info_text += [
        # '',
        # 'Collision:',
        # collision,
        # '',
        # 'Number of vehicles: % 8d' % len(vehicles)]
        if len(vehicles) > 1:
            self._info_text += ['Nearby vehicles:']
            distance = lambda l: math.sqrt(
                (l.x - t.location.x) ** 2 + (l.y - t.location.y) ** 2 + (l.z - t.location.z) ** 2)
            vehicles = [(distance(x.get_location()), x) for x in vehicles if x.id != world.player.id]
            global g_least_distance
            g_least_distance = 0
            for d, vehicle in sorted(vehicles, key=lambda vehicles: vehicles[0]):
                if d > 200.0:
                    break
                vehicle_type = get_actor_display_name(vehicle, truncate=22)
                self._info_text.append('% 4dm %s' % (d, vehicle_type))
                if d < g_least_distance or g_least_distance==0:
                    g_least_distance = d

    def toggle_info(self):
        self._show_info = not self._show_info

    def notification(self, text, seconds=2.0):
        self._notifications.set_text(text, seconds=seconds)

    def error(self, text):
        self._notifications.set_text('Error: %s' % text, (255, 0, 0))

    def render(self, display):
        if self._show_info:
            info_surface = pygame.Surface((220, self.dim[1]))
            info_surface.set_alpha(100)
            display.blit(info_surface, (0, 0))
            v_offset = 4
            bar_h_offset = 100
            bar_width = 106
            for item in self._info_text:
                if v_offset + 18 > self.dim[1]:
                    break
                if isinstance(item, list):
                    if len(item) > 1:
                        points = [(x + 8, v_offset + 8 + (1.0 - y) * 30) for x, y in enumerate(item)]
                        pygame.draw.lines(display, (255, 136, 0), False, points, 2)
                    item = None
                    v_offset += 18
                elif isinstance(item, tuple):
                    if isinstance(item[1], bool):
                        rect = pygame.Rect((bar_h_offset, v_offset + 8), (6, 6))
                        pygame.draw.rect(display, (255, 255, 255), rect, 0 if item[1] else 1)
                    else:
                        rect_border = pygame.Rect((bar_h_offset, v_offset + 8), (bar_width, 6))
                        pygame.draw.rect(display, (255, 255, 255), rect_border, 1)
                        f = (item[1] - item[2]) / (item[3] - item[2])
                        if item[2] < 0.0:
                            rect = pygame.Rect((bar_h_offset + f * (bar_width - 6), v_offset + 8), (6, 6))
                        else:
                            rect = pygame.Rect((bar_h_offset, v_offset + 8), (f * bar_width, 6))
                        pygame.draw.rect(display, (255, 255, 255), rect)
                    item = item[0]
                if item:  # At this point has to be a str.
                    surface = self._font_mono.render(item, True, (255, 255, 255))
                    display.blit(surface, (8, v_offset))
                v_offset += 18
        self._notifications.render(display)
        self.help.render(display)

        if self.warnleuchte is not None:
            self.warnleuchte.render(self.warnleuchte,display) #Warnleuchte zeichnen
        else: print("Fehler: HUD.warnleuchte is None")


# ==============================================================================
# -- FadingText ----------------------------------------------------------------
# ==============================================================================


class FadingText(object):
    def __init__(self, font, dim, pos):
        self.font = font
        self.dim = dim
        self.pos = pos
        self.seconds_left = 0
        self.surface = pygame.Surface(self.dim)

    def set_text(self, text, color=(255, 255, 255), seconds=2.0):
        text_texture = self.font.render(text, True, color)
        self.surface = pygame.Surface(self.dim)
        self.seconds_left = seconds
        self.surface.fill((0, 0, 0, 0))
        self.surface.blit(text_texture, (10, 11))

    def tick(self, _, clock):
        delta_seconds = 1e-3 * clock.get_time()
        self.seconds_left = max(0.0, self.seconds_left - delta_seconds)
        self.surface.set_alpha(500.0 * self.seconds_left)

    def render(self, display):
        display.blit(self.surface, self.pos)


# ==============================================================================
# -- HelpText ------------------------------------------------------------------
# ==============================================================================


class HelpText(object):
    """Helper class to handle text output using pygame"""

    def __init__(self, font, width, height):
        lines = __doc__.split('\n')
        self.font = font
        self.line_space = 18
        self.dim = (780, len(lines) * self.line_space + 12)
        self.pos = (0.5 * width - 0.5 * self.dim[0], 0.5 * height - 0.5 * self.dim[1])
        self.seconds_left = 0
        self.surface = pygame.Surface(self.dim)
        self.surface.fill((0, 0, 0, 0))
        for n, line in enumerate(lines):
            text_texture = self.font.render(line, True, (255, 255, 255))
            self.surface.blit(text_texture, (22, n * self.line_space))
            self._render = False
        self.surface.set_alpha(220)

    def toggle(self):
        self._render = not self._render

    def render(self, display):
        if self._render:
            display.blit(self.surface, self.pos)


# ==============================================================================
# -- AEBS ----------------------------------------------------------------------
# ==============================================================================


class AEBS(object):
    def __init__(self, parent_actor, hud, world):
        self.active = True
        #self.warning_image = pygame.image.load("./images/warning.png")
        self.warning_image = pygame.image.load("./images/warning-sign.jpg")
        self.hud = hud
        self.player = parent_actor
        self.speed = 0
        self.distance = None
        self.crossed_threshold = False
        self.world = world
        self.action = 0
        self.beep_sound = pygame.mixer.Sound("./sounds/beep.mp3")

    def toggle_aebs(self):
        if self.active:
            self.active = not self.active
            print("Turned AEBS off!")
            pygame.mixer.Sound.play(self.beep_sound)
            self.test_aebs()
        else:
            self.active = not self.active
            print("Truner AEBS on!")
            self.test_aebs()

    def test(self):
        global g_interrupt, g_player_action
        while not g_interrupt:
            while self.world.constant_velocity_enabled:
                print("checking stuff", " ---- distance:", self.distance)
                if self.distance < 4 and self.action == 0 and not g_player_action:
                    pygame.mixer.Sound.play(self.beep_sound)
                    self.action += 1
                if self.distance < 3 and self.action == 1 and not g_player_action:
                    pygame.mixer.Sound.play(self.beep_sound)
                    time.sleep(.1)
                    pygame.mixer.Sound.play(self.beep_sound)

                    self.action += 1
                if self.distance < 2 and self.action == 2 and not g_player_action:
                    self.world.player.disable_constant_velocity()
                    self.world.constant_velocity_enabled = False
                    self.player.apply_control(carla.VehicleControl(brake=1))
                    self.action += 1
                if self.action == 3 and self.speed == 0 and not g_player_action:
                    self.player.apply_control(carla.VehicleControl(brake=0))
                    self.action = 0
                if g_player_action:
                    self.player.apply_control(carla.VehicleControl(brake=0))
                    self.action = 0

    def get_current_speed(self, world):

        velocity = world.player.get_velocity()
        current_speed = 3.6 * math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2)
        self.speed = current_speed
        # print(self.speed)
        self.activate_at_speed()

    def get_current_distance(self, world):
        global g_distance
        self.distance = g_distance
        # print(self.distance)

    def activate_at_speed(self):
        if self.speed >= 15:
            if not self.active:
                self.toggle_aebs()
        """else:
            if self.active:
                self.toggle_aebs()"""

    def test_aebs(self):
        print("Testing AEBS functionality...")
        if not self.active:
            print("ERROR: AEBS system is not active.")
            return
        try:
            #
            # Perform AEBS system test here
            #
            print("AEBS system test successful.")
        except Exception as e:
            print("ERROR: AEBS system test failed with exception:", e)

    def disable_on_failure(self):
        try:
            #
            # Perform AEBS system test here
            #
            print("AEBS system test successful.")
        except Exception as e:
            print("ERROR: AEBS system test failed with exception:", e)
            self.system_failure_warning()
            self.active = False
            print("AEBS system deactivated due to failure.")

    def system_failure_warning(self):
        print("WARNING: AEBS system has failed. Please check for errors and restart the system.")
        self.mixer.music.set_volume(0.2)
        self.mixer.music.load("warn.mp3")
        self.mixer.music.play()
        screen = pygame.display.set_mode((300, 300))
        screen.blit(self.warning_image, (0, 0))
        pygame.display.flip()
        # Wait for error to be fixed
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    return
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        pygame.quit()
                        return
                    else:
                        # Error fixed, hide warning image
                        pygame.quit()
                        return

    def collision_warning(self):
        print("WARNING: Collision detected. Please take immediate action to avoid impact.")
        self.mixer.music.set_volume(0.2)
        self.mixer.music.load("collision.mp3")
        self.mixer.music.play()
        screen = pygame.display.set_mode((300, 300))
        screen.blit(self.warning_image, (0, 0))
        pygame.display.flip()
        # Wait for warning to be acknowledged
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    return
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        pygame.quit()
                        return
                    else:
                        # Warning acknowledged, hide warning image
                        pygame.quit()
                        return


# ==============================================================================
# -- DistanceSensor ------------------------------------------------------------
# ==============================================================================


class DistanceSensor(object):
    def __init__(self, parent_actor, parent_actor_2, aebs):
        self.sensor = None
        self.aebs = aebs
        self.ego = parent_actor
        self.lead = parent_actor_2
        self.world = self.ego.get_world()
        self.blueprint_library = self.world.get_blueprint_library()
        self.actor_list = []
        self.actor_list.append(parent_actor_2)
        self.actor_list.append(parent_actor)
        print("created ")
        self.reset()

    def reset(self):
        self.rgb_image = None;
        self.semantic_image = None;
        self.distance = None
        self.prev_kmph = 0;
        self.actor_list = [];
        skip_episode = False;
        kmph = None
        self.bump = False;
        self.crossed_threshold = False
        self.attach_sensors()
        while not self.distance:
            ""
        # Ensure lead is ahead of ego before start
        # print(self.distance, " --- ", MAX_DISTANCE)
        if self.distance < MAX_DISTANCE:
            # print("we made it")
            """ lead_speed = random.uniform(0.40, 0.55)
             ego_speed = random.uniform(0.65, 0.80)
             print("speed: ", lead_speed, ego_speed)
             self.lead.apply_control(carla.VehicleControl(throttle=0.3))
             self.ego.apply_control(carla.VehicleControl(throttle=0.4))
 
             velocity = self.ego.get_velocity()
             kmph = 3.6 * math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2)  
             self.episode_start = time.time()"""
            # print("speed: ", lead_speed, ego_speed)

        else:
            self.destroy_actor()
            skip_episode = True

        state = (self.rgb_image, self.semantic_image, self.distance, kmph)
        return state, skip_episode

    def position_behind(self):
        lead_location = random.choice(self.world.get_map().get_spawn_points())
        ego_location = carla.Transform(lead_location.location, lead_location.rotation)
        if lead_location.rotation.yaw > 80 and lead_location.rotation.yaw < 100:
            ego_location.location.y -= random.uniform(12, 17)
        elif lead_location.rotation.yaw < -80 and lead_location.rotation.yaw > -100:
            ego_location.location.y += random.uniform(12, 17)
        elif lead_location.rotation.yaw > 170 and lead_location.rotation.yaw < 190:
            ego_location.location.x -= random.uniform(12, 17)
        elif lead_location.rotation.yaw < -170 and lead_location.rotation.yaw > -190:
            ego_location.location.x += random.uniform(12, 17)

        return lead_location, ego_location

    def attach_sensors(self):
        semantic_camera = self.blueprint_library.find('sensor.camera.semantic_segmentation')
        semantic_camera.set_attribute('image_size_x', f'{SEMANTIC_IMG_WIDTH}')
        semantic_camera.set_attribute('image_size_y', f'{SEMANTIC_IMG_HEIGHT}')
        rgb_camera = self.blueprint_library.find('sensor.camera.rgb')
        rgb_camera.set_attribute('image_size_x', f'{RGB_IMG_WIDTH}')
        rgb_camera.set_attribute('image_size_y', f'{RGB_IMG_HEIGHT}')
        transform = carla.Transform(carla.Location(x=2.5, z=0.7))
        self.semantic_camera = self.world.spawn_actor(semantic_camera, transform, attach_to=self.ego)
        self.semantic_camera.listen(lambda image: self.preprocess_semantic(image))
        self.rgb_camera = self.world.spawn_actor(rgb_camera, transform, attach_to=self.ego)
        self.rgb_camera.listen(lambda image: self.preprocess_rgb(image))
        self.actor_list.append(self.semantic_camera)
        self.actor_list.append(self.rgb_camera)

    def preprocess_semantic(self, image):
        image_data = np.array(image.raw_data)
        image_data = image_data.reshape((SEMANTIC_IMG_HEIGHT, SEMANTIC_IMG_WIDTH, 4))
        image_data = image_data[:, :, :3]
        self.semantic_image = image_data
        self.distance = self.get_distance(self.semantic_image)
        # time.sleep(0.05)

    def preprocess_rgb(self, image):
        image_data = np.array(image.raw_data)
        image_data = image_data.reshape((RGB_IMG_HEIGHT, RGB_IMG_WIDTH, 4))
        image_data = image_data[300:600, 0:800, :]
        hmin = 0;
        hmax = 255;
        smin = 0;
        smax = 80;
        vmin = 180;
        vmax = 255
        bgrImage = cv2.cvtColor(image_data, cv2.COLOR_BGRA2BGR)
        yuvImage = cv2.cvtColor(bgrImage, cv2.COLOR_BGR2YUV)
        yuvImage[:, :, 0] = cv2.equalizeHist(yuvImage[:, :, 0])
        yuvImage[:, 0, :] = cv2.equalizeHist(yuvImage[:, 0, :])
        yuvImage[0, :, :] = cv2.equalizeHist(yuvImage[0, :, :])
        normalized = cv2.cvtColor(yuvImage, cv2.COLOR_YUV2RGB)
        hsvImage = cv2.cvtColor(normalized, cv2.COLOR_RGB2HSV)
        lower = (hmin, smin, vmin)
        upper = (hmax, smax, vmax)
        filter = cv2.inRange(hsvImage, lower, upper)
        edgeImage = cv2.Canny(filter, 100, 200)
        img = cv2.resize(edgeImage, (200, 75))
        self.rgb_image = img
        # time.sleep(0.05)

    def step(self, action):
        if self.distance < ACTION_THRESHOLD:
            self.crossed_threshold = True
            if action == 0:
                pass
            elif action == 1:
                self.ego.apply_control(carla.VehicleControl(brake=0.33))
            elif action == 2:
                self.ego.apply_control(carla.VehicleControl(brake=0.67))
            elif action == 3:
                self.ego.apply_control(carla.VehicleControl(brake=1))
        skip_episode = False
        velocity = self.ego.get_velocity()
        kmph = 3.6 * math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2)
        deceleration = kmph - self.prev_kmph
        alpha = 0.001;
        beta = 0.1;
        mu = 0.01;
        nu = 100;
        done = False
        if self.distance < CRASH_DISTANCE:
            self.destroy_actor()
            self.bump = True;
            done = True
        elif self.crossed_threshold and self.distance > ACTION_THRESHOLD:
            self.destroy_actor()
            done = True
        reward = -(alpha * (self.distance) ** 2 + beta) * deceleration - (mu * kmph ** 2 + nu) * self.bump
        self.prev_kmph = kmph
        if self.episode_start + MAX_SECONDS_PER_EPISODE < time.time():
            self.destroy_actor()
            skip_episode = True;
            done = True
        state = (self.rgb_image, self.semantic_image, self.distance, kmph)
        return state, reward, done, skip_episode

    def get_distance(self, semantic_image):
        global g_distance
        percieved_pixel_count = 0;
        vehicle_pixel_count = 0
        for layer in semantic_image:
            for pixel in layer:
                if pixel[2] == 10:
                    vehicle_pixel_count += 1
            if percieved_pixel_count < vehicle_pixel_count:
                percieved_pixel_count = vehicle_pixel_count
            vehicle_pixel_count = 0

        width = self.lead.bounding_box.extent.x * 2
        if percieved_pixel_count > 0:
            distance = (width * FOCAL_LENGTH) / percieved_pixel_count
            g_distance = distance
        if percieved_pixel_count == 0:
            print("coulnd't get distance")
            distance = 0
            g_distance = distance
        return distance

    def destroy_actor(self):
        for actor in self.actor_list:
            if actor.is_alive:
                if actor.__class__ != carla.libcarla.Vehicle:
                    actor.stop()
                actor.destroy()


# ==============================================================================
# -- CollisionSensor -----------------------------------------------------------
# ==============================================================================


class CollisionSensor(object):
    def __init__(self, parent_actor, hud):
        self.sensor = None
        self.history = []
        self._parent = parent_actor
        self.hud = hud
        world = self._parent.get_world()
        bp = world.get_blueprint_library().find('sensor.other.collision')
        self.sensor = world.spawn_actor(bp, carla.Transform(), attach_to=self._parent)
        # We need to pass the lambda a weak reference to self to avoid circular
        # reference.
        weak_self = weakref.ref(self)
        self.sensor.listen(lambda event: CollisionSensor._on_collision(weak_self, event))

    def get_collision_history(self):
        history = collections.defaultdict(int)
        for frame, intensity in self.history:
            history[frame] += intensity
        return history

    @staticmethod
    def _on_collision(weak_self, event):
        self = weak_self()
        if not self:
            return
        actor_type = get_actor_display_name(event.other_actor)
        self.hud.notification('Collision with %r' % actor_type)
        impulse = event.normal_impulse
        intensity = math.sqrt(impulse.x ** 2 + impulse.y ** 2 + impulse.z ** 2)
        self.history.append((event.frame, intensity))
        if len(self.history) > 4000:
            self.history.pop(0)


# ==============================================================================
# -- CameraManager -------------------------------------------------------------
# ==============================================================================


class CameraManager(object):
    def __init__(self, parent_actor, hud, gamma_correction):
        self.sensor = None
        self.surface = None
        self._parent = parent_actor
        self.hud = hud
        self.recording = False
        bound_x = 0.5 + self._parent.bounding_box.extent.x
        bound_y = 0.5 + self._parent.bounding_box.extent.y
        bound_z = 0.5 + self._parent.bounding_box.extent.z
        Attachment = carla.AttachmentType

        if not self._parent.type_id.startswith("walker.pedestrian"):
            self._camera_transforms = [
                (carla.Transform(carla.Location(x=-2.0 * bound_x, y=+0.0 * bound_y, z=2.0 * bound_z),
                                 carla.Rotation(pitch=8.0)), Attachment.SpringArm),
                (
                carla.Transform(carla.Location(x=+0.8 * bound_x, y=+0.0 * bound_y, z=1.3 * bound_z)), Attachment.Rigid),
                (carla.Transform(carla.Location(x=+1.9 * bound_x, y=+1.0 * bound_y, z=1.2 * bound_z)),
                 Attachment.SpringArm),
                (carla.Transform(carla.Location(x=-2.8 * bound_x, y=+0.0 * bound_y, z=4.6 * bound_z),
                                 carla.Rotation(pitch=6.0)), Attachment.SpringArm),
                (carla.Transform(carla.Location(x=-1.0, y=-1.0 * bound_y, z=0.4 * bound_z)), Attachment.Rigid)]
        else:
            self._camera_transforms = [
                (carla.Transform(carla.Location(x=-2.5, z=0.0), carla.Rotation(pitch=-8.0)), Attachment.SpringArm),
                (carla.Transform(carla.Location(x=1.6, z=1.7)), Attachment.Rigid),
                (
                carla.Transform(carla.Location(x=2.5, y=0.5, z=0.0), carla.Rotation(pitch=-8.0)), Attachment.SpringArm),
                (carla.Transform(carla.Location(x=-4.0, z=2.0), carla.Rotation(pitch=6.0)), Attachment.SpringArm),
                (carla.Transform(carla.Location(x=0, y=-2.5, z=-0.0), carla.Rotation(yaw=90.0)), Attachment.Rigid)]

        self.transform_index = 1
        self.sensors = [
            ['sensor.camera.rgb', cc.Raw, 'Camera RGB', {}],
            ['sensor.camera.depth', cc.Raw, 'Camera Depth (Raw)', {}],
            ['sensor.camera.depth', cc.Depth, 'Camera Depth (Gray Scale)', {}],
            ['sensor.camera.depth', cc.LogarithmicDepth, 'Camera Depth (Logarithmic Gray Scale)', {}],
            ['sensor.camera.semantic_segmentation', cc.Raw, 'Camera Semantic Segmentation (Raw)', {}],
            ['sensor.camera.semantic_segmentation', cc.CityScapesPalette,
             'Camera Semantic Segmentation (CityScapes Palette)', {}],
            ['sensor.camera.instance_segmentation', cc.CityScapesPalette,
             'Camera Instance Segmentation (CityScapes Palette)', {}],
            ['sensor.camera.instance_segmentation', cc.Raw, 'Camera Instance Segmentation (Raw)', {}],
            ['sensor.lidar.ray_cast', None, 'Lidar (Ray-Cast)', {'range': '50'}],
            ['sensor.camera.dvs', cc.Raw, 'Dynamic Vision Sensor', {}],
            ['sensor.camera.rgb', cc.Raw, 'Camera RGB Distorted',
             {'lens_circle_multiplier': '3.0',
              'lens_circle_falloff': '3.0',
              'chromatic_aberration_intensity': '0.5',
              'chromatic_aberration_offset': '0'}],
            ['sensor.camera.optical_flow', cc.Raw, 'Optical Flow', {}],
        ]
        world = self._parent.get_world()
        bp_library = world.get_blueprint_library()
        for item in self.sensors:
            bp = bp_library.find(item[0])
            if item[0].startswith('sensor.camera'):
                bp.set_attribute('image_size_x', str(hud.dim[0]))
                bp.set_attribute('image_size_y', str(hud.dim[1]))
                if bp.has_attribute('gamma'):
                    bp.set_attribute('gamma', str(gamma_correction))
                for attr_name, attr_value in item[3].items():
                    bp.set_attribute(attr_name, attr_value)
            elif item[0].startswith('sensor.lidar'):
                self.lidar_range = 50

                for attr_name, attr_value in item[3].items():
                    bp.set_attribute(attr_name, attr_value)
                    if attr_name == 'range':
                        self.lidar_range = float(attr_value)

            item.append(bp)
        self.index = None

    def toggle_camera(self):
        self.transform_index = (self.transform_index + 1) % len(self._camera_transforms)
        self.set_sensor(self.index, notify=False, force_respawn=True)

    def set_sensor(self, index, notify=True, force_respawn=False):
        index = index % len(self.sensors)
        needs_respawn = True if self.index is None else \
            (force_respawn or (self.sensors[index][2] != self.sensors[self.index][2]))
        if needs_respawn:
            if self.sensor is not None:
                self.sensor.destroy()
                self.surface = None
            self.sensor = self._parent.get_world().spawn_actor(
                self.sensors[index][-1],
                self._camera_transforms[self.transform_index][0],
                attach_to=self._parent,
                attachment_type=self._camera_transforms[self.transform_index][1])
            # We need to pass the lambda a weak reference to self to avoid
            # circular reference.
            weak_self = weakref.ref(self)
            self.sensor.listen(lambda image: CameraManager._parse_image(weak_self, image))
        if notify:
            self.hud.notification(self.sensors[index][2])
        self.index = index

    def next_sensor(self):
        self.set_sensor(self.index + 1)

    def toggle_recording(self):
        self.recording = not self.recording
        self.hud.notification('Recording %s' % ('On' if self.recording else 'Off'))

    def render(self, display):
        if self.surface is not None:
            display.blit(self.surface, (0, 0))

    @staticmethod
    def _parse_image(weak_self, image):
        self = weak_self()
        if not self:
            return
        if self.sensors[self.index][0].startswith('sensor.lidar'):
            points = np.frombuffer(image.raw_data, dtype=np.dtype('f4'))
            points = np.reshape(points, (int(points.shape[0] / 4), 4))
            lidar_data = np.array(points[:, :2])
            lidar_data *= min(self.hud.dim) / (2.0 * self.lidar_range)
            lidar_data += (0.5 * self.hud.dim[0], 0.5 * self.hud.dim[1])
            lidar_data = np.fabs(lidar_data)  # pylint: disable=E1111
            lidar_data = lidar_data.astype(np.int32)
            lidar_data = np.reshape(lidar_data, (-1, 2))
            lidar_img_size = (self.hud.dim[0], self.hud.dim[1], 3)
            lidar_img = np.zeros((lidar_img_size), dtype=np.uint8)
            lidar_img[tuple(lidar_data.T)] = (255, 255, 255)
            self.surface = pygame.surfarray.make_surface(lidar_img)
        elif self.sensors[self.index][0].startswith('sensor.camera.dvs'):
            # Example of converting the raw_data from a carla.DVSEventArray
            # sensor into a NumPy array and using it as an image
            dvs_events = np.frombuffer(image.raw_data, dtype=np.dtype([
                ('x', np.uint16), ('y', np.uint16), ('t', np.int64), ('pol', np.bool)]))
            dvs_img = np.zeros((image.height, image.width, 3), dtype=np.uint8)
            # Blue is positive, red is negative
            dvs_img[dvs_events[:]['y'], dvs_events[:]['x'], dvs_events[:]['pol'] * 2] = 255
            self.surface = pygame.surfarray.make_surface(dvs_img.swapaxes(0, 1))
        elif self.sensors[self.index][0].startswith('sensor.camera.optical_flow'):
            image = image.get_color_coded_flow()
            array = np.frombuffer(image.raw_data, dtype=np.dtype("uint8"))
            array = np.reshape(array, (image.height, image.width, 4))
            array = array[:, :, :3]
            array = array[:, :, ::-1]
            self.surface = pygame.surfarray.make_surface(array.swapaxes(0, 1))
        else:
            image.convert(self.sensors[self.index][1])
            array = np.frombuffer(image.raw_data, dtype=np.dtype("uint8"))
            array = np.reshape(array, (image.height, image.width, 4))
            array = array[:, :, :3]
            array = array[:, :, ::-1]
            self.surface = pygame.surfarray.make_surface(array.swapaxes(0, 1))
        if self.recording:
            image.save_to_disk('_out/%08d' % image.frame)


# ==============================================================================
# -- ObstacleSensor() ----------------------------------------------------------
# https://carla.readthedocs.io/en/latest/ref_sensors/#obstacle-detector
# -- Versuch: Anscheinend gibt es einen Sensor, welcher Hindernisse erkennen kann.
# ==============================================================================
class ObstacleSensor:

    __obstacle_sensor = None
    __obstacle_sensor_callback_counter = 0
    __camera = None
    __world = None
    __player = None
    __image_w = 0
    __image_h = 0
    __sensor_data = { 'rgb_image': np.zeros((__image_h, __image_w, 4)),
                      'obstacle': []
                     }
    __current_obstacle = []

    def getCurrentObstacleDictance(self, maxAlterDesHindernissesInMillis):
        try:
            if len(self.__current_obstacle) > 0:
                type_id = self.__current_obstacle['type_id']
                distance = self.__current_obstacle['distance']
                frame = self.__current_obstacle['frame']
                timestamp = self.__current_obstacle['timestamp']
                actor = self.__current_obstacle['actor']
                other_actor = self.__current_obstacle['other_actor']
                #print(f"last obstacle,{type_id},{distance:.2f},{frame},{timestamp},actor={actor},other_actor={other_actor}")
                #Zeit vergleichen
                myTimeStamp = self.__current_obstacle['myTimeStamp']
                timeStamp = time.time()
                #t1 = datetime.strptime(myTimeStamp, "%b %d %H:%M:%S %Y")
                #t2 = datetime.strptime(timeStamp, "%b %d %H:%M:%S %Y")
                t_diff = timeStamp-myTimeStamp
                if (t_diff < maxAlterDesHindernissesInMillis):
                    return distance
                else:
                    print(f"Hindernis veraltet, Alter in Millis={t_diff:.2f}")
                    return 0.0
            else: return 0.0
        except Exception as e:
            print(type(e))  # the exception type
            print(e.args)  # arguments stored in .args
            print(e)  # __str__ allows args to be printed directly,
            return 0.0 #keine Hindernisse


    def __init__(self, _player, _world):
        self.__world = _world
        self.__player = _player
        self.__attach(self.__world, self.__player)

    def __attach(self, _world, _vehicle):
        bp_lib = _world.world.get_blueprint_library()

        # Add camera sensor
        camera_bp = bp_lib.find('sensor.camera.rgb')
        _fov = camera_bp.get_attribute("fov").as_float()
        self.__image_w = camera_bp.get_attribute("image_size_x").as_int()
        self.__image_h = camera_bp.get_attribute("image_size_y").as_int()
        camera_init_trans = carla.Transform(carla.Location(z=2))
        self.__camera = _world.world.spawn_actor(camera_bp, camera_init_trans, attach_to=_vehicle)

        # Sensor wird dem Fahrzeug angehängt
        obstacle_bp = bp_lib.find('sensor.other.obstacle')
        obstacle_bp.set_attribute('hit_radius', '0.5')
        obstacle_bp.set_attribute('distance', '50')
        self.__obstacle_sensor = _world.world.spawn_actor(obstacle_bp, carla.Transform(), attach_to=_vehicle)

        # Calculate the camera projection matrix to project from 3D -> 2D
        K = self.__build_projection_matrix(self.__image_w, self.__image_h, _fov)
        # Starte den Sensor, damit daten empfangen werden können
        self.__obstacle_sensor.listen(lambda event: self.__obstacle_callback(event, self.__sensor_data, self.__camera, K))
        print("ObstacleSensor.__attached(...)")

    # Auxilliary geometry functions for transforming to screen coordinates
    def __build_projection_matrix(self, w, h, fov):
        focal = w / (2.0 * np.tan(fov * np.pi / 360.0))
        K = np.identity(3)
        K[0, 0] = K[1, 1] = focal
        K[0, 2] = w / 2.0
        K[1, 2] = h / 2.0
        return K

    def __obstacle_callback(self, event, data_dict, camera, k_mat): # call back des Obstacle Sensors
        self.__obstacle_sensor_callback_counter = self.__obstacle_sensor_callback_counter + 1
        #print(f"def __obstacle_callback(....)={self.__obstacle_sensor_callback_counter}")
        if 'static' not in event.other_actor.type_id: #"static" wird vermutlich alle Objekte wie ein Gebäude ausschließen
            #data_dict['obstacle'].append({'transform': event.other_actor.type_id, 'frame': event.frame})
            self.__current_obstacle = {'type_id': event.other_actor.type_id, 'frame': event.frame, 'timestamp':event.timestamp, 'actor':event.actor, 'other_actor':event.other_actor, 'distance':event.distance, 'myTimeStamp':time.time()}
            #print(f"Obstacle_event_distance in Meter={event.distance}") # distance https://carla.readthedocs.io/en/0.9.12/python_api/#instance-variables_38
            #print(f"Changed __current_bstacle={self.__current_obstacle}, other actor={event.other_actor}")
            #print(f"event.other_actor.attributes={event.other_actor.attributes}")
            #print(f"event.other_actor.type_id={event.other_actor.type_id}")
            #print(f"event.other_actor.is_alive={event.other_actor.is_alive}")
            #print(f"event.other_actor.get_transform={event.other_actor.get_transform}")
            #other_actor_transformation = event.other_actor.get_transform
            #print(f"event.other_actor.get_transform={other_actor_transformation}")
            #if issubclass(event.other_actor, carla.libcarla.Vehicle): # if (event.other_actor is carla.libcarla.Vehicle):
            #    other_vehicle = event.other_actor
            #    print(f"Dieses Fahrzeug={other_vehicle} als Hindernis erkannt!")
            #else:
            #    other_thing = event.other_actor
            #    print(f"Hindernis erkannt={other_thing}!")


        #print(data_dict) #like {'rgb_image': array([], shape=(0, 0, 4), dtype=float64), 'obstacle': [{'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2728}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2729}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2737}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2738}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2739}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2740}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2741}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2742}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2743}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2744}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2745}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2746}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2747}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2748}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2749}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2750}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2751}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2752}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2753}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2886}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2887}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2888}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2889}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2890}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2891}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2892}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2893}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2894}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2895}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2896}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2897}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2900}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2901}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2902}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2903}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2906}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2907}, {'transform': 'vehicle.mercedes.coupe_2020', 'frame': 2908}]}

        #nächste Abschnitt sollte eigentlich das Objekt markieren, aber es klappt irgendwie nicht
        #world_2_camera = np.array(camera.get_transform().get_inverse_matrix())
        #image_point = self.__get_image_point(event.other_actor.get_transform().location, k_mat, world_2_camera)
        #if 0 < image_point[0] < self.__image_w and 0 < image_point[1] < self.__image_h:
        #    print(f"Changed __current_bstacle=Error")
        #    cv2.circle(data_dict['rgb_image'], tuple(image_point), 10, (0, 0, 255), 3)
        #else:
        #    print(f"Changed __current_bstacle={image_point[0], image_point[1], self.__image_w, self.__image_h}")

    def __get_image_point(self, loc, K, w2c):
        # Calculate 2D projection of 3D coordinate

        # Format the input coordinate (loc is a carla.Position object)
        point = np.array([loc.x, loc.y, loc.z, 1])
        # transform to camera coordinates
        point_camera = np.dot(w2c, point)

        # New we must change from UE4's coordinate system to an "standard"
        # (x, y ,z) -> (y, -z, x)
        # and we remove the fourth componebonent also
        point_camera = [point_camera[1], -point_camera[2], point_camera[0]]

        # now project 3D->2D using the camera matrix
        point_img = np.dot(K, point_camera)
        # normalize
        point_img[0] /= point_img[2]
        point_img[1] /= point_img[2]

        return tuple(map(int, point_img[0:2]))

# ==============================================================================
# -- game_loop() ---------------------------------------------------------------
# ==============================================================================


def game_loop(args):
    pygame.init()
    pygame.font.init()
    world = None
    original_settings = None

    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(20.0)

        sim_world = client.get_world()
        if args.sync:
            original_settings = sim_world.get_settings()
            settings = sim_world.get_settings()
            if not settings.synchronous_mode:
                settings.synchronous_mode = True
                settings.fixed_delta_seconds = 0.05
            sim_world.apply_settings(settings)

            traffic_manager = client.get_trafficmanager()
            traffic_manager.set_synchronous_mode(True)

        if args.autopilot and not sim_world.get_settings().synchronous_mode:
            print("WARNING: You are currently in asynchronous mode and could "
                  "experience some issues with the traffic simulation")

        display = pygame.display.set_mode(
            (args.width, args.height),
            pygame.HWSURFACE | pygame.DOUBLEBUF)
        display.fill((0, 0, 0))
        pygame.display.flip()

        hud = HUD(args.width, args.height)
        world = World(sim_world, hud, args, client)
        controller = KeyboardControl(world, args.autopilot)

        if args.sync:
            sim_world.tick()
        else:
            sim_world.wait_for_tick()

        clock = pygame.time.Clock()
        while True:
            if args.sync:
                sim_world.tick()
            clock.tick_busy_loop(60)
            if controller.parse_events(client, world, clock, args.sync):
                return
            world.tick(clock)
            world.render(display)
            pygame.display.flip()

    finally:

        if original_settings:
            sim_world.apply_settings(original_settings)

        if (world and world.recording_enabled):
            client.stop_recorder()

        if world is not None:
            world.destroy()
            world.__del__()

        pygame.quit()


# ==============================================================================
# -- main() --------------------------------------------------------------------
# ==============================================================================


def main():
    argparser = argparse.ArgumentParser(
        description='CARLA Manual Control Client')
    argparser.add_argument(
        '-v', '--verbose',
        action='store_true',
        dest='debug',
        help='print debug information')
    argparser.add_argument(
        '--host',
        metavar='H',
        default='127.0.0.1',
        help='IP of the host server (default: 127.0.0.1)')
    argparser.add_argument(
        '-p', '--port',
        metavar='P',
        default=2000,
        type=int,
        help='TCP port to listen to (default: 2000)')
    argparser.add_argument(
        '-a', '--autopilot',
        action='store_true',
        help='enable autopilot')
    argparser.add_argument(
        '--res',
        metavar='WIDTHxHEIGHT',
        default='720x480', #default='1280x720',
        help='window resolution (default: 720x480)') #help='window resolution (default: 1280x720)')
    argparser.add_argument(
        '--filter',
        metavar='PATTERN',
        default='vehicle.*',
        help='actor filter (default: "vehicle.*")')
    argparser.add_argument(
        '--generation',
        metavar='G',
        default='2',
        help='restrict to certain actor generation (values: "1","2","All" - default: "2")')
    argparser.add_argument(
        '--rolename',
        metavar='NAME',
        default='hero',
        help='actor role name (default: "hero")')
    argparser.add_argument(
        '--gamma',
        default=2.2,
        type=float,
        help='Gamma correction of the camera (default: 2.2)')
    argparser.add_argument(
        '--sync',
        action='store_true',
        help='Activate synchronous mode execution')
    args = argparser.parse_args()

    args.width, args.height = [int(x) for x in args.res.split('x')]

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(format='%(levelname)s: %(message)s', level=log_level)

    logging.info('listening to server %s:%s', args.host, args.port)

    print(__doc__)

    try:

        game_loop(args)

    except KeyboardInterrupt:
        print('\nCancelled by user. Bye!')


if __name__ == '__main__':
    main()
