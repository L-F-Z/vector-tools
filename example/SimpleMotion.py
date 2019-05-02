from NewFSM.NewFSM import *

class SimpleMotion(StateMachineProgram):
    def setup(self):
        """
            Forward(50)=C=>Turn(30)=C=>{driver, speaker}
            driver : Forward(-50)=T(10)=>Say("All Done")=C=>TakePicture()=D=>DisplayImageOnMonitor()
            speaker : Say("Save Anki!")
        """
        
        # Code generated by genfsm on Thu May  2 18:05:24 2019:
        
        forward1 = Forward(50) .set_name("forward1") .set_parent(self)
        turn1 = Turn(30) .set_name("turn1") .set_parent(self)
        driver = Forward(-50) .set_name("driver") .set_parent(self)
        say1 = Say("All Done") .set_name("say1") .set_parent(self)
        takepicture1 = TakePicture() .set_name("takepicture1") .set_parent(self)
        displayimageonmonitor1 = DisplayImageOnMonitor() .set_name("displayimageonmonitor1") .set_parent(self)
        speaker = Say("Save Anki!") .set_name("speaker") .set_parent(self)
        
        completiontrans1 = CompletionTrans() .set_name("completiontrans1")
        completiontrans1 .add_sources(forward1) .add_destinations(turn1)
        
        completiontrans2 = CompletionTrans() .set_name("completiontrans2")
        completiontrans2 .add_sources(turn1) .add_destinations(driver,speaker)
        
        timertrans1 = TimerTrans(10) .set_name("timertrans1")
        timertrans1 .add_sources(driver) .add_destinations(say1)
        
        completiontrans3 = CompletionTrans() .set_name("completiontrans3")
        completiontrans3 .add_sources(say1) .add_destinations(takepicture1)
        
        datatrans1 = DataTrans() .set_name("datatrans1")
        datatrans1 .add_sources(takepicture1) .add_destinations(displayimageonmonitor1)
        
        return self
