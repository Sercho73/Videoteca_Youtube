# Arquitectura de Videoteca

Videoteca permite buscar y organizar varias listas de YouTube desde una aplicación local. Usa Python 3.9+, SQLite y HTML/CSS/JavaScript sin dependencias de producto.

## Componentes

| Archivo | Responsabilidad |
|---|---|
| launcher.py | Inicia o reutiliza el servidor local, guarda PID y registro y abre el navegador. |
| youtubelibrary/server.py | Sirve la interfaz y las operaciones HTTP en 127.0.0.1:8790; comprueba Host, Origin y token. |
| youtubelibrary/catalog.py | Valida importaciones, mantiene SQLite y aplica búsqueda, filtros y orden. |
| youtubelibrary/youtube_api.py | Consulta la API oficial, pagina listas completas y conserva la configuración local de la clave. |
| youtubelibrary/publication.py | Completa fechas de publicación desde páginas públicas para importaciones manuales. |
| youtubelibrary/mobile.py | Pasarela con contraseña en una IP/subred privada, con sesiones y restricción de rutas administrativas. |
| web/importer.js | Marcador que recoge la lista cargada en YouTube y descarga JSON. |
| web/app.js | Interfaz, filtros, anotaciones, importaciones, conexión y progreso. |
| web/login.js | Entrada móvil con contraseña y errores en la misma pantalla. |
| web/guia.html | Guía de uso integrada. |

## Catálogo y actualización

Las listas se identifican por su ID de YouTube. Sus apariciones se guardan por posición; un vídeo puede estar repetido o pertenecer a varias listas. La interfaz muestra una ficha por vídeo y cuenta las apariciones por separado. Notas, etiquetas, favorito y estado se guardan por ID de vídeo.

Una importación completa sustituye las pertenencias de la lista. Una parcial conserva las anteriores no recogidas. La API recorre todas las páginas, comprueba posiciones y contador y vuelve a comprobar el contador antes de importar. Si falla, conserva esa lista y continúa con las demás. Las fechas son las de publicación del vídeo.

La actualización automática se solicita al abrir o recargar la página, con un mínimo de una hora entre intentos automáticos. No hay un programador de tareas cuando la página está cerrada. El botón de actualización permite solicitar otra lectura.

## Datos privados

Los datos se guardan fuera del código, en `~/Library/Application Support/YouTube Biblioteca/`. El directorio usa permisos 700; las configuraciones privadas, 600. La clave se envía únicamente a Google para las consultas de API y no se devuelve al navegador. El repositorio y las copias JSON del catálogo no incluyen la clave ni la contraseña móvil.

El acceso móvil requiere una red de confianza porque utiliza HTTP. La pasarela valida IP de origen/subred, Host y Origin, exige sesión y conserva el token CSRF del backend. La sesión usa una cookie HttpOnly/SameSite=Strict y caduca a las 12 horas. Cinco intentos fallidos bloquean temporalmente la entrada para esa IP. Las rutas de configuración de Google y consulta/renovación del acceso móvil quedan limitadas al Mac.

El acceso por Internet no está configurado. No se instala ningún servicio de arranque automático ni se abre ningún puerto en el router.
