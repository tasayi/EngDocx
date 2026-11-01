"""Unit tests for Pandoc compilation runner."""

from pathlib import Path

import docx
import pytest

from engdoc.compiler.runner import PandocRunner
from engdoc.publishing.service import PublishingService

DOCX_MARKDOWN_SAMPLE = """# 1. Receiver Subsystem

This document describes the RF receiver subsystem.

## 1.1 Specifications

* Frequency: 2.4 GHz - 2.5 GHz
* Noise Figure: < 2.5 dB
* Gain: 45 dB

| Parameter | Value | Unit |
|---|---|---|
| IF Frequency | 140 | MHz |
| Bandwidth | 20 | MHz |
| Impedance | 50 | Ohm |

## 1.2 Mathematical Formulation

The overall system noise factor is calculated as:

$$
F_{\\text{total}} = F_1 + \\frac{F_2 - 1}{G_1} + \\frac{F_3 - 1}{G_1 G_2}
$$

Inline sensitivity formula: $P_{\\text{sens}} = k_B T B F$.
"""

@pytest.mark.asyncio
async def test_pandoc_runner_compile_to_docx(tmp_path: Path):
    output_docx = tmp_path / "compiled_sample.docx"
    res = await PandocRunner.compile_to_docx(
        markdown_text=DOCX_MARKDOWN_SAMPLE,
        output_path=output_docx,
    )

    assert res.success is True
    assert output_docx.is_file()
    assert output_docx.stat().st_size > 0
    assert res.returncode == 0

    # Validate output DOCX structure
    stats = PublishingService.validate_generated_docx(output_docx)
    assert stats["headings"] >= 2  # "1. Receiver Subsystem" and "1.1 Specifications"
    assert stats["tables"] >= 1    # The parameter table
    assert stats["equations"] >= 1 # The OMML math block/inline

    # Open with python-docx and inspect text content
    doc = docx.Document(output_docx)
    all_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Receiver Subsystem" in all_text
    assert "Frequency: 2.4 GHz" in all_text
