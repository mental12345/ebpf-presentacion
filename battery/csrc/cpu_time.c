#include <uapi/linux/ptrace.h>

struct process_key {
    u32 pid;
};

struct process_info {
    char comm[64];
};

BPF_HASH(start_time, u32, u64); // Stores when a process started running

BPF_HASH(cpu_time, u32, u64); // Stores accumulated CPU time.

BPF_HASH(processes, u32, struct process_info); // Stores the process name.

TRACEPOINT_PROBE(sched, sched_switch) // Probe called every time the Scheduler switches from one process to another
{
    u64 now = bpf_ktime_get_ns();

    u32 prev_pid = args->prev_pid;
    u32 next_pid = args->next_pid;


    // Account CPU time for the process leaving CPU
    if (prev_pid != 0) {

        u64 *start = start_time.lookup(&prev_pid);

        if (start != NULL) {

            // HOw long the process is running
            u64 delta = now - *start;

            // Accumulated CPU Time
            u64 *total = cpu_time.lookup(&prev_pid);

            if (total != NULL) {
                (*total) += delta;

            } else {

                cpu_time.update(
                    &prev_pid,
                    &delta
                );
            }
        }
    }

    // When does the next process starts to run
    if (next_pid != 0) {

        // Store the current timestamp.
        // This becomes the starting point for
        // the next CPU-time measurement.
        
        start_time.update(
            &next_pid,
            &now
        );

        struct process_info info = {}; // Store the process name.

        bpf_probe_read_kernel_str(
            &info.comm,
            sizeof(info.comm),
            args->next_comm
        );

        processes.update(
            &next_pid,
            &info
        );
    }

    return 0;
}


/*
 * Called when a process exits.
 *
 * This prevents old PIDs from remaining in
 * our BPF maps after the process has disappeared.
 */
TRACEPOINT_PROBE(sched, sched_process_exit)
{
    u32 pid = args->pid;
    // Remove the process from all maps.
    start_time.delete(&pid);
    cpu_time.delete(&pid);
    processes.delete(&pid);

    return 0;
}