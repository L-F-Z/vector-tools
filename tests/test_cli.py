#!/usr/bin/env python3

"""Hello World

Make Vector say 'Hello World' in this simple Vector SDK example program.
"""

import readline
import sys, os
import atexit
import code
import datetime
import logging
import platform
import re
import rlcompleter
import subprocess
import time
import traceback
from importlib import __import__, reload

import anki_vector
from anki_vector import *
from anki_vector.util import *

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
    del rlcompleter

    os_version = platform.system()
    del platform

    # Put current directory on search path.
    if '.' not in sys.path:
        sys.path.append('.')

    res = 0
    ans = None

    RUNNING = True


def cli_loop(robot):
    global RUNNING

    cli_globals = globals()
    cli_globals['world'] = robot.world
    cli_globals['light_cubes'] = world.light_cubes
    cli_globals['cube'] = light_cubes[vector.objects.LightCubeId]
    cli_globals['charger'] = robot.world.charger
    cli_globals['ans'] = None

    running_fsm = vector_fsm.program.running_fsm = \
        StateMachineProgram(cam_viewer=False, simple_cli_callback=simple_cli_callback)

    



def main():
    args = anki_vector.util.parse_command_args()
    with anki_vector.Robot(args.serial) as robot:
        while(True):
            cmd = input(">>> ")
            try:
                exec(cmd)
            except:
                print("Command not understood")
                continue


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
