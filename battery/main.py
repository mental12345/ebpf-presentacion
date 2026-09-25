import utils.battery as bat
from bcc import BPF

battery = bat.find_battery()



print(bat.battery_info(battery))

