#!/usr/bin/env python
# encoding: utf-8

"""
logerror.py - Contains a set of functions that facilitate special error 
logs that account for control code and Hardware Module special cases

Created by William Woodall on 2010-04-13.
"""
__author__ = "William Woodall"
__copyright__ = "Copyright (c) William Woodall"

###  Imports  ###

# ROS imports
import roslib; roslib.load_manifest('ax2550_python')
import rospy
from rospy.rostime import Time

# ROS msg and srv imports
from std_msgs.msg import String
from ax2550_python.msg import Encoder
from ax2550_python.msg import LightMode
from ax2550_python.srv import NavMode
from ax2550_python.srv import Move
from geometry_msgs.msg import Twist

# Python Libraries
from threading import Timer, Lock
import time
from time import sleep
import sys
import math

# pySerial
from serial import Serial

# Peer Libraries
from seriallistener import SerialListener
from logerror import logError

###  Classes  ###
class AX2550(object):
    """This class allows you to control an ax2550 motor controller"""
    def __init__(self, serial_port=None):
        """Function called after object instantiation"""
        
    	# Initialize ROS Node
        rospy.init_node('ax2550_driver', anonymous=True)

	   # Get the serial port name
        self.serial_port = serial_port or rospy.get_param('~serial_port', '/dev/ttyUSB0')
        self.wheel_base_length = rospy.get_param('~wheel_base_legth', 0.50)
        self.half_B = self.wheel_base_length / 2.0
        self.max_wheel_velocity = rospy.get_param('~max_wheel_velocity', 1.0) # m/s
        self.max_angular_velocity = 2*self.max_wheel_velocity/self.wheel_base_length # rad/s
        # I'm using this to compensate for wheel's different sizes
        self.motor_range_left = rospy.get_param('~motor_range_left', 127.0) # Relative max motor speed code 
        self.motor_range_right = rospy.get_param('~motor_range_right', 127.0) # Relative max motor speed code
        
        # Try to open and configure the serial port
        self.serial = Serial(self.serial_port)
        self.serial.timeout = 0.05
        self.serial.baud = "9600"
        self.serial.bytesize = 7
        self.serial.parity = "E"
        self.serial.stopbits = 1
        self.serial.close()
        self.serial.open()
        self.keep_alive_timer = None
        self.encoder_timer = None
        self.encoder_rate = 1.0 / 20.0 # TODO: find out what this means
        self.encoder_count = 0
        
        # Setup the lock to synchronize the setting of motor speeds
        self.speed_lock = Lock()
        self.serial_lock = Lock()
        
        # Set the motor speed to zero and start the dead man switch counter measure
        self.left_speed = 0
        self.right_speed = 0
        self.running = True
        self.sync()
        self.move(0, 0)

        self.testing_for_speed = False   # Initially, there is no speed test going on
        
        # Setup a Serial Listener
        self.serial_listener = SerialListener(self.serial)
        self.serial_listener.addHandler(self.isInRCMode, self.sync)
        self.serial_listener.listen()

        # Set default operation mode
        self.toggleMode = 0 # 0 for manual (joystick) mode, 1 for autonomous
        #self.handleNavMode(self.toggleMode); # To set the safety light initially
	
    	# Subscribe to the /cmd_vel topic to listen for motor commands
        rospy.Subscriber('cmd_vel', Twist, self.cmd_velReceived)

    	# Subscribe to the speed_test topic to listen for speed test commands
        rospy.Subscriber('/cata/speed_test', String, self.cmd_speedTestReceived)
        
        # Setup Publisher for publishing encoder data to the /motor_control_encoders topic
        self.encoders_pub = rospy.Publisher('/cata/motor_control_encoders', Encoder)
        
        # Setup Publisher for publishing status related data to the /motor_control_status topic
        self.status_pub = rospy.Publisher('/cata/motor_control_status', String)
        
        # Setup Publisher for publishing navigation mode status (either autonomous or manual) 
        self.nav_mode_pub = rospy.Publisher('/cata/navigation_mode', LightMode)

        # Setup Publisher for publishing navigation mode status as voice 
        self.voice_pub = rospy.Publisher('/cata/cata_voice', String)
        
        # Register the Move service with the handleMove function (Usually from data that comes from joystick commands)
        self.move_srv = rospy.Service('move', Move, self.handleMove)

        # Register the NavMode service with the handleNavMode function (based on button being pressed switches between manual and autonomous mode)
        self.joy_nav_mode_srv = rospy.Service('joy_mode_switch', NavMode, self.handleNavMode)
        
        # Register shutdown function
        rospy.on_shutdown(self.shutdown)
        
        # Start polling the encoders
        self.pollEncoders()
          
        # Handle ros srv requests
        rospy.spin()
        
    def handleMove(self, data):
        """Handles the Move srv requests"""
        if self.toggleMode == 0:
            self.move(data.speed, data.direction)
        return 0

    def handleNavMode(self, data):
        """Handles the NavMode srv requests that toggle between joystick and autonomous modes"""
        self.toggleMode = data.button_toggle # 0 for manual (joystick) mode, 1 for autonomous
    	try:
    	    # Publish the navigation mode as message
    	    if self.toggleMode == 0:
                message = LightMode(autonomous=0)
    	        mode_msg = "CATA is in manual mode!"
            else:
                message = LightMode(autonomous=1)
                mode_msg = "CATA is in autonomous mode!"
            self.voice_pub.publish(String(mode_msg))
            rospy.loginfo(mode_msg)
    	    message.header.stamp = rospy.Time.now()
    	    message.header.frame_id = "0"
    	    
    	    try:
    		    self.nav_mode_pub.publish(message)
    	    except:
                pass
        except ValueError:
            rospy.logerr("Invalid navigation mode data received, skipping this one.")
        except Exception as err:
            logError(sys.exc_info(), rospy.logerr, "Exception while Querying the Autonomous Mode: ")
        return 0 # service must return something
 
    def cmd_speedTestReceived(self, msg):
        """Handles incoming messages from the speed_test topic"""
        if msg.data == "cw": # Turn clockwise
           #rospy.loginfo("Received %s", msg.data) 
           self.setMaxSpeedTest(1)
        if msg.data == "ccw": # Turn counter-clockwise
            self.setMaxSpeedTest(-1)
        if msg.data == "end":
           self.setMaxSpeedTest(0)    

    def cmd_velReceived(self, msg):
        """Handles incoming messages from the cmd_vel topic"""

        if self.toggleMode == 1:  # in autonomous mode
            # rospy.loginfo(str(msg))
            # Extract Vx, Vy, and ang_vel
            v_x = msg.linear.x
            v_y = msg.linear.y
            ang_vel = msg.angular.z
            if ang_vel >= self.max_angular_velocity:
                ang_vel = self.max_angular_velocity
            elif ang_vel < -self.max_angular_velocity:
                ang_vel = -self.max_angular_velocity              
 
            # Calculate the magnitude of the velocity vector, V, and the Radius of Rotation R
            v_linear = math.sqrt((v_x ** 2) + (v_y ** 2))
#            if v_linear == 0:
#                R = 0
#                v_l = ang_vel * (R - self.half_B)
#                v_r = ang_vel * (R + self.half_B)
#            elif ang_vel == 0:
#                v_l = v_x
#                v_r = v_x
#            else:
            wB_over_2 = (self.wheel_base_length*ang_vel)/2
            v_l = v_x - wB_over_2
            v_r = v_x + wB_over_2
            
            # Calculate the difference in velocity between the wheels
#            if R == 0:   # If no radius of rotation, means turning in place
#                dV = 0
            # CARLOS: ^^^^^^ It's good ^^^^^^^^^^
#            else:
#                dV = 2 * ((v_linear * self.wheel_base_length) / R)
            # Calculate the velocity of each wheel
#            if v_linear == 0:  # we are just turning
#                v_l = ang_vel * (R - self.half_B)
#                v_r = ang_vel * (R + self.half_B)
#            elif v_x > 0:  # We are moving straight (forward):
#                v_l = (v_linear - (0.5 * dV))
#                v_r = (v_linear + (0.5 * dV))
#            else:
#                # We are moving straight (backward):
#                # CARLOS: may need review
#                v_l = (-1.0*v_linear + (0.5 * dV))
#                v_r = (-1.0*v_linear - (0.5 * dV))                

                
#            print "V_l = %0.2f" % v_l
#            print "V_r = %0.2f" % v_r
                
            # vvvvvvvvvv CARLOS: It's good! vvvvvvvvvvvvvvv
            # Calculate the percent of max velocity for each wheel
            if v_l == 0:
                speed_left = 0.0
            elif abs(v_l) > self.max_wheel_velocity:
                if v_l > 0:
                    speed_left = 1.0
                else:
                    speed_left = -1.0
            else:
                speed_left = v_l / self.max_wheel_velocity
            if v_r == 0:
                speed_right = 0
            elif abs(v_r) > self.max_wheel_velocity:
                if v_r > 0:
                    speed_right = 1.0
                else:
                    speed_right = -1.0
            else:
                speed_right = v_r / self.max_wheel_velocity
            
            rospy.loginfo("Speed from Twist-> PERCENTAGES:left: %f, right: %f, INPUT SPEEDS: Vx: %f, Vy: %f, ang_vel: %f" % (speed_left, speed_right, v_x, v_y, ang_vel))
            self.setSpeeds(speed_left, speed_right)
    
    def controlCommandReceived(self, msg):
        """Handle's messages received on the /motor_control topic"""
        self.move(msg.speed, msg.direction)
        rospy.logdebug("Move command received on /motor_control topic: %s speed and %s direction" % (msg.speed, msg.direction))
        return 0
        
    def isInRCMode(self, msg):
        """Determines if a msg indicates that the motor controller is in RC mode"""
        if msg != '' and msg[0] == ':':
            # It is an RC message
            rospy.loginfo('Motor Controller appears to be in RC Mode, Syncing...')
            return True
        else:
            return False
    
    def sync(self, msg=None):
        """This function ensures that the motor controller is in serial mode"""
        rospy.loginfo("Syncing MC")
        listening = None
        if hasattr(self, 'serial_listener'):
            listening = self.serial_listener.isListening()
        if listening:
            self.serial_listener.stopListening()
        try:
            self.serial_lock.acquire()
            self.speed_lock.acquire()
            # First clean the buffers out
            sio = self.serial
            sio.flushInput()
            sio.flushOutput()
            sio.flush()
            # Reset the Motor Controller, incase it is in the Serial mode already
            sio.write('\r\n' + '%' + 'rrrrrr\r\n')
            changing_modes = True
            line = ''
            token = sio.read(1)
            while changing_modes:
                line += token
                if token == '\r':
                    if line.strip() != '':
                        pass
                        # print line
                    line = ''
                    sio.write('\r')
                    token = sio.read(1)
                if token == 'O':
                    token = sio.read(1)
                    if token == 'K':
                        changing_modes = False
                else:
                    token = sio.read(1)
        finally:
            self.serial_lock.release()
            self.speed_lock.release()
            if listening:
                self.serial_listener.listen()
        rospy.loginfo('Motor Controller Synchronized')
    
    def shutdown(self):
        """Called when the server shutsdown"""
        self.running = False
        self.serial_listener.join()
        del self.serial_listener
        
    def start(self):
        """Called when Control Code Starts"""
        self.running = True
        self.keepAlive()
    
    def stop(self):
        """Called when Control Code Stops"""
        self.running = False
        if self.keep_alive_timer:
            self.keep_alive_timer.cancel()
    
    def disableKeepAlive(self):
        """Stops any running keep alive mechanism"""
        self.stop()
    
    def decodeEncoderValue(self, data):
        """Decodes the Encoder Value"""
        # Determine if the value is negative or positive
        if data[0] in "01234567": # Positive
            fill_byte = "0"
        else: # Negative
            fill_byte = "F"
        # Fill the rest of the data with the filler byte
        while len(data) != 8:
            data = fill_byte + data
        # Now that the data has 8 Hex characters translate to decimal
        data = int(data, 16)
        if fill_byte == "F": # If negative subtract 2**32
            data -= 4294967296
        # Return the processed data
        return data
    
    def getHexData(self, msg, timeout=0.05):
        """Given a message to send the motor controller it will wait for the next Hex response"""
        if self.serial.isOpen():
            self.serial.write(msg) # Send the given request
            message = ""
            while True: # Data not received
                if not hasattr(self, 'serial_listener'): # In case we are here during a ctrl-C
                    break
                message = self.serial_listener.grabNextUnhandledMessage(timeout) # Get next unhandled Message
                if message == None: # If None, timeout occurred, drop data read
                    break
                if message[0] in 'ABCDEF0123456789': # If if starts with Hex data keep it
                    message = message.strip()
                    break
            return message
        else:
            return None
    
    def pollEncoders(self):
        """Polls the encoder on a period"""

	# Kick off the next polling iteration timer
        if self.running:
            self.encoder_timer = Timer(self.encoder_rate, self.pollEncoders)
            self.encoder_timer.start()
        else:
            return
        encoder_1 = None
        encoder_2 = None
        try:
            # Lock the speed lock
            self.speed_lock.acquire()
            # Lock the serial lock
            self.serial_lock.acquire()
            # Query encoder 1
            encoder_1 = self.getHexData("?Q4\r")
            # Query encoder 2
            encoder_2 = self.getHexData("?Q5\r")
            # Release the serial lock
            self.serial_lock.release()
            # Release the speed lock
            self.speed_lock.release()
            # Convert the encoder data to ints
            if encoder_1 != None:
#                encoder_1 = self.decodeEncoderValue(encoder_1) * -1
                encoder_1 = self.decodeEncoderValue(encoder_1)
            else:
                encoder_1 = 0
            if encoder_2 != None:
#                encoder_2 = self.decodeEncoderValue(encoder_2) * -1
                encoder_2 = self.decodeEncoderValue(encoder_2) 
            else:
                encoder_2 = 0
            # Publish the encoder data
            #header = roslib.msg._Header.Header()
            message = Encoder(left=encoder_1, right=encoder_2)
            message.header.stamp = rospy.Time.now()
            message.header.frame_id = "0"
            
            try:
                self.encoders_pub.publish(message)
            except:
                pass
        except ValueError:
            rospy.logerr("Invalid encoder data received, skipping this one.")
        except Exception as err:
            logError(sys.exc_info(), rospy.logerr, "Exception while Querying the Encoders: ")
            self.encoder_timer.cancel()
    
    def keepAlive(self):
        """This functions sends the latest motor speed to prevent the dead man 
            system from stopping the motors.
        """
        try:
            # Lock the speed lock
            self.speed_lock.acquire()
            # Resend the current motor speeds
            self.__setSpeed(self.left_speed, self.right_speed)
            # Release the speed lock
            self.speed_lock.release()
        except Exception as err:
            logError(sys.exc_info(), rospy.logerr, "Exception in keepAlive function: ")
        if self.running:
            self.keep_alive_timer = Timer(0.4, self.keepAlive)
            self.keep_alive_timer.start()
    
    def move(self, speed=0.0, direction=0.0):
        """Adjusts the motors based on the speed and direction you specify.
            
        Speed and Direction should be values between -1.0 and 1.0, inclusively.
        """
        #Validate the parameters
        if speed < -1.0 or speed > 1.0:
            logError(sys.exc_info(), rospy.logerr, "Speed given to the move() function must be between -1.0 and 1.0 inclusively.")
            return
        if direction < -1.0 or direction > 1.0:
            logError(sys.exc_info(), rospy.logerr, "Direction given to the move() function must be between -1.0 and 1.0 inclusively.")
            return
        #First calculate the speed of each motor then send the commands
#        self.setSpeeds2(speed, direction)
#        return
        #Account for speed
        left_speed = speed
        right_speed = speed
        #Account for direction
        left_speed = right_speed - direction # the +/- of direction depends on joystick's axis values
        right_speed = right_speed + direction # the +/- of direction depends on joystick's axis values
        #Account for going over 1.0 or under -1.0
        if left_speed < -1.0:
            left_speed = -1.0
        if left_speed > 1.0:
            left_speed = 1.0
        if right_speed < -1.0:
            right_speed = -1.0
        if right_speed > 1.0:
            right_speed = 1.0
        #Send the commands
        self.setSpeeds(left=left_speed, right=right_speed)

    def setSpeeds2(self, left=None, right=None):
        """Sets the speed of both motors"""
        # Lock the speed lock
        self.speed_lock.acquire()
        # Resend the current motor speeds
        if left != None:
            self.left_speed = left
        if right != None:
            self.right_speed = right
        self.__setSpeed2(self.left_speed, self.right_speed)
        # Release the speed lock
        self.speed_lock.release()
    
    def __setSpeed2(self, left, right):
        """Actually sends the appropriate message to the motor"""
        speed = right
        direction = left
        # Form the commands
        #Left command
        speed_command = "!"
        if speed < 0:
            speed_command += "A"
        else:
            speed_command += "a"
        speed = int(abs(left) * self.motor_range_left)
        speed_command += "%02X" % speed
        #Right command
        direction_command = "!"
        if direction < 0:
            direction_command += "B"
        else:
            direction_command += "b"
        direction = int(abs(right) * self.motor_range_right)
        direction_command += "%02X" % direction
        # Lock the serial lock
        self.serial_lock.acquire()
        # Send the commands
        self.serial.write(speed_command + '\r')
        self.serial.write(direction_command + '\r')
        # Release the serial lock
        self.serial_lock.release()
    
    def setSpeeds(self, left=None, right=None):
        """Sets the speed of both motors"""
        # Lock the speed lock
        self.speed_lock.acquire()
        # Resend the current motor speeds
        # FIXME: check if this is safe (there may be cases when only one of them is None)
        if left != None and right != None:   
            self.left_speed = left
            self.right_speed = right
            self.__setSpeed(self.left_speed, self.right_speed)
        # Release the speed lock
        self.speed_lock.release()
    
    def setMaxSpeedTest(self, direction):
        """To test maximum velocities"""
        # For example:
        # !B7F  channel 2, 100% forward
        left_command = "!"
        right_command = "!" 
        if direction > 0: # move clockwise
            left_command += "A3F" # 50%, 100% = "A7F"
            right_command += "b3F"# 50%, 100% = "b7F"
        elif direction < 0:
            # move counter-clockwise
            left_command += "a3F" # 50%, 100% = "a7F"
            right_command += "B3F" # 50%, 100% = "B7F"
        else: # stop
            left_command += "A00"
            right_command += "B00"
            
        self.__sendSpeedsToMotorController(left_command, right_command)
        
    def __setSpeed(self, left, right):
        """Composes and sends the appropriate message to the motor"""
        # Speed or position value in 2 Hexadecimal digits from 00 to 7F
        # A: channel 1, forward direction 
        # a: channel 1, reverse direction 
        # B: channel 2, forward direction 
        # b: channel 2, reverse direction

        # Examples:
        # !A00  channel 1 to 0
        # !B7F  channel 2, 100% forward 
        # !a3F  channel 1, 50% reverse


        # Form the commands
        #Left command
        left_command = "!"
        if left < 0:
            left_command += "a"
        else:
            left_command += "A"
        left = int(abs(left) * self.motor_range_left)
        left_command += "%02X" % left   # Convert left percentage value (max is 1.0) into Hex representation
        #Right command
        right_command = "!"
        if right < 0:
            right_command += "b"
        else:
            right_command += "B"
        right = int(abs(right) * self.motor_range_right)
        right_command += "%02X" % right  # Convert left percentage value (max is 1.0) into Hex representation
        self.__sendSpeedsToMotorController(left_command, right_command)
        
    def __sendSpeedsToMotorController(self, left_command, right_command):
        """Actually sends the appropriate speed messages to the motor (2 channels)"""
        # Lock the serial lock
        self.serial_lock.acquire()
        # Send the commands
        self.serial.write(left_command + '\r')
        self.serial.write(right_command + '\r')
        rospy.loginfo("Sent left_command=%s and right_command=%s to motor controller", left_command, right_command)
        # Release the serial lock
        self.serial_lock.release()
        
# end class AX2550    

###  If Main  ###
if __name__ == '__main__':
    AX2550()
