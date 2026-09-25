from bcc import BPF
import ctypes as ct


with open("processes.c") as f:
    program = f.read()

b = BPF(text=program)

b.attach_kprobe(
    event="__x64_sys_execve",
    fn_name="trace_execve"
)


class Event(ct.Structure):
    _fields_ = [
        ("pid", ct.c_uint),
        ("ppid", ct.c_uint),
        ("comm", ct.c_char * 64),
    ]


def print_event(cpu, data, size):
    event = ct.cast(
        data,
        ct.POINTER(Event)
    ).contents

    print(
        f"PID={event.pid:<6} "
        f"PPID={event.ppid:<6} "
        f"PROCESS={event.comm.decode(errors='replace')}"
    )


b["events"].open_perf_buffer(print_event)

print("Watching process execution...")
print("Press Ctrl+C to exit\n")

while True:
    try:
        b.perf_buffer_poll()
    except KeyboardInterrupt:
        break