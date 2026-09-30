async page => JSON.stringify(await page.evaluate(() => {
  const cells = [...document.querySelectorAll('td[id$="-custom_-1"]')]
    .filter(el => /^\d+-custom_-1$/.test(el.id));
  return {
    total: cells.length,
    filled: cells.filter(el => !!el.querySelector('.image-item')).length,
    missing: cells.filter(el => !el.querySelector('.image-item'))
      .map(el => Number(el.id.split('-')[0]) + 1),
    sources: cells.map(el => ({ index: Number(el.id.split('-')[0]) + 1,
      src: el.querySelector('img.image-item')?.getAttribute('src') || '' })),
  };
}))
