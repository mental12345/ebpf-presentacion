from bcc import BPF
import ctypes as ct

with open("files_access.c") as f:
    program = f.read()

b = BPF(text=program)

#b.attach_kprobe(
#    event="__x64_sys_openat",
#    fn_name="trace_open"
#)


class Event(ct.Structure):
    _fields_ = [
        ("pid", ct.c_uint),
        ("comm", ct.c_char * 64),
        ("filename", ct.c_char * 256),
    ]


def print_event(cpu, data, size):
    event = ct.cast(
        data,
        ct.POINTER(Event)
    ).contents

    comm = event.comm.decode(errors="replace")
    filename = event.filename.decode(errors="replace")

    print(
        f"{event.pid:<7} "
        f"{comm:<15} "
        f"{filename}"
    )


b["events"].open_perf_buffer(print_event)

print("Watching file access...\n")
print(f"{'PID':<7} {'COMMAND':<15} FILE")
print("-" * 80)


print("Watching file access...\n")

b.perf_buffer_poll()

while True:
    try:
        b.perf_buffer_poll()
    except KeyboardInterrupt:
        break