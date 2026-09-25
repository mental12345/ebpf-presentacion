#include <uapi/linux/ptrace.h>

struct event_t {
    u32 pid;
    char comm[64];
    char filename[256];
};

BPF_PERF_OUTPUT(events);

TRACEPOINT_PROBE(syscalls, sys_enter_openat)
{
    struct event_t event = {};

    event.pid = bpf_get_current_pid_tgid() >> 32;

    bpf_get_current_comm(
        &event.comm,
        sizeof(event.comm)
    );

    bpf_probe_read_user_str(
        &event.filename,
        sizeof(event.filename),
        args->filename
    );

    events.perf_submit(
        args,
        &event,
        sizeof(event)
    );

    return 0;
}