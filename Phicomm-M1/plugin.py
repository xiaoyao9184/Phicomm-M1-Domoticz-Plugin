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
                <option label="Debug(Attach by rpdb)" value="rpdb"/>
            </options>
        </param>
        <param field="Mode2" label="Repeat Time(s)" width="30px" required="true" default="30"/>
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
    clientConns = {}
    proxyConn = None
    proxyConns = {}
    clientMacId = {}
    intervalTime = 0
    heartBeatFreq = 10
    # 22:30
    startTime = 81000
    # 6:30
    endTime = 23400
    
    # pattern = r"(\{.*?\})"
    # brightness_hex = "aa 2f 01 e0 24 11 39 8f 0b 00 00 00 00 00 00 00 00 b0 f8 93 11 42 0e 00 3d 00 00 02 7b 22 62 72 69 67 68 74 6e 65 73 73 22 3a 22 %s 22 2c 22 74 79 70 65 22 3a 32 7d ff 23 45 4e 44 23"
    # heartbeat_hex = "aa 2f 01 e0 24 11 39 8f 0b 00 00 00 00 00 00 00 00 b0 f8 93 11 42 0e 00 37 00 00 02 7b 22 74 79 70 65 22 3a 35 2c 22 73 74 61 74 75 73 22 3a 31 7d ff 23 45 4e 44 23"

    dict_brightness = {'0': '0', '10': '100', '20': '25'}
    dict_sleep = {'Off': 0, 'On': 1}

    def onStart(self):
        # Debug
        self.debug = 0
        if (Parameters["Mode1"] != "none"):
            Domoticz.Debugging(1)
            self.debug = 1
        
        if (Parameters["Mode1"] == 'ptvsd'):
            Domoticz.Log("Debugger ptvsd started, use 0.0.0.0:5678 to attach")
            import ptvsd             
            # signal error on raspberry
            ptvsd.enable_attach()
            ptvsd.wait_for_attach()
        elif (Parameters["Mode1"] == 'rpdb'):
            Domoticz.Log("Debugger rpdb started, use 'telnet 127.0.0.1 4444' on host to connect")
            import rpdb
            rpdb.set_trace()
            # signal error on raspberry
            # rpdb.handle_trap("0.0.0.0", 4444)

        # 
        Domoticz.Heartbeat(self.heartBeatFreq)
        self.repeatTime = int(Parameters["Mode2"])
        self.remoteIP = Parameters["Mode3"]
        
        # Server Connection
        self.serverConn = Domoticz.Connection(Name="Data Connection", Transport="TCP/IP", Protocol="None", Port="9000")
        self.serverConn.Listen()

        # Client Connection 
        if self.remoteIP:
            self.proxyConn = Domoticz.Connection(Name="Proxy Connection", Transport="TCP/IP", Protocol="None", Address=self.remoteIP, Port="9000")
            self.proxyConn.Connect()

    def onStop(self):
        Domoticz.Log("onStop called")
        if self.serverConn.Connected():
            self.serverConn.Disconnect()
        if self.proxyConn is not None and self.proxyConn.Connected():
            self.proxyConn.Disconnect()

    def onConnect(self, Connection, Status, Description):
        Domoticz.Log("onConnect called")
        if (Status == 0):
            Domoticz.Log("Connected successfully to: "+Connection.Address+":"+Connection.Port)
        else:
            Domoticz.Log("Failed to connect ("+str(Status)+") to: "+Connection.Address+":"+Connection.Port+" with error: "+Description)

        # proxy connection
        if (Connection.Name == 'Proxy Connection'):
            self.proxyConns['default'] = Connection
            Domoticz.Log('Cached proxy connection!')
            return

        # client connection
        clientId = self.generateClientIdentity(Connection.Address)
        self.clientConns[clientId] = Connection
        Domoticz.Log('Cached client connection!')

    def onDisconnect(self, Connection):
        Domoticz.Log("onDisconnect called")
        # proxy connection
        if (Connection.Name == 'Proxy Connection'):
            Domoticz.Log("Reconnect proxy connection!")
            self.proxyConns.pop('default')
            self.proxyConn.Connect()
            return

        # client connection
        clientId = self.generateClientIdentity(Connection.Address)
        if clientId in self.clientConns:
            self.clientConns.pop(clientId)
            print("Drop client connection: "+Connection.Address)

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Log("onNotification called: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)

    def onMessage(self, Connection, Data):
        Domoticz.Log("onMessage called for connection: "+Connection.Address+":"+Connection.Port)    
        
        msg = self.parseJsonData(Data)
        mac = msg['mac']
        Domoticz.Log("Message command is " + str(msg['command']) + "mac is " + mac)
        if (Connection.Name == 'Proxy Connection'):
            # proxy msg
            clientId = self.clientMacId[mac]
            # update setting
            self.updateSettingDevice(clientId, msg['set'])
            # forward
            Domoticz.Log("forward data from proxy[default] to client[" + clientId + "]") 
            self.clientConns[clientId].Send(Data)
        else:
            # client msg
            clientId = self.generateClientIdentity(Connection.Address)
            self.clientMacId[mac] = clientId
            # update status
            self.createAndUpdateDevice(clientId,mac,msg)
            # forward
            if 'default' in self.proxyConns:
                Domoticz.Log("forward data from client[" + clientId + "] to proxy[default]")    
                self.proxyConns['default'].Send(Data)
            
            # response heartbeat 
            if msg['command'] == 1:
                Domoticz.Log("Send heartbeat response to client make it report status: "+Connection.Address+":"+Connection.Port)
                self.sendCommandStatus(clientId)

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Log("onCommand called for Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))
        
        if Devices[Unit].DeviceID.endswith('_Brightness'):
            clientId = Devices[Unit].DeviceID.replace('_Brightness', '')
            value = self.dict_brightness[str(Level)]
            self.sendCommandBrightness(clientId, value)
            self.updateDevice(Devices[Unit],2,Level)
        elif Devices[Unit].DeviceID.endswith('_Sleep'):
            clientId = Devices[Unit].DeviceID.replace('_Sleep', '')
            value = self.dict_sleep[Command]
            self.sendCommandSleep(clientId, value)
            self.updateDevice(Devices[Unit],value,Command)
            # TODO control sleep device start end time
        
    def onHeartbeat(self):
        if self.repeatTime == 0:
            return
        self.intervalTime += self.heartBeatFreq
        if self.intervalTime >= self.repeatTime:
            self.intervalTime = 0
            Domoticz.Log("onHeartbeat called")
            for clientId in self.clientConns:
            #     self.clientConns[clientId].Send(bytes.fromhex(self.heartbeat_hex))
                self.sendCommandStatus(clientId)


    # Update device
    def createAndUpdateDevice(self, clientId, clientName, msg):
        Domoticz.Debug("Device count: " + str(len(Devices)))
        
        jsonData = None
        if ('status' in msg):
            jsonData = msg['status']

        # Create brightness device
        deviceIdBrightness = clientId + "_Brightness"
        device = self.getExistDevice(deviceIdBrightness)
        if not device:
            Options =   {    
                "LevelActions"  :"||||" , 
                "LevelNames"    :"Off|On|Dark" ,
                "LevelOffHidden":"false",
                "SelectorStyle" :"0"
            }
            unit = len(Devices) + 1
            Domoticz.Device(
                Name=clientName + "_Brightness", 
                Unit=unit, 
                TypeName="Selector Switch", 
                Switchtype=18, 
                Options=Options, 
                DeviceID=deviceIdBrightness, 
                Used=1).Create()

        # Create Sleep device
        deviceIdSleep = clientId + '_Sleep'
        device = self.getExistDevice(deviceIdSleep)
        if not device:
            unit = len(Devices) + 1
            Domoticz.Device(
                Name=clientName + "_Sleep", 
                Unit=unit, 
                Type = 244, 
                Subtype = 62,
                Image = 9,
                DeviceID=deviceIdSleep, 
                Used=1).Create()

        if jsonData:
            for i in range(4):
                deviceId = clientId + "_" + self.index_to_key(i)
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
                    self.updateDevice(device, nValue, sValue)
                else:
                    deviceNum = len(Devices) + 1
                    if i < 2:
                        Domoticz.Device(
                            Name=clientName + "_" + self.index_to_key(i), 
                            Unit=deviceNum, 
                            TypeName=self.index_to_key(i).capitalize(), 
                            DeviceID=deviceId, 
                            Used=1).Create()
                    else:
                        Domoticz.Device(
                            Name=clientName + "_" + self.index_to_key(i),  
                            Unit=deviceNum, 
                            TypeName="Custom", 
                            Options={"Custom":self.measure_to_str(i)}, 
                            DeviceID=deviceId, 
                            Used=1).Create()

    # Update device setting
    def updateSettingDevice(self, clientId, jsonData):
        if 'sleep' in jsonData:
            deviceIdSleep = clientId + "_Sleep"
            device = self.getExistDevice(deviceIdSleep)
            value = int(jsonData['sleep'])
            command = self.getKeyByValue(dict_sleep,value)
            self.updateDevice(device,value,command)
            
            # TODO control sleep device start end time
            self.startTime = jsonData['startTime']
            self.endTime = jsonData['endTime']
            Domoticz.Debug("Setting sleep startTime: " + str(self.startTime))
            Domoticz.Debug("Setting sleep endTime: " + str(self.endTime))

        elif 'brightness' in jsonData:
            deviceIdBrightness = clientId + "_Brightness"
            device = self.getExistDevice(deviceIdBrightness)
            value = jsonData['brightness']
            level = self.getKeyByValue(self.dict_brightness,value)
            self.updateDevice(device,2,level)

    # Update device into DB
    def updateDevice(self, device, nValue, sValue):
        if device.nValue != nValue or device.sValue != sValue:
            device.Update(nValue=nValue, sValue=str(sValue))
            Domoticz.Log("Update "+":'" + str(nValue)+" "+str(sValue)+"' ("+device.Name+")")

    # Setting type is 1
    def sendCommandSleep(self, clientId, value):
        if clientId in self.clientConns:
            msg = {
                "sleep":value,
                "startTime":self.startTime,
                "endTime":self.endTime,
                "type":1
            }

            mac = self.getKeyByValue(self.clientMacId,clientId)
            jsonString = json.dumps(msg)
            bytesCommand = self.generateJsonData(mac,2,jsonString)
            self.clientConns[clientId].Send(bytesCommand)

    # Setting type is 2
    def sendCommandBrightness(self, clientId, value):
        if clientId in self.clientConns:
            # hexCommand = self.brightness_hex%(self.stringToHex(value))
            # self.clientConns[clientId].Send(bytes.fromhex(hexCommand))
            msg = {
                "brightness":value,
                "type":2
            }

            mac = self.getKeyByValue(self.clientMacId,clientId)
            jsonString = json.dumps(msg)
            bytesCommand = self.generateJsonData(mac,2,jsonString)
            self.clientConns[clientId].Send(bytesCommand)

    # Setting type is 5
    def sendCommandStatus(self, clientId):
        if clientId in self.clientConns:
            # hexCommand = bytes.fromhex(self.heartbeat_hex)
            # self.clientConns[clientId].Send(hexCommand)
            msg = {
                "status":1,
                "type":5
            }

            mac = self.getKeyByValue(self.clientMacId,clientId)
            jsonString = json.dumps(msg)
            bytesCommand = self.generateJsonData(mac,2,jsonString)
            self.clientConns[clientId].Send(bytesCommand)


    def generateClientIdentity(self, ip):
        identity = ip.replace('.','')
        return identity[len(identity)-8:]

    def getExistDevice(self, identity):
        for x in Devices:
            if str(Devices[x].DeviceID) == identity:
                return Devices[x]
        return None

    def parseJsonData(self, data):
        msg = {
            "head": None,
            "mac": None,
            "command": None,
            "tail": None
        }

        reader = io.BytesIO(data)
        # head
        head = reader.read(3)
        msg['head'] = head

        # mac reverse
        mac_reverse = reader.read(6)

        # unknow
        unknow = reader.read(8)
        unknow_f = struct.unpack('>d',unknow)[0]
        if unknow_f != 0:
            Domoticz.Log("uncommon unknow, usually is all zero, but this time it is: " \
                + unknow.hex())

        # mac
        mac = reader.read(6)
        msg['mac'] = mac.hex()

        if mac_reverse[::-1] != mac:
            Domoticz.Log("uncommon mac, usually mac_reverse and mac are same, \
                but this time it is: mac_reverse: " + mac_reverse.hex() + " and mac:" + mac.hex() )

        # length
        lengthArray = reader.read(2)
        length = struct.unpack('>H',lengthArray)[0]

        if length == len(data):
            # when server send to client length is packet total length
            # reader.tell() is length of(head + mac reverse + unknow + mac + length)
            # 0x1F = reader.tell() + length of(tail)
            # 0x1F = (3 + 6 + 8 + 6 + 2) + 6
            length = length - reader.tell() - 6

        # info(zero + command + json)
        infoArray = reader.read(length)
        infoReader = io.BytesIO(infoArray)

        zero = infoReader.read(1)
        if (zero != b'\x00'):
            Domoticz.Log("uncommon zero, usually is 0x00, but this time it is: " \
                + zero.hex())

        commandArray = infoReader.read(2)
        command = struct.unpack('>H',commandArray)[0]
        msg['command'] = command
        if command == 4:
            # Status(Only from client)
            statusArray = infoArray[3:]
            jsonStr = statusArray.decode()
            msg['status'] = json.loads(jsonStr)
        elif command == 2:
            # Setting(Only from server)
            statusArray = infoArray[3:]
            jsonStr = statusArray.decode()
            msg['set'] = json.loads(jsonStr)
        elif command == 1:
            # Heartbeat
            pass
        else:
            unknowArray = infoArray[3:]
            msg['unknow'] = unknowArray
            Domoticz.Log("unknow command: " + command)

        # tail(mask + end)
        mask = reader.read(1)
        if (mask != b'\xff'):
            Domoticz.Log("uncommon mask, usually is 0xFF, but this time it is: " \
                + mask.hex())

        end = reader.read(5)
        msg['end'] = end.decode()
                    
        return msg

    def generateJsonData(self, mac, command, json):
        if type(mac) == str \
            and len(mac) == 12:
            mac = bytes.fromhex(mac)
        else:
            raise ValueError("The 'mac' argument must be two hexadecimal digits!")
        
        json = str(json).encode()
        command = int(command)
        
        header = b'\xAA\x2F\x01'
        mac_reverse = mac[::-1]
        unknow = b'\x00\x00\x00\x00\x00\x00\x00\x00'
        zero = b'\x00'
        mask = b'\xFF'
        end = '#END#'.encode()

        header_len = len(header)
        mac_len = len(mac)
        unknow_len = len(unknow)
        length_len = 2
        zero_len = 1
        command_len = 2
        json_len = len(json)
        mask_len = 1
        end_len = len(end)
        length = \
            header_len + mac_len + unknow_len + mac_len \
            + length_len + zero_len + command_len \
            + json_len + mask_len + end_len

        package = struct.pack(">3s6s8s6s1H1s1H" + str(json_len) + "s1s" + str(end_len) + "s", 
            header, mac_reverse, unknow, mac, 
            length, zero, command, 
            json, mask, end)

        return package

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

    def getKeyByValue(self, target, value):
        return list(target.keys())[list(target.values()).index(value)]


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