# Problemas conocidos

## `BrokenProcessPool` / `WinError 6` en joblib-loky bajo CPU saturada (Windows)

**Resumen:** en Windows, con la CPU saturada al 100 %, los workers de
joblib/loky pueden fallar con `OSError: [WinError 6] Controlador no válido`
en `call_queue.get()` → `self._sem.release()`. El proceso padre lo reporta,
de forma engañosa, como
`BrokenProcessPool: A task has failed to un-serialize`.

**Dónde se ve:** en cualquier `GridSearchCV(n_jobs=-1)` de
`scripts/train_model.py`, y por tanto en los tests que llaman a
`train_model.main()`.

**Referencias upstream:** mismo síntoma que
[joblib#901](https://github.com/joblib/joblib/issues/901). Es de la misma
familia que [loky#175](https://github.com/joblib/loky/issues/175), abierto
desde 2018.

**Evidencia (2026-09-24, joblib 1.6.0 / loky 3.6.0, Python 3.12.10, 12 núcleos):**

- Se reproduce con un script mínimo sin ningún código de este proyecto: un
  `GridSearchCV(n_jobs=-1)` sobre datos sintéticos, con 12 procesos
  saturando la CPU.
- Sin carga: 0 fallos en 19 corridas completas de la suite, 0 en 11 corridas
  del ejercicio de mutación y 0 en 300 búsquedas del script mínimo.
- Con carga: falló en 3 de 3 corridas de la suite.
- Instrumentando los workers se vio que el handle del semáforo llega válido
  al worker y se cierra durante la ejecución de su primera tarea. Se
  descartaron los cierres desde código Python y los cierres desde otros
  procesos; no se identificó el cierre a nivel nativo.

**Conclusión:** no se reproduce en uso normal y no es código de este
proyecto. No requiere acción. Si una corrida falla con este error, repetirla
con la máquina sin carga.
