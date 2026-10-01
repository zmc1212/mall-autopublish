# -*- coding: utf-8 -*-
"""现场侦查：重开 SKU 批量导入，观察识别结果弹窗内部结构。
绝不点击「在当前规格后添加 / 确认创建 / 确认导入」等会改动数据的按钮；
结束前取消/关闭弹窗，恢复现场。
"""
import json, sys, time
from playwright.sync_api import sync_playwright

TEMPLATE = r"C:\Users\Administrator\AppData\Roaming\千牛自动上架\results\sku-import\SKU导入_1f2759fff8b64325a550a66aa21b6bd2.xls"

def table_rows(page):
    return page.evaluate("""() => [...document.querySelectorAll('table tr')]
        .filter(tr => { const t = tr.innerText || '';
          return t.includes('元') && t.includes('件') && !t.includes('SKU分类'); }).length""")

def find_dialog(page):
    return page.locator(
        ".next-dialog:visible, [role=dialog]:visible, .next-overlay-wrapper:visible"
    ).filter(has_text="识别").last

def snap_dialog(page, tag):
    info = page.evaluate("""() => {
      const dialogs = [...document.querySelectorAll('.next-dialog, [role=dialog], .next-overlay-wrapper')]
        .filter(d => d.offsetWidth || d.offsetHeight);
      const out = [];
      for (const d of dialogs) {
        const text = (d.innerText || '').replace(/\\s+/g, ' ').trim();
        if (!/识别|导入|规格/.test(text)) continue;
        const scrollables = [...d.querySelectorAll('*')]
          .filter(el => { const st = getComputedStyle(el);
            return /(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 20; })
          .map(el => ({ cls: String(el.className || '').slice(0, 80),
            clientHeight: el.clientHeight, scrollHeight: el.scrollHeight,
            items: el.querySelectorAll('li, [class*=item], [class*=Item]').length,
            checked: el.querySelectorAll('input:checked').length,
            checkboxes: el.querySelectorAll('input[type=checkbox]').length }));
        const btns = [...d.querySelectorAll('button')].map(b => (b.innerText || '').trim()).filter(Boolean);
        out.push({ text: text.slice(0, 500), btns, scrollables });
      }
      return out;
    }""")
    print(f"--- {tag} ---")
    print(json.dumps(info, ensure_ascii=False, indent=1)[:3500])
    return info

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
        print("rows before:", table_rows(page))

        # 1. 点击批量导入入口（与 sku_import.js open 阶段同一策略）
        clicked = page.evaluate("""() => {
          const visible = (el) => { const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0; };
          const label = (el) => (el.innerText || '').replace(/\\s+/g, '').trim();
          const cands = [...document.querySelectorAll('button, a, [role=button], span, div')]
            .filter(visible).filter(el => /^(批量导入|导入SKU|导入规格|Excel导入)$/.test(label(el)));
          if (!cands.length) return 'NO_ENTRY';
          cands[0].scrollIntoView({ block: 'center' });
          cands[0].click();
          return 'CLICKED:' + label(cands[0]);
        }""")
        print("entry:", clicked)
        time.sleep(1.2)

        # 2. 设置文件：优先 xls input，否则点「选择文件」并拦截原生文件选择器
        set_ok = False
        try:
            inputs = page.locator("input[type=file]")
            if inputs.count():
                inputs.first.set_input_files(TEMPLATE, timeout=8000)
                set_ok = True
                print("file set: via input")
        except Exception as exc:
            print("via input failed:", str(exc)[:120])
        if not set_ok:
            try:
                chooser_btn = page.locator(
                    ".next-dialog:visible, [role=dialog]:visible"
                ).filter(has_text="批量导入").last.get_by_role(
                    "button", name="选择文件"
                ).first
                with page.expect_file_chooser(timeout=10000) as fc_info:
                    chooser_btn.click(timeout=5000)
                fc_info.value.set_files(TEMPLATE)
                set_ok = True
                print("file set: via file chooser")
            except Exception as exc:
                print("via chooser failed:", str(exc)[:200])
        if not set_ok:
            return
        time.sleep(2.0)
        snap_dialog(page, "after upload")

        # 3. 点「确认识别」
        rec = page.get_by_text("确认识别", exact=True).last
        if rec.count() and rec.is_visible():
            rec.click(timeout=5000)
            print("recognition clicked")
        else:
            print("no 确认识别 button")
        time.sleep(3.0)
        snap_dialog(page, "after recognition")

        # 4. 滚动测试：把弹窗内每个可滚动容器逐级滚到底，观察条目数是否增长
        for round_no in range(1, 5):
            grown = page.evaluate("""() => {
              const dialogs = [...document.querySelectorAll('.next-dialog, [role=dialog], .next-overlay-wrapper')]
                .filter(d => d.offsetWidth || d.offsetHeight);
              const report = [];
              for (const d of dialogs) {
                const text = (d.innerText || '');
                if (!/识别|导入/.test(text)) continue;
                const lists = [...d.querySelectorAll('*')].filter(el => {
                  const st = getComputedStyle(el);
                  return /(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 20;
                });
                for (const el of lists) {
                  const before = el.querySelectorAll('li, [class*=item], [class*=Item]').length;
                  el.scrollTop = el.scrollHeight;
                  report.push({ cls: String(el.className || '').slice(0, 50), before,
                    scrollTop: el.scrollTop, scrollHeight: el.scrollHeight });
                }
              }
              return report;
            }""")
            print(f"scroll round {round_no}:", json.dumps(grown, ensure_ascii=False))
            time.sleep(1.0)
        snap_dialog(page, "after scrolling")

        # 5. 关闭弹窗：优先取消/关闭按钮，否则 ESC
        closed = page.evaluate("""() => {
          const dialogs = [...document.querySelectorAll('.next-dialog, [role=dialog], .next-overlay-wrapper')]
            .filter(d => (d.offsetWidth || d.offsetHeight));
          for (const d of dialogs) {
            if (!/识别|导入/.test(d.innerText || '')) continue;
            const btn = [...d.querySelectorAll('button')].find(b =>
              /^(取消|关闭|知道了|我知道了)$/.test((b.innerText || '').trim()));
            if (btn) { btn.click(); return 'CANCEL_CLICKED'; }
          }
          return 'NO_CANCEL';
        }""")
        print("close:", closed)
        if closed == "NO_CANCEL":
            page.keyboard.press("Escape")
            time.sleep(0.6)
            page.keyboard.press("Escape")
        time.sleep(1.0)
        page.evaluate("""() => {
          const closers = document.querySelectorAll('.next-dialog-close, [class*=close]');
          closers.forEach(c => { if (c.offsetWidth) c.click(); });
        }""")
        time.sleep(1.0)
        print("rows after:", table_rows(page))
        left = page.evaluate("""() => [...document.querySelectorAll('.next-dialog, [role=dialog], .next-overlay-wrapper')]
            .filter(d => (d.offsetWidth || d.offsetHeight) && /识别|导入/.test(d.innerText || '')).length""")
        print("dialogs left:", left)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
