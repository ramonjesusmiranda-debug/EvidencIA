import pytest
from app.phi import redact

KEEP = [
    "HR 0,74 (IC 95% 0,65–0,85)", "4744 pacientes", "paciente de 75 años", "CHA2DS2-VASc ≥2",
    "TFGe 25 ml/min/1,73 m²", "10 mg/día", "ensayo de 2019", "marzo de 2020", "Paciente con IC",
    "PMID 912345678", "dosis de 10 mg/d. Pacientes mayores", "¿iSGLT2 en IC con FEVr y FG 30-45?", "presión 120/80 mmHg", "suplementar vitamina D. En pacientes con IC", "Don no aplica aquí",
]


@pytest.mark.parametrize("t", KEEP)
def test_clinical_text_unchanged(t):
    assert redact(t) == (t, [])


@pytest.mark.parametrize("t,kind", [
    ("DNI 12345678Z del paciente", "DNI/NIE"), ("NIE X1234567L", "DNI/NIE"),
    ("escribir a juan.perez@hospital.es", "correo"),
    ("llamar al 612 345 678", "teléfono"), ("tel +34 612345678", "teléfono"), ("el 912345678", "teléfono"),
    ("nació el 03/04/1957", "fecha"), ("nació el 3 de abril de 1957", "fecha"), ("ingreso 2024-05-06", "fecha"),
    ("NHC 1234567", "nº de historia"), ("historia clínica nº 998877", "nº de historia"),
    ("paciente Juan Pérez con IC", "nombre"), ("Sra. María López Ruiz", "nombre"), ("Dña. Ana", "nombre"), ("D. Luis García", "nombre"), ("Don José Pérez Ruiz", "nombre"),
])
def test_identifiers_redacted(t, kind):
    out, kinds = redact(t)
    assert kind in kinds and out != t


def test_redacted_text_has_no_identifier():
    out, kinds = redact("paciente Juan Pérez, DNI 12345678Z, tel 612345678, nació 03/04/1957, NHC 1234567. ¿iSGLT2 en FEVr?")
    for leak in ("Juan", "12345678Z", "612345678", "1957", "1234567"):
        assert leak not in out
    assert "iSGLT2 en FEVr" in out and len(kinds) == 5
