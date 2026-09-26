# Battery and CPU Activity Monitor

This project is a Linux command-line monitor that combines **battery telemetry** with
**kernel-level CPU scheduling data**. It answers a useful question for a laptop user:

> While the computer is running on battery, which processes are consuming the most CPU
> time, and how can the current battery power be distributed among them?

The monitor is implemented in Python and uses **eBPF through BCC** to observe the Linux
scheduler. It periodically reads the battery state from Linux sysfs, calculates how much
CPU time each process used during the previous interval, and prints a ranked report.

The project is an educational estimator, not a hardware power meter. The only directly
measured power value is the total battery power reported by the kernel. The power shown
for individual tasks is an allocation of that total based on their CPU-time share.

## What the program displays

Every five seconds, the program prints:

* **Battery capacity**: the current charge percentage.
* **Battery status**: normally `Charging`, `Discharging`, `Full`, or another value
  provided by the battery driver.
* **Battery power**: the current battery power in watts, when the driver exposes
  `power_now`.
* **Task name**: the short command name captured from the scheduler.
* **TID/PID**: the numeric identifier used as the key in the eBPF maps. The current
  implementation uses a scheduler PID and labels this column `TID`.
* **CPU percentage**: CPU time accumulated by the task during the five-second interval,
  divided by the interval length.
* **Estimated power**: the proportional share of the total battery power attributed to
  that task while the battery is discharging.

Only the top 15 tasks are printed. Tasks are ranked by estimated power when an estimate
is available; otherwise they are ranked by CPU percentage.

Example output has this shape:

```text
==========================================================
Battery: 73% | Status: Discharging
Battery power: 18.42 W
TASK                          TID       CPU     EST. POWER
----------------------------------------------------------
firefox                     12480    42.15%        7.761 W
python                       9211    18.40%        3.388 W
```

The exact values and task names depend on the machine, workload, kernel, and battery
driver.

## Architecture

The project has two cooperating halves:

```text
Linux scheduler tracepoints
          |
          v
  csrc/cpu_time.c (eBPF C program)
          |
          | BPF_HASH maps
          v
  utils/system.py (read maps from Python)
          |
          +--> CPU-time deltas and process names

/sys/class/power_supply/* (Linux sysfs)
          |
          v
  utils/battery.py
          |
          +--> capacity, status, and total battery power

                 main.py
          combines both data sources
          and prints the report
```

### 1. Battery data: `utils/battery.py`

`find_battery()` searches `/sys/class/power_supply` and returns the first device whose
`type` file contains exactly `Battery`. This supports common Linux laptop layouts such
as `/sys/class/power_supply/BAT0`, without hard-coding the battery name.

`battery_info()` reads three values:

* `capacity`: an integer percentage, such as `73`.
* `status`: the text in the battery's `status` file.
* `power_now`: an integer normally expressed by Linux power-supply drivers in
  microwatts. The code divides it by `1_000_000` to convert it to watts.

Missing files and non-integer values are represented as unavailable values instead of
crashing during a normal report. If no battery device exists at all, `main.py` raises an
explicit error because the monitor cannot fulfill its purpose.

## eBPF explained for the presentation

### What is eBPF?

**eBPF** means **extended Berkeley Packet Filter**. Despite the name, modern eBPF is
not limited to network packets. It is a Linux technology that lets us run small,
restricted programs inside the kernel when selected events occur.

Normally, an application runs in user space and asks the kernel for services through
system calls. The kernel owns information that applications cannot efficiently observe
directly, such as scheduler decisions and the exact moment a task stops using a CPU.
eBPF provides a controlled bridge:

```text
Python application (user space)
        |
        | loads program and reads results
        v
       BCC
        |
        | compiles and asks Linux to load it
        v
eBPF program (kernel space)
        |
        | runs when scheduler events happen
        v
Linux kernel scheduler
```

The eBPF program in this project is written in C because it runs in the kernel. Python
does not repeatedly poll `/proc` to guess CPU usage. Instead, the kernel observes every
relevant scheduler transition and maintains counters close to the event source. Python
later reads the accumulated results and turns them into a human-readable report.

### Why use eBPF here?

The Linux scheduler already knows when one task leaves a CPU and another task enters it.
The `sched_switch` tracepoint exposes exactly that information. This makes it a good
place to measure CPU runtime:

* The measurement happens at the scheduler event, rather than after the fact.
* The monitor does not need to modify the processes being observed.
* The program can collect data for many processes using shared kernel maps.
* The Python side receives counters instead of one user-space message for every switch.
* The same approach can be adapted to other kernel events, such as system calls,
  network activity, file access, or process creation.

This is also why the project is a useful eBPF example: it shows **event-driven
instrumentation**, **kernel maps**, **tracepoints**, and **user-space map reading** in a
small program.

### What happens when the program starts?

When `main.py` executes `BPF(text=program)`, BCC performs several jobs:

1. Python reads the C source from `csrc/cpu_time.c`.
2. BCC expands convenience macros such as `BPF_HASH` and `TRACEPOINT_PROBE`.
3. BCC invokes the compiler toolchain to turn the C program into eBPF bytecode.
4. BCC asks the Linux kernel to load the bytecode.
5. The kernel's **eBPF verifier** checks that the program is safe.
6. If accepted, the kernel attaches the program to the declared scheduler tracepoints.
7. The Python process receives a BPF object that provides access to the program's maps.

The verifier is essential because this code runs with kernel privileges. It checks
properties such as bounded execution, valid memory access, and valid helper usage. An
eBPF program cannot be allowed to loop forever, read arbitrary kernel memory, or crash
the kernel. On supported systems, the accepted bytecode may also be JIT-compiled into
native machine instructions for efficient execution.

BCC is the integration layer in this project. It is not the eBPF program itself:

* **The C source** defines what should happen inside the kernel.
* **The kernel** verifies and executes the resulting eBPF program.
* **BCC** compiles, loads, attaches, and exposes the program to Python.
* **Python** reads the maps and formats the output.

### What is a tracepoint?

A **tracepoint** is a stable, predefined observation point in the Linux kernel. The
kernel reaches that point during a known operation and exposes a documented set of
event fields. This project uses scheduler tracepoints instead of inserting arbitrary
code into a kernel function:

* `sched:sched_switch` is reached when the scheduler changes the task running on a
  CPU. Its arguments include the previous task's PID, the next task's PID, and the next
  task's command name.
* `sched:sched_process_exit` is reached when a task exits. Its PID is used to clean up
  the maps.

A useful analogy is a security camera installed at a doorway. The camera does not
continuously inspect every room. It records a small fact each time someone passes
through the doorway. Here, the doorway is the scheduler transition, and the facts are
the previous task, the next task, and the timestamp.

### The scheduler timeline

Suppose the scheduler runs `browser` and then switches to `python`:

```text
time 100 ns: browser starts running
time 160 ns: scheduler switches browser -> python
```

At the switch, the eBPF program:

1. Looks up the saved start time of `browser` (`100 ns`).
2. Calculates `160 - 100 = 60 ns`.
3. Adds `60 ns` to `browser`'s accumulated CPU time.
4. Stores `160 ns` as `python`'s new start time.
5. Stores Python's command name in the process map.

If the next switch occurs at `200 ns`, the program attributes `40 ns` to `python`.
This repeats for every scheduler switch. At no point does the eBPF program need to
sample a process and guess whether it was running: the scheduler tells it exactly when
the run segment starts and ends.

### What are BPF maps?

An eBPF program cannot return an arbitrary Python object or print directly to the
terminal. **BPF maps** are its shared storage. They live under kernel control and allow
the eBPF code and user-space BCC code to exchange structured data.

This project declares three hash maps:

```text
PID  ->  start timestamp
PID  ->  accumulated CPU nanoseconds
PID  ->  process name
```

Each map is keyed by a 32-bit scheduler PID. A hash map is appropriate because the
program needs to find the state for whichever task appears in the next scheduler event.
The eBPF side uses operations such as `lookup`, `update`, and `delete`; Python sees the
same maps through `bpf["cpu_time"]` and `bpf["processes"]`.

The maps are counters and state, not an event log. The monitor does not store every
scheduler switch. It stores the current total for each PID, which keeps communication
between kernel and user space compact. Python takes snapshots of those totals and
calculates the difference between snapshots.

### Detailed walkthrough of `sched_switch`

The `TRACEPOINT_PROBE(sched, sched_switch)` macro creates the kernel callback. Each
time Linux changes the running task, the callback executes:

1. **Read a timestamp**
   `bpf_ktime_get_ns()` returns a monotonic kernel timestamp in nanoseconds. It is
   suitable for measuring elapsed time because it is not based on the wall clock.

2. **Read the scheduler arguments**
   `args->prev_pid` identifies the task that is leaving the CPU, and
   `args->next_pid` identifies the task that is entering. PID zero represents the idle
   task and is ignored where appropriate.

3. **Close the previous run segment**
   The program looks up `start_time[prev_pid]`. If a start timestamp exists, the
   difference between `now` and that timestamp is the CPU time for the segment.

4. **Accumulate the duration**
   If `cpu_time[prev_pid]` already exists, the delta is added to it. Otherwise, a new
   counter is created with the delta as its first value.

5. **Open the next run segment**
   The current timestamp is written to `start_time[next_pid]`. This timestamp remains
   there until the next time that task leaves the CPU.

6. **Save the task name**
   `bpf_probe_read_kernel_str()` safely copies `args->next_comm` into a
   `process_info` structure. The structure is stored in `processes[next_pid]`.

7. **Return immediately**
   Returning `0` finishes the callback. The scheduler continues its normal work; the
   monitor does not control scheduling or change task priorities.

The callback intentionally does not perform expensive formatting, file I/O, or
printing. Kernel-side code should do the smallest amount of work needed to collect
the data.

### Cleaning up exited tasks

The `TRACEPOINT_PROBE(sched, sched_process_exit)` callback removes the exiting PID from
`start_time`, `cpu_time`, and `processes`. This matters because PIDs can eventually be
reused. Without cleanup, a new process could accidentally inherit the old process's
CPU total or name.

### How Python reads the maps

Every five seconds, `utils/system.py` iterates over the BCC maps:

```text
kernel map: { 1001: 8,000,000,000, 1002: 2,000,000,000 }
                         |
                         v
Python dictionary with integer PIDs and nanosecond totals
```

`main.py` takes one initial snapshot, waits five seconds, and takes another. If a task's
counter was 8 seconds in the first snapshot and 9.5 seconds in the second, the task
used 1.5 seconds of CPU during the interval. That delta is then converted to the
displayed percentage and used by the power-attribution formula.

### What eBPF does not do in this project

It is important to explain the boundary of responsibility:

* eBPF measures scheduler CPU-runtime segments; it does not measure electrical current
  for each process.
* eBPF does not read the battery percentage or `power_now`; Python reads those files
  from sysfs.
* eBPF does not decide which process is using the most power; Python computes that
  estimate after reading the maps.
* eBPF does not terminate, pause, reprioritize, or otherwise control processes.
* eBPF does not send one output line per event; it maintains counters in maps.

Therefore, the final report is produced by combining two independent observations:
kernel scheduling data from eBPF and total battery telemetry from sysfs.

### 2. Kernel instrumentation: `csrc/cpu_time.c`

The C file is compiled and loaded at runtime by BCC. It attaches to two scheduler
tracepoints:

* `sched:sched_switch`: runs whenever Linux switches the CPU from one task to another.
* `sched:sched_process_exit`: runs when a process exits.

The eBPF program maintains three BPF hash maps, all keyed by a 32-bit process ID:

| Map | Value | Purpose |
| --- | --- | --- |
| `start_time` | `u64` nanoseconds | Timestamp at which a task started its current CPU run. |
| `cpu_time` | `u64` nanoseconds | Accumulated CPU time for the task. |
| `processes` | `struct process_info` | The task's command name (`comm`). |

When a scheduler switch occurs, the program:

1. Gets the current monotonic kernel timestamp with `bpf_ktime_get_ns()`.
2. Looks up the task that is leaving the CPU.
3. Subtracts its saved start timestamp from the current timestamp.
4. Adds that elapsed duration to the task's accumulated CPU time.
5. Saves the current timestamp as the start time of the task that is entering the CPU.
6. Records the entering task's command name.

When a task exits, all entries associated with its PID are deleted. This prevents stale
process IDs and names from remaining in the maps after a process disappears.

The eBPF program does not print anything. It collects data in kernel-resident maps;
Python reads those maps through BCC.

### 3. Reading eBPF maps: `utils/system.py`

`get_cpu_times()` converts the `cpu_time` BPF map into a normal Python dictionary:

```text
{ process_id: accumulated_cpu_nanoseconds }
```

`get_process_names()` converts the fixed-size C `comm` byte array into a Python string.
It stops at the first NUL byte and uses replacement decoding so an unusual process name
cannot make report generation fail.

### 4. Aggregation and reporting: `main.py`

`main()` performs the following setup:

1. Finds a battery.
2. Reads `csrc/cpu_time.c`.
3. Creates a BCC `BPF` object, which compiles and loads the eBPF program.
4. Takes an initial CPU-time snapshot.
5. Repeats every five seconds until interrupted.

On each iteration it:

1. Sleeps for `INTERVAL` seconds.
2. Reads the current battery information.
3. Reads the current eBPF CPU-time map.
4. Calculates the difference between the current and previous snapshots.
5. Removes the monitor's own PID from the results.
6. Converts each positive CPU-time delta into a percentage.
7. Proportionally allocates measured battery power to tasks.
8. Sorts and prints the top `PROCESS_LIMIT` tasks.

## How the calculations work

### CPU-time delta

The eBPF map stores cumulative CPU time. To measure only the latest interval, the
program takes two snapshots:

```text
delta[pid] = current_total[pid] - previous_total[pid]
```

If a PID was not present in the previous snapshot, its previous value is treated as
zero. Non-positive deltas are ignored.

### CPU percentage

For a five-second interval, a task's displayed CPU percentage is calculated as:

```text
cpu_percent = (cpu_delta_nanoseconds / 1,000,000,000 / 5) * 100
```

On a multi-core system, the sum of percentages can exceed 100%, because different
processors can execute different tasks at the same time. This is CPU time relative to
wall-clock interval length, not a percentage normalized to one CPU.

### Estimated per-task power

When both conditions are true:

* the battery driver exposes `power_now`; and
* the battery status is `Discharging`;

the monitor estimates a task's power as:

```text
estimated_task_power =
    total_battery_power * task_cpu_delta / total_observed_cpu_delta
```

For example, if the battery reports 20 W and a task accounts for 25% of the observed
CPU time, the monitor displays an estimated 5 W for that task.

This is a proportional attribution model. It assumes that the CPU-time share is a useful
proxy for the share of battery power. It does **not** measure per-process electrical
power, and it does not account independently for screen brightness, GPU activity,
memory, storage, radios, fans, battery conversion losses, or other system components.

Power attribution is deliberately disabled while charging and whenever `power_now` is
unavailable. In those cases the report displays `N/A` for task power and sorts by CPU
percentage instead.

## Project layout

```text
battery/
├── main.py                 # Application loop, calculations, sorting, and output
├── csrc/
│   └── cpu_time.c           # eBPF program attached to scheduler tracepoints
└── utils/
    ├── __init__.py          # Python package marker
    ├── battery.py           # Linux battery sysfs discovery and parsing
    └── system.py            # BCC map readers for CPU time and process names
```

The `__pycache__` directory, when generated by Python, contains local bytecode caches
and is not part of the monitor's design.

## Requirements

This project is Linux-specific. You need:

* A Linux kernel with eBPF support.
* Python 3.10 or newer (the code uses modern type-annotation syntax).
* The Python `bcc` module.
* The system BCC tools and libraries, including the compiler support BCC uses to
  compile the embedded C program.
* Kernel headers or kernel development packages suitable for the running kernel.
* A battery exposed through `/sys/class/power_supply`.
* Permission to load eBPF programs and read scheduler data. Running with `sudo` is
  commonly required, depending on the distribution's BPF permissions.

The repository does not currently include a `requirements.txt` or packaging file. BCC
is normally installed through the Linux distribution's packages because it depends on
kernel tooling and native libraries; the exact package names vary by distribution.

For Debian- or Ubuntu-based systems, the package names are commonly similar to:

```bash
sudo apt update
sudo apt install bpfcc-tools python3-bpfcc linux-headers-$(uname -r)
```

Check the BCC documentation and your distribution's package repository if those names
are unavailable. A Python environment must be able to import `bcc`:

```bash
python3 -c "from bcc import BPF; print('BCC is available')"
```

## Running the monitor

Run from the project directory so the `utils` package can be imported:

```bash
cd battery
sudo python3 main.py
```

The path to `cpu_time.c` is resolved relative to `main.py`, so the command remains
correct even if the current working directory is different, as long as Python can
import the local `utils` package. To stop the monitor, press `Ctrl+C`.

The startup output includes the monitor's own PID, which is excluded from subsequent
reports:

```text
Monitor PID: 12345
Monitoring battery and CPU activity...
Press Ctrl+C to stop.
```

The first report appears after the first five-second interval. A message saying
`No CPU activity detected during this interval.` means no positive CPU-time delta was
available for the interval; it is not necessarily an error.

## Troubleshooting

### `ModuleNotFoundError: No module named 'bcc'`

Install the distribution's Python BCC package and ensure it is installed for the exact
Python interpreter used to run `main.py`. The system package may be named
`python3-bpfcc` rather than `bcc`.

### BCC compilation or verifier errors

Check that:

* the running kernel headers are installed;
* the BCC userspace library and Python bindings are compatible;
* the process has permission to load eBPF programs; and
* the kernel exposes the `sched_switch` and `sched_process_exit` tracepoints.

### `No battery was found under /sys/class/power_supply`

Inspect the directory:

```bash
ls -l /sys/class/power_supply
```

The program requires at least one device whose `type` file is `Battery`. Desktop
computers, virtual machines, containers, and some unusual hardware may not expose one.

### Battery power is unavailable

Some battery drivers expose `capacity` and `status` but do not expose `power_now`.
The monitor still reports CPU activity, but it cannot calculate estimated task power.

### Task names or rows look incomplete

The eBPF program learns a task when it enters the CPU during a scheduler switch. A
short-lived task that does not appear in a sampled map, or a task whose map entry was
removed after exit, may not have a matching name. In that case the Python code displays
`unkown` (the current spelling in the implementation).

## Important limitations and interpretation

1. **Power values per task are estimates.** Only the total battery `power_now` value is
   supplied by the hardware/kernel interface.
2. **CPU is only one source of energy use.** GPU work, display, memory, disk, network,
   fans, and platform firmware are not separately attributed.
3. **Sampling is interval-based.** Reports are snapshots over five seconds, not a
   complete history.
4. **The first interval is a warm-up interval.** Cumulative maps must be observed twice
   before a delta can be calculated reliably.
5. **The monitor is Linux-specific.** It depends on Linux power-supply sysfs, scheduler
   tracepoints, eBPF, and BCC.
6. **The report is process-ID based.** The column heading says `TID`, but the C maps use
   the scheduler's PID field. Thread-level interpretation should therefore be made
   carefully.
7. **Map lifecycle affects visibility.** Exited tasks are deleted immediately, and tasks
   that have not yet participated in a relevant scheduler transition may not be present.
8. **The monitor adds some overhead.** It observes frequent scheduler events and also
   consumes CPU itself, although it removes its own measured contribution from the
   displayed task list.

## Presentation takeaways

This project demonstrates a complete observability pipeline:

1. **Kernel instrumentation:** eBPF observes scheduler events close to their source.
2. **Efficient shared state:** BPF hash maps accumulate data without printing from the
   kernel.
3. **Userspace integration:** Python/BCC reads those maps and combines them with sysfs.
4. **Derived metrics:** cumulative counters become interval CPU usage through deltas.
5. **Attribution model:** measured total power is distributed using CPU-time shares.
6. **Graceful degradation:** missing battery power data disables only the estimate,
   rather than disabling CPU monitoring entirely.

The central idea is to combine **what the hardware reports** with **what the kernel knows
about scheduling**. That combination provides a useful and explainable approximation of
which workloads are active while a laptop is consuming battery power.
