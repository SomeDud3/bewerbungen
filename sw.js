// network-first fuer eigene Dateien, cache-first fuer CDN, GitHub-API nie
const C='bew-v2';
self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(C).then(c=>c.addAll(['./','index.html','manifest.webmanifest','icon-192.png'])))});
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!=C).map(x=>caches.delete(x)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(e.request.method!='GET'||u.hostname=='api.github.com')return;
 if(u.origin==location.origin){const k=u.origin+u.pathname;e.respondWith(fetch(e.request).then(r=>{if(r.ok){const cl=r.clone();caches.open(C).then(c=>c.put(k,cl))}return r}).catch(()=>caches.match(k)))}
 else e.respondWith(caches.match(e.request).then(m=>m||fetch(e.request).then(r=>{const cl=r.clone();caches.open(C).then(c=>c.put(e.request,cl));return r})))});
