#!/usr/bin/env python3

"""Test CLI

Run a simple CLI modeled off of simple_cli
"""

import readline
import sys, os
import atexit
import code
import datetime
import logging
import platform
import re
import subprocess
import time
import traceback
from importlib import __import__, reload

import anki_vector
from anki_vector import *
from anki_vector.util import *

from event_monitor import monitor, unmonitor

import vector_fsm
from vector_fsm import *
from vector_fsm.worldmap import ArucoMarkerObj, CustomMarkerObj, WallObj

RUNNING = False

def setup():
    global RUNNING
    # tab completion
    readline.parse_and_bind('tab: complete')
    # history file
    if 'HOME' in os.environ:  # Linux
        histfile = os.path.join(os.environ['HOME'], '.pythonhistory')
    elif 'USERPROFILE' in os.environ:  # Windows
        histfile = os.path.join(os.environ['USERPROFILE'], '.pythonhistory')
    else:
        histfile = '.pythonhistory'

    try:
        readline.read_history_file(histfile)
    except IOError:
        pass
    atexit.register(readline.write_history_file, histfile)

    os_version = platform.system()
    # del platform

    # Put current directory on search path.
    if '.' not in sys.path:
        sys.path.append('.')

    res = 0
    ans = None

    RUNNING = True


def do_shell_command(cmd):
    try:
        subprocess.call(cmd, shell=True)
    except Exception as e:
        print(e)


def text_message(msg):
    running_fsm = vector_fsm.program.running_fsm
    if not running_fsm or not running_fsm.running:
        print('No state machine running. Use runfsm(module_name) to start a state machine.')
        return
    try:
        running_fsm.robot.erouter.post(TextMsgEvent(msg))
    except KeyboardInterrupt: raise
    except Exception as e:
        traceback.print_exc()
        print()


def sort_wmobject_ids(ids):
    preference = ['Charger','Cube','Aruco','Wall','Door','CustomCube','CustomMarker','Room','Face']

    def key(id):
        index = 0
        for prefix in preference:
            if id.startswith(prefix):
                break
            else:
                index += 1
        return ('%02d' % index) + id

    result = sorted(ids, key=key)
    return result


def show_stuff(args):
    global running_fsm
    running_fsm = vector_fsm.program.running_fsm
    spec = args[0] if len(args) > 0 else ""
    if spec == 'active':
        if not running_fsm:
            print('No state machine present.')
        elif not running_fsm.running:
            print("State machine '%s' is not running." % running_fsm.name)
        else:
            show_active(running_fsm,0)
    elif spec == "kine":
        show_kine(args[1:])
    elif spec == 'cam_viewer' or spec=='viewer':
        if running_fsm:
            running_fsm.stop()
        running_fsm = StateMachineProgram(cam_viewer=True,
                                          simple_cli_callback=simple_cli_callback)
        running_fsm.set_name("CamViewer")
        running_fsm.simple_cli_callback = simple_cli_callback
        vector_fsm.program.running_fsm = running_fsm
        robot.loop.call_soon(running_fsm.start)
    elif spec == "crosshairs":
        if running_fsm:
            running_fsm.viewer_crosshairs = not running_fsm.viewer_crosshairs
    elif spec == "particle_viewer":
        if not robot.world.particle_viewer:
            robot.world.particle_viewer = ParticleViewer(robot)
            robot.world.particle_viewer.start()
    elif spec == "path_viewer":
        if not robot.world.path_viewer:
            robot.world.path_viewer = PathViewer(robot,world.rrt)
            robot.world.path_viewer.start()
    elif spec == "worldmap_viewer":
        if not robot.world.worldmap_viewer:
            robot.world.worldmap_viewer = WorldMapViewer(robot)
            robot.world.worldmap_viewer.start()
    elif (spec == "all") or (spec == "all_viewers"):
        running_fsm = StateMachineProgram(cam_viewer=True,
                                          simple_cli_callback=simple_cli_callback)
        running_fsm.set_name("CamViewer")
        running_fsm.simple_cli_callback = simple_cli_callback
        vector_fsm.program.running_fsm = running_fsm
        robot.loop.call_soon(running_fsm.start)
        robot.world.particle_viewer = ParticleViewer(robot)
        robot.world.particle_viewer.start()
        robot.world.path_viewer = PathViewer(robot,world.rrt)
        robot.world.path_viewer.start()
        robot.world.worldmap_viewer = WorldMapViewer(robot)
        robot.world.worldmap_viewer.start()
    elif spec == "pose":
        show_pose()
    elif spec == "landmarks":
        show_landmarks()
    elif spec == "objects":
        show_objects()
    elif spec == "particle":
        show_particle(args[1:])
    elif spec == "camera":
        show_camera(args[1:])
    else:
        print("""Invalid option. Try one of:
  show viewer | cam_viewer
  show crosshairs
  show worldmap_viewer
  show particle_viewer
  show path_viewer
  show all | all_viewers
  show active
  show kine [joint]
  show pose
  show landmarks
  show objects
  show particle [n]
  show camera n
  """)


def show_active(node,depth):
    if node.running: print('  '*depth, node)
    for child in node.children.values():
        show_active(child, depth+1)
    for trans in node.transitions:
        if trans.running: print('  '*(depth+1), trans)


def show_kine(args):
    if len(args) == 0:
        show_kine_tree(0, robot.kine.joints['base'])
        print()
    elif len(args) == 1:
        show_kine_joint(args[0])
    else:
        print('Usage:  show kine [joint]')


def show_kine_tree(level, joint):
    qstring = ''
    if joint.type != 'fixed':
        if isinstance(joint.q, (float,int)):
            qval = ('%9.5g' % joint.q).strip()
            if joint.type == 'revolute':
                qval = qval + (' (%.1f deg.)' % (joint.q*180/pi))
        else:
            qval = '(' + (', '.join([('%9.5g' % v).strip() for v in joint.q])) + ')'
        qstring = ' q=' + qval
    print('  '*level, joint.name, ': ', joint.type, qstring, sep='')
    for child in joint.children:
        show_kine_tree(level+1, child)


def show_kine_joint(name):
    if name not in robot.kine.joints:
        print("'"+repr(name)+"' is not the name of a joint.  Try 'show kine'.")
        return
    joint = robot.kine.joints[name]
    fmt = '%10s'

    def formatq(type,val):
        if type == 'revolute':
            if val == inf:
                return 'inf'
            elif val == -inf:
                return '-inf'
            jrad = ('%9.5g' % val).strip() + ' radians'
            jdeg = '(' + ('%9.5g' % (val * 180/pi)).strip() + ' degrees)' if val != 0 else ''
            return jrad + ' ' + jdeg
        elif type == 'prismatic':
            return ('%9.5g' % val).strip() + ' mm'
        elif type == 'fixed':
            return ''
        elif type == 'world':
            if val is None:
                return ''
            else:
                return '(' + (', '.join(['%9.5g' % x for x in val])) + ')'
        else:
            raise ValueError(type)

    print(fmt % 'Name:', name)
    print(fmt % 'Type:', joint.type)
    print(fmt % 'Parent:', joint.parent.name if joint.parent else '')
    print(fmt % 'Descr.:', joint.description)
    print(fmt % 'q:', formatq(joint.type, joint.q))
    print(fmt % 'qmin:', formatq(joint.type, joint.qmin))
    print(fmt % 'qmax:', formatq(joint.type, joint.qmax))
    print(fmt % 'DH d:', formatq('prismatic',joint.d))
    print(fmt % 'DH theta:', formatq('revolute',joint.theta))
    print(fmt % 'DH alpha:', formatq('revolute',joint.alpha))
    print(fmt % 'DH r:', formatq('prismatic',joint.r))
    print(fmt % 'Link in base frame:')
    tprint(robot.kine.link_to_base(name))
    print()


def show_pose():
    print('robot.pose is:   %6.1f %6.1f @ %6.1f deg.' %
          (robot.pose.position.x, robot.pose.position.y, robot.pose_angle.degrees))
    print('particle filter: %6.1f %6.1f @ %6.1f deg.' %
          (*robot.world.particle_filter.pose[0:2],
           robot.world.particle_filter.pose[2]*180/pi))
    print()


def show_landmarks():
    landmarks = robot.world.particle_filter.sensor_model.landmarks
    print('The particle filter has %d landmark%s:' %
          (len(landmarks), '' if (len(landmarks) == 1) else 's'))
    show_landmarks_helper(landmarks)


def show_landmarks_helper(landmarks):
    sorted_keys = sort_wmobject_ids(landmarks)
    for key in sorted_keys:
        value = landmarks[key]
        if isinstance(value, Pose):
            x = value.position.x
            y = value.position.y
            theta = value.rotation.angle_z.degrees
            sigma_x = 0
            sigma_y = 0
            sigma_theta = 0
        else:
            x = value[0][0,0]
            y = value[0][1,0]
            theta = value[1] * 180/pi
            sigma_x = sqrt(value[2][0,0])
            sigma_y = sqrt(value[2][1,1])
            sigma_theta = sqrt(value[2][2,2])*180/pi
        if key.startswith('Aruco-'):
            print('  Aruco marker %s' % key[6:], end='')
        elif key.startswith('Wall-'):
            print('  Wall %s' % key[5:], end='')
        elif key.startswith('Cube-'):
            print('  Cube %s' % key[5:], end='')
        else:
            print('  %r' % key, end='')
        print(' at (%6.1f, %6.1f) @ %4.1f deg    +/- (%4.1f,%4.1f)  +/- %3.1f deg' %
              (x, y, theta, sigma_x, sigma_y, sigma_theta))
    print()


def show_objects():
    objs = robot.world.world_map.objects
    print('%d object%s in the world map:' %
          (len(objs), '' if len(objs) == 1 else 's'))
    sorted_keys = sort_wmobject_ids(objs.keys())
    for key in sorted_keys:
        print('  ', objs[key])
    print()


def show_particle(args):
    if len(args) == 0:
        particle = robot.world.particle_filter.best_particle
        particle_number = particle.index
    elif len(args) > 1:
        print('Usage:  show particle [number]')
        return
    else:
        try:
            particle_number = int(args[0])
            particle = robot.world.particle_filter.particles[particle_number]
        except ValueError:
            print('Usage:  show particle [number]')
            return
        except IndexError:
            print('Particle number must be between 0 and',
                  len(robot.world.particle_filter.particles)-1)
            return
    print ('Particle %s:  x=%6.1f  y=%6.1f  theta=%6.1f deg   log wt=%f [%.25f]' %
           (particle_number, particle.x, particle.y, particle.theta*180/pi,
            particle.log_weight, particle.weight))
    if len(particle.landmarks) > 0:
        print('Landmarks:')
        show_landmarks_helper(particle.landmarks)
    else:
        print()


def show_camera(args):
    if len(args) != 1:
        print('Usage:  show camera n, where n is a camera number, typically 0 or 1.')
        return
    try:
        cam = int(args[0])
    except ValueError:
        show_camera()
    robot.world.perched.check_camera(cam)


def do_reload(module_name):
    the_module = None
    try:
        the_module = reload(sys.modules[module_name])
    except KeyError:
        print("Module '%s' isn't loaded." % module_name)
    except: raise
    if the_module:
        print(the_module)
    print()


def start_stuff(args):
    spec = args[0] if len(args) > 0 else ""
    if spec == 'perched':
        try:
            cams = [int(x) for x in args[1:]]
        except:
            print('Usage: start perched [camera_number...]')
            return
        robot.world.perched.start_perched_camera_thread(cams)
    elif spec == 'server':
        robot.world.server.start_server_thread()
    elif spec == 'client':
        if len(args) != 2:
            print('Usage: start client IP_address')
            return
        robot.world.client.start_client_thread(args[1])
    elif spec == 'shared_map':
        robot.world.client.use_shared_map()
        print('Now using shared map.')
    else:
        print("""Usage:
  start perched
  start server
  start client [IP_Address]
  start shared_map
""")


def cli_loop(robot):
    global RUNNING

    cli_globals = globals()
    cli_globals['world'] = robot.world
    cli_globals['light_cube'] = world.light_cube
    cli_globals['charger'] = robot.world.charger
    cli_globals['ans'] = None

    running_fsm = vector_fsm.program.running_fsm = \
        StateMachineProgram(cam_viewer=False, simple_cli_callback=simple_cli_callback)
    cli_globals['running_fsm'] = running_fsm
    running_fsm.start()

    cli_loop._console = code.InteractiveConsole()
    while True:
        if RUNNING == False:
            return
        cli_loop._line = ''
        while cli_loop._line == '':
            readline.write_history_file(histfile)
            try:
                if os_version == 'Darwin':   # Tkinter breaks console on Macs
                    print('C> ', end='')
                    cli_loop._line = sys.stdin.readline().strip()
                else:
                    cli_loop._line = cli_loop._console.input('VectorCLI>>> ').strip()
            except KeyboardInterrupt:
                process_interrupt()
                continue
            except EOFError:
                print("EOF.\nType 'exit' to exit.\n")
                continue
            try:
                robot.kine.get_pose()
            except: pass
        if cli_loop._line[0] == '!':
            do_shell_command(cli_loop._line[1:])
            continue
        elif cli_loop._line[0:3] == 'tm ' or cli_loop._line == 'tm':
            text_message(cli_loop._line[3:])
            continue
        elif cli_loop._line[0:5] == 'show ' or cli_loop._line == 'show':
            show_args = cli_loop._line[5:].split(' ')
            show_stuff(show_args)
            continue
        elif cli_loop._line[0:7] == 'reload ':
            do_reload(cli_loop._line[7:])
            continue
        elif cli_loop._line[0:6] == 'start ' or cli_loop._line == 'start':
            start_args = cli_loop._line[6:].split(' ')
            start_stuff(start_args)
            continue
        cli_loop._do_await = False
        if cli_loop._line[0:7] == 'import ' or cli_loop._line[0:5] == 'from '  or \
               cli_loop._line[0:7] == 'global ' or cli_loop._line[0:4] == 'del '   or \
               cli_loop._line[0:4] == 'for ' or \
               cli_loop._line[0:4] == 'def '    or cli_loop._line[0:6] == 'async ' :
            # Can't use assignment to capture a return value, so None.
            ans = None
        elif cli_loop._line[0:6] == 'await ':
            cli_loop._do_await = True
            cli_loop._line = 'ans=' + cli_loop._line[6:]
        elif cli_loop._line[0:5] == 'exit':
            # Clean up
            try:
                world_viewer.exited = True
            except: pass
            if running_fsm:
                running_fsm.stop()
            RUNNING=False
        else:
            cli_loop._line = 'ans=' + cli_loop._line
        try:
            cli_globals['charger'] = robot.world.charger  # charger may have appeared
            exec(cli_loop._line, cli_globals)
            if cli_loop._do_await:
                print("Can't use await outside of an async def.")
                ans = None # ans = await ans
            if not ans is None:
                print(ans,end='\n\n')
        except KeyboardInterrupt:
            print('Keyboard interrupt!')
        except SystemExit:
            print('Type exit() again to exit Python.')
            RUNNING = False
        except Exception:
            traceback.print_exc()
            print()


def main():
    args = anki_vector.util.parse_command_args()
    with anki_vector.Robot(args.serial) as robot:
        cli_loop(robot)


def process_interrupt():
    robot.stop_all_motors()
    running_fsm = vector_fsm.program.running_fsm
    if running_fsm and running_fsm.running:
        print('\nKeyboardInterrupt: stopping', running_fsm.name)
        running_fsm.stop()
    else:
        print("\nKeyboardInterrupt. Type 'exit' to exit.")


if __name__ == "__main__":
    setup()
    main()
