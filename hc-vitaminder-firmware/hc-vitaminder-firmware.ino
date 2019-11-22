// Basic Bluetooth sketch HC-05_AT_MODE_01
// Communicate with a HC-05 using the serial monitor
//
// The HC-05 defaults to communication mode when first powered on you will
// need to manually enter AT mode
// The default baud rate for AT mode is 38400
// See www.martyncurrey.com for details



/* There are three serial connections in this system, so it gets very confusing and you need to sort out all the baud rates or it flops.
    1) Serial - wired USB connection between host PC and arduino. this is essentially a debugging connection
    2) bt - hardwired circuit conn between arduino and HC-05
    3) Bluetooth radio - external to this sketch, there is the serial comm port between the HC-05 and whatever bluetooth device (host PC, rpi zero, android, iphone)
*/

#include <FastLED.h>

#include <HC_BouncyButton.h>

#include <SoftwareSerial.h>
SoftwareSerial bt(2, 3); // (RX/TX)
/* circuit connection between arduino and HC-05:
    direct - arduino pin 2 (software RX) to HC-05 tx
    voltage divider - arduino pin 3 (soft TX) to HC-05 rx
*/

byte c = ' ';

byte rsp[] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};
byte req[] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};

const int MSG_SIZE = 8;

const byte MSG_REQ_HEARTBEAT = 0x00;
const byte MSG_RSP_HEARTBEAT = 0x01;
const byte MSG_REQ_SET_LED = 0x02;
const byte MSG_RSP_SET_LED = 0x03;
const byte MSG_BOOT = 0x04;
const byte MSG_BUTTON = 0x06;

const int PIXEL_PIN = 8;
const int PIXEL_COUNT = 4;
const int DEFAULT_BRIGHTNESS = 128;
CRGB pixels[PIXEL_COUNT];

const int SYS_PIX = 0;
const int VIT_PIX = 1;

const int OK_BUTTON_PIN = 6;
const int SN_BUTTON_PIN = 7;

BouncyButton okButton = BouncyButton(OK_BUTTON_PIN);
BouncyButton snButton = BouncyButton(SN_BUTTON_PIN);

// if no hartbeat received for 5 minutes, enter error state
const int SOLITUDE_ERROR_DURATION = 5 * 60 * 1000;
//const int SOLITUDE_ERROR_DURATION = 10 * 1000;
unsigned long solitude_millis = 0;
boolean solitude_error_state = false;

void setup() {
  Serial.begin(9600);
  Serial.println(F("Select 'Both NL & CR' for best viewing of bluetooth comms"));

  // init() will set the pinMode for us
  okButton.init();
  snButton.init();

  // HC-05 default serial speed for AT mode is 38400
  //bt.begin(38400);
  bt.begin(9600);


  FastLED.addLeds<NEOPIXEL, PIXEL_PIN>(pixels, PIXEL_COUNT);
  FastLED.setBrightness(DEFAULT_BRIGHTNESS);

  // Do a little light show while waiting to send the BOOT message
  for (int i = 0; i < 6; i++) {

    pixels[VIT_PIX] = CRGB::Black;
    pixels[SYS_PIX] = CRGB::Pink;
    FastLED.show();
    delay(250);
    pixels[VIT_PIX] = CRGB::Pink;
    pixels[SYS_PIX] = CRGB::Black;
    FastLED.show();
    delay(250);
  }
  pixels[VIT_PIX] = CRGB::Black;
  pixels[SYS_PIX] = CRGB::Black;
  FastLED.show();

  // send a BOOT message so the host will send us current state info
  rsp[0] = MSG_BOOT;
  for (int x = 1; x < MSG_SIZE; x++) {
    // technically all bytes after the first are ignored, but we like to be cute
    rsp[x] = MSG_BOOT;
  }
  bt.write(rsp, MSG_SIZE);

}

void loop() {

  int len = 0;

  if ((millis() - solitude_millis) > SOLITUDE_ERROR_DURATION  && !solitude_error_state) {
    solitude_error_state = true;

    clearPixels();

    pixels[SYS_PIX] = CRGB::Red;
    FastLED.show();
  }

  boolean haveButtonPress = false;
  if (okButton.update() && !okButton.getState()) {
    // someone pressed the okButton
    Serial.println("ok button press");
    haveButtonPress = true;
  }

  if (snButton.update() && !snButton.getState()) {
    // someone pressed the snooze button
    Serial.println("sn button press");
    haveButtonPress = true;
  }

  if (haveButtonPress) {
    // either button triggers the same message, which contains state for both buttons
    rsp[0] = MSG_BUTTON;
    // remember - pull up resistor means getState()==1 when not pressed, and 0 when pressed
    rsp[1] = okButton.getState() ? 0x00 : 0x01;
    rsp[2] = snButton.getState() ? 0x00 : 0x01;
    for (int x = 3; x < MSG_SIZE; x++) {
      // these are ignored
      rsp[x] = MSG_BUTTON;
    }

    bt.write(rsp, MSG_SIZE);
  }

  if (bt.available()) {
    len = bt.readBytes(req, MSG_SIZE);
    if (len == MSG_SIZE) {
      Serial.println("received full msg");

      if (req[0] == MSG_REQ_HEARTBEAT) {
        Serial.println("msg 0 - heartbeat");

        haveContact();

        rsp[0] = MSG_RSP_HEARTBEAT;
        rsp[1] = FastLED.getBrightness();
        rsp[2] = pixels[VIT_PIX].r;
        rsp[3] = pixels[VIT_PIX].g;
        rsp[4] = pixels[VIT_PIX].b;
        rsp[5] = pixels[SYS_PIX].r;
        rsp[6] = pixels[SYS_PIX].g;
        rsp[7] = pixels[SYS_PIX].b;

        bt.write(rsp, MSG_SIZE);

      } else if (req[0] == MSG_REQ_SET_LED) {
        Serial.println("msg 1 - LED update");

        haveContact();

        // byte 1 - brightness
        FastLED.setBrightness(req[1]);

        // byte 2 - pixel mask
        Serial.print("\tpixel mask ");
        Serial.println(req[2], BIN);
        
        for (int pixelIdx=0; pixelIdx<PIXEL_COUNT; pixelIdx++) {
          if (req[2] & (0x01 << pixelIdx)) {
            Serial.print("\tmessage applies to pixel ");
            Serial.println(pixelIdx);
            pixels[pixelIdx] = CRGB(req[3], req[4], req[5]);
          }
        }

        // bytes 3-5 - rgb

        // bytes 6,7 have blink_off and blink_on durations (div by 10)
        // TODO implement blinking

        // the hardware is wired Vita LED on index=1, and Sys LED on index=0
        // pixels[VIT_PIX] = CRGB(req[2], req[3], req[4]);

        FastLED.show();

        rsp[0] = MSG_RSP_SET_LED;
        rsp[1] = FastLED.getBrightness();
        rsp[2] = pixels[VIT_PIX].r;
        rsp[3] = pixels[VIT_PIX].g;
        rsp[4] = pixels[VIT_PIX].b;
        rsp[5] = pixels[SYS_PIX].r;
        rsp[6] = pixels[SYS_PIX].g;
        rsp[7] = pixels[SYS_PIX].b;

        bt.write(rsp, MSG_SIZE);

      } else {
        Serial.println("unknown message ID received");
      }


    } else {
      Serial.print("received partial msg of len: ");
      Serial.println(len);
    }
  }

  // Echo anything received by the HC-05 to the serial monitor
  //  if (bt.available()) {
  //    c = bt.read();
  //    Serial.write(c);
  //    if (c == 0x00) {
  //      digitalWrite(8, !digitalRead(8));
  //   }
  //  }

  // Echo anything received from the serial monitor to the bluetooth HC-05
  if (Serial.available()) {
    c = Serial.read();
    bt.write(c);
  }
}

void clearPixels() {
  for (int i=0; i<PIXEL_COUNT; i++) {
    pixels[i] = CRGB::Black;
  }
  FastLED.show();
}

void haveContact() {
  // erase any error condition we were previously reporting
  if (solitude_error_state) {
    clearPixels();
  }
  
  //pixels[SYS_PIX] = CRGB::Green;
  //FastLED.show();
  
  solitude_millis = millis();
  solitude_error_state = false;
}
