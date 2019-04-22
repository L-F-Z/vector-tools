"""

Event Monitor Tool for Vector
============================

Usage:
    monitor(robot) to monitor all event types in the dispatch table
    monitor(robot, Event) to monitor a specific type of event

    unmonitor(robot[, Event]) to turn off monitoring

Author: David S. Touretzky, Carnegie Mellon University
=====

ChangeLog
=========

*   Add event handlers to world instead of to robot.
        Dave Touretzky
            - Many events (e.g. face stuff) aren't reliably sent to robot.

*   Renaming and more face support
        Dave Touretzky
            - Renamed module to event_monitor
            - Renamed monitor_on/off to monitor/unmonitor
            - Added monitor_face to handle face events

*   Created
        Dave Touretzky

"""

import re

import vector


def print_prefix(evt):
    robot.world.last_event = evt
    print('-> ', evt.event_name, ' ', sep='', end='')


def print_object(obj):
    if isinstance(obj,vector.objects.LightCube):
        cube_id = next(k for k,v in robot.world.light_cubes.items() if v==obj)
        print('LightCube-',cube_id,sep='',end='')
    else:
        r = re.search('<(\w*)', obj.__repr__())
        print(r.group(1), end='')


def monitor_generic(evt, **kwargs):
    print_prefix(evt)
    if 'behavior_type_name' in kwargs:
        print(kwargs['behavior_type_name'], '', end='')
        print(' ', end='')
    if 'obj' in kwargs:
        print_object(kwargs['obj'])
        print(' ', end='')
    if 'action' in kwargs:
        action = kwargs['action']
        if isinstance(action, vector.anim.Animation):
            print(action.anim_name, '', end='')
        elif isinstance(action, vector.anim.AnimationTrigger):
            print(action.trigger.name, '', end='')
    print(set(kwargs.keys()))


def monitor_EvtActionCompleted(evt, action, state, failure_code, failure_reason, **kwargs):
    print_prefix(evt)
    print_object(action)
    if isinstance(action, vector.anim.Animation):
        print('', action.anim_name, end='')
    elif isinstance(action, vector.anim.AnimationTrigger):
        print('', action.trigger.name, end='')
    print('',state,end='')
    if failure_code is not None:
        print('',failure_code,failure_reason,end='')
    print()


def monitor_EvtObjectTapped(evt, *, obj, tap_count, tap_duration, tap_intensity, **kwargs):
    print_prefix(evt)
    print_object(obj)
    print(' count=', tap_count,
          ' duration=', tap_duration, ' intensity=', tap_intensity, sep='')


def monitor_EvtObjectMovingStarted(evt, *, obj, acceleration, **kwargs):
    print_prefix(evt)
    print_object(obj)
    print(' accleration=', acceleration, sep='')


def monitor_EvtObjectMovingStopped(evt, *, obj, move_duration, **kwargs):
    print_prefix(evt)
    print_object(obj)
    print(' move_duration=%3.1f secs' %move_duration)


def monitor_face(evt, face, **kwargs):
    print_prefix(evt)
    name = face.name if face.name is not '' else '[unknown face]'
    expr = face.expression if face.expression is not None else 'expressionless'
    kw = set(kwargs.keys()) if len(kwargs) > 0 else '{}'
    print(name, ' (%s) ' % expr, ' face_id=', face.face_id, '  ', kw, sep='')

dispatch_table = {
  vector.action.EvtActionStarted        : monitor_generic,
  vector.action.EvtActionCompleted      : monitor_EvtActionCompleted,
  vector.behavior.EvtBehaviorStarted    : monitor_generic,
  vector.behavior.EvtBehaviorStopped    : monitor_generic,
  vector.anim.EvtAnimationsLoaded       : monitor_generic,
  vector.anim.EvtAnimationCompleted     : monitor_EvtActionCompleted,
  vector.objects.EvtObjectAppeared      : monitor_generic,
  vector.objects.EvtObjectDisappeared   : monitor_generic,
  vector.objects.EvtObjectMovingStarted : monitor_EvtObjectMovingStarted,
  vector.objects.EvtObjectMovingStopped : monitor_EvtObjectMovingStopped,
  vector.objects.EvtObjectObserved      : monitor_generic,
  vector.objects.EvtObjectTapped        : monitor_EvtObjectTapped,
  vector.faces.EvtFaceAppeared          : monitor_face,
  vector.faces.EvtFaceObserved          : monitor_face,
  vector.faces.EvtFaceDisappeared       : monitor_face,
}

excluded_events = {    # Occur too frequently to monitor by default
    vector.objects.EvtObjectObserved,
    vector.faces.EvtFaceObserved,
}


def monitor(_robot, evt_class=None):
    if not isinstance(_robot, vector.robot.Robot):
        raise TypeError('First argument must be a Robot instance')
    if evt_class is not None and not issubclass(evt_class, vector.event.Event):
        raise TypeError('Second argument must be an Event subclass')
    global robot
    robot = _robot
    if evt_class in dispatch_table:
        robot.world.add_event_handler(evt_class,dispatch_table[evt_class])
    elif evt_class is not None:
        robot.world.add_event_handler(evt_class,monitor_generic)
    else:
        for k,v in dispatch_table.items():
            if k not in excluded_events:
                robot.world.add_event_handler(k,v)


def unmonitor(_robot, evt_class=None):
    if not isinstance(_robot, vector.robot.Robot):
        raise TypeError('First argument must be a Robot instance')
    if evt_class is not None and not issubclass(evt_class, vector.event.Event):
        raise TypeError('Second argument must be an Event subclass')
    global robot
    robot = _robot
    try:
        if evt_class in dispatch_table:
            robot.world.remove_event_handler(evt_class,dispatch_table[evt_class])
        elif evt_class is not None:
            robot.world.remove_event_handler(evt_class,monitor_generic)
        else:
            for k,v in dispatch_table.items():
                robot.world.remove_event_handler(k,v)
    except Exception:
        pass

