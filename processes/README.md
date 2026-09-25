# Process Monitor with eBPF - A Beginner's Guide 🐣

Welcome! This little project watches every new process that starts on your computer and prints its PID, its parent's PID (PPID), and the process name. 


## Table of Contents

1.    What is eBPF? (The Big Idea)
1.    The Two Files
1.   The C File — Line by Line
1.    The Python File — Line by Line
1.    How the Two Halves Talk to Each Other
1.    How to Run It


## 1. What is eBPF? (The Big Idea)

Imagine your computer has a giant hallway where every action happens:

    A program starts 👶

    A file is opened 📂

    A network packet arrives 📨


The magic trick:

    You write a small program in C.

    You give it to the Linux kernel.

    The kernel checks it's safe (no infinite loops, no crashing!).

    The kernel runs it every time a specific event happens.

In this case, the event is: "a new program is being executed."

## 2. The C and Python Files

**processes.c**: The tiny program that runs inside the kernel.\

**monitor.py**:	The python file host that loads the C program and reads its messages

The C code cannot print to the terminal. It can only send messages through a special tunnel called a perf buffer. The Python code sits on the other end of the tunnel and does the printing.

## 3. The C File — Line by Line

```
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>
```
* These are header files. They tell the compiler about things like struct pt_regs (CPU registers at the moment of the event) and struct task_struct (the kernel's description of a running process).


```
struct event_t {
    u32 pid;
    u32 ppid;
    char comm[TASK_COMM_LEN];
};
```
👉 This is the message shape we will send to Python. Think of it as a little postcard with three fields:

    pid — the process's own ID number.

    ppid — the ID of the parent that spawned it.

    comm — the process's short name (max 16 characters; TASK_COMM_LEN is 16).

    Why u32? That's an unsigned 32-bit integer — a whole positive number that fits in 4 bytes.

```
BPF_PERF_OUTPUT(events);
```
👉 This creates a one-way pipe named events. The kernel-side program pushes information into it, and Python reads them out the other end.

```
int trace_execve(struct pt_regs *ctx)
```
👉 This is the function that will run every time a program calls execve() — the syscall that says "replace me with a new program." Every time you type a command in a shell, execve fires.

```
{
    struct event_t event = {};
    struct task_struct *task;
}
```

👉 Make an empty postcard to fill in. = {} zeroes it out (important! otherwise we'd leak old kernel memory).

```
    event.pid = bpf_get_current_pid_tgid() >> 32;
```

👉 bpf_get_current_pid_tgid() returns a 64-bit number where the top 32 bits are the PID and the bottom 32 are the thread ID (TGID). We shift right by 32 to grab just the PID.


```
    task = (struct task_struct *)bpf_get_current_task();
    event.ppid = task->real_parent->tgid;
```


👉 Ask the kernel: "Who am I right now?" → we get a task_struct pointer.
Then we walk to its parent (real_parent), and grab the parent's tgid (which is what user-space calls the "PID" of the parent).


⚠️ This is the tricky part. In raw eBPF C, you can't just dereference task->real_parent — the verifier will reject it. BCC (the toolkit we're using) automatically rewrites task->field into a safe helper call called bpf_probe_read_kernel. That's why the comment says "BCC rewrites this safely."
```

    bpf_get_current_comm(&event.comm, sizeof(event.comm));
```

👉 Copies the process's short name (like bash, python3, ls) into our postcard.

```
    events.perf_submit(ctx, &event, sizeof(event));
    return 0;
}
```

👉 Mail the postcard! The perf_submit call pushes it into the perf buffer, and the Python side will pick it up.

## 4. The Python File — Line by Line
```python

from bcc import BPF
import ctypes as ct

```
👉 BCC is the Python library that compiles our C and loads it into the kernel.
ctypes lets us read raw bytes as a C-like struct.

```python

with open("processes.c") as f:
    program = f.read()

b = BPF(text=program)
```

👉 Read the C code and hand it to BCC. BCC now:

    Compiles the C.

    Sends it to the kernel.

    Waits for the kernel's verifier to approve it.

    Loads it into memory.

If the C has a syntax error or the verifier is unhappy, this line throws an exception.
```python

b.attach_kprobe(
    event="__x64_sys_execve",
    fn_name="trace_execve"
)
```

👉 Attach the function to a hook point.

    __x64_sys_execve is the kernel function for the execve syscall on 64-bit x86.

    trace_execve is the name of our C function.

    kprobe means "kernel probe" — a hook that fires before the function runs.

    🪝 Think of it like hanging a wind chime on a specific door. Every time the door opens, the chime rings — and our code runs.

```python

class Event(ct.Structure):
    _fields_ = [
        ("pid", ct.c_uint),
        ("ppid", ct.c_uint),
        ("comm", ct.c_char * 64),
    ]
```

👉 This mirrors the C struct event_t. It must match field-for-field, or the values we read will be garbage.

    ⚠️ Note: on the C side comm is 16 bytes (TASK_COMM_LEN). Here we declare 64. That's slightly wasteful but harmless as long as Python reads only what C wrote. To be strictly correct, you could use ct.c_char * 16. Most people use 64 by habit — but I'd recommend 16 here.

```python

def print_event(cpu, data, size):
    event = ct.cast(
        data,
        ct.POINTER(Event)
    ).contents
```

👉 This is the callback. Every time a postcard arrives from the kernel:

    cpu — which CPU core the event happened on.

    data — a pointer to the raw bytes of the postcard.

    size — how many bytes.

We cast the raw bytes into our Event struct so we can read .pid, .ppid, .comm.
```python

    print(
        f"PID={event.pid:<6} "
        f"PPID={event.ppid:<6} "
        f"PROCESS={event.comm.decode(errors='replace')}"
    )
```

👉 Print it nicely.

    <6 means "left-align, pad to width 6."

    .decode(errors='replace') turns the C-style bytes into a Python string, replacing anything unreadable with ? (instead of crashing).

```python

b["events"].open_perf_buffer(print_event)
```
👉 Find the perf buffer named events (matches BPF_PERF_OUTPUT(events) in C) and register our callback.
```python

print("Watching process execution...")
print("Press Ctrl+C to exit\n")
```
👉 Just friendly chatter. 👋
```python

while True:
    try:
        b.perf_buffer_poll()
    except KeyboardInterrupt:
        break
```

👉 The heartbeat. perf_buffer_poll() blocks until an event arrives, then calls print_event. We loop forever, until you press Ctrl+C.
## 5. How the Two Halves Talk to Each Other
```

   You run:  ls
        │
        ▼
   Kernel:  execve() is called
        │
        ▼
   C program (trace_execve) runs
        │  builds an event_t postcard
        ▼
   perf_submit pushes it into the "events" buffer
        │
        ▼
   Python:  perf_buffer_poll() wakes up
        │
        ▼
   print_event() runs → prints the line
```
Nothing is copied through files or sockets. It's all in-memory, very fast.

## 6. How to Run It
Requirements

    Linux 

    Root User

    BCC installed.

    Python 3

    Kernel headers matching your running kernel.


See it in action

Open a second terminal and run anything — ls, curl example.com, echo hi. In the first terminal you'll see lines like:
text

Watching process execution...
Press Ctrl+C to exit

PID=4123   PPID=4100   PROCESS=ls
PID=4124   PPID=4100   PROCESS=bash
PID=4125   PPID=1      PROCESS=systemd

Press Ctrl+C to stop.

