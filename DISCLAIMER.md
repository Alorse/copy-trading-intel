# Disclaimer

## Esto no es asesoría financiera

Este repositorio es un **proyecto de análisis de datos**. Nada de lo que contiene —los reportes
`TOP_YYYY-MM.md`, el `roster.json`, los pesos de asignación, los hallazgos de `analysis/`— es una
recomendación de inversión, una oferta, ni una invitación a operar o a copiar a nadie.

El copy-trading con futuros apalancados puede hacerte perder **más de lo que depositas**. Las
métricas de aquí describen el pasado de una ventana corta y particular; no predicen nada. Si
actúas sobre esta información, es bajo tu exclusiva responsabilidad y conviene que consultes a
un asesor financiero con licencia.

El software se entrega "tal cual", sin garantías de ningún tipo (ver [LICENSE](LICENSE)).

## Sobre los traders nombrados

Los nicknames que aparecen en el análisis son los que **las propias plataformas publican** en sus
páginas de copy-trading, junto con las métricas que ellas mismas exponen.

Las etiquetas del detector —`loss_hider`, `lottery`, `roi_artifact`, `ruin_risk`, `no_alpha` y las
demás— son **clasificaciones estadísticas automáticas**, producidas por reglas deterministas
sobre esa data pública y documentadas en `pipeline/detect.py`. Describen la *forma* de un
historial de posiciones cerradas, no la conducta ni las intenciones de una persona.

En particular, `loss_hider` marca la firma numérica de un historial con win rate de cierres muy
alto junto a un drawdown de portfolio alto. Esa firma es **compatible** con no cerrar las
posiciones perdedoras, pero también con otras explicaciones que esta data no permite distinguir:
el historial público solo muestra posiciones **cerradas**. La etiqueta no afirma que nadie esté
ocultando nada ni actuando de mala fe.

Cualquier lectura de estas etiquetas como acusación de fraude o mala conducta es una lectura
incorrecta.

## Sobre la data

Los datos provienen de endpoints HTTP **públicos y sin autenticación** de Binance y Phemex,
consultados con rate limiting (~0.4-0.5 s entre llamadas). Este repositorio **no redistribuye**
los dumps crudos: quien quiera reproducir el análisis genera su propio snapshot. Revisa los
términos de servicio de cada plataforma antes de correr los scrapers; el uso que hagas de ellos
es responsabilidad tuya.

Si eres uno de los traders analizados y quieres que se retire tu nickname del análisis
publicado, abre un issue.

## Sin afiliación

Este proyecto no está afiliado, respaldado ni patrocinado por Binance, Phemex ni ninguna otra
plataforma. Todas las marcas pertenecen a sus respectivos dueños.
