from utils import battery as battery_utils
from utils import system as system_utils
import time
import os
from pathlib import Path
from bcc import BPF


INTERVAL = 5
BPF_SOURCE = Path(__file__).parent / "csrc" / "cpu_time.c"
PROCESS_LIMIT = 15

def calculate_delta(before, after):
    result = {}
    for pid, current in after.items():
        previous = before.get(pid, 0)
        delta = current - previous

        if delta > 0:
            result[pid] = delta
    return result

def print_report(
    battery_info: dict,
    processes: list[tuple[int, str, float, float | None]],
) -> None:
    power_watts = battery_info["power_watts"]
    power_is_attributable = (
        power_watts is not None
        and battery_info["status"].lower() == "discharging"
    )

    print()
    print("=" * 58)
    capacity = battery_info["capacity"]
    capacity_text = f"{capacity}%" if capacity is not None else "N/A"
    print(f"Battery: {capacity_text} | Status: {battery_info['status']}")

    if power_watts is None:
        print("Battery power: unavailable (power_now not exposed)")
    else:
        print(f"Battery power: {power_watts:.2f} W")

    if not power_is_attributable:
        print("Per-task power is only estimated while discharging.")

    print(f"{'TASK':<25}{'TID':>8}{'CPU':>10}{'EST. POWER':>15}")
    print("-" * 58)

    if not processes:
        print("No CPU activity detected during this interval.")
        return

    for tid, name, cpu_percent, estimated_power in processes[:PROCESS_LIMIT]:
        power_text = (
            f"{estimated_power:.3f} W"
            if estimated_power is not None
            else "N/A"
        )
        print(
            f"{name[:24]:<25}"
            f"{tid:>8}"
            f"{cpu_percent:>9.2f}%"
            f"{power_text:>15}"
        )


def main():
    battery = battery_utils.find_battery()
    if battery is None:
        raise RuntimeError("No battery was found under /sys/class/power_supply")

    
    program = BPF_SOURCE.read_text()
    bpf = BPF(text=program)

    monitor_pid = os.getpid() 
    print(f"Monitor PID: {monitor_pid}") 
    print("Monitoring battery and CPU activity...") 
    print("Press Ctrl+C to stop.") 


    previous_cpu = system_utils.get_cpu_times(bpf)

    try: 
        while True: 
            time.sleep(INTERVAL)
            info_bat = battery_utils.battery_info(battery) # Get battery information
            current_cpu = system_utils.get_cpu_times(bpf)
            

            cpu_delta = calculate_delta(previous_cpu, current_cpu)
            previous_cpu = current_cpu


            process_name = system_utils.get_process_names(bpf)

            cpu_delta.pop(monitor_pid, None)
            total_cpu_time = sum(cpu_delta.values())
            
            processes = [] 
            cpu_share = 0
            if total_cpu_time > 0:
                power_watts = info_bat["power_watts"]
                can_estimate_power = (
                    power_watts is not None 
                    and info_bat["status"].lower() == "discharging" 
                )
                
                for pid, cpu_ns in cpu_delta.items(): 
                    cpu_percent = ( cpu_ns / 1_000_000_000 / INTERVAL ) * 100    
                    estimated_power = (
                        power_watts * cpu_ns / total_cpu_time
                        if can_estimate_power
                        else None
                    ) 
                    processes.append(
                        ( 
                            pid,
                            process_name.get(pid, "unkown"),
                            cpu_percent,
                            estimated_power                            
                        ) 
                    )

            if info_bat["power_watts"] is not None and (
                info_bat["status"].lower() == "discharging"
            ):
                processes.sort(
                    key=lambda row: (
                        row[3] if row[3] is not None else 0,
                        row[2],
                    ),
                    reverse=True,
                )
            else: 
                processes.sort( reverse=True, key=lambda row: row[2] )
            
            print_report(info_bat, processes)
    except KeyboardInterrupt: 
        print("\nGoodBye!!")


if __name__ == "__main__":
    main()