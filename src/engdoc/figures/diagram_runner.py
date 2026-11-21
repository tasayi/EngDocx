"""Diagram Runner and Vector Mermaid SVG Generation Engine."""

import hashlib
import html
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FlowchartNode:
    id: str
    label: str
    shape: str = "rect"  # rect, rounded, stadium, cylinder, circle, diamond, flag
    x: float = 0.0
    y: float = 0.0
    width: float = 140.0
    height: float = 46.0
    rank: int = 0


@dataclass
class FlowchartEdge:
    src: str
    dst: str
    label: str = ""
    style: str = "solid"  # solid, dotted, thick
    has_arrow: bool = True


class DiagramRunner:
    """Renders Mermaid diagrams into vector SVG assets with hybrid CLI and built-in fallbacks."""

    CACHE_DIR = Path("assets/figures/.cache/diagrams")

    @classmethod
    def get_cache_dir(cls, workspace_dir: Path | None = None) -> Path:
        """Returns the cache directory, creating it if needed."""
        base = workspace_dir if workspace_dir else Path.cwd()
        cache_path = (base / cls.CACHE_DIR).resolve()
        cache_path.mkdir(parents=True, exist_ok=True)
        return cache_path

    @classmethod
    def render_mermaid_to_svg(
        cls,
        code: str,
        output_path: Path | None = None,
        workspace_dir: Path | None = None,
    ) -> Path:
        """Renders Mermaid diagram code into an SVG file, using cache and fallbacks."""
        clean_code = code.strip()
        code_hash = hashlib.sha256(clean_code.encode("utf-8")).hexdigest()

        if output_path is None:
            cache_dir = cls.get_cache_dir(workspace_dir)
            target = cache_dir / f"diagram_{code_hash[:16]}.svg"
        else:
            target = output_path.resolve()
            target.parent.mkdir(parents=True, exist_ok=True)

        if target.is_file() and target.stat().st_size > 0:
            return target

        # 1. Try external mmdc CLI if available
        mmdc_bin = shutil.which("mmdc")
        if mmdc_bin:
            try:
                with tempfile.NamedTemporaryFile("w", suffix=".mmd", encoding="utf-8", delete=False) as tmp_in:
                    tmp_in.write(clean_code)
                    tmp_in_path = Path(tmp_in.name)
                try:
                    proc = subprocess.run(
                        [mmdc_bin, "-i", str(tmp_in_path), "-o", str(target)],
                        capture_output=True,
                        text=True,
                        timeout=5.0,
                        check=False,
                    )
                    if proc.returncode == 0 and target.is_file() and target.stat().st_size > 0:
                        return target
                finally:
                    if tmp_in_path.exists():
                        tmp_in_path.unlink()
            except Exception:
                pass

        # 2. Built-in vector SVG generator fallback
        svg_content = render_builtin_mermaid_svg(clean_code)
        target.write_text(svg_content, encoding="utf-8")
        return target


def render_builtin_mermaid_svg(code: str) -> str:
    """Generates clean, standards-compliant vector SVG for Mermaid diagrams."""
    lines = [line.strip() for line in code.strip().splitlines() if line.strip()]
    header_line = ""
    for line in lines:
        if line.startswith("%%") or ":" in line and any(k in line.lower() for k in ("caption", "width", "height", "alias")):
            continue
        header_line = line.lower()
        break

    if "sequencediagram" in header_line:
        return _render_sequence_diagram(lines)
    elif any(k in header_line for k in ("flowchart", "graph")):
        return _render_flowchart_diagram(lines)
    else:
        return _render_generic_diagram(lines)


def _parse_node_string(token: str) -> tuple[str, str, str]:
    """Parses a node token into (node_id, label, shape)."""
    token = token.strip()
    # Cylinder: [(Database)]
    m = re.match(r"^([A-Za-z0-9_\-]+)\[\((.*?)\)\]$", token)
    if m:
        return (m.group(1), m.group(2).strip(), "cylinder")
    # Stadium: ([Stadium])
    m = re.match(r"^([A-Za-z0-9_\-]+)\(\[(.*?)\]\)$", token)
    if m:
        return (m.group(1), m.group(2).strip(), "stadium")
    # Circle: ((Circle))
    m = re.match(r"^([A-Za-z0-9_\-]+)\(\((.*?)\)\)$", token)
    if m:
        return (m.group(1), m.group(2).strip(), "circle")
    # Rounded: (Rounded)
    m = re.match(r"^([A-Za-z0-9_\-]+)\((.*?)\)$", token)
    if m:
        return (m.group(1), m.group(2).strip(), "rounded")
    # Diamond: {Decision}
    m = re.match(r"^([A-Za-z0-9_\-]+)\{(.*?)\}$", token)
    if m:
        return (m.group(1), m.group(2).strip(), "diamond")
    # Flag: >Flag]
    m = re.match(r"^([A-Za-z0-9_\-]+)\>(.*?)\]$", token)
    if m:
        return (m.group(1), m.group(2).strip(), "flag")
    # Rect: [Text]
    m = re.match(r"^([A-Za-z0-9_\-]+)\[(.*?)\]$", token)
    if m:
        return (m.group(1), m.group(2).strip(), "rect")
    # Plain ID
    clean_id = re.sub(r"[^A-Za-z0-9_\-]", "", token)
    return (clean_id or token, token, "rect")


def _render_flowchart_diagram(lines: list[str]) -> str:
    """Renders a flowchart or graph diagram as vector SVG."""
    direction = "TD"
    nodes: dict[str, FlowchartNode] = {}
    edges: list[FlowchartEdge] = []

    # Connection regex: A[...] -->|label| B[...] or A --> B
    edge_pattern = re.compile(
        r"^(?P<src>.+?)\s*(?P<arrow>==>|-->|--|-.->|-.-)\s*(?:\|(?P<lbl1>[^|]+)\|)?(?:--\s*(?P<lbl2>[^\-]+?)\s*-->)?\s*(?P<dst>.+)$"
    )

    for line in lines:
        if line.startswith("%%") or line.startswith("caption:") or line.startswith("alias:"):
            continue
        line_lower = line.lower()
        if line_lower.startswith("flowchart") or line_lower.startswith("graph"):
            parts = line.split()
            if len(parts) > 1 and parts[1].upper() in ("TD", "TB", "LR", "RL", "BT"):
                direction = parts[1].upper()
            continue

        # Check edge
        m = edge_pattern.match(line)
        if m:
            src_raw = m.group("src").strip()
            dst_raw = m.group("dst").strip()
            arrow = m.group("arrow")
            label = (m.group("lbl1") or m.group("lbl2") or "").strip()

            s_id, s_lbl, s_shape = _parse_node_string(src_raw)
            d_id, d_lbl, d_shape = _parse_node_string(dst_raw)

            if s_id not in nodes:
                nodes[s_id] = FlowchartNode(id=s_id, label=s_lbl, shape=s_shape)
            elif s_lbl != s_id:
                nodes[s_id].label = s_lbl
                nodes[s_id].shape = s_shape

            if d_id not in nodes:
                nodes[d_id] = FlowchartNode(id=d_id, label=d_lbl, shape=d_shape)
            elif d_lbl != d_id:
                nodes[d_id].label = d_lbl
                nodes[d_id].shape = d_shape

            style = "thick" if "==" in arrow else ("dotted" if "-." in arrow else "solid")
            has_arrow = ">" in arrow
            edges.append(FlowchartEdge(src=s_id, dst=d_id, label=label, style=style, has_arrow=has_arrow))
        else:
            # Standalone node declaration
            if any(c in line for c in ("[", "(", "{", ">")):
                n_id, n_lbl, n_shape = _parse_node_string(line)
                if n_id:
                    nodes[n_id] = FlowchartNode(id=n_id, label=n_lbl, shape=n_shape)

    if not nodes:
        nodes["N1"] = FlowchartNode(id="N1", label="Diagram")

    # Layered topological layout (Ranks)
    in_degree: dict[str, int] = {k: 0 for k in nodes}
    adj: dict[str, list[str]] = {k: [] for k in nodes}
    for e in edges:
        if e.src in adj and e.dst in in_degree:
            adj[e.src].append(e.dst)
            in_degree[e.dst] += 1

    # Assign ranks using longest path from sources
    ranks: dict[str, int] = {k: 0 for k in nodes}
    queue = [k for k, deg in in_degree.items() if deg == 0]
    if not queue:
        queue = list(nodes.keys())

    visited_count = 0
    max_steps = len(nodes) * 4
    while queue and visited_count < max_steps:
        curr = queue.pop(0)
        visited_count += 1
        curr_rank = ranks[curr]
        for neighbor in adj.get(curr, []):
            if ranks[neighbor] < curr_rank + 1:
                ranks[neighbor] = curr_rank + 1
            queue.append(neighbor)

    for n_id, n in nodes.items():
        n.rank = ranks.get(n_id, 0)

    # Group by rank
    rank_groups: dict[int, list[FlowchartNode]] = {}
    for n in nodes.values():
        rank_groups.setdefault(n.rank, []).append(n)

    # Calculate coordinates
    is_horizontal = direction in ("LR", "RL")
    node_margin_x = 45.0
    node_margin_y = 65.0

    for n in nodes.values():
        txt_len = max(len(n.label), len(n.id))
        n.width = max(130.0, txt_len * 8.5 + 32.0)
        n.height = 46.0 if n.shape != "diamond" else 58.0
        if n.shape == "circle":
            n.width = max(n.width, 56.0)
            n.height = n.width

    if is_horizontal:
        # X based on rank, Y based on position in rank
        curr_x = 40.0
        sorted_ranks = sorted(rank_groups.keys(), reverse=(direction == "RL"))
        max_height = 0.0
        for r in sorted_ranks:
            group = rank_groups[r]
            max_col_w = max(n.width for n in group)
            total_col_h = sum(n.height for n in group) + (len(group) - 1) * node_margin_y
            max_height = max(max_height, total_col_h)
            curr_y = 40.0
            for n in group:
                n.x = curr_x + (max_col_w - n.width) / 2.0
                n.y = curr_y
                curr_y += n.height + node_margin_y
            curr_x += max_col_w + 70.0
        total_w = curr_x + 20.0
        total_h = max_height + 80.0
    else:
        # Y based on rank, X based on position in rank
        curr_y = 40.0
        sorted_ranks = sorted(rank_groups.keys(), reverse=(direction == "BT"))
        max_width = 0.0
        for r in sorted_ranks:
            group = rank_groups[r]
            max_row_h = max(n.height for n in group)
            total_row_w = sum(n.width for n in group) + (len(group) - 1) * node_margin_x
            max_width = max(max_width, total_row_w)
            curr_x = 40.0
            for n in group:
                n.y = curr_y + (max_row_h - n.height) / 2.0
                n.x = curr_x
                curr_x += n.width + node_margin_x
            curr_y += max_row_h + 70.0
        total_w = max_width + 80.0
        total_h = curr_y + 20.0

    # SVG assembly
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w:.1f} {total_h:.1f}" width="{total_w:.1f}" height="{total_h:.1f}">',
        '  <defs>',
        '    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
        '      <path d="M 0 1 L 10 5 L 0 9 z" fill="#64748B"/>',
        '    </marker>',
        '    <marker id="arrow-thick" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">',
        '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#4F46E5"/>',
        '    </marker>',
        '    <filter id="shadow" x="-5%" y="-5%" width="110%" height="115%" filterUnits="userSpaceOnUse">',
        '      <feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#0F172A" flood-opacity="0.08"/>',
        '    </filter>',
        '  </defs>',
        '  <rect width="100%" height="100%" fill="#FFFFFF" rx="8"/>',
    ]

    # Draw edges
    for e in edges:
        s_node = nodes.get(e.src)
        d_node = nodes.get(e.dst)
        if not s_node or not d_node:
            continue

        if is_horizontal:
            start_x = s_node.x + s_node.width
            start_y = s_node.y + s_node.height / 2.0
            end_x = d_node.x
            end_y = d_node.y + d_node.height / 2.0
            mid_x = (start_x + end_x) / 2.0
            path_d = f"M {start_x:.1f} {start_y:.1f} C {mid_x:.1f} {start_y:.1f}, {mid_x:.1f} {end_y:.1f}, {end_x:.1f} {end_y:.1f}"
        else:
            start_x = s_node.x + s_node.width / 2.0
            start_y = s_node.y + s_node.height
            end_x = d_node.x + d_node.width / 2.0
            end_y = d_node.y
            mid_y = (start_y + end_y) / 2.0
            path_d = f"M {start_x:.1f} {start_y:.1f} C {start_x:.1f} {mid_y:.1f}, {end_x:.1f} {mid_y:.1f}, {end_x:.1f} {end_y:.1f}"

        stroke_color = "#4F46E5" if e.style == "thick" else "#64748B"
        stroke_width = "2.5" if e.style == "thick" else "1.6"
        dash_attr = ' stroke-dasharray="4,4"' if e.style == "dotted" else ""
        marker_id = "arrow-thick" if e.style == "thick" else "arrow"
        marker_attr = f' marker-end="url(#{marker_id})"' if e.has_arrow else ""

        svg_parts.append(
            f'  <path d="{path_d}" fill="none" stroke="{stroke_color}" stroke-width="{stroke_width}"{dash_attr}{marker_attr}/>'
        )

        if e.label:
            lbl_x = (start_x + end_x) / 2.0
            lbl_y = (start_y + end_y) / 2.0
            lbl_esc = html.escape(e.label)
            lbl_w = max(40.0, len(e.label) * 7.5 + 14.0)
            svg_parts.append(
                f'  <rect x="{lbl_x - lbl_w/2.0:.1f}" y="{lbl_y - 11.0:.1f}" width="{lbl_w:.1f}" height="22" rx="4" fill="#F8FAFC" stroke="#E2E8F0" stroke-width="1"/>'
            )
            svg_parts.append(
                f'  <text x="{lbl_x:.1f}" y="{lbl_y + 4.0:.1f}" font-family="system-ui, -apple-system, sans-serif" font-size="11" fill="#475569" text-anchor="middle">{lbl_esc}</text>'
            )

    # Draw nodes
    for n in nodes.values():
        lbl_esc = html.escape(n.label)
        cx = n.x + n.width / 2.0
        cy = n.y + n.height / 2.0

        if n.shape == "diamond":
            pts = f"{cx:.1f},{n.y:.1f} {n.x + n.width:.1f},{cy:.1f} {cx:.1f},{n.y + n.height:.1f} {n.x:.1f},{cy:.1f}"
            svg_parts.append(
                f'  <polygon points="{pts}" fill="#FFFBEB" stroke="#F59E0B" stroke-width="1.8" filter="url(#shadow)"/>'
            )
            text_color = "#92400E"
        elif n.shape == "cylinder":
            svg_parts.append(
                f'  <rect x="{n.x:.1f}" y="{n.y + 6.0:.1f}" width="{n.width:.1f}" height="{n.height - 12.0:.1f}" fill="#F5F3FF" stroke="#8B5CF6" stroke-width="1.8" filter="url(#shadow)"/>'
            )
            svg_parts.append(
                f'  <ellipse cx="{cx:.1f}" cy="{n.y + 6.0:.1f}" rx="{n.width/2.0:.1f}" ry="7" fill="#EDE9FE" stroke="#8B5CF6" stroke-width="1.8"/>'
            )
            svg_parts.append(
                f'  <ellipse cx="{cx:.1f}" cy="{n.y + n.height - 6.0:.1f}" rx="{n.width/2.0:.1f}" ry="7" fill="#F5F3FF" stroke="#8B5CF6" stroke-width="1.8"/>'
            )
            text_color = "#5B21B6"
        elif n.shape == "stadium" or n.shape == "rounded":
            rx = n.height / 2.0 if n.shape == "stadium" else 8.0
            svg_parts.append(
                f'  <rect x="{n.x:.1f}" y="{n.y:.1f}" width="{n.width:.1f}" height="{n.height:.1f}" rx="{rx:.1f}" ry="{rx:.1f}" fill="#ECFDF5" stroke="#10B981" stroke-width="1.8" filter="url(#shadow)"/>'
            )
            text_color = "#065F46"
        elif n.shape == "circle":
            r = min(n.width, n.height) / 2.0
            svg_parts.append(
                f'  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="#EFF6FF" stroke="#3B82F6" stroke-width="1.8" filter="url(#shadow)"/>'
            )
            text_color = "#1E40AF"
        else:
            # Standard Card/Rect
            svg_parts.append(
                f'  <rect x="{n.x:.1f}" y="{n.y:.1f}" width="{n.width:.1f}" height="{n.height:.1f}" rx="6" ry="6" fill="#F8FAFC" stroke="#3B82F6" stroke-width="1.8" filter="url(#shadow)"/>'
            )
            text_color = "#0F172A"

        svg_parts.append(
            f'  <text x="{cx:.1f}" y="{cy + 4.5:.1f}" font-family="system-ui, -apple-system, sans-serif" font-size="12.5" font-weight="600" fill="{text_color}" text-anchor="middle">{lbl_esc}</text>'
        )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def _render_sequence_diagram(lines: list[str]) -> str:
    """Renders a Sequence diagram as vector SVG."""
    participants: list[tuple[str, str]] = []  # (id, label)
    messages: list[tuple[str, str, str, str]] = []  # (src, dst, text, style)

    for line in lines:
        if line.startswith("%%") or line.lower().startswith("sequencediagram"):
            continue
        m_part = re.match(r"^(?:participant|actor)\s+([A-Za-z0-9_\-]+)(?:\s+as\s+(.+))?$", line, re.IGNORECASE)
        if m_part:
            pid = m_part.group(1).strip()
            plabel = (m_part.group(2) or pid).strip().strip('"\'')
            if not any(p[0] == pid for p in participants):
                participants.append((pid, plabel))
            continue

        m_msg = re.match(
            r"^([A-Za-z0-9_\-]+)\s*(-->>|->>|-->|->)\s*([A-Za-z0-9_\-]+)\s*:\s*(.*)$",
            line,
        )
        if m_msg:
            src = m_msg.group(1).strip()
            arrow = m_msg.group(2).strip()
            dst = m_msg.group(3).strip()
            txt = m_msg.group(4).strip()
            style = "dotted" if "--" in arrow else "solid"

            for node in (src, dst):
                if not any(p[0] == node for p in participants):
                    participants.append((node, node))

            messages.append((src, dst, txt, style))

    if not participants:
        participants = [("A", "Client"), ("B", "Server")]

    box_w = 120.0
    box_h = 36.0
    col_spacing = 160.0
    total_w = max(400.0, 60.0 + len(participants) * col_spacing)
    msg_spacing = 48.0
    total_h = max(250.0, 90.0 + len(messages) * msg_spacing + 70.0)

    part_x: dict[str, float] = {}
    for i, (pid, _) in enumerate(participants):
        part_x[pid] = 60.0 + i * col_spacing + box_w / 2.0

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w:.1f} {total_h:.1f}" width="{total_w:.1f}" height="{total_h:.1f}">',
        '  <defs>',
        '    <marker id="seq-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
        '      <path d="M 0 1 L 10 5 L 0 9 z" fill="#3B82F6"/>',
        '    </marker>',
        '  </defs>',
        '  <rect width="100%" height="100%" fill="#FFFFFF" rx="8"/>',
    ]

    # Lifelines
    for pid, _ in participants:
        cx = part_x[pid]
        svg_parts.append(
            f'  <line x1="{cx:.1f}" y1="50" x2="{cx:.1f}" y2="{total_h - 40:.1f}" stroke="#CBD5E1" stroke-width="1.5" stroke-dasharray="4,4"/>'
        )

    # Participant boxes top
    for pid, plabel in participants:
        cx = part_x[pid]
        bx = cx - box_w / 2.0
        lbl_esc = html.escape(plabel)
        svg_parts.append(
            f'  <rect x="{bx:.1f}" y="20" width="{box_w}" height="{box_h}" rx="6" fill="#EFF6FF" stroke="#3B82F6" stroke-width="1.8"/>'
        )
        svg_parts.append(
            f'  <text x="{cx:.1f}" y="43" font-family="system-ui, sans-serif" font-size="12" font-weight="600" fill="#1E40AF" text-anchor="middle">{lbl_esc}</text>'
        )

    # Messages
    curr_y = 90.0
    for src, dst, txt, style in messages:
        sx = part_x.get(src, 60.0)
        dx = part_x.get(dst, 220.0)
        dash = ' stroke-dasharray="4,4"' if style == "dotted" else ""
        txt_esc = html.escape(txt)
        mid_x = (sx + dx) / 2.0

        svg_parts.append(
            f'  <line x1="{sx:.1f}" y1="{curr_y:.1f}" x2="{dx:.1f}" y2="{curr_y:.1f}" stroke="#3B82F6" stroke-width="1.8"{dash} marker-end="url(#seq-arrow)"/>'
        )
        svg_parts.append(
            f'  <text x="{mid_x:.1f}" y="{curr_y - 6.0:.1f}" font-family="system-ui, sans-serif" font-size="11.5" fill="#334155" text-anchor="middle">{txt_esc}</text>'
        )
        curr_y += msg_spacing

    # Participant boxes bottom
    by = total_h - 46.0
    for pid, plabel in participants:
        cx = part_x[pid]
        bx = cx - box_w / 2.0
        lbl_esc = html.escape(plabel)
        svg_parts.append(
            f'  <rect x="{bx:.1f}" y="{by:.1f}" width="{box_w}" height="{box_h}" rx="6" fill="#EFF6FF" stroke="#3B82F6" stroke-width="1.8"/>'
        )
        svg_parts.append(
            f'  <text x="{cx:.1f}" y="{by + 23.0:.1f}" font-family="system-ui, sans-serif" font-size="12" font-weight="600" fill="#1E40AF" text-anchor="middle">{lbl_esc}</text>'
        )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def _render_generic_diagram(lines: list[str]) -> str:
    """Fallback card renderer for miscellaneous diagram formats."""
    title = lines[0] if lines else "Diagram"
    items = lines[1:7] if len(lines) > 1 else ["Component A", "Component B"]

    w = 420.0
    h = 80.0 + len(items) * 36.0
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.1f} {h:.1f}" width="{w:.1f}" height="{h:.1f}">',
        '  <rect width="100%" height="100%" fill="#FFFFFF" rx="8" stroke="#E2E8F0" stroke-width="1.5"/>',
        f'  <rect x="15" y="15" width="{w - 30.0:.1f}" height="32" rx="4" fill="#F1F5F9"/>',
        f'  <text x="25" y="36" font-family="system-ui, sans-serif" font-size="13" font-weight="600" fill="#334155">{html.escape(title)}</text>',
    ]

    curr_y = 65.0
    for item in items:
        svg_parts.append(
            f'  <rect x="25" y="{curr_y:.1f}" width="{w - 50.0:.1f}" height="28" rx="4" fill="#F8FAFC" stroke="#CBD5E1" stroke-width="1"/>'
        )
        svg_parts.append(
            f'  <text x="35" y="{curr_y + 19.0:.1f}" font-family="system-ui, sans-serif" font-size="12" fill="#1E293B">{html.escape(item)}</text>'
        )
        curr_y += 34.0

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)
