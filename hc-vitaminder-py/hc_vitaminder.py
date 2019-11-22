import threading
from queue import Queue
from enum import Enum, auto
import serial
import sys
from datetime import datetime, timedelta, date, time
import configparser

# server message definitions (ones sent out from python):
# id=00: heartbeat request
#   req bytes:
#       0 - message ID 0x00
#       1-7 - ignored
#   rsp bytes:
#       send the current settings for LED brightness and colors
#       server might ignore it, or make use of it for some future reason
#       0 - 0x01
#       1 - led brightness
#       2-4 - vita LED r, g, b
#       5-7 - sys  LED r, g, b
# id=02: set LED
#   req bytes:
#       0 - message ID 0x02
#       1 - brightness
#       2 - pixel mask (least significant nibble represents the 4 pixels)
#       3 - red
#       4 - green
#       5 - blue
#       6 - off millis duration (div by 10) (off=0 means constant on)
#       7 - on millis duration (div by 10)
#   rsp bytes:
#       0 - 0x03
#       1-7 - ignored

# client message definitions (sent out by Arduino, received by python):
# id=04: device boot
#   req bytes:
#       0 - message ID 0x04
#       1-7 - ignored
#   rsp bytes:
#       none, the host PC will send "set LED" message within 5 secs of responding to this boot message
# id=06: button press
#   req bytes:
#       0 - message ID 0x06
#       1 - ok button status (0x00 for unpressed, 0x01 for pressed)
#       2 - snooze status    (0x00 for unpressed, 0x01 for pressed)
#       3-7 - ignored
#   rsp bytes:
#       none, it is likely (but not required) the host will send a "set LED" message soon,
#       since a button press typically triggers a state change.


def rgb_from_config(color_str="0,0,0"):
    return [int(c) for c in color_str.split(',')]


class Vitaminder:
    def __init__(self, config=None):
        self.config = config

        self.port_name = None
        self.serial_port = None
        self.state = VitState.UNMEDICATED
        self.current_date = date.today()
        self.snooze_expiration = None

        self.snooze_delta = timedelta(seconds=int(self.config["snooze_duration_seconds"]))

        self.heartbeat_time = None
        self.heartbeat_result = None

        self.alive = True
        self.alive_lock = threading.Condition()
        self.msg_lock = threading.Condition()
        self.msg_queue = Queue()

    def connect(self):
        self.port_name = self.config["comm_port"]
        print("connecting:", self.port_name)
        self.serial_port = serial.Serial(self.port_name, timeout=int(self.config["comm_read_timeout"]))
        print("connection status:", self.serial_port.isOpen())

    def disconnect(self):
        if self.is_connected():
            self.serial_port.close()

    def is_connected(self):
        return self.serial_port is not None and self.serial_port.isOpen()

    def __del__(self):
        self.disconnect()

    def send_set_led_message(self):
        # we basically need a brightness (just use default) and a color (base on state)
        color_map = {
            VitState.UNMEDICATED:   rgb_from_config(self.config["color_unmedicated"]),
            VitState.NAILED_IT:     rgb_from_config(self.config["color_nailed_it"]),
            VitState.SOFT_REMINDER: rgb_from_config(self.config["color_soft_reminder"]),
            VitState.HARD_REMINDER: rgb_from_config(self.config["color_hard_reminder"]),
            VitState.SNOOZE:        rgb_from_config(self.config["color_snooze"]),
        }
        brightness_map = {
            VitState.UNMEDICATED:   int(self.config["brightness_unmedicated"]),
            VitState.NAILED_IT:     int(self.config["brightness_nailed_it"]),
            VitState.SOFT_REMINDER: int(self.config["brightness_soft_reminder"]),
            VitState.HARD_REMINDER: int(self.config["brightness_hard_reminder"]),
            VitState.SNOOZE:        int(self.config["brightness_snooze"])
        }

        rgb = color_map.get(self.state, [128, 0, 255])
        brightness = brightness_map.get(self.state, 128)

        # rgb = [0, 0, 255]
        # TODO implement blinking for reminder states

        blink_off = 25
        blink_on = 75

        pixel_mask = 0x0F

        #   req bytes:
        #       0 - message ID 0x02
        #       1 - brightness
        #       2 - pixel mask (least significant nibble represents the 4 pixels)
        #       3 - red
        #       4 - green
        #       5 - blue
        #       6 - off millis duration (div by 10) (off=0 means constant on)
        #       7 - on millis duration (div by 10)

        self.serial_port.write(bytes([0x02, brightness, pixel_mask, rgb[0], rgb[1], rgb[2], blink_off, blink_on]))

    def time_update_thread(self, debug=False):
        while self.alive:
            if debug:
                print("time_update() doing my thing")
            self.update_state_by_time()
            self.add_event(VitEvent(VitMsg.STATE))
            self.alive_lock.acquire()
            self.alive_lock.wait(int(self.config["time_update_thread_sleep_sec"]))
            self.alive_lock.release()

        if debug:
            print("time_update() end")

    def update_state_by_time(self):
        # if it is our first update after 2am of a new day,
        #   reset a new day, back to UNMEDICATED and clear any snooze flags

        # if we NAILED_IT, simply move along, maybe give yourself a hug

        # if we are snoozing, check the snooze expiry.
        #   if still snoozing, no state change, buh bye
        #   if done snoozing, temporarily set state to UNMEDICATED and continue to next section...

        # so we're not snoozing, lets figure the right state based on time
        #   2am - 6pm, UNMEDICATED
        #   6pm-7pm, SOFT_REMINDER
        #   7pm-2am, HARD_REMINDER

        if self.current_date is not None and self.current_date != date.today():
            # we have a new day! happy new year!
            self.current_date = date.today()
            self.snooze_expiration = None
            self.state = VitState.UNMEDICATED
            return

        if self.state == VitState.NAILED_IT:
            # congrats brah
            return

        if self.state == VitState.SNOOZE:
            if datetime.now() < self.snooze_expiration:
                # goto sleep; goto sleep; goto sleep, little baby
                return
            else:
                # WAKE UP, SLEEPY HEAD!
                self.snooze_expiration = None
                self.state = VitState.UNMEDICATED

        n = datetime.now().time()
        unmed_begin = time.fromisoformat(self.config["boundary_unmedicated_begin"])
        unmed_end = time.fromisoformat(self.config["boundary_unmedicated_end"])
        soft_begin = time.fromisoformat(self.config["boundary_soft_reminder_begin"])
        soft_end = time.fromisoformat(self.config["boundary_soft_reminder_end"])
        # print("time.now()", n)
        # print("unmed_begin", unmed_begin)
        # print("unmed_end", unmed_end)
        # print("soft_begin", soft_begin)
        # print("soft_end", soft_end)

        if unmed_begin <= n < unmed_end:
            self.state = VitState.UNMEDICATED
            print("update_state_by_time() UNMEDICATED")
        elif soft_begin <= n < soft_end:
            self.state = VitState.SOFT_REMINDER
            print("update_state_by_time() SOFT_REMINDER")
        else:
            self.state = VitState.HARD_REMINDER
            print("update_state_by_time() HARD_REMINDER")

    def handle_button_press(self, event):
        # snooze button is only valid if current state is hard or soft reminder, or snooze (adds more time)
        if event.data[2] == 0x01:
            # snooze button
            if self.state in [VitState.SNOOZE, VitState.SOFT_REMINDER, VitState.HARD_REMINDER]:
                self.state = VitState.SNOOZE
                self.snooze_expiration = datetime.now() + self.snooze_delta

        elif event.data[1] == 0x01:
            # ok button

            # if currently NAILED_IT, revert to whatever time-based state you should be in
            # if not currently NAILED_IT, then NAIL_IT
            if self.state != VitState.NAILED_IT:
                self.state = VitState.NAILED_IT
                self.snooze_expiration = None
            else:
                self.state = VitState.UNMEDICATED
                self.update_state_by_time()

            # mapper = {
            #    VitState.UNMEDICATED: VitState.SOFT_REMINDER,
            #    VitState.SOFT_REMINDER: VitState.HARD_REMINDER,
            #    VitState.HARD_REMINDER: VitState.SNOOZE,
            #    VitState.SNOOZE: VitState.NAILED_IT,
            #    VitState.NAILED_IT: VitState.UNMEDICATED
            # }
            # self.state = mapper.get(self.state)

        self.add_event(VitEvent(VitMsg.STATE))

    def add_event(self, event):
        self.msg_lock.acquire()
        self.msg_queue.put(event)
        self.msg_lock.notify_all()
        self.msg_lock.release()

    def serial_read_thread(self, debug=False):
        while self.alive:
            msg = self.serial_port.read(int(self.config["msg_size"]))
            if debug:
                print("serial_read: looping")
            if msg is None or len(msg) < int(self.config["msg_size"]):
                if debug:
                    print("serial_read: simply a timeout, msg is none")
            else:
                if debug:
                    print("serial_read: have a message")
                # create a message event and push it to the queue
                msg_type = None
                if msg[0] == 0x01:
                    msg_type = VitMsg.SERIAL_HEARTBEAT_RSP
                elif msg[0] == 0x03:
                    msg_type = VitMsg.SERIAL_STATE_RSP
                elif msg[0] == 0x04:
                    msg_type = VitMsg.SERIAL_BOOT
                elif msg[0] == 0x06:
                    msg_type = VitMsg.SERIAL_BUTTON
                e = VitEvent(msg_type, msg)
                self.add_event(e)
        if debug:
            print("serial_read: end")

    def dummy_thread(self, debug=False):
        dummy_sleep_sec = int(self.config["dummy_thread_sleep_sec"])
        if debug:
            print("dummy() sleeping for", dummy_sleep_sec, "seconds")
        self.alive_lock.acquire()
        self.alive_lock.wait(dummy_sleep_sec)
        self.alive_lock.release()

        if debug:
            print("dummy() adding EXIT msg")
        self.add_event(VitEvent(event_id=VitMsg.EXIT))

    def heartbeat_thread(self, debug=False):
        while self.alive:
            if debug:
                print("hb() adding heartbeat message")
            self.add_event(VitEvent(VitMsg.HEARTBEAT))
            self.alive_lock.acquire()
            self.alive_lock.wait(int(self.config["heartbeat_thread_sleep_sec"]))
            self.alive_lock.release()

        if debug:
            print("hb() end")

    def ctl_thread(self, debug=False, print_msg=True):
        # acquire the lock
        self.msg_lock.acquire()

        # keep reading messages for as long as we're alive
        while self.alive:
            # process messages
            while not self.msg_queue.empty():
                e = self.msg_queue.get()
                if debug or print_msg:
                    print("ctl: ", e.event_id)

                if e.event_id == VitMsg.EXIT:
                    if debug:
                        print("ctl got exit message")
                    self.alive = False
                    # wake everybody up so they can exit cleanly
                    self.alive_lock.acquire()
                    self.alive_lock.notify_all()
                    self.alive_lock.release()
                else:
                    if debug:
                        print("ctl got non-exit message:", str(e.data))
                    if e.event_id == VitMsg.HEARTBEAT:
                        self.serial_port.write(bytes([0, 1, 1, 1, 1, 1, 1, 1]))
                    elif e.event_id == VitMsg.STATE:
                        self.send_set_led_message()
                    elif e.event_id == VitMsg.SERIAL_BOOT:
                        # device booted, send them current state info
                        self.send_set_led_message()
                    elif e.event_id == VitMsg.SERIAL_BUTTON:
                        # they pressed a button, DO SOMETHING!
                        self.handle_button_press(e)

            # wait for new messages (temporarily releases the lock)
            if self.alive:
                self.msg_lock.wait(int(self.config["ctl_thread_sleep_sec"]))
                if debug:
                    print("ctl done waiting")

        # release the lock
        self.msg_lock.release()
        if debug:
            print("ctl end")


class VitEvent:
    def __init__(self, event_id, data=None):
        self.event_id = event_id
        self.data = data


class VitMsg(Enum):
    EXIT = auto()
    HEARTBEAT = auto()
    STATE = auto()
    SERIAL_BOOT = auto()
    SERIAL_BUTTON = auto()
    SERIAL_HEARTBEAT_RSP = auto()
    SERIAL_STATE_RSP = auto()


class VitState(Enum):
    UNMEDICATED = auto()
    SOFT_REMINDER = auto()
    HARD_REMINDER = auto()
    SNOOZE = auto()
    NAILED_IT = auto()


if __name__ == "__main__":

    # load configuration
    config_file = "hc-vitaminder.ini"
    if len(sys.argv) < 2:
        print("no config file specified, using default:", config_file)
    else:
        config_file = sys.argv[1]
        print("using config file:", config_file)

    configuration = configparser.ConfigParser()
    configuration.read(config_file)
    configuration = configuration["DEFAULT"]

    v = Vitaminder(config=configuration)
    v.connect()

    ctl_thread = threading.Thread(target=v.ctl_thread)
    print("main starting control thread")
    ctl_thread.start()

    serial_thread = threading.Thread(target=v.serial_read_thread)
    print("main starting serial_read")
    serial_thread.start()

    # dummy_thread = threading.Thread(target=v.dummy_thread)
    # print("main starting dummy")
    # dummy_thread.start()

    heartbeat_thread = threading.Thread(target=v.heartbeat_thread)
    print("main starting heartbeat")
    heartbeat_thread.start()

    time_thread = threading.Thread(target=v.time_update_thread)
    print("main starting time_update")
    time_thread.start()

    ctl_thread.join()
    # dummy_thread.join()
    heartbeat_thread.join()
    serial_thread.join()
    time_thread.join()

    v.disconnect()
    print("main all done")


if __name__ == "__xxxmain__":
    port_name = "COM5"
    if len(sys.argv) < 2:
        print("no port specified, using default:", port_name)
    else:
        port_name = sys.argv[1]
        print("using port:", port_name)

    ser = serial.Serial(port_name)
    print("Serial name:", ser.name)

    # TODO - test for successful connection

    # ser.write(b'py\n')
    ser.write(bytes([0, 1, 1, 1, 1, 1, 1, 1]))

    # TODO handle failed ack
    rsp = ser.read(8)
    if rsp[0] == 0x00:
        print("have heartbeat response")
    else:
        print("have unknown response")

    ser.write(bytes([1, 128, 255, 0, 255, 0, 255, 0]))

    # TODO handle failed ack
    rsp = ser.read(8)
    if rsp[0] == 0x01:
        print("have LED response")
    else:
        print("have unknown response")

    ser.write(bytes([2, 98, 99, 100, 101, 102, 103, 104]))

    ser.close()
