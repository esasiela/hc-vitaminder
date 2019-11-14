import serial.tools.list_ports

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout, QHBoxLayout,\
    QComboBox, QPushButton, QColorDialog, QGridLayout, QFrame
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt

from hc_vitaminder import *


class SerialConnectionWidget(QFrame):
    def __init__(self, parent=None, vitaminder=None):
        QFrame.__init__(self, parent)
        self.vitaminder = vitaminder
        self.port_combobox = None
        self.connect_button = None
        self.initUI()

    def initUI(self):
        self.setFrameStyle(QFrame.StyledPanel)

        layout = QVBoxLayout()

        port_frame = QWidget()
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("Port"))

        self.port_combobox = QComboBox()
        self.click_refresh()
        port_layout.addWidget(self.port_combobox)

        port_refresh_button = QPushButton("Refresh")
        port_refresh_button.clicked.connect(self.click_refresh)
        port_layout.addWidget(port_refresh_button)

        port_frame.setLayout(port_layout)

        connect_frame = QWidget()
        connect_layout = QHBoxLayout()
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.click_connect)
        connect_layout.addWidget(self.connect_button)
        connect_frame.setLayout(connect_layout)

        layout.addWidget(port_frame)
        layout.addWidget(connect_frame)

        self.setLayout(layout)

    def click_refresh(self):
        if self.port_combobox is not None:
            self.port_combobox.clear()
            for p in serial.tools.list_ports.comports():
                self.port_combobox.addItem(str(p))

    def click_connect(self):
        print("clicked connect", self.port_combobox.currentText())

        if self.vitaminder is not None and not self.vitaminder.isConnected():
            self.vitaminder.port_name = self.port_combobox.currentText().split(" ")[0]
            self.vitaminder.connect()
            # TODO check success of connection


class LEDColorWidget(QFrame):
    def __init__(self, parent=None, color=QColor("#00FF00"), title=None):
        QFrame.__init__(self, parent)
        self.color = color
        self.title = title
        self.icon = None
        self.textbox_r = None
        self.textbox_g = None
        self.textbox_b = None

        self.initUI()

    def initUI(self):
        self.setFrameStyle(QFrame.StyledPanel)

        text_frame = QWidget()
        #text_frame.setFrameStyle(QFrame.StyledPanel)
        text_layout = QGridLayout()

        text_layout.addWidget(QLabel(self.title), 0, 0)
        self.icon = QFrame()
        self.icon.setFrameStyle(QFrame.StyledPanel)
        self.icon.setMinimumSize(10, 10)
        if self.color is not None:
            self.icon.setStyleSheet("background-color: " + self.color.name())
        else:
            self.icon.setStyleSheet("background-color: #FF0000")

        text_layout.addWidget(self.icon, 0, 1)

        text_layout.addWidget(QLabel("Red"), 1, 0)
        text_layout.addWidget(QLabel("txt"), 1, 1)
        text_layout.addWidget(QLabel("Green"), 2, 0)
        text_layout.addWidget(QLabel("txt"), 2, 1)
        text_layout.addWidget(QLabel("Blue"), 3, 0)
        text_layout.addWidget(QLabel("txt"), 3, 1)

        text_frame.setLayout(text_layout)

        outer_layout = QVBoxLayout()
        outer_layout.addWidget(text_frame)

        button = QPushButton("Choose Color")
        button.clicked.connect(self.button_click)
        outer_layout.addWidget(button)

        self.setLayout(outer_layout)

    def button_click(self):
        c = QColorDialog.getColor()
        if c is not None and c.isValid():
            print("color chosen", c.name())
            self.color = c
            self.icon.setStyleSheet("background-color: " + c.name())


class VitaminderGui(Vitaminder):
    def __init__(self):
        Vitaminder.__init__(self)
        self.main_window = None
        self.led_vit_widget = None
        self.led_sys_widget = None

    def send_button_clicked(self):
        # TODO make sure the serial port is connected
        print("send button clicked")

        print("brightness:", self.led_brightness)
        print("vit:")
        print("\tr:", self.led_vit_widget.color.red())
        print("\tg:", self.led_vit_widget.color.green())
        print("\tb:", self.led_vit_widget.color.blue())
        print("sys:")
        print("\tr:", self.led_sys_widget.color.red())
        print("\tg:", self.led_sys_widget.color.green())
        print("\tb:", self.led_sys_widget.color.blue())


        #v = self.led_vit_widget.color.

        self.serial_port.write(
            bytes([1, self.led_brightness,
                   self.led_vit_widget.color.red(), self.led_vit_widget.color.green(), self.led_vit_widget.color.blue(),
                   self.led_sys_widget.color.red(), self.led_sys_widget.color.green(), self.led_sys_widget.color.blue()]))
        print("done sending")

        # TODO handle failed ack
        rsp = self.serial_port.read(8)
        if rsp[0] == 0x01:
            print("have LED response")
        else:
            print("have unknown response")

    def create_gui(self):

        port_frame = SerialConnectionWidget(vitaminder=self)

        self.led_vit_widget = LEDColorWidget(title="Vitaminder LED", color=QColor("#FF0000"))
        self.led_sys_widget = LEDColorWidget(title="System LED")

        led_frame = QWidget()
        led_layout = QHBoxLayout()
        led_layout.addWidget(self.led_vit_widget)
        led_layout.addWidget(self.led_sys_widget)
        led_frame.setLayout(led_layout)

        send_button = QPushButton("Send LED Message")
        send_button.clicked.connect(self.send_button_clicked)


        central_frame = QWidget()
        central_layout = QVBoxLayout()
        central_layout.addWidget(port_frame)
        central_layout.addWidget(led_frame)
        central_layout.addWidget(send_button)
        central_frame.setLayout(central_layout)

        self.main_window = QMainWindow()
        self.main_window.setCentralWidget(central_frame)
        self.main_window.setWindowTitle("Vitaminder")
        self.main_window.show()


if __name__ == "__main__":
    app = QApplication([])

    gui = VitaminderGui()
    gui.create_gui()

    app.exit(app.exec_())