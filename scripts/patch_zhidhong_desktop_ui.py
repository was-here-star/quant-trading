#!/usr/bin/env python3
"""Apply desktop-only 指定红 UI patches to ~/Desktop/指定红看板策略/*.html"""
from __future__ import annotations

import re
from pathlib import Path

desk = Path.home() / "Desktop" / "指定红看板策略"
files = sorted(desk.glob("指定红策略-*.html"))
v2 = Path.home() / "Desktop" / "指定红策略-1年-月频V2.html"
if v2.exists():
    files.append(v2)

kpi_css_new = """  .kpi {
    position: relative;
    background: var(--card);
    border: 0;
    border-radius: var(--radius);
    padding: 18px 18px 16px;
    display: flex; flex-direction: column; justify-content: flex-start;
    min-height: 0;
    overflow: hidden;
    box-shadow: none;
  }"""

layout_css = """  /* 指定红桌面：KPI 外层无灰底；左右分栏后右侧气温/配置均分左侧总高 */
  #kpi-card-wrap {
    align-self: start;
    background: transparent !important;
    padding: 0 !important;
    border: 0 !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    width: 100%;
    height: auto !important;
    min-height: 0 !important;
  }
  #kpi-card-wrap > .kpi-row {
    margin-bottom: 0;
    width: 100%;
    gap: 12px;
  }
  #kpi-card-wrap > .action { display: none !important; }

  .main-split {
    grid-column: span 12;
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: 14px;
    align-items: stretch;
    min-width: 0;
  }
  .main-split .split-left {
    display: flex;
    flex-direction: column;
    gap: 14px;
    min-width: 0;
  }
  .main-split .split-right {
    display: grid;
    grid-template-rows: 1fr 1fr;
    gap: 14px;
    min-width: 0;
    min-height: 0;
  }
  .main-split .split-left > .card,
  .main-split .split-right > .card {
    width: 100%;
    min-width: 0;
  }
  .main-split #kpi-card-wrap { flex: 0 0 auto; }
  .main-split #hold-card-wrap { flex: 1 1 auto; }
  .main-split #temp-card-wrap,
  .main-split #alloc-card-wrap {
    height: auto;
    min-height: 0;
    align-self: stretch;
    display: flex;
    flex-direction: column;
  }
  .main-split #temp-card-wrap .temp-wrap,
  .main-split #alloc-card-wrap .alloc-wrap {
    flex: 1 1 auto;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }
  @media (max-width: 1100px) {
    .main-split { grid-template-columns: 1fr; }
    .main-split .split-right { grid-template-rows: auto auto; }
  }"""

neon_css = """  /* 近一年月收益柱：零轴上下发散，红涨绿跌；霓虹胶囊柱（仅指定红桌面看板） */
  .month-bars {
    display: grid;
    grid-template-columns: repeat(12, 1fr);
    gap: 14px;
    align-items: stretch;
    height: 360px;
    min-height: 360px;
    padding: 12px 8px 4px;
    margin-bottom: 4px;
    overflow: visible;
  }
  .month-bars .bar-cell {
    display: grid;
    grid-template-rows: minmax(0, 1fr) auto minmax(0, 1fr) auto;
    align-items: stretch;
    justify-items: center;
    min-width: 0;
    height: 100%;
    position: relative;
  }
  .month-bars .bar-slot {
    width: 100%;
    max-width: 56px;
    height: 100%;
    min-height: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  .month-bars .bar-slot.pos { justify-content: flex-end; }
  .month-bars .bar-slot.neg { justify-content: flex-start; }
  .month-bars .bar {
    position: relative;
    width: 44px;
    max-width: 90%;
    flex-shrink: 0;
    border-radius: 999px;
  }
  .month-bars .bar.up {
    background: linear-gradient(
      180deg,
      rgba(255,186,192,.98) 0%,
      rgba(255,90,102,.92) 42%,
      rgba(244,63,94,.62) 78%,
      rgba(244,63,94,.22) 100%
    );
    box-shadow:
      0 0 10px rgba(255,90,102,.75),
      0 0 24px rgba(255,82,93,.55),
      0 0 48px rgba(255,82,93,.32),
      inset 0 1px 0 rgba(255,255,255,.35);
  }
  .month-bars .bar.down {
    background: linear-gradient(
      180deg,
      rgba(52,211,153,.22) 0%,
      rgba(34,197,94,.62) 22%,
      rgba(34,197,94,.92) 58%,
      rgba(134,239,172,.98) 100%
    );
    box-shadow:
      0 0 10px rgba(52,211,153,.7),
      0 0 24px rgba(34,197,94,.5),
      0 0 48px rgba(34,197,94,.28),
      inset 0 1px 0 rgba(255,255,255,.3);
  }
  .month-bars .bar.flat {
    border-radius: 999px;
    background: rgba(255,255,255,.16);
    box-shadow: none;
    height: 4px !important;
    flex: none !important;
  }
  .month-bars .zero-line {
    width: 100%; height: 1px;
    background: rgba(255,255,255,.08);
    margin: 0;
    flex-shrink: 0;
  }
  .month-bars .bar-val {
    font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums;
    white-space: nowrap; line-height: 1.2;
    flex-shrink: 0;
  }
  .month-bars .bar-slot.pos .bar-val { margin-bottom: 8px; }
  .month-bars .bar-slot.neg .bar-val { margin-top: 8px; }
  .month-bars .bar-val.up { color: #ff6b75; }
  .month-bars .bar-val.down { color: #3dd68c; }
  .month-bars .bar-val.flat { color: #71717a; }
  .month-bars .bar-lab {
    font-size: 10px; color: #71717a; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; max-width: 100%;
    margin-top: 10px;
  }
  .month-bars-legend {
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
    font-size: 12px; color: var(--muted); margin: 0 4px 8px;
  }
  .month-bars-legend .leg {
    display: inline-flex; align-items: center; gap: 6px;
  }
  .month-bars-legend .swatch {
    width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0;
  }
  .month-bars-legend .swatch.up { background: #ff525d; box-shadow: 0 0 10px rgba(255,82,93,.45); }
  .month-bars-legend .swatch.down { background: #22c55e; box-shadow: 0 0 10px rgba(34,197,94,.4); }"""

js_new = r"""  // 排版：年化整行 → 左(KPI+持仓) / 右(气温+配置，均分左侧总高)
  if (annWrap) {
    annWrap.classList.remove("col-8", "col-7", "col-6", "col-5", "col-4");
    annWrap.classList.add("col-12");
  }
  (function ensureMainSplit() {
    if (isHorizon) {
      const old = document.getElementById("main-split");
      if (old) {
        const parent = old.parentNode;
        while (old.firstChild) {
          const col = old.firstChild;
          while (col.firstChild) parent.insertBefore(col.firstChild, old);
          old.removeChild(col);
        }
        old.remove();
      }
      return;
    }
    if (!kpiWrap || !holdWrap || !tempWrap) return;
    let shell = document.getElementById("main-split");
    if (!shell) {
      shell = document.createElement("div");
      shell.id = "main-split";
      shell.className = "main-split";
      const anchor = annWrap || kpiWrap;
      if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(shell, anchor.nextSibling);
    }
    let left = shell.querySelector(".split-left");
    let right = shell.querySelector(".split-right");
    if (!left) {
      left = document.createElement("div");
      left.className = "split-left";
      shell.appendChild(left);
    }
    if (!right) {
      right = document.createElement("div");
      right.className = "split-right";
      shell.appendChild(right);
    }
    [kpiWrap, holdWrap, tempWrap, allocWrap].forEach((el) => {
      if (!el) return;
      el.classList.remove("col-12", "col-8", "col-7", "col-6", "col-5", "col-4", "col-3");
    });
    if (kpiWrap.parentNode !== left) left.appendChild(kpiWrap);
    if (holdWrap.parentNode !== left) left.appendChild(holdWrap);
    if (tempWrap.parentNode !== right) right.appendChild(tempWrap);
    if (allocWrap && allocWrap.style.display !== "none" && allocWrap.parentNode !== right) {
      right.appendChild(allocWrap);
    }
    if (!allocWrap || allocWrap.style.display === "none") {
      right.style.gridTemplateRows = "1fr";
    } else {
      right.style.gridTemplateRows = "1fr 1fr";
    }
  })();"""


def patch_one(p: Path) -> bool:
    text = p.read_text(encoding="utf-8")
    orig = text

    text = text.replace(
        "          <th>仓位占比</th>\n          <th>最新价</th>\n          <th>日涨跌</th>\n          <th>策略备注</th>\n",
        "          <th>仓位占比</th>\n          <th>日涨跌</th>\n",
    )
    if "const note =" in text:
        text = re.sub(
            r"  const note =[\s\S]*?(?=  document\.getElementById\(\"hold-body\"\))",
            "",
            text,
            count=1,
        )
    text = text.replace(
        "      <td>${pct(h.weight, 2)}</td>\n      <td>${money(h.price)}</td>\n      <td class=\"${chgCls}\">${chgTxt}</td>\n      <td>${note}</td>\n",
        "      <td>${pct(h.weight, 2)}</td>\n      <td class=\"${chgCls}\">${chgTxt}</td>\n",
    )

    text, _ = re.subn(r"  \.kpi \{[\s\S]*?^  \}", kpi_css_new, text, count=1, flags=re.M)

    if "main-split" not in text:
        text2, n = re.subn(
            r"  /\* 示意图排版：[\s\S]*?#kpi-card-wrap > \.kpi-row \{[^}]*\}",
            layout_css,
            text,
            count=1,
        )
        if n == 0:
            text2, n = re.subn(
                r"  #kpi-card-wrap \{[^}]*\}\n  #kpi-card-wrap > \.kpi-row \{[^}]*\}",
                layout_css,
                text,
                count=1,
            )
        text = text2
        if "main-split" not in text:
            text = text.replace(
                "  #temp-card-wrap { align-self: stretch; }",
                layout_css + "\n  #temp-card-wrap { align-self: stretch; }",
            )

    text2, n = re.subn(
        r"  /\* 近一年月收益柱[\s\S]*?\.month-bars-legend \.swatch\.down \{[^}]+\}",
        neon_css,
        text,
        count=1,
    )
    if n == 0:
        text2, n = re.subn(
            r"  /\* 近一年月收益柱[\s\S]*?\.month-bars \.bar-lab \{[^}]+\}",
            neon_css,
            text,
            count=1,
        )
    text = text2

    text = re.sub(r"const maxBarPx = \d+;", "const maxBarPx = 150;", text)
    text = re.sub(
        r"return Math\.max\(\d+, Math\.round\(soft \* maxBarPx\)\);",
        "return Math.max(36, Math.round(soft * maxBarPx));",
        text,
    )

    if "ensureMainSplit" not in text:
        for pat in [
            r"  // 排版：[\s\S]*?if \(tempWrap\) \{\n    tempWrap\.classList\.remove\([\s\S]*?kpiWrap\.after\(tempWrap\);\n    \}\n  \}",
            r"  // 示意图固定排版：[\s\S]*?if \(tempWrap\) \{\n    tempWrap\.classList\.remove\([\s\S]*?kpiWrap\.after\(tempWrap\);\n    \}\n  \}",
        ]:
            text2, n = re.subn(pat, js_new, text, count=1)
            if n:
                text = text2
                break
        if "ensureMainSplit" not in text:
            marker = '  if (holdWrap) holdWrap.style.display = isHorizon ? "none" : "";'
            if marker in text:
                text = text.replace(marker, marker + "\n" + js_new)

    if text != orig:
        p.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> int:
    changed = []
    for p in files:
        if not p.exists():
            continue
        if patch_one(p):
            changed.append(p.name)
    print(f"patched {len(changed)}/{len(files)}")
    for c in changed:
        print(" -", c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
