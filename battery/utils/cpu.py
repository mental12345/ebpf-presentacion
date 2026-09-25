from bcc import BPF


def get_cpu_times(bpf):
    result = {}

    table = bpf["cpu_time"]
    for pid, value in table.items():
        pid = pid.value
        nanoseconds = value.value

        result[pid] = nanoseconds

    return result



