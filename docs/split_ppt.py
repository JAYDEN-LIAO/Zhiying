#!/usr/bin/env python3
"""
Split cerno-ppt.html into: index.html (shell) + slides/ (individual files)
"""

import re, os, shutil
from pathlib import Path

SRC = Path(__file__).parent / "cerno-ppt.html"
SLIDES_DIR = Path(__file__).parent / "slides"
INDEX_OUT = Path(__file__).parent / "index.html"
BACKUP = Path(__file__).parent / "cerno-ppt.html.bak"

# ── 1. Read source ──────────────────────────────────────────────
html = SRC.read_text(encoding="utf-8")

# ── 2. Extract slides using balanced div matching ───────────────
# Find all <div class="slide ..." data-index="N">
slide_pattern = re.compile(
    r'(<div class="slide[^>]*data-index="(\d+)"[^>]*>.*?</div>\s*(?=</div>\s*</div>))',
    re.DOTALL,
)

# Better approach: manually split by slide boundaries using the known structure
# Each slide: <div class="slide ..." data-index="N"> ... </div>
# We need to match balanced divs

def extract_slides(html):
    """Extract each slide div with balanced nesting."""
    slides = []
    # Find all <div class="slide ... data-index="N"> positions
    pattern = re.compile(r'(<div class="slide[^"]*"[^>]*data-index="(\d+)"[^>]*>)')
    pos = 0
    slide_starts = []
    for m in pattern.finditer(html):
        slide_starts.append((int(m.group(2)), m.start()))

    # Sort by index
    slide_starts.sort(key=lambda x: x[0])

    for i, (idx, start) in enumerate(slide_starts):
        if i + 1 < len(slide_starts):
            end = slide_starts[i + 1][1]
        else:
            # Last slide: find the closing </div> of #presentation
            # After the last slide div, there should be </div> for #presentation
            after_slide = html[start:]
            # Find the closing </div> that closes the slide itself
            # The slide is: <div class="slide"> ...content... </div>
            # We match balanced divs

            # Simple approach: find the end by the pattern of slide end
            slide_end = len(html)
            # Look for </div>\n\n</div> which closes the slide then #presentation
            for m in re.finditer(r'</div>\s*\n\s*</div>', html[start:]):
                # The first </div> closes the slide's content div or slide div
                slide_end_candidate = start + m.end()
                if slide_end_candidate < len(html) - 50:
                    slide_end = slide_end_candidate
            end = slide_end

        slide_html = html[start:end].strip()
        slides.append((idx, slide_html))

    return slides

# Actually, let me use a much simpler approach based on the known line numbers.
# I know exactly where each slide starts at the line level.
# Let me just split by lines.

lines = html.split('\n')

# Line numbers (1-indexed from grep results)
slide_lines = [
    (0, 372), (1, 388), (2, 414), (3, 477), (4, 505),
    (5, 538), (6, 571), (7, 601), (8, 643), (9, 672),
    (10, 700), (11, 734), (12, 764), (13, 799), (14, 844),
    (15, 906), (16, 941), (17, 982), (18, 1027), (19, 1066),
    (20, 1109), (21, 1151), (22, 1182), (23, 1219),
]

# Convert to 0-indexed
slide_lines = [(idx, ln-1) for idx, ln in slide_lines]

# Determine end line for each slide
slides_text = []
for i, (idx, start_ln) in enumerate(slide_lines):
    if i + 1 < len(slide_lines):
        end_ln = slide_lines[i + 1][1]
    else:
        # For slide 23, find the </div> that closes #presentation
        # After line 1241 (0-indexed: 1240) we have </div> for #presentation
        # But we need to find where the slide itself ends
        # Look from line 1219 until we find the </div> that closes slide 23
        # The slide closing is followed by </div> (close #presentation) then <script>
        end_ln = len(lines)
        # Find the right closing - we need the </div> that closes the slide div
        # From the file structure, after slide 23, there's </div> (close slide-content)
        # then </div> (close slide), then </div> (close #presentation)
        # So we go to </div>\n\n</div>\n\n<script>
        for ln in range(start_ln, len(lines)):
            stripped = lines[ln].strip()
            # The slide ends 3 </div> before <script>
            if stripped == '<script>':
                end_ln = ln - 2  # Go back past </div> (#presentation) and </div> (slide)
                break

    slide_content = '\n'.join(lines[start_ln:end_ln])
    slides_text.append((idx, slide_content))

# ── 3. Extract CSS (lines 1-357) and JS (before </body>) ─────
# CSS: from <style> to </style>
style_match = re.search(r'<style>(.*?)</style>', html, re.DOTALL)
css_content = style_match.group(1) if style_match else ""

# JS: from <script> to </script>
script_match = re.search(r'(<script>.*?</script>)', html, re.DOTALL)
js_script = script_match.group(1) if script_match else ""

# ── 4. Write individual slide files ──────────────────────────
SLIDES_DIR.mkdir(exist_ok=True)
# Remove old slides
for f in SLIDES_DIR.glob("*.html"):
    f.unlink()

slide_names = [
    "00-cover",           # 0
    "01-what-is-cerno",   # 1
    "02-market-quadrants", # 2
    "03-core-features",   # 3
    "04-competitors",     # 4
    "05-competitor-detail", # 5
    "06-model-selection", # 6
    "07-funnel",          # 7
    "08-pipeline-overview", # 8
    "09-model-bench",     # 9
    "10-solution-vs",     # 10
    "11-product-insight", # 11
    "12-pricing-tiers",   # 12
    "13-model-summary",   # 13
    "14-dag-architecture", # 14
    "15-encoding-paths",  # 15
    "16-vs-comparison",   # 16
    "17-search-flow",     # 17
    "18-param-system",    # 18
    "19-tech-stack",      # 19
    "20-cerno-vs-others", # 20
    "21-cerno-advantage", # 21
    "22-roadmap",         # 22
    "23-close",           # 23
]

for idx, content in slides_text:
    name = slide_names[idx] if idx < len(slide_names) else f"slide-{idx:02d}"
    filepath = SLIDES_DIR / f"{name}.html"
    filepath.write_text(content.strip() + '\n', encoding="utf-8")
    print(f"  ✓ {filepath.name}  ({len(content)} chars)")

# ── 5. Generate new index.html ───────────────────────────────
# This will have CSS + container + JS that fetches slides
index_html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cerno · 视频语义分析引擎</title>
<style>
''' + css_content + '''
/* ── Loading indicator ── */
#loader {
  position: fixed; inset: 0;
  display: flex; align-items: center; justify-content: center;
  background: #1a1d23; color: #9ca3af;
  font-family: 'Inter', -apple-system, sans-serif;
  font-size: 14px; z-index: 999;
  transition: opacity 0.4s ease;
}
#loader.hidden { opacity: 0; pointer-events: none; }
#loader .spinner { width: 24px; height: 24px; border: 3px solid #374151; border-top-color: #1a65e1; border-radius: 50%; animation: spin 0.8s linear infinite; margin-right: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>

<div id="loader"><div class="spinner"></div><span>加载演示文稿…</span></div>

<div id="presentation"></div>

<script>
const TOTAL = 24;

async function loadSlides() {
  const names = [
    "00-cover",           // 0
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
    "23-close",           // 23
  ];

  const container = document.getElementById('presentation');
  const fragments = await Promise.all(
    names.map(name =>
      fetch('slides/' + name + '.html')
        .then(r => { if (!r.ok) throw new Error(name + ' not found'); return r.text(); })
        .catch(() => '<div class="slide" data-index="' + names.indexOf(name) + '"><div class="slide-content"><div class="section-label">ERROR</div><h2>Slide ' + names.indexOf(name) + ' failed to load</h2><p class="body-text">Missing file: slides/' + name + '.html</p></div></div>')
    )
  );

  container.innerHTML = fragments.join('\\n');
  showSlide(0);

  // Hide loader
  document.getElementById('loader').classList.add('hidden');
}

let current = 0;

function showSlide(idx) {
  document.querySelectorAll('.slide').forEach((el, i) => {
    el.classList.toggle('active', i === idx);
  });
}

document.addEventListener('keydown', function(e) {
  if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'ArrowDown') {
    e.preventDefault();
    if (current < TOTAL - 1) { current++; showSlide(current); }
  } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
    e.preventDefault();
    if (current > 0) { current--; showSlide(current); }
  }
});

// Click to advance
document.addEventListener('click', function(e) {
  if (current < TOTAL - 1) { current++; showSlide(current); }
});

loadSlides();
</script>
</body>
</html>'''

INDEX_OUT.write_text(index_html, encoding="utf-8")
print(f"\n  ✓ index.html 生成完毕 ({len(index_html)} chars)")
print(f"\n🎉 拆分完成！打开 index.html 即可像原来一样演示。")
