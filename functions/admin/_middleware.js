// The admin panel only opens on estonian-pool-rating.pages.dev, where Cloudflare Access asks for the login.
// the login (Cloudflare Access) is set up for the pages.dev address:
// send every visit there to the protected address instead.
export async function onRequest({ request, next }) {
  const url = new URL(request.url);
  if (!url.hostname.endsWith('estonian-pool-rating.pages.dev')) {
    return Response.redirect('https://estonian-pool-rating.pages.dev' + url.pathname + url.search, 302);
  }
  return next();
}
