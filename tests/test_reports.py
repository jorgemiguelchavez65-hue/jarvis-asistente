from jarvis.reports import MedicalVisit, render_report


def test_render_report_includes_sections():
    md = render_report(MedicalVisit(
        date="2026-01-01", doctor="Dra. Pérez", specialty="Cardiología",
        reason="Control", medications=["Aspirina 100mg"], follow_up="En 3 meses",
    ))
    assert "Dra. Pérez" in md and "Aspirina 100mg" in md and "## Seguimiento" in md
    assert "## Notas" not in md
