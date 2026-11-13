async page => {
  /*PAYLOAD*/
  /*HELPERS*/
  const sample = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const dialogs = [...document.querySelectorAll(".next-dialog, [role=dialog], .next-overlay-wrapper")].filter(visible)
      .map((el) => (el.innerText||"").replace(/\s+/g," ").trim().slice(0,600));
    const fileInputs = [...document.querySelectorAll("input[type=file]")].map((el) => ({accept: String(el.accept||""), visible: visible(el)}));
    const tableRows = [...document.querySelectorAll("table tr")].filter((tr)=>/元|件/.test(tr.innerText||"")).length;
    return { dialogs, fileInputs, tableRows };
  });
  return JSON.stringify(sample);
}
