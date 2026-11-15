'use strict';
/* Küçük grafik yardımcıları (SVG ve canvas). Dış kütüphane ve ağ isteği yok.
   Kullanım: sayfa HTML'inde G.yer(cizici) bir yer tutucu döndürür; sayfa çizildikten sonra G.ciz() her yer tutucuyu
   gerçek genişliğiyle çizer. Pencere boyutu değişince grafikler yeniden çizilir. */

const G = (() => {
  const bekleyen = new Map();
  let sayac = 0;
  const RENK = {
    ana: '#0f8b7d', ana2: '#7fc8bd', mavi: '#2f6fe0', mavi2: '#9db8f0', sari: '#e5a12a', kirmizi: '#d64532', mor: '#7c5cd6', gri: '#97a29e',
    cizgi: '#e6ebe8', yazi: '#66706d', koyu: '#141a19',
  };
  const DURUM_RENK = { dolu: '#2f8f6b', az: '#e5a12a', bos: '#d64532', yanlis: '#7c5cd6', kapali: '#97a29e', bilinmiyor: '#c7d0cc', tanimsiz: '#e3e8e6' };
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const sayiBicim = (v, ondalik = 0) => v == null || isNaN(v) ? '–' : Number(v).toLocaleString('tr-TR', { maximumFractionDigits: ondalik, minimumFractionDigits: 0 });

  function yer(cizici, sinif = '') {
    const id = 'g' + (++sayac);
    bekleyen.set(id, cizici);
    return `<div class="grafik ${sinif}" data-grafik="${id}"></div>`;
  }
  function ciz(kok = document) {
    kok.querySelectorAll('[data-grafik]').forEach(e => {
      const f = bekleyen.get(e.dataset.grafik);
      if (!f) return;
      const w = Math.max(160, e.clientWidth || 300);
      try { e.innerHTML = f(w); } catch (x) { e.innerHTML = '<div class="not">Grafik çizilemedi.</div>'; console.error(x); }
    });
  }
  function temizle() { bekleyen.clear(); }
  let zam = null;
  window.addEventListener('resize', () => { clearTimeout(zam); zam = setTimeout(() => ciz(), 150); });

  function guzelUst(v) {
    if (v <= 0) return 1;
    const us = Math.pow(10, Math.floor(Math.log10(v)));
    for (const k of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (k * us >= v) return k * us;
    return 10 * us;
  }
  const bos = (h, metin = 'Bu dönemde veri yok.') => `<div class="grafik-bos" style="height:${h}px">${esc(metin)}</div>`;

  /* Sütun grafiği. o: {etiketler, seriler: [{ad, degerler, renk}], yigin, yukseklik, bicim(v), enCok, isaret: [{i, renk}], etiketAdim} */
  function sutun(o) {
    return w => {
      const H = o.yukseklik || 180, sol = 38, alt = 22, ust = 8, sag = 6;
      const n = o.etiketler.length;
      // üstteki çizgi serisi de veridir: sütunlar boşken (ör. bugün henüz kayıt yok) dönem ortalaması yine çizilir
      const cizgiVar = !!o.cizgi && o.cizgi.degerler.some(v => v);
      if (!n || (o.seriler.every(s => s.degerler.every(v => !v)) && !cizgiVar)) return bos(H, o.bosMetin);
      const toplam = i => Math.max(o.yigin ? o.seriler.reduce((t, s) => t + (s.degerler[i] || 0), 0) : Math.max(...o.seriler.map(s => s.degerler[i] || 0)),
        cizgiVar ? o.cizgi.degerler[i] || 0 : 0);
      const enCok = guzelUst(o.enCok || Math.max(...o.etiketler.map((_, i) => toplam(i))));
      const gw = (w - sol - sag) / n, ic = o.yigin ? 1 : o.seriler.length, bw = Math.max(2, Math.min(38, gw * 0.72 / ic));
      const Y = v => ust + (H - ust - alt) * (1 - v / enCok);
      const bicim = o.bicim || (v => sayiBicim(v));
      let s = `<svg width="${w}" height="${H}" role="img" aria-label="${esc(o.aciklama || 'sütun grafiği')}">`;
      for (const t of [0, 0.5, 1]) s += `<line x1="${sol}" x2="${w - sag}" y1="${Y(enCok * t)}" y2="${Y(enCok * t)}" stroke="${RENK.cizgi}"/><text x="${sol - 6}" y="${Y(enCok * t) + 4}" text-anchor="end" class="g-eksen">${esc(bicim(enCok * t))}</text>`;
      const adim = o.etiketAdim || Math.max(1, Math.ceil(n / Math.max(4, Math.floor((w - sol) / 46))));
      o.etiketler.forEach((et, i) => {
        const x0 = sol + gw * i + (gw - bw * ic) / 2;
        let yigin = 0;
        o.seriler.forEach((sr, k) => {
          const v = sr.degerler[i] || 0;
          if (!v) return;
          const x = o.yigin ? x0 : x0 + k * bw;
          const y1 = Y(yigin + v), y0 = Y(yigin);
          s += `<rect x="${x.toFixed(1)}" y="${y1.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1, y0 - y1).toFixed(1)}" rx="2" fill="${sr.renk || RENK.ana}"><title>${esc(et)} · ${esc(sr.ad)}: ${esc(bicim(v))}</title></rect>`;
          if (o.yigin) yigin += v;
        });
        if (i % adim === 0) s += `<text x="${(sol + gw * i + gw / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle" class="g-eksen">${esc(et)}</text>`;
      });
      (o.isaret || []).forEach(m => { s += `<rect x="${sol + gw * m.i}" y="${ust}" width="${gw}" height="${H - ust - alt}" fill="${m.renk || 'rgba(15,139,125,.07)'}"/>`; });
      if (o.cizgi) {  // üstüne çizgi serisi (ör. dönem ortalaması)
        const p = o.cizgi.degerler.map((v, i) => v == null ? null : `${(sol + gw * i + gw / 2).toFixed(1)},${Y(v).toFixed(1)}`).filter(Boolean);
        s += `<polyline points="${p.join(' ')}" fill="none" stroke="${o.cizgi.renk || RENK.koyu}" stroke-width="2" stroke-dasharray="4 3" stroke-linejoin="round"/>`;
      }
      return s + '</svg>' + gosterge(o.seriler.concat(o.cizgi ? [{ ...o.cizgi, kesik: true }] : []));
    };
  }

  function gosterge(seriler) {
    if (seriler.length < 2) return '';
    return `<div class="g-gosterge">${seriler.map(s => `<span><i style="background:${s.kesik ? 'transparent' : s.renk || RENK.ana};${s.kesik ? `border-top:2px dashed ${s.renk || RENK.koyu};height:0;margin-top:5px` : ''}"></i>${esc(s.ad)}</span>`).join('')}</div>`;
  }

  /* Çizgi grafiği. o: {etiketler, seriler: [{ad, degerler, renk, alan}], yukseklik, enAz, enCok, bicim, yuzde} */
  function cizgi(o) {
    return w => {
      const H = o.yukseklik || 180, sol = 40, alt = 22, ust = 10, sag = 8;
      const n = o.etiketler.length;
      const tum = o.seriler.flatMap(s => s.degerler).filter(v => v != null);
      if (!n || !tum.length) return bos(H, o.bosMetin);
      const enAz = o.enAz ?? Math.min(0, ...tum), enCok = o.enCok ?? guzelUst(Math.max(...tum));
      const X = i => sol + (n === 1 ? (w - sol - sag) / 2 : (w - sol - sag) * i / (n - 1));
      const Y = v => ust + (H - ust - alt) * (1 - (v - enAz) / ((enCok - enAz) || 1));
      const bicim = o.bicim || (v => sayiBicim(v));
      let s = `<svg width="${w}" height="${H}" role="img" aria-label="${esc(o.aciklama || 'çizgi grafiği')}">`;
      for (const t of [0, 0.5, 1]) { const v = enAz + (enCok - enAz) * t; s += `<line x1="${sol}" x2="${w - sag}" y1="${Y(v)}" y2="${Y(v)}" stroke="${RENK.cizgi}"/><text x="${sol - 6}" y="${Y(v) + 4}" text-anchor="end" class="g-eksen">${esc(bicim(v))}</text>`; }
      const adim = Math.max(1, Math.ceil(n / Math.max(3, Math.floor((w - sol) / 64))));
      o.etiketler.forEach((et, i) => { if (i % adim === 0 || i === n - 1 && n < 8) s += `<text x="${X(i)}" y="${H - 6}" text-anchor="middle" class="g-eksen">${esc(et)}</text>`; });
      o.seriler.forEach(sr => {
        const parca = [];
        let su = [];
        sr.degerler.forEach((v, i) => { if (v == null) { if (su.length) parca.push(su); su = []; } else su.push([X(i), Y(v), v, i]); });
        if (su.length) parca.push(su);
        for (const p of parca) {
          const d = p.map((q, j) => `${j ? 'L' : 'M'}${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(' ');
          if (sr.alan && p.length > 1) s += `<path d="${d} L${p[p.length - 1][0].toFixed(1)},${Y(enAz)} L${p[0][0].toFixed(1)},${Y(enAz)} Z" fill="${sr.renk || RENK.ana}" opacity=".10"/>`;
          s += `<path d="${d}" fill="none" stroke="${sr.renk || RENK.ana}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>`;
          if (p.length <= 40) s += p.map(q => `<circle cx="${q[0].toFixed(1)}" cy="${q[1].toFixed(1)}" r="3" fill="#fff" stroke="${sr.renk || RENK.ana}" stroke-width="1.8"><title>${esc(o.etiketler[q[3]])} · ${esc(sr.ad)}: ${esc(bicim(q[2]))}</title></circle>`).join('');
        }
      });
      return s + '</svg>' + gosterge(o.seriler);
    };
  }

  /* Huni: adimlar [{ad, n}] — her adımın bir öncekine oranı yazılır. */
  function huni(adimlar) {
    return w => {
      const ilk = adimlar[0]?.n || 0;
      if (!ilk) return bos(150, 'Bu dönemde müşteri sayımı yok.');
      const renk = [RENK.ana, '#2b9d8f', '#58b3a7', '#8ccbc1'];
      return `<div class="huni">${adimlar.map((a, i) => {
        const pay = Math.max(2, 100 * a.n / ilk), oran = i ? (adimlar[i - 1].n ? Math.round(100 * a.n / adimlar[i - 1].n) : 0) : null;
        return `<div class="huni-satir"><div class="huni-ad">${esc(a.ad)}</div><div class="huni-cubuk"><i style="width:${pay}%;background:${renk[i % 4]}"></i><b>${sayiBicim(a.n)}</b></div>
          <div class="huni-oran">${oran == null ? '' : `%${oran}<small> önceki adımın</small>`}</div></div>`;
      }).join('')}</div>`;
    };
  }

  /* Isı matrisi (ör. haftanın günü × saat): m[satır][sütun]. o: {satirlar, sutunlar, bicim, renk: 'kirmizi'|'ana', sutunBas, sutunBit} */
  function matris(m, o) {
    return w => {
      const b = o.sutunBas ?? 0, s = o.sutunBit ?? m[0].length;
      const tum = m.flatMap(r => r.slice(b, s));
      const enCok = Math.max(0, ...tum);
      if (!enCok) return bos(160, o.bosMetin || 'Bu dönemde veri yok.');
      const sol = 34, ust = 4, alt = 18, hucW = (w - sol) / (s - b), hucH = o.hucre || 20;
      const H = ust + hucH * m.length + alt;
      const ton = o.renk === 'kirmizi' ? [214, 69, 50] : [15, 139, 125];
      let svg = `<svg width="${w}" height="${H}" role="img" aria-label="${esc(o.aciklama || 'ısı matrisi')}">`;
      m.forEach((r, y) => {
        svg += `<text x="${sol - 6}" y="${ust + hucH * y + hucH / 2 + 4}" text-anchor="end" class="g-eksen">${esc(o.satirlar[y])}</text>`;
        for (let x = b; x < s; x++) {
          const v = r[x] || 0, a = v ? 0.12 + 0.88 * v / enCok : 0;
          svg += `<rect x="${(sol + (x - b) * hucW + 1).toFixed(1)}" y="${ust + hucH * y + 1}" width="${Math.max(1, hucW - 2).toFixed(1)}" height="${hucH - 2}" rx="3" fill="${v ? `rgba(${ton.join(',')},${a.toFixed(2)})` : '#f1f4f2'}"><title>${esc(o.satirlar[y])} ${esc(o.sutunlar[x])}: ${esc((o.bicim || sayiBicim)(v))}</title></rect>`;
        }
      });
      const adim = Math.max(1, Math.ceil((s - b) / Math.floor((w - sol) / 30)));
      for (let x = b; x < s; x += adim) svg += `<text x="${(sol + (x - b) * hucW + hucW / 2).toFixed(1)}" y="${H - 4}" text-anchor="middle" class="g-eksen">${esc(o.sutunlar[x])}</text>`;
      return svg + '</svg>';
    };
  }

  /* Halka (oranlar). parcalar [{ad, n, renk}] */
  function halka(parcalar, o = {}) {
    return w => {
      const toplam = parcalar.reduce((t, p) => t + (p.n || 0), 0);
      if (!toplam) return bos(o.yukseklik || 140, o.bosMetin || 'Veri yok.');
      const R = Math.min(64, (o.yukseklik || 140) / 2 - 6), r = R * 0.62, cx = R + 4, cy = R + 4;
      let a0 = -Math.PI / 2, svg = `<svg width="${2 * R + 8}" height="${2 * R + 8}" role="img" aria-label="${esc(o.aciklama || 'dağılım')}">`;
      parcalar.forEach(p => {
        if (!p.n) return;
        const a1 = a0 + 2 * Math.PI * p.n / toplam, buyuk = a1 - a0 > Math.PI ? 1 : 0;
        const P = (a, rr) => `${(cx + rr * Math.cos(a)).toFixed(2)},${(cy + rr * Math.sin(a)).toFixed(2)}`;
        const d = p.n === toplam ? `M${P(0, R)} A${R},${R} 0 1 1 ${P(Math.PI, R)} A${R},${R} 0 1 1 ${P(0, R)} M${P(0, r)} A${r},${r} 0 1 0 ${P(Math.PI, r)} A${r},${r} 0 1 0 ${P(0, r)}`
          : `M${P(a0, R)} A${R},${R} 0 ${buyuk} 1 ${P(a1, R)} L${P(a1, r)} A${r},${r} 0 ${buyuk} 0 ${P(a0, r)} Z`;
        svg += `<path d="${d}" fill="${p.renk}" fill-rule="evenodd"><title>${esc(p.ad)}: %${Math.round(100 * p.n / toplam)}</title></path>`;
        a0 = a1;
      });
      svg += `<text x="${cx}" y="${cy + 5}" text-anchor="middle" class="g-halka-orta">${esc(o.orta ?? '')}</text></svg>`;
      return `<div class="halka">${svg}<div class="halka-liste">${parcalar.map(p => `<div><i style="background:${p.renk}"></i><span>${esc(p.ad)}</span><b>%${Math.round(100 * (p.n || 0) / toplam)}</b></div>`).join('')}</div></div>`;
    };
  }

  /* Yatay çubuklar: satirlar [{ad, n, alt, renk}] */
  function yatay(satirlar, o = {}) {
    return () => {
      if (!satirlar.length || satirlar.every(s => !s.n)) return bos(80, o.bosMetin || 'Veri yok.');
      const enCok = o.enCok || Math.max(...satirlar.map(s => s.n || 0)) || 1;
      return `<div class="yatay">${satirlar.map(s => `<div class="yatay-satir"><div class="yatay-ad" title="${esc(s.ad)}">${esc(s.ad)}${s.alt ? `<small>${esc(s.alt)}</small>` : ''}</div>
        <div class="yatay-cubuk"><i style="width:${Math.min(100, Math.max(1, 100 * (s.n || 0) / enCok))}%;background:${s.renk || RENK.ana}"></i></div><b>${esc((o.bicim || sayiBicim)(s.n))}</b></div>`).join('')}</div>`;
    };
  }

  /* Kıvılcım (küçük eğilim çizgisi) */
  function kivilcim(degerler, renk = RENK.ana, h = 34) {
    return w => {
      const v = degerler.filter(x => x != null);
      if (v.length < 2) return '';
      const enAz = Math.min(...v), enCok = Math.max(...v), n = degerler.length;
      const p = degerler.map((x, i) => x == null ? null : `${(2 + (w - 4) * i / (n - 1)).toFixed(1)},${(h - 3 - (h - 6) * (x - enAz) / ((enCok - enAz) || 1)).toFixed(1)}`).filter(Boolean);
      return `<svg width="${w}" height="${h}" aria-hidden="true"><polyline points="${p.join(' ')}" fill="none" stroke="${renk}" stroke-width="1.8" stroke-linejoin="round"/></svg>`;
    };
  }

  /* Zaman şeridi: araliklar [{bas, bit, durum}] → durum renkli şerit (göz geçmişi) */
  function serit(araliklar, bas, bit, etiket) {
    return w => {
      if (!araliklar.length) return bos(46, 'Bu dönemde durum kaydı yok.');
      const t0 = new Date(bas).getTime(), t1 = Math.min(Date.now(), new Date(bit).getTime()), H = 46;
      const X = t => 4 + (w - 8) * (t - t0) / ((t1 - t0) || 1);
      let s = `<svg width="${w}" height="${H}" role="img" aria-label="durum şeridi"><rect x="4" y="6" width="${w - 8}" height="20" rx="4" fill="#f1f4f2"/>`;
      for (const a of araliklar) {
        const x0 = X(new Date(a.bas).getTime()), x1 = X(new Date(a.bit).getTime());
        s += `<rect x="${x0.toFixed(1)}" y="6" width="${Math.max(0.8, x1 - x0).toFixed(1)}" height="20" fill="${DURUM_RENK[a.durum] || RENK.gri}"><title>${esc(etiket(a))}</title></rect>`;
      }
      const gun = 86400000, adim = Math.max(1, Math.ceil((t1 - t0) / gun / Math.max(2, Math.floor(w / 70))));
      for (let t = new Date(new Date(t0).toDateString()).getTime() + gun; t < t1; t += gun * adim) {
        const d = new Date(t);
        s += `<line x1="${X(t)}" x2="${X(t)}" y1="4" y2="28" stroke="#fff" stroke-width="1.5"/><text x="${X(t)}" y="${H - 4}" text-anchor="middle" class="g-eksen">${d.getDate()}.${String(d.getMonth() + 1).padStart(2, '0')}</text>`;
      }
      return s + '</svg>';
    };
  }

  /* Isı haritasını (ızgara) kameranın karesinin üstüne canvas olarak çizer. */
  function isiHaritasi(canvas, izgara, katman, renk = 'sicak') {
    const ctx = canvas.getContext('2d');
    const W = canvas.width = canvas.clientWidth * (window.devicePixelRatio || 1);
    const H = canvas.height = canvas.clientHeight * (window.devicePixelRatio || 1);
    ctx.clearRect(0, 0, W, H);
    const m = izgara?.katmanlar?.[katman];
    if (!m || !m.length) return false;
    const gen = izgara.gen, yuk = izgara.yuk;
    const enCok = Math.max(...m.flat()) || 1;
    const kucuk = document.createElement('canvas');
    kucuk.width = gen; kucuk.height = yuk;
    const kc = kucuk.getContext('2d'), veri = kc.createImageData(gen, yuk);
    const renkler = renk === 'sicak' ? [[255, 237, 160], [254, 178, 76], [240, 59, 32], [150, 0, 40]] : [[215, 240, 235], [51, 179, 163], [11, 95, 86], [5, 50, 45]];
    for (let y = 0; y < yuk; y++) for (let x = 0; x < gen; x++) {
      const v = Math.sqrt(m[y][x] / enCok), i = (y * gen + x) * 4;
      const k = Math.min(2.999, v * 3), j = Math.floor(k), f = k - j, a = renkler[j], b = renkler[j + 1];
      veri.data[i] = a[0] + (b[0] - a[0]) * f; veri.data[i + 1] = a[1] + (b[1] - a[1]) * f; veri.data[i + 2] = a[2] + (b[2] - a[2]) * f;
      veri.data[i + 3] = v < 0.12 ? 0 : Math.round(30 + 185 * v);
    }
    kc.putImageData(veri, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.filter = 'blur(' + Math.round(W / gen / 2.2) + 'px)';
    ctx.drawImage(kucuk, 0, 0, W, H);
    ctx.filter = 'none';
    return true;
  }

  return { yer, ciz, temizle, sutun, cizgi, huni, matris, halka, yatay, kivilcim, serit, isiHaritasi, RENK, DURUM_RENK, sayiBicim, guzelUst };
})();
