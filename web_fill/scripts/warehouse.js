async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (!/\/sell\/v2\/publish\.htm/i.test(page.url())) {
    return JSON.stringify({ skipped: true, href: page.url() });
  }
  const state = await selectWarehouseRadio();
  return JSON.stringify(state);
}
