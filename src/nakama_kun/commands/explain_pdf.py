import logging
from pathlib import Path
from typing import Optional

import pypdf

logger = logging.getLogger(__name__)


def extract_pdf_text(pdf_path: Path) -> str:
    """
    Extract all text content from a PDF file.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Extracted text as a single string.

    Raises:
        FileNotFoundError: If the PDF file does not exist.
        ValueError: If the PDF file cannot be read or parsed.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    try:
        reader = pypdf.PdfReader(pdf_path)
        text_parts: list[str] = []
        for page_num, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text_parts.append(f"--- Page {page_num + 1} ---\n{page_text}")
            else:
                logger.warning("No text found on page %d", page_num + 1)
        if not text_parts:
            raise ValueError("No text could be extracted from the PDF.")
        return "\n\n".join(text_parts)
    except Exception as e:
        raise ValueError(f"Failed to parse PDF: {e}") from e


def parse_document_structure(text: str) -> dict:
    """
    Parse the document into sections (abstract, introduction, methods, etc.).

    Args:
        text: Full extracted text from the PDF.

    Returns:
        Dictionary with section names as keys and text content as values.
    """
    lines = text.split("\n")
    sections: dict[str, list[str]] = {}
    current_section: Optional[str] = None
    # Section indicators (case-insensitive)
    section_keywords = [
        "abstract",
        "introduction",
        "related work",
        "methodology",
        "methods",
        "experiments",
        "results",
        "discussion",
        "conclusion",
        "references",
    ]
    for line in lines:
        stripped = line.strip()
        lower_stripped = stripped.lower()
        # Check if line matches a section keyword
        matched_keyword = None
        for keyword in section_keywords:
            if lower_stripped.startswith(keyword) or lower_stripped == keyword:
                matched_keyword = keyword
                break
        if matched_keyword:
            current_section = matched_keyword
            if current_section not in sections:
                sections[current_section] = []
        else:
            if current_section is None:
                # Content before any section heading -> assume preamble/abstract catchall
                current_section = "preamble"
                if current_section not in sections:
                    sections[current_section] = []
            sections[current_section].append(stripped)
    # Join lines per section
    section_text = {k: "\n".join(v).strip() for k, v in sections.items()}
    return section_text


def identify_key_concepts(text: str) -> dict:
    """
    Identify key concepts: generation techniques, detection methods, datasets, metrics, limitations.

    Args:
        text: Full extracted text.

    Returns:
        Dictionary with concept categories and extracted snippet lists.
    """
    concepts: dict[str, list[str]] = {
        "deepfake_generation_techniques": [],
        "forensic_detection_methods": [],
        "datasets": [],
        "performance_metrics": [],
        "limitations": [],
    }
    lines = text.split("\n")
    for line in lines:
        lower = line.lower()
        # Naive keyword matching for each category
        if any(kw in lower for kw in ["gan", "generative adversarial", "autoencoder", "face swap", "deepfake generation"]):
            concepts["deepfake_generation_techniques"].append(line.strip())
        if any(kw in lower for kw in ["detection method", "forensic analysis", "classifier", "cnn", "lstm", "transformer", "artifact detection"]):
            concepts["forensic_detection_methods"].append(line.strip())
        if any(kw in lower for kw in ["dataset", "data set", "celeb-a", "ff++", "faceforensics", "dfdc"]):
            concepts["datasets"].append(line.strip())
        if any(kw in lower for kw in ["accuracy", "precision", "recall", "f1", "auc", "performance metric", "evaluation"]):
            concepts["performance_metrics"].append(line.strip())
        if any(kw in lower for kw in ["limitation", "challenge", "issue", "future work", "drawback"]):
            concepts["limitations"].append(line.strip())
    return concepts


def generate_plain_explanation(document_structure: dict, key_concepts: dict) -> str:
    """
    Compile a plain-language explanation of the document.

    Args:
        document_structure: Parsed sections from parse_document_structure.
        key_concepts: Extracted concepts from identify_key_concepts.

    Returns:
        A human-readable explanation string.
    """
    lines = []
    lines.append("# Explanation of Deepfake_Forensics.pdf")
    lines.append("")
    lines.append("## Document Summary")
    summary_parts = []
    for section_name in ["abstract", "introduction", "conclusion"]:
        content = document_structure.get(section_name, "")
        if content:
            summary_parts.append(f"### {section_name.capitalize()}\n{content[:500]}...")
    if summary_parts:
        lines.append("\n\n".join(summary_parts))
    else:
        lines.append("No clear abstract, introduction, or conclusion sections found in the extracted text.")
    lines.append("")
    lines.append("## Key Topics")
    lines.append("")
    if key_concepts["deepfake_generation_techniques"]:
        lines.append("### Deepfake Generation Techniques")
        for snippet in key_concepts["deepfake_generation_techniques"][:5]:
            lines.append(f"- {snippet}")
        lines.append("")
    if key_concepts["forensic_detection_methods"]:
        lines.append("### Forensic Detection Methods")
        for snippet in key_concepts["forensic_detection_methods"][:5]:
            lines.append(f"- {snippet}")
        lines.append("")
    if key_concepts["datasets"]:
        lines.append("### Datasets Used")
        for snippet in key_concepts["datasets"][:5]:
            lines.append(f"- {snippet}")
        lines.append("")
    if key_concepts["performance_metrics"]:
        lines.append("### Performance Metrics")
        for snippet in key_concepts["performance_metrics"][:5]:
            lines.append(f"- {snippet}")
        lines.append("")
    if key_concepts["limitations"]:
        lines.append("### Limitations / Challenges")
        for snippet in key_concepts["limitations"][:5]:
            lines.append(f"- {snippet}")
        lines.append("")
    lines.append("## Main Findings")
    # Attempt to summarize from conclusion or results sections
    findings = document_structure.get("conclusion", "") or document_structure.get("results", "") or document_structure.get("discussion", "")
    if findings:
        lines.append(findings[:1000] + ("..." if len(findings) > 1000 else ""))
    else:
        lines.append("No explicit findings section found in the extracted text.")
    lines.append("")
    lines.append("## Glossary")
    glossary = {
        "GAN": "Generative Adversarial Network - two neural networks contest with each other to generate realistic fake data.",
        "Autoencoder": "A neural network trained to reconstruct its input, often used in deepfake face swapping.",
        "CNN": "Convolutional Neural Network - a deep learning model commonly used for image analysis and deepfake detection.",
        "AUC": "Area Under the ROC Curve - a performance metric for binary classification.",
        "DFDC": "Deepfake Detection Challenge dataset - a large-scale benchmark for deepfake detection.",
    }
    for term, definition in glossary.items():
        lines.append(f"- **{term}**: {definition}")
    return "\n".join(lines)


def explain_pdf(pdf_path: str) -> str:
    """
    High-level function that reads the PDF, parses its content, and returns a plain-language explanation.

    Args:
        pdf_path: Path to the PDF file as a string.

    Returns:
        A string containing the structured explanation.
    """
    path = Path(pdf_path).expanduser().resolve()
    logger.info("Explaining PDF: %s", path)
    raw_text = extract_pdf_text(path)
    logger.debug("Extracted %d characters of text", len(raw_text))
    structure = parse_document_structure(raw_text)
    concepts = identify_key_concepts(raw_text)
    explanation = generate_plain_explanation(structure, concepts)
    return explanation