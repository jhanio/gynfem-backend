-- 0003 — Registro de las 8 variables clínicas de una paciente en un momento dado.
--
-- Unidades clínicas peruanas, las mismas que recibe la API (docs/ML_SPEC.md,
-- Sección 4). Los nombres de columna son los campos de `PredictionRequest`.
-- `double precision` conserva exacto el float que recibió la API.
--
-- Sin límites fisiológicos en CHECK: su única fuente es
-- app/services/clinical_limits.py, y son provisionales (ML_SPEC.md,
-- Sección 5.1). Aquí solo se exige un valor finito: en PostgreSQL `NaN` es
-- mayor que todo número, así que `x < 'Infinity'` también lo excluye.

CREATE TABLE gynfem.clinical_measurements (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    deleted_at             timestamptz,
    created_by             uuid,
    updated_by             uuid,
    deleted_by             uuid,
    patient_id             uuid NOT NULL REFERENCES gynfem.patients (id)
                               ON DELETE RESTRICT ON UPDATE RESTRICT,
    measured_at            timestamptz NOT NULL,
    age_years              double precision NOT NULL
        CONSTRAINT age_years_finite CHECK (age_years > '-Infinity' AND age_years < 'Infinity'),
    temperature_c          double precision NOT NULL
        CONSTRAINT temperature_c_finite CHECK (temperature_c > '-Infinity' AND temperature_c < 'Infinity'),
    heart_rate_bpm         double precision NOT NULL
        CONSTRAINT heart_rate_bpm_finite CHECK (heart_rate_bpm > '-Infinity' AND heart_rate_bpm < 'Infinity'),
    systolic_bp_mmhg       double precision NOT NULL
        CONSTRAINT systolic_bp_mmhg_finite CHECK (systolic_bp_mmhg > '-Infinity' AND systolic_bp_mmhg < 'Infinity'),
    diastolic_bp_mmhg      double precision NOT NULL
        CONSTRAINT diastolic_bp_mmhg_finite CHECK (diastolic_bp_mmhg > '-Infinity' AND diastolic_bp_mmhg < 'Infinity'),
    bmi_kg_m2              double precision NOT NULL
        CONSTRAINT bmi_kg_m2_finite CHECK (bmi_kg_m2 > '-Infinity' AND bmi_kg_m2 < 'Infinity'),
    hba1c_percent          double precision NOT NULL
        CONSTRAINT hba1c_percent_finite CHECK (hba1c_percent > '-Infinity' AND hba1c_percent < 'Infinity'),
    fasting_glucose_mg_dl  double precision NOT NULL
        CONSTRAINT fasting_glucose_mg_dl_finite CHECK (fasting_glucose_mg_dl > '-Infinity' AND fasting_glucose_mg_dl < 'Infinity')
);
ALTER TABLE gynfem.clinical_measurements ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE gynfem.clinical_measurements FROM PUBLIC, anon, authenticated;

CREATE INDEX clinical_measurements_patient_measured_idx
    ON gynfem.clinical_measurements (patient_id, measured_at DESC);

CREATE TRIGGER clinical_measurements_set_updated_at BEFORE UPDATE ON gynfem.clinical_measurements
    FOR EACH ROW EXECUTE FUNCTION gynfem.set_updated_at();
CREATE TRIGGER clinical_measurements_forbid_delete BEFORE DELETE ON gynfem.clinical_measurements
    FOR EACH ROW EXECUTE FUNCTION gynfem.forbid_physical_delete();
CREATE TRIGGER clinical_measurements_forbid_truncate BEFORE TRUNCATE ON gynfem.clinical_measurements
    FOR EACH STATEMENT EXECUTE FUNCTION gynfem.forbid_physical_delete();

COMMENT ON TABLE gynfem.clinical_measurements IS 'Las 8 variables clínicas en unidades clínicas peruanas (ML_SPEC.md, Sección 4).';
