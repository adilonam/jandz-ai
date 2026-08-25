"""Generate a CV PDF from collected profile data and AI (or fallback) copy."""

from io import BytesIO
from typing import Optional, Sequence

from fpdf import FPDF

from src.services.openai_service import ManualCvContent, build_fallback_manual_cv_content


def _pdf_safe(text: str) -> str:
    """Map common Unicode to Latin-1-safe characters for core PDF fonts."""
    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "-",
        "\u00a0": " ",
        "\u2026": "...",
    }
    cleaned = "".join(replacements.get(ch, ch) for ch in (text or ""))
    return cleaned.encode("latin-1", errors="replace").decode("latin-1")


def _draw_section_heading(pdf: FPDF, title: str) -> None:
    pdf.ln(3)
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 8, _pdf_safe(title), ln=True)
    pdf.set_draw_color(180, 180, 180)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(3)
    pdf.set_x(pdf.l_margin)


def _write_body(pdf: FPDF, text: str) -> None:
    """Write wrapped body text and keep the cursor on the left margin."""
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 5.5, _pdf_safe(text))
    pdf.set_x(pdf.l_margin)


def generate_cv_pdf(
    full_name: str,
    skills: Sequence[str],
    category: str,
    content: Optional[ManualCvContent] = None,
) -> bytes:
    """Build a clean multi-section CV PDF (typically one page)."""
    cv = content or build_fallback_manual_cv_content(full_name, category, skills)
    name = _pdf_safe(" ".join((full_name or "").split()) or "Candidate")
    category_label = _pdf_safe(" ".join((category or "").split()) or "Professional")
    headline = _pdf_safe(cv.headline or category_label)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(left=16, top=14, right=16)
    pdf.add_page()

    # Header
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 10, name, ln=True, align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(70, 70, 70)
    pdf.cell(0, 7, headline, ln=True, align="C")
    if category_label.lower() not in headline.lower():
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 6, category_label, ln=True, align="C")

    pdf.set_draw_color(50, 50, 50)
    pdf.ln(2)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(4)

    # Professional summary
    if cv.summary:
        _draw_section_heading(pdf, "Professional Summary")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(40, 40, 40)
        _write_body(pdf, cv.summary)

    # Career focus / objective
    if cv.career_focus:
        _draw_section_heading(pdf, "Career Focus")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(40, 40, 40)
        _write_body(pdf, cv.career_focus)

    # Strengths
    strengths = [s.strip() for s in (cv.strengths or []) if s and s.strip()]
    if strengths:
        _draw_section_heading(pdf, "Key Strengths")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(40, 40, 40)
        for strength in strengths:
            _write_body(pdf, f"- {strength}")

    # Skills
    skill_items = [s.strip() for s in (cv.skills or list(skills) or []) if s and s.strip()]
    if not skill_items:
        skill_items = ["General professional skills"]
    _draw_section_heading(pdf, "Skills")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(40, 40, 40)
    if len(skill_items) <= 8 and all(len(s) < 40 for s in skill_items):
        _write_body(pdf, "  |  ".join(skill_items))
    else:
        for skill in skill_items:
            pdf.set_x(pdf.l_margin)
            pdf.cell(0, 5.5, _pdf_safe(f"- {skill}"), ln=True)

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()


def generate_basic_cv_pdf(
    full_name: str,
    skills: Sequence[str],
    category: str,
    content: Optional[ManualCvContent] = None,
) -> bytes:
    """Compatibility wrapper; prefer generate_cv_pdf for new call sites."""
    return generate_cv_pdf(full_name, skills, category, content=content)
