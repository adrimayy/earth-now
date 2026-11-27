const C='earth-now-v18', FILES=['./','index.html','manifest.json','icon.png','tex/day8k.jpg','tex/day4k.jpg','tex/lights8k.jpg','tex/lights4k.jpg','tex/dem8k.png','tex/rug.png','tex/water.png','tex/moon.jpg', 'tex/moon4k.jpg', 'tex/moonh.png', 'tex/moonb.png','tex/milkyway.png','tex/stars.txt','tex/clouds.jpg','tex/seasons.jpg'];
// (fresh copies on install, not whatever the browser happens to hold)
self.addEventListener('install',e=>e.waitUntil(caches.open(C).then(c=>c.addAll(FILES.map(f=>new Request(f,{cache:'reload'})))).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x.startsWith('earth-now-')&&x!==C).map(x=>caches.delete(x)))).then(()=>self.clients.claim())));
// The app's own files come from the offline store. Anything from elsewhere (the live cloud map, the aurora reading) is
// left to the network, so it is always the newest; the page keeps its own last copy of the clouds for offline use.
self.addEventListener('fetch',e=>{ if(new URL(e.request.url).origin!==self.location.origin) return;
  e.respondWith(caches.open(C).then(c=>c.match(e.request,{ignoreSearch:true})).then(r=>r||fetch(e.request))); });
