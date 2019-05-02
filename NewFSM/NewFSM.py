
import anki_vector
from anki_vector import *
from anki_vector.util import *
import concurrent.futures
"""
Nodes for Actions and stuff
"""
def stopAllMotors():
    robot.motors.set_lift_motor(0)
    robot.motors.set_wheel_motors(0, 0)

class StateMachineProgram(object):
    def __init__(self):
        self.robot = robot
        self.children = []
        self.first_child = None
        self.setup()

    def start(self):
        self.first_child.start()

    def stop(self):
        for child in self.children:
            child.stop()

    # @classmethod
    # def setRobot(cls, robot):
    #     StateMachineProgram.robot = robot
    #     print("Setting StateMachineProgram robot to {}: {}".format(robot, StateMachineProgram.robot))

class ActionNode(StateMachineProgram):
    def __init__(self):
        super().__init__()     
        self.awaiting_actions = []
        self.action = None
        self.completed = False
        self.failed = False
        self.succeeded = False
        self.data = None
        self.name = ""
        self.parent = None
        self.running = False

    def add_transition(self, trans_func):
        if self.action:
            self.action.add_done_callback(trans_func)
        else:
            self.awaiting_actions.append(trans_func)

    def set_name(self, name):
        self.name = name
        return self

    def set_parent(self, node):
        self.parent = node
        if len(self.parent.children) == 0:
            self.parent.first_child = self
        self.parent.children.append(self)
        return self

    def setup(self):
        pass

    def start(self, data=None):
        for act in self.awaiting_actions:
            self.action.add_done_callback(act)
        # need some changes here, we should directly call those transitions.


        # try:
        #     if self.action.result():
        #         print("    Got result")
        #         self.post_success()
        #     else:
        #         print("result: {}".format(self.action))
        # except:
        #     print("Failed")
        #     self.post_failure()

        # self.post_completion()

    def stop(self):
        if self.action:
            self.action.cancel()

    def result(self):
        if self.action:
            return self.action.result()
        else:
            return None

    def post_completion(self):
        self.completed = True

    def post_success(self):
        self.completed = True
        self.succeeded = True
        self.failed = False

    def post_failure(self):
        self.completed = True
        self.succeeded = False
        self.failed = True

class Forward(ActionNode):
    def __init__(self, distance=50, speed=50):
        super().__init__()
        self.distance = distance_mm(distance)
        self.speed = speed_mmps(speed)
        
    def start(self):
        self.action = self.robot.behavior.drive_straight(self.distance, self.speed)
        super().start()

class Turn(ActionNode):
    def __init__(self, angle=degrees(45)):
        super().__init__()
        if not isinstance(angle, Angle):
            angle = degrees(angle)
        self.theta = angle

    def start(self):
        self.action = self.robot.behavior.turn_in_place(self.theta)
        super().start()

class SetHeadAngle(ActionNode):
    def __init__(self, angle=degrees(0)):
        super().__init__()
        if not isinstance(angle, Angle):
            angle = degrees(angle)
        self.angle = angle

    def start(self):
        self.action = self.robot.behavior.set_head_angle(self.angle)
        super().start()

class SetLiftHeight(ActionNode):
    def __init__(self, height=0):
        super().__init__()
        self.height = height

    def start(self):
        self.action = self.robot.behavior.set_lift_height(self.height)
        super().start()

class MoveLift(ActionNode):
    def __init__(self, speed):
        super().__init__()
        self.speed = speed

    def start(self):
        self.action = self.robot.motors.set_lift_motor(self.speed)
        super().start()

class GoToPose(ActionNode):
    def __init__(self, pose, relative=False):
        super().__init__()
        self.pose = pose
        self.relative = relative

    def start(self):
        self.action = self.robot.behavior.go_to_pose(self.pose, self.relative)
        super().start()

class GoToPosition(GoToPose):
    def __init__(self, x, y, angle=degrees(0), relative=False):
        if not isinstance(angle, Angle):
            angle = degrees(angle)
        pose = Pose(x=x, y=y, angle_z=angle)
        super().__init__(pose, relative)

    def start(self):
        super().start()

class DriveOffCharger(ActionNode):
    def __init__(self):
        super().__init__()

    def start(self):
        self.action = self.robot.behavior.drive_off_charger()
        super().start()

class DriveOnCharger(ActionNode):
    def __init__(self):
        super().__init__()

    def start(self):
        self.action = self.robot.behavior.drive_on_charger()
        super().start()


class Say(ActionNode):
    def __init__(self, text):
        super().__init__()
        self.text = text

    def start(self):
        self.action = self.robot.behavior.say_text(self.text)
        super().start()

class TakePicture(ActionNode):
    def __init__(self):
        super().__init__()

    def start(self):
        self.action = self.robot.camera.capture_single_image()
        # self.action.data = self.action.result().raw_image
        super().start()

class DisplayImageOnMonitor(ActionNode):
    def __init__(self):
        super().__init__()
    # AttributeError: 'NoneType' object has no attribute 'add_done_callback'
    # we dont have self.action here.
    def start(self):
        if self.data is None:
            print("No data to show")
        else:
            image_data = self.data.raw_image
            image_data.show()
        self.action = self.robot.behavior.drive_straight(distance_mm(0), speed_mmps(100))
            # Image.open(io.BytesIO(image_data))
        super().start()

class DisplayImageOnScreen(ActionNode):
    def __init__(self, duration=1):
        super().__init__()
        self.duration = duration

    def start(self):
        if self.data is None:
            print("No data to show")
        else:
            image_data = self.data.raw_image.resize((184,96))
            screen_data = anki_vector.screen.convert_image_to_screen_data(image_data)
            self.action = self.robot.screen.set_screen_with_image_data(screen_data, self.duration)
            super().start()

class MirrorMode(ActionNode):
    def __init__(self, enable=True):
        super().__init__()
        self.enable = enable

    def start(self):
        self.action = self.robot.vision.enable_display_camera_feed_on_face(self.enable)
        super().start()

class Transition(StateMachineProgram):
    def __init__(self):
        self.sources = []
        self.destinations = []
        self.name = ""

    def set_name(self, name):
        self.name = name
        return self

    def add_sources(self, *sources):
        self.sources.extend(sources)
        for source_node in self.sources:
            source_node.add_transition(self)
        return self

    def add_destinations(self, *dests):
        self.destinations.extend(dests)
        return self

class CompletionTrans(Transition):
    def __init__(self):
        super().__init__()
        self.transition_type = "Completion"

    def __call__(self, future):
        try:
            if future.result():
                for dest_node in self.destinations:
                    dest_node.start()
                # for source_node in self.sources:
                #     if source_node.completed:
                #         for dest_node in self.destinations:
                #             dest_node.start()
        except:
            pass

class SuccessTrans(Transition):
    def __init__(self):
        super().__init__()
        self.transition_type = "Success"

    def __call__(self, future):
        try:
            if future.result():
                for source_node in self.sources:
                    if source_node.succeeded:
                        for dest_node in self.destinations:
                            dest_node.start()
        except:
            pass

class FailureTrans(Transition):
    def __init__(self):
        super().__init__()
        self.transition_type = "Failure"

    def __call__(self, future):
        try:
            if future.result():
                for source_node in self.sources:
                    if source_node.succeeded:
                        for dest_node in self.destinations:
                            dest_node.start()
        except:
            for dest_node in self.destinations:
                dest_node.start()
            

class DataTrans(Transition):
    def __init__(self, target_data=None):
        super().__init__()
        self.transition_type = "Data"
        self.target_data = target_data

    def __call__(self, future):
        for source_node in self.sources:
            if self.target_data is None or source_node.data == self.target_data:
                for dest_node in self.destinations:
                    dest_node.data = future.result()
                    dest_node.start()

class TimerTrans(Transition):
    def __init__(self, duration=0):
        super().__init__()
        self.robot = robot
        self.transition_type = "Time"
        self.duration = duration

    def startNode(self, node):
        node.start()

    def __call__(self, future):
        for dest_node in self.destinations:
            self.robot.conn.loop.call_later(self.duration, self.startNode, dest_node)