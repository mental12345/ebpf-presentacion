from bcc import BPF

## Read the cpu time created by ebpf

def get_cpu_times(bpf):
    result = {}

    table = bpf["cpu_time"]
    for pid, value in table.items():
        pid = pid.value
        nanoseconds = value.value

        result[pid] = nanoseconds

    return result

def get_process_names(bpf):
    result = {} 
    table = bpf["processes"] 
    for pid, info in table.items(): 
        pid = pid.value 
        # info.comm is a ctypes byte array. 
        name = bytes(info.comm).split(b"\x00", 1)[0].decode("utf-8", errors="replace") 
        result[pid] = name
        
    return result

