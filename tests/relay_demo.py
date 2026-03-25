#!/usr/bin/python
# -*- coding:UTF-8 -*-

from RPi import GPIO
import time

Relay = [5, 6, 13, 16, 19, 20, 21, 26]

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

for i in range(0,8):
    GPIO.setup(Relay[i], GPIO.OUT)
    GPIO.output(Relay[i], GPIO.HIGH)

try:
    while True:
        for i in range(8):
            GPIO.output(Relay[i], GPIO.LOW)
            time.sleep(0.5)
        for i in range(8):
            GPIO.output(Relay[i], GPIO.HIGH)
            time.sleep(0.5)


except:
    GPIO.cleanup()


