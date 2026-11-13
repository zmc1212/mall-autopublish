
async page => {
  /*PAYLOAD*/
  /*HELPERS*/
  return await page.evaluate(() => {
    const rows = [...document.querySelectorAll("table tr")].filter((tr) => /元|件/.test(tr.innerText||""));
    return {
      count: rows.length,
      first8: rows.slice(0, 8).map((tr) => (tr.innerText||"").replace(/\s+/g," ").trim().slice(0, 110)),
      url: location.href.slice(0, 90),
    };
  });
}
