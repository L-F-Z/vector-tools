#!/usr/bin/env python3

# Copyright (c) 2018 Anki, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License in the file LICENSE.txt or at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Hello World

Make Vector say 'Hello World' in this simple Vector SDK example program.
"""

import anki_vector
from anki_vector import *
from anki_vector.util import *
import subprocess, shlex, functools, time, concurrent.futures

class ActionNode(object):
    def __init__(self, robot):
        self.robot = robot
        self.awaiting_actions = []
        self.action = None
        self.completed = False
        self.failed = False
        self.succeeded = False
        self.data = None
        self.name = ""
        self.parent = None

    def add_transition(self, transition):
        trans_func = functools.partial(transition, self.robot)
        if self.action:
            self.action.add_done_callback(trans_func)
        else:
            self.awaiting_actions.append(trans_func)

    def set_name(self, name):
        self.name = name

    def set_parent(self, node):
        self.parent = node

    def start(self, data=None):
        for act in self.awaiting_actions:
            self.action.add_done_callback(act)
        # need some changes here, we should directly call those transitions.


        # try:
        #     print("checking status")
        #     if self.action.result():
        #         print("    Got result")
        #         self.post_success()
        #     else:
        #         print("result: {}".format(self.action))
        # except:
        #     print("Failed")
        #     self.post_failure()

        # self.post_completion()

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
    def __init__(self, robot, distance=50, speed=50):
        super().__init__(robot)
        self.distance = distance_mm(distance)
        self.speed = speed_mmps(speed)
        
    def start(self):
        self.action = self.robot.behavior.drive_straight(self.distance, self.speed)
        super().start()

class Turn(ActionNode):
    def __init__(self, robot, angle=45):
        super().__init__(robot)
        self.theta = degrees(angle)

    def start(self):
        self.action = self.robot.behavior.turn_in_place(self.theta)
        super().start()

class Say(ActionNode):
    def __init__(self, robot, text):
        super().__init__(robot)
        self.text = text

    def start(self):
        self.action = self.robot.behavior.say_text(self.text)
        super().start()

class TakePicture(ActionNode):
    def __init__(self, robot):
        super().__init__(robot)

    def start(self):
        self.action = self.robot.camera.capture_single_image()
        # self.action.data = self.action.result().raw_image
        super().start()

class DisplayImageOnMonitor(ActionNode):
    def __init__(self, robot):
        super().__init__(robot)
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

class Transition(object):
    def __init__(self):
        self.sources = []
        self.destinations = []
        self.name = ""

    def set_name(self, name):
        self.name = name

    def add_sources(self, *sources):
        self.sources.extend(sources)
        for source_node in self.sources:
            source_node.add_transition(self)
        return self

    def add_destinations(self, *dests):
        self.destinations.extend(dests)
        return self

class CompletionTransition(Transition):
    def __init__(self):
        super().__init__()
        self.transition_type = "Completion"

    def __call__(self, robot, future):
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

class SuccessTransition(Transition):
    def __init__(self):
        super().__init__()
        self.transition_type = "Success"

    def __call__(self, robot, future):
        try:
            if future.result():
                for source_node in self.sources:
                    if source_node.succeeded:
                        for dest_node in self.destinations:
                            dest_node.start()
        except:
            pass

class FailureTransition(Transition):
    def __init__(self):
        super().__init__()
        self.transition_type = "Failure"

    def __call__(self, robot, future):
        try:
            if future.result():
                for source_node in self.sources:
                    if source_node.succeeded:
                        for dest_node in self.destinations:
                            dest_node.start()
        except:
            for dest_node in self.destinations:
                dest_node.start()
            

class DataTransition(Transition):
    def __init__(self, target_data=None):
        super().__init__()
        self.transition_type = "Data"
        self.target_data = target_data

    def __call__(self, robot, future):
        print("Calling data transition")
        for source_node in self.sources:
            if self.target_data is None or source_node.data == self.target_data:
                print("Check Passed")
                for dest_node in self.destinations:
                    dest_node.data = future.result()
                    print("firing up next node")
                    dest_node.start()

class TimeTransition(Transition):
    def __init__(self, duration=0):
        super().__init__()
        self.transition_type = "Time"
        self.duration = duration

    def startNode(self, node):
        node.start()

    def __call__(self, robot, future):
        print("Calling time transition")
        for dest_node in self.destinations:
            robot.conn.loop.call_later(self.duration, self.startNode, dest_node)



def main():
    args = anki_vector.util.parse_command_args()
    with anki_vector.AsyncRobot(args.serial) as robot:
        print("Got robot")
        time.sleep(3)
        print("Starting program")
        forward = Forward(robot)
        turn = Turn(robot)
        backward = Forward(robot, -50)
        speak = Say(robot, "Hi There")
        takepic = TakePicture(robot)
        speak2 = Say(robot, "All done")
        declare_failure = Say(robot, "I have failed but I am still the best")
        displaypic = DisplayImageOnMonitor(robot);
        complete1 = CompletionTransition().add_sources(forward).add_destinations(turn)
        complete2 = CompletionTransition().add_sources(turn).add_destinations(backward, speak)
        complete3 = CompletionTransition().add_sources(speak).add_destinations(takepic)
        dataTrans = DataTransition().add_sources(takepic).add_destinations(displaypic)
        timeTrans = TimeTransition(10).add_sources(displaypic).add_destinations(speak2)
        failureTrans = FailureTransition().add_sources(forward, turn, backward, speak, takepic, speak2).add_destinations(declare_failure)
        forward.start()

        while(True):
        	cmd = input(">>> ")
        	exec(cmd)


if __name__ == "__main__":
    main()

