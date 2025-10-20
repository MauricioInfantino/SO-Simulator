#!/usr/bin/env python

from hardware import *
import log

## emulates a compiled program
class Program():

    def __init__(self, name, instructions):
        self._name = name
        self._instructions = self.expand(instructions)

    @property
    def name(self):
        return self._name

    @property
    def instructions(self):
        return self._instructions

    def addInstr(self, instruction):
        self._instructions.append(instruction)

    def expand(self, instructions):
        expanded = []
        for i in instructions:
            if isinstance(i, list):
                ## is a list of instructions
                expanded.extend(i)
            else:
                ## a single instr (a String)
                expanded.append(i)

        ## now test if last instruction is EXIT
        ## if not... add an EXIT as final instruction
        last = expanded[-1]
        if not ASM.isEXIT(last):
            expanded.append(INSTRUCTION_EXIT)

        return expanded

    def __repr__(self):
        return "Program({name}, {instructions})".format(name=self._name, instructions=self._instructions)


## emulates an Input/Output device controller (driver)
class IoDeviceController():

    def __init__(self, device):
        self._device = device
        self._waiting_queue = []
        self._currentPCB = None

    def runOperation(self, pcb, instruction):
        pair = {'pcb': pcb, 'instruction': instruction}
        # append: adds the element at the end of the queue
        self._waiting_queue.append(pair)
        # try to send the instruction to hardware's device (if is idle)
        self.__load_from_waiting_queue_if_apply()

    def getFinishedPCB(self):
        finishedPCB = self._currentPCB
        self._currentPCB = None
        self.__load_from_waiting_queue_if_apply()
        return finishedPCB

    def __load_from_waiting_queue_if_apply(self):
        if (len(self._waiting_queue) > 0) and self._device.is_idle:
            ## pop(): extracts (deletes and return) the first element in queue
            pair = self._waiting_queue.pop(0)
            #print(pair)
            pcb = pair['pcb']
            instruction = pair['instruction']
            self._currentPCB = pcb
            self._device.execute(instruction)

    def __repr__(self):
        return "IoDeviceController for {deviceID} running: {currentPCB} waiting: {waiting_queue}".format(deviceID=self._device.deviceId, currentPCB=self._currentPCB, waiting_queue=self._waiting_queue)

class Loader():

    def __init__(self):
        self._lastMemoryDir = 0

    def load(self, program):
        programSize = len(program.instructions)

        baseDir = self._lastMemoryDir

        for index in range(0, programSize):
            inst = program.instructions[index]
            HARDWARE.memory.write(index + baseDir, inst)

        self._lastMemoryDir += programSize

        return baseDir

class Dispatcher():

    def load(self,pcb):
        HARDWARE.cpu.pc = pcb.pc 
        HARDWARE.mmu.baseDir = pcb.baseDir

    def save(self,pcb):
        pcb.pc = HARDWARE.cpu.pc
        HARDWARE.cpu.pc = -1

NEW = "new"
READY = "ready"
RUNNING = "running"
WAITING = "waiting"
TERMINATED = "terminated"

class PCB:

    def __init__(self, pid, baseDir, path):
        self._pid = pid
        self._baseDir = baseDir
        self._pc = 0
        self._state = NEW
        self._path = path

    @property
    def pid(self):
        return self._pid

    @property
    def baseDir(self):
        return self._baseDir

    @property
    def pc(self):
        return self._pc

    def path(self):
        return self._path

    @pc.setter
    def pc(self, newPc):
        self._pc = newPc

    def setState(self, newState):
        self._state = newState

class PCBTable():

    def __init__(self):
        self._pcbTable = []
        self._newPID = 1
        self._runningPCB = None

    def get(self, PID):
        return self._pcbTable[PID]

    def add(self, PCB):
        self._pcbTable.append(PCB)
        self._newPID = self._newPID + 1

    def remove(self, PID):
        self._pcbTable.pop[PID]

    @property
    def getNewPID(self):
        return self._newPID

    @property
    def runningPCB(self):
        return self._runningPCB

    @runningPCB.setter
    def runningPCB(self, newRunningPCB):
        self._runningPCB = newRunningPCB


class ReadyQueue():

    def __init__(self):
        self._readyQueue = []

    @property
    def readyQueue(self):
        return self._readyQueue

    def add(self,pcb):
        self._readyQueue.append(pcb)
    

## emulates the  Interruptions Handlers
class AbstractInterruptionHandler():
    def __init__(self, kernel):
        self._kernel = kernel

    @property
    def kernel(self):
        return self._kernel
    
    def runNextProgramInCPU(self,pcbIn):
        if(not self.kernel.pcbTable.runningPCB):
            self.kernel.dispatcher.load(pcbIn)
            pcbIn.setState(RUNNING)
            self.kernel.pcbTable.runningPCB = pcbIn
            
        else:
            self.kernel.readyQueue.add(pcbIn)
            pcbIn.setState(READY)

    def runNextProgramOutCPU(self):
        if self.kernel.readyQueue.readyQueue:
            newPCB = self.kernel.readyQueue.readyQueue.pop(0)
            self.kernel.dispatcher.load(newPCB)
            self.kernel.pcbTable.runningPCB = newPCB
            newPCB.setState(RUNNING)
        else:
            self.kernel.pcbTable.runningPCB = None
            HARDWARE.cpu.pc = -1   ## dejamos el CPU IDLE

    def execute(self, irq):
        log.logger.error("-- EXECUTE MUST BE OVERRIDEN in class {classname}".format(classname=self.__class__.__name__))

class NewInterruptionHandler(AbstractInterruptionHandler):
    
    def execute(self, irq):
        program = irq.parameters
        pid = self.kernel.pcbTable.getNewPID
        baseDir = self.kernel.loader.load(program)
        path = program.name
        newPCB = PCB(pid,baseDir,path) 
        self.kernel.pcbTable.add(newPCB)
        self.runNextProgramInCPU(newPCB)


class KillInterruptionHandler(AbstractInterruptionHandler):

    def execute(self, irq):
        log.logger.info(" Program Finished ")
        pcb = self.kernel.pcbTable.runningPCB
        self.kernel.dispatcher.save(pcb)
        pcb.setState(TERMINATED)
        self.runNextProgramOutCPU()


class IoInInterruptionHandler(AbstractInterruptionHandler):

    def execute(self, irq):
        operation = irq.parameters
        pcb = self.kernel.pcbTable.runningPCB
        self.kernel.dispatcher.save(pcb)
        pcb.setState(WAITING)
        self.kernel.ioDeviceController.runOperation(pcb, operation) #Agrega el pcb a la waiting queue
        log.logger.info(self.kernel.ioDeviceController)
        self.runNextProgramOutCPU()



class IoOutInterruptionHandler(AbstractInterruptionHandler):

    def execute(self, irq):
        pcb = self.kernel.ioDeviceController.getFinishedPCB()
        self.runNextProgramInCPU(pcb)

# emulates the core of an Operative System
class Kernel():

    def __init__(self):
        ## setup interruption handlers
        killHandler = KillInterruptionHandler(self)
        HARDWARE.interruptVector.register(KILL_INTERRUPTION_TYPE, killHandler)

        ioInHandler = IoInInterruptionHandler(self)
        HARDWARE.interruptVector.register(IO_IN_INTERRUPTION_TYPE, ioInHandler)

        ioOutHandler = IoOutInterruptionHandler(self)
        HARDWARE.interruptVector.register(IO_OUT_INTERRUPTION_TYPE, ioOutHandler)
        
        newHandler = NewInterruptionHandler(self)
        HARDWARE.interruptVector.register(NEW_INTERRUPTION_TYPE, newHandler)

        ## controls the Hardware's I/O Device
        self._ioDeviceController = IoDeviceController(HARDWARE.ioDevice)
        
        self._loader = Loader()
        
        self._dispatcher = Dispatcher()
        
        self._pcbTable = PCBTable()
        
        self._readyQueue = ReadyQueue()

    @property
    def loader(self):
        return self._loader

    @property
    def dispatcher(self):
        return self._dispatcher

    @property
    def pcbTable(self):
        return self._pcbTable

    @property
    def readyQueue(self):
        return self._readyQueue    

    @property
    def ioDeviceController(self):
        return self._ioDeviceController

    ## emulates a "system call" for programs execution
    def run(self, program):
        newIRQ = IRQ(NEW_INTERRUPTION_TYPE, program)
        HARDWARE.interruptVector.handle(newIRQ)
        log.logger.info(HARDWARE)

    def __repr__(self):
        return "Kernel "
