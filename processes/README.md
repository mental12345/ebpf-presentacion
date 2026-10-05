# Monitor de ejecucion de procesos con eBPF

Este proyecto observa llamadas al syscall `execve` en Linux y muestra en la
terminal el identificador del proceso que realiza la llamada (PID), el PID de
su proceso padre (PPID) y el nombre corto del proceso. La captura se realiza
en el kernel con un programa eBPF escrito en C; un programa Python, usando BCC,
carga ese programa, recibe sus eventos y los imprime.

El monitor observa la entrada al syscall: registra el proceso que intenta
ejecutar `execve`, no el nombre ni la ruta del ejecutable solicitado. Por ello,
puede emitir un evento aunque la llamada falle, y no necesariamente representa
la creacion de un proceso nuevo.

## Componentes

| Archivo | Responsabilidad |
| --- | --- |
| `processes.c` | Define el programa eBPF que se ejecuta en el kernel y envia los datos de cada evento. |
| `monitor.py` | Carga y conecta el programa eBPF, recibe los datos del buffer y los presenta en la terminal. |

## Flujo de datos

1. `monitor.py` lee `processes.c` y entrega su contenido a BCC.
2. BCC compila y carga el programa eBPF.
3. Python conecta la funcion `trace_execve` a `__x64_sys_execve` mediante un
   kprobe.
4. Cuando se alcanza ese punto del kernel, eBPF obtiene los datos del proceso y
   los envia al buffer de rendimiento `events`.
5. `perf_buffer_poll()` recibe cada evento y llama a `print_event()`, que lo
   decodifica y lo imprime.

## Codigo eBPF: `processes.c`

- Los encabezados `uapi/linux/ptrace.h` y `linux/sched.h` proporcionan las
  definiciones del contexto de registros y de las estructuras del kernel que
  usa el programa.
- `struct event_t` define el formato del evento que se envia a Python:
  `pid` y `ppid` son enteros de 32 bits sin signo; `comm` es el nombre corto
  del proceso, con espacio para `TASK_COMM_LEN` bytes (16 en Linux).
- `BPF_PERF_OUTPUT(events)` declara el canal de salida que BCC expone a Python.
- `trace_execve(struct pt_regs *ctx)` es la funcion ejecutada por el kprobe.
  Inicializa un evento a cero y obtiene el proceso actual con
  `bpf_get_current_pid_tgid()`. El desplazamiento de 32 bits selecciona el
  TGID, que corresponde al PID del proceso en este reporte.
- La funcion obtiene el `task_struct` actual y lee el TGID de su padre real
  (`real_parent->tgid`) para llenar `ppid`. El comentario del codigo indica
  que BCC reescribe el acceso al campo del kernel de forma compatible con su
  instrumentacion.
- `bpf_get_current_comm()` copia el nombre corto del proceso actual a `comm`.
- `events.perf_submit()` envia la estructura al espacio de usuario. La funcion
  devuelve `0`; el programa no cambia el resultado del syscall observado.

## Codigo Python: `monitor.py`

- `from bcc import BPF` importa la interfaz de BCC para compilar y cargar
  programas eBPF; `ctypes` permite interpretar la memoria recibida como una
  estructura C.
- El bloque `open("processes.c")` lee el codigo C y `BPF(text=program)` pide a
  BCC que lo compile y lo cargue en el kernel.
- `attach_kprobe()` conecta el punto de entrada `__x64_sys_execve` con la
  funcion eBPF `trace_execve`. El nombre del punto de instrumentacion es
  especifico de Linux x86 de 64 bits.
- La clase `Event` describe el formato de los datos que Python espera recibir:
  dos enteros sin signo y el campo de bytes `comm`.
- `print_event(cpu, data, size)` convierte el puntero recibido en una
  estructura `Event` y muestra PID, PPID y nombre. El callback recibe tambien
  el CPU y el tamano del evento, aunque no los utiliza. La decodificacion usa
  `errors="replace"` para sustituir bytes que no puedan decodificarse.
- `b["events"].open_perf_buffer(print_event)` abre el buffer `events` declarado
  en C y registra el callback.
- El bucle llama a `perf_buffer_poll()` para esperar eventos. Al pulsar
  `Ctrl+C`, captura `KeyboardInterrupt` y termina el bucle.


## Requisitos y ejecucion

- Linux con BCC instalado, incluidos sus bindings de Python.
- Permisos suficientes para cargar programas eBPF y adjuntar kprobes
  (normalmente se ejecuta con `sudo`).
- Una arquitectura y un kernel que expongan el simbolo `__x64_sys_execve`.
- Si la instalacion de BCC requiere compilar programas para el kernel, tambien
  pueden ser necesarios los encabezados correspondientes al kernel en uso.

Ejecuta el script desde el directorio `processes`, porque abre `processes.c`
usando una ruta relativa:

```bash
cd processes
sudo python3 monitor.py
```

Al iniciar, el programa indica que esta observando ejecuciones. Cuando otros
procesos realicen llamadas a `execve`, imprime lineas similares a:

```text
PID=4123   PPID=4100   PROCESS=bash
```

Pulsa `Ctrl+C` para detenerlo.

## Alcance y limitaciones

- El kprobe esta fijado a `__x64_sys_execve`, por lo que el punto de conexion
  depende de la arquitectura y de los simbolos disponibles en el kernel.
- El codigo observa `execve`; no instrumenta `execveat` ni otros eventos de
  creacion o finalizacion de procesos.
- `comm` es el nombre corto del proceso actual, limitado por `TASK_COMM_LEN`;
  no es la ruta ni necesariamente el nombre del ejecutable solicitado.
- El programa no captura argumentos, rutas, codigos de retorno ni resultados
  de `execve`.
