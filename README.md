### This is a project for CMU 15494/694 course, developed by Aravind Vadali and Fengzhi Li. Special thanks to Professor Dave Touretzky who developed cozmo-tools https://github.com/touretzkyds/cozmo-tools.

# vector-tools

For a radically different approach to Vector programming more suited to beginners, try Calypso at https://Calypso.software

## Tools for programming Anki's Vector robot via the Python SDK.

* __simple_cli__ provides a _Command Line Interface_ for the Vector SDK
so you can evaluate expressions in the context of an active SDK connection
to a robot. It also provides a variety of visualization tools, such as a
camera viewer, worldmap viewer, particle viewer, and path viewer.
Run it by typing: `python3 simple_cli`

* __event_monitor.py__ provides Vector event monitoring.
Type `monitor(robot)` to start monitoring.  See doc for more options.

* __vector_fsm__ is a Finite State Machine package for Vector programming.

* __genfsm__ is a preprocessor that converts .fsm files written in
the vector_fsm notation to .py files that are ready to run.

__Note__: you can install all the python dependencies by running `pip3 install -r requirements.txt`

