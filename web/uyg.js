'use strict';
/* Raf Kamera arayüzü: tek sayfa, veriler /api/... adreslerinden gelir. Derleme adımı ve dış istek yok.
   Dosyalar: grafik.js (grafikler), uyg.js (çekirdek, üst çubuk, uyarılar, görevler, kameralar, entegrasyonlar, ayarlar),
   ekranlar.js (genel bakış, raflar, ürünler, müşteri, raporlar), duzenleyici.js (kamera, bölge ve planogram düzenleyici),
   rehber.js (tanıtım turu). */

const S = { durum: null, katalog: null, olaylar: {}, gorevler: {}, donem: { gun: 7 }, kamera: '', sayfaNo: 0 };
const $ = (s, k = document) => k.querySelector(s);
const $$ = (s, k = document) => [...k.querySelectorAll(s)];
const h = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const AYLAR = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
const GUNLER = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];
const DUZEY = { kritik: 'Kritik', yuksek: 'Yüksek', orta: 'Orta', dusuk: 'Düşük' };
const DURUM = { acik: 'Açık', ustlenildi: 'Üstlenildi', cozuldu: 'Çözüldü', yanlis: 'Yanlış alarm' };
const GDURUM = { acik: 'Açık', suruyor: 'Sürüyor', kapandi: 'Kapandı' };
const GOZ_DURUM = { dolu: 'Dolu', az: 'Azalan', bos: 'Boş', yanlis: 'Yanlış ürün', kapali: 'Önü kapalı', bilinmiyor: 'Bilinmiyor', tanimsiz: 'Veri yok' };
const ETIKET = { uygun: 'Etiket uygun', farkli: 'Fiyat farklı', yok: 'Etiket yok', okunamadi: 'Okunamadı', bakilmadi: 'Bakılmadı' };

try { const d = JSON.parse(localStorage.getItem('raf-donem') || 'null'); if (d && (d.gun || (d.bas && d.bit))) S.donem = d; } catch (x) { /* depolama kapalı */ }
try { S.kamera = localStorage.getItem('raf-kamera-suzgec') || ''; } catch (x) { /* depolama kapalı */ }
function sakla(ad, deger) { try { localStorage.setItem(ad, typeof deger === 'string' ? deger : JSON.stringify(deger)); } catch (x) { /* depolama kapalı: bu oturumda geçerli */ } }

async function api(yol, govde) {
  let r;
  try {
    r = await fetch(yol, govde ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(govde) } : {});
  } catch (x) { throw new Error('Program yanıt vermiyor. Raf Kamera kapanmış olabilir.'); }
  const j = await r.json().catch(() => ({ hata: 'Yanıt okunamadı.' }));
  if (!r.ok || j.hata) { const e = new Error(j.hata || 'İstek başarısız.'); e.motorYok = !!j.motor_yok; throw e; }
  return j;
}
function yerelGun(d = new Date()) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }
function tarih(iso, saniye) {
  if (!iso) return '–';
  const [g, s] = iso.split('T');
  const [, a, d] = g.split('-');
  const dun = yerelGun(new Date(Date.now() - 864e5));
  return (yerelGun() === g ? 'Bugün' : dun === g ? 'Dün' : `${+d} ${AYLAR[+a - 1]}`) + (s ? ' ' + s.slice(0, saniye ? 8 : 5) : '');
}
const gunAdi = iso => { const [, a, d] = iso.slice(0, 10).split('-'); return `${+d} ${AYLAR[+a - 1]}`; };
function once(iso) {
  if (!iso) return '–';
  const sn = (Date.now() - new Date(iso).getTime()) / 1000;
  if (sn < 60) return 'az önce';
  if (sn < 3600) return `${Math.floor(sn / 60)} dk önce`;
  if (sn < 86400) return `${Math.floor(sn / 3600)} sa önce`;
  return tarih(iso);
}
function sure(sn) {
  if (sn == null) return '–';
  sn = Math.round(sn);
  if (sn < 60) return `${sn} sn`;
  if (sn < 3600) return `${Math.floor(sn / 60)} dk`;
  if (sn < 86400) return `${Math.floor(sn / 3600)} sa ${Math.floor(sn % 3600 / 60)} dk`;
  return `${Math.floor(sn / 86400)} gün ${Math.floor(sn % 86400 / 3600)} sa`;
}
const sayi = (v, o = 0) => G.sayiBicim(v, o);
const yuzde = (v, o = 0) => v == null ? '–' : '%' + sayi(100 * v, o);
const para = (v, o = 0) => v == null ? '–' : sayi(v, o) + ' ' + (S.durum?.genel?.para_birimi || '₺');
function fark(su, once_, ters = false, bicim = v => sayi(v)) {
  // önceki döneme göre değişim: ters=true ise artış kötü
  if (su == null || once_ == null || (!su && !once_)) return '';
  const d = su - once_;
  if (Math.abs(d) < 1e-9 || (once_ && Math.abs(d / once_) < 0.005)) return '<span class="fark notr">değişmedi</span>';
  const kotu = ters ? d > 0 : d < 0;
  const oran = once_ ? ` (%${sayi(Math.abs(100 * d / once_))})` : '';
  return `<span class="fark ${kotu ? 'kotu' : ''}" title="önceki döneme göre">${d > 0 ? '▲' : '▼'} ${bicim(Math.abs(d))}${oran}</span>`;
}
function bildir(metin, hata) {
  let kap = document.getElementById('bildirimler');
  if (!kap) { kap = document.createElement('div'); kap.id = 'bildirimler'; kap.setAttribute('aria-live', 'polite'); document.body.appendChild(kap); }
  const e = document.createElement('div');
  e.className = 'bildirim' + (hata ? ' hata' : ''); e.textContent = metin; e.setAttribute('role', 'status');
  kap.appendChild(e);
  setTimeout(() => e.remove(), hata ? 6500 : 4200);
}
/* Onay penceresi: geri alınamaz işlemlerden önce. Promise<bool> döner. */
function onayla(baslik, metin, { tamam = 'Evet', tehlike = false } = {}) {
  return new Promise(coz => {
    const k = document.createElement('div');
    k.className = 'perde'; k.setAttribute('role', 'dialog'); k.setAttribute('aria-modal', 'true');
    k.innerHTML = `<div class="pencere" style="width:min(460px,100%)"><h2>${h(baslik)}</h2><p style="color:var(--soluk);margin:8px 0 0">${h(metin)}</p>
      <div class="eylemler"><button class="dug" data-c="0">Vazgeç</button><button class="dug ${tehlike ? 'tehlike' : 'ana'}" data-c="1">${h(tamam)}</button></div></div>`;
    const bitir = v => { k.remove(); document.removeEventListener('keydown', tus, true); coz(v); };
    const tus = e => { if (e.key === 'Escape') { e.stopPropagation(); bitir(false); } };
    k.addEventListener('click', e => { const b = e.target.closest('[data-c]'); if (b) bitir(b.dataset.c === '1'); else if (e.target === k) bitir(false); });
    document.addEventListener('keydown', tus, true);
    document.body.appendChild(k);
    k.querySelector('[data-c="1"]').focus();
  });
}

/* ------------------------------------------------------------ dönem (bütün ekranlarda ortak) */
function donemQ(ek = {}) {
  const p = new URLSearchParams(S.donem.bas ? { bas: S.donem.bas, bit: S.donem.bit } : { gun: S.donem.gun });
  for (const [a, v] of Object.entries(ek)) if (v != null && v !== '') p.set(a, v);
  return p.toString();
}
function donemAdi() {
  if (S.donem.bas) return S.donem.bas === S.donem.bit ? gunAdi(S.donem.bas) : `${gunAdi(S.donem.bas)} – ${gunAdi(S.donem.bit)}`;
  return { 1: 'Bugün', 7: 'Son 7 gün', 30: 'Son 30 gün', 90: 'Son 90 gün' }[S.donem.gun] || `Son ${S.donem.gun} gün`;
}
const donemKucuk = () => S.donem.bas ? donemAdi() : donemAdi().toLocaleLowerCase('tr');  // cümle içinde: "son 7 gün", "10 Kas – 12 Kas"
function donemSecici() {
  const dun = yerelGun(new Date(Date.now() - 864e5));
  const deger = S.donem.bas ? (S.donem.bas === dun && S.donem.bit === dun ? 'dun' : 'ozel') : String(S.donem.gun);
  return `<select class="cip" data-degis="donem" aria-label="Dönem">${[['1', 'Bugün'], ['dun', 'Dün'], ['7', 'Son 7 gün'], ['30', 'Son 30 gün'], ['90', 'Son 90 gün'], ['ozel', 'Tarih seç…']]
    .map(([v, a]) => `<option value="${v}" ${deger === v ? 'selected' : ''}>${a}</option>`).join('')}</select>`
    + (deger === 'ozel' ? `<input class="cip" type="date" id="d-bas" value="${h(S.donem.bas || '')}" aria-label="Başlangıç"><input class="cip" type="date" id="d-bit" value="${h(S.donem.bit || '')}" aria-label="Bitiş"><button class="dug kucuk" data-is="donem-uygula">Uygula</button>` : '');
}
function donemSec(deger) {
  const dun = yerelGun(new Date(Date.now() - 864e5));
  if (deger === 'dun') S.donem = { bas: dun, bit: dun };
  else if (deger === 'ozel') S.donem = { bas: S.donem.bas || yerelGun(new Date(Date.now() - 6 * 864e5)), bit: S.donem.bit || yerelGun() };
  else S.donem = { gun: +deger };
  sakla('raf-donem', S.donem);
  ustbarCiz();
  if (deger !== 'ozel') ciz();
}

/* ------------------------------------------------------------ simgeler ve sol şerit */
const ikon = d => `<svg viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
const IKON = {
  kontrol: ikon('<rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="5" rx="2"/><rect x="13" y="11" width="8" height="10" rx="2"/><rect x="3" y="14" width="8" height="7" rx="2"/>'),
  uyari: ikon('<path d="M6 9a6 6 0 0112 0c0 6 2.5 7 2.5 7h-17S6 15 6 9z"/><path d="M10 20a2 2 0 004 0"/>'),
  aksiyon: ikon('<rect x="3" y="3" width="18" height="18" rx="4"/><path d="M8 12l3 3 5-6"/>'),
  rapor: ikon('<path d="M4 20V10M10 20V4M16 20v-7M21 20H3"/>'),
  raf: ikon('<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M8 6v.1M13 12v.1M10 18v.1"/>'),
  urun: ikon('<path d="M3 7.5l9-4.5 9 4.5v9l-9 4.5-9-4.5z"/><path d="M3 7.5l9 4.5 9-4.5M12 12v9"/>'),
  musteri: ikon('<circle cx="12" cy="7" r="3.5"/><path d="M5 21c0-4 3-6.5 7-6.5s7 2.5 7 6.5"/>'),
  kamera: ikon('<rect x="2.5" y="6" width="14" height="12" rx="2.5"/><path d="M16.5 10.5l5-3v9l-5-3z"/>'),
  entegrasyon: ikon('<path d="M9 15l6-6"/><path d="M10.5 6.5l1.8-1.8a4 4 0 015.7 5.7l-1.8 1.8M13.5 17.5l-1.8 1.8a4 4 0 01-5.7-5.7l1.8-1.8"/>'),
  ses: ikon('<path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z"/><path d="M15.5 9a4.2 4.2 0 010 6M18 6.5a8 8 0 010 11"/>'),
  sessiz: ikon('<path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>'),
  yardim: ikon('<circle cx="12" cy="12" r="9"/><path d="M9.3 9.3a2.8 2.8 0 115 1.7c-.9 1-2.3 1.4-2.3 3"/><path d="M12 17.2v.1"/>'),
  ayar: ikon('<circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8"/>'),
  ara: ikon('<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>'),
  indir: ikon('<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>'),
  yazdir: ikon('<path d="M7 9V4h10v5M7 17H5a2 2 0 01-2-2v-4a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2h-2"/><rect x="7" y="14" width="10" height="6" rx="1"/>'),
  arti: ikon('<path d="M12 5v14M5 12h14"/>'),
};
const SAYFALAR = [['', 'kontrol', 'Genel', 'Genel Bakış'], ['raflar', 'raf', 'Raflar'], ['urunler', 'urun', 'Ürünler'], ['musteri', 'musteri', 'Müşteri'],
  ['gorevler', 'aksiyon', 'Görevler'], ['uyarilar', 'uyari', 'Uyarılar'], ['raporlar', 'rapor', 'Raporlar'], ['kameralar', 'kamera', 'Kameralar', 'Kameralar ve bölgeler'],
  ['entegrasyonlar', 'entegrasyon', 'Entegre', 'Entegrasyonlar']];
const MARKA = '<svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true"><rect x="8" y="6.5" width="5" height="4.5" rx="1" fill="#0f8b7d"/><rect x="14.5" y="6.5" width="4" height="4.5" rx="1" fill="#5cc23a"/><rect x="8" y="14" width="3.5" height="4.5" rx="1" fill="#5cc23a"/><rect x="13" y="14" width="5.5" height="4.5" rx="1" fill="#0f8b7d"/><rect x="20" y="14" width="4" height="4.5" rx="1" fill="#0f8b7d"/><rect x="17" y="21.5" width="7" height="4.5" rx="1" fill="#5cc23a"/><path d="M6 11.5h20M6 19h20M6 26.5h20" stroke="#0d2523" stroke-width="1.8" stroke-linecap="round"/></svg>';

function rayCiz() {
  const yol = konum().yol, secili = y => yol === y || (y === 'kameralar' && yol.startsWith('kamera/'));
  const acikGorev = S.durum?.acik_gorev ?? 0;
  const acikUyari = (S.durum?.kameralar || []).reduce((t, k) => t + (k.acik || 0), 0);
  const isVar = S.durum?.is?.durum === 'calisiyor' || Object.values(S.durum?.izlemeler || {}).some(i => i.durum === 'calisiyor');
  const rozet = n => n ? `<span class="rozet">${n > 99 ? '99+' : n}</span>` : '';
  $('#ray').innerHTML = `<div class="marka" title="Raf Kamera">${MARKA}</div>`
    + SAYFALAR.map(([y, i, ad, tam]) => `<a href="#/${y}" title="${h(tam || ad)}" aria-label="${h(tam || ad)}" class="${secili(y) ? 'secili' : ''}" ${secili(y) ? 'aria-current="page"' : ''}>${IKON[i]}${ad}${y === 'uyarilar' ? rozet(acikUyari) : ''}${y === 'gorevler' ? rozet(acikGorev) : ''}${y === 'kameralar' && isVar ? '<span class="rozet">•</span>' : ''}</a>`).join('')
    + `<div class="bosluk"></div><a href="#" data-is="rehber" title="Tanıtım turu" aria-label="Tanıtım turu">${IKON.yardim}Tur</a><a href="#/ayarlar" title="Ayarlar" aria-label="Ayarlar" class="${yol === 'ayarlar' ? 'secili' : ''}">${IKON.ayar}Ayarlar</a>`;
}
function konum() {
  const ham = location.hash.replace(/^#\/?/, '');
  const [yol, sorgu] = ham.split('?');
  return { yol: yol || '', q: Object.fromEntries(new URLSearchParams(sorgu || '')) };
}
function git(yol, q) { const s = new URLSearchParams(q || {}).toString(); location.hash = '#/' + yol + (s ? '?' + s : ''); }
function sorguDegistir(q) { const k = konum(); history.replaceState(null, '', '#/' + k.yol + (Object.keys(q).length ? '?' + new URLSearchParams(q) : '')); }
const ust = (baslik, alt, sag = '') => `<div class="ust"><h1>${h(baslik)}<small>${alt}</small></h1>${sag}</div>`;
const yukleniyor = (metin = 'Yükleniyor…') => `<div class="yukleniyor" role="status"><span class="don"></span>${h(metin)}</div>`;
const durumRozeti = d => `<span class="d-rozet"><i style="background:${G.DURUM_RENK[d] || '#ccc'}"></i>${h(GOZ_DURUM[d] || d)}</span>`;
const duzeyRozet = o => `<span class="rozet ${o.duzey}">${DUZEY[o.duzey] || h(o.duzey)}</span>${o.suruyor ? ' <span class="rozet ciddi">Sürüyor</span>' : ''}`;
const kameraAdi = kod => (S.durum?.kameralar || []).find(k => k.kod === kod)?.ad || kod;
const gorselAdresi = f => f ? '/urunler/gorsel/' + encodeURIComponent(f) : '';

/* ------------------------------------------------------------ üst çubuk: arama, dönem, örnek veri, bildirimler */
function ustbarCiz() {
  const d = S.durum, g = d?.genel || {};
  const ornek = d?.ornek_veri?.yuklu;
  const odak = document.activeElement?.id === 'ara';
  const aranan = $('#ara')?.value || '';
  $('#ustbar').innerHTML = `<div class="tesis">${h(g.tesis || 'Raf Kamera')}${g.sube ? `<small>${h(g.sube)}</small>` : ''}</div>
    <div class="arama" role="search">${IKON.ara}<input id="ara" type="search" placeholder="Ürün, raf ya da kamera ara" autocomplete="off" aria-label="Ara" value="${h(aranan)}"><div id="ara-sonuc"></div></div>
    <div class="sag">${ornek ? `<span class="ornek-rozet" title="Ekrandaki veriler örnek verilerdir; gerçek kameralardan gelmez.">Örnek veriler <button data-is="ornek-kaldir">Kaldır</button></span>` : ''}
      ${d?.gelistirme ? '<span class="rozet mavi" title="RAF_GELISTIRME açık: AugeLab Studio çalıştırılmaz">Geliştirme kipi</span>' : ''}
      ${donemSecici()}
      <div style="position:relative"><button class="zil" data-is="zil" aria-label="Bildirimler" title="Yeni uyarılar">${IKON.uyari}${ZIL.yeni ? `<span class="nokta">${ZIL.yeni > 99 ? '99+' : ZIL.yeni}</span>` : ''}</button><div id="zil-panel"></div></div></div>`;
  if (odak) { const e = $('#ara'); e.focus(); e.setSelectionRange(e.value.length, e.value.length); }
}
const ARA = { zaman: null, sonuc: [], i: -1 };
function aramaGit(s) {
  $('#ara-sonuc').innerHTML = ''; $('#ara').value = '';
  if (s.tur === 'urun') git('urunler', { id: s.kimlik });
  else if (s.tur === 'goz') git('raflar', { kamera: s.kamera, goz: s.goz });
  else if (s.tur === 'kamera') git((S.durum.kameralar.find(k => k.kod === s.kamera)?.goz) ? 'raflar' : 'kamera/' + s.kamera, (S.durum.kameralar.find(k => k.kod === s.kamera)?.goz) ? { kamera: s.kamera } : undefined);
  else if (s.tur === 'bolge') git(['raf', 'dolap'].includes(s.bolge_tur) ? 'raflar' : 'musteri', { kamera: s.kamera });
}
function aramaCiz() {
  const k = $('#ara-sonuc');
  if (!ARA.sonuc.length) { k.innerHTML = $('#ara').value.trim().length >= 2 ? '<div class="arama-sonuc"><div class="not" style="padding:10px 12px">Sonuç yok.</div></div>' : ''; return; }
  const tur = { urun: 'Ürün', goz: 'Göz', kamera: 'Kamera', bolge: 'Bölge' };
  k.innerHTML = `<div class="arama-sonuc" role="listbox">${ARA.sonuc.map((s, i) => `<a href="#" data-ara="${i}" class="${i === ARA.i ? 'aktif' : ''}" role="option"><span class="rozet gri">${tur[s.tur]}</span><span style="flex:1;min-width:0"><b>${h(s.ad)}</b><br><small>${h(s.alt || '')}</small></span></a>`).join('')}</div>`;
}

/* bildirim zili: son görülen olaydan sonra gelenler */
const ZIL = { son: null, yeni: 0, acik: false, ses: true };
try { ZIL.son = +localStorage.getItem('raf-zil-son') || null; ZIL.ses = localStorage.getItem('raf-siren') !== '0'; } catch (x) { /* depolama kapalı */ }
async function zilPaneli() {
  const k = $('#zil-panel');
  if (!ZIL.acik) { k.innerHTML = ''; return; }
  k.innerHTML = `<div class="zil-panel">${yukleniyor()}</div>`;
  let d;
  try { d = await api('/api/olaylar?gun=7&sinir=12'); } catch (x) { k.innerHTML = `<div class="zil-panel"><div class="not">${h(x.message)}</div></div>`; return; }
  for (const o of d.olaylar) S.olaylar[o.id] = o;
  k.innerHTML = `<div class="zil-panel" role="dialog" aria-label="Son uyarılar"><div class="bas"><b style="flex:1">Son uyarılar</b>
      <label class="not" style="display:flex;gap:6px;align-items:center;cursor:pointer"><input type="checkbox" data-degis="zil-ses" ${ZIL.ses ? 'checked' : ''}> Ses</label>
      <a class="dug kucuk" href="#/uyarilar">Tümü</a></div>
    <div class="liste kaydir" style="max-height:380px">${d.olaylar.length ? d.olaylar.map(o => uyariSatiri(o)).join('') : '<div class="not" style="padding:10px">Son 7 günde uyarı yok.</div>'}</div></div>`;
  ZIL.son = S.durum?.son_olay || ZIL.son; ZIL.yeni = 0; sakla('raf-zil-son', String(ZIL.son || 0));
  const z = $('.zil .nokta'); if (z) z.remove();
}
const SES = { ctx: null };
function sesBaglami() {
  if (!SES.ctx) { const C = window.AudioContext || window.webkitAudioContext; if (!C) return null; SES.ctx = new C(); }
  if (SES.ctx.state === 'suspended') SES.ctx.resume().catch(() => { /* sayfaya tıklanmadan ses açılmaz */ });
  return SES.ctx;
}
function sirenCal(sn = 0.9) {
  // kısa, iki tonlu uyarı sesi (ses dosyası yok, WebAudio ile üretilir)
  if (!ZIL.ses) return;
  const c = sesBaglami();
  if (!c) return;
  const t0 = c.currentTime + 0.03, o = c.createOscillator(), g = c.createGain();
  o.type = 'triangle';
  o.frequency.setValueAtTime(880, t0); o.frequency.setValueAtTime(660, t0 + sn / 2);
  g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(0.18, t0 + 0.04); g.gain.setValueAtTime(0.18, t0 + sn - 0.1); g.gain.exponentialRampToValueAtTime(0.0001, t0 + sn);
  o.connect(g); g.connect(c.destination); o.start(t0); o.stop(t0 + sn + 0.05);
}
document.addEventListener('pointerdown', () => { if (ZIL.ses) sesBaglami(); }, { capture: true });
async function yeniUyarilar() {
  const son = S.durum?.son_olay || 0;
  if (ZIL.son == null) { ZIL.son = son; sakla('raf-zil-son', String(son)); return; }
  if (son <= ZIL.son) { if (ZIL.yeni) { ZIL.yeni = 0; ustbarCiz(); } return; }
  const once_ = ZIL.yeni;
  try {
    const d = await api(`/api/olaylar?gun=2&sinir=100`);
    ZIL.yeni = d.olaylar.filter(o => o.id > ZIL.son).length;
    const enYeni = d.olaylar.find(o => o.id > ZIL.son && o.id > (ZIL.cald || 0));
    if (enYeni && ZIL.yeni > once_) {
      ZIL.cald = d.olaylar[0].id;
      if (['kritik', 'yuksek'].includes(enYeni.duzey) && !enYeni.ornek) sirenCal();
      if (!enYeni.ornek) bildir(`Yeni uyarı · ${enYeni.kural_ad} · ${enYeni.kamera_ad}`);
    }
  } catch (x) { /* program kapanmış olabilir */ }
  if (!ZIL.acik) ustbarCiz();
}

/* ------------------------------------------------------------ ortak parçalar */
// süren uyarının süresi: motorun son bildirdiği süre ile başlangıçtan bu yana geçen sürenin büyüğü
const olaySuresi = o => o.suruyor ? Math.max(o.sure_sn || 0, (Date.now() - new Date(o.zaman).getTime()) / 1000) : o.sure_sn;
function uyariSatiri(o, secili) {
  S.olaylar[o.id] = o;
  return `<button type="button" class="uyari ${secili ? 'secili' : ''}" data-is="olay-ac" data-id="${o.id}">${o.kare ? `<img src="/cikti/${h(o.kare)}" loading="lazy" alt="">` : '<div class="yok"></div>'}
    <div class="govde"><div>${duzeyRozet(o)} ${o.durum !== 'acik' ? `<span class="rozet gri">${DURUM[o.durum] || h(o.durum)}</span>` : ''}</div>
    <div class="bas">${h(o.kural_ad)}${o.urun_ad ? ' · ' + h(o.urun_ad) : ''}</div><div class="alt">${h(o.kamera_ad)}${o.bolge ? ' · ' + h(o.bolge) : ''} · ${tarih(o.zaman)} · ${sure(olaySuresi(o))}${o.suruyor ? ' (sürüyor)' : ''}</div></div></button>`;
}
function kameraHali(k) {
  const is = S.durum?.is;
  if (k.suruyor_ciddi) return ['alarm', 'Uyarı'];
  if (S.durum?.izlemeler?.[k.kod]?.durum === 'calisiyor') return ['canli', 'Canlı'];
  if (is?.durum === 'calisiyor' && is.kod === k.kod && ['video', 'ornek'].includes(is.tur)) return ['canli', 'Analiz'];
  if (k.ornek) return ['ornek', 'Örnek'];
  if (k.eski) return ['eski', 'Veri eski'];
  return ['', k.son_analiz ? 'Beklemede' : 'Veri yok'];
}
function kameraKarosu(k) {
  const [sinif, ad] = kameraHali(k), kare = k.son_kare || k.referans_karesi;
  const hedef = k.goz ? `#/raflar?kamera=${encodeURIComponent(k.kod)}` : `#/kamera/${encodeURIComponent(k.kod)}`;
  return `<a class="kam ${sinif === 'alarm' ? 'alarm' : ''}" href="${hedef}" data-kod="${h(k.kod)}" title="${h(k.ad)}${k.son_analiz ? ' · son kayıt ' + h(tarih(k.son_analiz)) : ''}">${kare ? `<img src="${h(kare)}" alt="">` : `<div class="bos">${sinif === 'canli' ? 'Görüntü bekleniyor…' : 'Henüz görüntü yok.<br>Kameralar ekranından başlatın.'}</div>`}
    <div class="hal ${sinif}">${ad}</div>${k.acik ? `<div class="acik">${k.acik} açık</div>` : ''}<div class="ad"><span>${h(k.ad)}</span>${k.son_analiz ? `<span>${once(k.son_analiz)}</span>` : ''}</div></a>`;
}
function hataKarti(x) {
  return `<div class="bos-durum"><h3>Sayfa açılamadı</h3><p>${h(x.message)}</p><div class="eylemler"><button class="dug" data-is="yenile">Yeniden dene</button></div></div>`;
}
function ornekVeriDavet(baslik = 'Henüz veri yok') {
  return `<div class="bos-durum"><h3>${h(baslik)}</h3><p>Kameralarınızı ekleyip raf ve bölgeleri çizdiğinizde sayılar burada görünür.</p>
    <p class="not">Ekranları önce denemek isterseniz küçük bir marketin iki haftalık örnek verisini yükleyin. Örnek veriler ayrı tutulur ve tek tıkla kaldırılır.</p>
    <div class="eylemler"><a class="dug ana" href="#/kamera/yeni">Kamera ekle</a><button class="dug" data-is="ornek-yukle">Örnek verilerle dene</button>${(S.durum?.ornek_videolar || []).length && !S.durum?.gelistirme ? '<button class="dug" data-is="ornek">Örnek videoları çözümle</button>' : ''}</div></div>`;
}

/* ------------------------------------------------------------ AugeLab Studio kurulum sihirbazı (iskeletten, değişmedi)
   Adım adım: Studio'yu kur → AugeLab hesabı → lisans kodu → hazır. Studio penceresi hiç açılmaz. Geliştirme kipinde açılmaz. */
const SH = { kapatildi: false, cevrimdisi: 0, hesapVar: false, zamanlayici: null, kod: '', hata: '', otoDeneme: false };
try { SH.hesapVar = localStorage.getItem('raf-augelab-hesap') === '1'; } catch (x) { /* depolama kapalı */ }
const SH_KURULUM = ['indiriliyor', 'vc', 'kuruluyor', 'pencere'];
const shMb = b => (b / 1048576).toFixed(1).replace('.', ',');
function shHesapUrl() { return S.durum?.hesap_url || 'https://account.augelab.com/'; }
function shDeniyor(d) { return d?.is?.tur === 'studio-dene' && d?.is?.durum === 'calisiyor'; }
function shAdim(d) {
  const k = d?.studio_kurulum || {};
  const kuruluyor = (d?.is?.tur === 'studio-kurulum' && d?.is?.durum === 'calisiyor') || SH_KURULUM.includes(k.asama);
  if (!d?.studio_kurulu || kuruluyor) return 0;
  if (d?.studio?.bagli && !shDeniyor(d)) return 3;
  if (!SH.hesapVar && !d?.studio?.lisans_kaydedildi && !shDeniyor(d)) return 1;
  return 2;
}
function shHesap(adim, d) {
  const k = d?.studio_kurulum || {};
  const goster = !SH.hesapVar && (adim === 1 || (adim === 0 && SH_KURULUM.includes(k.asama)));
  $('#sh-hesap').hidden = !goster;
  $('#sihirbaz').classList.toggle('genis', goster);
  if (!goster) return;
  const url = shHesapUrl() + '?p=signup';
  const cerceve = $('#sh-iframe');
  if (cerceve.dataset.url !== url) {
    cerceve.src = url; cerceve.dataset.url = url;
    $('#sh-cerceve').classList.remove('tam'); $('#sh-ust').textContent = 'Sayfanın üstünü göster';
    $('#sh-kaydir').classList.remove('gitti');
  }
  $('#sh-hesap-bag').href = url;
  $('#sh-hesap-yazi').innerHTML = adim === 0
    ? '<b>AugeLab hesabınız yoksa kurulum sürerken burada oluşturun.</b> Lisans kodu için gerekli.'
    : '<b>AugeLab hesabınızı burada oluşturun</b> (e-postanıza gelen bağlantıyla onaylayın). Hesabınız varsa “Hesabım var”a basın.';
}
function shSonDeneme(d) {
  const is = d?.is;
  if (is?.tur !== 'studio-dene' || is.durum === 'calisiyor' || d?.studio?.bagli) return '';
  return is.durum === 'hata' ? (is.satirlar || []).slice(-1)[0] || 'Lisans bulunamadı.' : '';
}
function shCiz() {
  const d = S.durum;
  if (!d || !$('#sihirbaz').open) return;
  const k = d.studio_kurulum || {};
  const adim = shAdim(d);
  document.querySelectorAll('#sihirbaz .sh-adimlar li').forEach((li, i) => { li.className = i < adim ? 'bitti' : i === adim ? 'su' : ''; });
  let govde = '', eylem = '';
  if (adim === 0 && SH_KURULUM.includes(k.asama)) {
    const sira = { indiriliyor: 0, vc: 1, kuruluyor: 2, pencere: 2 }[k.asama];
    const yuzde_ = k.toplam ? Math.round(100 * k.indirilen / k.toplam) : 0;
    const indirme = k.toplam ? `<div class="sh-cubuk"><i style="width:${yuzde_}%"></i></div><div class="sh-bekle">${h(k.ne)} · ${shMb(k.indirilen)} / ${shMb(k.toplam)} MB · %${yuzde_}</div>` : '';
    const gecen = `${Math.floor((k.gecen || 0) / 60)}:${String((k.gecen || 0) % 60).padStart(2, '0')}`;
    const satir = (i, yazi, ek = '') => `<li style="list-style:none;margin-left:-20px">${i < sira ? '✓' : i === sira ? '▶' : '○'} ${i === sira ? `<b>${yazi}</b>` : yazi}${i === sira ? ek : ''}</li>`;
    govde = `<h2>AugeLab Studio kuruluyor</h2><ol class="yap">
      ${satir(0, 'AugeLab kurulum dosyasını indir', k.asama === 'indiriliyor' ? indirme : '')}
      ${satir(1, 'Visual C++ bileşenini kur (Microsoft)', k.asama === 'vc' ? (indirme || '<div class="sh-bekle"><span class="sh-don"></span>Kuruluyor. Windows izin sorarsa <b>Evet</b> deyin.</div>') : '')}
      ${satir(2, k.asama === 'pencere' ? 'AugeLab Studio’yu kurulum penceresinde kur' : 'AugeLab Studio’yu kur (birkaç dakika sürer)',
        `<div class="sh-bekle"><span class="sh-don"></span>${k.asama === 'pencere' ? 'Kurulum penceresindeki adımları tamamlayın. ' : ''}${gecen}</div>`)}
    </ol>`;
  } else if (adim === 0) {
    govde = `<h2>AugeLab Studio kurulu değil</h2><p>Raf Kamera görüntüleri bu bilgisayardaki <b>AugeLab Studio</b> ile analiz eder; görüntüler internete gönderilmez. Studio arka planda çalışır, penceresi açılmaz.</p>
      <p>Raf Kamera, AugeLab Studio’yu AugeLab’den indirip bu bilgisayara kuracak; Visual C++ bileşeni eksikse onu da Microsoft’tan kurar.</p>
      ${k.asama === 'hata' && k.hata ? `<p class="hata">${h(k.hata)}</p>` : ''}`;
    eylem = `<button class="dug ana" data-is="studio-kurulum" data-tur="kur"${d.is?.durum === 'calisiyor' ? ' disabled' : ''}>${k.asama === 'hata' ? 'Tekrar dene' : 'İndir ve kur'} →</button>`;
  } else if (adim === 1) {
    govde = '<h2>AugeLab hesabı</h2><p>AugeLab Studio kuruldu. Studio’yu etkinleştiren lisans kodu AugeLab hesabınızda görünür; ücretsiz Community planı yeterli.</p>';
    eylem = '<button class="dug ana" id="sh-hesap-tamam" type="button">Hesabım hazır →</button>';
  } else if (adim === 2) {
    const deniyor = shDeniyor(d);
    const hata = SH.hata || shSonDeneme(d);
    govde = `<h2>Lisans kodu</h2>
      <ol class="yap">
        <li>AugeLab hesabınıza giriş yapın (Google, Microsoft ya da e-posta) ve lisans kodunu kopyalayın.
          <div style="margin-top:8px"><button class="dug" data-is="hesap-ac">Lisans kodumu al ↗</button></div></li>
        <li>Kodu buraya yapıştırın. Raf Kamera kodu yalnızca AugeLab Studio’ya verir; saklamaz.
          <div class="sh-kod"><input id="sh-kod" autocomplete="off" spellcheck="false" placeholder="Lisans kodu" value="${h(SH.kod)}"${deniyor ? ' disabled' : ''}></div></li>
      </ol>
      ${deniyor ? '<div class="sh-bekle"><span class="sh-don"></span>Lisans kontrol ediliyor…</div>' : ''}
      ${hata ? `<p class="hata">${h(hata)}</p>` : ''}
      ${d.studio?.lisans_kaydedildi || deniyor ? '' : '<p class="soluk" style="font-size:13px">Studio bu bilgisayarda zaten etkinse kod girmeden <a href="#" id="sh-dene">lisansı kontrol edin</a>.</p>'}`;
    eylem = `<button class="dug ana" id="sh-kaydet" type="button"${deniyor ? ' disabled' : ''}>Kaydet →</button>`;
  } else {
    govde = `<h2>Hazır</h2><p>AugeLab Studio ${h(d.studio?.surum || '')} arka planda çalışmaya hazır; penceresi açılmaz. Kameralar ekranından kameralarınızı ekleyip analizi başlatabilirsiniz.</p>`;
    eylem = '<button class="dug ana" data-is="sihirbaz-kapat">Bitir</button>';
  }
  const odak = document.activeElement?.id === 'sh-kod';
  $('#sh-govde').innerHTML = govde; $('#sh-eylem').innerHTML = eylem;
  const model = modelIndirme(d);
  $('#sh-model').hidden = !model; $('#sh-model').innerHTML = model;
  if (adim === 2) {
    const girdi = $('#sh-kod');
    girdi.oninput = () => { SH.kod = girdi.value; SH.hata = ''; };
    girdi.onkeydown = e => { if (e.key === 'Enter') $('#sh-kaydet').click(); };
    if (odak) { girdi.focus(); girdi.setSelectionRange(girdi.value.length, girdi.value.length); }
    $('#sh-kaydet').onclick = shKaydet;
    const dene = $('#sh-dene');
    if (dene) dene.onclick = async e => { e.preventDefault(); SH.hata = ''; try { await api('/api/studio/dene', {}); } catch (x) { SH.hata = x.message; } await durumAl(); };
  }
  if (adim === 1) $('#sh-hesap-tamam').onclick = () => $('#sh-hesabim-var').click();
  if (adim === 2 && d.studio?.lisans_kaydedildi && d.studio?.hazir !== true && !shDeniyor(d) && !SH.otoDeneme && d.is?.durum !== 'calisiyor' && !d.model_indirme?.eksik) {
    SH.otoDeneme = true;
    api('/api/studio/dene', {}).then(durumAl).catch(x => { SH.hata = x.message; shCiz(); });
  }
  shHesap(adim, d);
  $('#sh-sonra').style.visibility = adim === 3 ? 'hidden' : 'visible';
}
async function shKaydet() {
  const kod = (SH.kod || '').trim();
  if (!kod) { SH.hata = 'Lisans kodunu yapıştırın.'; shCiz(); return; }
  SH.hata = '';
  $('#sh-kaydet').disabled = true;
  try { await api('/api/studio/lisans', { kod }); SH.kod = ''; } catch (x) { SH.hata = x.message; }
  await durumAl();
}
function sihirbazAc() {
  if (S.durum?.gelistirme) return bildir('Geliştirme kipinde AugeLab Studio kurulumu kapalı.');
  SH.kapatildi = false;
  if (!$('#sihirbaz').open) $('#sihirbaz').showModal();
  shCiz();
  clearInterval(SH.zamanlayici);
  SH.zamanlayici = setInterval(async () => { try { await durumAl(); } catch (x) { /* program kapanmış olabilir */ } }, 1500);
}
function sihirbazKapat() { $('#sihirbaz').close(); clearInterval(SH.zamanlayici); }
function sihirbazIzle() {
  if (S.durum?.gelistirme) return;
  const bagli = !!S.durum?.studio?.bagli;
  SH.cevrimdisi = bagli ? 0 : SH.cevrimdisi + 1;
  if (!bagli && SH.cevrimdisi >= 2 && !SH.kapatildi && !$('#sihirbaz').open && !document.getElementById('rehber')) sihirbazAc();
  shCiz();
}
$('#sh-sonra').onclick = () => { SH.kapatildi = true; sihirbazKapat(); };
$('#sh-hesabim-var').onclick = () => { SH.hesapVar = true; sakla('raf-augelab-hesap', '1'); shCiz(); };
$('#sh-ust').onclick = () => { const tam = $('#sh-cerceve').classList.toggle('tam'); $('#sh-ust').textContent = tam ? 'Formu öne getir' : 'Sayfanın üstünü göster'; };
$('#sh-cerceve').addEventListener('mouseenter', () => setTimeout(() => $('#sh-kaydir').classList.add('gitti'), 4000));
$('#sihirbaz').addEventListener('cancel', () => { SH.kapatildi = true; clearInterval(SH.zamanlayici); });

let otoDenemeYapildi = false;
function studioOtoDene(d) {
  if (d?.gelistirme || otoDenemeYapildi || !d?.studio_kurulu || d?.studio?.kurulu === false || d?.studio?.hazir != null || d?.is?.durum === 'calisiyor' || d?.model_indirme?.eksik) return;
  otoDenemeYapildi = true;
  api('/api/studio/dene', {}).then(durumAl).catch(() => { /* iş çalışıyor olabilir; sihirbazdan yeniden denenir */ });
}
function studioUyarisi() {
  const d = S.durum;
  if (d?.gelistirme) return '<div data-studio-kurulum class="uyari-seridi bilgi-seridi"><b>Geliştirme kipi.</b> AugeLab Studio çalıştırılmaz; analiz ve motor işleri kapalı. Ekranlar kayıtlı ya da örnek verilerle çalışır.</div>';
  if (d?.studio?.bagli) return '<div data-studio-kurulum hidden></div>';
  const kuruluyor = d?.is?.tur === 'studio-kurulum' && d?.is?.durum === 'calisiyor';
  const deniyor = d?.is?.tur === 'studio-dene' && d?.is?.durum === 'calisiyor';
  if (deniyor || (d?.studio_kurulu && d?.studio?.hazir == null && !kuruluyor)) return '<div data-studio-kurulum class="uyari-seridi"><b>Lisans kontrol ediliyor</b> Lütfen bekleyin.</div>';
  const baslik = kuruluyor ? 'AugeLab Studio kuruluyor' : d?.studio_kurulu ? 'Lisans bulunamadı' : 'AugeLab Studio kurulu değil';
  const ek = d?.studio_kurulu && d?.studio?.hata ? h(d.studio.hata) + ' ' : 'Analiz için AugeLab Studio gerekir (arka planda çalışır, penceresi açılmaz). ';
  return '<div data-studio-kurulum class="uyari-seridi"><b>' + baslik + '</b> ' + ek + '<button class="dug kucuk ana" data-is="sihirbaz-ac">Kurulum sihirbazı</button></div>';
}
function modelIndirme(d) {
  const m = d?.model_indirme;
  if (!m?.eksik) return '';
  if (m.asama === 'dogrulaniyor') return '<b>Modeller hazırlanıyor…</b> Dosyalar doğrulanıyor; birkaç saniye sürer.';
  if (m.asama === 'indiriliyor') {
    const y = m.toplam ? Math.round(100 * m.indirilen / m.toplam) : 0;
    return `<b>Model indiriliyor… %${y}</b> ${h(m.ne || '')} · ${shMb(m.indirilen)} / ${shMb(m.toplam)} MB. İndirme bitince analiz başlatılabilir.<div class="sh-cubuk"><i style="width:${y}%"></i></div>`;
  }
  const dugme = `<button class="dug kucuk ana" data-is="model-indir">${m.asama === 'hata' ? 'Yeniden dene' : 'İndir'}</button>`;
  if (m.asama === 'hata') return `<b>Model indirilemedi.</b> ${h(m.hata)} ${dugme}`;
  return `<b>Modeller yok.</b> Analiz için indirilmeleri gerekir (yaklaşık ${Math.max(1, Math.round((m.boyut || 0) / 1e6))} MB). ${dugme}`;
}
function modelIndirmeSeridi() { const m = modelIndirme(S.durum); return m ? `<div data-model-indirme class="uyari-seridi">${m}</div>` : '<div data-model-indirme hidden></div>'; }
function modelUyarisi() {
  const d = S.durum, k = d?.model_kilidi;
  let model = '';
  if (d?.model_indirme?.eksik) model = modelIndirmeSeridi();
  else if (k?.paketli && k.durum !== 'studio_kosusunda_dogrulanir') model = '<div class="uyari-seridi"><b>Model paketi</b> ' + h(k.mesaj || 'Model paketi açılamıyor.') + '</div>';
  else if (d && !d.model) model = '<div class="uyari-seridi"><b>Model dosyaları yok.</b> Analiz yapılamaz; programı yeniden kurun.</div>';
  return studioUyarisi() + model;
}

/* ------------------------------------------------------------ Uyarılar */
async function sayfaUyarilar(q) {
  const d = await api('/api/olaylar?' + donemQ({ kamera: q.kamera, kategori: q.kategori, duzey: q.duzey, durum: q.durum, kural: q.kural, bolge: q.bolge, sirala: q.sirala, sinir: q.hepsi ? 1000 : 150 }));
  const sec = (ad, etiket, secenekler) => `<select class="cip" data-degis="suzgec" data-alan="${ad}" aria-label="${h(etiket)}"><option value="">${etiket}</option>${secenekler.map(([v, a]) => `<option value="${h(v)}" ${q[ad] === String(v) ? 'selected' : ''}>${h(a)}</option>`).join('')}</select>`;
  const kurallar_ = d.kurallar?.length ? d.kurallar.map(k => [k.kod, k.ad]) : S.katalog.kurallar.filter(k => k.olay).map(k => [k.kod, k.ad]);
  const suzgec = sec('kural', 'Bütün özellikler', kurallar_) + sec('kamera', 'Bütün kameralar', S.durum.kameralar.map(k => [k.kod, k.ad]))
    + sec('bolge', 'Bütün bölgeler', (d.bolgeler || []).map(b => [b, b])) + sec('kategori', 'Bütün kategoriler', Object.entries(S.katalog.kategoriler))
    + sec('duzey', 'Bütün düzeyler', Object.entries(DUZEY)) + sec('durum', 'Bütün durumlar', Object.entries(DURUM)) + sec('sirala', 'Yeniden eskiye', [['puan', 'Önceliğe göre']]);
  const filtreli = ['kural', 'kamera', 'bolge', 'kategori', 'duzey', 'durum'].some(a => q[a]);
  $('#sayfa').innerHTML = ust('Uyarılar', `${donemAdi()} · ${d.toplam} uyarı${d.suruyor ? ` · ${d.suruyor} sürüyor` : ''}`,
    `<a class="dug" href="/api/disa/olaylar.xlsx?${donemQ()}">${IKON.indir}Excel</a>`)
    + `<div class="ust" style="margin-top:-6px;gap:6px">${suzgec}${filtreli ? '<button class="dug kucuk" data-is="suzgec-temizle">Süzgeçleri temizle</button>' : ''}</div>`
    + (d.olaylar.length ? `<div class="liste">${d.olaylar.map(o => uyariSatiri(o, q.id == o.id)).join('')}</div>${d.toplam > d.olaylar.length ? `<p class="not">${d.toplam} uyarının ilk ${d.olaylar.length} tanesi gösteriliyor. ${d.olaylar.length < 1000 ? '<a href="#" data-is="uyari-hepsi">Daha fazla göster</a> · ' : ''}Süzgeç seçin ya da Excel'e aktarın.</p>` : ''}`
      : `<div class="bos-durum"><h3>Uyarı yok</h3><p>${filtreli ? 'Bu süzgeçlere uyan uyarı bulunamadı.' : 'Bu dönemde uyarı yok.'}</p></div>`);
  if (q.id) { const o = S.olaylar[q.id] || await api('/api/olay/' + q.id).catch(() => null); if (o) olayCekmecesi(o); }
}
function olayCekmecesi(o) {
  S.olaylar[o.id] = o;
  $('#katman').innerHTML = `<aside class="cekmece form" role="dialog" aria-label="Uyarı ayrıntısı"><div class="cekmece-bas"><div>
      <div>${duzeyRozet(o)} <span class="rozet gri">${DURUM[o.durum] || h(o.durum)}</span>${o.ornek ? ' <span class="rozet mor">Örnek</span>' : ''}</div><h2 style="margin-top:6px">${h(o.kural_ad)}${o.urun_ad ? ' · ' + h(o.urun_ad) : ''}</h2>
      <div class="not">${h(o.kamera_ad)}${o.bolge ? ' · ' + h(o.bolge) : ''} · ${tarih(o.zaman, true)}${o.vardiya ? ' · ' + h(o.vardiya) + ' vardiyası' : ''}</div></div>
      <button class="dug kucuk" data-is="katman-kapat" aria-label="Kapat">Kapat</button></div>
    ${o.klip ? `<video src="/cikti/${h(o.klip)}" controls autoplay muted loop playsinline></video>` : (o.kare ? `<img class="buyuk" src="/cikti/${h(o.kare)}" alt="Uyarının karesi (yüzler gizli)">` : '<div class="bos-durum" style="padding:20px">Bu uyarının karesi yok.</div>')}
    <div class="bilgi"><div><span class="et">Süre</span><b>${sure(olaySuresi(o))}</b><span class="not">${o.suruyor ? 'sürüyor' : 'kapandı'}</span></div>
      <div><span class="et">Öncelik</span><b>${o.puan} / 25</b><span class="not">${DUZEY[o.duzey] || ''}</span></div>
      <div><span class="et">${o.kural === 'kasa_kuyrugu' ? 'Kuyruk' : o.kural === 'fiyat_farkli' ? 'Okunan / beklenen' : 'Uyarı no'}</span><b>${o.kural === 'kasa_kuyrugu' && o.deger != null ? sayi(o.deger) + ' kişi' : o.kural === 'fiyat_farkli' && o.deger != null ? `${sayi(o.deger, 2)} / ${h(o.beklenen ?? '–')}` : '#' + o.id}</b><span class="not">${h(S.katalog.kategoriler[o.kategori] || o.kategori)}</span></div></div>
    ${o.aciklama ? `<p>${h(o.aciklama)}</p>` : ''}
    ${o.goz ? `<p><a class="dug kucuk" href="#/raflar?kamera=${encodeURIComponent(o.kamera)}&goz=${encodeURIComponent(o.goz)}">Gözün geçmişini aç</a></p>` : ''}
    <label for="o-ustlenen">Üstlenen</label><input id="o-ustlenen" value="${h(o.ustlenen || '')}" placeholder="ad ya da görev" maxlength="80">
    <label for="o-not">Not</label><textarea id="o-not" placeholder="ne yapıldı, ne görüldü" maxlength="2000">${h(o.notlar || '')}</textarea>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
      <button class="dug" data-is="olay-durum" data-id="${o.id}" data-durum="ustlenildi">Üstlen</button>
      <button class="dug" data-is="olay-durum" data-id="${o.id}" data-durum="cozuldu">Çözüldü</button>
      <button class="dug" data-is="olay-durum" data-id="${o.id}" data-durum="yanlis">Yanlış alarm</button>
      ${o.durum !== 'acik' ? `<button class="dug" data-is="olay-durum" data-id="${o.id}" data-durum="acik">Yeniden aç</button>` : ''}
      ${(o.gorevler || []).length ? '' : `<button class="dug ana" data-is="gorev-yeni" data-olay="${o.id}">Görev oluştur</button>`}</div>
    ${(o.gorevler || []).length ? `<p class="not">Bu uyarıya bağlı görev: ${o.gorevler.map(g => `<a href="#/gorevler?id=${g}">#${g}</a>`).join(', ')}.</p>` : ''}
    <p class="not">"Yanlış alarm" işaretlenen uyarı raporlara girmez. Görüntüdeki yüzler motor tarafından gizlenmiştir.</p></aside>`;
  $('.cekmece button')?.focus();
}

/* ------------------------------------------------------------ Görevler */
async function sayfaGorevler(q) {
  const sekme = q.durum || 'acik';
  const d = await api('/api/gorevler?' + donemQ({ durum: sekme === 'hepsi' ? '' : sekme, sorumlu: q.sorumlu, kaynak: q.kaynak, kamera: q.kamera }));
  S.gorevler = Object.fromEntries(d.gorevler.map(g => [g.id, g]));
  const t = d.tepki;
  const sekmeler = [['acik', 'Açık', d.sayilar.acik], ['suruyor', 'Sürüyor', d.sayilar.suruyor], ['kapandi', 'Kapanan', d.sayilar.kapandi], ['hepsi', 'Hepsi']];
  const sec = (ad, etiket, sec_) => `<select class="cip" data-degis="gorev-suzgec" data-alan="${ad}" aria-label="${etiket}"><option value="">${etiket}</option>${sec_.map(([v, a]) => `<option value="${h(v)}" ${q[ad] === v ? 'selected' : ''}>${h(a)}</option>`).join('')}</select>`;
  const satir = g => `<tr class="tik" data-is="gorev-duzenle" data-id="${g.id}">
      <td><b>${h(g.baslik)}</b>${g.otomatik ? ' <span class="rozet gri" title="Uyarıdan kendiliğinden açıldı">oto</span>' : ''}
        <div class="not">${h(g.kamera_ad || kameraAdi(g.kamera) || '')}${g.bolge ? ' · ' + h(g.bolge) : ''} · açıldı ${tarih(g.olusturma)}${g.notlar ? ' · ' + h(g.notlar.slice(0, 60)) : ''}</div></td>
      <td>${g.sorumlu ? h(g.sorumlu) : '<span class="not">atanmadı</span>'}</td>
      <td>${g.son_tarih ? `<span class="rozet ${g.gecikti ? 'kirmizi' : 'gri'}">${g.son_tarih.slice(8, 10)}.${g.son_tarih.slice(5, 7)}</span>` : '<span class="not">–</span>'}</td>
      <td><span class="rozet ${g.durum === 'kapandi' ? 'yesil' : g.durum === 'suruyor' ? 'sari' : 'gri'}">${GDURUM[g.durum]}</span></td>
      <td class="s">${g.durum === 'kapandi' ? sure(g.tepki_sn) : `<span class="not">${sure((Date.now() - new Date(g.olusturma).getTime()) / 1000)}</span>`}</td>
      <td class="s yazdirma" style="white-space:nowrap">${g.durum === 'acik' ? `<button class="dug kucuk" data-is="gorev-durum" data-id="${g.id}" data-durum="suruyor">Başlat</button> ` : ''}${g.durum !== 'kapandi' ? `<button class="dug kucuk ana" data-is="gorev-durum" data-id="${g.id}" data-durum="kapandi">Kapat</button>` : `<button class="dug kucuk" data-is="gorev-durum" data-id="${g.id}" data-durum="acik">Yeniden aç</button>`}</td></tr>`;
  $('#sayfa').innerHTML = ust('Görevler', `personel görevleri · tepki süreleri ${donemKucuk()} için`,
    `<button class="dug" data-is="yazdir">${IKON.yazdir}Yazdır</button><a class="dug" href="/api/disa/gorevler.xlsx?${donemQ()}">${IKON.indir}Excel</a><button class="dug ana" data-is="gorev-yeni">${IKON.arti}Yeni görev</button>`)
    + `<div class="yazdir-baslik"><h2>${h(S.durum.genel.tesis)} · görev listesi · ${new Date().toLocaleString('tr-TR')}</h2></div>`
    + `<div class="izgara dortlu bosluk-alt">
      <div class="kpi"><div class="et">Ortalama tepki</div><div class="deger">${sure(t.ort_sn)}</div><div class="alt">${t.n} kapanan görev</div></div>
      <div class="kpi"><div class="et">Ortanca tepki</div><div class="deger">${sure(t.medyan_sn)}</div><div class="alt">görevlerin yarısı bundan kısa</div></div>
      <div class="kpi"><div class="et">En yavaş %10</div><div class="deger">${sure(t.p90_sn)}</div><div class="alt">ve üstü</div></div>
      <div class="kpi ${d.geciken ? 'kpi-uyari' : ''}"><div class="et">Son tarihi geçen</div><div class="deger">${d.geciken}</div><div class="alt">açık görev</div></div></div>`
    + `<div class="izgara iki"><div class="kart"><div class="kart-bas" style="flex-wrap:wrap"><div class="grup" role="tablist">${sekmeler.map(([v, a, n]) => `<button role="tab" aria-selected="${sekme === v}" class="${sekme === v ? 'secili' : ''}" data-is="gorev-sekme" data-durum="${v}">${a}${n != null ? `<span class="n">${n}</span>` : ''}</button>`).join('')}</div><span style="flex:1"></span>
        ${sec('sorumlu', 'Bütün sorumlular', d.sorumlular.map(s => [s, s]))}${sec('kaynak', 'Bütün kaynaklar', [['otomatik', 'Uyarıdan'], ['elle', 'Elle açılan']])}${sec('kamera', 'Bütün kameralar', S.durum.kameralar.map(k => [k.kod, k.ad]))}</div>
        ${d.gorevler.length ? `<div class="kaydir" style="max-height:640px"><table><thead><tr><th>Görev</th><th>Sorumlu</th><th>Son tarih</th><th>Durum</th><th class="s">${sekme === 'kapandi' ? 'Tepki' : 'Bekliyor'}</th><th class="yazdirma"></th></tr></thead><tbody>${d.gorevler.map(satir).join('')}</tbody></table></div>`
          : `<div class="bos-durum" style="padding:24px"><h3>${sekme === 'acik' ? 'Açık görev yok' : 'Görev yok'}</h3><p>Görev açan uyarılar (boş raf, azalan stok, fiyat farkı, kasa kuyruğu…) görevi kendiliğinden açar ve durum düzelince kapatır. Elle de görev ekleyebilirsiniz.</p></div>`}</div>
      <div><div class="kart bosluk-alt"><div class="kart-bas"><h2>Tepki süresi dağılımı <small>dakika</small></h2></div>${G.yer(G.sutun({ etiketler: t.dagilim.map(k => k.ust == null ? `${k.alt}+` : `${k.alt}-${k.ust}`), seriler: [{ ad: 'Görev', degerler: t.dagilim.map(k => k.n) }], yukseklik: 160, bosMetin: 'Bu dönemde kapanan görev yok.' }))}</div>
        <div class="kart"><div class="kart-bas"><h2>Özelliğe göre ortalama tepki</h2></div>${G.yer(G.yatay(d.kural_tepki.slice(0, 8).map(k => ({ ad: k.ad, alt: `${k.n} görev`, n: Math.round(k.ort_sn / 60) })), { bicim: v => sure(v * 60), bosMetin: 'Kapanan görev yok.', enCok: [...d.kural_tepki.slice(0, 8).map(k => k.ort_sn / 60)].sort((a, b) => b - a)[1] * 1.25 || undefined }))}
          <p class="not" style="margin-bottom:0">Çubuklar okunaklı kalsın diye en uzun süre kırpılır; sayı tamdır.</p></div></div></div>`;
  if (q.id && S.gorevler[q.id]) gorevPenceresi(S.gorevler[q.id]);
}
function gorevPenceresi(g, olay) {
  const o = olay ? S.olaylar[olay] : null;
  g = g || { baslik: o ? `${o.kural_ad}${o.urun_ad ? ' · ' + o.urun_ad : o.bolge ? ' · ' + o.bolge : ''}` : '', aciklama: '', sorumlu: '', son_tarih: '', durum: 'acik', kamera: o?.kamera || '', kural: o?.kural || '', bolge: o?.bolge || '', notlar: '' };
  const sorumlular = [...new Set(Object.values(S.gorevler).map(x => x.sorumlu).filter(Boolean))];
  $('#katman').innerHTML = `<div class="perde"><div class="pencere form" role="dialog" aria-modal="true" aria-label="Görev"><h2>${g.id ? 'Görev #' + g.id : 'Yeni görev'}</h2>
    ${o ? `<div class="not">Uyarı #${o.id} bu göreve bağlanır ve "üstlenildi" olur.</div>` : ''}${g.otomatik ? '<div class="not">Bu görev bir uyarıdan kendiliğinden açıldı; uyarı kapanınca kendiliğinden kapanır.</div>' : ''}
    <label for="g-baslik">Başlık</label><input id="g-baslik" value="${h(g.baslik)}" placeholder="ör. Süt dolabını doldur" maxlength="200">
    <label for="g-aciklama">Açıklama</label><textarea id="g-aciklama" maxlength="4000">${h(g.aciklama || '')}</textarea>
    <div class="satir"><div><label for="g-sorumlu">Sorumlu</label><input id="g-sorumlu" value="${h(g.sorumlu || '')}" list="g-sorumlular" maxlength="80"><datalist id="g-sorumlular">${sorumlular.map(s => `<option value="${h(s)}">`).join('')}</datalist></div>
      <div><label for="g-tarih">Son tarih</label><input id="g-tarih" type="date" value="${h(g.son_tarih || '')}"></div>
      <div><label for="g-durum">Durum</label><select id="g-durum">${Object.entries(GDURUM).map(([v, a]) => `<option value="${v}" ${g.durum === v ? 'selected' : ''}>${a}</option>`).join('')}</select></div></div>
    <label for="g-not">Not</label><textarea id="g-not" placeholder="ne yapıldı" maxlength="4000">${h(g.notlar || '')}</textarea>
    <div class="satir"><div><label for="g-kamera">Kamera</label><select id="g-kamera"><option value="">–</option>${S.durum.kameralar.map(k => `<option value="${h(k.kod)}" ${g.kamera === k.kod ? 'selected' : ''}>${h(k.ad)}</option>`).join('')}</select></div>
      <div><label for="g-kural">İzlenecek özellik</label><select id="g-kural"><option value="">–</option>${S.katalog.kurallar.filter(k => k.olay).map(k => `<option value="${k.kod}" ${g.kural === k.kod ? 'selected' : ''}>${h(k.ad)}</option>`).join('')}</select></div></div>
    ${g.olaylar?.length ? `<p class="not">Bağlı uyarılar: ${g.olaylar.map(x => `<a href="#/uyarilar?id=${x.id}">#${x.id} ${h(x.kural_ad)}</a>`).join(', ')}</p>` : ''}
    <div class="eylemler">${g.id ? `<button class="dug tehlike" data-is="gorev-sil" data-id="${g.id}" style="margin-right:auto">Sil</button>` : ''}<button class="dug" data-is="katman-kapat">Vazgeç</button>
      <button class="dug ana" data-is="gorev-kaydet" data-id="${g.id || ''}" data-olay="${olay || ''}" data-bolge="${h(g.bolge || '')}">Kaydet</button></div></div></div>`;
  $('#g-baslik').focus();
}

/* ------------------------------------------------------------ Kameralar (liste ve işler) */
function isKarti() {
  const i = S.durum.is;
  if (!i) return '<div class="not">Henüz bir iş çalıştırılmadı.</div>';
  const ad = { calisiyor: 'çalışıyor', bitti: 'bitti', hata: 'hata', durduruldu: 'durduruldu' }[i.durum];
  return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap"><b>${h(i.baslik)}</b><span class="rozet ${i.durum === 'calisiyor' ? 'sari' : i.durum === 'hata' ? 'kirmizi' : 'yesil'}">${ad}</span><span class="not">${sure(i.sure)}</span><span style="flex:1"></span>
    ${i.durum === 'calisiyor' && i.tur !== 'ornek-veri' ? `<button class="dug kucuk tehlike" data-is="is-durdur">${i.durduruluyor ? 'Durduruluyor…' : 'Durdur'}</button>` : ''}</div><div class="kayit" id="kayit">${h(i.satirlar.join('\n'))}</div>`;
}
/* Canlı izleme kamera başına ayrı çalışır: her kameranın kendi durumu, durdurma düğmesi ve kaydı vardır. */
function izlemeDurumu(kod) {
  const i = S.durum.izlemeler?.[kod];
  if (!i) return '';
  if (i.durum === 'calisiyor') return `<span class="rozet yesil">${i.durduruluyor ? 'durduruluyor' : 'canlı · ' + h(sure(i.sure))}</span>`;
  if (i.istenen && i.bekleme) return `<span class="rozet ${/Şifre/.test(i.bekleme) ? 'kirmizi' : 'sari'}" title="${h(i.bekleme)}">${/Şifre/.test(i.bekleme) ? 'şifre bekleniyor' : /dışında/.test(i.bekleme) ? 'açılışta başlar' : i.durum === 'hata' ? 'hata · yeniden denenecek' : 'bekliyor'}</span>`;
  if (i.durum === 'hata') return '<span class="rozet kirmizi">hata</span>';
  return '';
}
function izlemeDugmesi(k, gel) {
  const i = S.durum.izlemeler?.[k.kod];
  const baslat = `<button class="dug kucuk ana" data-is="is" data-tur="izle" data-kod="${h(k.kod)}" ${gel ? 'disabled title="Geliştirme kipinde kapalı"' : ''}>İzlemeyi başlat</button>`;
  if (i?.durum === 'calisiyor') return `<button class="dug kucuk tehlike" data-is="izleme-durdur" data-kod="${h(k.kod)}" data-ad="${h(k.ad)}">${i.durduruluyor ? 'Durduruluyor…' : 'İzlemeyi durdur'}</button>`;
  // istenen ama çalışmıyor (şifre bekleniyor, kapanış, hata sonrası): elle başlatılabilir ya da istek kaldırılır
  if (i?.istenen) return `${/Şifre/.test(i.bekleme || '') ? baslat : ''}<button class="dug kucuk" data-is="izleme-durdur" data-kod="${h(k.kod)}" data-ad="${h(k.ad)}" title="Açılışta kendiliğinden başlamasın">Otomatik başlatmayı kapat</button>`;
  return baslat;
}
function izlemeKarti() {
  const liste = Object.entries(S.durum.izlemeler || {});
  if (!liste.length) return '<div class="not">Canlı izlenen kamera yok. Kameranın satırındaki <b>İzlemeyi başlat</b> ile başlatın; her kamera kendi arka plan sürecinde izlenir.</div>';
  const calisan = liste.filter(([, i]) => i.durum === 'calisiyor').length;
  return `<div class="not" style="margin-bottom:8px">${calisan} kamera canlı · en çok ${S.durum.en_cok_canli} · izlenmesi istenenler çalışma saati bitince durur, açılışta kendiliğinden yeniden başlar.</div>`
    + liste.map(([kod, i]) => `<details class="izleme" ${i.durum === 'hata' ? 'open' : ''}><summary><b>${h(kameraAdi(kod))}</b> ${izlemeDurumu(kod) || '<span class="rozet gri">' + h({ bitti: 'durdu', durduruldu: 'durduruldu' }[i.durum] || '–') + '</span>'}</summary>
      ${i.bekleme ? `<div class="not" style="margin:6px 0">${h(i.bekleme)}</div>` : ''}${(i.satirlar || []).length ? `<div class="kayit" style="margin-top:6px;max-height:160px">${h(i.satirlar.join('\n'))}</div>` : ''}</details>`).join('');
}
async function sayfaKameralar() {
  const d = S.durum, gel = d.gelistirme;
  const kam = k => `<tr><td style="width:120px"><a href="#/kamera/${encodeURIComponent(k.kod)}" style="display:block;border-radius:8px;overflow:hidden;background:#0f1115;aspect-ratio:16/9">${k.son_kare || k.referans_karesi || k.ayar_karesi ? `<img src="${h(k.son_kare || k.referans_karesi || k.ayar_karesi)}" alt="" style="width:100%;height:100%;object-fit:cover;display:block">` : ''}</a></td>
    <td><b>${h(k.ad)}</b> ${k.ornek ? `<span class="rozet mor">${k.ornek_video ? 'örnek video' : 'örnek'}</span>` : ''} ${k.eski ? '<span class="rozet sari">veri eski</span>' : ''} <span data-izleme-durum="${h(k.kod)}">${izlemeDurumu(k.kod)}</span><div class="not">${{ rtsp: 'IP kamera / kayıt cihazı', onvif: 'ONVIF', http: 'HTTP akışı', dosya: 'video dosyası' }[k.tur] || k.tur} · ${k.bolge} bölge · ${k.goz} göz · ${k.kural} özellik${k.son_analiz ? ' · son kayıt ' + once(k.son_analiz) : ''}</div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:6px">${k.sifre ?`<input type="password" placeholder="kamera şifresi" autocomplete="off" data-sifre="${h(k.kod)}" aria-label="Kamera şifresi" style="width:120px;border:1px solid var(--cizgi2);border-radius:8px;padding:4px 8px">` : ''}
      ${k.ornek ? '' : `<button class="dug kucuk" data-is="is" data-tur="test" data-kod="${h(k.kod)}">Bağlantıyı dene</button>
      ${k.tur === 'dosya' ? `<button class="dug kucuk ana" data-is="is" data-tur="video" data-kod="${h(k.kod)}" ${gel ? 'disabled title="Geliştirme kipinde kapalı"' : ''}>Videoyu analiz et</button>` : `<span data-izleme-dugme="${h(k.kod)}" style="display:inline-flex;gap:6px">${izlemeDugmesi(k, gel)}</span>`}`}
      <a class="dug kucuk" href="#/kamera/${h(k.kod)}">Düzenle</a><button class="dug kucuk tehlike" data-is="kamera-sil" data-kod="${h(k.kod)}" data-ad="${h(k.ad)}">Sil</button></div></td></tr>`;
  const ov = d.ornek_videolar || [];
  $('#sayfa').innerHTML = ust('Kameralar', 'kameralar, bölgeler, planogram ve analiz işleri',
    (ov.length ? `<button class="dug" data-is="ornek" ${gel ? 'disabled title="Geliştirme kipinde kapalı"' : ''} title="${h(ov.map(o => o.ad).join(', '))}">Örnek videoları çözümle (${ov.length})</button>` : '') + `<a class="dug ana" href="#/kamera/yeni">${IKON.arti}Kamera ekle</a>`)
    + modelUyarisi()
    + `<div class="izgara iki"><div class="kart" id="a-kameralar"><div class="kart-bas"><h2>Kameralar <small>${d.kameralar.length}</small></h2></div>
        ${d.kameralar.length ? `<table>${d.kameralar.map(kam).join('')}</table>` : '<div class="bos-durum" style="padding:22px"><h3>Henüz kamera yok</h3><p>IP kamera, kayıt cihazı (ONVIF ya da RTSP) ya da video dosyası ekleyin. Sonra raf, koridor, kasa ve giriş bölgelerini çizin.</p></div>'}
        <p class="not">Analiz AugeLab Studio'da arka planda çalışır. <b>İzlemeyi başlat</b>: her kamera kendi sürecinde, çalışma saatlerinde izlenir; kapanışta durur, açılışta kendiliğinden başlar. Video dosyası analizi ve diğer işler sırayla, birer birer çalışır. Kamera şifresi diske kaydedilmez.</p></div>
      <div><div class="kart bosluk-alt"><div class="kart-bas"><h2>Canlı izleme</h2></div><div id="izleme-karti">${izlemeKarti()}</div></div>
      <div class="kart"><div class="kart-bas"><h2>İşlem <small>video, örnek videolar, motor işleri</small></h2></div><div id="is-karti">${isKarti()}</div></div></div></div>`;
  const k = $('#kayit'); if (k) k.scrollTop = k.scrollHeight;
}
function karePenceresi(sonuc) {
  $('#katman').innerHTML = `<div class="perde"><div class="pencere" style="width:min(820px,100%)"><h2 style="margin:0 0 10px">Bağlantı kuruldu</h2>
    <img src="${h(sonuc.kare)}" alt="" style="width:100%;border-radius:12px;display:block;background:#0f1115">
    <div class="eylemler"><button class="dug" data-is="katman-kapat">Kapat</button><a class="dug ana" href="#/kamera/${h(sonuc.kod)}">Bölge çiz</a></div></div></div>`;
}

/* ------------------------------------------------------------ Entegrasyonlar */
async function sayfaEntegrasyonlar() {
  const d = S.durum, g = d.genel;
  $('#sayfa').innerHTML = ust('Entegrasyonlar', 'uyarıları başka sistemlere iletin, verileri okutun', `<button class="dug ana" data-is="baglanti-pencere" data-i="-1">${IKON.arti}Çıkış ekle</button>`)
    + `<div class="kart" id="e-cikislar"><div class="kart-bas"><h2>Çıkışlar <small>PLC, haberleşme, bildirim</small></h2></div>
        ${g.baglantilar.length ? `<table>${g.baglantilar.map((b, i) => `<tr><td><b>${h(b.ad)}</b> ${b.acik === false ? '<span class="rozet gri">kapalı</span>' : ''}<div class="not">${h(S.katalog.baglanti_turleri[b.tur] || b.tur)} · ${h(baglantiOzeti(b))}</div></td>
          <td style="white-space:nowrap;text-align:right"><button class="dug kucuk" data-is="baglanti-dene" data-i="${i}">Dene</button> <button class="dug kucuk" data-is="baglanti-pencere" data-i="${i}">Düzenle</button> <button class="dug kucuk tehlike" data-is="baglanti-sil" data-i="${i}">Sil</button></td></tr>`).join('')}</table>` : '<div class="not">Henüz çıkış yok. Yeni uyarılar PLC\'ye (Modbus TCP, OPC UA), MQTT sunucusuna, webhook adresine, Slack / Teams kanalına ya da e-postaya iletilebilir.</div>'}
        <p class="not" style="margin-bottom:0">Çıkışlar uyarı başladığında tetiklenir. Örnek veriler hiçbir çıkışa gönderilmez. Görüntü gönderilmez; şifreler kaydedilmez, ortam değişkeninden okunur.</p></div>
    <div class="kart" style="margin-top:14px"><div class="kart-bas" style="flex-wrap:wrap"><h2>Dış sistemler için API <small>yalnızca okuma</small></h2>
        <label class="cip" style="cursor:pointer"><input type="checkbox" data-degis="ag-erisimi" ${g.ag_erisimi ? 'checked' : ''}> Ağdaki sistemler anahtarla okuyabilsin</label>
        ${g.api_anahtari ? '<button class="dug kucuk" data-is="anahtar-yenile">Anahtarı yenile</button>' : ''}</div>
      <table>${Object.entries(S.katalog.api).map(([u, a]) => `<tr><td style="font-family:var(--mono);font-size:12.5px;white-space:nowrap">GET ${h(u)}</td><td class="not">${h(a)}</td></tr>`).join('')}</table>
      <p class="not">Bu bilgisayardan anahtarsız okunur: <code>http://127.0.0.1:${d.dinlenen.port}/api/v1/raflar</code>. ${g.ag_erisimi ? (d.dinlenen.adres === '0.0.0.0'
        ? `Ağdan: ${d.dinlenen.ag.map(ip => `<code>http://${h(ip)}:${d.dinlenen.port}/api/v1/…</code>`).join(', ') || 'bu bilgisayarın ağ adresi'} · her istekte <code>X-API-Key</code> başlığı gerekir. Arayüz ve ayarlar ağdan açılmaz. Bağlantı şifrelenmez (HTTP): yalnızca güvendiğiniz yerel ağda açın.`
        : '<b>Ağ erişimi kaydedildi; geçerli olması için programı kapatıp yeniden açın.</b>') : (d.dinlenen.adres === '0.0.0.0' ? '<b>Ağ erişimi kapatıldı:</b> ağdan gelen istekler reddediliyor; program yeniden açılana kadar ağ arayüzlerini dinlemeyi sürdürür.' : 'Ağ erişimi kapalı: program yalnızca bu bilgisayarı dinler.')}</p>
      ${g.ag_erisimi && g.api_anahtari ? `<div class="form"><label>API anahtarı (Power BI, Grafana, SCADA gibi sistemlere yazılır; başkasıyla paylaşmayın)</label><input readonly value="${h(g.api_anahtari)}" onfocus="this.select()" style="font-family:var(--mono)"></div>` : ''}</div>`;
}
const B_ORTAK = [['kullanici', 'Kullanıcı adı (gerekmiyorsa boş)', ''], ['sifre_degiskeni', 'Şifrenin okunacağı ortam değişkeninin adı', 'ör. RAF_SIFRE']];
const B_ALAN = {
  webhook: [['adres', 'Adres (uyarı JSON olarak POST edilir)', 'https://…']],
  slack: [['adres', 'Gelen webhook adresi', 'https://hooks.slack.com/…']],
  teams: [['adres', 'Gelen webhook adresi', 'https://…']],
  mqtt: [['sunucu', 'MQTT sunucusu', 'ör. 10.0.0.5'], ['port', 'Port', 1883, 'sayi'], ['konu', 'Konu', 'raf/olay'], ['qos', 'QoS (0 ya da 1)', 0, 'sayi'], ...B_ORTAK],
  modbus: [['sunucu', 'PLC adresi', 'ör. 10.0.0.20'], ['port', 'Port', 502, 'sayi'], ['birim', 'Birim (slave) no', 1, 'sayi'],
    ['hedef', 'Yazılacak yer', 'bobin', 'secim', [['bobin', 'Bobin / coil (işlev 5)'], ['yazmac', 'Tutma yazmacı / holding register (işlev 6)']]],
    ['adres', 'Adres (0\'dan başlar; 40001 → 0)', 0, 'sayi'], ['deger', 'Yazılacak değer (bobinde 1 = açık)', 1, 'sayi'], ['darbe_sn', 'Kaç saniye sonra sıfırlansın (0 = sıfırlama)', 5, 'sayi']],
  opcua: [['adres', 'Sunucu adresi', 'opc.tcp://10.0.0.20:4840'], ['dugum', 'Düğüm (node)', 'ns=2;s=RafAlarm'], ['deger', 'Yazılacak değer', 'true'], ['darbe_sn', 'Kaç saniye sonra sıfırlansın (0 = sıfırlama)', 5, 'sayi'], ...B_ORTAK],
  eposta: [['sunucu', 'SMTP sunucusu', 'smtp.ornek.com'], ['port', 'Port', 587, 'sayi'], ['gonderen', 'Gönderen adres', ''], ['alicilar', 'Alıcılar (virgülle ayırın)', '', 'liste'], ...B_ORTAK],
};
function baglantiOzeti(b) {
  const hedef = { webhook: b.adres, slack: b.adres, teams: b.adres, mqtt: `${b.sunucu}:${b.port} · ${b.konu}`, modbus: `${b.sunucu}:${b.port} · ${b.hedef === 'yazmac' ? 'yazmaç' : 'bobin'} ${b.adres}${b.darbe_sn ? ` · ${b.darbe_sn} sn darbe` : ''}`,
    opcua: `${b.adres} · ${b.dugum}`, eposta: `${b.sunucu} → ${(b.alicilar || []).join(', ')}` }[b.tur] || '';
  const suzgec = [b.en_az_puan ? `öncelik ≥ ${b.en_az_puan}` : '', b.yalniz_ciddi ? 'yalnız kritik' : '', (b.kategoriler || []).length ? b.kategoriler.map(k => S.katalog.kategoriler[k] || k).join(', ') : '',
    (b.kameralar || []).length ? `${b.kameralar.length} kamera` : ''].filter(Boolean).join(' · ');
  return hedef + (suzgec ? ' · ' + suzgec : ' · bütün uyarılar');
}
function baglantiPenceresi(i, tur) {
  const eski = i >= 0 ? S.durum.genel.baglantilar[i] : null;
  const b = eski && (!tur || tur === eski.tur) ? eski : { tur: tur || 'webhook', ad: '', acik: true, en_az_puan: 0, yalniz_ciddi: false, kategoriler: [], kameralar: [] };
  const alan = ([ad, etiket, varsayilan, tip, secenekler]) => {
    const deger = b[ad] ?? (tip === 'sayi' || tip === 'secim' ? varsayilan : '');
    if (tip === 'secim') return `<div><label>${etiket}</label><select data-b="${ad}">${secenekler.map(([v, a]) => `<option value="${v}" ${deger === v ? 'selected' : ''}>${a}</option>`).join('')}</select></div>`;
    return `<div><label>${etiket}</label><input data-b="${ad}" data-tip="${tip || ''}" ${tip === 'sayi' ? 'type="number"' : ''} value="${h(Array.isArray(deger) ? deger.join(', ') : deger)}" placeholder="${h(tip === 'sayi' ? '' : varsayilan)}" autocomplete="off"></div>`;
  };
  const isaretler = (ad, secenekler) => `<div style="display:flex;gap:6px;flex-wrap:wrap">${secenekler.map(([v, a]) => `<label class="cip" style="cursor:pointer;margin:0"><input type="checkbox" data-b-liste="${ad}" value="${h(v)}" ${(b[ad] || []).includes(v) ? 'checked' : ''}>${h(a)}</label>`).join('')}</div>`;
  $('#katman').innerHTML = `<div class="perde"><div class="pencere form" style="width:min(640px,100%)" role="dialog" aria-modal="true"><h2>${eski ? 'Çıkışı düzenle' : 'Çıkış ekle'}</h2>
    <div class="satir"><div><label>Tür</label><select data-degis="baglanti-tur" data-i="${i}">${Object.entries(S.katalog.baglanti_turleri).map(([t, a]) => `<option value="${t}" ${b.tur === t ? 'selected' : ''}>${h(a)}</option>`).join('')}</select></div>
      <div><label>Ad</label><input data-b="ad" value="${h(b.ad || '')}" placeholder="ör. Mağaza müdürüne bildirim"></div></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:0 8px">${(B_ALAN[b.tur] || []).map(alan).join('')}</div>
    <div class="et" style="margin-top:14px">Hangi uyarılar iletilsin</div>
    <div class="satir"><div><label>En az öncelik (0-25)</label><input data-b="en_az_puan" data-tip="sayi" type="number" min="0" max="25" value="${b.en_az_puan ?? 0}"></div>
      <div><label>&nbsp;</label><label class="cip" style="cursor:pointer;margin:0"><input type="checkbox" data-b-kutu="yalniz_ciddi" ${b.yalniz_ciddi ? 'checked' : ''}> Yalnızca kritik</label></div>
      <div><label>&nbsp;</label><label class="cip" style="cursor:pointer;margin:0"><input type="checkbox" data-b-kutu="acik" ${b.acik !== false ? 'checked' : ''}> Açık</label></div></div>
    <label>Kategoriler (hiçbiri seçilmezse hepsi)</label>${isaretler('kategoriler', Object.entries(S.katalog.kategoriler))}
    <label>Kameralar (hiçbiri seçilmezse hepsi)</label>${isaretler('kameralar', S.durum.kameralar.map(k => [k.kod, k.ad])) || '<span class="not">Kamera yok.</span>'}
    <div class="eylemler"><button class="dug" data-is="katman-kapat">Vazgeç</button><button class="dug" data-is="baglanti-dene" data-i="form">Deneme iletisi gönder</button>
      <button class="dug ana" data-is="baglanti-kaydet" data-i="${i}">Kaydet</button></div></div></div>`;
}
function baglantiFormu() {
  const b = { tur: $('[data-degis="baglanti-tur"]').value };
  $$('[data-b]').forEach(e => { const tip = e.dataset.tip; b[e.dataset.b] = tip === 'sayi' ? (e.value === '' ? undefined : +e.value) : tip === 'liste' ? e.value.split(',').map(x => x.trim()).filter(Boolean) : e.value.trim(); });
  $$('[data-b-kutu]').forEach(e => { b[e.dataset.bKutu] = e.checked; });
  for (const ad of ['kategoriler', 'kameralar']) b[ad] = $$(`[data-b-liste="${ad}"]`).filter(e => e.checked).map(e => e.value);
  return b;
}

/* ------------------------------------------------------------ Ayarlar */
const OZELLIK_RENGI = { hazir: 'yesil', sinirli: 'sari', deneysel: 'gri' };
function ozellikDurumu(k) {
  if (k.model_eksik) return '<span class="rozet kirmizi">Model yok</span>';
  if (k.durum === 'yok') return '<span class="rozet gri">Kapalı</span>';
  return `<span class="rozet ${OZELLIK_RENGI[k.durum] || 'gri'}">${h(S.katalog.durumlar?.[k.durum] || k.durum)}</span>`;
}
async function sayfaAyarlar() {
  const d = S.durum, g = d.genel, K = S.katalog, ov = d.ornek_veri || {};
  const c = g.calisma || { bas: '08:00', bit: '22:00' };
  const ozellik = K.kurallar.length ? Object.entries(K.kategoriler).map(([kat, ad]) => { const rs = K.kurallar.filter(r => r.kategori === kat); return rs.length ? `<div class="et" style="margin:12px 0 2px">${h(ad)}</div>` + rs.map(r => `<div class="kural"><div style="flex:1"><div class="ad">${h(r.ad)}</div><div class="ac">${h(r.aciklama || '')}</div></div><div>${ozellikDurumu(r)}</div></div>`).join('') : ''; }).join('')
    : '<div class="not">Analiz motorunun özellik listesi henüz boş. Motor güncellenince her özellik burada durumuyla görünür: hazır, sınırlı ya da deneysel.</div>';
  $('#sayfa').innerHTML = ust('Ayarlar', `Raf Kamera ${h(d.surum)} · AugeLab Studio ${d.gelistirme ? 'kullanılmıyor (geliştirme kipi)' : d.studio?.bagli ? h(d.studio.surum || '') + ' hazır (arka planda)' : 'hazır değil'}`,
    `${d.gelistirme ? '' : '<button class="dug" data-is="sihirbaz-ac">Kurulum sihirbazı</button>'}<button class="dug" data-is="klasor">Veri klasörü</button><button class="dug tehlike" data-is="kapat">Programı kapat</button>`)
    + modelUyarisi()
    + `<div class="izgara iki"><div>
      <div class="kart form bosluk-alt" id="a-magaza"><div class="kart-bas"><h2>Mağaza</h2></div>
        <div class="satir"><div><label for="a-tesis">Mağaza adı</label><input id="a-tesis" value="${h(g.tesis)}" maxlength="80"></div><div><label for="a-sube">Şube</label><input id="a-sube" value="${h(g.sube || '')}" maxlength="60" placeholder="isteğe bağlı"></div><div style="flex:.4"><label for="a-para">Para birimi</label><input id="a-para" value="${h(g.para_birimi || '₺')}" maxlength="4"></div></div>
        <label for="a-adres">Adres</label><input id="a-adres" value="${h(g.adres || '')}" maxlength="200" placeholder="isteğe bağlı; raporlarda görünür">
        <div class="satir"><div><label for="a-cbas">Açılış</label><input id="a-cbas" type="time" value="${h(c.bas)}"></div><div><label for="a-cbit">Kapanış</label><input id="a-cbit" type="time" value="${h(c.bit)}"></div></div>
        <p class="not" style="margin:6px 0 0">Canlı analiz yalnızca çalışma saatlerinde yapılır; kayıp satış, boş raf süresi ve tepki süreleri çalışma saatlerine göre hesaplanır.</p>
        <label>Vardiyalar (ad, başlangıç, bitiş)</label><div id="vardiyalar">${g.vardiyalar.map(v => `<div class="satir" style="margin-bottom:6px"><input value="${h(v.ad)}" aria-label="Vardiya adı"><input type="time" value="${v.bas}" aria-label="Başlangıç"><input type="time" value="${v.bit}" aria-label="Bitiş"></div>`).join('')}</div>
        <div class="satir"><div><label for="a-saklama">Kayıtlar kaç gün tutulsun</label><input id="a-saklama" type="number" min="7" max="3650" value="${g.saklama_gun}"></div><div><label for="a-klip">Klip ve kareler kaç gün</label><input id="a-klip" type="number" min="1" max="3650" value="${g.klip_gun}"></div></div>
        <p class="not" style="margin:6px 0 0">Süresi dolan uyarılar, ölçümler ve klipler kendiliğinden silinir (görevlere bağlı uyarılar ve görevler kalır).</p>
        <div class="eylemler" style="justify-content:flex-start"><button class="dug ana" data-is="genel-kaydet">Kaydet</button><button class="dug" data-is="temizle">Şimdi temizle</button></div></div>
      <div class="kart bosluk-alt" id="a-ornek"><div class="kart-bas"><h2>Örnek veriler</h2>${ov.yuklu ? '<span class="rozet mor">Yüklü</span>' : ''}</div>
        ${ov.yuklu ? `<p style="margin:0 0 8px">Örnek veriler yüklü${ov.zaman ? ' (' + tarih(ov.zaman) + ')' : ''}: ${ov.kameralar.length} kamera, ${sayi(ov.sayilar?.olay)} uyarı, ${sayi(ov.sayilar?.gorev)} görev. Yüklü oldukça üst çubukta <span class="rozet mor">Örnek veriler</span> işareti görünür; kamera listesinde ve uyarı ayrıntısında da işaretlidir.</p>
          <button class="dug tehlike" data-is="ornek-kaldir">Örnek verileri kaldır</button>`
        : `<p style="margin:0 0 8px">Küçük bir marketin iki haftalık örnek verisini yükleyip bütün ekranları deneyin: iki raf kamerası, koridor, kasa ve giriş; 31 ürün.</p>
          <button class="dug ana" data-is="ornek-yukle">Örnek verilerle dene</button>`}
        <p class="not">Örnek veriler ayrı işaretlenir; kaldırmak yalnızca onları siler, gerçek kayıtlarınıza dokunmaz. Örnek uyarılar hiçbir çıkışa gönderilmez.</p></div>
      <div class="kart" id="a-gizlilik"><div class="kart-bas"><h2>Gizlilik</h2></div>
        <ul style="margin:0;padding-left:18px;line-height:1.7">
          <li>Görüntüler bu bilgisayarda işlenir; internete gönderilmez.</li>
          <li>Yüz tanıma yoktur. Görüntülerdeki başlar kayıttan önce pikselleştirilir; panel yalnızca bu görüntüleri gösterir.</li>
          <li>Kişi kaydı ve kimlik tutulmaz. Yaş grubu ve cinsiyet gövde görünümünden tahmin edilir ve yalnızca toplu sayı olarak saklanır.</li>
          <li>Müşteri hareketleri (durma, uzanma, alma) kimliksiz sayılardır.</li>
          <li>Kamera şifreleri kaydedilmez. Ağdan erişim kapalıdır; açılırsa yalnızca anahtarla okuma yapılır.</li></ul></div></div>
      <div class="kart" id="a-ozellikler"><div class="kart-bas"><h2>Özellikler <small>${K.kurallar.length}</small></h2></div>
        <p class="not" style="margin-top:0"><span class="rozet yesil">Hazır</span> sınandı · <span class="rozet sari">Sınırlı</span> belirli koşullarda güvenilir · <span class="rozet gri">Deneysel</span> sonuçlar dikkatle okunmalı</p>${ozellik}</div></div>`;
}

/* ------------------------------------------------------------ tıklamalar ve değişiklikler */
async function ornekYukle() {
  if (!await onayla('Örnek veriler yüklensin mi?', 'Küçük bir marketin iki haftalık örnek verisi yüklenir (yaklaşık bir dakika sürer). Örnek veriler ayrı tutulur ve tek tıkla kaldırılır.', { tamam: 'Yükle' })) return;
  await api('/api/ornek-veri/yukle', {});
  await durumAl();
  $('#katman').innerHTML = `<div class="perde"><div class="pencere" role="dialog" aria-modal="true"><h2>Örnek veriler yükleniyor</h2><div id="ornek-is">${isKarti()}</div></div></div>`;
  const izle = setInterval(async () => {
    await durumAl().catch(() => null);
    const i = S.durum.is, k = $('#ornek-is');
    if (k) { k.innerHTML = isKarti(); const y = $('#kayit'); if (y) y.scrollTop = y.scrollHeight; }
    if (i?.tur === 'ornek-veri' && i.durum !== 'calisiyor') {
      clearInterval(izle);
      $('#katman').innerHTML = '';
      if (i.durum === 'bitti') { bildir('Örnek veriler yüklendi.'); S.katalog = await api('/api/katalog'); git(''); ciz(); } else bildir('Örnek veriler yüklenemedi: ' + (i.satirlar.slice(-1)[0] || ''), true);
    }
  }, 1200);
}
const IS = {
  'yenile': () => ciz(),
  'donem-uygula': () => {
    const a = $('#d-bas').value, b = $('#d-bit').value;
    if (!a || !b) return bildir('İki tarihi de seçin.', true);
    S.donem = a <= b ? { bas: a, bit: b } : { bas: b, bit: a }; sakla('raf-donem', S.donem); ustbarCiz(); ciz();
  },
  'zil': () => { ZIL.acik = !ZIL.acik; zilPaneli(); },
  'yazdir': () => window.print(),
  'ornek-yukle': ornekYukle,
  'ornek-kaldir': async () => {
    if (!await onayla('Örnek veriler kaldırılsın mı?', 'Örnek kameralar, ürünler, uyarılar, görevler ve ölçümler silinir. Gerçek kayıtlarınız silinmez. Bu geri alınamaz.', { tamam: 'Kaldır', tehlike: true })) return;
    const r = await api('/api/ornek-veri/kaldir', {});
    bildir(`Örnek veriler kaldırıldı (${r.kameralar.length} kamera, ${r.urunler} ürün).`);
    S.katalog = await api('/api/katalog'); await durumAl(); ciz();
  },
  'studio-kurulum': async e => {
    if (e.dataset.tur === 'kur' && !await onayla('AugeLab Studio kurulsun mu?', 'Resmî AugeLab Studio kurucusu indirilip çalıştırılır.', { tamam: 'İndir ve kur' })) return;
    await api('/api/studio/' + e.dataset.tur, {}); await durumAl(); await ciz();
  },
  'model-indir': async () => { await api('/api/model/indir', {}); await durumAl(); shCiz(); },
  'sihirbaz-ac': () => sihirbazAc(),
  'sihirbaz-kapat': () => sihirbazKapat(),
  'hesap-ac': () => { const url = S.durum?.hesap_url || 'https://account.augelab.com/'; if (!window.open(url, 'augelab-hesap', 'width=560,height=820')) window.open(url, '_blank'); },
  'katman-kapat': () => {
    $('#katman').innerHTML = '';
    const k = konum();
    for (const a of ['id', 'goz']) if (k.q[a]) delete k.q[a];
    sorguDegistir(k.q);
  },
  'olay-ac': async e => {
    const k = konum(), o = S.olaylar[e.dataset.id];
    ZIL.acik = false; $('#zil-panel').innerHTML = '';
    if (k.yol === 'uyarilar') { sorguDegistir({ ...k.q, id: e.dataset.id }); $$('.uyari.secili').forEach(x => x.classList.remove('secili')); e.classList.add('secili'); }
    olayCekmecesi(o || await api('/api/olay/' + e.dataset.id));
  },
  'olay-durum': async e => {
    await api('/api/olay/durum', { id: +e.dataset.id, durum: e.dataset.durum, ustlenen: $('#o-ustlenen')?.value || null, not: $('#o-not')?.value ?? null });
    bildir('Uyarı: ' + DURUM[e.dataset.durum].toLowerCase()); IS['katman-kapat'](); await durumAl(); ciz();
  },
  'suzgec-temizle': () => git('uyarilar'),
  'uyari-hepsi': () => git('uyarilar', { ...konum().q, hepsi: 1 }),
  'gorev-yeni': e => gorevPenceresi(null, e.dataset.olay),
  'gorev-duzenle': e => { if (S.gorevler[e.dataset.id]) gorevPenceresi(S.gorevler[e.dataset.id]); },
  'gorev-sekme': e => { const q = konum().q; q.durum = e.dataset.durum; git('gorevler', q); },
  'gorev-kaydet': async e => {
    const baslik = $('#g-baslik').value.trim();
    if (!baslik) { $('#g-baslik').classList.add('hata-alan'); $('#g-baslik').focus(); return bildir('Görevin başlığını yazın.', true); }
    const g = { id: e.dataset.id ? +e.dataset.id : undefined, baslik, aciklama: $('#g-aciklama').value, sorumlu: $('#g-sorumlu').value, son_tarih: $('#g-tarih').value,
      durum: $('#g-durum').value, notlar: $('#g-not').value, kamera: $('#g-kamera').value, kural: $('#g-kural').value, bolge: e.dataset.bolge, olaylar: e.dataset.olay ? [+e.dataset.olay] : [] };
    await api('/api/gorev', g); $('#katman').innerHTML = ''; bildir('Görev kaydedildi.'); await durumAl();
    if (konum().yol === 'gorevler') { sorguDegistir({ ...konum().q, id: undefined }); ciz(); } else git('gorevler');
  },
  'gorev-durum': async e => {
    const g = S.gorevler[e.dataset.id];
    await api('/api/gorev', { ...g, olaylar: [], durum: e.dataset.durum });
    bildir(`Görev: ${GDURUM[e.dataset.durum].toLowerCase()}.`); await durumAl(); ciz();
  },
  'gorev-sil': async e => {
    if (!await onayla('Görev silinsin mi?', 'Bağlı uyarılar silinmez. Bu geri alınamaz.', { tamam: 'Sil', tehlike: true })) return;
    await api('/api/gorev/sil', { id: +e.dataset.id }); $('#katman').innerHTML = ''; await durumAl(); ciz();
  },
  'is': async e => {
    const sifre = document.querySelector(`[data-sifre="${e.dataset.kod}"]`);
    const r = await api('/api/is/' + e.dataset.tur, { kod: e.dataset.kod, sifre: sifre ? sifre.value : undefined });
    if (r.ileti) bildir(r.ileti);
    await durumAl(); ciz();
  },
  'is-durdur': async () => { await api('/api/is/durdur', {}); await durumAl(); ciz(); },
  'izleme-durdur': async e => {
    if (!await onayla(`${e.dataset.ad}: izleme durdurulsun mu?`, 'Kamera artık izlenmez ve açılışta kendiliğinden başlamaz. Yeniden başlatmak için “İzlemeyi başlat”a basın.', { tamam: 'Durdur', tehlike: true })) return;
    await api('/api/izleme/durdur', { kod: e.dataset.kod }); bildir('İzleme durduruluyor.'); await durumAl(); ciz();
  },
  'ornek': async () => {
    const ov = S.durum.ornek_videolar || [];
    if (!await onayla('Örnek videolar çözümlensin mi?', `${ov.length} örnek video (${ov.map(o => o.ad).join(', ')}) kamera olarak kurulur ve AugeLab Studio'da sırayla baştan sona analiz edilir. Önceki çözümlemenin sonuçları silinir.`, { tamam: 'Çözümle' })) return;
    await api('/api/is/ornek', {}); await durumAl(); git('kameralar'); ciz();
  },
  'kamera-sil': async e => {
    if (!await onayla(`"${e.dataset.ad}" silinsin mi?`, 'Kameranın ayarı, bölgeleri, planogramı, uyarıları, ölçümleri ve klipleri silinir. Bu geri alınamaz.', { tamam: 'Sil', tehlike: true })) return;
    await api('/api/ayar/sil', { kod: e.dataset.kod }); await durumAl(); ciz();
  },
  'klasor': () => api('/api/klasor', {}),
  'kapat': async () => {
    if (!await onayla('Program kapatılsın mı?', 'İzleme sürüyorsa durur. Panel yeniden açılana kadar uyarı gelmez.', { tamam: 'Kapat', tehlike: true })) return;
    await api('/api/kapat', {}); document.body.innerHTML = '<div style="padding:40px;font:16px Segoe UI">Raf Kamera kapatıldı. Bu sekmeyi kapatabilirsiniz.</div>';
  },
  'genel-kaydet': async () => {
    const vardiyalar = $$('#vardiyalar .satir').map(s => { const [a, b, c] = s.querySelectorAll('input'); return { ad: a.value.trim(), bas: b.value, bit: c.value }; });
    if (vardiyalar.some(v => !v.ad || !v.bas || !v.bit)) return bildir('Her vardiyanın adını, başlangıcını ve bitişini yazın.', true);
    await api('/api/genel', { tesis: $('#a-tesis').value, sube: $('#a-sube').value, adres: $('#a-adres').value, para_birimi: $('#a-para').value,
      calisma: { bas: $('#a-cbas').value, bit: $('#a-cbit').value }, saklama_gun: $('#a-saklama').value, klip_gun: $('#a-klip').value, vardiyalar });
    bildir('Ayarlar kaydedildi.'); await durumAl(); ustbarCiz();
  },
  'temizle': async () => {
    if (!await onayla('Eski kayıtlar silinsin mi?', `Saklama süresini (${S.durum.genel.saklama_gun} gün; klipler ${S.durum.genel.klip_gun} gün) geçen kayıtlar silinir. Bu geri alınamaz.`, { tamam: 'Temizle', tehlike: true })) return;
    const r = await api('/api/temizle', {}); bildir(`${r.satir} kayıt, ${r.dosya} dosya silindi.`);
  },
  'baglanti-pencere': e => baglantiPenceresi(+e.dataset.i),
  'baglanti-kaydet': async e => {
    const liste = [...S.durum.genel.baglantilar], i = +e.dataset.i, b = baglantiFormu();
    if (i >= 0) liste[i] = b; else liste.push(b);
    await api('/api/genel', { baglantilar: liste }); $('#katman').innerHTML = ''; bildir('Çıkış kaydedildi.'); await durumAl(); ciz();
  },
  'baglanti-sil': async e => {
    const liste = [...S.durum.genel.baglantilar];
    if (!await onayla(`"${liste[+e.dataset.i].ad}" çıkışı silinsin mi?`, 'Bu çıkışa artık uyarı gönderilmez.', { tamam: 'Sil', tehlike: true })) return;
    liste.splice(+e.dataset.i, 1); await api('/api/genel', { baglantilar: liste }); await durumAl(); ciz();
  },
  'baglanti-dene': async e => {
    const b = e.dataset.i === 'form' ? baglantiFormu() : S.durum.genel.baglantilar[+e.dataset.i];
    bildir('Deneme iletisi gönderiliyor…');
    const r = await api('/api/baglanti/dene', { baglanti: b });
    bildir(r.tamam ? `${b.ad || 'Çıkış'}: ${r.mesaj}` : `Gönderilemedi: ${r.mesaj}`, !r.tamam);
  },
  'anahtar-yenile': async () => {
    if (!await onayla('Yeni anahtar üretilsin mi?', 'Eski anahtarı kullanan sistemler okuyamaz.', { tamam: 'Yenile', tehlike: true })) return;
    await api('/api/genel', { anahtar_yenile: true }); await durumAl(); ciz();
  },
};
document.addEventListener('click', async ev => {
  const a = ev.target.closest('[data-ara]');
  if (a) { ev.preventDefault(); aramaGit(ARA.sonuc[+a.dataset.ara]); return; }
  if (ZIL.acik && !ev.target.closest('#zil-panel') && !ev.target.closest('[data-is="zil"]')) { ZIL.acik = false; $('#zil-panel').innerHTML = ''; }
  if (!ev.target.closest('.arama')) { const s = $('#ara-sonuc'); if (s) s.innerHTML = ''; }
  const e = ev.target.closest('[data-is]');
  if (e && IS[e.dataset.is]) {
    if (e.tagName !== 'INPUT') ev.preventDefault();
    if (e.disabled) return;
    try { await IS[e.dataset.is](e, ev); } catch (x) { bildir(x.message, true); }
  }
});
document.addEventListener('change', ev => {
  const e = ev.target, d = e.dataset.degis;
  if (d === 'donem') donemSec(e.value);
  else if (d === 'suzgec') { const k = konum(); if (e.value) k.q[e.dataset.alan] = e.value; else delete k.q[e.dataset.alan]; delete k.q.id; git('uyarilar', k.q); }
  else if (d === 'gorev-suzgec') { const k = konum(); if (e.value) k.q[e.dataset.alan] = e.value; else delete k.q[e.dataset.alan]; git('gorevler', k.q); }
  else if (d === 'baglanti-tur') baglantiPenceresi(+e.dataset.i, e.value);
  else if (d === 'ag-erisimi') api('/api/genel', { ag_erisimi: e.checked }).then(durumAl).then(ciz).catch(x => bildir(x.message, true));
  else if (d === 'zil-ses') { ZIL.ses = e.checked; sakla('raf-siren', ZIL.ses ? '1' : '0'); if (ZIL.ses) sirenCal(0.4); }
  else if (DEGIS[d]) DEGIS[d](e, ev);
});
const DEGIS = {};
document.addEventListener('input', ev => {
  if (ev.target.id !== 'ara') return;
  clearTimeout(ARA.zaman);
  const q = ev.target.value.trim();
  if (q.length < 2) { ARA.sonuc = []; $('#ara-sonuc').innerHTML = ''; return; }
  ARA.zaman = setTimeout(async () => { try { ARA.sonuc = (await api('/api/ara?q=' + encodeURIComponent(q))).sonuclar; ARA.i = -1; aramaCiz(); } catch (x) { /* kapanmış olabilir */ } }, 180);
});
document.addEventListener('keydown', ev => {
  if (ev.target.id === 'ara' && ARA.sonuc.length) {
    if (ev.key === 'ArrowDown') { ARA.i = Math.min(ARA.sonuc.length - 1, ARA.i + 1); aramaCiz(); ev.preventDefault(); }
    else if (ev.key === 'ArrowUp') { ARA.i = Math.max(0, ARA.i - 1); aramaCiz(); ev.preventDefault(); }
    else if (ev.key === 'Enter') { aramaGit(ARA.sonuc[Math.max(0, ARA.i)]); ev.preventDefault(); }
    else if (ev.key === 'Escape') { $('#ara-sonuc').innerHTML = ''; }
    return;
  }
  if (ev.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '') && !document.getElementById('rehber')) { ev.preventDefault(); $('#ara')?.focus(); return; }
  if (ev.key === 'Escape') {
    if (ZIL.acik) { ZIL.acik = false; $('#zil-panel').innerHTML = ''; return; }
    if ($('#katman').innerHTML && !document.querySelector('.perde [data-c]')) IS['katman-kapat']();
  }
});

/* ------------------------------------------------------------ yönlendirme ve yoklama */
let durumIstegi = null;
function durumAl() {
  if (!durumIstegi) durumIstegi = durumuYenile().finally(() => { durumIstegi = null; });
  return durumIstegi;
}
const acikImza = () => (S.durum?.kameralar || []).map(k => `${k.kod}:${k.acik}:${k.suruyor}`).join(',') + '|' + (S.durum?.son_olay || 0);
async function durumuYenile() {
  const modelEksikti = S.durum?.model_indirme?.eksik;
  S.durum = await api('/api/durum');
  S.durum.acik_gorev = S.durum.acik_gorev ?? null;
  rayCiz();
  studioOtoDene(S.durum);
  $$('[data-studio-kurulum]').forEach(e => { e.outerHTML = studioUyarisi(); });
  $$('[data-model-indirme]').forEach(e => { e.outerHTML = modelIndirmeSeridi(); });
  if (modelEksikti && !S.durum.model_indirme?.eksik) { S.katalog = await api('/api/katalog'); bildir('Modeller indirildi ve doğrulandı.'); }
  sihirbazIzle();
}
async function ciz(sessiz = false) {
  const { yol, q } = konum();
  const no = ++S.sayfaNo;
  rayCiz();
  S.acikImza = acikImza();
  if (!sessiz) {
    if (!q.id && !q.goz) $('#katman').innerHTML = '';
    $('#sayfa').innerHTML = yukleniyor();
  }
  if (!document.querySelector('#katman .cekmece')) G.temizle();  // eski grafiklerin çizicileri bırakılır (çekmecedekiler kalır)
  const SAYFA = { '': sayfaGenel, raflar: sayfaRaflar, urunler: sayfaUrunler, musteri: sayfaMusteri, gorevler: sayfaGorevler, uyarilar: sayfaUyarilar,
    raporlar: sayfaRaporlar, kameralar: sayfaKameralar, entegrasyonlar: sayfaEntegrasyonlar, ayarlar: sayfaAyarlar };
  try {
    if (SAYFA[yol]) await SAYFA[yol](q, no);
    else if (yol.startsWith('kamera/')) await sayfaKamera(decodeURIComponent(yol.slice(7)), q);
    else return git('');
    if (no === S.sayfaNo) G.ciz($('#sayfa'));
  } catch (x) { if (no === S.sayfaNo) $('#sayfa').innerHTML = hataKarti(x); console.error(x); }
}
let sonYenileme = Date.now();
async function nabiz() {
  try {
    const onceki = S.durum?.is, oncekiIzleme = S.durum?.izlemeler || {};
    await durumAl();
    for (const [kod, i] of Object.entries(S.durum.izlemeler || {})) {  // canlı izleme kamera başına biter: hatayla bitince haber ver
      if (oncekiIzleme[kod]?.durum === 'calisiyor' && i.durum === 'hata') bildir(`${kameraAdi(kod)}: izleme hata verdi. ${(i.satirlar || []).slice(-1)[0] || ''}`, true);
    }
    yeniUyarilar();
    const simdi = S.durum.is, yol = konum().yol, katmanAcik = !!document.querySelector('.cekmece, .perde');
    if (yol === 'kameralar') {
      const k = $('#is-karti'); if (k && simdi) { k.innerHTML = isKarti(); const y = $('#kayit'); if (y) y.scrollTop = y.scrollHeight; }
      const z = $('#izleme-karti');
      if (z) { const acik = $$('#izleme-karti details[open] summary b').map(b => b.textContent); z.innerHTML = izlemeKarti(); $$('#izleme-karti details').forEach(d => { if (acik.includes(d.querySelector('summary b').textContent)) d.open = true; }); }
      $$('[data-izleme-durum]').forEach(e => { e.innerHTML = izlemeDurumu(e.dataset.izlemeDurum); });
      $$('[data-izleme-dugme]').forEach(e => { const kam = S.durum.kameralar.find(c => c.kod === e.dataset.izlemeDugme); if (kam) e.innerHTML = izlemeDugmesi(kam, S.durum.gelistirme); });
    }
    if (yol === '') karolariYenile();
    const bitti = onceki?.durum === 'calisiyor' && simdi?.durum !== 'calisiyor';
    if (bitti && !['ornek-veri', 'motor'].includes(simdi.tur) && !yol.startsWith('kamera/')) {
      bildir(`${simdi.baslik}: ${{ bitti: 'bitti', hata: 'hata verdi', durduruldu: 'durduruldu' }[simdi.durum] || simdi.durum}.`, simdi.durum === 'hata');
      if (!katmanAcik) await ciz(true);
      if (simdi.tur === 'test' && simdi.durum === 'bitti' && simdi.sonuc?.kare && !katmanAcik) karePenceresi(simdi.sonuc);
    } else if (['', 'uyarilar', 'raflar'].includes(yol) && !katmanAcik && (S.acikImza !== acikImza() || Date.now() - sonYenileme > 60000) && !document.getElementById('rehber')) {
      sonYenileme = Date.now();
      await ciz(true);  // yeni uyarı geldi ya da bir dakika geçti: sayfa sessizce yenilenir
    }
  } catch (x) { /* program kapanmış olabilir */ }
}
function karolariYenile() {
  for (const k of S.durum?.kameralar || []) {
    const e = document.querySelector(`.kam[data-kod="${CSS.escape(k.kod)}"]`);
    if (!e) continue;
    const img = e.querySelector('img'), kare = k.son_kare || k.referans_karesi;
    if (img && kare && img.getAttribute('src') !== kare) img.src = kare;
  }
}
window.addEventListener('hashchange', () => ciz());
(async () => {
  try {
    [S.durum, S.katalog] = await Promise.all([api('/api/durum'), api('/api/katalog')]);
    if (ZIL.son == null) { ZIL.son = S.durum.son_olay || 0; sakla('raf-zil-son', String(ZIL.son)); }
    ustbarCiz();
    await ciz();
    setInterval(nabiz, 3000);
  } catch (x) { $('#sayfa').innerHTML = `<div class="bos-durum"><h3>Program yanıt vermiyor</h3><p>${h(x.message)}</p></div>`; }
})();
