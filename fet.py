import lib8mosind
from time import sleep

for i in range(10):
    lib8mosind.set_pwm(0, 1, 1.)  # channel 0, 1kHz, 50% duty cycle
    sleep(0.5)  # Keep the PWM signal active for 1 second
    print(lib8mosind.get_pwm(0, 1))  # Get the current PWM value for channel 0
    sleep(0.5)  # Wait for 1 second before the next activation
    lib8mosind.set_pwm(0, 1, 0)  # Stop the PWM signal on channel 0
    sleep(0.5)  # Wait for 1 second before the next activation
    print(lib8mosind.get_pwm(0, 1))  # Get the current PWM value for channel 0
    sleep(0.5)  # Wait for 1 second before the next activation
