async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const tableInputs = page.locator("table input");
  const count = await tableInputs.count();
  const filled = [];
  for (let i = 0; i < count; i++) {
    const meta = await tableInputs.nth(i).evaluate((el) => ({
      val: el.value,
      disabled: el.disabled,
      type: el.type,
      cell: (el.closest("td") && el.closest("td").innerText) || "",
    }));
    if (meta.disabled || meta.type === "checkbox" || meta.type === "radio") continue;
    if (/元/.test(meta.cell) && !meta.val && PAYLOAD.price) {
      await tableInputs.nth(i).fill(String(PAYLOAD.price));
      filled.push({ i, as: "price" });
    } else if (/件/.test(meta.cell) && !meta.val && PAYLOAD.stock) {
      await tableInputs.nth(i).fill(String(PAYLOAD.stock));
      filled.push({ i, as: "qty" });
    }
  }
  await sleep(600);
  const tableRows = await page.evaluate(() => [...document.querySelectorAll("table tr")]
    .filter((tr) => /元|件/.test(tr.innerText || ""))
    .map((tr) => [...tr.querySelectorAll("input")].map((el) => el.value).join("|")));
  return JSON.stringify({ filled, tableRows }, null, 1);
}
