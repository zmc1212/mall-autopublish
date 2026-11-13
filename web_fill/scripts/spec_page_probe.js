async page => {
  /*HELPERS*/
  // 只读探测 SKU 规格图列的页面版本，供 spec_images_gate 选择绑定路径：
  // 老版页面有“编辑规格”抽屉（.sku-decouple-drawer），批量绑定走抽屉；
  // 潮玩盲盒使用销售属性旁的图片框及批量选择器；<n>-skuPicture 是
  // SKU 搜索主图，不能作为规格图入口或核验依据。
  return JSON.stringify(await page.evaluate(() => ({
    salePropImages: document.querySelectorAll('#sell-field-saleProp .sell-color-option-image-upload').length,
    searchMainCells: document.querySelectorAll('td[id$="-skuPicture"]').length,
    legacyCells: document.querySelectorAll('td[id$="-custom_-1"]').length,
    drawer: !!document.querySelector('.sku-decouple-drawer'),
    editSpecBtn: [...document.querySelectorAll('button')].some((el) =>
      /编辑规格|创建规格/.test((el.innerText || '').trim())),
  })));
}
