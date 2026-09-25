-- 0004 — Evaluaciones (predicciones) con su trazabilidad completa.
--
-- Cada fila guarda los cuatro elementos de docs/ML_SPEC.md, Sección 6:
--   1. `input_*`: las 8 variables clínicas evaluadas (copia de la entrada, de
--      modo que corregir la medición no altere una predicción ya emitida);
--   2. `model_*`: el vector exacto que entró al modelo, en unidades del dataset
--      y en el orden de models/model_metadata.json;
--   3. `model_version`;
--   4. `conversion_schema_version`.
-- Además, los avisos de extrapolación emitidos, tal como los devolvió la API.
--
-- La fila es inmutable: solo se admite el borrado lógico.

CREATE TABLE gynfem.predictions (
    id                                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at                        timestamptz NOT NULL DEFAULT now(),
    updated_at                        timestamptz NOT NULL DEFAULT now(),
    deleted_at                        timestamptz,
    created_by                        uuid,
    updated_by                        uuid,
    deleted_by                        uuid,
    measurement_id                    uuid NOT NULL REFERENCES gynfem.clinical_measurements (id)
                                          ON DELETE RESTRICT ON UPDATE RESTRICT,
    input_age_years                   double precision NOT NULL,
    input_temperature_c               double precision NOT NULL,
    input_heart_rate_bpm              double precision NOT NULL,
    input_systolic_bp_mmhg            double precision NOT NULL,
    input_diastolic_bp_mmhg           double precision NOT NULL,
    input_bmi_kg_m2                   double precision NOT NULL,
    input_hba1c_percent               double precision NOT NULL,
    input_fasting_glucose_mg_dl       double precision NOT NULL,
    model_age_years                   double precision NOT NULL,
    model_temperature_f               double precision NOT NULL,
    model_heart_rate_bpm              double precision NOT NULL,
    model_systolic_bp_mmhg            double precision NOT NULL,
    model_diastolic_bp_mmhg           double precision NOT NULL,
    model_bmi_kg_m2                   double precision NOT NULL,
    model_hba1c_mmol_mol              double precision NOT NULL,
    model_fasting_glucose_mmol_l      double precision NOT NULL,
    risk_level                        text NOT NULL,
    prob_high                         double precision NOT NULL,
    prob_mid                          double precision NOT NULL,
    prob_low                          double precision NOT NULL,
    extrapolation_warnings            jsonb NOT NULL DEFAULT '[]'::jsonb,
    model_version                     text NOT NULL,
    conversion_schema_version         text NOT NULL,
    predicted_at                      timestamptz NOT NULL,

    -- En PostgreSQL `NaN` es mayor que todo número: `x < 'Infinity'` también lo excluye.
    CONSTRAINT predictions_values_finite CHECK (
        input_age_years > '-Infinity' AND input_age_years < 'Infinity'
        AND input_temperature_c > '-Infinity' AND input_temperature_c < 'Infinity'
        AND input_heart_rate_bpm > '-Infinity' AND input_heart_rate_bpm < 'Infinity'
        AND input_systolic_bp_mmhg > '-Infinity' AND input_systolic_bp_mmhg < 'Infinity'
        AND input_diastolic_bp_mmhg > '-Infinity' AND input_diastolic_bp_mmhg < 'Infinity'
        AND input_bmi_kg_m2 > '-Infinity' AND input_bmi_kg_m2 < 'Infinity'
        AND input_hba1c_percent > '-Infinity' AND input_hba1c_percent < 'Infinity'
        AND input_fasting_glucose_mg_dl > '-Infinity' AND input_fasting_glucose_mg_dl < 'Infinity'
        AND model_age_years > '-Infinity' AND model_age_years < 'Infinity'
        AND model_temperature_f > '-Infinity' AND model_temperature_f < 'Infinity'
        AND model_heart_rate_bpm > '-Infinity' AND model_heart_rate_bpm < 'Infinity'
        AND model_systolic_bp_mmhg > '-Infinity' AND model_systolic_bp_mmhg < 'Infinity'
        AND model_diastolic_bp_mmhg > '-Infinity' AND model_diastolic_bp_mmhg < 'Infinity'
        AND model_bmi_kg_m2 > '-Infinity' AND model_bmi_kg_m2 < 'Infinity'
        AND model_hba1c_mmol_mol > '-Infinity' AND model_hba1c_mmol_mol < 'Infinity'
        AND model_fasting_glucose_mmol_l > '-Infinity' AND model_fasting_glucose_mmol_l < 'Infinity'
    ),
    -- Los niveles que produce RISK_LEVELS (app/services/prediction.py) a partir
    -- de las clases del modelo; un test los deriva de model_metadata.json.
    CONSTRAINT predictions_risk_level_valid CHECK (risk_level IN ('high', 'mid', 'low')),
    CONSTRAINT predictions_probabilities_valid CHECK (
        prob_high BETWEEN 0 AND 1 AND prob_mid BETWEEN 0 AND 1 AND prob_low BETWEEN 0 AND 1
        AND abs(prob_high + prob_mid + prob_low - 1) < 1e-9
    ),
    CONSTRAINT predictions_warnings_is_array CHECK (jsonb_typeof(extrapolation_warnings) = 'array'),
    CONSTRAINT predictions_model_version_semver CHECK (model_version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    CONSTRAINT predictions_conversion_version_semver CHECK (conversion_schema_version ~ '^[0-9]+\.[0-9]+\.[0-9]+$')
);
ALTER TABLE gynfem.predictions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE gynfem.predictions FROM PUBLIC, anon, authenticated;

CREATE INDEX predictions_measurement_idx ON gynfem.predictions (measurement_id);
CREATE INDEX predictions_predicted_at_idx ON gynfem.predictions (predicted_at);

-- Una predicción emitida no cambia: solo admite el borrado lógico. Se comparan
-- todas las columnas salvo las de actualización y borrado, también las que se
-- añadan en el futuro.
CREATE FUNCTION gynfem.forbid_prediction_changes() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE
    mutables CONSTANT text[] := ARRAY['updated_at', 'updated_by', 'deleted_at', 'deleted_by'];
BEGIN
    IF (to_jsonb(NEW) - mutables) IS DISTINCT FROM (to_jsonb(OLD) - mutables) THEN
        RAISE EXCEPTION 'una predicción es inmutable: solo admite el borrado lógico';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION gynfem.forbid_prediction_changes() FROM PUBLIC, anon, authenticated;

-- Los triggers BEFORE se disparan en orden alfabético: `immutable` va antes que `set_updated_at`.
CREATE TRIGGER predictions_immutable BEFORE UPDATE ON gynfem.predictions
    FOR EACH ROW EXECUTE FUNCTION gynfem.forbid_prediction_changes();
CREATE TRIGGER predictions_set_updated_at BEFORE UPDATE ON gynfem.predictions
    FOR EACH ROW EXECUTE FUNCTION gynfem.set_updated_at();
CREATE TRIGGER predictions_forbid_delete BEFORE DELETE ON gynfem.predictions
    FOR EACH ROW EXECUTE FUNCTION gynfem.forbid_physical_delete();
CREATE TRIGGER predictions_forbid_truncate BEFORE TRUNCATE ON gynfem.predictions
    FOR EACH STATEMENT EXECUTE FUNCTION gynfem.forbid_physical_delete();

COMMENT ON TABLE gynfem.predictions IS 'Evaluación con los cuatro elementos de trazabilidad de ML_SPEC.md, Sección 6. Inmutable.';
