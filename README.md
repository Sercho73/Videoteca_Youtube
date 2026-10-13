# Videoteca — piloto local

Abre `Iniciar Videoteca.command` con doble clic. La aplicación está en http://127.0.0.1:8790/ El servidor principal escucha en este Mac; el acceso móvil opcional utiliza una pasarela con contraseña en la red local. Utiliza Python 3 y SQLite, sin paquetes adicionales. La importación manual funciona sin API; la sincronización completa usa una clave de YouTube Data API v3, sin OAuth.

## Conectar listas completas con YouTube

1. Pon tus listas de YouTube como **Ocultas** o **Públicas**. Las privadas siguen admitiendo importación manual.
2. En [Google Cloud](https://console.cloud.google.com/), crea un proyecto y activa **YouTube Data API v3**.
3. En **APIs y servicios → Credenciales → Crear credenciales → Clave de API**, crea una clave y limita su uso a YouTube Data API v3. Las solicitudes salen del servidor local: no uses una restricción por sitios web.
4. En Videoteca, pulsa **Conectar YouTube**, pega la clave y pulsa **Guardar y actualizar**.

La sincronización recorre todas las páginas de cada lista importada. Actualiza orden, pertenencias, títulos, duraciones y fechas de publicación. Conserva estados, favoritos, notas y etiquetas. Los vídeos eliminados de una lista dejan de pertenecer a ella; sus anotaciones permanecen guardadas en la base de datos.

**Actualizar al abrir Videoteca** viene activado. Comprueba las listas cuando abres o recargas la aplicación, como máximo una vez por hora. **Actualizar listas** permite consultar antes de ese plazo. No hay tareas programadas mientras la aplicación está cerrada. Si falla una página, el contador no coincide o cambia durante la consulta, no sustituye esa lista por datos parciales. Las otras listas se comprueban por separado.

La clave se guarda en `~/Library/Application Support/YouTube Biblioteca/youtube-api.json`, con permisos 600. Solo se envía a Google al consultar su API y no se devuelve al navegador ni se incluye en las copias JSON del catálogo. **Desconectar** retira la clave y conserva la biblioteca. No necesitas iniciar sesión en Google desde Videoteca ni configurar OAuth. Se aplica la cuota del proyecto de Google.

## Importar cualquier lista

1. Pulsa **Importar lista** y arrastra **Importar a Videoteca** a la barra de favoritos de Safari.
2. Abre la página completa de tu lista (`youtube.com/playlist?list=…`) con tu sesión habitual. Pulsa el marcador y mantén abierta la pestaña hasta que termine.
3. Vuelve a Videoteca y selecciona el JSON descargado. También puedes arrastrarlo a la ventana.

El marcador lee títulos, canales, duración, identificadores y posiciones de los elementos cargados en la página. No lee contraseñas ni cookies y no envía la lista a un servicio externo. Descarga el JSON en la carpeta de descargas configurada en Safari, que puede estar en iCloud.

La aplicación muestra cuántos elementos ha recogido frente al contador de YouTube. Si falta alguno, marca la importación como parcial. No interpreta esa diferencia como prueba de que sean vídeos privados o eliminados. Puede ocurrir por carga incompleta o por elementos que YouTube no muestra.

## Navegar

Busca por título, canal, etiquetas o notas. Puedes combinar canal, duración, estado y etiqueta. Selecciona una lista en la barra lateral o busca en todas. **Favoritos** reúne los vídeos que marques con la estrella.

Cada vídeo aparece una vez en los resultados, aunque esté repetido en una lista o pertenezca a varias. Las pertenencias y sus posiciones se conservan. **Visto** es un estado manual de Videoteca; no sincroniza tu historial de YouTube. Al pulsar un vídeo, se abre en YouTube.

## Fechas de publicación

La sincronización API obtiene la fecha de publicación del vídeo, no la fecha en que se añadió a la lista. Cada importación manual consulta en segundo plano la fecha de publicación en las páginas públicas de los vídeos. Se guarda localmente y se puede ordenar de más reciente a más antigua o al revés. Las fechas desconocidas aparecen al final. **Actualizar fechas** reintenta las que falten. No utiliza OAuth ni una clave de API. No sustituye la fecha de publicación por la de subida o importación.

## Actualizar y guardar

Repite la importación para actualizar una lista. Conserva tus favoritos, estados, etiquetas y notas. Una importación completa sustituye las pertenencias de esa lista; una parcial conserva los elementos anteriores que no haya podido recoger. Los nuevos vídeos siguen el orden del archivo importado y se conservan después las entradas anteriores no recogidas. Un título sin verificar no cambia el nombre de una lista existente. Las listas sin conexión API se actualizan mediante importación manual.

Los datos están en `~/Library/Application Support/YouTube Biblioteca/catalog.sqlite3`. **Exportar copia** descarga los datos y anotaciones en JSON para su conservación; este piloto todavía no dispone de restauración de esa copia desde la interfaz. Para una copia restaurable, cierra el servidor y copia `catalog.sqlite3`.

Las miniaturas y las fechas de publicación se consultan en YouTube, enviando los identificadores de los vídeos; los enlaces abren YouTube; el catálogo y las anotaciones se guardan localmente. No incorpora transcripciones, búsqueda dentro del audio ni clasificación automática por IA.

## Desarrollo y comprobación

Desde la carpeta de la aplicación:

```sh
python3 -m unittest discover -s tests -v
node --check web/app.js
node --check web/importer.js
node --check web/login.js
node tests/test_importer.js
```

Para ejecutar en primer plano, con el servidor anterior detenido:

```sh
python3 -m youtubelibrary.server
```

El inicio normal deja el servidor funcionando en segundo plano. Su PID se guarda en `~/Library/Application Support/YouTube Biblioteca/server.pid` y el registro en `server.log`. No se instala ningún servicio de arranque automático. Puedes detener el proceso `python3 -m youtubelibrary.server` desde Monitor de Actividad.

El importador depende de la estructura visible de YouTube. Si cambia, puede requerir una adaptación. Los archivos descargados con la primera versión de prueba, cuyos títulos empezaban por `VISTO` o `Reproduciendo`, deben volver a exportarse con el importador corregido.

Tras esta actualización, sustituye una vez el marcador de Safari por el enlace de **Importar lista**, para usar la nueva lectura del nombre y contador. Los JSON anteriores también se pueden importar.

La cabecera incluye **Guía de uso**, disponible también en `http://127.0.0.1:8790/guia.html`. El filtro de canal se limita a la lista seleccionada; Duración incluye más de 1, 2 y 3 horas, y Orden permite título Z–A y mayor duración.

## Acceso móvil por red local

En Videoteca del Mac, **Acceso móvil** muestra la URL de la red y la contraseña. El móvil debe compartir la red local del Mac. La conexión usa HTTP y requiere una Wi-Fi de confianza; el Mac debe permanecer encendido con el servidor activo. Las sesiones caducan a las 12 horas.

La pasarela escucha exclusivamente en la dirección privada de la interfaz configurada, puerto 8792; valida la subred, Host y Origin. Requiere contraseña para el catálogo y las operaciones, limita los intentos fallidos y usa una cookie HttpOnly/SameSite=Strict. Mantiene la protección CSRF del servidor local. La configuración de YouTube y la consulta de la contraseña no se exponen a la pasarela. No se ha abierto ningún puerto en el router.

Configuración privada: `~/Library/Application Support/YouTube Biblioteca/mobile-access.json`, permisos 600. Para desactivar, cambia `enabled` a `false` y reinicia Videoteca. La dirección de la interfaz se vuelve a consultar al iniciar o al pulsar Actualizar dirección en Acceso móvil; las sesiones móviles anteriores se invalidan. Si está desconectada o falla la apertura, Videoteca sigue disponible en el Mac y Acceso móvil muestra el aviso.

## Instalar desde este repositorio

Requiere macOS y Python 3.9 o posterior. Node.js solo se usa para las comprobaciones JavaScript de desarrollo.

```sh
git clone https://github.com/Sercho73/Videoteca_Youtube.git
cd Videoteca_Youtube
python3 launcher.py
```

También puedes abrir `Iniciar Videoteca.command` desde Finder. Si pierde el permiso de ejecución al descargar un ZIP, ejecuta `chmod +x "Iniciar Videoteca.command"`.

El repositorio contiene código y documentación. No contiene listas personales, SQLite, claves, contraseñas, registros ni copias de datos. Al iniciarlo en otro equipo, la biblioteca estará vacía hasta importar listas. Los datos de una instalación anterior se conservan si ejecutas el código en el mismo Mac con la misma cuenta.

### Activar acceso móvil en una instalación nueva

Crea `mobile-access.json` en la carpeta de datos, con permisos 600. Esta preparación es local: no subas el archivo al repositorio. El siguiente ejemplo crea una contraseña aleatoria y usa `en0`; comprueba tu interfaz de red antes de ejecutarlo. La aplicación obtiene de esa interfaz la IP y la máscara al arrancar.

```sh
python3 - <<'PYTHON'
import json, os, secrets
from pathlib import Path
folder = Path.home() / 'Library/Application Support/YouTube Biblioteca'
folder.mkdir(parents=True, exist_ok=True)
folder.chmod(0o700)
path = folder / 'mobile-access.json'
values = {'enabled': True, 'interface': 'en0', 'port': 8792,
          'password': secrets.token_urlsafe(18)}
fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    json.dump(values, stream)
print('Acceso móvil preparado. Reinicia el servidor de Videoteca.')
PYTHON
```

El ejemplo se detiene si el archivo ya existe, para conservar su contraseña. Reinicia el proceso del servidor; cerrar únicamente la pestaña no detiene el proceso. Después abre **Acceso móvil** en la interfaz del Mac para consultar dirección y contraseña. El acceso por Internet mediante Tailscale se ha propuesto, pero no está implementado ni configurado.

Consulta [arquitectura](docs/architecture.md), [validación](docs/validation.md) y la guía integrada `web/guia.html`.
