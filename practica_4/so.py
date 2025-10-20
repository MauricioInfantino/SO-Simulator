#!/usr/bin/env python

from hardware import *
import log
from collections import deque

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
        HARDWARE.timer.reset()

    def save(self,pcb):
        pcb.pc = HARDWARE.cpu.pc
        HARDWARE.cpu.pc = -1

NEW = "new"
READY = "ready"
RUNNING = "running"
WAITING = "waiting"
TERMINATED = "terminated"
STAT = "stat"

class PCB:

    def __init__(self, pid, baseDir, path, priority):
        self._pid = pid
        self._baseDir = baseDir
        self._pc = 0
        self._state = NEW
        self._path = path
        
        self._base_priority = priority  # prioridad
        self._current_priority = priority  # prioridad modificable
        self._waiting_ticks = 0  # ticks
        self._aging_ticks = 4  # a cuantos ticks envejece

    def age(self):
        # Suma un tick de espera
        self._waiting_ticks += 1
    
        if self._waiting_ticks >= self._aging_ticks and self._current_priority > 0:
            self._current_priority -= 1
            self._waiting_ticks = 0      # reinicia contador
            return True                  # avisa que envejeció (subió)
    
        return False # por default no envejece

    @property
    def pid(self):
        return self._pid

    @property
    def baseDir(self):
        return self._baseDir

    @property
    def pc(self):
        return self._pc

    @property
    def path(self):
        return self._path

    @pc.setter
    def pc(self, newPc):
        self._pc = newPc

    def setState(self, newState):
        self._state = newState

    @property
    def priority(self):
        return self._base_priority

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
    

## emulates the  Interruptions Handlers
class AbstractInterruptionHandler():
    def __init__(self, kernel):
        self._kernel = kernel

    @property
    def kernel(self):
        return self._kernel

    def runNextProgramInCPU(self, pcbIn):
        running = self.kernel.pcbTable.runningPCB
        scheduler = self.kernel.scheduler()
        if running is None:
            self.kernel.dispatcher.load(pcbIn)
            pcbIn.setState(RUNNING)
            self.kernel.pcbTable.runningPCB = pcbIn
        else:
            if scheduler.mustExpropiate(running, pcbIn):
                self.kernel.dispatcher.save(running)
                running.setState(READY)
                scheduler.add(running)
                self.kernel.dispatcher.load(pcbIn)
                pcbIn.setState(RUNNING)
                self.kernel.pcbTable.runningPCB = pcbIn
            else:
                scheduler.add(pcbIn)
                pcbIn.setState(READY)

    def runNextProgramOutCPU(self):
        scheduler = self.kernel.scheduler()
        if not scheduler.isReadyQueueEmpty():
            newPCB = scheduler.getNext()
            self.kernel.dispatcher.load(newPCB)
            self.kernel.pcbTable.runningPCB = newPCB
            newPCB.setState(RUNNING)
        else:
            self.kernel.pcbTable.runningPCB = None
            HARDWARE.cpu.pc = -1

    def execute(self, irq):
        log.logger.error("-- EXECUTE MUST BE OVERRIDEN in class {classname}".format(classname=self.__class__.__name__))

class NewInterruptionHandler(AbstractInterruptionHandler):
    
    def execute(self, irq):
        parameters = irq.parameters
        program = parameters['program']
        priority = parameters['priority']
        pid = self.kernel.pcbTable.getNewPID
        baseDir = self.kernel.loader.load(program)
        path = program.name
        newPCB = PCB(pid,baseDir,path,priority) 
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
        pcb._current_priority = pcb._base_priority # Resetea la prioridad y ticks para aging
        pcb._waiting_ticks = 0
        self.runNextProgramInCPU(pcb)
            
class StatInterruptionHandler(AbstractInterruptionHandler):
    
    def __init__(self, kernel):
        super().__init__(kernel)
        self.gantt = {}  #Es un map donde las claves son pid y el values es una lista de ticks PID -> lista de ticks '█' o '░'

    def execute(self, irq):
        self.kernel.scheduler().apply_aging()
        tick = HARDWARE.clock.currentTick
        running_pcb = self.kernel.pcbTable.runningPCB

        # registrar PIDs
        if running_pcb:
            pid = running_pcb.pid
        else:
            pid = None

        # marcar todos los PIDs en el Gantt
        for p in self.gantt.keys():
            self.gantt[p].append('█' if p == pid else '░')

        # si aparece un PID nuevo
        if pid is not None and pid not in self.gantt:
            self.gantt[pid] = ['░'] * tick + ['█']
            
        if HARDWARE.cpu.pc == -1 and all(p._state == TERMINATED for p in self.kernel.pcbTable._pcbTable):
            self.printGantt()

    def printGantt(self):
        print("\n=== Diagrama de Gantt ===")
        for pid, line in sorted(self.gantt.items()):
            print(f"PID {pid}: {''.join(line)}")

class TimeoutInterruptionHandler(AbstractInterruptionHandler):    
    def execute(self, irq):
        running_pcb = self.kernel.pcbTable.runningPCB
        if running_pcb is not None:
            self.kernel.dispatcher.save(running_pcb)
            running_pcb.setState(READY)
            self.kernel.scheduler().add(running_pcb)

        next_pcb = self.kernel.scheduler().getNext()
        if next_pcb is not None:
            self.kernel.dispatcher.load(next_pcb)
            next_pcb.setState(RUNNING)
            self.kernel.pcbTable.runningPCB = next_pcb

class AbstractScheduler():

    def __init__(self):
        self._readyQueue = []
    
    def add(self, pcb):
        self._readyQueue.append(pcb)

    def getNext(self):
        pass

    def mustExpropiate(self, pcbIn, pcbToAdd):
        return False
    
    def isReadyQueueEmpty(self):
        return len(self._readyQueue) == 0
    
    def apply_aging(self):
        pass

class SchedulerFCFS(AbstractScheduler):

    def __init__(self):
        super().__init__()
        self._readyQueue = deque()
    
    def getNext(self):
        return self._readyQueue.popleft()
    
class SchedulerRoundRobin(SchedulerFCFS):

    def __init__(self):
        super().__init__()
        HARDWARE.timer.quantum = 4
    
    def mustExpropiate(self, pcbIn, pcbToAdd):
        return False
    

class SchedulerPriority(AbstractScheduler):
    def __init__(self):
        super().__init__()
        self._readyQueue = [[],[],[],[],[]]

    def add(self, pcb):
        self._readyQueue[pcb._base_priority].append(pcb)

    def getNext(self):
        for queue in self._readyQueue:
            if queue:
                return queue.pop(0)
        return None
    
    def isReadyQueueEmpty(self):
        return all(len(q) == 0 for q in self._readyQueue)
    
    def apply_aging(self):
        aged_pcbs = []

    # Recorremos todas las colas de prioridad
        for prio, queue in enumerate(self._readyQueue):
            for pcb in list(queue):  # usamos list() por si modificamos la cola
                if pcb.age():  # 👈 si envejeció (llegó al límite)
                    queue.remove(pcb)
                    aged_pcbs.append(pcb)

        # Reinsertamos los que envejecieron en su nueva cola (mayor prioridad)
        for pcb in aged_pcbs:
            self._readyQueue[pcb._current_priority].append(pcb)

class SchedulerPreemtive(SchedulerPriority):
    def __init__(self):
        super().__init__()

    def mustExpropiate(self, pcbIn, pcbToAdd):
        return pcbToAdd._base_priority < pcbIn._base_priority


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

        timeoutHandler = TimeoutInterruptionHandler(self)
        HARDWARE.interruptVector.register(TIMEOUT_INTERRUPTION_TYPE, timeoutHandler)
        
        self._statHandler = StatInterruptionHandler(self)
        HARDWARE.interruptVector.register(STAT_INTERRUPTION_TYPE, self._statHandler)


        ## controls the Hardware's I/O Device
        self._ioDeviceController = IoDeviceController(HARDWARE.ioDevice)
        
        self._loader = Loader()
        
        self._dispatcher = Dispatcher()
        
        self._pcbTable = PCBTable()
        
        self._scheduler = SchedulerPriority()

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
    def ioDeviceController(self):
        return self._ioDeviceController
    
    def scheduler(self):
        return self._scheduler
    
    @property
    def statHandler(self):
        return self._statHandler

    ## emulates a "system call" for programs execution
    def run(self, program, priority):
        parameters = {'program': program, 'priority': priority}
        newIRQ = IRQ(NEW_INTERRUPTION_TYPE, parameters)
        HARDWARE.interruptVector.handle(newIRQ)
        log.logger.info(HARDWARE)

    def __repr__(self):
        return "Kernel "
