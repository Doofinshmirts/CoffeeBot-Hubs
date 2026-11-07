'use strict';
const photo = document.querySelector('#photo');
let photoUrl;
photo?.addEventListener('change', () => {
  const preview = document.querySelector('#photo-preview');
  if (photoUrl) URL.revokeObjectURL(photoUrl);
  preview.hidden = !photo.files.length;
  if (photo.files.length) { photoUrl = URL.createObjectURL(photo.files[0]); preview.src = photoUrl; }
});
document.querySelector('#dropoff-form')?.addEventListener('submit', () => {
  const button = document.querySelector('#save-dropoff'); button.disabled = true; button.textContent = 'Saving drop-off…';
});
window.addEventListener('pageshow', () => {
  const button = document.querySelector('#save-dropoff');
  if (button) { button.disabled = false; button.textContent = 'Record drop-off →'; }
});
document.querySelectorAll('.collect-form').forEach(form => form.addEventListener('submit', event => {
  if (!window.confirm('Confirm that this entire batch has been collected?')) event.preventDefault();
}));

const config = document.querySelector('#poll-config');
if (config) {
  const initialIds = JSON.parse(config.dataset.initialIds);
  let remembered = [];
  try { remembered = JSON.parse(sessionStorage.getItem('coffeebot-seen') || '[]'); } catch (_) { /* Storage may be disabled. */ }
  const seen = new Set([...remembered, ...initialIds]);
  const saveSeen = () => { try { sessionStorage.setItem('coffeebot-seen', JSON.stringify([...seen].slice(-1000))); } catch (_) {} };
  saveSeen();
  const status = document.querySelector('#connection-status');
  const date = value => value ? new Intl.DateTimeFormat('en-SG', { timeZone: 'Asia/Singapore', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value)) + ' SGT' : 'No drop-offs yet';
  let polling = false;
  async function refresh() {
    if (document.hidden || polling) return;
    polling = true;
    const abort = new AbortController();
    const timeout = setTimeout(() => abort.abort(), 8000);
    try {
      const response = await fetch('/api/availability', { cache: 'no-store', signal: abort.signal });
      if (!response.ok) throw new Error('Unavailable');
      const data = await response.json();
      let total = 0;
      for (const hub of data.hubs) {
        total += Number(hub.available_kg);
        const card = document.querySelector(`[data-hub-id="${Number(hub.id)}"]`);
        if (!card) continue;
        card.querySelector('.hub-weight').textContent = String(Number(Number(hub.available_kg).toFixed(2)));
        card.querySelector('.batch-count').textContent = hub.batch_count;
        card.querySelector('.availability-badge').textContent = hub.available_kg > 0 ? 'Available' : 'No grounds available';
        card.querySelector('.updated').textContent = date(hub.last_update);
      }
      document.querySelector('#total-weight').textContent = String(Number(total.toFixed(2)));
      for (const batch of data.batches) {
        if (seen.has(batch.id)) continue;
        seen.add(batch.id);
        const hub = data.hubs.find(h => h.id === batch.hub_id);
        if (!hub) continue;
        const item = document.createElement('div'); item.className = 'alert';
        const link = document.createElement('a'); link.href = `/hubs/${Number(hub.id)}`;
        link.textContent = `${Number(batch.weight_kg)} kg just added at ${hub.name}. View hub →`;
        const close = document.createElement('button'); close.type = 'button'; close.textContent = '×'; close.setAttribute('aria-label', 'Dismiss notification'); close.addEventListener('click', () => item.remove());
        item.append(link, close); document.querySelector('#alerts').prepend(item);
      }
      saveSeen(); status.textContent = '● Up to date · checks every 10 seconds while this page is open';
    } catch (_) { status.textContent = 'Reconnecting… availability may be out of date. Retrying shortly.'; }
    finally { clearTimeout(timeout); polling = false; }
  }
  setInterval(refresh, 10000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  document.querySelector('#locate').addEventListener('click', () => {
    const label = document.querySelector('#location-status');
    if (!navigator.geolocation) { label.textContent = 'Location is unavailable. You can still browse all demo hubs.'; return; }
    label.textContent = 'Finding nearby demo hubs…';
    navigator.geolocation.getCurrentPosition(position => {
      const rad = d => d * Math.PI / 180;
      const distance = (lat, lon) => {
        const a = Math.sin(rad(lat - position.coords.latitude) / 2) ** 2 + Math.cos(rad(position.coords.latitude)) * Math.cos(rad(lat)) * Math.sin(rad(lon - position.coords.longitude) / 2) ** 2;
        return 6371 * 2 * Math.asin(Math.sqrt(Math.min(1, a)));
      };
      const list = document.querySelector('#hub-list');
      [...list.children].map(card => ({ card, km: distance(Number(card.dataset.lat), Number(card.dataset.lon)) }))
        .sort((a, b) => a.km - b.km).forEach(({ card, km }) => { card.querySelector('.distance').textContent = `${km.toFixed(1)} km away`; list.append(card); });
      label.textContent = 'Sorted by straight-line distance, not travel distance. Demo locations only. Your location stays in this browser.';
    }, () => { label.textContent = 'Location was unavailable or declined. Browse all demo hubs below.'; }, { timeout: 10000 });
  });
}
