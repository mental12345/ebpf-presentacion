#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

struct event_t {
    u32 pid;
    u32 ppid;
    char comm[TASK_COMM_LEN];  
    
};

BPF_PERF_OUTPUT(events);

int trace_execve(struct pt_regs *ctx)
{
    struct event_t event = {};
    struct task_struct *task;

    event.pid = bpf_get_current_pid_tgid() >> 32;

    task = (struct task_struct *)bpf_get_current_task();
    event.ppid = task->real_parent->tgid;   // BCC rewrites this safely

    bpf_get_current_comm(&event.comm, sizeof(event.comm));
    events.perf_submit(ctx, &event, sizeof(event));
    return 0;
}