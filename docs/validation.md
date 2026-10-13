# Validación

La versión publicada procede del piloto local verificado el 13 de octubre de 2026. Antes de subirla se ejecutan de nuevo las pruebas sobre esta copia sin datos personales.

```sh
python3 -m unittest discover -s tests -v
node --check web/app.js
node --check web/importer.js
node --check web/login.js
node tests/test_importer.js
```

La batería incluye 53 pruebas Python/HTTP y cuatro comprobaciones JavaScript del importador. Cubre normalización, cobertura, deduplicación, persistencia, anotaciones, filtros por lista y duración, orden, paginación de API, conservación ante fallos y protección de credenciales. El acceso móvil comprueba autenticación, CSRF, restricciones de subred/Host/Origin, límites de intentos, caducidad y recuperación de configuración/red.

En el piloto también se completaron dos listas reales mediante la API, se comprobó la conservación de las anotaciones y se probó el acceso por la IP local con contraseña en el navegador. La interfaz y sus filtros se verificaron en escritorio y en una vista de 390×844, sin errores de consola ni desbordamiento horizontal.

No se ha validado con un móvil físico ni desde otra red. Tampoco se ha configurado Tailscale. Las pruebas automatizadas de API usan respuestas controladas y no necesitan una clave real. La importación manual depende de la estructura y carga de YouTube; una recogida incompleta debe conservar su aviso de cobertura.
