# -*- coding: utf-8 -*-
"""只读探测：暂停现场的 SKU 表格实际行数与渲染状态，不做任何点击/修改。"""
import json, sys
from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        page = None
        for ctx in browser.contexts:
            for pg in ctx.pages:
                if "publish.htm" in pg.url:
                    page = pg
                    break
        if page is None:
            print("NO_PUBLISH_PAGE")
            return
        info = page.evaluate("""() => {
          const allTr = [...document.querySelectorAll('table tr')];
          const passing = allTr.filter(tr => {
            const t = tr.innerText || '';
            return t.includes('元') && t.includes('件') && !t.includes('SKU分类');
          });
          const passingDetail = passing.map(tr => ({
            text: (tr.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 80),
            display: getComputedStyle(tr).display,
            rects: tr.getClientRects().length,
            h: tr.getBoundingClientRect().height,
          }));
          const emptyish = allTr.filter(tr => {
            const t = (tr.innerText || '').trim();
            return t.length > 0 && t.length < 400 && !t.includes('SKU分类') && !(t.includes('元') && t.includes('件'));
          }).map(tr => (tr.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 80));
          // 表格外层滚动容器
          let container = null;
          for (const tr of passing) {
            let el = tr.parentElement;
            while (el && el !== document.body) {
              const st = getComputedStyle(el);
              if (/(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 50) { container = el; break; }
              el = el.parentElement;
            }
            if (container) break;
          }
          const cont = container ? {
            clientHeight: container.clientHeight,
            scrollHeight: container.scrollHeight,
            scrollTop: container.scrollTop,
            cls: String(container.className || '').slice(0, 120),
          } : null;
          return {
            visibility: document.visibilityState,
            hasFocus: document.hasFocus(),
            allTrCount: allTr.length,
            passingCount: passing.length,
            passingDetail,
            emptyishCount: emptyish.length,
            emptyishSample: emptyish.slice(0, 10),
            container: cont,
            bodyHas37: /共\\s*37|37\\s*个/.test(document.body.innerText || ''),
          };
        }""")
        print(json.dumps(info, ensure_ascii=False, indent=1)[:4000])

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
