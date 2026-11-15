'use strict';
/* Ekranlar: Genel Bakış, Raflar, Ürünler, Müşteri, Raporlar. uyg.js'teki S, api, h, IS, DEGIS, G yardımcıları kullanılır. */

const saatEt = s => String(s).padStart(2, '0') + ':00';
const calismaSaatleri = () => {
  const c = S.durum?.genel?.calisma || { bas: '08:00', bit: '22:00' };
  const a = +c.bas.slice(0, 2), b = +c.bit.slice(0, 2) + (+c.bit.slice(3, 5) ? 1 : 0);
  return b > a ? [a, b] : [0, 24];
};
const tahminRozeti = '<span class="tahmin" title="Tahmindir: boş kalma süresi × gözün (ya da bölgenin) alma hızı">tahmin</span>';
const kpi = (et, deger, alt = '', { link, uyari, baslik } = {}) => `<${link ? `a href="${link}"` : 'div'} class="kpi ${uyari ? 'kpi-uyari' : ''}" ${baslik ? `title="${h(baslik)}"` : ''}><div class="et">${et}</div><div class="deger">${deger}</div><div class="alt">${alt}</div></${link ? 'a' : 'div'}>`;

/* ------------------------------------------------------------ Genel Bakış */
const DIKKAT = {
  bos: ['B', 'var(--d-bos)', '#fff'], az: ['A', 'var(--d-az)', '#3b2a00'], yanlis: ['Y', 'var(--d-yanlis)', '#fff'], etiket_farkli: ['₺', 'var(--mor-acik)', '#4a2fa6'],
  etiket_yok: ['E', '#eceeed', '#4b5552'], olay: ['!', 'var(--kirmizi-acik)', 'var(--kritik)'], eski: ['⏸', 'var(--sari-acik)', '#7a5300'], gorev_gecikti: ['G', '#eceeed', '#4b5552'],
};
function dikkatSatiri(x) {
  const [harf, zemin, renk] = DIKKAT[x.tur] || ['•', '#eee', '#333'];
  let bas, alt, link;
  const yer = [x.kamera_ad, x.bolge_ad].filter(Boolean).join(' · ');
  if (['bos', 'az', 'yanlis'].includes(x.tur)) {
    bas = `${x.urun_ad || 'Göz ' + x.goz} · ${{ bos: 'boş', az: 'azaldı', yanlis: 'yanlış ürün' }[x.tur]}`; alt = yer;
    link = `#/raflar?kamera=${encodeURIComponent(x.kamera)}&goz=${encodeURIComponent(x.goz)}`;
  } else if (x.tur.startsWith('etiket')) {
    bas = `${x.urun_ad || 'Göz ' + x.goz} · ${x.tur === 'etiket_yok' ? 'fiyat etiketi yok' : 'fiyat farklı'}`;
    alt = x.tur === 'etiket_farkli' ? `etikette ${sayi(x.okunan, 2)}, olması gereken ${sayi(x.beklenen, 2)} · ${yer}` : yer;
    link = `#/raflar?kamera=${encodeURIComponent(x.kamera)}&goz=${encodeURIComponent(x.goz)}`;
  } else if (x.tur === 'olay') { bas = x.kural_ad + (x.deger != null && x.kural === 'kasa_kuyrugu' ? ` · ${sayi(x.deger)} kişi` : ''); alt = [x.kamera_ad, x.bolge].filter(Boolean).join(' · '); link = `#/uyarilar?id=${x.id}`; }
  else if (x.tur === 'eski') { bas = 'Kameradan veri gelmiyor'; alt = `${x.kamera_ad} · son kayıt ${tarih(x.zaman)}`; link = `#/kamera/${encodeURIComponent(x.kamera)}`; }
  else { bas = `Görevin son tarihi geçti: ${x.baslik}`; alt = `son tarih ${x.son_tarih}`; link = `#/gorevler?id=${x.id}`; }
  return `<a class="dikkat" href="${link}"><span class="sim" style="background:${zemin};color:${renk}">${harf}</span><span class="metin"><b>${h(bas)}</b><span>${h(alt)}</span></span><span class="zaman">${x.zaman ? once(x.zaman) : ''}</span></a>`;
}
async function sayfaGenel() {
  const d = await api('/api/genel-bakis?' + donemQ());
  if (!d.kameralar.length) {
    $('#sayfa').innerHTML = ust('Genel Bakış', 'raf, müşteri ve operasyon özeti') + modelUyarisi() + ornekVeriDavet('Raf Kamera\'ya hoş geldiniz');
    return;
  }
  const s = d.simdi, p = d.donem, o = d.onceki, sy = s.sayilar || {};
  const [a, b] = [d.trafik.acilis, d.trafik.kapanis];
  const saatler = d.trafik.saatlik.filter(x => x.saat >= a && x.saat < b);
  const tekGun = !S.donem.bas && S.donem.gun === 1;
  const egilimEt = d.egilim.map(x => x.d.length > 10 ? x.d.slice(11, 16) : gunAdi(x.d));
  const rafVar = sy.goz > 0;
  $('#sayfa').innerHTML = ust('Genel Bakış', `${h(d.tesis)} · şimdiki durum ve ${donemKucuk()}`, `<a class="dug" href="#/raporlar">Rapor</a>`)
    + modelUyarisi()
    + `<div class="izgara dortlu bosluk-alt" id="g-kpi">
      ${kpi('Raf doluluğu · şimdi', rafVar ? yuzde(s.doluluk) : '–', rafVar ? `dönem ort. ${yuzde(p.doluluk)} ${fark(p.doluluk, o.doluluk, false, v => yuzde(v))}` : 'planogram yok', { link: '#/raflar' })}
      ${kpi('Boş göz · şimdi', rafVar ? `${sayi(sy.bos || 0)}<small>/ ${sy.goz}</small>` : '–', rafVar ? `${sayi(sy.az || 0)} azalan · dönemde ${sayi(p.bos_sn / 3600, 1)} göz-saat boş` : '', { link: '#/raflar?suzgec=bos', uyari: sy.bos > 0 })}
      ${kpi('Planogram uyumu', rafVar ? yuzde(s.uyum) : '–', rafVar ? `${sayi(sy.yanlis || 0)} yanlış ürün · ${sayi(sy.etiket_sorun || 0)} etiket sorunu` : '', { link: '#/raflar?suzgec=yanlis', baslik: 'Beklenen ürünü taşıyan gözlerin oranı' })}
      ${kpi('Açık görev', sayi(s.acik_gorev), `ort. doldurma ${sure(p.dolum_ort_sn)} ${fark(p.dolum_ort_sn, o.dolum_ort_sn, true, v => sure(v))}`, { link: '#/gorevler' })}
      ${kpi('Ziyaretçi', p.ziyaretci == null ? '–' : sayi(p.ziyaretci), p.ziyaretci == null ? 'giriş sayımı yok' : `${donemKucuk()} ${fark(p.ziyaretci, o.ziyaretci)}`, { link: '#/musteri' })}
      ${kpi('Raf önünde ort. bekleme', sure(p.ort_bekleme_sn), fark(p.ort_bekleme_sn, o.ort_bekleme_sn, false, v => sure(v)) || 'duran müşteri başına', { link: '#/musteri' })}
      ${kpi('Kasa kuyruğu · şimdi', s.kuyruk == null ? '–' : `${sayi(s.kuyruk, 1)}<small>kişi</small>`, `dönemde en çok ${p.kuyruk_en_cok == null ? '–' : sayi(p.kuyruk_en_cok) + ' kişi'}`, { link: '#/uyarilar?kural=kasa_kuyrugu' })}
      ${kpi(`Kayıp satış ${tahminRozeti}`, para(p.kayip_tutar), `${sayi(p.kayip_adet, 1)} adet ${fark(p.kayip_tutar, o.kayip_tutar, true, v => para(v))}`, { link: '#/urunler?sirala=kayip', baslik: 'Tahmin: boş kalan gözün süresi × o gözün alma hızı' })}</div>`
    + `<div class="izgara iki bosluk-alt"><div class="izgara" style="gap:14px">
        <div class="kart"><div class="kart-bas"><h2>Saatlik ${d.trafik.alan === 'giren' ? 'ziyaretçi' : 'trafik (geçen kişi)'} <small>${tekGun ? 'bugün' : 'bugün ve dönem ortalaması'}</small></h2></div>
          ${G.yer(G.sutun({ etiketler: saatler.map(x => saatEt(x.saat)), seriler: [{ ad: 'Bugün', degerler: saatler.map(x => x.bugun), renk: G.RENK.ana }], cizgi: tekGun ? null : { ad: 'Dönem ortalaması', degerler: saatler.map(x => x.ort), renk: '#3c4744' }, yukseklik: 190, isaret: saatler.map((x, i) => x.saat === new Date().getHours() ? { i } : null).filter(Boolean), aciklama: 'Saatlik ziyaretçi' }))}</div>
        <div class="kart"><div class="kart-bas"><h2>Raf doluluğu ve planogram uyumu <small>${egilimEt.length && d.egilim[0].d.length > 10 ? 'saatlik' : 'günlük'}</small></h2></div>
          ${G.yer(G.cizgi({ etiketler: egilimEt, seriler: [{ ad: 'Doluluk', degerler: d.egilim.map(x => x.doluluk), renk: G.RENK.ana, alan: true }, { ad: 'Planogram uyumu', degerler: d.egilim.map(x => x.uyum), renk: G.RENK.mavi }], enAz: 0, enCok: 1, bicim: v => yuzde(v), yukseklik: 180, bosMetin: 'Bu dönemde raf kaydı yok.' }))}</div></div>
      <div class="izgara" style="gap:14px;align-content:start">
        <div class="kart"><div class="kart-bas"><h2>Şimdi ilgilenilmesi gerekenler <small>${d.dikkat_toplam}</small></h2></div>
          <div class="kaydir" style="max-height:330px">${d.dikkat.length ? d.dikkat.map(dikkatSatiri).join('') : '<div class="not" style="padding:16px 4px">Her şey yolunda: boş göz, fiyat sorunu ya da süren operasyon uyarısı yok.</div>'}</div></div>
        <div class="kart"><div class="kart-bas"><h2>En çok kayıp ${tahminRozeti}</h2><a class="dug kucuk" href="#/urunler?sirala=kayip">Ürünler</a></div>
          ${G.yer(G.yatay(d.en_kayip.map(x => ({ ad: x.urun_ad || 'Göz ' + x.goz, alt: x.kamera_ad, n: x.kayip_tutar ?? x.kayip_adet, renk: G.RENK.kirmizi })), { bicim: v => para(v), bosMetin: (d.donem.bos_sn || 0) > 0 ? 'Boş kalan göz var; kayıp tahmini için süre ve trafik verisi henüz az.' : 'Bu dönemde boş kalan göz yok.' }))}</div></div></div>`
    + `<div class="kart"><div class="kart-bas"><h2>Kameralar <small>${d.kameralar.length}</small></h2><a class="dug kucuk" href="#/kameralar">Kameraları yönet</a></div>
        <div class="kameralar">${d.kameralar.map(kameraKarosu).join('')}</div>
        <div class="not" style="margin-top:10px">Karolar kameranın yüzleri gizlenmiş son karesidir. ${d.kameralar.some(k => k.eski) ? '<b>Sarı “Veri eski”</b>: çalışma saatinde 10 dakikadır kayıt gelmiyor.' : ''}</div></div>`;
}

/* ------------------------------------------------------------ Raflar */
const RAF_SUZGEC = { '': 'Tümü', bos: 'Boş', az: 'Azalan', yanlis: 'Yanlış ürün', etiket: 'Etiket sorunu' };
const gozUyar = (g, suzgec) => !suzgec || (suzgec === 'etiket' ? ['farkli', 'yok'].includes(g.etiket) : g.durum === suzgec);
function satirlara(gozler) {
  // gözleri ekrandaki yerlerine göre raf satırlarına ayırır (y merkezine göre), satır içinde soldan sağa
  const l = gozler.filter(g => g.kutu).map(g => ({ g, y: (g.kutu[1] + g.kutu[3]) / 2, x: (g.kutu[0] + g.kutu[2]) / 2, hy: g.kutu[3] - g.kutu[1] }));
  l.sort((a, b) => a.y - b.y);
  const satirlar = [];
  for (const o of l) {
    const s = satirlar[satirlar.length - 1];
    if (s && Math.abs(o.y - s.y) < Math.max(0.02, o.hy * 0.5)) { s.l.push(o); s.y = s.l.reduce((t, x) => t + x.y, 0) / s.l.length; } else satirlar.push({ y: o.y, l: [o] });
  }
  return satirlar.map(s => s.l.sort((a, b) => a.x - b.x).map(o => o.g));
}
function gozRengi(g) { return G.DURUM_RENK[g.durum] || G.DURUM_RENK.tanimsiz; }
function rafGoruntusu(d, suzgec) {
  if (!d.kare) return '<div class="sahne"><div class="bosyazi">Bu kameranın yüzleri gizlenmiş karesi henüz yok.<br>Analiz çalışınca burada görünür; şimdilik planogram görünümünü kullanın.</div></div>';
  const kutular = d.bolgeler.flatMap(b => (b.gozler || []).filter(g => g.kutu).map(g => {
    const [x1, y1, x2, y2] = g.kutu.map(v => v * 1000), r = gozRengi(g), uy = gozUyar(g, suzgec);
    const et = g.etiket_kutu && ['farkli', 'yok'].includes(g.etiket) ? `<rect x="${g.etiket_kutu[0] * 1000}" y="${g.etiket_kutu[1] * 1000}" width="${(g.etiket_kutu[2] - g.etiket_kutu[0]) * 1000}" height="${(g.etiket_kutu[3] - g.etiket_kutu[1]) * 1000}" fill="none" stroke="#b18cff" stroke-width="2.5" stroke-dasharray="5 3" vector-effect="non-scaling-stroke"/>` : '';
    return `<g class="goz-kutu" data-is="goz-ac" data-goz="${h(g.kimlik)}" opacity="${uy ? 1 : 0.25}" tabindex="0" role="button" aria-label="${h((g.urun_ad || 'Göz ' + g.kimlik) + ': ' + (GOZ_DURUM[g.durum] || g.durum))}"><rect x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}" rx="4" fill="${r}" fill-opacity="${g.durum === 'dolu' ? 0.12 : 0.38}" stroke="${r}" stroke-width="2" vector-effect="non-scaling-stroke"><title>${h(g.urun_ad || 'Ürün atanmamış')} · ${h(GOZ_DURUM[g.durum] || g.durum)}${g.doluluk != null ? ' · ' + yuzde(g.doluluk) : ''}</title></rect>${et}</g>`;
  })).join('');
  return `<div class="sahne"><img src="${h(d.kare)}" alt="${h(d.kamera_ad)} rafının son karesi (yüzler gizli)"><svg viewBox="0 0 1000 1000" preserveAspectRatio="none">${kutular}</svg></div>`;
}
function planogramGorunumu(d, suzgec) {
  const bolgeler = d.bolgeler.filter(b => (b.gozler || []).length);
  if (!bolgeler.length) return '<div class="not">Bu kamerada göz tanımlı değil.</div>';
  return `<div class="planogram">${bolgeler.map(b => `<div class="pg-bolge"><h3>${h(b.ad)} <span class="rozet gri">${b.gozler.length} göz</span></h3>${satirlara(b.gozler).map(satir => `<div class="pg-satir" style="grid-template-columns:repeat(${satir.length},minmax(0,1fr))">${satir.map(g => `<button type="button" class="pg-goz ${gozUyar(g, suzgec) ? '' : 'soluk'}" style="border-top-color:${gozRengi(g)}" data-is="goz-ac" data-goz="${h(g.kimlik)}" title="${h(g.urun_ad || '')}">
      ${g.gorsel ? `<img src="${gorselAdresi(g.gorsel)}" alt="" loading="lazy">` : '<img alt="">'}<span class="ad">${h(g.urun_ad || 'Ürün yok')}</span>
      <span class="alt"><span style="color:${gozRengi(g)}">${h(GOZ_DURUM[g.durum] || g.durum)}</span><span>${g.doluluk != null ? yuzde(g.doluluk) : ''}</span></span>${['farkli', 'yok'].includes(g.etiket) ? `<span class="rozet mor">${h(ETIKET[g.etiket])}</span>` : ''}</button>`).join('')}</div>`).join('')}</div>`).join('')}</div>`;
}
async function sayfaRaflar(q) {
  const kamera = q.kamera || (S.durum.kameralar.find(k => k.kod === S.kamera && k.goz) ? S.kamera : '');
  const d = await api('/api/raflar?' + donemQ({ kamera }));
  S.raf = d;
  if (!d.kamera) {
    $('#sayfa').innerHTML = ust('Raflar', 'planogram ve göz durumları') + (S.durum.kameralar.length
      ? `<div class="bos-durum"><h3>Planogram tanımlı raf yok</h3><p>Bir kameranın düzenleyicisinde raf bölgesini çizin, rafı gözlere bölün ve her göze ürününü atayın. Sonra her gözün durumu (dolu, azalan, boş, yanlış ürün) ve fiyat etiketi burada görünür.</p><div class="eylemler"><a class="dug ana" href="#/kameralar">Kameraya git</a></div></div>`
      : ornekVeriDavet('Henüz raf yok'));
    return;
  }
  if (S.kamera !== d.kamera) { S.kamera = d.kamera; sakla('raf-kamera-suzgec', d.kamera); }
  const suzgec = q.suzgec || '', gorunum = q.gorunum || (d.kare ? 'goruntu' : 'planogram'), sy = d.sayilar, t = d.toplam;
  const tum = d.bolgeler.flatMap(b => b.gozler || []);
  const sorunlu = tum.filter(g => ['bos', 'az', 'yanlis'].includes(g.durum) || ['farkli', 'yok'].includes(g.etiket)).filter(g => gozUyar(g, suzgec) || (suzgec === '' && true))
    .sort((x, y) => ({ bos: 0, yanlis: 1, az: 2 }[x.durum] ?? 3) - ({ bos: 0, yanlis: 1, az: 2 }[y.durum] ?? 3));
  const [a, b] = calismaSaatleri();
  const sayac = { '': sy.goz, bos: sy.bos || 0, az: sy.az || 0, yanlis: sy.yanlis || 0, etiket: sy.etiket_sorun || 0 };
  $('#sayfa').innerHTML = ust('Raflar', `${h(d.kamera_ad)} · ${sy.goz} göz · şimdi ${yuzde(d.doluluk)} dolu`,
    `<a class="dug" href="/api/disa/tukenmeler.xlsx?${donemQ()}">${IKON.indir}Tükenmeler</a><a class="dug" href="#/kamera/${encodeURIComponent(d.kamera)}?sekme=planogram">Planogramı düzenle</a>`)
    + (d.kameralar.length > 1 ? `<div class="ust" style="margin-top:-6px"><div class="grup" role="tablist" aria-label="Raf kameraları">${d.kameralar.map(k => `<button role="tab" aria-selected="${k.kod === d.kamera}" class="${k.kod === d.kamera ? 'secili' : ''}" data-is="raf-kamera" data-kod="${h(k.kod)}">${h(k.ad)}${k.sayilar.bos ? `<span class="n" style="color:var(--d-bos)">${k.sayilar.bos} boş</span>` : ''}</button>`).join('')}</div></div>` : '')
    + (d.referans_gecici ? `<div class="uyari-seridi"><b>Geçici referans.</b> Bu kamera için kayıtlı “dolu raf” karesi yok; motor koşunun ilk karelerini referans alıyor, doluluk yanlış okunabilir. Rafı doldurup düzenleyicide <b>Rafı dolu olarak kaydet</b>'e basın. <a class="dug kucuk" href="#/kamera/${encodeURIComponent(d.kamera)}?sekme=planogram">Düzenleyiciyi aç</a></div>` : '')
    + (d.referans_eski ? `<div class="uyari-seridi"><b>Referans kare eski.</b> Gözler referans karesi kaydedildikten sonra değişti. Raf doluyken referansı yenileyin. <a class="dug kucuk" href="#/kamera/${encodeURIComponent(d.kamera)}?sekme=planogram">Yenile</a></div>` : '')
    + `<div class="izgara dortlu bosluk-alt">
        ${kpi('Doluluk · şimdi', yuzde(d.doluluk), `${sy.dolu || 0} dolu · ${sy.az || 0} azalan`)}
        ${kpi('Boş göz · şimdi', sayi(sy.bos || 0), `dönemde ${sayi(t.bos_sn / 3600, 1)} göz-saat boş`, { uyari: sy.bos > 0 })}
        ${kpi('Planogram uyumu', yuzde(d.uyum), `${sy.yanlis || 0} yanlış ürün · ${sy.etiket_sorun || 0} etiket sorunu`)}
        ${kpi('Ort. doldurma süresi', sure(t.dolum_ort_sn), `ortanca ${sure(t.dolum_medyan_sn)} · ${t.dolum_sayi} doldurma · ${tahminRozeti} kayıp ${para(t.kayip_tutar)}`)}</div>`
    + `<div class="izgara iki bosluk-alt"><div class="kart"><div class="kart-bas" style="flex-wrap:wrap"><div class="grup">${Object.entries(RAF_SUZGEC).map(([v, ad]) => `<button class="${suzgec === v ? 'secili' : ''}" data-is="raf-suzgec" data-v="${v}">${ad}<span class="n">${sayac[v]}</span></button>`).join('')}</div><span style="flex:1"></span>
          <div class="grup">${[['goruntu', 'Görüntü'], ['planogram', 'Planogram']].map(([v, ad]) => `<button class="${gorunum === v ? 'secili' : ''}" data-is="raf-gorunum" data-v="${v}">${ad}</button>`).join('')}</div></div>
        ${gorunum === 'goruntu' ? rafGoruntusu(d, suzgec) : planogramGorunumu(d, suzgec)}
        <div class="durum-serit" style="margin-top:10px">${['dolu', 'az', 'bos', 'yanlis', 'kapali', 'tanimsiz'].map(durumRozeti).join('')}<span class="d-rozet"><i style="background:none;border:2px dashed #b18cff;width:12px;height:9px"></i>Etiket sorunu</span><span class="not" style="margin-left:auto">${d.bolgeler[0]?.gozler?.[0]?.zaman ? 'son raf kaydı ' + once(tum.map(g => g.zaman).filter(Boolean).sort().slice(-1)[0]) : ''}</span></div></div>
      <div class="izgara" style="gap:14px;align-content:start"><div class="kart"><div class="kart-bas"><h2>${suzgec ? h(RAF_SUZGEC[suzgec]) + ' gözler' : 'Sorunlu gözler'} <small>${sorunlu.length}</small></h2></div>
        <div class="kaydir" style="max-height:300px">${sorunlu.length ? sorunlu.map(g => `<a class="dikkat" href="#" data-is="goz-ac" data-goz="${h(g.kimlik)}"><span class="sim" style="background:#fff;border:3px solid ${gozRengi(g)};overflow:hidden">${g.gorsel ? `<img src="${gorselAdresi(g.gorsel)}" alt="" style="width:100%;height:100%;object-fit:contain">` : ''}</span>
          <span class="metin"><b>${h(g.urun_ad || 'Göz ' + g.kimlik)}</b><span>${h(GOZ_DURUM[g.durum] || g.durum)}${['farkli', 'yok'].includes(g.etiket) ? ' · ' + h(ETIKET[g.etiket]) + (g.etiket === 'farkli' ? ` (${sayi(g.okunan_fiyat, 2)} / ${sayi(g.fiyat, 2)})` : '') : ''}${g.kayip_tutar ? ' · kayıp ' + para(g.kayip_tutar) : ''}</span></span><span class="zaman">${g.degisim ? once(g.degisim) : ''}</span></a>`).join('')
          : `<div class="not" style="padding:16px 4px">${suzgec ? 'Bu süzgece uyan göz yok.' : 'Şu an sorunlu göz yok: bütün gözler dolu ve etiketler uygun.'}</div>`}</div></div>
        <div class="kart"><div class="kart-bas"><h2>Doluluk ve planogram uyumu</h2></div>
        ${G.yer(G.cizgi({ etiketler: d.egilim.map(x => x.d.length > 10 ? x.d.slice(11, 16) : gunAdi(x.d)), seriler: [{ ad: 'Doluluk', degerler: d.egilim.map(x => x.doluluk), renk: G.RENK.ana, alan: true }, { ad: 'Uyum', degerler: d.egilim.map(x => x.uyum), renk: G.RENK.mavi }], enAz: 0, enCok: 1, bicim: v => yuzde(v), yukseklik: 180 }))}</div></div></div>`
    + `<div class="izgara ikili"><div class="kart"><div class="kart-bas"><h2>Saate göre tükenme <small>boş göz-dakika · gün × saat</small></h2></div>
        ${G.yer(G.matris(d.matris, { satirlar: GUNLER, sutunlar: Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0')), sutunBas: a, sutunBit: b, renk: 'kirmizi', bicim: v => sayi(v) + ' dk', bosMetin: 'Bu dönemde boş kalan göz yok.' }))}
        <p class="not" style="margin-bottom:0">Koyu hücreler rafların en çok boş kaldığı gün ve saatlerdir: doldurma turlarını bu saatlerden önceye alın.</p></div>
      <div class="kart"><div class="kart-bas"><h2>Son doldurmalar <small>boş ya da azalan gözün yeniden dolması</small></h2></div>
        ${d.dolum.length ? `<div class="kaydir" style="max-height:250px"><table><thead><tr><th>Ürün</th><th>Başladı</th><th>Dolduruldu</th><th class="s">Tepki</th></tr></thead><tbody>${d.dolum.slice(0, 40).map(x => `<tr class="tik" data-is="goz-ac" data-goz="${h(x.goz)}"><td>${h(x.urun_ad || '–')}<div class="not">${h(x.bolge_ad)} · ${h(x.goz)}</div></td><td>${tarih(x.bas)}</td><td>${tarih(x.bit)}</td><td class="s"><b>${sure(x.sure_sn)}</b> ${x.bos ? '<span class="rozet kirmizi">boş</span>' : '<span class="rozet sari">az</span>'}</td></tr>`).join('')}</tbody></table></div>`
          : '<div class="not">Bu dönemde doldurma yok.</div>'}</div></div>`;
  if (q.goz) gozCekmecesi(d.kamera, q.goz);
}
async function gozCekmecesi(kamera, goz) {
  $('#katman').innerHTML = `<aside class="cekmece">${yukleniyor()}</aside>`;
  let d;
  try { d = await api('/api/goz?' + donemQ({ kamera, goz })); } catch (x) { $('#katman').innerHTML = `<aside class="cekmece"><div class="cekmece-bas"><div><h2>Göz</h2></div><button class="dug kucuk" data-is="katman-kapat">Kapat</button></div><div class="not">${h(x.message)}</div></aside>`; return; }
  const s = d.son || {}, o = d.olcu || {}, u = (S.raf?.bolgeler || []).flatMap(b => b.gozler || []).find(g => g.kimlik === goz) || {};
  const dur = s.durum || 'tanimsiz';
  const etk = d.etkilesim;
  $('#katman').innerHTML = `<aside class="cekmece" role="dialog" aria-label="Göz ayrıntısı"><div class="cekmece-bas"><div class="goz-ozet">${u.gorsel ? `<img src="${gorselAdresi(u.gorsel)}" alt="">` : ''}<div>
      <div>${durumRozeti(dur)} ${s.etiket ? `<span class="rozet ${['farkli', 'yok'].includes(s.etiket) ? 'mor' : 'gri'}">${h(ETIKET[s.etiket] || s.etiket)}</span>` : ''}</div>
      <h2 style="margin-top:4px">${h(d.urun_ad || 'Ürün atanmamış')}</h2><div class="not">${h(d.kamera_ad)} · ${h(d.bolge_ad)} · göz ${h(goz)}${s.degisim ? ' · bu durumda ' + once(s.degisim).replace(' önce', '') : ''}</div></div></div>
      <button class="dug kucuk" data-is="katman-kapat">Kapat</button></div>
    <div class="bilgi"><div><span class="et">Doluluk</span><b>${s.doluluk != null ? yuzde(s.doluluk) : '–'}</b><span class="not">${s.adet != null ? `${s.adet} / ${d.adet} yüz` : `beklenen ${d.adet} yüz`}</span></div>
      <div><span class="et">Boş kalma</span><b>${sure(o.bos_sn)}</b><span class="not">${donemKucuk()}</span></div>
      <div><span class="et">Alma</span><b>${sayi(o.alma)}</b><span class="not">müşteri aldı</span></div>
      <div><span class="et">Kayıp ${tahminRozeti}</span><b>${o.kayip_tutar != null ? para(o.kayip_tutar) : sayi(o.kayip_adet, 1) + ' adet'}</b><span class="not">${o.yontem === 'goz' ? 'gözün alma hızından' : 'bölgedeki duran müşteriden'}</span></div>
      <div><span class="et">Fiyat</span><b>${d.fiyat != null ? sayi(d.fiyat, 2) : '–'}</b><span class="not">${s.fiyat != null ? 'etikette ' + sayi(s.fiyat, 2) : 'etiket okunmadı'}</span></div>
      <div><span class="et">Doldurma</span><b>${d.dolum.length ? sure(d.dolum.reduce((t, x) => t + x.sure_sn, 0) / d.dolum.length) : '–'}</b><span class="not">${d.dolum.length} kez, ortalama</span></div></div>
    <div class="et" style="margin:12px 0 4px">Durum geçmişi</div>${G.yer(G.serit(d.araliklar, d.bas, d.bit, a => `${GOZ_DURUM[a.durum] || a.durum} · ${tarih(a.bas)} – ${tarih(a.bit)}`))}
    <div class="durum-serit" style="margin-bottom:12px">${['dolu', 'az', 'bos', 'yanlis', 'kapali'].map(durumRozeti).join('')}</div>
    <div class="et" style="margin:12px 0 4px">Müşteri etkileşimi · günlük</div>${G.yer(G.sutun({ etiketler: etk.map(x => gunAdi(x.gun)), seriler: [{ ad: 'Durdu', degerler: etk.map(x => x.durdu), renk: G.RENK.mavi2 }, { ad: 'Uzandı', degerler: etk.map(x => x.uzandi), renk: G.RENK.ana2 }, { ad: 'Aldı', degerler: etk.map(x => x.aldi), renk: G.RENK.ana }], yukseklik: 150, bosMetin: 'Bu dönemde etkileşim yok.' }))}
    ${d.dolum.length ? `<div class="et" style="margin:14px 0 4px">Doldurmalar</div><table><thead><tr><th>Başladı</th><th>Dolduruldu</th><th class="s">Tepki</th></tr></thead><tbody>${d.dolum.slice(-8).reverse().map(x => `<tr><td>${tarih(x.bas)}${x.bos ? ' <span class="rozet kirmizi">boş</span>' : ''}</td><td>${tarih(x.bit)}</td><td class="s">${sure(x.sure_sn)}</td></tr>`).join('')}</tbody></table>` : ''}
    ${d.fiyatlar.length ? `<div class="et" style="margin:14px 0 4px">Etiket okumaları</div><table><thead><tr><th>Zaman</th><th>Etiket</th><th class="s">Okunan</th><th class="s">Beklenen</th></tr></thead><tbody>${d.fiyatlar.slice(0, 8).map(x => `<tr><td>${tarih(x.zaman)}</td><td>${h(ETIKET[x.etiket] || x.etiket || '–')}</td><td class="s">${x.fiyat != null ? sayi(x.fiyat, 2) : '–'}</td><td class="s">${d.beklenen_fiyat != null ? sayi(d.beklenen_fiyat, 2) : '–'}</td></tr>`).join('')}</tbody></table>` : ''}
    ${d.olaylar.length ? `<div class="et" style="margin:14px 0 4px">Uyarılar</div><div class="liste">${d.olaylar.slice(0, 6).map(x => `<a class="dikkat" href="#/uyarilar?id=${x.id}"><span class="metin"><b>${h(x.kural_ad)}</b><span>${tarih(x.zaman)} · ${sure(x.sure_sn)}${x.suruyor ? ' · sürüyor' : ''}</span></span></a>`).join('')}</div>` : ''}
    <div class="eylemler" style="justify-content:flex-start"><button class="dug ana" data-is="goz-gorev" data-goz="${h(goz)}">Görev oluştur</button><a class="dug" href="#/kamera/${encodeURIComponent(kamera)}?sekme=planogram&goz=${encodeURIComponent(goz)}">Planogramda düzenle</a>${d.urun ? `<a class="dug" href="#/urunler?id=${encodeURIComponent(d.urun)}">Ürün</a>` : ''}</div></aside>`;
  G.ciz($('#katman'));
  sorguDegistir({ ...konum().q, goz });
}
Object.assign(IS, {
  'raf-kamera': e => { const q = konum().q; git('raflar', { ...q, kamera: e.dataset.kod, goz: undefined }); },
  'raf-suzgec': e => { const q = konum().q; if (e.dataset.v) q.suzgec = e.dataset.v; else delete q.suzgec; delete q.goz; git('raflar', q); },
  'raf-gorunum': e => { const q = konum().q; q.gorunum = e.dataset.v; delete q.goz; git('raflar', q); },
  'goz-ac': e => gozCekmecesi(S.raf.kamera, e.dataset.goz),
  'goz-gorev': e => {
    const g = (S.raf?.bolgeler || []).flatMap(b => (b.gozler || []).map(x => ({ ...x, bolge_ad: b.ad }))).find(x => x.kimlik === e.dataset.goz) || {};
    gorevPenceresi({ baslik: `${g.urun_ad || 'Göz ' + e.dataset.goz} · ${GOZ_DURUM[g.durum] === 'Dolu' ? 'kontrol et' : 'doldur'}`, aciklama: `${S.raf.kamera_ad} · ${g.bolge_ad || ''} · göz ${e.dataset.goz}`, sorumlu: '', son_tarih: '', durum: 'acik', kamera: S.raf.kamera, kural: g.durum === 'bos' ? 'bos_raf' : g.durum === 'az' ? 'az_stok' : '', bolge: g.bolge_ad || '', notlar: '' });
  },
});
document.addEventListener('keydown', ev => {
  if ((ev.key === 'Enter' || ev.key === ' ') && ev.target.matches?.('g.goz-kutu')) { ev.preventDefault(); gozCekmecesi(S.raf.kamera, ev.target.dataset.goz); }
});

/* ------------------------------------------------------------ Ürünler */
const US = { ara: '', kategori: '', sirala: 'ad', gorunum: 'tablo' };
try { US.gorunum = localStorage.getItem('raf-urun-gorunum') || 'tablo'; } catch (x) { /* depolama kapalı */ }
function urunSuz(liste) {
  const k = s => String(s || '').toLocaleLowerCase('tr');
  let l = liste.filter(u => (!US.ara || k(u.ad).includes(k(US.ara)) || k(u.barkod).includes(k(US.ara))) && (!US.kategori || u.kategori === US.kategori));
  const sirala = { ad: (a, b) => a.ad.localeCompare(b.ad, 'tr'), kayip: (a, b) => (b.kayip_tutar || b.kayip_adet) - (a.kayip_tutar || a.kayip_adet), bos: (a, b) => b.bos_sn - a.bos_sn, alma: (a, b) => b.alma - a.alma, sorun: (a, b) => (b.bos_simdi * 3 + b.az_simdi + b.fiyat_sorun * 2) - (a.bos_simdi * 3 + a.az_simdi + a.fiyat_sorun * 2) }[US.sirala];
  return l.sort(sirala);
}
const urunSimdi = u => [u.bos_simdi ? `<span class="rozet kirmizi">${u.bos_simdi} boş</span>` : '', u.az_simdi ? `<span class="rozet sari">${u.az_simdi} azalan</span>` : '', u.fiyat_sorun ? '<span class="rozet mor">etiket</span>' : ''].filter(Boolean).join(' ') || (u.goz ? '<span class="rozet yesil">dolu</span>' : '<span class="not">rafta değil</span>');
function urunListesiCiz() {
  const l = urunSuz(S.urunler || []);
  const k = $('#urun-liste');
  if (!k) return;
  if (!l.length) { k.innerHTML = '<div class="not" style="padding:20px 4px">Aramaya uyan ürün yok.</div>'; return; }
  k.innerHTML = US.gorunum === 'kart'
    ? `<div class="urun-kartlar">${l.map(u => `<button type="button" class="urun-kart" data-is="urun-ac" data-id="${h(u.kimlik)}">${u.gorseller?.length ? `<img src="${gorselAdresi(u.gorseller[0])}" alt="" loading="lazy">` : '<div class="yer"></div>'}<b>${h(u.ad)}</b>
        <span class="not">${h(u.kategori || '')}${u.fiyat != null ? ' · ' + para(u.fiyat, 2) : ''}</span><span>${urunSimdi(u)}</span><span class="not">${u.goz} göz · ${sayi(u.alma)} alma${u.kayip_adet ? ` · kayıp ${para(u.kayip_tutar)}` : ''}</span></button>`).join('')}</div>`
    : `<div class="tablo-kap"><table><thead><tr><th></th><th>Ürün</th><th class="s">Fiyat</th><th class="s">Göz</th><th>Şimdi</th><th class="s">Boş kalma</th><th class="s">Alma</th><th class="s">Kayıp ${tahminRozeti}</th></tr></thead><tbody>${l.map(u => `<tr class="tik" data-is="urun-ac" data-id="${h(u.kimlik)}">
        <td style="width:46px">${u.gorseller?.length ? `<img class="kucuk-gorsel" src="${gorselAdresi(u.gorseller[0])}" alt="" loading="lazy">` : '<div class="kucuk-gorsel"></div>'}</td>
        <td><b>${h(u.ad)}</b><div class="not">${h([u.kategori, u.barkod].filter(Boolean).join(' · '))}</div></td>
        <td class="s">${u.fiyat != null ? para(u.fiyat, 2) : '–'}</td><td class="s">${u.goz}</td><td>${urunSimdi(u)}</td>
        <td class="s">${u.bos_sn ? sure(u.bos_sn) : '–'}</td><td class="s">${sayi(u.alma)}</td><td class="s">${u.kayip_adet ? `<b>${para(u.kayip_tutar)}</b><div class="not">${sayi(u.kayip_adet, 1)} adet</div>` : '–'}</td></tr>`).join('')}</tbody></table></div>`;
}
async function sayfaUrunler(q) {
  const d = await api('/api/urunler?' + donemQ());
  S.urunler = d.urunler;
  if (q.sirala) US.sirala = q.sirala;
  const kategoriler = [...new Set(d.urunler.map(u => u.kategori).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'tr'));
  const rafta = d.urunler.filter(u => u.goz).length;
  $('#sayfa').innerHTML = ust('Ürünler', `${d.urunler.length} ürün · ${rafta} ürün rafta · ${donemKucuk()}`,
    `<a class="dug" href="/api/disa/kayip-satis.xlsx?${donemQ()}">${IKON.indir}Kayıp satış</a><button class="dug ana" data-is="urun-yeni">${IKON.arti}Ürün ekle</button>`)
    + (d.urunler.length ? `<div class="izgara dortlu bosluk-alt">
        ${kpi('Şimdi boş olan ürün', sayi(d.urunler.filter(u => u.bos_simdi).length), `${sayi(d.urunler.filter(u => u.az_simdi).length)} üründe azalan göz`, { uyari: d.urunler.some(u => u.bos_simdi) })}
        ${kpi(`Kayıp satış ${tahminRozeti}`, para(d.toplam.kayip_tutar), `${sayi(d.toplam.kayip_adet, 1)} adet · ${donemKucuk()}`)}
        ${kpi('Etiket sorunu', sayi(d.urunler.filter(u => u.fiyat_sorun).length), 'fiyat farklı ya da etiket yok')}
        ${kpi('Referans görseli olmayan', sayi(d.urunler.filter(u => !(u.gorseller || []).length).length), 'ürün tanıma için görsel ekleyin')}</div>
      <div class="kart"><div class="kart-bas" style="flex-wrap:wrap"><input class="cip" id="urun-ara" type="search" placeholder="Ürün adı ya da barkod" value="${h(US.ara)}" aria-label="Ürün ara" style="min-width:220px">
          <select class="cip" data-degis="urun-kategori" aria-label="Kategori"><option value="">Bütün kategoriler</option>${kategoriler.map(k => `<option ${US.kategori === k ? 'selected' : ''}>${h(k)}</option>`).join('')}</select>
          <select class="cip" data-degis="urun-sirala" aria-label="Sıralama">${[['ad', 'Ada göre'], ['sorun', 'Şimdiki soruna göre'], ['kayip', 'Kayıp satışa göre'], ['bos', 'Boş kalmaya göre'], ['alma', 'Almaya göre']].map(([v, a]) => `<option value="${v}" ${US.sirala === v ? 'selected' : ''}>${a}</option>`).join('')}</select>
          <span style="flex:1"></span><div class="grup">${[['tablo', 'Tablo'], ['kart', 'Kartlar']].map(([v, a]) => `<button class="${US.gorunum === v ? 'secili' : ''}" data-is="urun-gorunum" data-v="${v}">${a}</button>`).join('')}</div></div>
        <div id="urun-liste"></div></div>`
      : `<div class="bos-durum"><h3>Katalog boş</h3><p>Rafta izlenecek ürünleri ekleyin: ad, barkod, fiyat ve her ürünün bir ya da birkaç referans görseli (raftaki ürünün kameradan kırpılmış görüntüsü ya da kendi çektiğiniz fotoğraf).</p><div class="eylemler"><button class="dug ana" data-is="urun-yeni">Ürün ekle</button><button class="dug" data-is="ornek-yukle">Örnek verilerle dene</button></div></div>`);
  urunListesiCiz();
  if (q.id) urunCekmecesi(q.id);
}
function urunCekmecesi(id) {
  const u = id ? (S.urunler || []).find(x => x.kimlik === id) : { kimlik: '', ad: '', barkod: '', kategori: '', fiyat: null, gorseller: [], yerler: [] };
  if (!u) return bildir('Ürün bulunamadı.', true);
  const kategoriler = [...new Set((S.urunler || []).map(x => x.kategori).filter(Boolean))];
  $('#katman').innerHTML = `<aside class="cekmece form" role="dialog" aria-label="Ürün"><div class="cekmece-bas"><div><h2>${u.kimlik ? h(u.ad) : 'Yeni ürün'}</h2>${u.kimlik ? `<div class="not">${u.goz} gözde · kimlik ${h(u.kimlik)}${u.ornek ? ' · örnek' : ''}</div>` : ''}</div><button class="dug kucuk" data-is="katman-kapat">Kapat</button></div>
    <label for="u-ad">Ürün adı</label><input id="u-ad" value="${h(u.ad)}" maxlength="80" placeholder="ör. Ayran 1 L">
    <div class="satir"><div><label for="u-barkod">Barkod</label><input id="u-barkod" value="${h(u.barkod || '')}" maxlength="32" inputmode="numeric"></div>
      <div><label for="u-kategori">Kategori</label><input id="u-kategori" value="${h(u.kategori || '')}" maxlength="40" list="u-kategoriler"><datalist id="u-kategoriler">${kategoriler.map(k => `<option value="${h(k)}">`).join('')}</datalist></div>
      <div style="flex:.6"><label for="u-fiyat">Fiyat</label><input id="u-fiyat" value="${u.fiyat != null ? String(u.fiyat).replace('.', ',') : ''}" inputmode="decimal" placeholder="0,00"></div></div>
    <div class="eylemler" style="justify-content:flex-start">${u.kimlik ? `<button class="dug tehlike" data-is="urun-sil" data-id="${h(u.kimlik)}" style="margin-right:auto">Sil</button>` : ''}<button class="dug ana" data-is="urun-kaydet" data-id="${h(u.kimlik)}">Kaydet</button></div>
    ${u.kimlik ? `<div class="kart-bas" style="margin-top:18px"><h2>Referans görselleri <small>${u.gorseller.length}</small></h2>
        <label class="dug kucuk" style="margin:0;cursor:pointer">Fotoğraf yükle<input type="file" accept="image/jpeg,image/png" id="u-dosya" hidden></label><button class="dug kucuk" data-is="urun-kirp-kamera" data-id="${h(u.kimlik)}">Kameradan kırp</button></div>
      ${u.gorseller.length ? `<div class="gorseller">${u.gorseller.map(f => `<figure><img src="${gorselAdresi(f)}" alt="${h(u.ad)} görseli"><button data-is="urun-gorsel-sil" data-id="${h(u.kimlik)}" data-dosya="${h(f)}" aria-label="Görseli sil">Sil</button></figure>`).join('')}</div>` : '<div class="not">Henüz görsel yok. Ürün tanıma ve planogram uyumu için raftaki ürünün önden görünüşünü ekleyin (2-5 görsel önerilir).</div>'}
      <p class="not">Görseller yalnızca bu bilgisayarda saklanır. Kameradan kırpma yalnızca raf ve dolap bölgelerinin içinden yapılır.</p>
      <div class="kart-bas" style="margin-top:18px"><h2>Raftaki yerleri</h2></div>
      ${u.yerler.length ? `<table><thead><tr><th>Kamera · bölge · göz</th><th>Şimdi</th><th class="s">Boş kalma</th><th class="s">Alma</th><th class="s">Kayıp</th></tr></thead><tbody>${u.yerler.map(y => `<tr class="tik" data-is="git-goz" data-kamera="${h(y.kamera)}" data-goz="${h(y.goz)}"><td>${h(y.kamera_ad)} · ${h(y.bolge_ad)} · ${h(y.goz)}</td><td>${durumRozeti(y.durum)}${['farkli', 'yok'].includes(y.etiket) ? ` <span class="rozet mor">${h(ETIKET[y.etiket])}</span>` : ''}</td><td class="s">${sure(y.bos_sn)}</td><td class="s">${sayi(y.alma)}</td><td class="s">${y.kayip_adet ? para(y.kayip_tutar) : '–'}</td></tr>`).join('')}</tbody></table>`
        : '<div class="not">Bu ürün henüz bir göze atanmadı. Kamera düzenleyicisinde göze ürün seçin.</div>'}
      <div class="bilgi"><div><span class="et">Boş kalma</span><b>${sure(u.bos_sn)}</b></div><div><span class="et">Alma</span><b>${sayi(u.alma)}</b></div><div><span class="et">Kayıp ${tahminRozeti}</span><b>${para(u.kayip_tutar)}</b></div></div>` : '<p class="not">Kaydettikten sonra referans görselleri eklenir.</p>'}</aside>`;
  if (!id) $('#u-ad').focus();
  if (id) sorguDegistir({ ...konum().q, id });
}
/* Kırpma penceresi: kaynak bir görüntü (kamera karesi ya da yüklenen fotoğraf); sürükleyerek kutu çizilir. */
function kirpmaPenceresi(baslik, kaynak, kaydet, aciklama = '') {
  const k = document.createElement('div');
  k.className = 'perde'; k.id = 'kirp-perde';
  k.innerHTML = `<div class="pencere" style="width:min(900px,100%)" role="dialog" aria-modal="true"><h2>${h(baslik)}</h2><p class="not">${aciklama || 'Ürünün çevresine sürükleyerek bir kutu çizin.'}</p>
    <div class="kirpma" id="kirp"><img src="${h(kaynak)}" alt="Kırpılacak görüntü" draggable="false"><div class="kutu" hidden></div></div>
    <div class="eylemler"><button class="dug" data-c="0">Vazgeç</button><button class="dug ana" data-c="1" disabled>Kaydet</button></div></div>`;
  document.body.appendChild(k);
  const alan = k.querySelector('#kirp'), kutuE = k.querySelector('.kutu'), tamam = k.querySelector('[data-c="1"]');
  let bas = null, kutu = null;
  const nokta = e => { const r = alan.getBoundingClientRect(); return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))]; };
  const ciz_ = () => { if (!kutu) return; Object.assign(kutuE.style, { left: kutu[0] * 100 + '%', top: kutu[1] * 100 + '%', width: (kutu[2] - kutu[0]) * 100 + '%', height: (kutu[3] - kutu[1]) * 100 + '%' }); kutuE.hidden = false; };
  alan.addEventListener('pointerdown', e => { bas = nokta(e); alan.setPointerCapture(e.pointerId); });
  alan.addEventListener('pointermove', e => { if (!bas) return; const p = nokta(e); kutu = [Math.min(bas[0], p[0]), Math.min(bas[1], p[1]), Math.max(bas[0], p[0]), Math.max(bas[1], p[1])]; ciz_(); });
  alan.addEventListener('pointerup', () => { bas = null; tamam.disabled = !(kutu && kutu[2] - kutu[0] > 0.01 && kutu[3] - kutu[1] > 0.01); });
  k.addEventListener('click', async e => {
    const b = e.target.closest('[data-c]');
    if (!b) return;
    if (b.dataset.c === '0') return k.remove();
    tamam.disabled = true;
    try { await kaydet(kutu.map(v => +v.toFixed(4))); k.remove(); } catch (x) { bildir(x.message, true); tamam.disabled = false; }
  });
}
async function urunGorseliEklendi(id) {
  bildir('Görsel eklendi.');
  const d = await api('/api/urunler?' + donemQ());
  S.urunler = d.urunler; urunListesiCiz(); urunCekmecesi(id);
}
Object.assign(IS, {
  'urun-yeni': () => urunCekmecesi(null),
  'urun-ac': e => urunCekmecesi(e.dataset.id),
  'urun-gorunum': e => { US.gorunum = e.dataset.v; sakla('raf-urun-gorunum', US.gorunum); $$('[data-is="urun-gorunum"]').forEach(b => b.classList.toggle('secili', b.dataset.v === US.gorunum)); urunListesiCiz(); },
  'git-goz': e => git('raflar', { kamera: e.dataset.kamera, goz: e.dataset.goz }),
  'urun-kaydet': async e => {
    const ad = $('#u-ad').value.trim();
    if (!ad) { $('#u-ad').classList.add('hata-alan'); $('#u-ad').focus(); return bildir('Ürün adını yazın.', true); }
    const r = await api('/api/urun', { kimlik: e.dataset.id || undefined, ad, barkod: $('#u-barkod').value.trim(), kategori: $('#u-kategori').value.trim(), fiyat: $('#u-fiyat').value.trim() });
    bildir('Ürün kaydedildi.');
    if (konum().yol === 'urunler') { const d = await api('/api/urunler?' + donemQ()); S.urunler = d.urunler; urunListesiCiz(); urunCekmecesi(r.urun.kimlik); }
  },
  'urun-sil': async e => {
    const u = S.urunler.find(x => x.kimlik === e.dataset.id);
    if (!await onayla(`"${u?.ad}" silinsin mi?`, 'Ürün ve referans görselleri silinir. Planogramda kullanılıyorsa önce gözlerden kaldırılmalıdır. Bu geri alınamaz.', { tamam: 'Sil', tehlike: true })) return;
    await api('/api/urun/sil', { kimlik: e.dataset.id }); bildir('Ürün silindi.'); IS['katman-kapat'](); ciz();
  },
  'urun-gorsel-sil': async e => {
    if (!await onayla('Görsel silinsin mi?', 'Bu referans görseli silinir.', { tamam: 'Sil', tehlike: true })) return;
    await api('/api/urun/gorsel/sil', { kimlik: e.dataset.id, dosya: e.dataset.dosya }); await urunGorseliEklendi(e.dataset.id);
  },
  'urun-kirp-kamera': async e => {
    const kams = S.durum.kameralar.filter(k => (k.temiz_kare || k.referans_karesi || k.ayar_karesi) && (k.bolge_turleri || []).some(t => t === 'raf' || t === 'dolap'));
    if (!kams.length) return bildir('Raf bölgesi çizilmiş ve karesi olan kamera yok. Önce kamerada raf bölgesini çizin.', true);
    let kam = kams[0];
    if (kams.length > 1) {
      kam = await new Promise(coz => {
        const k = document.createElement('div'); k.className = 'perde';
        k.innerHTML = `<div class="pencere"><h2>Hangi kameradan?</h2><div class="liste" style="margin-top:10px">${kams.map((c, i) => `<button class="bolge-oge" data-k="${i}">${h(c.ad)}</button>`).join('')}</div><div class="eylemler"><button class="dug" data-k="-1">Vazgeç</button></div></div>`;
        k.addEventListener('click', ev => { const b = ev.target.closest('[data-k]'); if (b) { k.remove(); coz(+b.dataset.k >= 0 ? kams[+b.dataset.k] : null); } });
        document.body.appendChild(k);
      });
      if (!kam) return;
    }
    const id = e.dataset.id;
    kirpmaPenceresi(`${kam.ad} · ürünü kırp`, kam.temiz_kare || kam.referans_karesi || kam.ayar_karesi,
      async kutu => { await api('/api/urun/gorsel', { kimlik: id, kaynak: 'kamera', kod: kam.kod, kutu }); await urunGorseliEklendi(id); },
      'Raftaki ürünün çevresine sürükleyerek kutu çizin. Kutu raf ya da dolap bölgesinin içinde olmalıdır.');
  },
});
Object.assign(DEGIS, {
  'urun-kategori': e => { US.kategori = e.value; urunListesiCiz(); },
  'urun-sirala': e => { US.sirala = e.value; urunListesiCiz(); },
});
document.addEventListener('input', ev => { if (ev.target.id === 'urun-ara') { US.ara = ev.target.value; urunListesiCiz(); } });
document.addEventListener('change', ev => {
  const e = ev.target;
  if (e.id !== 'u-dosya' || !e.files[0]) return;
  const dosya = e.files[0], id = $('[data-is="urun-kaydet"]')?.dataset.id;
  if (dosya.size > 3.5e6) return bildir('Fotoğraf çok büyük (en çok 3,5 MB).', true);
  const o = new FileReader();
  o.onload = () => kirpmaPenceresi('Fotoğraftan kırp', o.result, async kutu => { await api('/api/urun/gorsel', { kimlik: id, kaynak: 'dosya', veri: o.result, kutu }); await urunGorseliEklendi(id); },
    'Ürünün çevresine kutu çizin. Fotoğraf yalnızca bu bilgisayarda saklanır.');
  o.readAsDataURL(dosya);
});

/* ------------------------------------------------------------ Müşteri */
const MS = { katman: 'yogunluk' };
async function sayfaMusteri(q) {
  const kamera = q.kamera || '';
  const d = await api('/api/musteri?' + donemQ({ kamera }));
  S.musteri = d;
  const hu = d.huni, t = d.toplam, [a, b] = calismaSaatleri();
  const kamSec = `<select class="cip" data-degis="musteri-kamera" aria-label="Kamera"><option value="">Bütün kameralar</option>${S.durum.kameralar.map(k => `<option value="${h(k.kod)}" ${kamera === k.kod ? 'selected' : ''}>${h(k.ad)}</option>`).join('')}</select>`;
  if (!t.gecen && !t.giren && !hu.gecen) {
    $('#sayfa').innerHTML = ust('Müşteri', 'yoğunluk, bekleme, huni ve dağılım', kamSec) + (S.durum.kameralar.length ? '<div class="bos-durum"><h3>Bu dönemde müşteri sayımı yok</h3><p>Koridor, raf, kasa ve giriş bölgeleri çizilmiş kameralar çalıştıkça burada yoğunluk haritası, bekleme süresi ve alışveriş hunisi görünür.</p></div>' : ornekVeriDavet('Henüz müşteri verisi yok'));
    return;
  }
  const dem = d.demografi, yogun = d.yogun_saatler;
  const saatler = d.saatlik.filter(x => x.saat >= a && x.saat < b);
  const harita = d.harita;
  $('#sayfa').innerHTML = ust('Müşteri', `${kamera ? h(kameraAdi(kamera)) : 'Bütün kameralar'} · ${donemKucuk()} · kişi kaydı yok, yalnızca toplu sayılar`,
    kamSec + `<a class="dug" href="/api/disa/trafik.xlsx?${donemQ()}">${IKON.indir}Trafik</a>`)
    + `<div class="izgara dortlu bosluk-alt">
      ${kpi('Ziyaretçi', d.giris_var ? sayi(t.giren) : '–', d.giris_var ? `günde ort. ${sayi(t.giren / d.gun_sayisi)} · çıkan ${sayi(t.cikan)}` : 'giriş sayımı yok')}
      ${kpi('Raf önünde ort. bekleme', sure(t.ort_bekleme_sn), `ortanca ${sure(d.bekleme.medyan)}`)}
      ${kpi('Durma oranı', hu.gecen ? yuzde(hu.duran / hu.gecen) : '–', `alma oranı ${hu.gecen ? yuzde(hu.alan / hu.gecen) : '–'} (geçenlere göre)`)}
      ${kpi('En yoğun saatler', yogun.length ? yogun.map(y => saatEt(y.saat).slice(0, 2)).join(', ') : '–', `en uzun kuyruk ${t.kuyruk_en_cok == null ? '–' : t.kuyruk_en_cok + ' kişi'}`)}</div>`
    + `<div class="izgara iki bosluk-alt"><div class="kart"><div class="kart-bas" style="flex-wrap:wrap"><h2>Yoğunluk haritası <small>${h(kameraAdi(harita.kamera || ''))}</small></h2>
          ${d.harita_kameralari.length > 1 && !kamera ? `<select class="cip" data-degis="harita-kamera" aria-label="Harita kamerası">${d.harita_kameralari.map(k => `<option value="${h(k)}" ${harita.kamera === k ? 'selected' : ''}>${h(kameraAdi(k))}</option>`).join('')}</select>` : ''}
          <div class="grup">${[['yogunluk', 'Yoğunluk'], ['durma', 'Durma']].map(([v, ad]) => `<button class="${MS.katman === v ? 'secili' : ''}" data-is="harita-katman" data-v="${v}">${ad}</button>`).join('')}</div></div>
        ${harita.gen ? `<div class="sahne" id="harita">${harita.kare ? `<img src="${h(harita.kare)}" alt="Kameranın son karesi (yüzler gizli)" style="filter:saturate(.6) brightness(.85)">` : '<div class="bosyazi"></div>'}<canvas aria-hidden="true"></canvas>
          <svg viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true">${(harita.bolgeler || []).filter(x => x.poly).map(x => `<polygon points="${x.poly.map(p => `${p[0] * 1000},${p[1] * 1000}`).join(' ')}" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="1.5" stroke-dasharray="6 4" vector-effect="non-scaling-stroke"><title>${h(x.ad)}</title></polygon>`).join('')}</svg></div>
          <div class="not" style="margin-top:8px;display:flex;gap:10px;align-items:center">Az<span style="display:inline-block;width:120px;height:8px;border-radius:4px;background:linear-gradient(90deg,#ffeda0,#feb24c,#f03b20,#960028)"></span>Çok · ${MS.katman === 'durma' ? 'duran kişi-saniye' : 'kişi-saniye'}, dönem toplamı</div>`
          : '<div class="grafik-bos" style="height:240px">Bu dönemde ısı haritası verisi yok.</div>'}</div>
      <div class="kart"><div class="kart-bas"><h2>Alışveriş hunisi</h2></div>${G.yer(G.huni([{ ad: 'Geçti', n: hu.gecen }, { ad: 'Durdu', n: hu.duran }, { ad: 'Uzandı', n: hu.uzanan }, { ad: 'Aldı', n: hu.alan }]))}
        <p class="not">${kamera ? 'Seçili kameradaki farklı kişiler.' : 'Raf ve dolap bölgelerinin toplamı: aynı kişi birden çok bölgede sayılabilir.'} "Aldı": rafa uzanıp ürünle ayrılan.</p>
        <div class="kart-bas" style="margin-top:14px"><h2>Rafa göre alma oranı <small>alan / geçen</small></h2></div>
        ${G.yer(G.yatay(d.bolgeler.filter(r => ['raf', 'dolap'].includes(r.tur) && r.gecen).sort((x, y) => (y.alma_orani || 0) - (x.alma_orani || 0)).slice(0, 6).map(r => ({ ad: r.ad, alt: r.kamera_ad, n: r.alma_orani || 0 })), { bicim: v => yuzde(v, 1), bosMetin: 'Raf bölgesi sayımı yok.' }))}</div></div>`
    + `<div class="izgara uclu bosluk-alt"><div class="kart"><div class="kart-bas"><h2>Raf önünde durma süresi</h2></div>
        ${G.yer(G.sutun({ etiketler: d.bekleme.dagilim.map(k => k.ust == null ? `${k.alt}+ sn` : `${k.alt}-${k.ust}`), seriler: [{ ad: 'Durma', degerler: d.bekleme.dagilim.map(k => k.n), renk: G.RENK.mavi }], yukseklik: 170, bosMetin: 'Durma kaydı yok.' }))}</div>
      <div class="kart"><div class="kart-bas"><h2>Yaş grubu ${'<span class="tahmin" title="Gövde görünümünden tahmin; yalnızca toplu sayı">tahmin</span>'}</h2></div>
        ${G.yer(G.halka([{ ad: 'Genç', n: dem.yas_genc, renk: '#7fc8bd' }, { ad: 'Yetişkin', n: dem.yas_yetiskin, renk: G.RENK.ana }, { ad: 'Yaşlı', n: dem.yas_yasli, renk: '#3c4744' }], { orta: '', bosMetin: 'Veri yok.' }))}
        <p class="not">Gövde görünümünden tahmin. Kişi bazında kayıt yoktur.</p></div>
      <div class="kart"><div class="kart-bas"><h2>Cinsiyet ${'<span class="tahmin" title="Gövde görünümünden tahmin; yalnızca toplu sayı">tahmin</span>'}</h2></div>
        ${G.yer(G.halka([{ ad: 'Kadın', n: dem.kadin, renk: G.RENK.mor }, { ad: 'Erkek', n: dem.erkek, renk: G.RENK.mavi }], { bosMetin: 'Veri yok.' }))}
        <p class="not">Gövde görünümünden tahmin; yalnızca toplu oran.</p></div></div>`
    + `<div class="izgara ikili bosluk-alt"><div class="kart"><div class="kart-bas"><h2>${d.giris_var ? 'Saate göre giriş ve çıkış' : 'Saate göre geçen kişi'} <small>günlük ortalama</small></h2></div>
        ${G.yer(G.sutun({ etiketler: saatler.map(x => saatEt(x.saat)), seriler: d.giris_var ? [{ ad: 'Giren', degerler: saatler.map(x => x.giren), renk: G.RENK.ana }, { ad: 'Çıkan', degerler: saatler.map(x => x.cikan), renk: G.RENK.ana2 }] : [{ ad: 'Geçen', degerler: saatler.map(x => x.gecen), renk: G.RENK.ana }], yukseklik: 190, bicim: v => sayi(v, 1) }))}</div>
      <div class="kart"><div class="kart-bas"><h2>Haftanın günü ve saat <small>${d.giris_var ? 'giren' : 'geçen'} kişi</small></h2></div>
        ${G.yer(G.matris(d.haftalik, { satirlar: GUNLER, sutunlar: Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0')), sutunBas: a, sutunBit: b, bicim: v => sayi(v) + ' kişi' }))}</div></div>`
    + `<div class="kart bosluk-alt"><div class="kart-bas"><h2>Bölgeler</h2></div>${d.bolgeler.length ? `<div style="overflow:auto"><table><thead><tr><th>Bölge</th><th>Kamera</th><th class="s">Geçen</th><th class="s">Duran</th><th class="s">Uzanan</th><th class="s">Alan</th><th class="s">Durma oranı</th><th class="s">Alma oranı</th><th class="s">Ort. bekleme</th><th class="s">Rafa dönük</th><th style="width:16%"></th></tr></thead><tbody>
        ${d.bolgeler.map(r => `<tr><td><b>${h(r.ad)}</b> <span class="not">${h(S.katalog.bolge_turleri[r.tur] || r.tur)}</span></td><td class="not">${h(r.kamera_ad)}</td><td class="s">${sayi(r.gecen)}</td><td class="s">${sayi(r.duran)}</td><td class="s">${sayi(r.uzanan)}</td><td class="s">${sayi(r.alan)}</td>
          <td class="s">${yuzde(r.durma_orani)}</td><td class="s">${yuzde(r.alma_orani, 1)}</td><td class="s">${sure(r.ort_bekleme_sn)}</td><td class="s">${sure(r.ilgi_sn)}</td><td><div class="cubuk"><i style="width:${100 * r.gecen / Math.max(1, d.bolgeler[0].gecen)}%"></i></div></td></tr>`).join('')}</tbody></table></div>` : '<div class="not">Bölge sayımı yok.</div>'}</div>`
    + `<div class="kart"><div class="kart-bas"><h2>Günlük ${d.giris_var ? 'ziyaretçi' : 'trafik'}</h2></div>${G.yer(G.cizgi({ etiketler: d.gunluk.map(x => gunAdi(x.gun)), seriler: d.giris_var ? [{ ad: 'Ziyaretçi', degerler: d.gunluk.map(x => x.giren), renk: G.RENK.ana, alan: true }] : [{ ad: 'Geçen', degerler: d.gunluk.map(x => x.gecen), renk: G.RENK.ana, alan: true }], yukseklik: 170 }))}</div>`;
  haritaCiz();
}
function haritaCiz() {
  const k = $('#harita');
  if (!k || !S.musteri?.harita?.gen) return;
  const ciz_ = () => G.isiHaritasi(k.querySelector('canvas'), S.musteri.harita, MS.katman);
  const img = k.querySelector('img');
  if (img && !img.complete) img.onload = ciz_; else ciz_();
}
window.addEventListener('resize', () => { if (konum().yol === 'musteri') haritaCiz(); });
Object.assign(IS, { 'harita-katman': e => { MS.katman = e.dataset.v; $$('[data-is="harita-katman"]').forEach(b => b.classList.toggle('secili', b.dataset.v === MS.katman)); haritaCiz(); } });
Object.assign(DEGIS, {
  'musteri-kamera': e => { const q = konum().q; if (e.value) q.kamera = e.value; else delete q.kamera; git('musteri', q); },
  'harita-kamera': e => git('musteri', { ...konum().q, kamera: e.value }),
});

/* ------------------------------------------------------------ Raporlar */
async function sayfaRaporlar() {
  const d = await api('/api/rapor-ozeti?' + donemQ());
  const su = d.su, on = d.once, g = S.durum.genel;
  const satir = (ad, a, b, bicim, ters, aciklama) => `<tr><td>${ad}${aciklama ? ` <span class="not">${aciklama}</span>` : ''}</td><td class="s"><b>${bicim(a)}</b></td><td class="s">${bicim(b)}</td><td class="s">${fark(a, b, ters, bicim) || '–'}</td></tr>`;
  const [ca, cb] = calismaSaatleri();
  const disa = Object.entries(S.katalog.disa_tablolar || {});
  $('#sayfa').innerHTML = ust('Raporlar', `${h(d.tesis)} · ${tarih(d.bas).replace(' 00:00', '')} – ${tarih(d.bit).replace(' 23:59', '')} · önceki dönemle karşılaştırma`,
    `<button class="dug" data-is="yazdir">${IKON.yazdir}Yazdır</button><a class="dug ana" href="/api/disa/hepsi.xlsx?${donemQ()}">${IKON.indir}Excel (bütün tablolar)</a>`)
    + `<div class="yazdir-baslik"><h2 style="margin:0">${h(d.tesis)}${g.sube ? ' · ' + h(g.sube) : ''} · ${S.donem.gun === 1 ? 'Günlük' : 'Dönem'} raporu</h2><div>${h(g.adres || '')}</div><div>${d.bas.slice(0, 10)} – ${d.bit.slice(0, 10)} · çalışma saatleri ${h(d.calisma?.bas || '')}–${h(d.calisma?.bit || '')} · hazırlandı ${new Date().toLocaleString('tr-TR')}</div></div>`
    + `<div class="izgara iki bosluk-alt"><div class="kart"><div class="kart-bas"><h2>Özet <small>önceki dönem: ${d.obas.slice(0, 10)} – ${d.obit.slice(0, 10)}</small></h2></div>
        <div class="tablo-kap"><table><thead><tr><th>Ölçü</th><th class="s">Bu dönem</th><th class="s">Önceki</th><th class="s">Değişim</th></tr></thead><tbody>
        ${satir('Ziyaretçi', su.ziyaretci, on.ziyaretci, v => sayi(v))}
        ${satir('Rafta duran müşteri', su.duran, on.duran, v => sayi(v))}
        ${satir('Ürün alan', su.alan, on.alan, v => sayi(v))}
        ${satir('Raf önünde ort. bekleme', su.ort_bekleme_sn, on.ort_bekleme_sn, v => sure(v))}
        ${satir('Raf doluluğu', su.doluluk, on.doluluk, v => yuzde(v))}
        ${satir('Planogram uyumu', su.uyum, on.uyum, v => yuzde(v))}
        ${satir('Boş raf süresi', su.bos_saat, on.bos_saat, v => v == null ? '–' : sayi(v, 1) + ' sa', true, 'göz-saat')}
        ${satir(`Kayıp satış ${tahminRozeti}`, su.kayip_tutar, on.kayip_tutar, v => para(v), true)}
        ${satir(`Kayıp adet ${tahminRozeti}`, su.kayip_adet, on.kayip_adet, v => sayi(v, 1), true)}
        ${satir('Ort. raf doldurma', su.dolum_ort_sn, on.dolum_ort_sn, v => sure(v), true)}
        ${satir('Ort. görev tepkisi', su.gorev_tepki_sn, on.gorev_tepki_sn, v => sure(v), true)}
        ${satir('Uyarı', su.olay, on.olay, v => sayi(v), true)}
        ${satir('En uzun kuyruk', su.kuyruk_en_cok, on.kuyruk_en_cok, v => v == null ? '–' : sayi(v) + ' kişi', true)}</tbody></table></div></div>
      <div class="izgara" style="gap:14px;align-content:start"><div class="kart"><div class="kart-bas"><h2>Günlük ziyaretçi ve doluluk</h2></div>
          ${G.yer(G.sutun({ etiketler: d.gunluk.map(x => gunAdi(x.gun)), seriler: [{ ad: 'Ziyaretçi', degerler: d.gunluk.map(x => x.giren || x.gecen), renk: G.RENK.ana }], yukseklik: 160 }))}
          ${G.yer(G.cizgi({ etiketler: d.gunluk.map(x => gunAdi(x.gun)), seriler: [{ ad: 'Doluluk', degerler: d.gunluk.map(x => x.doluluk), renk: G.RENK.mavi }], enAz: 0, enCok: 1, bicim: v => yuzde(v), yukseklik: 120 }))}</div>
        <div class="kart"><div class="kart-bas"><h2>Saate göre boş raf <small>göz-dakika</small></h2></div>
          ${G.yer(G.sutun({ etiketler: d.saatlik_bos_dk.slice(ca, cb).map((_, i) => saatEt(ca + i)), seriler: [{ ad: 'Boş göz-dakika', degerler: d.saatlik_bos_dk.slice(ca, cb), renk: G.RENK.kirmizi }], yukseklik: 150, bicim: v => sayi(v) + ' dk', bosMetin: 'Bu dönemde boş kalan göz yok.' }))}</div></div></div>`
    + `<div class="izgara ikili bosluk-alt"><div class="kart"><div class="kart-bas"><h2>En çok kayıp satış ${tahminRozeti}</h2></div>
        ${d.en_kayip.some(x => x.kayip_adet) ? `<div class="tablo-kap"><table><thead><tr><th>Ürün</th><th class="s">Boş kalma</th><th class="s">Alma</th><th class="s">Kayıp adet</th><th class="s">Tutar</th></tr></thead><tbody>${d.en_kayip.filter(x => x.kayip_adet).map(x => `<tr><td>${h(x.ad)}</td><td class="s">${sure(x.bos_sn)}</td><td class="s">${sayi(x.alma)}</td><td class="s">${sayi(x.kayip_adet, 1)}</td><td class="s"><b>${para(x.kayip_tutar)}</b></td></tr>`).join('')}</tbody></table></div>` : '<div class="not">Bu dönemde boş kalan göz yok.</div>'}</div>
      <div class="kart"><div class="kart-bas"><h2>En uzun boş kalan gözler</h2></div>
        ${d.en_bos.length ? `<div class="tablo-kap"><table><thead><tr><th>Ürün</th><th>Yer</th><th class="s">Boş kalma</th><th class="s">Kayıp</th></tr></thead><tbody>${d.en_bos.map(x => `<tr><td>${h(x.urun_ad || '–')}</td><td class="not">${h(x.kamera_ad)} · ${h(x.bolge_ad)}</td><td class="s">${sure(x.bos_sn)}</td><td class="s">${x.kayip_tutar != null ? para(x.kayip_tutar) : sayi(x.kayip_adet, 1)}</td></tr>`).join('')}</tbody></table></div>` : '<div class="not">Bu dönemde boş kalan göz yok.</div>'}</div></div>`
    + `<div class="kart bosluk-alt"><div class="kart-bas"><h2>Günlük tablo</h2></div><div style="overflow:auto"><table><thead><tr><th>Gün</th><th class="s">Ziyaretçi</th><th class="s">Geçen (kamera)</th><th class="s">Ürün alan</th><th class="s">Doluluk</th><th class="s">Boş raf (göz-dk)</th><th class="s">Uyarı</th></tr></thead><tbody>
        ${d.gunluk.map(x => `<tr><td>${gunAdi(x.gun)} <span class="not">${GUNLER[(new Date(x.gun + 'T12:00:00').getDay() + 6) % 7]}</span></td><td class="s">${sayi(x.giren)}</td><td class="s">${sayi(x.gecen)}</td><td class="s">${sayi(x.alan)}</td><td class="s">${yuzde(x.doluluk)}</td><td class="s">${sayi(x.bos_dk)}</td><td class="s">${sayi(x.olay)}</td></tr>`).join('')}</tbody></table></div></div>`
    + `<div class="kart yazdirma"><div class="kart-bas"><h2>Dışa aktar <small>${donemKucuk()}</small></h2></div><table>${disa.map(([ad, baslik]) => `<tr><td>${h(baslik)}</td><td class="s" style="white-space:nowrap"><a class="dug kucuk" href="/api/disa/${ad}.xlsx?${donemQ()}">Excel</a> <a class="dug kucuk" href="/api/disa/${ad}.csv?${donemQ()}">CSV</a></td></tr>`).join('')}</table>
      <p class="not">Kayıp satış bir tahmindir: gözün boş kaldığı çalışma süresi × o gözün (yeterli geçmiş yoksa bölgesinin) alma hızı. Süreler çalışma saatlerine göredir.</p></div>`;
}
