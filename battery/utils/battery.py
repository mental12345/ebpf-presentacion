import os
import time
from pathlib import Path


def find_battery():
    power_supply = Path("/sys/class/power_supply")
    for device in power_supply.iterdir():
        if (device / "type").exists():
            device_type = (device / "type").read_text().strip()

            if device_type == "Battery":                
                return device
    return None

def read_value(battery, name):
    
    path = battery / name

    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except ValueError:
        return None

def battery_info(battery):
    
    battery_path = Path(battery)
    
    capacity = read_value(battery_path, "capacity")

    status_path = battery_path / "status"

    status = "Unknown"

    if status_path.exists():
        status = status_path.read_text().strip()


    power_now = read_value(battery_path, "power_now")

    if power_now is not None:
        power_watts = power_now / 1_000_000
    else:
        power_watts = None

    return {
        "capacity": capacity,
        "status": status,
        "power_watts": power_watts,
    }