"""Word OpenXML Layout Models and Geometry Calculations."""

import re
from dataclasses import dataclass
from typing import Literal

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP = {"w": W_NS}

# Standard dimensions in dxa (1 mm = 56.6929 dxa, 1 in = 1440 dxa)
PAGE_SIZES_DXA: dict[str, dict[str, tuple[int, int]]] = {
    "A4": {
        "portrait": (11906, 16838),
        "landscape": (16838, 11906),
    },
    "A3": {
        "portrait": (16838, 23811),
        "landscape": (23811, 16838),
    },
    "Letter": {
        "portrait": (12240, 15840),
        "landscape": (15840, 12240),
    },
    "Legal": {
        "portrait": (12240, 20160),
        "landscape": (20160, 12240),
    },
}

DIMENSION_REGEX = re.compile(
    r"^(?P<num>[\d\.]+)\s*(?P<unit>mm|cm|in|pt|dxa)?$", re.IGNORECASE
)


def parse_dimension_to_dxa(dim_str: str | int | float, default: int = 1440) -> int:
    """Parses a dimension string (e.g., '25mm', '1in', '2cm', '1440') into dxa."""
    if isinstance(dim_str, (int, float)):
        return int(dim_str)

    s = str(dim_str).strip().lower()
    if not s:
        return default

    m = DIMENSION_REGEX.match(s)
    if not m:
        return default

    val = float(m.group("num"))
    unit = m.group("unit") or "dxa"

    if unit == "mm":
        return int(round(val * 56.6929133858))
    elif unit == "cm":
        return int(round(val * 566.929133858))
    elif unit == "in":
        return int(round(val * 1440.0))
    elif unit == "pt":
        return int(round(val * 20.0))
    elif unit == "dxa":
        return int(round(val))
    return default


@dataclass
class SectionLayout:
    """Encapsulates page geometry, orientation, margins, and columns for a Word section."""

    orientation: Literal["portrait", "landscape"] = "portrait"
    page: str = "A4"
    columns: int = 1
    column_space_dxa: int = 720  # 0.5 inch between columns
    margin_top_dxa: int = 1440  # 1 inch default
    margin_bottom_dxa: int = 1440
    margin_left_dxa: int = 1440
    margin_right_dxa: int = 1440
    margin_header_dxa: int = 720
    margin_footer_dxa: int = 720
    custom_width_dxa: int | None = None
    custom_height_dxa: int | None = None

    @classmethod
    def from_params(cls, params: dict) -> "SectionLayout":
        """Instantiates SectionLayout from a dictionary of directive parameters."""
        orient_raw = str(params.get("orientation", "portrait")).strip().lower()
        orientation: Literal["portrait", "landscape"] = (
            "landscape" if "land" in orient_raw else "portrait"
        )
        page = str(params.get("page", "A4")).strip().upper()
        if page not in PAGE_SIZES_DXA:
            page = "A4"

        try:
            cols = int(params.get("columns", 1))
            cols = max(1, min(3, cols))
        except (ValueError, TypeError):
            cols = 1

        # Margins
        top = parse_dimension_to_dxa(params.get("margin_top", params.get("margin", 1440)))
        bottom = parse_dimension_to_dxa(params.get("margin_bottom", params.get("margin", 1440)))
        left = parse_dimension_to_dxa(params.get("margin_left", params.get("margin", 1440)))
        right = parse_dimension_to_dxa(params.get("margin_right", params.get("margin", 1440)))

        return cls(
            orientation=orientation,
            page=page,
            columns=cols,
            margin_top_dxa=top,
            margin_bottom_dxa=bottom,
            margin_left_dxa=left,
            margin_right_dxa=right,
        )

    def get_page_dimensions(self) -> tuple[int, int]:
        """Returns (width_dxa, height_dxa) for current page size and orientation."""
        if self.custom_width_dxa and self.custom_height_dxa:
            return self.custom_width_dxa, self.custom_height_dxa

        page_key = self.page if self.page in PAGE_SIZES_DXA else "A4"
        return PAGE_SIZES_DXA[page_key][self.orientation]

    def apply_to_sect_pr(
        self,
        sect_pr: etree.Element,
        section_type: str = "nextPage",
    ) -> etree.Element:
        """Applies this layout's geometry to an OpenXML <w:sectPr> element, preserving existing headers/footers."""
        w, h = self.get_page_dimensions()

        # 1. <w:type w:val="nextPage"/>
        type_el = sect_pr.find(f"{{{W_NS}}}type")
        if type_el is None:
            type_el = etree.SubElement(sect_pr, f"{{{W_NS}}}type")
        type_el.set(f"{{{W_NS}}}val", section_type)

        # 2. <w:pgSz w:w="..." w:h="..." w:orient="..."/>
        pg_sz = sect_pr.find(f"{{{W_NS}}}pgSz")
        if pg_sz is None:
            pg_sz = etree.SubElement(sect_pr, f"{{{W_NS}}}pgSz")
        pg_sz.set(f"{{{W_NS}}}w", str(w))
        pg_sz.set(f"{{{W_NS}}}h", str(h))
        pg_sz.set(f"{{{W_NS}}}orient", self.orientation)

        # 3. <w:pgMar w:top="..." w:right="..." w:bottom="..." w:left="..."/>
        pg_mar = sect_pr.find(f"{{{W_NS}}}pgMar")
        if pg_mar is None:
            pg_mar = etree.SubElement(sect_pr, f"{{{W_NS}}}pgMar")
        pg_mar.set(f"{{{W_NS}}}top", str(self.margin_top_dxa))
        pg_mar.set(f"{{{W_NS}}}right", str(self.margin_right_dxa))
        pg_mar.set(f"{{{W_NS}}}bottom", str(self.margin_bottom_dxa))
        pg_mar.set(f"{{{W_NS}}}left", str(self.margin_left_dxa))
        pg_mar.set(f"{{{W_NS}}}header", str(self.margin_header_dxa))
        pg_mar.set(f"{{{W_NS}}}footer", str(self.margin_footer_dxa))

        # 4. <w:cols w:num="..." w:space="..."/>
        cols_el = sect_pr.find(f"{{{W_NS}}}cols")
        if cols_el is None:
            cols_el = etree.SubElement(sect_pr, f"{{{W_NS}}}cols")
        cols_el.set(f"{{{W_NS}}}num", str(self.columns))
        if self.columns > 1:
            cols_el.set(f"{{{W_NS}}}space", str(self.column_space_dxa))
        elif f"{{{W_NS}}}space" in cols_el.attrib:
            del cols_el.attrib[f"{{{W_NS}}}space"]

        return sect_pr
