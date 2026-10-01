# -*- coding: utf-8 -*-
"""侦查第 1 步：按 sku_import.js 的定位策略点「批量导入」，截图看弹窗。"""
import sys, time
from playwright.sync_api import sync_playwright

OUT = r"G:\workspace\淘宝自动上架\.zcode\tmp\recon_step1.png"

def main():
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        page = None
        for ctx in b.contexts:
            for pg in ctx.pages:
                if "publish.htm" in pg.url:
                    page = pg
                    break
        if not page:
            print("NO_PAGE")
            return
        r = page.evaluate("""() => {
          const visible = (el) => { const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none'
              && getComputedStyle(el).visibility !== 'hidden'; };
          const label = (el) => (el.innerText || '').replace(/\\s+/g, '').trim();
          const cands = [...document.querySelectorAll('button, a, [role=button], span, div')]
            .filter(visible).filter(el => /^(批量导入|导入SKU|导入规格|Excel导入)$/.test(label(el)));
          if (!cands.length) return { found: false };
          const heading = [...document.querySelectorAll('h1, h2, h3, span, div')]
            .find(el => visible(el) && label(el) === '销售信息');
          const anchor = heading ? heading.getBoundingClientRect().top : null;
          cands.sort((a, b) => {
            const score = (el) => {
              const tag = el.tagName.toLowerCase();
              const semantic = /^(button|a)$/.test(tag) || el.getAttribute('role') === 'button' ? 0 : 1;
              const distance = anchor == null ? 0 : Math.abs(el.getBoundingClientRect().top - anchor);
              return distance + semantic * 8;
            };
            return score(a) - score(b);
          });
          const t = cands[0];
          return { found: true, tag: t.tagName, cls: String(t.className || '').slice(0, 80),
            top: t.getBoundingClientRect().top };
        }""")
        print("candidate:", r)
        if not r.get("found"):
            return
        # 用 Playwright locator 点击（真实鼠标事件，绕过合成 click 的限制）
        loc = page.locator("button, a, [role=button], span, div").filter(
            has_text="批量导入")
        # 缩小到可见且文本恰为批量导入的第一个
        target = page.get_by_text("批量导入", exact=True).first
        try:
            target.scroll_into_view_if_needed(timeout=3000)
            target.click(timeout=5000)
            print("clicked via playwright")
        except Exception as exc:
            print("playwright click failed:", str(exc)[:150])
        time.sleep(4)
        page.screenshot(path=OUT, full_page=False)
        print("screenshot saved")
        d = page.evaluate("""() => {
          const vis = [...document.querySelectorAll('.next-dialog, [role=dialog], .next-overlay-wrapper, [class*=dialog], [class*=Dialog], [class*=modal], [class*=Modal], [class*=drawer], [class*=Drawer]')]
            .filter(x => x.offsetWidth || x.offsetHeight);
          return vis.map(x => ({ cls: String(x.className).slice(0, 70),
            text: (x.innerText || '').replace(/\\s+/g, ' ').slice(0, 300) }));
        }""")
        for item in d:
            print("OVERLAY:", item["cls"], "|", item["text"][:200])

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
