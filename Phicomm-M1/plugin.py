# coding=UTF-8
# Phicomm M1 Python Plugin
#
# Author: Zack & xiaoyao9184
#
"""
<plugin 
    key="Phicomm-M1"
    name="Phicomm M1 Receiver"
    author="Zack & xiaoyao9184"
    version="1.3"
    externallink="https://www.domoticz.cn/forum/viewtopic.php?f=11&t=165">
    <params>
        <param field="Mode1" label="Debug" width="200px">
            <options>
                <option label="None" value="none" default="none"/>
                <option label="Debug(Only Domoticz)" value="debug"/>
                <option label="Debug(Attach by ptvsd)" value="ptvsd"/>
            </options>
        </param>
        <param field="Mode2" label="repeatTime(s)" width="30px" required="true" default="0"/>
        <param field="Mode3" label="Remote IP" width="100px" default="47.102.38.171"/>
        </params>
</plugin>
"""

# Fix import of libs installed with pip as PluginSystem has a wierd pythonpath...
import os
import sys
import site
for mp in site.getsitepackages():
    sys.path.append(mp)

import Domoticz
import socket
import io
import struct
import json
import re
import binascii

class plugin:
    serverConn = None
    clientConn = None
    deviceMacTag = {}
    clientConns = {}
    serverConns = {}
    pattern = r"(\{.*?\})"
    intervalTime = 0
    heartBeatFreq = 10
    brightness_hex = "aa 2f 01 e0 24 11 39 8f 0b 00 00 00 00 00 00 00 00 b0 f8 93 11 42 0e 00 3d 00 00 02 7b 22 62 72 69 67 68 74 6e 65 73 73 22 3a 22 %s 22 2c 22 74 79 70 65 22 3a 32 7d ff 23 45 4e 44 23"
    heartbeat_hex = "aa 2f 01 e0 24 11 39 8f 0b 00 00 00 00 00 00 00 00 b0 f8 93 11 42 0e 00 37 00 00 02 7b 22 74 79 70 65 22 3a 35 2c 22 73 74 61 74 75 73 22 3a 31 7d ff 23 45 4e 44 23"
    
    dict_value = {'0': '0', '10': '100', '20': '25'}

    # Update Device into DB
    def updateDevice(self, device, nValue, sValue):
        if device.nValue != nValue or device.sValue != sValue:
            device.Update(nValue=nValue, sValue=str(sValue))
            Domoticz.Log("Update "+":'" + str(nValue)+" "+str(sValue)+"' ("+device.Name+")")

    def createAndUpdateDevice(self, ip, data):
        Domoticz.Debug("Device count: " + str(len(Devices)))
        deviceTag = self.generateIdentityTag(ip)
        msg = self.parseJsonData(data)
        
        jsonData = None
        if ('status' in msg):
            jsonData = msg['status']

        #create dimmer
        deviceIdSelector = deviceTag + "_Selector"
        device = self.getExistDevice(deviceIdSelector)
        if not device:
            Options =   {    
                "LevelActions"  :"||||" , 
                "LevelNames"    :"Off|On|Dark" ,
                "LevelOffHidden":"false",
                "SelectorStyle" :"0"
            }
            unit = len(Devices) + 1
            Domoticz.Device(
                Name=ip + "_Selector", 
                Unit=unit, 
                TypeName="Selector Switch", 
                Switchtype=18, 
                Options=Options, 
                DeviceID=deviceIdSelector, 
                Used=1).Create()

        if jsonData:
            for i in range(4):
                deviceId = deviceTag + str(i)
                nValue = 1
                sValue = float(jsonData[self.index_to_key(i)])
                device = self.getExistDevice(deviceId)
                if i == 3: #fix hcho value
                    sValue = sValue / 1000
                elif i == 1: #fix humidity
                    nValue = int(sValue)
                    if nValue < 46:
                        sValue = 2        #dry
                    elif nValue > 70:
                        sValue = 3        #wet
                    else:
                        sValue = 1        #comfortable
                if device:
                    self.updateDevice(device,nValue, sValue)
                else:
                    deviceNum = len(Devices) + 1
                    if i < 2:
                        Domoticz.Device(
                            Name=ip + "_" + self.index_to_key(i), 
                            Unit=deviceNum, 
                            TypeName=self.index_to_key(i).capitalize(), 
                            DeviceID=deviceId, 
                            Used=1).Create()
                    else:
                        Domoticz.Device(Name=ip + "_" + self.index_to_key(i),  
                        Unit=deviceNum, 
                        TypeName="Custom", 
                        Options={"Custom":self.measure_to_str(i)}, 
                        DeviceID=deviceId, 
                        Used=1).Create()

        # sleep device
        # deviceIdSleep = deviceTag + '_Sleep'
        # device = self.getExistDevice(deviceIdSleep)
        # if not device:
        #     unit = len(Devices) + 1
        #     Domoticz.Device(
        #         Name=ip + "_Sleep", 
        #         Unit=unit, 
        #         TypeName="Selector Switch", 
        #         Switchtype=18, 
        #         Options=Options, 
        #         DeviceID=deviceIdSleep, 
        #         Used=1).Create()

    # only update device
    def updateSettingDevice(self, deviceMac, jsonData):
        deviceTag = self.deviceMacTag[deviceMac]
        if 'sleep' in jsonData:
            deviceIdSleep = deviceTag + "_Sleep"
            device = self.getExistDevice(deviceIdSleep)
            # TODO
            # unit = device.Unit
            # self.updateDeviceSleep(
            #     unit, 
            #     jsonData['sleep'], 
            #     jsonData['startTime'], 
            #     jsonData['endTime'])
        elif 'brightness' in jsonData:
            deviceIdSelector = deviceTag + "_Selector"
            device = self.getExistDevice(deviceIdSelector)
            unit = device.Unit
            self.updateDeviceBrightness(
                unit, 
                jsonData['brightness'])

    def updateDeviceBrightness(self, unit, value):
        level = list(self.dict_value.keys())[list(self.dict_value.values()).index(str(value))]
        self.updateDevice(Devices[unit],2,level)
        return

    def updateDeviceSleep(self, unit, sleep, startTime, endTime):
        # TODO update sleep device
        return

    def sendCommandBrightness(self, unit, parameter, level):
        value = self.dict_value[str(level)]
        deviceTag = Devices[unit].DeviceID.replace('_Selector', '')
        if deviceTag in self.clientConns:
            hexCommand = self.brightness_hex%(self.stringToHex(value))
            self.clientConns[deviceTag].Send(bytes.fromhex(hexCommand))
            self.updateDevice(Devices[unit],2,level)

    def sendCommandSleep(self, unit, parameter, level):
        deviceTag = Devices[unit].DeviceID.replace('_Sleep', '')
        if deviceTag in self.clientConns:
            hexCommand = self.brightness_hex%(self.stringToHex(value))
            self.clientConns[deviceTag].Send(bytes.fromhex(hexCommand))
            # TODO update sleep device
            # self.updateDevice(Devices[unit],2,level)
    

    def generateIdentityTag(self, ip):
        identity = ip.replace('.','')
        return identity[len(identity)-8:]

    def getExistDevice(self, identity):
        for x in Devices:
            if str(Devices[x].DeviceID) == identity:
                return Devices[x]
        return None

    def parseJsonData(self,data):
        result = {
            "head": None,
            "mac": None,
            "command": None,
            "tail": None
        }

        reader = io.BytesIO(data)
        # head
        head = reader.read(17)
        result['head'] = head

        # mac
        mac = reader.read(6)
        result['mac'] = mac.hex()

        # length
        lengthArray = reader.read(2)
        length = struct.unpack('>H',lengthArray)[0]

        if length == len(data):
            # when server send to client length is packet total length
            # reader.tell() is length of(head + id + length)
            # 0x1F = reader.tell() + length of(tail)
            # 0x1F = 25 + 6
            length = length - reader.tell() - 6

        # info
        infoArray = reader.read(length)
        infoReader = io.BytesIO(infoArray)

        infoReader.seek(1)
        commandArray = infoReader.read(2)
        command = struct.unpack('>H',commandArray)[0]
        result['command'] = command
        if command == 4:
            statusArray = infoArray[3:]
            jsonStr = statusArray.decode()
            result['status'] = json.loads(jsonStr)
        if command == 2:
            statusArray = infoArray[3:]
            jsonStr = statusArray.decode()
            result['set'] = json.loads(jsonStr)
        else:
            unknowArray = infoArray[3:]
            result['unknow'] = unknowArray

        # tail
        if (reader.read(1) == b'\xff'):
            if (reader.read(1) == b'\x23'):
                tail = reader.read(3)
                if (reader.read(1) == b'\x23'):
                    result['tail'] = tail

        return result

    def measure_to_str(self, arg):
        keys = {
            0: "1;°C",
            1: "1;%",
            2: "1;μg/m³",
            3: "1;mg/m³",
        }
        return keys.get(arg, "null")

    def index_to_key(self, arg):
        keys = {
            0: "temperature",
            1: "humidity",
            2: "value",
            3: "hcho",
        }
        return keys.get(arg, "temperature")

    def stringToHex(self, str):
        r = ''
        hex = binascii.hexlify(str.encode()).decode('utf-8')
        for i, c in enumerate(hex):
            r = r + c
            if i % 2 == 1:
                r = r + ' '
        return r


    def onStart(self):
        # Debug
        self.debug = 0
        if (Parameters["Mode1"] != "none"):
            Domoticz.Debugging(1)
            self.debug = 1
        
        if (Parameters["Mode1"] == 'ptvsd'):
            Domoticz.Log("Debugger ptvsd started, use 0.0.0.0:5678 to attach")
            import ptvsd 
            ptvsd.enable_attach()
            ptvsd.wait_for_attach()
        elif (Parameters["Mode1"] == 'rpdb'):
            Domoticz.Log("Debugger rpdb started, use 'telnet 0.0.0.0 4444' to connect")
            import rpdb
            rpdb.set_trace()

        # 
        Domoticz.Heartbeat(self.heartBeatFreq)
        self.repeatTime = int(Parameters["Mode2"])
        self.remoteIP = Parameters["Mode3"]
        
        # Server Connection
        self.serverConn = Domoticz.Connection(Name="Data Connection", Transport="TCP/IP", Protocol="None", Port="9000")
        self.serverConn.Listen()

        # Client Connection
        self.clientConn = Domoticz.Connection(Name="Data Send Connection", Transport="TCP/IP", Protocol="None", Address=self.remoteIP, Port="9000")
        self.clientConn.Connect()

    def onStop(self):
        Domoticz.Log("onStop called")
        if self.serverConn.Connected():
            self.serverConn.Disconnect()
        if self.clientConn.Connected():
            self.clientConn.Disconnect()

    def onConnect(self, Connection, Status, Description):
        if (Status == 0):
            Domoticz.Log("Connected successfully to: "+Connection.Address+":"+Connection.Port)
        else:
            Domoticz.Log("Failed to connect ("+str(Status)+") to: "+Connection.Address+":"+Connection.Port+" with error: "+Description)
        Domoticz.Log(str(Connection))

        # server
        if (Connection.Name == 'Data Send Connection'):
            self.serverConns['default'] = Connection
            return

        # client
        deviceTag = self.generateIdentityTag(Connection.Address)
        self.clientConns[deviceTag] = Connection

    def onDisconnect(self, Connection):
        Domoticz.Log("onDisconnect called")
        # server
        if (Connection.Name == 'Data Send Connection'):
            self.serverConns.pop('default')
            self.clientConn.Connect()
            return

        # client
        deviceTag = self.generateIdentityTag(Connection.Address)
        if deviceTag in self.clientConns:
            self.clientConns.pop(deviceTag)
            print("drop connect "+Connection.Address)

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Log("Notification: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)

    def onMessage(self, Connection, Data):
        Domoticz.Log("onMessage called for connection: "+Connection.Address+":"+Connection.Port)    
        
        msg = self.parseJsonData(Data)
        deviceMac = msg['mac']
        if (Connection.Name == 'Data Send Connection'):
            # server
            deviceTag = self.deviceMacTag[deviceMac]
            # update setting
            self.updateSettingDevice(deviceMac, msg['set'])
            # forward
            self.clientConns[deviceTag].Send(Data)
        else:
            # client
            deviceTag = self.generateIdentityTag(Connection.Address)
            self.deviceMacTag[deviceMac] = deviceTag
            # update status
            self.createAndUpdateDevice(Connection.Address,Data)
            # forward
            if 'default' in self.serverConns:
                self.serverConns['default'].Send(Data)

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Log("onCommand called for Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))
        
        if Devices[Unit].DeviceID.endswith('_Selector'):
            self.sendCommandBrightness(Unit, Command, Level)
        elif Devices[Unit].DeviceID.endswith('_Sleep'):
            # TODO control sleep device
            # self.sendCommandSleep(Unit, Command, Level)
            return
        
    def onHeartbeat(self):
        if self.repeatTime == 0:
            return
        self.intervalTime += self.heartBeatFreq
        if self.intervalTime >= self.repeatTime:
            self.intervalTime = 0
            Domoticz.Log("send onHeartbeat....")
            for deviceTag in self.clientConns:
                self.clientConns[deviceTag].Send(bytes.fromhex(self.heartbeat_hex))

global _plugin
_plugin = plugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)

def onMessage(Connection, Data):
    global _plugin
    _plugin.onMessage(Connection, Data)

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    global _plugin
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)

def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()