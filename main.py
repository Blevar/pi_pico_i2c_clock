import network
import ntptime
import utime
import time
import struct
import socket
import machine
from machine import Pin, I2C, PWM
from ssd1306 import SSD1306_I2C
from picozero import Speaker, Button
import _thread
from ds3231 import DS3231

time.sleep(5)

NTP_DELTA = 2208988800
host = "pool.ntp.org"

def set_time(hours_offset):
    NTP_QUERY = bytearray(48)
    NTP_QUERY[0] = 0x1B
    addr = socket.getaddrinfo(host, 123)[0][-1]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(1)
        res = s.sendto(NTP_QUERY, addr)
        msg = s.recv(48)
    finally:
        s.close()
    val = struct.unpack("!I", msg[40:44])[0]
    t = val - NTP_DELTA + hours_offset * 3600  
    tm = time.gmtime(t)
    machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5], 0))

# Initialize buttons
button_up = Button(5)
button_down = Button(3)
button_enter = Button(4)
button_back = Button(2)

# Initialize speakers
speaker = Speaker(18)

# I2C settings
i2c = I2C(0, scl=Pin(1), sda=Pin(0), freq=400000)

# Initialize DS3231
rtc_ds3231 = DS3231(i2c)

# TCA9548A address
TCA9548A_ADDRESS = 0x70

# Initialize the main display
big_display = SSD1306_I2C(128, 64, i2c, 0x3D)

# List for storing digit bitmaps
digit = []

# Global variable for IP address
ip_address = None

# Initialize button states
button_states = {
    'up': False,
    'down': False,
    'enter': False,
    'back': False
}

def set_local_time_from_ds3231():
    dt = rtc_ds3231.DateTime()  # (year, month, day, weekday, hour, minute, second)
    # Correctly map the returned tuple to the RTC's expected input
    # machine.RTC().datetime((dt[0], dt[1], dt[2], dt[3] + 1, dt[4], dt[5], dt[6], 0))

# Define callback functions for buttons
def button_up_pressed():
    button_states['up'] = True
    log_message("Button UP pressed")
    
def button_up_released():
    button_states['up'] = False

def button_down_pressed():
    button_states['down'] = True
    log_message("Button DOWN pressed")
    
def button_down_released():
    button_states['down'] = False

def button_enter_pressed():
    button_states['enter'] = True
    log_message("Button ENTER pressed")
    
def button_enter_released():
    button_states['enter'] = False

def button_back_pressed():
    button_states['back'] = True
    log_message("Button BACK pressed")
    
def button_back_released():
    button_states['back'] = False

# Attach callbacks to button events
button_up.when_pressed = button_up_pressed
button_up.when_released = button_up_released
button_down.when_pressed = button_down_pressed
button_down.when_released = button_down_released
button_enter.when_pressed = button_enter_pressed
button_enter.when_released = button_enter_released
button_back.when_pressed = button_back_pressed
button_back.when_released = button_back_released

# Function to update logs on the main display
def log_message(message):
    now = utime.localtime()
    date_str = '{:02d}/{:02d}/{:04d}'.format(now[2], now[1], now[0])
    
    big_display.fill(0)
    
    # Center the date
    date_width = len(date_str) * 8  # Estimated text width in pixels (8 pixels per character)
    date_x = (128 - date_width) // 2  # Center the text
    big_display.text(date_str, date_x, 0)
    
    # Display IP address if available
    if ip_address:        
        big_display.text(ip_address, 0, 10)  # Positioned below the date
    
    # Draw a horizontal line
    big_display.hline(0, 21, 128, 1)  # Line just below the IP address
    
    # Display logs
    log_lines = wrap_text(message, 16)  # 16 characters per line, adjust based on font
    y = 24  # Starting Y position for logs
    for line in log_lines:
        big_display.text(line, 0, y)
        y += 10
        if y > 54:  # Scroll logs
            big_display.scroll(0, 0)
    
    big_display.show()
    print("Logged to big screen: " + message)

# Function to wrap text for logs
def wrap_text(text, max_width):
    words = text.split()
    lines = []
    current_line = ''
    for word in words:
        if len(current_line) + len(word) + 1 > max_width:
            lines.append(current_line)
            current_line = word
        else:
            if current_line:
                current_line += ' '
            current_line += word
    if current_line:
        lines.append(current_line)
    return lines

# Function to select a channel on the TCA9548A multiplexer
def tca_select(channel):
    if channel > 7:
        return
    i2c.writeto(TCA9548A_ADDRESS, bytearray([1 << channel]))

# Function to initialize the display on a given channel
def init_display(channel):
    tca_select(channel)
    display = SSD1306_I2C(128, 32, i2c)
    return display

# Initialize all displays
displays = []
for i in range(8):
    try:
        displays.append(init_display(i))
        print(f"Display {i} initialized successfully.")
        log_message(f"Display {i} initialized successfully.")
    except Exception as e:
        print(f"Failed to initialize display {i}: {e}")  
        log_message(f"Failed to initialize display {i}: {e}")

# Function to load Wi-Fi configuration from a file
def load_wifi_config(filename):
    config = {}
    try:
        with open(filename, 'r') as file:
            for line in file:
                key, value = line.strip().split('=')
                config[key] = value
    except OSError as e:
        log_message("Failed to load Wi-Fi config: {}".format(e))
    return config

# Get Wi-Fi credentials
config = load_wifi_config('wifi_config.txt')
SSID = config.get('SSID', '')
PASSWORD = config.get('PASSWORD', '')

# Function to connect to Wi-Fi
def connect_wifi(ssid, password):
    global ip_address
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(ssid, password)
    log_message("Connecting to WiFi...")
    
    # Wait until connected
    while not wlan.isconnected():
        pass
    
    ip_address = wlan.ifconfig()[0]
    log_message('Connected to WiFi ' + ip_address)
    log_message('IP Address: {}'.format(ip_address))

# Function to fetch time from NTP server
def get_ntp_time():
    global ntp_time
    for i in range(5):  # Retry up to 5 times
        try:
            set_time(2)
            ntp_time = utime.localtime()            
         
            time_str = '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(
                ntp_time[0], ntp_time[1], ntp_time[2], 
                ntp_time[3], ntp_time[4], ntp_time[5]
            )
            hour_str = '{:02d}:{:02d}:{:02d}'.format(                
                ntp_time[3], ntp_time[4], ntp_time[5]
            )
            log_message(f"NTP time set successfully at attempt: {i + 1} at {hour_str}.")
            
            # Update DS3231 with NTP time
            rtc_ds3231.DateTime(ntp_time)        
            return  # Exit the function on success
        except Exception as e:
            log_message(f"Failed to get NTP time on attempt: {i + 1} {e}")
            time.sleep(5)
    log_message("Failed to get NTP time after 5 attempts.")

# Function to load bitmap from file
def load_bitmap_from_file(filename):
    with open(filename, 'rb') as f:
        bitmap = f.read()
    return bitmap

# Load bitmaps for digits and colon
colon = load_bitmap_from_file("colon_128x32.bin")
log_message("Loaded Colon bitmap")
for i in range(10):
    file_name = "digit_" + str(i) + "_128x32.bin"
    digit.append(load_bitmap_from_file(file_name))
    log_message("Loaded bitmap for digit " + str(i))

# Function to display colon bitmap
def display_colon(display, show_colon):
    display.fill(0)
    if show_colon:
        bitmap = colon
        for y in range(32):
            for x in range(128):
                if bitmap[(x + y * 128) // 8] & (1 << (7 - (x % 8))):
                    display.pixel(x, y, 1)

# Function to display digit bitmap on screen
def display_digit(display, digit_char):
    bitmap = digit[int(digit_char)]
    display.fill(0)
    for y in range(32):
        for x in range(128):
            if bitmap[(x + y * 128) // 8] & (1 << (7 - (x % 8))):
                display.pixel(x, y, 1)

# Function to refresh displays
def refresh_displays(display_list, indices):
    for i in indices:
        tca_select(i)
        display_list[i].show()

# Function to display time on screens
def display_time():    
    previous_time = [""] * 8
    while True:
        refresh_list = []
        current_time = utime.localtime()
        hours = '{:02d}'.format(current_time[3])
        minutes = '{:02d}'.format(current_time[4])
        seconds = '{:02d}'.format(current_time[5])
        
        # Create list of digits to display
        time_digits = [
            hours[0], hours[1],
            ':',  # Colon
            minutes[0], minutes[1],
            ':',  # Colon
            seconds[0], seconds[1]
        ]
        
        # Display hours on screens 1 and 2
        for i in range(2):
            if previous_time[i] != time_digits[i]:
                tca_select(i)
                display_digit(displays[i], time_digits[i])
                previous_time[i] = time_digits[i]
                refresh_list.append(i)  
        
        # Display minutes on screens 4 and 5
        for i in range(3, 5):
            tca_select(i)
            if previous_time[i] != time_digits[i]:
                display_digit(displays[i], time_digits[i])
                previous_time[i] = time_digits[i]
                refresh_list.append(i)

        # Display seconds on screens 7 and 8
        for i in range(6, 8):
            tca_select(i)
            if previous_time[i] != time_digits[i]:
                display_digit(displays[i], time_digits[i])
                previous_time[i] = time_digits[i]
                refresh_list.append(i)
                
        # Flashing colon on screens 3 and 6
        show_colon = current_time[5] % 2 == 0
        if previous_time[5] != (":" if show_colon else " "):
            for i in [2, 5]:
                tca_select(i)
                display_colon(displays[i], show_colon)
                refresh_list.append(i)
            previous_time[5] = ":" if show_colon else " "
            
        refresh_displays(displays, refresh_list)              
        
        #if ip_address != None and seconds[1] == "0":
        #    fetch_and_display_weather()
            
        time.sleep(0.1) 

# Function to fetch and display weather data
def fetch_and_display_weather():
    global ip_address
    weather_url = "http://192.168.50.200"
    while True:
        try:
            print("socket.getaddrinfo")
            addr = socket.getaddrinfo('192.168.50.200', 80)[0][-1]
            s = socket.socket()
            print("s.connect")
            s.connect(addr)
            print("s.send")
            s.send(b"GET / HTTP/1.1\r\nHost: 192.168.50.200\r\nConnection: close\r\n\r\n")
            
            print("response")
            response = s.recv(4096)
            print("s.close")
            s.close()
            
            # Parse the response for temperature, humidity, and pressure
            response = response.decode('utf-8')
            temp_start = response.find('Temperature:') + len('Temperature:')
            temp_end = response.find('°C', temp_start)
            temperature = response[temp_start:temp_end].strip()
            
            hum_start = response.find('Humidity:') + len('Humidity:')
            hum_end = response.find('%', hum_start)
            humidity = response[hum_start:hum_end].strip()
            
            pres_start = response.find('Pressure:') + len('Pressure:')
            pres_end = response.find('hPa', pres_start)
            pressure = response[pres_start:pres_end].strip()
            
            #big_display.fill(0)
            #big_display.text(f"Temp: {temperature} °C", 0, 0)
            #big_display.text(f"Hum: {humidity} %", 0, 10)
            #big_display.text(f"Pres: {pressure} hPa", 0, 20)
            #big_display.show()
            
            print("Temp: " + temperature + "°C")
            print("Hum: " + humidity + "%")
            print("Pres: " + pressure + "hPa")
            
            log_message(f"Weather - Temp: {temperature} °C, Hum: {humidity} %, Pres: {pressure} hPa")
        
        except Exception as e:
            log_message(f"Failed to fetch weather data: {e}")
            
def display_system_time():
    now = utime.localtime()
    time_str = '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(
        now[0], now[1], now[2], now[3], now[4], now[5]
    )
    
    big_display.fill(0)
    big_display.text(time_str, 0, 0)
    big_display.show()
    print("Displayed system time: " + time_str)
    
def display_ds3231_time():
    dt = rtc_ds3231.DateTime()
    time_str = '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(
        dt[0], dt[1], dt[2], dt[3], dt[4], dt[5]
    )
    
    big_display.fill(0)
    big_display.text("DS3231 Time:", 0, 0)
    big_display.text(time_str, 0, 10)
    big_display.show()
    print("Displayed DS3231 time: " + time_str)

# Main program loop
try:
    log_message("Starting initialization...")
    
    set_local_time_from_ds3231()
    
    # Start time and weather threads
    _thread.start_new_thread(display_time, ())
    
    log_message("Speaker test")
    speaker.play(523, 1)
    speaker.play(623, 0.2)
    
    connect_wifi(SSID, PASSWORD)
    get_ntp_time()
    
    log_message("Initialization complete.")
    
    # Main thread can perform other tasks or just sleep
    while True:
        # Check button states and take action
        if button_states['up']:
            log_message("Button UP is held down.")
            refresh_list = []
            for i in range(8):
                refresh_list.append(i)
            refresh_displays(displays, refresh_list)
            # Add functionality for button_up here
            
        if button_states['down']:
            log_message("Button DOWN is held down.")
            display_system_time()
            # Add functionality for button_down here
            
        if button_states['enter']:
            log_message("Button ENTER is held down.")
            get_ntp_time()
            # Add functionality for button_enter here
            
        if button_states['back']:
            log_message("Button BACK is held down.")
            display_ds3231_time()
            # Add functionality for button_back here
            
        time.sleep(0.1)

except KeyboardInterrupt:
    log_message("Program interrupted.")