#!/usr/bin/env python3
"""
Apply requested changes:
1. Delete slide 01 (01-what-is-cerno.html)
2. Re-number remaining slides (renumber data-index, rename files)
3. Update index.html (remove slide 1, TOTAL=23)
4. Update quadrant chart positioning
"""

from pathlib import Path
import re, shutil

SLIDES_DIR = Path(__file__).parent / "slides"
INDEX = Path(__file__).parent / "index.html"

# ── 1. Delete slide 01 ────────────────────────────────────────
f01 = SLIDES_DIR / "01-what-is-cerno.html"
if f01.exists():
    f01.unlink()
    print("  ✗ Deleted 01-what-is-cerno.html")
else:
    print("  - 01-what-is-cerno.html already gone")

# ── 2. Renumber slides (rename files + update data-index) ─────
# Current files: 02-market-quadrants.html ... 23-close.html
# Target files:  01-market-quadrants.html ... 22-close.html
# Also update data-index="N" -> data-index="N-1" in each file

for old_idx in range(2, 24):
    # Find file with this index prefix
    pattern = f"{old_idx:02d}-*.html"
    matches = list(SLIDES_DIR.glob(pattern))
    if not matches:
        continue
    old_path = matches[0]
    new_idx = old_idx - 1
    new_name = old_path.name.replace(f"{old_idx:02d}-", f"{new_idx:02d}-")
    new_path = SLIDES_DIR / new_name

    # Read content and update data-index
    content = old_path.read_text(encoding="utf-8")
    content = content.replace(f'data-index="{old_idx}"', f'data-index="{new_idx}"')

    # Write to new path
    new_path.write_text(content, encoding="utf-8")
    old_path.unlink()
    print(f"  ✎ {old_path.name} → {new_path.name}  (data-index: {old_idx}→{new_idx})")

# ── 3. Update the quadrant chart (now 01-market-quadrants.html) ─
chart_file = SLIDES_DIR / "01-market-quadrants.html"
if chart_file.exists():
    content = chart_file.read_text(encoding="utf-8")

    # Move Cerno: cx=390 cy=110 -> cx=290 cy=130 (same height as 绝影, left of it, left of Mixpeek)
    # Cerno circle
    content = content.replace(
        '<circle cx="390" cy="110" r="10" fill="#1a65e1" stroke="white" stroke-width="3"/>',
        '<circle cx="290" cy="130" r="10" fill="#1a65e1" stroke="white" stroke-width="3"/>'
    )
    # Cerno text
    content = content.replace(
        '<text x="390" y="92" text-anchor="middle" fill="#1a65e1" font-size="11" font-weight="700" font-family="Inter">Cerno</text>',
        '<text x="290" y="112" text-anchor="middle" fill="#1a65e1" font-size="11" font-weight="700" font-family="Inter">Cerno</text>'
    )

    # Move TwelveLabs: cx=370 -> cx=420 (more right)
    content = content.replace(
        '<circle cx="370" cy="280" r="7" fill="#5ca8e8" stroke="white" stroke-width="2"/>',
        '<circle cx="420" cy="280" r="7" fill="#5ca8e8" stroke="white" stroke-width="2"/>'
    )
    content = content.replace(
        '<text x="370" y="300" text-anchor="middle" fill="#5ca8e8" font-size="10" font-weight="600" font-family="Inter">Twelve Labs</text>',
        '<text x="420" y="300" text-anchor="middle" fill="#5ca8e8" font-size="10" font-weight="600" font-family="Inter">Twelve Labs</text>'
    )

    # Remove the "右上角是空的 →" label (no longer makes sense with Cerno moved)
    content = content.replace(
        '        <rect x="335" y="68" width="120" height="22" rx="11" fill="#1a65e1" opacity="0.12"/>\n        <text x="395" y="83" text-anchor="middle" fill="#1a65e1" font-size="9" font-weight="600" font-family="Inter">右上角是空的 →</text>',
        '        <!-- Cerno relocated to upper-center-left -->'
    )

    # Add quadrant legend BELOW the SVG (inside quadrant-chart, after SVG closes)
    # Find where SVG ends and insert the legend
    old_svg_close = '      </svg>\n    </div>'
    new_svg_close = '''      </svg>
      <!-- Quadrant legend below chart -->
      <div style="display:flex;gap:8px;margin-top:6px;justify-content:center;font-size:10px;color:#6b7280;font-family:Inter;">
        <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:#e5e7eb;border:1px solid #d1d5db;"></span> 隐私好·语义浅</span>
        <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:#e5e7eb;border:1px solid #d1d5db;"></span> 隐私好·语义深</span>
        <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:#e5e7eb;border:1px solid #d1d5db;"></span> 隐私差·语义浅</span>
        <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:#e5e7eb;border:1px solid #d1d5db;"></span> 隐私差·语义深</span>
      </div>
    </div>'''
    content = content.replace(old_svg_close, new_svg_close)

    chart_file.write_text(content, encoding="utf-8")
    print(f"  ✎ Updated 01-market-quadrants.html (Cerno moved to cx=290, TwelveLabs→cx=420, legend added)")

# ── 4. Update index.html ──────────────────────────────────────
index_content = INDEX.read_text(encoding="utf-8")

# Remove slide 1 from names array
old_names = '''    "00-cover",           // 0
    "01-what-is-cerno",   // 1
    "02-market-quadrants", // 2
    "03-core-features",   // 3
    "04-competitors",     // 4
    "05-competitor-detail", // 5
    "06-model-selection", // 6
    "07-funnel",          // 7
    "08-pipeline-overview", // 8
    "09-model-bench",     // 9
    "10-solution-vs",     // 10
    "11-product-insight", // 11
    "12-pricing-tiers",   // 12
    "13-model-summary",   // 13
    "14-dag-architecture", // 14
    "15-encoding-paths",  // 15
    "16-vs-comparison",   // 16
    "17-search-flow",     // 17
    "18-param-system",    // 18
    "19-tech-stack",      // 19
    "20-cerno-vs-others", // 20
    "21-cerno-advantage", // 21
    "22-roadmap",         // 22
    "23-close",           // 23'''

new_names = '''    "00-cover",           // 0
    "01-market-quadrants", // 1
    "02-core-features",   // 2
    "03-competitors",     // 3
    "04-competitor-detail", // 4
    "05-model-selection", // 5
    "06-funnel",          // 6
    "07-pipeline-overview", // 7
    "08-model-bench",     // 8
    "09-solution-vs",     // 9
    "10-product-insight", // 10
    "11-pricing-tiers",   // 11
    "12-model-summary",   // 12
    "13-dag-architecture", // 13
    "14-encoding-paths",  // 14
    "15-vs-comparison",   // 15
    "16-search-flow",     // 16
    "17-param-system",    // 17
    "18-tech-stack",      // 18
    "19-cerno-vs-others", // 19
    "20-cerno-advantage", // 20
    "21-roadmap",         // 21
    "22-close"            // 22'''

index_content = index_content.replace(old_names, new_names)

# Update TOTAL
index_content = index_content.replace("const TOTAL = 24;", "const TOTAL = 23;")

# Update file references in error message (just in case)
index_content = index_content.replace('const TOTAL = 24;', 'const TOTAL = 23;')

INDEX.write_text(index_content, encoding="utf-8")
print("  ✎ Updated index.html (removed slide 1, TOTAL=23)")

print("\n✅ All changes applied!")
