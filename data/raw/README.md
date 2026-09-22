# data/raw — Dataset original (inmutable)

Esta carpeta contiene el dataset **sin modificar**. Nunca se limpia, reescribe ni
transforma. Cualquier procesamiento debe leer de aquí y escribir en
`data/interim/` o `data/processed/`.

## Fuente

- **Paper:** Hossain et al., *BMC Medical Informatics and Decision Making*, 2026, 26:79
- **DOI del paper:** 10.1186/s12911-026-03343-1
- **DOI del dataset:** 10.17632/ckhgtgdg4f
- **Licencia:** CC BY 4.0
- **Fecha de acceso:** 2026-09-21

## Archivo

- `Mathernal_Risk.csv` — copia byte a byte de
  `workspace-reference/dataset/Mathernal_Risk_1.csv`

## Integridad

- **SHA-256:** `2d5b35af3c401329ce3dfd8ef0fb48057f66570e7bae24f6f40c970cb012ae0b`
- **Filas:** 6103
- **Columnas:** 11

## Sobre la columna `Name`

El CSV incluye una columna `Name`. Estos nombres provienen de la publicación
original en Mendeley Data (CC BY 4.0) y **no pertenecen a pacientes de
GynFem**. Se versionan sin alterar únicamente para preservar la trazabilidad
del SHA-256 frente a la fuente original. El pipeline de limpieza (PR #2)
descarta esta columna en su primer paso: nunca se usa como feature de
entrenamiento ni se imprime en reportes, logs o salida de consola en ninguna
etapa posterior.

## Advertencia

Esta carpeta es **inmutable**. No editar, limpiar ni sobrescribir
`Mathernal_Risk.csv` bajo ninguna circunstancia.
