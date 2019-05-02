#!/usr/bin/env python3

"""
Aravind and Fengzhi's 15-694 Final Project: Make Vector Great Again
"""

import anki_vector
from anki_vector import *
from anki_vector.util import *
import subprocess
import shlex
import functools
import time
import readline
import sys, os
import atexit
import code
import datetime
import logging
import platform
import re
import traceback
from collections import namedtuple
from importlib import __import__, reload
import concurrent.futures
import pdb
from pdb import break_on_setattr
from NewFSM import NewFSM
from NewFSM.NewFSM import *

# robot = None
RUNNING = False
histfile = None
running_fsm = None


"""
FSM STUFF
"""

def setup():
    global RUNNING, histfile
    robot = NewFSM.robot
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

    # del platform

    # Put current directory on search path.
    if '.' not in sys.path:
        sys.path.append('.')

    res = 0
    ans = None

    RUNNING = True

def runfsm(module_name, running_modules=dict()):
    """runfsm('modname') reloads that module and expects it to contain
    a class of the same name. It calls that class's constructor and then
    calls the instance's start() method."""

    global running_fsm
    robot = NewFSM.robot
    if running_fsm:
        stopAllMotors()
        running_fsm.stop()

    r_py = re.compile('.*\.py$')
    if r_py.match(module_name):
        print("\n'%s' is not a module name. Trying '%s' instead.\n" %
              (module_name, module_name[0:-3]))
        module_name = module_name[0:-3]

    found = False
    try:
        reload(running_modules[module_name])
        found = True
    except KeyError: pass
    except: raise
    if not found:
        try:
            running_modules[module_name] = __import__(module_name)
        except ImportError as e:
            print("Error loading %s: %s.  Check your search path.\n" %
                  (module_name,e))
            return
        except Exception as e:
            print('\n===> Error loading %s:' % module_name)
            raise

    py_filepath = running_modules[module_name].__file__
    fsm_filepath = py_filepath[0:-2] + 'fsm'
    try:
        py_time = datetime.datetime.fromtimestamp(os.path.getmtime(py_filepath))
        fsm_time = datetime.datetime.fromtimestamp(os.path.getmtime(fsm_filepath))
        if py_time < fsm_time:
            cprint('Warning: %s.py is older than %s.fsm. Should you run genfsm?' %
                   (module_name,module_name), color="yellow")
    except: pass

    # The parent node class's constructor must match the module name.
    the_module = running_modules[module_name]
    the_class = the_module.__getattribute__(module_name) \
                if module_name in dir(the_module) else None
    # if not isinstance(the_class,type) or not issubclass(the_class,StateNode):
    #     cprint("Module %s does not contain a StateNode class named %s.\n" %
    #           (module_name, module_name), color="red")
    #     return       
    # print("StateMachineProgram robot in runfsm: {}".format(StateMachineProgram.robot))
    running_fsm = the_class()
    the_module.robot = robot
    the_module.world = the_module.robot.world
    the_module.charger = the_module.robot.world.charger
    the_module.cube = the_module.robot.world.connected_light_cube
    # StateMachineProgram.robot = robot
    # Class's __init__ method will call setup, which can reference the above variables.
    running_fsm.robot = robot
    cli_globals = globals()
    cli_globals['running_fsm'] = running_fsm
    robot.conn.loop.call_soon(running_fsm.start)
    return running_fsm   

def cli_loop():
    global RUNNING, histfile, ans, running_fsm
    robot = NewFSM.robot
    cli_globals = globals()
    cli_globals['world'] = robot.world
    cli_globals['light_cube'] = world.light_cube
    cli_globals['charger'] = robot.world.charger
    cli_globals['ans'] = None

    cli_globals['running_fsm'] = running_fsm
    # running_fsm.start()

    cli_loop._console = code.InteractiveConsole()
    cli_loop.battery_warned = False

    # MAIN LOOP
    while True:
        # Check for low battery
        battery_state = robot.get_battery_state().result()
        if not cli_loop.battery_warned and battery_state.battery_level == 1:
            cli_loop.battery_warned = True
            print("\n** Low battery. Type robot.behavior.drive_on_charger() to recharge.")
        elif cli_loop.battery_warned and battery_state.battery_level == 2:
            cli_loop.battery_warned = False

        # If we're not supposed to be running, get out
        if RUNNING == False:
            return

        # Main line reader
        cli_loop._line = ''
        while cli_loop._line == '':
            readline.write_history_file(histfile)
            try:
                os_version = platform.system()
                if os_version == 'Darwin':   # Tkinter breaks console on Macs
                    print('VectorCLI>>> ', end='')
                    cli_loop._line = sys.stdin.readline().strip()
                else:
                    cli_loop._line = cli_loop._console.raw_input('VectorCLI>>> ').strip()
            except KeyboardInterrupt:
                process_interrupt()
                continue
            except EOFError:
                print("EOF.\nType 'exit' to exit.\n")
                continue

            try:
                robot.kine.get_pose()
            except: pass

        # ! means repeat last command
        if cli_loop._line[0] == '!':
            do_shell_command(cli_loop._line[1:])
            continue
        # # tm means send a text message (not yet implemented in our system)
        # elif cli_loop._line[0:3] == 'tm ' or cli_loop._line == 'tm':
        #     text_message(cli_loop._line[3:])
        #     continue
        # show means show a type of visualization. not implemented by us
        # elif cli_loop._line[0:5] == 'show ' or cli_loop._line == 'show':
        #     show_args = cli_loop._line[5:].split(' ')
        #     show_stuff(show_args)
        #     continue
        # Reload this cli program
        elif cli_loop._line[0:7] == 'reload ':
            do_reload(cli_loop._line[7:])
            continue
        # Start something
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
            robot.disconnect()
        except SystemExit:
            print('Type exit() again to exit Python.')
            robot.disconnect()
            RUNNING = False
        except Exception:
            # robot.disconnect()
            traceback.print_exc()
            print()

def main():
    args = anki_vector.util.parse_command_args()
    # with anki_vector.AsyncRobot(args.serial, show_viewer=True, show_3d_viewer=True) as async_robot:
    robot = anki_vector.AsyncRobot(args.serial, show_viewer=True, show_3d_viewer=True)
    robot.connect()
    NewFSM.robot = robot
    # forward = Forward()
    # turn = Turn()
    # backward = Forward(-50)
    # speak = Say("Hi There")
    # takepic = TakePicture()
    # speak2 = Say("All done")
    # declare_failure = Say("I have failed but I am still the best")
    # displaypic = DisplayImageOnMonitor()
    # screenpic = DisplayImageOnScreen()
    # complete1 = CompletionTrans().add_sources(forward).add_destinations(turn)
    # complete2 = CompletionTrans().add_sources(turn).add_destinations(backward, speak)
    # complete3 = CompletionTrans().add_sources(speak).add_destinations(takepic)
    # dataTrans = DataTrans().add_sources(takepic).add_destinations(displaypic, screenpic)
    # timeTrans = TimeTrans(10).add_sources(displaypic).add_destinations(speak2)
    # failureTrans = FailureTrans().add_sources(forward, turn, backward, speak, takepic, speak2).add_destinations(declare_failure)
    # forward.start()
    setup()
    cli_loop()
    robot.disconnect()


if __name__ == "__main__":
    main()

