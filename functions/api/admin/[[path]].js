// Admin API for ee.poolrating.eu/admin (Cloudflare Pages Function).
// Cloudflare Access lets only Aleksandrs through; this code checks the Access token again before every action.
// Settings (Cloudflare Pages > Settings > Variables and Secrets):
//   GITHUB_TOKEN  secret, fine-grained token for fscign/estonian-pool-rating (Contents + Actions read/write)
//   ACCESS_TEAM   Zero Trust team domain, for example horsuns.cloudflareaccess.com
//   ACCESS_AUD    Application Audience (AUD) tag of the Access application
//   ADMIN_EMAIL   the one e-mail address that may use the panel
//   GITHUB_BRANCH branch to read and write (main for the live site, admin-panel for the preview)
const REPO = 'fscign/estonian-pool-rating';
const FILES = ['overrides.json', 'site/hof.json', 'site/ml.json', 'site/texts.json'];
const WORKFLOW = 'daily.yml';

const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });

const b64url = s => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(s.length / 4) * 4, '=')), c => c.charCodeAt(0));
let CERTS = null, CERTS_AT = 0;
async function checkAccess(request, env) {
  const jwt = request.headers.get('Cf-Access-Jwt-Assertion');
  if (!jwt || !env.ACCESS_TEAM || !env.ACCESS_AUD || !env.ADMIN_EMAIL) return null;
  const [h, p, sig] = jwt.split('.');
  if (!sig) return null;
  const head = JSON.parse(new TextDecoder().decode(b64url(h)));
  const body = JSON.parse(new TextDecoder().decode(b64url(p)));
  if (!CERTS || Date.now() - CERTS_AT > 3600e3) {
    CERTS = (await (await fetch(`https://${env.ACCESS_TEAM}/cdn-cgi/access/certs`)).json()).keys; CERTS_AT = Date.now();
  }
  const jwk = CERTS.find(k => k.kid === head.kid);
  if (!jwk) return null;
  const key = await crypto.subtle.importKey('jwk', jwk, { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
  const ok = await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, b64url(sig), new TextEncoder().encode(`${h}.${p}`));
  const aud = Array.isArray(body.aud) ? body.aud : [body.aud];
  if (!ok || !aud.includes(env.ACCESS_AUD) || body.exp * 1000 < Date.now()) return null;
  if ((body.email || '').toLowerCase() !== env.ADMIN_EMAIL.toLowerCase()) return null;
  return body.email;
}

function gh(env, path, init = {}) {
  return fetch(`https://api.github.com/repos/${REPO}/${path}`, { ...init, headers: {
    authorization: `Bearer ${env.GITHUB_TOKEN}`, accept: 'application/vnd.github+json', 'user-agent': 'ee-pool-rating-admin',
    'x-github-api-version': '2022-11-28', ...(init.body ? { 'content-type': 'application/json' } : {}) } });
}
const toB64 = s => { const b = new TextEncoder().encode(s); let t = ''; for (let i = 0; i < b.length; i += 0x8000) t += String.fromCharCode(...b.subarray(i, i + 0x8000)); return btoa(t); };
const fromB64 = s => new TextDecoder().decode(Uint8Array.from(atob(s.replace(/\n/g, '')), c => c.charCodeAt(0)));

async function readFile(env, path) {
  const r = await gh(env, `contents/${path}?ref=${env.GITHUB_BRANCH || 'main'}`);
  if (!r.ok) throw new Error(`GitHub read ${path}: ${r.status}`);
  const j = await r.json();
  let content = j.content ? fromB64(j.content) : null;
  if (content === null) {   // files over 1 MB come without content
    const raw = await gh(env, `git/blobs/${j.sha}`); content = fromB64((await raw.json()).content);
  }
  return { path, sha: j.sha, content };
}

export async function onRequest({ request, env, params }) {
  const who = await checkAccess(request, env).catch(() => null);
  if (!who) return json({ error: 'Not signed in as the admin' }, 403);
  if (!env.GITHUB_TOKEN) return json({ error: 'GITHUB_TOKEN is not set in Cloudflare Pages' }, 500);
  const route = (params.path || []).join('/');
  const branch = env.GITHUB_BRANCH || 'main';
  try {
    if (route === 'whoami') return json({ email: who, branch });
    if (route === 'files' && request.method === 'GET')
      return json({ branch, files: await Promise.all(FILES.map(f => readFile(env, f))) });
    if (route === 'save' && request.method === 'POST') {
      const { files, message } = await request.json();
      const done = [];
      for (const f of files) {
        if (!FILES.includes(f.path)) return json({ error: `Not allowed: ${f.path}` }, 400);
        JSON.parse(f.content);   // never commit broken JSON
        const r = await gh(env, `contents/${f.path}`, { method: 'PUT', body: JSON.stringify({
          message: `${message || 'Admin panel change'} (${f.path})\n\nSaved in the admin panel by ${who}`,
          content: toB64(f.content), sha: f.sha, branch }) });
        const j = await r.json();
        if (!r.ok) return json({ error: r.status === 409 ? `${f.path} changed on GitHub since you opened the panel. Reload and redo the change.` : (j.message || 'GitHub error'), done }, r.status);
        done.push({ path: f.path, sha: j.content.sha, commit: j.commit.html_url });
      }
      return json({ ok: true, done });
    }
    if (route === 'apply' && request.method === 'POST') {
      // one update at a time: refuse while a run is queued or running, or was started in the last 2 minutes
      const runs = (await (await gh(env, `actions/workflows/${WORKFLOW}/runs?per_page=3&branch=${branch}`)).json()).workflow_runs || [];
      if (runs.some(x => x.status !== 'completed' || Date.now() - Date.parse(x.created_at) < 120e3))
        return json({ error: 'A rating update is already running. Wait until it ends; it includes everything saved before it started.' }, 409);
      const r = await gh(env, `actions/workflows/${WORKFLOW}/dispatches`, { method: 'POST', body: JSON.stringify({ ref: branch }) });
      if (!r.ok) return json({ error: `GitHub: ${r.status} ${await r.text()}` }, r.status);
      return json({ ok: true });
    }
    if (route === 'runs') {
      const r = await gh(env, `actions/workflows/${WORKFLOW}/runs?per_page=5&branch=${branch}`);
      const j = await r.json();
      return json((j.workflow_runs || []).map(x => ({ status: x.status, conclusion: x.conclusion, created: x.created_at, updated: x.updated_at, event: x.event, url: x.html_url })));
    }
    return json({ error: 'Unknown action' }, 404);
  } catch (e) {
    return json({ error: String(e.message || e) }, 500);
  }
}
