async page => {
  const P = /*PAYLOAD*/;
  return JSON.stringify(await page.evaluate(({item_id, baseline}) => {
    if (new URL(location.href).searchParams.get('itemId') !== item_id)
      throw new Error('PAUSE:验证商品ID不一致');
    if (/请拖动.*滑块|安全验证|请完成验证|扫码登录/.test(document.body.innerText))
      throw new Error('PAUSE:人工验证阻断');
    const source = baseline || [];
    if (new Set(source.map(r => r.name)).size !== source.length ||
        new Set(source.map(r => r.sku_id)).size !== source.length)
      throw new Error('PAUSE:SKU名称或ID重复');
    const rows = [...document.querySelectorAll('td[id$="-custom_-1"]')].map(cell => {
      const name = cell.querySelector('textarea[data-real="true"]')?.value;
      const match = source.filter(r => r.name === name);
      if (match.length !== 1) throw new Error('PAUSE:销售规格与SKU不唯一对应');
      const prefix = cell.id.split('-')[0];
      const get = key => document.getElementById(prefix + '-' + key);
      const value = key => {
        const input = get(key)?.querySelector('input');
        if (!input) throw new Error('PAUSE:后台字段未加载:' + key);
        return input.value;
      };
      if (!cell.querySelector('img.image-item') && !cell.querySelector('.image-empty'))
        throw new Error('PAUSE:无法确定销售规格图状态');
      const attributes = {};
      for (const td of cell.closest('tr').querySelectorAll('td[id*="-skuParam_"]'))
        attributes[td.id.substring(prefix.length + 1)] = td.innerText.trim() || td.querySelector('input')?.value || '';
      return {
        sku_id: match[0].sku_id, name,
        search_image: get('skuPicture')?.querySelector('img')?.src || '',
        spec_image: cell.querySelector('img.image-item')?.src || '',
        price: value('skuPrice'), stock: value('skuStock'),
        merchant_code: value('skuOuterId'), attributes,
        search_title: match[0].search_title,
        search_title_source: 'SKU管理中心；列表占位符保持原值',
      };
    });
    if (!rows.length || rows.length !== source.length || new Set(rows.map(r => r.sku_id)).size !== rows.length)
      throw new Error('PAUSE:SKU数量或绑定不一致');
    return {item_id, url: location.href, captured_at: new Date().toISOString(), rows,
      notice: '只读当前状态；不是导入前后验收结论'};
  }, P));
}
