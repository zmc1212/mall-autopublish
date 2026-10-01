# -*- coding: utf-8 -*-
"""侦查第 2 步（窗口已还原）：完整走到识别结果弹窗并做结构/滚动侦查。
不点击「在当前规格后添加」。结束时取消弹窗。
"""
import json, sys, time
from playwright.sync_api import sync_playwright

TEMPLATE = r"C:\Users\Administrator\AppData\Roaming\千牛自动上架\results\sku-import\SKU导入_1f2759fff8b64325a550a66aa21b6bd2.xls"
SHOT = r"G:\workspace\淘宝自动上架\.zcode\tmp\recon2_{}.png"

def rows(page):
    return page.evaluate("""() => [...document.querySelectorAll('table tr')]
        .filter(tr => { const t = tr.innerText || '';
          return t.includes('元') && t.includes('件') && !t.includes('SKU分类'); }).length""")

def dump_dialogs(page, tag):
    d = page.evaluate("""() => {
      const vis = [...document.querySelectorAll('.next-dialog, [role=dialog], .next-overlay-wrapper')]
        .filter(x => x.offsetWidth || x.offsetHeight);
      return vis.map(x => {
        const scrollables = [...x.querySelectorAll('*')]
          .filter(el => { const st = getComputedStyle(el);
            return /(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 20; })
          .map(el => ({ cls: String(el.className || '').slice(0, 60),
            clientH: el.clientHeight, scrollH: el.scrollHeight,
            items: el.querySelectorAll('li, [class*=item], [class*=Item]').length }));
        return { cls: String(x.className).slice(0, 60),
          text: (x.innerText || '').replace(/\\s+/g, ' ').slice(0, 600),
          btns: [...x.querySelectorAll('button')].map(b => (b.innerText || '').trim()).filter(Boolean).slice(0, 15),
          fileInputs: x.querySelectorAll('input[type=file]').length,
          checkboxes: x.querySelectorAll('input[type=checkbox]').length,
          checked: x.querySelectorAll('input[type=checkbox]:checked').length,
          scrollables };
      });
    }""")
    print(f"===== {tag} | table rows = {rows(page)} =====")
    print(json.dumps(d, ensure_ascii=False, indent=1)[:4000])
    return d

def shot(page, tag):
    try:
        page.screenshot(path=SHOT.format(tag), full_page=False)
        print("shot:", SHOT.format(tag))
    except Exception as exc:
        print("shot failed:", str(exc)[:100])

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

        # 1. 点批量导入（合成 click，与线上脚本一致）
        r = page.evaluate("""() => {
          const visible = (el) => { const rc = el.getBoundingClientRect();
            return rc.width > 0 && rc.height > 0; };
          const label = (el) => (el.innerText || '').replace(/\\s+/g, '').trim();
          const cands = [...document.querySelectorAll('button, a, [role=button], span, div')]
            .filter(visible).filter(el => /^(批量导入)$/.test(label(el)))
            .filter(el => !/down-load-template/.test(String(el.className)));
          if (!cands.length) return 'NO_ENTRY';
          const heading = [...document.querySelectorAll('h1, h2, h3, span, div')]
            .find(el => visible(el) && label(el) === '销售信息');
          const anchor = heading ? heading.getBoundingClientRect().top : 0;
          cands.sort((a, b) => Math.abs(a.getBoundingClientRect().top - anchor)
            - Math.abs(b.getBoundingClientRect().top - anchor));
          cands[0].scrollIntoView({ block: 'center' });
          cands[0].click();
          return 'CLICKED:' + cands[0].tagName + ':' + String(cands[0].className).slice(0, 60);
        }""")
        print("entry:", r)
        time.sleep(2.5)
        dump_dialogs(page, "after entry click")
        shot(page, "1_entry")

        # 2. 传文件：file input 或 选择文件 + 拦截 chooser
        set_ok = False
        inputs = page.locator("input[type=file]")
        cnt = inputs.count()
        print("file inputs:", cnt)
        for i in range(cnt):
            acc = inputs.nth(i).evaluate("el => String(el.accept || '')")
            print(f"  input {i} accept={acc[:50]}")
        if cnt:
            try:
                inputs.first.set_input_files(TEMPLATE, timeout=8000)
                set_ok = True
                print("file set via input")
            except Exception as exc:
                print("input set failed:", str(exc)[:120])
        if not set_ok:
            try:
                btn = page.locator(".next-dialog:visible, [role=dialog]:visible, .next-overlay-wrapper:visible") \
                    .filter(has_text="批量导入").last \
                    .get_by_text("选择文件", exact=False).first
                with page.expect_file_chooser(timeout=10000) as fc:
                    btn.click(force=True, timeout=4000)
                fc.value.set_files(TEMPLATE)
                set_ok = True
                print("file set via chooser")
            except Exception as exc:
                print("chooser failed:", str(exc)[:200])
        if not set_ok:
            print("STOP: cannot set file")
            return
        time.sleep(3)
        dump_dialogs(page, "after file set")
        shot(page, "2_file")

        # 3. 确认识别
        clicked_rec = page.evaluate("""() => {
          const btn = [...document.querySelectorAll('.next-dialog button, [role=dialog] button, .next-overlay-wrapper button')]
            .filter(b => b.offsetWidth || b.offsetHeight)
            .find(b => (b.innerText || '').trim() === '确认识别');
          if (!btn) return 'NO_BTN';
          btn.click();
          return 'CLICKED';
        }""")
        print("recognize:", clicked_rec)
        if clicked_rec != "CLICKED":
            return
        # 等「已成功识别」出现
        for i in range(30):
            await_flag = page.evaluate("""() => /已成功识别|识别结果|在当前规格后添加/
                .test((document.querySelector('.next-dialog, [role=dialog], .next-overlay-wrapper') || document.body).innerText || '')""")
            if await_flag:
                break
            time.sleep(1)
        time.sleep(2)
        dump_dialogs(page, "after recognition")
        shot(page, "3_recognized")

        # 4. 滚动侦查
        for rd in range(1, 4):
            rep = page.evaluate("""() => {
              const vis = [...document.querySelectorAll('.next-dialog, [role=dialog], .next-overlay-wrapper')]
                .filter(x => x.offsetWidth || x.offsetHeight);
              const out = [];
              for (const x of vis) {
                if (!/识别|导入/.test(x.innerText || '')) continue;
                const lists = [...x.querySelectorAll('*')].filter(el => {
                  const st = getComputedStyle(el);
                  return /(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 20;
                });
                for (const el of lists) {
                  const sel = 'li, [class*=item], [class*=Item]';
                  const before = el.querySelectorAll(sel).length;
                  el.scrollTop = el.scrollHeight;
                  out.push({ cls: String(el.className || '').slice(0, 50), before, after: el.querySelectorAll(sel).length });
                }
              }
              return out;
            }""")
            print(f"scroll round {rd}:", json.dumps(rep, ensure_ascii=False))
            time.sleep(1.2)
        dump_dialogs(page, "after scrolls")
        shot(page, "4_scrolled")

        # 5. 不点添加；取消/关闭弹窗
        closed = page.evaluate("""() => {
          const vis = [...document.querySelectorAll('.next-dialog, [role=dialog], .next-overlay-wrapper')]
            .filter(x => x.offsetWidth || x.offsetHeight);
          for (const x of vis) {
            if (!/识别|导入/.test(x.innerText || '')) continue;
            const btn = [...x.querySelectorAll('button')].find(b =>
              /^(取消|关闭)$/.test((b.innerText || '').trim()));
            if (btn) { btn.click(); return 'CANCEL'; }
            const x2 = x.querySelector('.next-dialog-close, [class*=close]');
            if (x2) { x2.click(); return 'CLOSE_X'; }
          }
          return 'NONE';
        }""")
        print("close:", closed)
        if closed == "NONE":
            page.keyboard.press("Escape")
        time.sleep(1.5)
        print("final rows:", rows(page))
        shot(page, "5_closed")

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
