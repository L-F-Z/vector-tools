import time
import asyncio
import inspect
import types
import random
import numpy as np
import math
from math import pi
import cv2

import anki_vector
from anki_vector.util import distance_mm, speed_mmps, degrees, Distance, Angle, Pose

from .base import *
from .events import *
from .vector_kin import wheelbase
from .transform import wrap_angle
from .worldmap import WorldObject, FaceObj, CustomMarkerObj

#________________ Ordinary Nodes ________________

def stopAllMotors(robot):
    robot.motors.set_lift_motor(0)
    robot.motors.set_wheel_motors(0, 0)

class ParentCompletes(StateNode):
    def start(self,event=None):
        super().start(event)
        if TRACE.trace_level > TRACE.statenode_startstop:
            print('TRACE%d:' % TRACE.statenode_startstop,
                  '%s is causing %s to complete' % (self, self.parent))
        if self.parent:
            self.parent.post_completion()

class ParentSucceeds(StateNode):
    def start(self,event=None):
        super().start(event)
        if TRACE.trace_level > TRACE.statenode_startstop:
            print('TRACE%d:' % TRACE.statenode_startstop,
                  '%s is causing %s to succeed' % (self, self.parent))
        if self.parent:
            self.parent.post_success()

class ParentFails(StateNode):
    def start(self,event=None):
        super().start(event)
        if TRACE.trace_level > TRACE.statenode_startstop:
            print('TRACE%d:' % TRACE.statenode_startstop,
                  '%s is causing %s to fail' % (self, self.parent))
        if self.parent:
            self.parent.post_failure()

class Iterate(StateNode):
    """Iterates over an iterable, posting DataEvents.  Completes when done."""
    def __init__(self,iterable=None):
        super().__init__()
        self.iterable = iterable

    class NextEvent(Event): pass

    def start(self,event=None):
        if self.running: return
        super().start(event)
        if isinstance(event, DataEvent):
            self.iterable = event.data
        if isinstance(self.iterable, int):
            self.iterable = range(self.iterable)
        if self.iterable is None:
            raise ValueError('~s has nothing to iterate on.' % repr(self))
        if not isinstance(event, self.NextEvent):
            self.iterator = self.iterable.__iter__()
        try:
            value = next(self.iterator)
        except StopIteration:
            self.post_completion()
            return
        self.post_data(value)

class MoveLift(StateNode):
    "Move lift at specified speed."
    def __init__(self,speed):
        super().__init__()
        self.speed = speed

    def start(self,event=None):
        if self.running: return
        super().start(event)
        # Temporary hack supplied by Mark Wesley at Anki
        msg = anki_vector._clad._clad_to_engine_iface.EnableLiftPower(True)
        self.robot.conn.send_msg(msg)
        self.robot.motors.set_lift_motor(self.speed)

    def stop(self):
        if not self.running: return
        self.robot.motors.set_lift_motor(0)
        super().stop()

class RelaxLift(StateNode):
    def start(self,event=None):
        if self.running: return
        super().start(event)
        # Temporary hack supplied by Mark Wesley at Anki
        self.robot.motors.set_lift_motor(0)
        self.robot.conn.send_msg(msg)

# class SetLights(StateNode):
#     def __init__(self, object, light):
#         super().__init__()
#         self.object = object
#         self.light = light

#     def start(self,event=None):
#         super().start(event)
#         if self.object is not self.robot:
#             self.object.set_lights(self.light)
#         else:
#             if self.light.on_color.int_color & 0x00FFFF00 == 0: # no green or blue component
#                 self.robot.set_all_backpack_lights(self.light)
#             else:
#                 self.robot.set_backpack_lights_off()
#                 self.robot.set_center_backpack_lights(self.light)
#         self.post_completion()

class DriveContinuous(StateNode):
    def __init__(self,path=[]):
        self.path = path
        self.polling_interval = 0.05
        self.handle = None
        super().__init__()

    def start(self,event=None):
        if isinstance(event, DataEvent) and isinstance(event.data,(list,tuple)):
            self.path = event.data
        if len(self.path) == 0:
            raise ValueError('Node %s has a null path' % repr(self))
        self.path_index = 0
        self.cur = self.path[self.path_index]
        self.last_dist = -1
        self.reached_dist = False
        self.mode = None
        self.pause_counter = 0
        self.handle = None
        super().start(event)

    def stop(self):
        if self.handle:
            self.handle.cancel()
        stopAllMotors(self.robot)
        super().stop()

    def poll(self):
        # Quit if the robot is picked up.
        if self.robot.is_picked_up:
            print('** Robot was picked up.')
            stopAllMotors(self.robot)
            self.post_failure()
            return
        # See where we are, and if we've passed the current waypoint.
        x = self.robot.world.particle_filter.pose[0]
        y = self.robot.world.particle_filter.pose[1]
        q = self.robot.world.particle_filter.pose[2]
        dist = math.sqrt((self.cur[0]-x)**2 + (self.cur[1]-y)**2)
        if self.pause_counter > 0:
            self.pause_counter -= 1
            #print('p.. x: %5.1f  y: %5.1f  q:%6.1f     dist: %5.1f' %
            #      (x, y, q*180/pi, dist))
            return
        if not self.reached_dist:
            self.reached_dist = \
                (dist - self.last_dist) > 0.1 and \
                ( (self.mode == 'x' and np.sign(x-self.cur[0]) == np.sign(self.cur[0]-self.prev[0])) or
                  (self.mode == 'y' and np.sign(y-self.cur[1]) == np.sign(self.cur[1]-self.prev[1])) )
        # Once reached_dist is true, we can enter mode 'q' where we'll turn  until
        # the heading error is < 5 degrees, then we've reached the waypoint.
        reached_waypoint = (self.path_index == 0) or \
                           (self.reached_dist and \
                            abs(wrap_angle(q - self.target_q)) < 5*pi/180)
        self.last_dist = dist

        # Advance to next waypoint if indicated
        if reached_waypoint:
            self.path_index += 1
            print('DriveContinuous: current position is (%.1f, %.1f) @ %.1f deg.' %
                  (x, y, q*180/pi))
            print('   path index advanced to %d' % self.path_index, end='')
            if self.path_index == len(self.path):
                print('\nDriveContinous: path complete.  Stopping.')
                stopAllMotors(self.robot)
                self.post_completion()
                return
            elif self.path_index > len(self.path):
                # uncaught completion event
                print('\nDriveContinuous: uncaught completion! Stopping.')
                self.stop()
                return
            self.prev = self.cur
            self.cur = self.path[self.path_index]
            self.last_dist = math.inf
            self.reached_dist = False
            self.target_q = math.atan2(self.cur[1]-self.prev[1], self.cur[0]-self.prev[0])
            print(': [%.1f, %.1f] tgtQ is %.1f deg.' % (*self.cur, self.target_q*180/pi))

            # Is the target behind us?
            delta_q = wrap_angle(self.target_q - q)
            delta_dist = math.sqrt((self.cur[0]-x)**2 + (self.cur[1]-y)**2)
            if False and abs(delta_q) > 135*pi/180:
                #self.target_q = wrap_angle(self.target_q + pi)
                self.drive_direction = -1
                print('Driving backwards --> delta_q = %.1f deg., new target_q = %.1f deg., dist = %.1f' %
                      (delta_q*180/pi, self.target_q*180/pi, delta_dist))
            else:
                self.drive_direction = +1

            # Heading determines whether we're solving y=f(x) or x=f(y)
            if abs(self.target_q) < pi/4 or abs(abs(self.target_q)-pi) < pi/4:
                self.mode = 'x'
                self.m = (self.cur[1]-self.prev[1]) / (self.cur[0]-self.prev[0])
                self.b = self.cur[1] - self.m * (self.cur[0]-self.prev[0])
            else:
                self.mode = 'y'
                self.m = (self.cur[0]-self.prev[0]) / (self.cur[1]-self.prev[1])
                self.b = self.cur[0] - self.m * (self.cur[1]-self.prev[1])

            # Do we need to turn in place before setting off toward new waypoint?
            if abs(wrap_angle(q-self.target_q)) > 45*pi/180:
                self.saved_mode = self.mode
                self.mode = 'q'
                print('DriveContinuous: turning to %.1f deg. before driving to waypoint.' %
                      (self.target_q*180/pi))

            if self.path_index > 1:
                # come to a full stop before trying to change direction
                stopAllMotors(self.robot)
                self.pause_counter = 5
                return

        # Haven't reached waypoint yet
        elif self.reached_dist:
            # But we have traveled far enough, so come to a stop and then fix heading
            if self.mode != 'q':
                stopAllMotors(self.robot)
                self.robot.pause_counter = 5
                self.mode = 'q'  # We're there; now fix our heading
                if abs(wrap_angle(q-self.target_q)) > 5*pi/180:
                    print('DriveContinuous: waypoint reached; adjusting heading to %.1f deg.' %
                          (self.target_q*180/pi))
                return
        elif self.mode == 'q' and abs(wrap_angle(q-self.target_q)) < 5*pi/180:
            print('DriveContinuous: turn to heading complete: heading is %.1f deg.' %
                  (q*180/pi))
            self.mode = self.saved_mode

        # Calculate error and correction based on present x/y/q position
        q_error = wrap_angle(q - self.target_q)
        #print('DriveCont--> q_error is',q*180/pi,'degrees')
        if self.mode == 'x':      # y = f(x)
            target_y = self.m * (x-self.prev[0]) + self.b
            d_error = (y - target_y) * np.sign(pi/2 - abs(self.target_q))
            correcting_q = - 0.8*q_error - 0.25*math.atan2(d_error,25)
        elif self.mode == 'y':    # x = f(y)
            target_x = self.m * (y-self.prev[1]) + self.b
            d_error = (x - target_x) * np.sign(pi/2 - abs(self.target_q-pi/2))
            correcting_q = - 0.8*q_error - 0.25*math.atan2(-d_error,25)
        elif self.mode == 'q':
            d_error = math.sqrt((x-self.cur[0])**2 + (y-self.cur[1])**2)
            correcting_q = - 0.8*q_error
        else:
            print("Bad mode value '%s'" % repr(self.mode))
            return

        # Calculate wheel speeds based on correction value
        if self.mode == 'q' or abs(q_error*180/pi) >= 10:
            # For large heading error, turn in place
            speed = 0
            qscale = 50
            correcting_q = - 1.0 * np.sign(q_error) * max(abs(q_error), 25*pi/180)
            flag = "<>"
        elif abs(q_error*180/pi) > 5 and abs(d_error) < 100:
            # For moderate heading error where  distance error isn't huge,
            # slow down and turn more slowly
            speed = 20
            qscale = 75
            flag = "**"
        else:
            # We're doing pretty well; go fast and make minor corrections
            speed = 100
            qscale = 150
            flag = "  "
        speedinc = qscale * correcting_q
        lspeed = self.drive_direction * (speed - self.drive_direction*speedinc)
        rspeed = self.drive_direction * (speed + self.drive_direction*speedinc)

        """print('%s x: %5.1f  y: %5.1f  q:%6.1f     derr: %5.1f  qerr:%6.1f  corq: %5.1f  inc: %5.1f  dist: %5.1f' %
              (self.mode+flag, x, y, q*180/pi, d_error, q_error*180/pi,
               correcting_q*180/pi, speedinc, dist))
        """
        self.robot.motors.set_wheel_motors(lspeed, rspeed, 200, 200)

class LookAtObject(StateNode):
    "Continuously adjust head angle to fixate object."
    def __init__(self):
        super().__init__()
        self.object = None
        self.handle = None

    def start(self,event=None):
        self.set_polling_interval(0.1)
        self.handle = None
        super().start()

    def stop(self):
        if self.handle:
            self.handle.cancel()
        super().stop()

    def poll(self):
        if isinstance(self.object, FaceObj) or isinstance(self.object, CustomMarkerObj):
            image_box =  self.object.sdk_obj.last_observed_image_box
            camera_center = self.robot.camera.config.center.y
            delta = image_box.top_left_y + image_box.height/2 - camera_center
            adjust_level = 0.1
            if self.robot.status.are_wheels_moving:
                adjust_level = 0.2
            if delta > 15:
                angle = self.robot.head_angle_rad - adjust_level
            elif delta < -15:
                angle = self.robot.head_angle_rad + adjust_level
            else:
                angle = self.robot.head_angle_rad
            angle = anki_vector.robot.behavior.MAX_HEAD_ANGLE.radians if angle > anki_vector.robot.behavior.MAX_HEAD_ANGLE.radians else angle
            angle = anki_vector.robot.behavior.MIN_HEAD_ANGLE.radians if angle < anki_vector.robot.behavior.MIN_HEAD_ANGLE.radians else angle
        else:
            if isinstance(self.object, WorldObject):
                rpose = self.robot.world.particle_filter.pose
                dx = self.object.x - rpose[0]
                dy = self.object.y - rpose[1]
            else:
                opos = self.object.pose.position
                rpos = self.robot.pose.position
                dx = opos.x - rpos.x
                dy = opos.y - rpos.y
            dist = math.sqrt(dx**2 + dy**2)
            if dist < 60:
                angle = -0.4
            elif dist < 80:
                angle = -0.3
            elif dist < 100:
                angle = -0.2
            elif dist < 140:
                angle = -0.1
            elif dist < 180:
                angle = 0
            else:
                angle = 0.1
        if abs(self.robot.head_angle_rad - angle) > 0.03:
            self.handle = self.robot.conn.loop.call_soon(self.move_head, angle)

    def move_head(self,angle):
        try:
            self.robot.behavior.set_head_angle(anki_vector.util.radians(angle), num_retries=2)
        except anki_vector.exceptions.VectorNotReadyException:
            print("LookAtObject: robot busy; can't move head to",angle)
            pass


class Print(StateNode):
    "Argument can be a string, or a function to be evaluated at print time."
    def __init__(self,spec=None):
        super().__init__()
        self.spec = spec

    def start(self,event=None):
        super().start(event)
        if isinstance(self.spec, types.FunctionType):
            text = self.spec()
        else:
            text = self.spec
        if text is None and isinstance(event, DataEvent):
            text = repr(event.data)
        print(text)
        self.post_completion()


# class AbortAllActions(StateNode):
#     def start(self,event=None):
#         super().start(event)
#         self.robot.abort_all_actions()
#         self.post_completion()


# class AbortHeadAction(StateNode):
#     def start(self,event=None):
#         super().start(event)
#         actionType = anki_vector._clad._clad_to_engine_vector.RobotActionType.UNKNOWN
#         msg = anki_vector._clad._clad_to_engine_iface.CancelAction(actionType=actionType)
#         self.robot.conn.send_msg(msg)
#         self.post_completion()


class StopAllMotors(StateNode):
    def start(self,event=None):
        super().start(event)
        stopAllMotors(self.robot)
        self.post_completion()


#________________ Color Images ________________

class ColorImageBase(StateNode):
    def __init__(self):
        pass


# class ColorImageEnabled(ColorImageBase):
#     """Turn color images on or off and post completion when setting has taken effect."""
#     def __init__(self,enabled=True):
#         self.enabled = enabled
#         super().__init__()

#     def start(self,event=None):
#         super().start(event)
#         if self.robot.camera.color_image_enabled == self.enabled:
#             self.post_completion()
#         else:
#             self.robot.camera.color_image_enabled = self.enabled
#             self.robot.world.add_event_handler(anki_vector.world.EvtNewCameraImage, self.new_image)

#     def new_image(self,event,**kwargs):
#         is_color = self.is_color(event.image)
#         if is_color:
#             self.robot.world.latest_color_image = event.image
#         if is_color == self.enabled:
#             self.robot.world.remove_event_handler(anki_vector.world.EvtNewCameraImage, self.new_image)
#             self.post_completion()


class GetColorImage(ColorImageBase):
    """Post one color image as a data event; leave color mode unchanged."""

    def start(self,event=None):
        super().start(event)
        self.post_data(self.robot.camera.latest_image)


class SaveImage(StateNode):
    "Save an image to a file."

    def __init__(self, filename="image", filetype="jpg", counter=0, verbose=True):
        super().__init__()
        self.filename = filename
        self.filetype = filetype
        self.counter = counter
        self.verbose = verbose

    def start(self,event=None):
        super().start(event)
        fname = self.filename
        if isinstance(self.counter, int):
            fname = fname + str(self.counter)
            self.counter = self.counter + 1
        fname = fname + "." + self.filetype
        image = np.array(self.robot.camera.latest_image.raw_image)
        cv2.imwrite(fname, cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        if self.verbose:
            print('Wrote',fname)


#________________ Coroutine Nodes ________________

class CoroutineNode(StateNode):
    def __init__(self):
        super().__init__()
        self.handle = None

    def start(self,event=None):
        super().start(event)
        cor = self.coroutine_launcher()
        if inspect.iscoroutine(cor):
            self.handle = self.robot.conn.loop.create_task(cor)
        elif cor is False:
            self.handle = None
        else:
            print('cor=',cor,'type=',type(cor))
            raise ValueError("Result of %s launch_couroutine() is %s, not a coroutine." %
                             (self,cor))

    def coroutine_launcher(self):
        raise Exception('%s lacks a coroutine_launcher() method' % self)

    def stop(self):
        if not self.running: return
        if self.handle: self.handle.cancel()
        super().stop()


class DriveWheels(CoroutineNode):
    def __init__(self,l_wheel_speed,r_wheel_speed,**kwargs):
        super().__init__()
        self.l_wheel_speed = l_wheel_speed
        self.r_wheel_speed = r_wheel_speed
        self.kwargs = kwargs

    def start(self,event=None):
        if (isinstance(event,DataEvent) and isinstance(event.data,(list,tuple)) and
                len(event.data) == 2):
            (lspeed,rspeed) = event.data
            if isinstance(lspeed,(int,float)) and isinstance(rspeed,(int,float)):
                self.l_wheel_speed = lspeed
                self.r_wheel_speed = rspeed
        super().start(event)

    def coroutine_launcher(self):
        return self.robot.motors.set_wheel_motors(self.l_wheel_speed,self.r_wheel_speed,**self.kwargs)

    def stop_wheels(self):
        try:
            driver = self.robot.motors.set_wheel_motors(0,0)
            # driver is either a co-routine or None
            if driver: driver.send(None)  # will raise StopIteration
        except StopIteration: pass

    def stop(self):
        if not self.running: return
        self.stop_wheels()
        super().stop()


class DriveForward(DriveWheels):
    def __init__(self, distance=50, speed=50, **kwargs):
        if isinstance(distance, anki_vector.util.Distance):
            distance = distance.distance_mm
        if isinstance(speed, anki_vector.util.Speed):
            speed = speed.speed_mmps
        if distance < 0:
            distance = -distance
            speed = -speed
        self.distance = distance
        self.speed = speed
        self.kwargs = kwargs
        super().__init__(speed,speed,**self.kwargs)
        self.polling_interval = 0.1

    def start(self,event=None):
        if self.running: return
        if isinstance(event, DataEvent) and isinstance(event.data, anki_vector.util.Distance):
            self.distance = event.data.distance_mm
        self.start_position = self.robot.pose.position
        super().start(event)

    def poll(self):
        """See how far we've traveled"""
        p0 = self.start_position
        p1 = self.robot.pose.position
        diff = (p1.x - p0.x, p1.y - p0.y)
        dist = math.sqrt(diff[0]*diff[0] + diff[1]*diff[1])
        if dist >= self.distance:
            self.poll_handle.cancel()
            self.stop_wheels()
            self.post_completion()

class SmallTurn(CoroutineNode):
    """Estimates how many polling cycles to run the wheels; doesn't use odometry."""
    def __init__(self, angle=5):
        self.angle = angle
        self.counter = 0
        self.polling_interval = 0.025
        super().__init__()

    def start(self,event=None):
        # constants were determined empirically for speed 50
        self.counter = round((abs(self.angle) + 5) / 1.25) if self.angle else 0
        super().start(event)

    def coroutine_launcher(self):
        if self.angle:
            speed = 50 if self.angle < 0 else -50
            return self.robot.motors.set_wheel_motors(speed,-speed,500,500)
        else:
            stopAllMotors(self.robot)
            return False

    def poll(self):
        self.counter -= 1
        if self.counter <= 0:
            self.poll_handle.cancel()
            stopAllMotors(self.robot)
            self.post_completion()

class DriveTurn(DriveWheels):
    def __init__(self, angle=90, speed=50, **kwargs):
        if isinstance(angle, anki_vector.util.Angle):
            angle = angle.degrees
        if isinstance(speed, anki_vector.util.Speed):
            speed = speed.speed_mmps
        if speed <= 0:
            raise ValueError('speed parameter must be positive')
        self.angle = angle
        self.speed = speed
        self.kwargs = kwargs
        self.polling_interval = 0.05
        super().__init__(0,0,**self.kwargs)

    def start(self,event=None):
        if self.running: return
        if isinstance(event, DataEvent) and isinstance(event.data, anki_vector.util.Angle):
            self.angle = event.data.degrees
        if self.angle > 0:
            self.l_wheel_speed = -self.speed
            self.r_wheel_speed = self.speed
        else:
            self.l_wheel_speed = self.speed
            self.r_wheel_speed = -self.speed
        self.last_heading = self.robot.pose.rotation.angle_z.degrees
        self.traveled = 0
        super().start(event)

    def poll(self):
        """See how far we've traveled"""
        p0 = self.last_heading
        p1 = self.robot.pose.rotation.angle_z.degrees
        self.last_heading = p1
        # Assume we're polling quickly enough that diff will be small;
        # typically only about 1 degree.  So diff will be large only
        # if the heading has passed through 360 degrees since the last
        # call to poll().  Use 90 degrees as an arbitrary large threshold.
        diff = p1 - p0
        if diff  < -90.0:
            diff += 360.0
        elif diff > 90.0:
            diff -= 360.0
        self.traveled += diff
        if abs(self.traveled) > abs(self.angle):
            self.poll_handle.cancel()
            self.stop_wheels()
            self.post_completion()


class DriveArc(DriveWheels):
    """Negative radius means right turn; negative angle means drive
    backwards.  This node can be passed a DataEvent with a dict
    containing any of the arguments accepted by __init__: radius,
    angle, distance, speed, and angspeed.  Values must already be in
    the appropriate units (degrees, mm, deg/sec, or mm/sec)."""
    def __init__(self, radius=0, angle=None, distance=None,
                 speed=None, angspeed=None, **kwargs):
        if isinstance(radius, anki_vector.util.Distance):
            radius = radius.distance_mm
        if isinstance(angle, anki_vector.util.Angle):
            angle = angle.degrees
        if isinstance(speed, anki_vector.util.Speed):
            speed = speed.speed_mmps
        if isinstance(angspeed, anki_vector.util.Angle):
            angspeed = angspeed.degrees
        self.calculate_wheel_speeds(radius, angle, distance, speed, angspeed)
        super().__init__(self.l_wheel_speed, self.r_wheel_speed, **kwargs)
        # Call parent init before setting polling interval.
        self.polling_interval = 0.05

    def calculate_wheel_speeds(self, radius=0, angle=None, distance=None,
                               speed=None, angspeed=None):
        if radius != 0:
            if angle is not None:
                pass
            elif distance is not None:
                angle = self.dist2ang(distance, radius)
            else:
                raise ValueError('DriveArc requires an angle or distance.')

            if  speed is not None:
                pass
            elif angspeed is not None:
                speed = self.ang2dist(angspeed, radius)
            else:
                speed = 40 # degrees/second
            if angle < 0:
                speed = - speed

            self.angle = angle
            self.l_wheel_speed = speed * (1 - wheelbase / radius)
            self.r_wheel_speed = speed * (1 + wheelbase / radius)

        else:  # radius is 0
            if angspeed is None:
                angspeed = 40 # degrees/second
            s = angspeed
            if angle < 0:
                s = -s
            self.angle = angle
            self.l_wheel_speed = -s
            self.r_wheel_speed = s

    def ang2dist(self, angle, radius):
        return (angle / 360) * 2 * pi * abs(radius)

    def dist2ang(self, distance, radius):
        return (distance / abs(2 * pi * radius)) * 360

    def start(self,event=None):
        if self.running: return
        if isinstance(event,DataEvent) and isinstance(event.data,dict):
            self.calculate_wheel_speeds(**event.data)
        self.last_heading = self.robot.pose.rotation.angle_z.degrees
        self.traveled = 0
        super().start(event)

    def poll(self):
        """See how far we've traveled"""
        p0 = self.last_heading
        p1 = self.robot.pose.rotation.angle_z.degrees
        self.last_heading = p1
        # Assume we're polling quickly enough that diff will be small;
        # typically only about 1 degree.  So diff will be large only
        # if the heading has passed through 360 degrees since the last
        # call to poll().  Use 90 degrees as an arbitrary large threshold.
        diff = p1 - p0
        if diff  < -90.0:
            diff += 360.0
        elif diff > 90.0:
            diff -= 360.0
        self.traveled += diff

        if abs(self.traveled) > abs(self.angle):
            self.poll_handle.cancel()
            self.stop_wheels()
            self.post_completion()


#________________ Action Nodes ________________

class ActionNode(StateNode):
    relaunch_delay = 0.050 # 50 milliseconds

    def __init__(self, abort_on_stop=True):
        """Call this method only after the subclass __init__ has set
        up self.action_kwargs"""
        self.abort_on_stop = abort_on_stop
        super().__init__()
        # if 'in_parallel' not in self.action_kwargs:
        #     self.action_kwargs['in_parallel'] = True
        if 'num_retries' not in self.action_kwargs:
            self.action_kwargs['num_retries'] = 2
        self.anki_vector_action_handle = None

    def start(self,event=None):
        super().start(event)
        self.retry_count = 0
        self.launch_or_retry()

    def launch_or_retry(self):
        result = self.action_launcher()
        # try:
        #     result = self.action_launcher()
        # except anki_vector.exceptions.VectorNotReadyException:
        #     if TRACE.trace_level >= TRACE.statenode_startstop:
        #         print('TRACE%d:' % TRACE.statenode_startstop, self, 'launch_action raised RobotBusy')
        #     self.handle = self.robot.conn.loop.call_later(self.relaunch_delay, self.launch_or_retry)
        #     return
        if str(result) == '':
            self.anki_vector_action_handle = result
        else: # Aborted
            print("result is not empty string: {}".format(result))
            return
        # else:
        #     raise ValueError("Result of %s launch_action() is %s, not a anki_vector.action.Action." %
        #                      (self,result))
        # self.post_completion()
        # self.post_when_complete()

    def action_launcher(self):
        raise Exception('%s lacks an action_launcher() method' % self)

    def post_when_complete(self):
       self.robot.conn.loop.create_task(self.wait_for_completion())

    async def wait_for_completion(self):
        async_task = self.anki_vector_action_handle.wait_for_completed()
        await async_task
        if TRACE.trace_level >= TRACE.await_satisfied:
            print('TRACE%d:' % TRACE.await_satisfied, self,
                  'await satisfied:', self.anki_vector_action_handle)
        # check status for 'completed'; if not, schedule relaunch or post failure
        if self.running:
            if self.anki_vector_action_handle.state == 'action_succeeded':
                self.post_completion()
            elif self.anki_vector_action_handle.failure_reason[0] == 'cancelled':
                print('CANCELLED: ***>',self,self.anki_vector_action_handle)
                self.post_completion()
            elif self.anki_vector_action_handle.failure_reason[0] == 'retry':
                if self.retry_count < self.action_kwargs['num_retries']:
                    print("*** ACTION %s of %s FAILED WITH CODE 'retry': TRYING AGAIN" %
                          (self.anki_vector_action_handle, self.name))
                    self.retry_count += 1
                    self.launch_or_retry()
                else:
                    print("*** %s ACTION RETRY COUNT EXCEEDED: FAILING" % self.name)
                    self.post_failure(self.anki_vector_action_handle)
            else:
                print("*** ACTION %s OF NODE %s FAILED DUE TO %s AND CAN'T BE RETRIED." %
                      (self.anki_vector_action_handle,
                       self.name,
                       self.anki_vector_action_handle.failure_reason[0] or 'unknown reason'))
                self.post_failure(self.anki_vector_action_handle)

    def stop(self):
        if not self.running: return
        if self.anki_vector_action_handle and self.abort_on_stop and \
                self.anki_vector_action_handle.is_running:
            self.anki_vector_action_handle.abort()
        super().stop()


class Say(ActionNode):
    """Speaks some text, then posts a completion event."""

    class SayDataEvent(Event):
        def __init__(self,text=None):
            self.text = text

    def __init__(self, text="I'm speechless",
                 abort_on_stop=False, **action_kwargs):
        self.text = text
        self.action_kwargs = action_kwargs
        super().__init__(abort_on_stop)

    def start(self,event=None):
        if self.running: return
        if isinstance(event, self.SayDataEvent):
            utterance = event.text
        else:
            utterance = self.text
        if isinstance(utterance, (list,tuple)):
            utterance = random.choice(utterance)
        if not isinstance(utterance, str):
            utterance = repr(utterance)
        self.utterance = utterance
        print("Speaking: '",utterance,"'",sep='')
        super().start(event)

    def action_launcher(self):
        if 'num_retries' in self.action_kwargs:
            num_retries = self.action_kwargs.pop('num_retries')
        resp = self.robot.say_text(self.utterance, **self.action_kwargs)
        print("Say node completed")
        self.action_kwargs['num_retries'] = num_retries
        self.post_completion()
        return '' #if str(resp.state) == '4' else 'ERROR'


class Forward(ActionNode):
    """ Moves forward a specified distance. Can accept a Distance as a Dataevent."""
    def __init__(self, distance=distance_mm(50),
                 speed=speed_mmps(50), abort_on_stop=True, **action_kwargs):
        if isinstance(distance, (int,float)):
            distance = distance_mm(distance)
        elif not isinstance(distance, anki_vector.util.Distance):
            raise ValueError('%s distance must be a number or a anki_vector.util.Distance' % self)
        if isinstance(speed, (int,float)):
            speed = speed_mmps(speed)
        elif not isinstance(speed, anki_vector.util.Speed):
            raise ValueError('%s speed must be a number or a anki_vector.util.Speed' % self)
        self.distance = distance
        self.speed = speed
        if 'should_play_anim' not in action_kwargs:
            action_kwargs['should_play_anim'] = False
        self.action_kwargs = action_kwargs
        # super's init must come last because it checks self.action_kwargs
        super().__init__(abort_on_stop)

    def start(self,event=None):
        if self.running: return
        if isinstance(event, DataEvent) and isinstance(event.data, anki_vector.util.Distance):
            self.distance = event.data
        super().start(event)

    def action_launcher(self):
        resp = self.robot.behavior.drive_straight(self.distance, self.speed,
                                         **self.action_kwargs)
        print("resp-{}".format(resp))
        print("action_kwargs-{}".format(self.action_kwargs))
        print("Forward node completed")
        self.post_completion()
        return str(resp.result)


class Turn(ActionNode):
    """Turns by a specified angle. Can accept an Angle as a DataEvent."""
    def __init__(self, angle=degrees(90), abort_on_stop=True, **action_kwargs):
        if isinstance(angle, (int,float)):
            angle = degrees(angle)
        elif angle is None:
            pass
        elif not isinstance(angle, anki_vector.util.Angle):
            raise ValueError('%s angle must be a number or a anki_vector.util.Angle' % self)
        self.angle = angle
        self.action_kwargs = action_kwargs
        super().__init__(abort_on_stop)

    def start(self,event=None):
        if self.running: return
        if isinstance(event, DataEvent) and isinstance(event.data, anki_vector.util.Angle):
            self.angle = event.data
        super().start(event)

    def action_launcher(self):
        if self.angle is None:
            self.post_failure()
            return None
        else:
            resp = self.robot.behavior.turn_in_place(self.angle, **self.action_kwargs)
            print("Turn node completed")
            self.post_completion()
            return str(resp.result)

class GoToRelativePosition(ActionNode):
    "Uses SDK's go_to_pose method."
    def __init__(self, x, y, angle, abort_on_stop=True, **action_kwargs):
        self.pose = Pose(x=x, y=y, z=0, angle_z=Angle(degrees=angle))
        self.action_kwargs = action_kwargs
        super().__init__(abort_on_stop)

    def action_launcher(self):
        resp = self.robot.behavior.go_to_pose(self.pose, relative_to_robot=True, **self.action_kwargs)
        return '' if resp is not None else 'ERROR'

class GoToPosition(ActionNode):
    "Uses SDK's go_to_pose method."
    def __init__(self, x, y, angle, abort_on_stop=True, **action_kwargs):
        self.pose = Pose(x=x, y=y, z=0, angle_z=Angle(degrees=angle))
        self.action_kwargs = action_kwargs
        super().__init__(abort_on_stop)

    def action_launcher(self):
        resp = self.robot.behavior.go_to_pose(self.pose, **self.action_kwargs)
        return '' if resp is not None else 'ERROR'

class GoToPose(ActionNode):
    "Uses SDK's go_to_pose method."
    def __init__(self, pose, abort_on_stop=True, **action_kwargs):
        self.pose = pose
        self.action_kwargs = action_kwargs
        super().__init__(abort_on_stop)

    def action_launcher(self):
        resp = self.robot.behavior.go_to_pose(self.pose, **self.action_kwargs)
        return '' if resp is not None else 'ERROR'

class SetHeadAngle(ActionNode):
    def __init__(self, angle=degrees(0), abort_on_stop=True, **action_kwargs):
        if isinstance(angle, (int,float)):
            angle = degrees(angle)
        elif not isinstance(angle, anki_vector.util.Angle):
            raise ValueError('%s angle must be a number or a anki_vector.util.Angle' % self)
        self.angle = angle
        self.action_kwargs = action_kwargs
        super().__init__(abort_on_stop)

    def start(self,event=None):
        if self.running: return
        if isinstance(event, DataEvent) and isinstance(event.data, anki_vector.util.Angle):
            self.angle = event.data
        super().start(event)

    def action_launcher(self):
        resp = self.robot.behavior.set_head_angle(self.angle, **self.action_kwargs)
        return '' if resp is not None else 'ERROR'

class SetLiftHeight(ActionNode):
    def __init__(self, height=0, abort_on_stop=True, **action_kwargs):
        """height is a percentage from 0 to 1"""
        self.height = height
        self.action_kwargs = action_kwargs
        super().__init__(abort_on_stop)

    def action_launcher(self):
        # Temporary hack supplied by Mark Wesley at Anki
        msg = anki_vector._clad._clad_to_engine_iface.EnableLiftPower(True)
        self.robot.conn.send_msg(msg)
        resp = self.robot.behavior.set_lift_height(self.height, **self.action_kwargs)
        return '' if resp is not None else 'ERROR'

class SetLiftAngle(SetLiftHeight):
    def __init__(self, angle, abort_on_stop=True, **action_kwargs):

        #def get_theta(height):
        #   return math.asin((height-45)/66)

        if isinstance(angle, anki_vector.util.Angle):
            angle = angle.degrees
        self.angle = angle
        super().__init__(0, abort_on_stop=abort_on_stop, **action_kwargs)

    def start(self,event=None):
        if self.running: return
        if isinstance(event, DataEvent) and isinstance(event.data, anki_vector.util.Angle):
            self.angle = event.data.degrees
        min_theta = anki_vector.robot.behavior.MIN_LIFT_ANGLE.degrees
        max_theta = anki_vector.robot.behavior.MAX_LIFT_ANGLE.degrees
        angle_range = max_theta - min_theta
        self.height = (self.angle - min_theta) / angle_range
        super().start(event)


class DockWithCube(ActionNode):
    "Uses SDK's dock_with_cube method."
    def __init__(self, object=None, abort_on_stop=False, **action_kwargs):
        self.object = object
        self.action_kwargs = action_kwargs
        super().__init__(abort_on_stop=abort_on_stop)

    def start(self,event=None):
        if self.running: return
        if isinstance(event, DataEvent) and \
                isinstance(event.data,anki_vector.objects.LightCube):
            self.object = event.data
        super().start(event)

    def action_launcher(self):
        if self.robot.world.connected_light_cube is None:
            print("Light cube is not currently connected. Try 'robot.world.connect_cube()' (no guarantees this will work)")
            return 'ERROR'
        return self.robot.behavior.dock_with_cube(self.object, **self.action_kwargs)


# class PickUpObject(ActionNode):
#     "Uses SDK's pick_up_object method."
#     def __init__(self, object=None, abort_on_stop=False, **action_kwargs):
#         self.object = object
#         self.action_kwargs = action_kwargs
#         super().__init__(abort_on_stop=abort_on_stop)

#     def start(self,event=None):
#         if self.running: return
#         if isinstance(event, DataEvent) and \
#                 isinstance(event.data,anki_vector.objects.LightCube):
#             self.object = event.data
#         super().start(event)

#     def action_launcher(self):
#         if self.object is None:
#             raise ValueError('No object to pick up')
#         return self.robot.pickup_object(self.object, **self.action_kwargs)


# class PlaceObjectOnGroundHere(ActionNode):
#     "Uses SDK's place_object_on_ground_here method."
#     def __init__(self, object=None, abort_on_stop=False, **action_kwargs):
#         self.object = object
#         self.action_kwargs = action_kwargs
#         super().__init__(abort_on_stop=abort_on_stop)

#     def start(self,event=None):
#         if self.running: return
#         if isinstance(event, DataEvent) and \
#                 isinstance(event.data,anki_vector.objects.LightCube):
#             self.object = event.data
#         super().start(event)

#     def action_launcher(self):
#         if self.object is None:
#             raise ValueError('No object to place')
#         return self.robot.place_object_on_ground_here(self.object, **self.action_kwargs)

# class PlaceOnObject(ActionNode):
#     "Uses SDK's place_on_object method."
#     def __init__(self, object=None, abort_on_stop=False, **action_kwargs):
#         self.object = object
#         self.action_kwargs = action_kwargs
#         super().__init__(abort_on_stop=abort_on_stop)

#     def start(self,event=None):
#         if self.running: return
#         if isinstance(event, DataEvent) and \
#                 isinstance(event.data,anki_vector.objects.LightCube):
#             self.object = event.data
#         super().start(event)

#     def action_launcher(self):
#         if self.object is None:
#             raise ValueError('No object to place')
#         return self.robot.place_on_object(self.object, **self.action_kwargs)

# Note: additional nodes for object manipulation are in pickup.fsm.

#________________ Animations ________________

class AnimationNode(ActionNode):
    def __init__(self, anim_name='anim_bored_01', **kwargs):
        self.anim_name = anim_name
        self.action_kwargs = kwargs
        super().__init__()

    def action_launcher(self):
        return self.robot.anim.play_anim(self.anim_name, **self.action_kwargs)

class AnimationTriggerNode(ActionNode):
    def __init__(self, trigger="", **kwargs):
        self.robot.anim.load_animation_list()
        if trigger not in robot.anim.anim_list:
            raise TypeError('%s is not an instance of anki_vector.animation.AnimationComponent.anim_list' %
                            repr(trigger))
        self.trigger = trigger
        self.action_kwargs = kwargs
        super().__init__()

    def action_launcher(self):
        return self.robot.anim.play_animation(self.trigger, **self.action_kwargs)

#________________ Behaviors ________________

# class StartBehavior(StateNode):
#     def __init__(self, behavior=None, stop_on_exit=True):
#         if not isinstance(behavior, anki_vector.behavior._BehaviorType):
#             raise ValueError("'%s' isn't an instance of anki_vector.behavior._BehaviorType" %
#                              repr(behavior))
#         self.behavior = behavior
#         self.behavior_handle = None
#         self.stop_on_exit = stop_on_exit
#         super().__init__()

#     def __repr__(self):
#         if self.behavior_handle:
#             return '<%s %s active=%s>' % \
#                    (self.__class__.__name__, self.name, self.behavior_handle.is_active)
#         else:
#             return super().__repr__()

#     def start(self,event=None):
#         if self.running: return
#         super().start(event)
#         try:
#             if self.robot.behavior_handle:
#                 self.robot.behavior_handle.stop()
#         except: pass
#         finally:
#             self.robot.behavior_handle = None
#         self.behavior_handle = self.robot.start_behavior(self.behavior)
#         self.robot.behavior_handle = self.behavior_handle
#         self.post_completion()

#     def stop(self):
#         if not self.running: return
#         if self.stop_on_exit and self.behavior_handle is self.robot.behavior_handle:
#             self.robot.behavior_handle.stop()
#             self.robot.behavior_handle = None
#         super().stop()

# class StopBehavior(StateNode):
#     def start(self,event=None):
#         if self.running: return
#         super().start(event)
#         try:
#             if self.robot.behavior_handle:
#                 self.robot.behavior_handle.stop()
#         except: pass
#         self.robot.behavior_handle = None
#         self.post_completion()

# class FindFaces(StartBehavior):
#     def __init__(self,stop_on_exit=True):
#         super().__init__(anki_vector.robot.behavior.BehaviorTypes.FindFaces,stop_on_exit)

# class KnockOverCubes(StartBehavior):
#     def __init__(self,stop_on_exit=True):
#         super().__init__(anki_vector.robot.behavior.BehaviorTypes.KnockOverCubes,stop_on_exit)

# class LookAroundInPlace(StartBehavior):
#     def __init__(self,stop_on_exit=True):
#         super().__init__(anki_vector.robot.behavior.BehaviorTypes.LookAroundInPlace,stop_on_exit)

# class PounceOnMotion(StartBehavior):
#     def __init__(self,stop_on_exit=True):
#         super().__init__(anki_vector.robot.behavior.BehaviorTypes.PounceOnMotion,stop_on_exit)

# class RollBlock(StartBehavior):
#     def __init__(self,stop_on_exit=True):
#         super().__init__(anki_vector.robot.behavior.BehaviorTypes.RollBlock,stop_on_exit)

# class StackBlocks(StartBehavior):
#     def __init__(self,stop_on_exit=True):
#         super().__init__(anki_vector.robot.behavior.BehaviorTypes.StackBlocks,stop_on_exit)
