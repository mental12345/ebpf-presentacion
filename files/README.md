# Monitor de acceso a archivos con eBPF y Python

Este proyecto es un ejemplo sencillo de cómo utilizar **eBPF desde Python** para observar qué archivos están intentando abrir los procesos de un sistema Linux.

El programa utiliza:

* **Python** para ejecutar y recibir los eventos.
* **BCC (BPF Compiler Collection)** como herramienta para trabajar con eBPF.
* **C** para escribir el programa eBPF que se ejecutará dentro del kernel de Linux.
* Un **tracepoint** del kernel para detectar llamadas al sistema `openat()`.

El resultado será algo parecido a:

```text
PID     COMMAND         FILE
--------------------------------------------------------------------------------
1254    bash            /etc/bash.bashrc
1254    bash            /home/ramon/test.txt
1821    python3         /tmp/data.json
1934    cat             /etc/hosts
1934    cat             /home/ramon/document.txt
```

La idea principal del proyecto es entender cómo podemos utilizar eBPF para observar lo que ocurre dentro del kernel desde una aplicación Python.

---

# 1. ¿Qué es eBPF?

Antes de ver el código, es importante entender qué problema estamos intentando resolver.

Linux tiene un kernel que se encarga de muchas operaciones del sistema:

* procesos
* memoria
* archivos
* red
* dispositivos
* llamadas al sistema
* etc.

Cuando un programa quiere hacer algo, normalmente tiene que pedirle al kernel que lo haga.

Por ejemplo, cuando ejecutamos:

```bash
cat test.txt
```

el programa `cat` necesita abrir el archivo.

Internamente termina realizando una llamada al sistema, conocida como:

```text
openat()
```

Podemos imaginarlo de forma simplificada así:

```text
cat
 |
 | openat("test.txt")
 v
Linux Kernel
 |
 | abre el archivo
 v
Filesystem
```

eBPF nos permite colocar pequeños programas dentro de determinados puntos del kernel para observar qué está ocurriendo.

En este proyecto vamos a colocar nuestro programa eBPF en:

```text
sys_enter_openat
```

Esto significa:

> "Ejecuta nuestro programa eBPF cada vez que un proceso entra al syscall `openat()`."

---

# 2. ¿Qué es BCC?

BCC significa:

```text
BPF Compiler Collection
```

BCC proporciona herramientas y librerías que hacen mucho más sencillo trabajar con eBPF.

En este proyecto utilizamos BCC desde Python:

```python
from bcc import BPF
```

Esto nos permite hacer cosas como:

```python
b = BPF(text=program)
```

Aquí BCC toma nuestro programa escrito en C, lo prepara para eBPF y lo carga en el kernel.

Por eso tenemos dos lenguajes:

```text
Python
   |
   | controla el programa
   |
   v
BCC
   |
   | carga
   v
eBPF escrito en C
   |
   v
Linux Kernel
```

Python es nuestra aplicación.

C es el programa que realmente observa los eventos dentro del kernel.

---

# 3. Estructura del proyecto

Podemos tener solamente dos archivos:

```text
file-monitor/
├── monitor.py
└── files_access.c
```

`monitor.py` contiene el programa Python.

`files_access.c` contiene el programa eBPF.

---

# 4. El programa eBPF

Nuestro archivo `files_access.c` contiene:

```c
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
```

Ahora vamos a analizarlo parte por parte.

---

# 5. Incluir las definiciones necesarias

La primera línea es:

```c
#include <uapi/linux/ptrace.h>
```

Estamos incluyendo definiciones que BCC necesita para trabajar con los programas eBPF.

No estamos escribiendo un programa C tradicional que se ejecuta como:

```bash
./programa
```

Este C será procesado por BCC y convertido en un programa eBPF que será ejecutado por el kernel.

---

# 6. La estructura `event_t`

Tenemos:

```c
struct event_t {
    u32 pid;
    char comm[64];
    char filename[256];
};
```

Esta estructura define la información que queremos enviar desde el kernel hacia Python.

Podemos pensar en ella como un pequeño mensaje.

Cada vez que ocurre un `openat()`, queremos enviar:

```text
PID
nombre del proceso
nombre del archivo
```

Por ejemplo:

```text
PID:      1234
COMMAND:  cat
FILE:     /home/ramon/test.txt
```

La estructura representa esos datos:

```text
event_t
│
├── pid
├── comm
└── filename
```

---

# 7. El PID

Tenemos:

```c
u32 pid;
```

`u32` significa un entero sin signo de 32 bits.

Aquí almacenaremos el PID del proceso que realizó el `openat()`.

Por ejemplo:

```text
1234
```

---

# 8. El nombre del proceso

Tenemos:

```c
char comm[64];
```

`char` representa caracteres.

El `[64]` significa que reservamos espacio para hasta 64 caracteres.

Aquí guardaremos el nombre del proceso.

Por ejemplo:

```text
bash
python3
cat
vim
firefox
```

Es importante entender que `comm` normalmente contiene el nombre corto del proceso, no necesariamente el comando completo.

Por ejemplo:

```text
python3
```

y no necesariamente:

```text
python3 my_script.py --verbose
```

---

# 9. El nombre del archivo

Tenemos:

```c
char filename[256];
```

Aquí reservamos espacio para almacenar el nombre o path del archivo.

Por ejemplo:

```text
/etc/hosts
```

o:

```text
/home/ramon/test.txt
```

El tamaño máximo que estamos guardando en este ejemplo es de 256 bytes.

---

# 10. `BPF_PERF_OUTPUT`

Después tenemos:

```c
BPF_PERF_OUTPUT(events);
```

Esta línea es muy importante.

Nuestro programa eBPF está ejecutándose dentro del kernel.

Pero nosotros queremos mostrar los resultados en Python.

Necesitamos algún mecanismo para transportar información:

```text
Kernel
   |
   | evento
   v
Python
```

`BPF_PERF_OUTPUT` crea un mecanismo para enviar eventos desde eBPF hacia el programa que está utilizando BCC.

En nuestro caso lo llamamos:

```text
events
```

Por eso posteriormente en Python podemos hacer:

```python
b["events"]
```

Estamos accediendo al mismo objeto que declaramos en C:

```c
BPF_PERF_OUTPUT(events);
```

---

# 11. El tracepoint

Ahora llegamos a una de las partes más importantes:

```c
TRACEPOINT_PROBE(syscalls, sys_enter_openat)
```

Esto le dice a BCC que queremos ejecutar nuestro programa cuando ocurra el tracepoint:

```text
syscalls:sys_enter_openat
```

Un tracepoint es un punto de instrumentación que el kernel proporciona para que podamos observar determinados eventos.

En este caso:

```text
syscalls
   |
   └── sys_enter_openat
```

Significa:

> Queremos observar cuando un proceso entra al syscall `openat()`.

---

# 12. ¿Qué es `openat()`?

Los programas normalmente no acceden directamente al filesystem.

Utilizan syscalls para pedirle al kernel que realice determinadas operaciones.

Por ejemplo:

```text
Programa
   |
   | openat()
   v
Kernel
   |
   v
Filesystem
```

Cuando ejecutamos:

```bash
cat test.txt
```

`cat` necesita abrir `test.txt`.

Una de las operaciones que puede utilizar es:

```text
openat()
```

Nuestro programa eBPF observa justamente ese momento.

---

# 13. Los argumentos del tracepoint

Dentro del programa tenemos:

```c
args->filename
```

`args` contiene los argumentos que el tracepoint proporciona.

Para `sys_enter_openat`, uno de esos argumentos es el nombre del archivo que el proceso está intentando abrir.

Conceptualmente podemos imaginar:

```text
args
│
├── dfd
├── filename
└── flags
```

Nos interesa:

```c
args->filename
```

porque contiene el puntero hacia el nombre del archivo que el proceso pasó al syscall.

---

# 14. Crear un evento

Dentro del programa hacemos:

```c
struct event_t event = {};
```

Estamos creando una instancia de nuestra estructura:

```c
event_t
```

La variable se llama:

```text
event
```

Inicializarla con:

```c
= {};
```

hace que sus campos comiencen inicializados en cero.

Ahora tenemos un objeto vacío:

```text
event
│
├── pid       = 0
├── comm      = ""
└── filename  = ""
```

Vamos a llenarlo.

---

# 15. Obtener el PID

Tenemos:

```c
event.pid = bpf_get_current_pid_tgid() >> 32;
```

Esta línea puede parecer complicada al principio.

La función:

```c
bpf_get_current_pid_tgid()
```

nos proporciona información sobre el proceso y el thread group actual.

Devuelve un valor de 64 bits.

Conceptualmente podemos verlo como:

```text
63                     32 31                      0
+------------------------+------------------------+
|        TGID            |          PID           |
+------------------------+------------------------+
```

Al hacer:

```c
>> 32
```

desplazamos los bits 32 posiciones hacia la derecha para obtener la parte superior.

En este contexto obtenemos el TGID, que normalmente corresponde al PID que queremos mostrar para el proceso.

El resultado se guarda en:

```c
event.pid
```

---

# 16. Obtener el nombre del proceso

Después hacemos:

```c
bpf_get_current_comm(
    &event.comm,
    sizeof(event.comm)
);
```

`bpf_get_current_comm()` obtiene el nombre del proceso actual.

Tenemos:

```c
&event.comm
```

que indica dónde queremos guardar el resultado.

Y:

```c
sizeof(event.comm)
```

indica cuánto espacio tenemos disponible.

Como declaramos:

```c
char comm[64];
```

tenemos espacio para 64 bytes.

Después de esta operación podemos tener algo como:

```text
event.comm = "cat"
```

---

# 17. Leer el nombre del archivo

Esta es probablemente la línea más importante del ejemplo:

```c
bpf_probe_read_user_str(
    &event.filename,
    sizeof(event.filename),
    args->filename
);
```

¿Por qué necesitamos una función especial para esto?

Porque `args->filename` apunta a memoria perteneciente al proceso que realizó el syscall.

No podemos simplemente hacer:

```c
event.filename = args->filename;
```

Eso no sería una lectura válida de la memoria del proceso.

Necesitamos utilizar una función proporcionada para que eBPF pueda leer de forma segura una cadena desde memoria de usuario.

Por eso utilizamos:

```c
bpf_probe_read_user_str()
```

Conceptualmente:

```text
Proceso
   |
   | filename
   v
memoria del proceso
   |
   | bpf_probe_read_user_str()
   v
event.filename
```

Después de esta operación podemos tener:

```text
event.filename = "/etc/hosts"
```

---

# 18. Enviar el evento a Python

Una vez que tenemos:

```text
PID
nombre del proceso
nombre del archivo
```

necesitamos enviarlo a Python.

Utilizamos:

```c
events.perf_submit(
    args,
    &event,
    sizeof(event)
);
```

Esto envía nuestra estructura:

```c
event
```

a través del buffer que creamos anteriormente:

```c
BPF_PERF_OUTPUT(events);
```

Podemos visualizar todo el flujo así:

```text
Linux Kernel
    |
    |
    | sys_enter_openat
    v
eBPF program
    |
    |
    | crea event
    v
event_t
    |
    ├── pid
    ├── comm
    └── filename
    |
    v
BPF_PERF_OUTPUT
    |
    v
Python
```

---

# 19. `return 0`

Al final tenemos:

```c
return 0;
```

El programa eBPF termina y devuelve cero.

En este caso simplemente estamos indicando que terminamos correctamente.

---

# 20. El programa Python

Ahora podemos observar el otro lado.

Nuestro `monitor.py` contiene:

```python
from bcc import BPF
import ctypes as ct
```

---

# 21. Importar BCC

Tenemos:

```python
from bcc import BPF
```

`BPF` es la clase principal que utilizamos para cargar y trabajar con nuestro programa eBPF.

---

# 22. Importar ctypes

Tenemos:

```python
import ctypes as ct
```

Necesitamos `ctypes` porque los datos que vienen desde C tienen una estructura binaria.

Python necesita saber cómo interpretar esos bytes.

Por ejemplo, C tiene:

```c
u32 pid;
```

y Python necesita saber:

```python
ct.c_uint
```

para interpretar correctamente esos datos.

---

# 23. Leer el programa C

Tenemos:

```python
with open("files_access.c") as f:
    program = f.read()
```

Aquí simplemente abrimos nuestro archivo:

```text
files_access.c
```

y lo cargamos como texto en Python.

Por ejemplo:

```python
program
```

contendrá todo nuestro código C.

---

# 24. Crear el programa BPF

Después:

```python
b = BPF(text=program)
```

Esta es una de las líneas más importantes de Python.

Estamos entregando el código C a BCC.

BCC se encarga de preparar y cargar el programa eBPF.

Conceptualmente:

```text
files_access.c
      |
      v
    Python
      |
      v
     BCC
      |
      v
   eBPF/kernel
```

---

# 25. La estructura Python

Ahora necesitamos definir en Python exactamente cómo interpretar el evento que viene desde C.

Tenemos:

```python
class Event(ct.Structure):
    _fields_ = [
        ("pid", ct.c_uint),
        ("comm", ct.c_char * 64),
        ("filename", ct.c_char * 256),
    ]
```

Esta estructura debe corresponder con la estructura C:

```c
struct event_t {
    u32 pid;
    char comm[64];
    char filename[256];
};
```

Es muy importante que ambas estructuras tengan el mismo orden y tamaños compatibles.

C:

```text
pid
comm
filename
```

Python:

```text
pid
comm
filename
```

---

# 26. Correspondencia entre C y Python

Podemos verlo así:

| C           | Python            |
| ----------- | ----------------- |
| `u32`       | `ct.c_uint`       |
| `char[64]`  | `ct.c_char * 64`  |
| `char[256]` | `ct.c_char * 256` |

Esta correspondencia permite que Python interprete correctamente los bytes enviados desde el kernel.

---

# 27. La función `print_event`

Tenemos:

```python
def print_event(cpu, data, size):
```

Esta función será llamada cada vez que llegue un evento desde eBPF.

BCC nos proporciona:

```text
cpu
data
size
```

El parámetro más importante para nosotros es:

```python
data
```

porque contiene los datos enviados por:

```c
events.perf_submit(...)
```

---

# 28. Convertir los datos a nuestra estructura

Tenemos:

```python
event = ct.cast(
    data,
    ct.POINTER(Event)
).contents
```

Aquí estamos diciendo:

> "Interpreta los bytes recibidos como una estructura `Event`."

Después podemos acceder directamente a:

```python
event.pid
event.comm
event.filename
```

---

# 29. Convertir `comm`

Tenemos:

```python
comm = event.comm.decode(errors="replace")
```

Desde C recibimos:

```c
char comm[64]
```

Eso son bytes.

Python necesita convertir esos bytes a un `str`.

Por eso utilizamos:

```python
.decode()
```

Por ejemplo:

```text
b"bash"
```

se convierte en:

```text
"bash"
```

---

# 30. Convertir `filename`

Hacemos exactamente lo mismo:

```python
filename = event.filename.decode(errors="replace")
```

Convertimos los bytes recibidos desde C a un string de Python.

Por ejemplo:

```text
b"/etc/hosts"
```

se convierte en:

```text
"/etc/hosts"
```

---

# 31. Mostrar el resultado

Finalmente:

```python
print(
    f"{event.pid:<7} "
    f"{comm:<15} "
    f"{filename}"
)
```

Esto simplemente imprime los datos en columnas.

Por ejemplo:

```text
1234    bash            /etc/bash.bashrc
```

Los valores:

```text
<7
<15
```

son solamente formato para mantener las columnas alineadas.

---

# 32. Conectar Python con `events`

Ahora tenemos:

```python
b["events"].open_perf_buffer(print_event)
```

Recuerda que en C tenemos:

```c
BPF_PERF_OUTPUT(events);
```

Por eso en Python podemos acceder a:

```python
b["events"]
```

Estamos accediendo al canal que conecta los eventos de eBPF con Python.

Le estamos diciendo:

> "Cuando llegue un evento desde `events`, ejecuta la función `print_event`."

Visualmente:

```text
eBPF
 |
 | events.perf_submit()
 v
events
 |
 | evento
 v
print_event()
 |
 v
Python
```

---

# 33. Iniciar el monitor

Finalmente:

```python
print("Watching file access...\n")
```

simplemente muestra un mensaje indicando que el monitor comenzó.

Después:

```python
while True:
    try:
        b.perf_buffer_poll()
    except KeyboardInterrupt:
        break
```

esperamos eventos.

`perf_buffer_poll()` mantiene a Python esperando nuevos eventos.

Cuando alguien ejecuta:

```bash
cat /etc/hosts
```

ocurre aproximadamente esto:

```text
cat
 |
 | openat("/etc/hosts")
 v
Linux Kernel
 |
 | tracepoint
 v
eBPF
 |
 | crea event
 v
BPF_PERF_OUTPUT
 |
 v
Python
 |
 v
print_event()
 |
 v
1234 cat /etc/hosts
```

---

# 34. Probando el programa

Primero ejecutamos nuestro monitor.

Dependiendo de la configuración de Linux y BCC, probablemente necesitaremos privilegios de root:

```bash
sudo python3 monitor.py
```

Deberíamos ver:

```text
Watching file access...

PID     COMMAND         FILE
--------------------------------------------------------------------------------
```

Ahora, desde otra terminal:

```bash
cat /etc/hosts
```

Podríamos obtener:

```text
1234    cat             /etc/hosts
```

También podemos probar:

```bash
cat /etc/passwd
```

o:

```bash
cat /tmp/test.txt
```

o:

```bash
python3 -c "open('/tmp/example.txt').read()"
```

El monitor debería detectar los `openat()` correspondientes.

---

# 35. Algo importante: estamos observando `openat()`

El nombre del proyecto puede dar la impresión de que estamos detectando cualquier acceso a archivos.

En realidad, esta versión está observando:

```text
sys_enter_openat
```

Por lo tanto estamos detectando procesos que entran al syscall `openat()`.

Eso significa que esto:

```text
openat()
```

no necesariamente significa:

```text
read()
```

y tampoco significa:

```text
write()
```

Por ejemplo, un proceso puede abrir un archivo y nunca leerlo.

Otro proceso puede tener un descriptor de archivo abierto y posteriormente utilizar:

```text
read()
```

para leer datos.

---

# 36. ¿Qué podemos aprender de este ejemplo?

Este pequeño programa demuestra varias ideas fundamentales de eBPF.

## 36.1 eBPF puede observar el kernel

Nuestro código Python no está leyendo directamente:

```text
/proc
```

ni está ejecutando:

```bash
ps
```

ni:

```bash
lsof
```

Estamos observando un evento que ocurre dentro del kernel.

---

## 36.2 Podemos enganchar nuestro programa a eventos

En este caso utilizamos:

```c
TRACEPOINT_PROBE(syscalls, sys_enter_openat)
```

Pero eBPF puede trabajar con muchos otros tipos de eventos y mecanismos.

Por ejemplo:

```text
tracepoints
kprobes
uprobes
network hooks
etc.
```

Cada uno sirve para diferentes tipos de observabilidad.

---

## 36.3 El programa eBPF puede recolectar información

Nuestro programa obtiene:

```text
PID
process name
filename
```

y construye una estructura:

```c
struct event_t
```

---

## 36.4 Los datos pueden viajar hacia user space

El kernel no imprime directamente:

```text
1234 cat /etc/hosts
```

En lugar de eso, nuestro programa eBPF envía un evento:

```text
Kernel
   |
   v
BPF_PERF_OUTPUT
   |
   v
Python
```

Python recibe ese evento y decide qué hacer con él.

En este caso:

```python
print(...)
```

---

# 37. El concepto más importante del ejemplo

Si estás aprendiendo eBPF, probablemente la parte más importante que debes recordar de este proyecto es esta:

```text
                 USER SPACE
        ┌────────────────────────┐
        │                        │
        │       Python           │
        │                        │
        │    print_event()       │
        │          ▲             │
        └──────────┼─────────────┘
                   │
                   │ evento
                   │
        ┌──────────┼─────────────┐
        │          │             │
        │   BPF_PERF_OUTPUT      │
        │                        │
        ├────────────────────────┤
        │                        │
        │       KERNEL           │
        │                        │
        │      eBPF program      │
        │           │            │
        │           ▼            │
        │ sys_enter_openat       │
        │           │            │
        │           ▼            │
        │       openat()         │
        │                        │
        └────────────────────────┘
```

El flujo completo es:

```text
1. Un proceso llama a openat()
2. El kernel genera el tracepoint
3. Nuestro programa eBPF se ejecuta
4. eBPF obtiene el PID
5. eBPF obtiene el nombre del proceso
6. eBPF lee el nombre del archivo
7. eBPF crea un evento
8. El evento pasa a BPF_PERF_OUTPUT
9. Python recibe el evento
10. Python convierte los bytes en una estructura
11. Python imprime la información
```

Ese flujo es una de las ideas fundamentales para comenzar a entender eBPF.

---

# 38. Una posible evolución

Una vez que este ejemplo funciona, podemos hacerlo mucho más interesante.

Por ejemplo, podemos detectar diferentes tipos de operaciones:

```text
openat()   → archivo abierto
read()     → datos leídos
write()    → datos escritos
unlink()   → archivo eliminado
rename()   → archivo renombrado
mkdir()    → directorio creado
```

También podemos agregar filtros.

Por ejemplo:

```text
solo /tmp
solo archivos .log
solo procesos Python
solo un PID
ignorar nuestro propio monitor
```

También podríamos producir información como:

```text
PID     PROCESS       OPERATION    FILE
---------------------------------------------------------
1234    python3       OPEN         /tmp/data.json
1234    python3       READ         /tmp/data.json
1256    nginx         OPEN         /var/log/nginx/access.log
1256    nginx         WRITE        /var/log/nginx/access.log
```

En ese punto el programa empieza a parecerse más a una pequeña herramienta de observabilidad del sistema.

---

# 39. Resumen

Este proyecto es pequeño, pero contiene varias piezas importantes de eBPF:

```text
Python
  |
  | BCC
  v
eBPF
  |
  | Tracepoint
  v
sys_enter_openat
  |
  | información
  v
event_t
  |
  | perf buffer
  v
Python
```

La idea fundamental es:

> Python controla el programa y procesa los resultados, mientras que el programa eBPF observa los eventos desde el kernel.

En este ejemplo estamos observando `openat()` para saber qué proceso está intentando abrir qué archivo.

Una vez que se entiende este patrón, se puede reutilizar para construir muchos otros programas de observabilidad con eBPF.
