#!/usr/bin/python3

import smllib
import serial
import threading
import time
from flask import Flask
import yaml
import argparse

#The two connected serial ports
baseConfig = {
    "obisCodes": {
        "0.0.9":  {"name": "GeraeteID",    "unit": ""},
        "1.8.0":  {"name": "Zaehlerstand", "unit": "Wh"},
        "16.7.0": {"name": "Wirkleistung", "unit": "W"},
    },

    "server": {
        "port": 8000,
        "host": "127.0.0.1",
    },
}


latestValues = {}
threadList = []
lock = threading.Lock()
stopThreads = False

app = Flask(__name__)

def readMeter_thread(serialDevice):
    global lock, latestValues, stopThreads 
    
    t_frame = time.time()

    with serial.Serial(serialDevice, 9600, timeout=0, exclusive=True) as ser:
        stream = smllib.SmlStreamReader()
        print(f"Reader for '{serialDevice}' is READY!")

        while not stopThreads:
            time.sleep(10/1000)

            if ser.in_waiting > 0:
                try:
                    stream.add(ser.read(100))
                except SerialException as e:
                    print(e)
            sml_frame = stream.get_frame()

            #Skip further processing if no complete new frame is received
            if sml_frame is None:
                continue
            
            t_frameLast = t_frame
            t_frame = time.time()
            
            # Shortcut to extract all values without parsing
            obis_values = sml_frame.get_obis()
            entry = {}

            for val in obis_values:
                if val.obis.obis_short not in config["obisCodes"]:
                    continue

                entry[val.obis.obis_short] = {
                    "value": val.get_value(),
                    "unit":  config["obisCodes"][val.obis.obis_short]["unit"],
                    "name":  config["obisCodes"][val.obis.obis_short]["name"],
                    "obis":  val.obis.obis_short,
                        }
                #print(entry)
            
            #If defined, replace unique ID with meter name from config file
            entry["name"] = entry["0.0.9"]["value"]
            if entry["0.0.9"]["value"] in config["meterNames"]:
                entry["name"] = config["meterNames"][entry["0.0.9"]["value"]]
            
            #Update readings to be provided by the server 
            with lock:
                latestValues[entry["name"]]=entry
                print(f"New vales for: {entry['name']:20s} >{entry['16.7.0']['value']:8.1f}W ({t_frame-t_frameLast:.2f}s)")

@app.route('/')
def index():
    """Return latest meter readings as JSON."""
    
    with lock:
        return latestValues


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--device', help='Manually provide a single device for testing instead of using the config file')
    parser.add_argument('-c', '--configfile', default="smartmeterreader.yaml", help='Path to YAML config file')
    parser.add_argument('-p', '--printconfig', action='store_true', help='Output the current configuration')
    args = parser.parse_args()
    print(args)
    
    #Prepare configuration
    with open(args.configfile,'r') as file:
        config = yaml.safe_load(file)
    if "obisCodes" not in config:
        config["obisCodes"] = baseConfig["obisCodes"]
    if "server" not in config:
        config["server"] = baseConfig["server"]
    if args.device:
        config["devices"] = [args.device]

    #Show configuration on request
    if args.printconfig:
        print("")
        print("===== CURRENT CONFIG BEGIN YAML =====")
        print(yaml.dump(config))
        print("===== CURRENT CONFIG END YAML =====")
        print("")

    #Start reader threads
    for dev in config["devices"]:
        x = threading.Thread(target=readMeter_thread, args=(dev,))
        threadList.append(x)
        x.start()

    #Using Flask in debug mode collides with our own threads running above.
    #Flask tries to reload itself, not stopping the threads, but starts them another time
    #app.run(host='0.0.0.0', port=8000, debug=True, use_debugger=True, use_reloader=True)
    app.run(host=config["server"]["host"], port=config["server"]["port"])
    
    #EXIT
    stopThreads = True
    for t in threadList:
        t.join()


