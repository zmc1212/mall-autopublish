async page => {
  const PAYLOAD = /*PAYLOAD*/;
  return page.evaluate(value => {
    const checkpoint = { ...value, href: location.href, updatedAt: new Date().toISOString() };
    sessionStorage.setItem('qianniu-fill-checkpoint', JSON.stringify(checkpoint));
    return checkpoint;
  }, PAYLOAD);
}
