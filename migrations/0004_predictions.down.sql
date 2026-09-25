-- Reversión de 0004. Los índices y triggers se eliminan con la tabla.
DROP TABLE gynfem.predictions;
DROP FUNCTION gynfem.forbid_prediction_changes();
