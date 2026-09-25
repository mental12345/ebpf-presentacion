#include <uapi/linux/ptrace.h>

struct cpu_time_key {
    u32 pid;
};

BPF_HASH(start_time, u32, u64);
BPF_HASH(cpu_time, u32, u64);


TRACEPOINT_PROBE(sched, sched_switch)
{
    u64 now = bpf_ktime_get_ns();

   
    u32 prev_pid = args->prev_pid;

 
    u32 next_pid = args->next_pid;


    
    if (prev_pid != 0) {

        u64 *start = start_time.lookup(&prev_pid);

        if (start != NULL) {

            u64 delta = now - *start;

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


   
    if (next_pid != 0) {

        start_time.update(
            &next_pid,
            &now
        );
    }

    return 0;
}