# Monitor de intentos de apertura de archivos con eBPF

Este proyecto observa llamadas al tracepoint `sys_enter_openat` del kernel de
Linux. Cada vez que un proceso entra a `openat`, el programa eBPF obtiene el
PID del proceso, su nombre corto y la cadena de ruta que el proceso pasó como
argumento `filename`. Después envía esos datos a un programa Python, que los
imprime en la terminal.

Es un monitor de **intentos de apertura**, no una auditoría de accesos
completados: el evento se captura al entrar al syscall, antes de conocer su
resultado. Por tanto, una línea no garantiza que el archivo exista, que se
haya abierto correctamente ni que luego se haya leído o escrito.

## Componentes

| Archivo | Responsabilidad |
| --- | --- |
| `files_access.c` | Define el programa eBPF y captura los datos de cada entrada a `openat`. |
| `monitor.py` | Compila y carga el programa mediante BCC, recibe eventos y los imprime. |

## Recorrido completo de un evento

1. Python lee `files_access.c` desde el directorio de trabajo actual.
2. `BPF(text=program)` pide a BCC que compile el código C y lo cargue en el
   kernel.
3. La macro `TRACEPOINT_PROBE(syscalls, sys_enter_openat)` de BCC conecta la
   función eBPF al tracepoint de entrada al syscall `openat`.
4. Cuando un proceso invoca `openat`, el kernel ejecuta el programa eBPF.
5. El programa obtiene el TGID del proceso, copia su nombre corto y lee la
   cadena de ruta desde el espacio de memoria de usuario del proceso.
6. `events.perf_submit()` envía el evento por el buffer de rendimiento `events`.
7. Python mantiene abierto ese buffer; cuando llega un evento, BCC invoca
   `print_event()`, que interpreta los bytes como una estructura `Event` y
   escribe una fila en la terminal.

## Código eBPF en `files_access.c`

### Encabezado y formato del evento

```c
#include <uapi/linux/ptrace.h>

struct event_t {
    u32 pid;
    char comm[64];
    char filename[256];
};
```

- El encabezado proporciona definiciones usadas por los programas BPF y por
  las macros de instrumentación de BCC.
- `struct event_t` establece el formato binario compartido con Python:
  - `pid`: entero sin signo de 32 bits.
  - `comm`: arreglo de 64 bytes para el nombre corto del proceso.
  - `filename`: arreglo de 256 bytes para la ruta recibida en `openat`.
- El orden y el tamaño de estos campos deben coincidir con los declarados en
  la clase Python `Event`. Actualmente coinciden: 4 + 64 + 256 bytes.
- El evento se inicializa a cero antes de rellenarse. Esto deja en cero los
  bytes restantes de los arreglos cuando las cadenas son más cortas.

### Canal de eventos

```c
BPF_PERF_OUTPUT(events);
```

Declara un buffer de rendimiento llamado `events`. El nombre debe coincidir
con el que Python utiliza en `b["events"]`. Este mecanismo transporta registros
desde el contexto del kernel hasta el proceso de usuario; no escribe archivos
ni imprime directamente desde eBPF.

### Hook de entrada a `openat`

```c
TRACEPOINT_PROBE(syscalls, sys_enter_openat)
```

BCC genera y conecta el programa al tracepoint de entrada del syscall
`openat`. El parámetro `args` que BCC proporciona a la función contiene los
campos del tracepoint, entre ellos `filename`, el puntero a la cadena que el
proceso solicitó abrir.

El hook se ejecuta al entrar al syscall. No espera a la salida de `openat` y
por ello no conoce el descriptor de archivo ni el código de error o éxito.

### Obtención de los datos del proceso

```c
struct event_t event = {};

event.pid = bpf_get_current_pid_tgid() >> 32;
```

`event = {}` inicializa los campos en cero. `bpf_get_current_pid_tgid()` devuelve
un valor de 64 bits que contiene identificadores de proceso e hilo. Al
desplazarlo 32 bits se obtiene el TGID, normalmente el PID visible del proceso
(no el identificador individual de cada hilo).

```c
bpf_get_current_comm(&event.comm, sizeof(event.comm));
```

Copia a `comm` el nombre corto del proceso actual. No es una ruta al ejecutable
y está limitado al tamaño del arreglo (64 bytes en este evento).

```c
bpf_probe_read_user_str(
    &event.filename,
    sizeof(event.filename),
    args->filename
);
```

Lee una cadena terminada en nulo desde la dirección de usuario indicada por
`args->filename` y la copia a `event.filename`. Se limita a 256 bytes, incluido
el terminador nulo cuando cabe. Una ruta más larga puede quedar truncada. El
valor de retorno de esta lectura no se comprueba en el código, así que el
programa no informa por separado de errores de lectura.

La cadena es exactamente el argumento de ruta del syscall, no necesariamente
una ruta absoluta resuelta. En particular, puede ser relativa y su resolución
depende del directorio actual o del descriptor de directorio pasado a
`openat`; el monitor no guarda ese descriptor ni resuelve la ruta final.

### Envío y retorno

```c
events.perf_submit(
    args,
    &event,
    sizeof(event)
);

return 0;
```

`perf_submit` envía el evento completo al buffer `events`. La función devuelve
cero y no altera el resultado de la operación de apertura. El código no
captura el resultado del syscall ni diferencia entre apertura de lectura,
escritura, creación u otros modos.

## Código Python en `monitor.py`

### Importaciones y carga del programa

```python
from bcc import BPF
import ctypes as ct
```

- `BPF` es la interfaz de BCC usada para compilar y cargar el código eBPF.
- `ctypes` permite describir en Python la estructura de bytes definida en C.

```python
with open("files_access.c") as f:
    program = f.read()

b = BPF(text=program)
```

El archivo C se abre usando una ruta relativa al directorio de trabajo actual,
no relativa automáticamente a la ubicación de `monitor.py`. Luego BCC compila
el texto, carga el programa y procesa la macro del tracepoint. Los errores de
compilación, permisos o carga se producirán al construir `BPF`.

### Kprobe comentado

```python
#b.attach_kprobe(
#    event="__x64_sys_openat",
#    fn_name="trace_open"
#)
```

Este bloque está comentado y no se ejecuta. Muestra una alternativa basada en
un kprobe, pero el programa C actual no define una función llamada
`trace_open`. La instrumentación activa es el tracepoint declarado en C,
`sys_enter_openat`; ese tracepoint no requiere llamar a `attach_kprobe()` desde
Python.

### Estructura que interpreta el evento

```python
class Event(ct.Structure):
    _fields_ = [
        ("pid", ct.c_uint),
        ("comm", ct.c_char * 64),
        ("filename", ct.c_char * 256),
    ]
```

`Event` refleja los campos de `struct event_t` en el mismo orden y con los
mismos tamaños. `ct.c_uint` corresponde al `u32` de C en la plataforma Linux
habitual. `ct.c_char * 64` y `ct.c_char * 256` representan los dos arreglos de
caracteres. Mantener estas definiciones sincronizadas es esencial: si cambia el
formato en C, también debe cambiar la estructura de Python.

### Callback e impresión

```python
def print_event(cpu, data, size):
    event = ct.cast(
        data,
        ct.POINTER(Event)
    ).contents
```

BCC llama a esta función cuando recibe un evento. `data` apunta a los bytes
enviados desde C; `ct.cast(...).contents` los interpreta como una instancia de
`Event`. Los argumentos `cpu` y `size` los proporciona BCC, pero el código no
los consulta ni valida el tamaño recibido.

```python
    comm = event.comm.decode(errors="replace")
    filename = event.filename.decode(errors="replace")
```

Los arreglos de bytes se decodifican como texto. `errors="replace"` evita que
una secuencia de bytes no válida interrumpa la impresión y la reemplaza por un
carácter de sustitución.

```python
    print(
        f"{event.pid:<7} "
        f"{comm:<15} "
        f"{filename}"
    )
```

Imprime PID, comando y ruta en columnas. `<7` y `<15` alinean los dos primeros
valores a la izquierda con el ancho indicado; la ruta se imprime después, sin
un ancho fijo.

### Registro del buffer y ciclo de espera

```python
b["events"].open_perf_buffer(print_event)
```

Busca el buffer `events` declarado en C y registra `print_event` como callback
para los eventos que lleguen.

El programa imprime un mensaje y una cabecera de columnas. El mensaje
`Watching file access...` aparece dos veces en el código actual. Después llama
a `b.perf_buffer_poll()` una vez y entra en un bucle que vuelve a llamar a la
misma función. Cada llamada espera y procesa eventos; al pulsar `Ctrl+C`,
`KeyboardInterrupt` rompe el bucle y finaliza el script.

## Requisitos y ejecución

- Linux con BCC instalado y sus bindings para Python disponibles.
- Permisos suficientes para cargar programas eBPF y leer el tracepoint
  (normalmente se ejecuta con `sudo`).
- El kernel debe exponer el tracepoint `syscalls:sys_enter_openat`.
- En instalaciones de BCC que compilan contra el kernel local pueden hacer
  falta los encabezados de ese kernel.

Ejecuta el script desde el directorio `files`, ya que `monitor.py` abre
`files_access.c` con una ruta relativa:

```bash
cd files
sudo python3 monitor.py
```

Mientras está activo, abre archivos desde otra terminal o aplicación. El
monitor mostrará filas similares a:

```text
PID     COMMAND         FILE
--------------------------------------------------------------------------------
1234    bash            /etc/hosts
```

La línea representa que ese proceso pasó esa cadena de ruta a `openat`; no
confirma que la apertura haya tenido éxito. Pulsa `Ctrl+C` para detener el
monitor.

## Alcance y limitaciones

- Solo observa entradas a `openat`. No instrumenta explícitamente
  `openat2`, `creat` u otros syscalls de apertura. Algunas bibliotecas o
  herramientas implementan una apertura usando `openat`, pero no se debe
  interpretar esto como cobertura universal de toda actividad con archivos.
- Registra el argumento `filename`, no la ruta canónica final ni el descriptor
  devuelto por el kernel.
- Puede mostrar intentos fallidos porque captura el syscall antes de que
  termine.
- No registra el proceso que posteriormente lee, escribe, cierra o modifica el
  archivo; tampoco captura el modo de apertura, las banderas, el resultado o
  los datos transferidos.
- El nombre corto del proceso y la ruta tienen tamaños fijos. El nombre puede
  ser limitado y la ruta puede truncarse a 255 bytes de contenido, más el
  terminador nulo.
- El callback no valida el argumento `size` antes de interpretar el puntero
  como `Event`.
- El texto de ruta se lee desde memoria de usuario. Si esa lectura falla, el
  código actual no expone una indicación explícita del error.
