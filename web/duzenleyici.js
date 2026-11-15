'use strict';
/* Kamera düzenleyici: bağlantı, bölgeler ve planogram (raf gözleri, ürün, beklenen yüz sayısı, etiket kutusu, fiyat),
   kamera başına özellikler. Koordinatlar 0-1 aralığındadır (karenin genişliği ve yüksekliğine oranlı).
   Bölge ve göz kimliklerini sunucu verir (kaydedince); var olan kimlikler değişmez. */

const BOLGE_RENK = { raf: '#8fd14f', koridor: '#5bb8c9', kasa: '#f2b33d', dolap: '#3c8ce6', giris: '#ff8a3d' };
const bolgeRengi = tur => BOLGE_RENK[tur] || '#bbbbbb';
const D = { ayar: null, kod: '', yeni: false, sekme: 'planogram', mod: 'sec', tur: 'raf', sb: null, sg: null, cizim: [], surukle: null, geri: [], degisti: false, kare: null, oneriler: null, yol: '' };
const AYAR_ADLARI = { sure_sn: 'Süre (sn)', esik: 'Eşik', oran: 'Oran', en_az: 'En az', en_cok: 'En çok', dakika: 'Dakika', adet: 'Adet', kisi: 'Kişi', benzerlik: 'Benzerlik', doluluk: 'Doluluk', aralik_sn: 'Aralık (sn)', bekleme_sn: 'Bekleme (sn)' };
const ayarAdi = a => AYAR_ADLARI[a] || (a.charAt(0).toLocaleUpperCase('tr') + a.slice(1)).replace(/_sn$/, ' (sn)').replace(/_/g, ' ');

function ayrilmaKorumasi(yol) {
  // kaydedilmemiş düzenleme varken başka sayfaya geçilirse sorulur
  if (!D.degisti || !D.yol || yol === D.yol) return true;
  if (window.confirm('Kaydedilmemiş değişiklikler var. Kaydetmeden çıkılsın mı?')) { D.degisti = false; return true; }
  location.hash = '#/' + D.yol;
  return false;
}
window.addEventListener('beforeunload', e => { if (D.degisti) { e.preventDefault(); e.returnValue = ''; } });
{ // yönlendirmeden önce koruma: uyg.js'teki ciz() çağrılmadan önce sorulur
  const asil = ciz;
  ciz = async function (sessiz) {  // eslint-disable-line no-global-assign
    const k = konum();
    if (!ayrilmaKorumasi(k.yol)) return;
    if (D.degisti && k.yol === D.yol && $('#k-planogram')) return;  // düzenleyici açık: yeniden çizip değişiklikleri silme
    return asil(sessiz);
  };
}

function kareSec(bilgi) {
  // motorun temiz karesi (yüzler gizli, çizim yok), yoksa referans kare, yoksa bağlantı denemesinin karesi; son_kare (çizimli) kullanılmaz
  return bilgi?.temiz_kare || bilgi?.referans_karesi || bilgi?.ayar_karesi || null;
}
async function sayfaKamera(kod, q) {
  const K = S.katalog;
  const yeni = kod === 'yeni';
  let ayar = { ad: '', kod: '', kamera: { tur: 'rtsp', marka: 'hikvision', port: 554, kanal: 1, akis: 'alt', kullanici: 'admin' }, bolgeler: [], ozellikler: {} };
  if (!yeni) ayar = await api('/api/ayar/' + encodeURIComponent(kod));
  ayar.bolgeler = ayar.bolgeler || [];
  ayar.ozellikler = ayar.ozellikler || {};
  const bilgi = S.durum.kameralar.find(k => k.kod === kod);
  if (!S.urunler) { try { S.urunler = (await api('/api/urunler?gun=1')).urunler; } catch (x) { S.urunler = []; } }
  Object.assign(D, { ayar, kod, yeni, sekme: q.sekme || (yeni ? 'baglanti' : 'planogram'), mod: 'sec', sb: null, sg: null, cizim: [], surukle: null, geri: [], degisti: false, oneriler: null,
    kare: D.yerelKod === kod && D.yerelKare ? D.yerelKare : kareSec(bilgi), yol: konum().yol, ornek: !!ayar.ornek });
  if (q.goz) {
    ayar.bolgeler.forEach((b, i) => (b.gozler || []).forEach((g, j) => { if (g.kimlik === q.goz) { D.sb = i; D.sg = j; } }));
  } else if (ayar.bolgeler.length) D.sb = ayar.bolgeler.findIndex(b => b.tur === 'raf' || b.tur === 'dolap') >= 0 ? ayar.bolgeler.findIndex(b => b.tur === 'raf' || b.tur === 'dolap') : 0;
  const k = ayar.kamera || {};
  $('#sayfa').innerHTML = ust(yeni ? 'Kamera ekle' : ayar.ad || kod, yeni ? 'bağlantı, sonra bölgeler ve planogram' : `bağlantı, bölgeler, planogram ve özellikler${ayar.ornek ? ' · örnek kamera' : ''}`,
    `<span class="not" id="kaydedilmedi" hidden>Kaydedilmemiş değişiklik var</span><a class="dug" href="#/kameralar">← Kameralar</a><button class="dug ana" data-is="kamera-kaydet">Kaydet</button>`)
    + `<div class="sekmeler" role="tablist">${[['baglanti', 'Bağlantı'], ['planogram', 'Bölgeler ve planogram'], ['ozellikler', 'Özellikler']].map(([v, a]) => `<button role="tab" aria-selected="${D.sekme === v}" class="${D.sekme === v ? 'secili' : ''}" data-is="k-sekme" data-v="${v}">${a}</button>`).join('')}</div>`
    + `<div id="k-baglanti" class="izgara iki" ${D.sekme === 'baglanti' ? '' : 'hidden'}><div class="kart form"><div class="kart-bas"><h2>Bağlantı</h2></div>
        <div class="satir"><div><label for="k-ad">Kamera adı</label><input id="k-ad" value="${h(ayar.ad || '')}" placeholder="ör. İçecek rafı" maxlength="80"></div><div><label for="k-kod">Kısa kod</label><input id="k-kod" value="${h(ayar.kod || (yeni ? '' : kod))}" ${yeni ? '' : 'disabled'} placeholder="icecek1" maxlength="40"></div></div>
        <label for="k-tur">Bağlantı türü</label><select id="k-tur" data-degis="kamera-tur">${[['rtsp', 'IP kamera / kayıt cihazı – NVR, DVR (RTSP, markaya göre)'], ['onvif', 'ONVIF kamera / kayıt cihazı (adres cihazdan öğrenilir)'], ['http', 'HTTP akışı (MJPEG)'], ['dosya', 'Video dosyası']].map(([t, a]) => `<option value="${t}" ${k.tur === t ? 'selected' : ''}>${a}</option>`).join('')}</select>
        <div data-tur="rtsp"><label for="k-marka">Marka</label><select id="k-marka">${Object.entries(K.markalar).map(([m, a]) => `<option value="${m}" ${k.marka === m && !k.adres ? 'selected' : ''}>${h(a)}</option>`).join('')}<option value="" ${k.adres ? 'selected' : ''}>Diğer (tam adres)</option></select>
          <div class="satir"><div><label for="k-ip">IP adresi</label><input id="k-ip" value="${h(k.ip || '')}"></div><div style="flex:.5"><label for="k-port">Port</label><input id="k-port" value="${h(k.port ?? 554)}"></div></div>
          <div class="satir"><div><label for="k-kanal">Kanal</label><input id="k-kanal" value="${h(k.kanal ?? 1)}"></div><div><label for="k-akis">Akış</label><select id="k-akis"><option value="alt" ${k.akis !== 'ana' ? 'selected' : ''}>Alt akış (önerilen)</option><option value="ana" ${k.akis === 'ana' ? 'selected' : ''}>Ana akış</option></select></div></div>
          <p class="not" style="margin:6px 0 0">Kayıt cihazında (NVR / DVR) IP adresi cihazın adresidir; <b>kanal</b>, kameranın cihazdaki sırasıdır. Her kanal ayrı bir kamera olarak eklenir.</p>
          <div class="satir" style="align-items:flex-end"><div style="flex:.5"><label for="k-kanal-sayisi">Kayıt cihazındaki kanal sayısı</label><input id="k-kanal-sayisi" type="number" min="2" max="64" placeholder="ör. 8"></div>
            <div><button class="dug kucuk" data-is="nvr-kanallari-ekle">Kanalları ayrı kameralar olarak ekle</button></div></div></div>
        <div data-tur="rtsp http"><label for="k-adres">Tam adres (şifre yerine {sifre}; marka seçiliyse boş bırakın)</label><input id="k-adres" value="${h(k.adres || '')}" placeholder="rtsp://{kullanici}:{sifre}@IP:554/...">
          <label for="k-kullanici">Kullanıcı adı</label><input id="k-kullanici" value="${h(k.kullanici || 'admin')}" autocomplete="off"></div>
        <div data-tur="onvif"><div class="satir"><div><label for="o-ip">Cihazın IP adresi</label><input id="o-ip" value="${h(k.ip || '')}"></div><div style="flex:.5"><label for="o-port">ONVIF portu</label><input id="o-port" value="${h(k.tur === 'onvif' ? k.port ?? 80 : 80)}"></div>
            <div style="flex:none;align-self:flex-end"><button class="dug kucuk" data-is="onvif-kesfet">Ağda ara</button></div></div>
          <div class="satir"><div><label for="o-kullanici">Kullanıcı adı</label><input id="o-kullanici" value="${h(k.kullanici || 'admin')}" autocomplete="off"></div>
            <div style="flex:.5"><label for="o-kanal">Kanal</label><input id="o-kanal" type="number" min="1" value="${h(k.kanal ?? 1)}"></div>
            <div><label for="o-akis">Akış</label><select id="o-akis"><option value="alt" ${k.akis !== 'ana' ? 'selected' : ''}>Alt akış (önerilen)</option><option value="ana" ${k.akis === 'ana' ? 'selected' : ''}>Ana akış</option></select></div></div>
          <label for="o-profil">Profil</label><select id="o-profil"><option value="">Kendiliğinden (yalnızca tek kanallı kamera): seçilen akış</option>${k.tur === 'onvif' && k.profil ? `<option value="${h(k.profil)}" data-ad="${h(k.profil_ad || '')}" data-kaynak="${h(k.kaynak || '')}" selected>${h(k.profil_ad || k.profil)}</option>` : ''}</select>
          <div class="satir" style="align-items:flex-end;margin-top:8px"><div><label for="o-sifre">Şifre (yalnızca listelemek için; kaydedilmez)</label><input id="o-sifre" type="password" autocomplete="off"></div>
            <div style="flex:none"><button class="dug kucuk" data-is="onvif-profiller">Kanalları ve profilleri listele</button></div></div>
          <div id="o-sonuc" style="margin-top:8px"></div>
          <p class="not">ONVIF'te akışın adresi cihazdan sorulur. Kayıt cihazında her kanal ayrı bir kamera olarak eklenir ve profili listeden seçmek zorunludur.</p></div>
        <div data-tur="dosya"><label for="k-yol">Video dosyası (tam yol ya da veri klasörüne göre)</label><input id="k-yol" value="${h(k.yol || '')}" placeholder="videolar/kayit.mp4">
          <label for="k-baslangic">Kaydın başlangıç zamanı (isteğe bağlı)</label><input id="k-baslangic" type="datetime-local" value="${h((k.baslangic || '').slice(0, 16))}"></div>
        <p class="not">Şifre buraya yazılmaz ve kaydedilmez; bağlanırken Kameralar ekranındaki şifre kutusuna yazılır.</p></div>
      <div class="kart"><div class="kart-bas"><h2>Sonraki adımlar</h2></div><ol style="margin:0;padding-left:18px;line-height:1.8">
        <li>Bağlantıyı kaydedin, Kameralar ekranında <b>Bağlantıyı dene</b> ile bir kare alın.</li><li><b>Bölgeler ve planogram</b> sekmesinde raf, koridor, kasa, dolap ve giriş bölgelerini çizin.</li>
        <li>Raf bölgesini gözlere bölün, her göze ürününü, beklenen yüz sayısını ve fiyatını yazın.</li><li>Raf doluyken <b>Rafı dolu olarak kaydet</b>'e basın.</li><li><b>Özellikler</b> sekmesinde bu kamerada çalışacakları seçin.</li></ol></div></div>`
    + `<div id="k-planogram" ${D.sekme === 'planogram' ? '' : 'hidden'}><div class="duzen"><div><div class="kart"><div class="arac" id="arac"></div><div id="cizim-alani"></div><div id="cizim-ipucu" class="ipucu"></div></div>
        <div id="oneri-alani"></div></div><div id="yan-panel"></div></div></div>`
    + `<div id="k-ozellikler" ${D.sekme === 'ozellikler' ? '' : 'hidden'}>${ozellikSekmesi()}</div>`;
  kameraTuruGoster();
  duzenleyiciCiz();
}
function kameraTuruGoster() {
  const t = $('#k-tur')?.value;
  $$('#k-baglanti [data-tur]').forEach(e => { if (e.tagName === 'DIV') e.style.display = e.dataset.tur.split(' ').includes(t) ? '' : 'none'; });
}

/* ------------------------------------------------------------ özellikler sekmesi (katalogdan) */
function ozellikAcikMi(k) { const o = D.ayar.ozellikler?.[k.kod]; return o && 'acik' in o ? !!o.acik : !!k.varsayilan; }
function ozellikSekmesi() {
  const K = S.katalog, turler = new Set((D.ayar.bolgeler || []).map(b => b.tur));
  const kural = r => {
    const o = D.ayar.ozellikler?.[r.kod] || {};
    const eksikTur = (r.bolge_turleri || []).length && !(r.bolge_turleri || []).some(t => turler.has(t));
    // katalogdaki ayar ya düz varsayılandır (20) ya da tanımdır ({ad, varsayilan, birim, en_az, en_cok, adim})
    const ayarlar = Object.entries(r.ayarlar || {}).map(([a, t]) => {
      const tanim = t && typeof t === 'object' && !Array.isArray(t) ? t : { varsayilan: t };
      const v = tanim.varsayilan, deger = o[a] ?? v;
      const ad = (tanim.ad || ayarAdi(a)) + (tanim.birim && !['oran', ''].includes(tanim.birim) ? ` (${tanim.birim})` : '');
      const ipucu = [tanim.en_az != null ? `en az ${tanim.en_az}` : '', tanim.en_cok != null ? `en çok ${tanim.en_cok}` : '', `varsayılan ${v}`].filter(Boolean).join(' · ');
      if (typeof v === 'boolean') return `<label class="cip" style="margin:0;cursor:pointer"><input type="checkbox" data-oz-ayar="${r.kod}:${a}" data-tip="bool" ${deger ? 'checked' : ''}> ${h(ad)}</label>`;
      if (typeof v === 'number') return `<label class="not" style="display:inline-flex;gap:6px;align-items:center;margin:0" title="${h(ipucu)}">${h(ad)}<input type="number" step="${tanim.adim ?? 'any'}" min="${tanim.en_az ?? 0}" ${tanim.en_cok != null ? `max="${tanim.en_cok}"` : ''} data-oz-ayar="${r.kod}:${a}" data-tip="sayi" value="${h(deger)}" style="width:80px;padding:3px 6px;border:1px solid var(--cizgi2);border-radius:7px"></label>`;
      return `<label class="not" style="display:inline-flex;gap:6px;align-items:center;margin:0">${h(ad)}<input data-oz-ayar="${r.kod}:${a}" data-tip="metin" value="${h(deger ?? '')}" style="width:120px;padding:3px 6px;border:1px solid var(--cizgi2);border-radius:7px"></label>`;
    }).join('');
    return `<div class="kural"><input type="checkbox" id="oz-${r.kod}" data-ozellik="${r.kod}" ${ozellikAcikMi(r) ? 'checked' : ''} ${r.model_eksik || r.durum === 'yok' ? 'disabled' : ''} style="margin-top:4px">
      <div style="flex:1"><label for="oz-${r.kod}" class="ad" style="cursor:pointer">${h(r.ad)}</label> ${ozellikDurumu(r)} ${r.olay ? '<span class="rozet gri">uyarı</span>' : ''} ${r.gorev ? '<span class="rozet gri">görev açar</span>' : ''}
        <div class="ac">${h(r.aciklama || '')}${(r.bolge_turleri || []).length ? ` · bölge: ${r.bolge_turleri.map(t => h(K.bolge_turleri[t] || t)).join(', ')}` : ''}</div>
        ${eksikTur ? `<div class="not" style="color:#7a5300">Bu kamerada ${r.bolge_turleri.map(t => h(K.bolge_turleri[t] || t)).join(' ya da ')} bölgesi yok; çizilene kadar çalışmaz.</div>` : ''}
        ${ayarlar ? `<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:6px">${ayarlar}</div>` : ''}</div></div>`;
  };
  const gruplar = Object.entries(K.kategoriler).map(([kat, ad]) => { const rs = K.kurallar.filter(r => r.kategori === kat); return rs.length ? `<div class="kart bosluk-alt"><div class="kart-bas"><h2>${h(ad)}</h2></div>${rs.map(kural).join('')}</div>` : ''; }).join('');
  return `<div class="izgara iki"><div>${gruplar || '<div class="bos-durum"><h3>Özellik listesi boş</h3><p>Analiz motorunun özellik listesi henüz gelmedi. Motor güncellenince her özellik burada açılıp kapatılır ve ayarları değiştirilir.</p></div>'}</div>
    <div class="kart form"><div class="kart-bas"><h2>Analiz hızı</h2></div>
      <label for="k-kisi-fps">Kişi analizi (kare / saniye)</label><input id="k-kisi-fps" type="number" min="0.5" max="10" step="0.5" value="${h(D.ayar.kisi_fps ?? '')}" placeholder="varsayılan (3)">
      <label for="k-raf-araligi">Raf kontrol aralığı (saniye)</label><input id="k-raf-araligi" type="number" min="1" max="3600" value="${h(D.ayar.raf_araligi_sn ?? '')}" placeholder="varsayılan (10)">
      <p class="not">Analiz yalnızca bu bilgisayarın işlemcisinde çalışır. Çok kamera izleniyorsa hızı düşürün.</p></div></div>`;
}
function ozellikleriOku() {
  const out = {};
  $$('[data-ozellik]').forEach(e => { out[e.dataset.ozellik] = { acik: e.checked }; });
  $$('[data-oz-ayar]').forEach(e => {
    const [kod, a] = e.dataset.ozAyar.split(':');
    const v = e.dataset.tip === 'bool' ? e.checked : e.dataset.tip === 'sayi' ? (e.value === '' ? undefined : +e.value) : e.value;
    if (v !== undefined) (out[kod] = out[kod] || {})[a] = v;
  });
  return Object.keys(out).length || !S.katalog.kurallar.length ? { ...(S.katalog.kurallar.length ? {} : D.ayar.ozellikler), ...out } : D.ayar.ozellikler;
}

/* ------------------------------------------------------------ çizim */
const MODLAR = [['sec', 'Seç', 'Göz ya da bölge seçin; gözü sürükleyerek taşıyın, sağ alt köşesinden boyutlandırın. Ok tuşları kaydırır, Sil tuşu siler.'],
  ['bolge', 'Bölge çiz', 'Köşelere sırayla tıklayın; bitirmek için ilk noktaya tıklayın, Enter\'a basın ya da çift tıklayın. Esc vazgeçer.'],
  ['giris', 'Giriş çizgisi', 'Sayım çizgisinin iki ucuna tıklayın, sonra mağazanın iç tarafında bir noktaya tıklayın.'],
  ['goz', 'Göz çiz', 'Raf ya da dolap bölgesinin içinde, bir ürün gözünü kapsayan kutuyu sürükleyerek çizin.'],
  ['etiket', 'Etiket çiz', 'Önce bir göz seçin, sonra o gözün fiyat etiketini kapsayan kutuyu sürükleyerek çizin.']];
function seciliBolge() { return D.sb != null ? D.ayar.bolgeler[D.sb] : null; }
function seciliGoz() { const b = seciliBolge(); return b && D.sg != null ? (b.gozler || [])[D.sg] : null; }
function degisti() { D.degisti = true; const e = $('#kaydedilmedi'); if (e) e.hidden = false; }
function geriKaydet() { D.geri.push(JSON.stringify(D.ayar.bolgeler)); if (D.geri.length > 60) D.geri.shift(); }
function duzenleyiciCiz() {
  if (!$('#arac')) return;
  const motorKapali = S.durum.gelistirme;
  const b = seciliBolge(), gozlu = b && ['raf', 'dolap'].includes(b.tur);
  $('#arac').innerHTML = `<div class="grup" role="toolbar" aria-label="Çizim kipi">${MODLAR.map(([v, ad]) => `<button class="${D.mod === v ? 'secili' : ''}" data-is="d-mod" data-v="${v}" aria-pressed="${D.mod === v}">${ad}</button>`).join('')}</div>
    ${D.mod === 'bolge' ? `<select class="cip" id="d-tur" aria-label="Bölge türü">${Object.entries(S.katalog.bolge_turleri).filter(([t]) => t !== 'giris').map(([t, a]) => `<option value="${t}" ${D.tur === t ? 'selected' : ''}>${h(a)}</option>`).join('')}</select>` : ''}
    <span class="ayrac"></span>
    <button class="dug kucuk" data-is="d-geri" ${D.geri.length ? '' : 'disabled'} title="Geri al (Ctrl+Z)">Geri al</button>
    <button class="dug kucuk" data-is="d-izgara" ${gozlu ? '' : 'disabled'} title="Seçili raf bölgesini satır ve sütunlara böler">Gözlere böl</button>
    <button class="dug kucuk" data-is="d-satir-kopyala" ${seciliGoz() ? '' : 'disabled'} title="Seçili gözün satırını bir alta kopyalar">Satırı kopyala</button>
    <span class="ayrac"></span>
    <button class="dug kucuk" data-is="d-motor" data-v="gozler" ${(b && gozlu) || D.ayar.bolgeler.some(x => ['raf', 'dolap'].includes(x.tur)) ? '' : 'disabled'} title="${motorKapali ? 'Analiz motoru bu kipte kapalı' : 'Raf bölgesindeki ürün yüzlerinden gözleri motor önerir'}">Gözleri otomatik bul</button>
    <button class="dug kucuk" data-is="d-motor" data-v="urun_tani" ${D.ayar.bolgeler.some(x => (x.gozler || []).length) ? '' : 'disabled'} title="Gözlerdeki ürünleri katalogdaki görsellerle eşleştirir">Ürünleri tanı</button>
    <button class="dug kucuk" data-is="d-motor" data-v="etiketler" ${D.ayar.bolgeler.some(x => (x.gozler || []).some(g => g.etiket)) ? '' : 'disabled'} title="Etiket kutularındaki fiyatları okur">Etiketleri oku</button>
    <span style="flex:1"></span>
    <label class="dug kucuk" style="cursor:pointer;margin:0" title="Bu bilgisayardan bir görüntü seçin (kaydedilmez, yalnızca çizim için)">Görüntü seç<input type="file" accept="image/*" id="kare-dosya" hidden></label>`;
  $('#cizim-ipucu').innerHTML = `<b>${MODLAR.find(m => m[0] === D.mod)[1]}:</b> ${MODLAR.find(m => m[0] === D.mod)[2]}${D.cizim.length && D.mod === 'bolge' ? ` <button class="dug kucuk ana" data-is="d-bitir">Bölgeyi bitir (${D.cizim.length} köşe)</button>` : ''}`;
  cizimCiz();
  yanPanelCiz();
}
function svgPoly(p) { return p.map(n => `${(n[0] * 1000).toFixed(1)},${(n[1] * 1000).toFixed(1)}`).join(' '); }
function cizimCiz() {
  const alan = $('#cizim-alani');
  if (!alan) return;
  const parcalar = [];
  D.ayar.bolgeler.forEach((b, i) => {
    const r = bolgeRengi(b.tur), sec = i === D.sb;
    if (b.tur === 'giris' && b.cizgi) {
      const [p, q] = b.cizgi;
      parcalar.push(`<line x1="${p[0] * 1000}" y1="${p[1] * 1000}" x2="${q[0] * 1000}" y2="${q[1] * 1000}" stroke="${r}" stroke-width="${sec ? 5 : 3.5}" vector-effect="non-scaling-stroke" data-bolge="${i}" style="cursor:pointer"><title>${h(b.ad)}</title></line>`);
      if (b.ic) parcalar.push(`<circle cx="${b.ic[0] * 1000}" cy="${b.ic[1] * 1000}" r="9" fill="${r}" stroke="#fff" stroke-width="2" vector-effect="non-scaling-stroke"><title>Mağazanın iç tarafı</title></circle>`);
      return;
    }
    if (!b.poly) return;
    parcalar.push(`<polygon points="${svgPoly(b.poly)}" fill="${r}" fill-opacity="${sec ? 0.14 : 0.07}" stroke="${r}" stroke-width="${sec ? 3 : 2}" vector-effect="non-scaling-stroke" data-bolge="${i}"><title>${h(b.ad)}</title></polygon>`);
    (b.gozler || []).forEach((g, j) => {
      const [x1, y1, x2, y2] = g.kutu.map(v => v * 1000), gs = sec && j === D.sg;
      const urun = (S.urunler || []).find(u => u.kimlik === g.urun);
      parcalar.push(`<rect x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}" rx="3" fill="${g.urun ? '#ffffff' : '#ff6b6b'}" fill-opacity="${gs ? 0.28 : 0.1}" stroke="${gs ? '#ffffff' : g.urun ? r : '#ff6b6b'}" stroke-width="${gs ? 3 : 1.6}" vector-effect="non-scaling-stroke" data-goz="${i}:${j}" style="cursor:${D.mod === 'sec' ? 'move' : 'inherit'}"><title>${h(urun?.ad || 'Ürün seçilmedi')} · ${g.adet || 1} yüz</title></rect>`);
      if (g.etiket) { const [a1, b1, a2, b2] = g.etiket.map(v => v * 1000); parcalar.push(`<rect x="${a1}" y="${b1}" width="${a2 - a1}" height="${b2 - b1}" fill="#b18cff" fill-opacity=".25" stroke="#b18cff" stroke-width="1.3" stroke-dasharray="4 2" vector-effect="non-scaling-stroke" pointer-events="none"/>`); }
      if (gs) parcalar.push(`<rect x="${x2 - 9}" y="${y2 - 14}" width="18" height="28" fill="#fff" stroke="#0f8b7d" stroke-width="1.5" vector-effect="non-scaling-stroke" data-boyut="${i}:${j}" style="cursor:nwse-resize"/>`);
    });
  });
  for (const o of D.oneriler?.gozler || []) { const [x1, y1, x2, y2] = o.kutu.map(v => v * 1000); parcalar.push(`<rect x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}" fill="#7ed957" fill-opacity=".15" stroke="#7ed957" stroke-width="2" stroke-dasharray="6 3" vector-effect="non-scaling-stroke" pointer-events="none"/>`); }
  if (D.cizim.length) {
    const r = D.mod === 'giris' ? BOLGE_RENK.giris : bolgeRengi(D.tur);
    parcalar.push(`<polyline points="${svgPoly(D.cizim)}" fill="none" stroke="${r}" stroke-width="2.5" vector-effect="non-scaling-stroke"/>`);
    D.cizim.forEach((p, i) => parcalar.push(`<circle cx="${p[0] * 1000}" cy="${p[1] * 1000}" r="${i === 0 ? 8 : 5}" fill="${i === 0 ? '#fff' : r}" stroke="${r}" stroke-width="2" vector-effect="non-scaling-stroke"/>`));
  }
  if (D.surukle?.tur === 'yeni') { const [x1, y1, x2, y2] = D.surukle.kutu.map(v => v * 1000); parcalar.push(`<rect x="${Math.min(x1, x2)}" y="${Math.min(y1, y2)}" width="${Math.abs(x2 - x1)}" height="${Math.abs(y2 - y1)}" fill="none" stroke="#fff" stroke-width="2" stroke-dasharray="5 3" vector-effect="non-scaling-stroke"/>`); }
  const ic = `<svg viewBox="0 0 1000 1000" preserveAspectRatio="none" id="cizim-svg" role="application" aria-label="Bölge ve göz çizim alanı" tabindex="0">${parcalar.join('')}</svg>`;
  const mevcut = $('#cizim');
  if (mevcut && mevcut.dataset.kare === (D.kare || '')) { mevcut.querySelector('svg').outerHTML = ic; mevcut.className = `sahne cizim ${D.mod === 'sec' ? 'sec' : ''}`; return; }
  alan.innerHTML = `<div class="sahne cizim ${D.mod === 'sec' ? 'sec' : ''}" id="cizim" data-kare="${h(D.kare || '')}">${D.kare ? `<img src="${h(D.kare)}" alt="Kameranın karesi" draggable="false">` : '<div class="bosyazi">Bu kameranın karesi yok. Kamerayı kaydedip Kameralar ekranında <b>Bağlantıyı dene</b>\'ye basın ya da üstten bir görüntü seçin.<br>Kare olmadan da çizebilirsiniz.</div>'}${ic}</div>`;
}
function yanPanelCiz() {
  const K = S.katalog, b = seciliBolge(), g = seciliGoz();
  const urunler = (S.urunler || []).slice().sort((x, y) => x.ad.localeCompare(y.ad, 'tr'));
  const bilgi = S.durum.kameralar.find(k => k.kod === D.kod) || {};
  const ref = D.ayar.referans, gozVar = D.ayar.bolgeler.some(x => (x.gozler || []).length);
  const refEski = ref && D.ayar.gozler_degisim && D.ayar.gozler_degisim > ref.zaman;
  let html = `<div class="kart bosluk-alt"><div class="kart-bas"><h2>Bölgeler <small>${D.ayar.bolgeler.length}</small></h2></div>
    ${D.ayar.bolgeler.length ? `<div class="bolge-liste">${D.ayar.bolgeler.map((x, i) => `<button class="bolge-oge ${i === D.sb ? 'secili' : ''}" data-is="d-bolge-sec" data-i="${i}"><i style="background:${bolgeRengi(x.tur)}"></i><span><b>${h(x.ad)}</b> <span class="not">${h(K.bolge_turleri[x.tur] || x.tur)}</span></span>${(x.gozler || []).length ? `<span class="rozet gri">${x.gozler.length} göz</span>` : ''}</button>`).join('')}</div>`
      : '<div class="not">Henüz bölge yok. <b>Bölge çiz</b> ile raf, koridor, kasa ya da dolap; <b>Giriş çizgisi</b> ile giriş sayımı çizin.</div>'}</div>`;
  if (b) {
    html += `<div class="kart form bosluk-alt"><div class="kart-bas"><h2>${h(b.ad)}</h2><span class="rozet gri">${h(b.kimlik || 'yeni')}</span></div>
      <div class="satir"><div><label for="d-bad">Ad</label><input id="d-bad" value="${h(b.ad)}" maxlength="60" data-d-alan="bolge-ad"></div>
        <div><label for="d-btur">Tür</label><select id="d-btur" data-degis="d-btur" ${b.tur === 'giris' ? 'disabled' : ''}>${Object.entries(K.bolge_turleri).filter(([t]) => (t === 'giris') === (b.tur === 'giris')).map(([t, a]) => `<option value="${t}" ${b.tur === t ? 'selected' : ''}>${h(a)}</option>`).join('')}</select></div></div>
      ${b.tur === 'kasa' ? `<label for="d-esik">Kuyruk uyarısı: kaç kişide</label><input id="d-esik" type="number" min="1" max="50" value="${h(b.esik ?? '')}" placeholder="varsayılan" data-d-alan="esik">` : ''}
      ${b.tur === 'giris' ? '<p class="not">Çizgiyi geçenler, iç taraftaki noktaya göre giren ya da çıkan sayılır.</p>' : ''}
      ${['raf', 'dolap'].includes(b.tur) ? `<p class="not" style="margin:8px 0 0">${(b.gozler || []).length} göz · ${(b.gozler || []).filter(x => !x.urun).length} gözde ürün seçilmedi</p>` : ''}
      <div class="eylemler" style="justify-content:flex-start;margin-top:10px"><button class="dug kucuk tehlike" data-is="d-bolge-sil">Bölgeyi sil</button></div></div>`;
  }
  if (g) {
    const sira = D.sg + 1;
    html += `<div class="kart form bosluk-alt"><div class="kart-bas"><h2>Göz ${sira}</h2><span class="rozet gri">${h(g.kimlik || 'yeni')}</span></div>
      <label for="d-urun">Ürün</label><select id="d-urun" data-degis="d-urun"><option value="">– seçilmedi –</option>${urunler.map(u => `<option value="${h(u.kimlik)}" ${g.urun === u.kimlik ? 'selected' : ''}>${h(u.ad)}${u.fiyat != null ? ' · ' + sayi(u.fiyat, 2) : ''}</option>`).join('')}</select>
      ${!urunler.length ? '<p class="not">Katalogda ürün yok. <a href="#/urunler">Ürünler</a> ekranından ekleyin.</p>' : ''}
      <div class="satir"><div><label for="d-adet">Beklenen yüz sayısı</label><input id="d-adet" type="number" min="1" max="99" value="${h(g.adet ?? 1)}" data-d-alan="adet"></div>
        <div><label for="d-fiyat">Raf fiyatı</label><input id="d-fiyat" inputmode="decimal" value="${g.fiyat != null ? String(g.fiyat).replace('.', ',') : ''}" placeholder="ürün fiyatı" data-d-alan="fiyat"></div></div>
      <p class="not" style="margin:6px 0 0">Etiket kutusu: ${g.etiket ? 'çizildi' : 'yok'} ${g.etiket ? '<button class="dug kucuk" data-is="d-etiket-sil">Kaldır</button>' : '<button class="dug kucuk" data-is="d-mod" data-v="etiket">Etiket çiz</button>'}</p>
      <div class="eylemler" style="justify-content:flex-start;margin-top:10px"><button class="dug kucuk tehlike" data-is="d-goz-sil">Gözü sil</button></div></div>`;
  }
  if (gozVar || ref) {
    html += `<div class="kart" id="d-referans"><div class="kart-bas"><h2>Raf referans karesi</h2>${ref ? (refEski ? '<span class="rozet sari">yenileyin</span>' : '<span class="rozet yesil">kayıtlı</span>') : '<span class="rozet sari">yok</span>'}</div>
      ${bilgi.referans_karesi ? `<img src="${h(bilgi.referans_karesi)}" alt="Kayıtlı referans kare" style="width:100%;border-radius:8px;display:block;margin-bottom:8px">` : ''}
      <p class="not" style="margin:0 0 8px">${ref ? `Kaydedildi: ${tarih(ref.zaman)}.` : 'Kayıtlı değil: motor koşunun ilk karelerini geçici referans sayar.'} Motor her gözün “dolu” görünümünü bu kareden alır. ${refEski ? '<b>Gözler bu kareden sonra değişti; raf doluyken yenileyin.</b>' : ''}</p>
      <button class="dug ${ref && !refEski ? '' : 'ana'}" data-is="d-referans" ${bilgi.temiz_kare ? '' : 'disabled'}>Rafı dolu olarak kaydet</button>
      ${bilgi.temiz_kare ? '' : '<p class="not">Motorun temiz karesi (yüzler gizli, çizimsiz) yok: önce analizi kısa bir süre çalıştırın. Bağlantı denemesinin karesi ve çizimli son kare referans olamaz.</p>'}</div>`;
  }
  $('#yan-panel').innerHTML = html;
  const o = $('#oneri-alani');
  if (o) o.innerHTML = D.oneriler ? `<div class="uyari-seridi bilgi-seridi" style="margin-top:12px"><b>${D.oneriler.metin}</b><span style="flex:1"></span><button class="dug kucuk ana" data-is="d-oneri-ekle">Ekle</button><button class="dug kucuk" data-is="d-oneri-vazgec">Vazgeç</button></div>` : '';
}

/* fare ile çizim */
function svgNokta(ev) {
  const r = $('#cizim-svg').getBoundingClientRect();
  return [Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height))];
}
function iceri(p, poly) {
  let ic = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > p[1]) !== (yj > p[1]) && p[0] < (xj - xi) * (p[1] - yi) / ((yj - yi) || 1e-9) + xi) ic = !ic;
  }
  return ic;
}
const yuvarla = v => Math.round(v * 10000) / 10000;
const kutuDuzelt = k => [yuvarla(Math.min(k[0], k[2])), yuvarla(Math.min(k[1], k[3])), yuvarla(Math.max(k[0], k[2])), yuvarla(Math.max(k[1], k[3]))];
function bolgeBitir() {
  if (D.cizim.length < 3) return bildir('Bölge için en az üç köşe gerekir.', true);
  geriKaydet();
  const tur = $('#d-tur')?.value || D.tur, ayni = D.ayar.bolgeler.filter(b => b.tur === tur).length;
  D.ayar.bolgeler.push({ ad: `${S.katalog.bolge_turleri[tur]} ${ayni + 1}`, tur, poly: D.cizim.map(p => [yuvarla(p[0]), yuvarla(p[1])]), ...(['raf', 'dolap'].includes(tur) ? { gozler: [] } : {}) });
  D.cizim = []; D.sb = D.ayar.bolgeler.length - 1; D.sg = null;
  if (['raf', 'dolap'].includes(tur)) D.mod = 'goz';
  degisti(); duzenleyiciCiz();
  $('#d-bad')?.select();
}
document.addEventListener('pointerdown', ev => {
  const svg = ev.target.closest?.('#cizim-svg');
  if (!svg || ev.button !== 0) return;
  ev.preventDefault();
  const p = svgNokta(ev);
  if (D.mod === 'bolge') {
    if (D.cizim.length >= 3) {
      const r = svg.getBoundingClientRect(), ilk = D.cizim[0];
      if (Math.hypot((ilk[0] - p[0]) * r.width, (ilk[1] - p[1]) * r.height) < 12) return bolgeBitir();
    }
    D.cizim.push(p); duzenleyiciCiz(); return;
  }
  if (D.mod === 'giris') {
    D.cizim.push(p);
    if (D.cizim.length === 3) {
      geriKaydet();
      D.ayar.bolgeler.push({ ad: `Giriş ${D.ayar.bolgeler.filter(b => b.tur === 'giris').length + 1}`, tur: 'giris', cizgi: [D.cizim[0], D.cizim[1]].map(q => [yuvarla(q[0]), yuvarla(q[1])]), ic: [yuvarla(p[0]), yuvarla(p[1])] });
      D.cizim = []; D.sb = D.ayar.bolgeler.length - 1; D.sg = null; D.mod = 'sec'; degisti();
    }
    duzenleyiciCiz(); return;
  }
  if (D.mod === 'goz' || D.mod === 'etiket') {
    if (D.mod === 'etiket' && !seciliGoz()) return bildir('Önce etiketini çizeceğiniz gözü seçin (Seç kipinde gözün üstüne tıklayın).', true);
    D.surukle = { tur: 'yeni', kutu: [p[0], p[1], p[0], p[1]] };
    svg.setPointerCapture(ev.pointerId); return;
  }
  // seç kipi
  const boyut = ev.target.closest('[data-boyut]'), goz = ev.target.closest('[data-goz]'), bolge = ev.target.closest('[data-bolge]');
  if (boyut || goz) {
    const [i, j] = (boyut || goz).dataset[boyut ? 'boyut' : 'goz'].split(':').map(Number);
    D.sb = i; D.sg = j;
    geriKaydet();
    D.surukle = { tur: boyut ? 'boyut' : 'tasi', bas: p, ilk: [...D.ayar.bolgeler[i].gozler[j].kutu], etiket: D.ayar.bolgeler[i].gozler[j].etiket ? [...D.ayar.bolgeler[i].gozler[j].etiket] : null, oynadi: false };
    svg.setPointerCapture(ev.pointerId);
    duzenleyiciCiz(); return;
  }
  if (bolge) { D.sb = +bolge.dataset.bolge; D.sg = null; duzenleyiciCiz(); return; }
  D.sg = null; duzenleyiciCiz();
});
document.addEventListener('pointermove', ev => {
  if (!D.surukle || !$('#cizim-svg')) return;
  const p = svgNokta(ev), s = D.surukle;
  if (s.tur === 'yeni') { s.kutu[2] = p[0]; s.kutu[3] = p[1]; cizimCiz(); return; }
  const g = seciliGoz();
  if (!g) return;
  const dx = p[0] - s.bas[0], dy = p[1] - s.bas[1];
  if (Math.abs(dx) + Math.abs(dy) > 0.002) s.oynadi = true;
  if (s.tur === 'tasi') {
    const w = s.ilk[2] - s.ilk[0], hgt = s.ilk[3] - s.ilk[1];
    const x1 = Math.min(1 - w, Math.max(0, s.ilk[0] + dx)), y1 = Math.min(1 - hgt, Math.max(0, s.ilk[1] + dy));
    g.kutu = [yuvarla(x1), yuvarla(y1), yuvarla(x1 + w), yuvarla(y1 + hgt)];
    if (s.etiket) { const ex = x1 - s.ilk[0], ey = y1 - s.ilk[1]; g.etiket = [s.etiket[0] + ex, s.etiket[1] + ey, s.etiket[2] + ex, s.etiket[3] + ey].map(v => yuvarla(Math.min(1, Math.max(0, v)))); }
  } else {
    g.kutu = [s.ilk[0], s.ilk[1], yuvarla(Math.max(s.ilk[0] + 0.01, Math.min(1, s.ilk[2] + dx))), yuvarla(Math.max(s.ilk[1] + 0.01, Math.min(1, s.ilk[3] + dy)))];
  }
  cizimCiz();
});
document.addEventListener('pointerup', () => {
  const s = D.surukle;
  if (!s) return;
  D.surukle = null;
  if (s.tur === 'yeni') {
    const k = kutuDuzelt(s.kutu);
    if (k[2] - k[0] < 0.008 || k[3] - k[1] < 0.008) { cizimCiz(); return; }
    const merkez = [(k[0] + k[2]) / 2, (k[1] + k[3]) / 2];
    if (D.mod === 'etiket') { geriKaydet(); seciliGoz().etiket = k; degisti(); D.mod = 'sec'; duzenleyiciCiz(); return; }
    let i = D.sb != null && ['raf', 'dolap'].includes(seciliBolge()?.tur) && iceri(merkez, seciliBolge().poly) ? D.sb : D.ayar.bolgeler.findIndex(b => ['raf', 'dolap'].includes(b.tur) && b.poly && iceri(merkez, b.poly));
    if (i < 0) { cizimCiz(); return bildir('Göz, bir raf ya da dolap bölgesinin içinde olmalı. Önce raf bölgesini çizin.', true); }
    geriKaydet();
    const b = D.ayar.bolgeler[i];
    b.gozler = b.gozler || [];
    const onceki = b.gozler[b.gozler.length - 1];
    b.gozler.push({ kutu: k, urun: null, adet: onceki?.adet || 1, etiket: null, fiyat: null });
    D.sb = i; D.sg = b.gozler.length - 1; degisti(); duzenleyiciCiz(); return;
  }
  if (s.oynadi) degisti(); else D.geri.pop();
  duzenleyiciCiz();
});
document.addEventListener('dblclick', ev => { if (ev.target.closest?.('#cizim-svg') && D.mod === 'bolge' && D.cizim.length >= 3) bolgeBitir(); });
document.addEventListener('keydown', ev => {
  if (!$('#cizim-svg') || konum().yol !== D.yol || $('#k-planogram')?.hidden) return;
  if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '') || document.querySelector('.perde')) return;
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'z') { ev.preventDefault(); IS['d-geri'](); return; }
  if (ev.key === 'Escape' && D.cizim.length) { ev.stopPropagation(); D.cizim = []; duzenleyiciCiz(); return; }
  if (ev.key === 'Enter' && D.mod === 'bolge' && D.cizim.length >= 3) { ev.preventDefault(); bolgeBitir(); return; }
  const g = seciliGoz();
  if (!g) return;
  if (ev.key === 'Delete' || ev.key === 'Backspace') { ev.preventDefault(); IS['d-goz-sil'](); return; }
  const ok = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[ev.key];
  if (ok) {
    ev.preventDefault();
    const a = ev.shiftKey ? 0.01 : 0.002, dx = ok[0] * a, dy = ok[1] * a;
    if (g.kutu[0] + dx < 0 || g.kutu[2] + dx > 1 || g.kutu[1] + dy < 0 || g.kutu[3] + dy > 1) return;
    geriKaydet();
    g.kutu = g.kutu.map((v, i) => yuvarla(v + (i % 2 ? dy : dx)));
    if (g.etiket) g.etiket = g.etiket.map((v, i) => yuvarla(Math.min(1, Math.max(0, v + (i % 2 ? dy : dx)))));
    degisti(); cizimCiz();
  }
});

/* ------------------------------------------------------------ eylemler */
async function motorIsi(ad, govde) {
  // tek seferlik motor işi: başlatılır, iş bitene kadar beklenir, sonucu döner
  let r;
  try { r = await api('/api/motor/' + ad, govde); } catch (x) {
    if (x.motorYok) bildir('Analiz motoru kullanılamıyor: ' + x.message, true); else bildir(x.message, true);
    return null;
  }
  bildir(`${S.katalog.motor_isleri[ad]}: AugeLab Studio'da çalışıyor…`);
  const no = r.is?.no;
  for (let i = 0; i < 240; i++) {
    await new Promise(c => setTimeout(c, 1500));
    await durumAl().catch(() => null);
    const is = S.durum.is;
    if (!is || is.no !== no) continue;
    if (is.durum === 'calisiyor') continue;
    if (is.durum === 'bitti') return is.sonuc;
    bildir((is.satirlar || []).slice(-1)[0] || 'Analiz motoru işi yapamadı.', true);
    return null;
  }
  bildir('Analiz motoru zamanında yanıt vermedi.', true);
  return null;
}
async function kaydetGerekirse() {
  if (!D.degisti && !D.yeni) return true;
  if (!await onayla('Önce kaydedilsin mi?', 'Motor kaydedilmiş bölgelerle çalışır. Değişiklikler şimdi kaydedilecek.', { tamam: 'Kaydet ve devam et' })) return false;
  return await kameraKaydet(true);
}
async function kameraKaydet(kal = false) {
  const kf = kameraFormu();
  if (!kf.kod) { IS['k-sekme']({ dataset: { v: 'baglanti' } }); $('#k-kod').focus(); bildir('Kısa kod yazın (ör. icecek1).', true); return false; }
  const ayar = { ...D.ayar, ...kf, bolgeler: D.ayar.bolgeler, ozellikler: ozellikleriOku() };
  const kisi = $('#k-kisi-fps')?.value, araligi = $('#k-raf-araligi')?.value;
  if (kisi !== undefined) { if (kisi === '') delete ayar.kisi_fps; else ayar.kisi_fps = +kisi; }
  if (araligi !== undefined) { if (araligi === '') delete ayar.raf_araligi_sn; else ayar.raf_araligi_sn = +araligi; }
  const gozlerOnce = JSON.stringify((D.ayar.bolgeler || []).map(b => (b.gozler || []).map(g => g.kutu)));
  let r;
  try { r = await api('/api/ayar', D.yeni ? { ayar, yeni: true } : { ayar }); } catch (x) { bildir(x.message, true); return false; }
  D.degisti = false;
  bildir(['Kaydedildi.', ...(r.notlar || [])].join(' '));
  await durumAl();
  if (D.yeni) { git('kamera/' + r.kod, { sekme: 'planogram' }); return true; }
  D.ayar = r.ayar || D.ayar;
  D.geri = [];
  $('#kaydedilmedi').hidden = true;
  if (D.ayar.referans && D.ayar.gozler_degisim && D.ayar.gozler_degisim > D.ayar.referans.zaman && JSON.stringify((D.ayar.bolgeler || []).map(b => (b.gozler || []).map(g => g.kutu))) !== gozlerOnce)
    bildir('Gözler değişti: raf doluyken “Rafı dolu olarak kaydet” ile referansı yenileyin.');
  if (!kal) duzenleyiciCiz(); else duzenleyiciCiz();
  return true;
}
function kameraFormu() {
  const v = id => $('#' + id)?.value.trim() ?? '';
  const tur = v('k-tur');
  const kamera = { tur };
  if (tur === 'rtsp') {
    if (v('k-adres')) Object.assign(kamera, { adres: v('k-adres') });
    else Object.assign(kamera, { marka: v('k-marka') || 'hikvision', ip: v('k-ip'), port: +v('k-port') || 554, kanal: +v('k-kanal') || 1, akis: v('k-akis') });
    kamera.kullanici = v('k-kullanici') || 'admin';
  } else if (tur === 'onvif') {
    Object.assign(kamera, { ip: v('o-ip'), port: +v('o-port') || 80, kullanici: v('o-kullanici') || 'admin', kanal: +v('o-kanal') || 1, akis: v('o-akis') });
    const secili = $('#o-profil').selectedOptions[0];
    if (secili?.value) Object.assign(kamera, { profil: secili.value, profil_ad: secili.dataset.ad || secili.textContent }, secili.dataset.kaynak ? { kaynak: secili.dataset.kaynak } : {});
  } else if (tur === 'http') Object.assign(kamera, { adres: v('k-adres'), kullanici: v('k-kullanici') || 'admin' });
  else { kamera.yol = v('k-yol'); if (v('k-baslangic')) kamera.baslangic = v('k-baslangic') + ':00'; }
  return { ad: v('k-ad') || v('k-kod'), kod: v('k-kod'), kamera: D.ornek ? D.ayar.kamera : kamera };
}
function izgaraPenceresi() {
  const b = seciliBolge();
  const xs = b.poly.map(p => p[0]), ys = b.poly.map(p => p[1]);
  const k = document.createElement('div'); k.className = 'perde';
  k.innerHTML = `<div class="pencere form" role="dialog" aria-modal="true"><h2>Gözlere böl · ${h(b.ad)}</h2><p class="not">Bölgenin çerçevesi satır ve sütunlara bölünür; her hücre bir göz olur. Sonra her gözü sürükleyerek düzeltebilirsiniz.</p>
    <div class="satir"><div><label for="iz-satir">Raf satırı</label><input id="iz-satir" type="number" min="1" max="20" value="3"></div><div><label for="iz-sutun">Satırdaki göz</label><input id="iz-sutun" type="number" min="1" max="40" value="6"></div><div><label for="iz-adet">Göz başına yüz</label><input id="iz-adet" type="number" min="1" max="99" value="3"></div></div>
    <label style="display:flex;gap:8px;align-items:center"><input type="checkbox" id="iz-etiket" checked style="width:auto"> Her gözün altına etiket kutusu ekle</label>
    ${(b.gozler || []).length ? '<p class="not" style="color:#7a5300">Bölgedeki mevcut gözler silinip yerine yenileri konur.</p>' : ''}
    <div class="eylemler"><button class="dug" data-c="0">Vazgeç</button><button class="dug ana" data-c="1">Böl</button></div></div>`;
  document.body.appendChild(k);
  k.querySelector('#iz-satir').focus();
  k.addEventListener('click', e => {
    const d = e.target.closest('[data-c]');
    if (!d) return;
    if (d.dataset.c === '1') {
      const sr = Math.max(1, Math.min(20, +$('#iz-satir').value || 1)), su = Math.max(1, Math.min(40, +$('#iz-sutun').value || 1)), adet = Math.max(1, Math.min(99, +$('#iz-adet').value || 1)), et = $('#iz-etiket').checked;
      const x1 = Math.min(...xs), x2 = Math.max(...xs), y1 = Math.min(...ys), y2 = Math.max(...ys), sh = (y2 - y1) / sr, sw = (x2 - x1) / su;
      geriKaydet();
      b.gozler = [];
      for (let r = 0; r < sr; r++) for (let c = 0; c < su; c++) {
        const gx1 = x1 + c * sw + sw * 0.04, gx2 = x1 + (c + 1) * sw - sw * 0.04, gy1 = y1 + r * sh + sh * 0.05, gy2 = y1 + (r + 1) * sh - sh * (et ? 0.2 : 0.06);
        b.gozler.push({ kutu: kutuDuzelt([gx1, gy1, gx2, gy2]), urun: null, adet, fiyat: null, etiket: et ? kutuDuzelt([gx1, gy2 + sh * 0.03, Math.min(gx2, gx1 + sw * 0.6), gy2 + sh * 0.14]) : null });
      }
      D.sg = 0; degisti(); duzenleyiciCiz();
    }
    k.remove();
  });
}
Object.assign(IS, {
  'k-sekme': e => {
    D.sekme = e.dataset.v;
    for (const s of ['baglanti', 'planogram', 'ozellikler']) { const k = $('#k-' + s); if (k) k.hidden = s !== D.sekme; }
    $$('[data-is="k-sekme"]').forEach(b => { b.classList.toggle('secili', b.dataset.v === D.sekme); b.setAttribute('aria-selected', b.dataset.v === D.sekme); });
    sorguDegistir({ ...konum().q, sekme: D.sekme });
    if (D.sekme === 'ozellikler') $('#k-ozellikler').innerHTML = ozellikSekmesi();
  },
  'kamera-kaydet': () => kameraKaydet(),
  'd-mod': e => { D.mod = e.dataset.v; D.cizim = []; if (D.mod === 'bolge') D.tur = $('#d-tur')?.value || D.tur; duzenleyiciCiz(); },
  'd-bitir': () => bolgeBitir(),
  'd-geri': () => { if (!D.geri.length) return; D.ayar.bolgeler = JSON.parse(D.geri.pop()); D.sb = D.sb != null && D.sb < D.ayar.bolgeler.length ? D.sb : null; D.sg = null; degisti(); duzenleyiciCiz(); },
  'd-bolge-sec': e => { D.sb = +e.dataset.i; D.sg = null; duzenleyiciCiz(); },
  'd-bolge-sil': async () => {
    const b = seciliBolge();
    if ((b.gozler || []).length && !await onayla(`"${b.ad}" silinsin mi?`, `Bölge ve ${b.gozler.length} gözü silinir. Kaydetmeden önce Geri al ile geri alınabilir.`, { tamam: 'Sil', tehlike: true })) return;
    geriKaydet(); D.ayar.bolgeler.splice(D.sb, 1); D.sb = null; D.sg = null; degisti(); duzenleyiciCiz();
  },
  'd-goz-sil': () => { const b = seciliBolge(); if (!b || D.sg == null) return; geriKaydet(); b.gozler.splice(D.sg, 1); D.sg = null; degisti(); duzenleyiciCiz(); },
  'd-etiket-sil': () => { geriKaydet(); seciliGoz().etiket = null; degisti(); duzenleyiciCiz(); },
  'd-izgara': () => izgaraPenceresi(),
  'd-satir-kopyala': () => {
    const b = seciliBolge(), g = seciliGoz();
    const hy = g.kutu[3] - g.kutu[1], yc = (g.kutu[1] + g.kutu[3]) / 2;
    const satir = b.gozler.filter(x => Math.abs((x.kutu[1] + x.kutu[3]) / 2 - yc) < hy * 0.5);
    // satır, bölgedeki en alttaki gözün altına kopyalanır (alt satırların üstüne binmez)
    const ust_ = Math.min(...satir.map(x => x.kutu[1])), alt = Math.max(...satir.map(x => Math.max(x.kutu[3], x.etiket ? x.etiket[3] : 0)));
    const enAlt = Math.max(...b.gozler.map(x => Math.max(x.kutu[3], x.etiket ? x.etiket[3] : 0)));
    const dy = enAlt - ust_ + 0.01;
    if (alt + dy > 1) return bildir('Bölgenin altında yeni satıra yer yok. Bölgeyi büyütün ya da gözü elle çizin.', true);
    geriKaydet();
    const yeni = satir.map(x => ({ kutu: x.kutu.map((v, i) => yuvarla(v + (i % 2 ? dy : 0))), urun: null, adet: x.adet, fiyat: null, etiket: x.etiket ? x.etiket.map((v, i) => yuvarla(Math.min(1, Math.max(0, v + (i % 2 ? dy : 0))))) : null }));
    b.gozler.push(...yeni);
    D.sg = b.gozler.length - yeni.length; degisti(); duzenleyiciCiz();
    bildir(`${yeni.length} göz kopyalandı; ürünlerini seçin.`);
  },
  'd-referans': async () => {
    if (D.degisti && !await kaydetGerekirse()) return;
    if (!await onayla('Raf dolu mu?', 'Motorun şu anki temiz karesi (yüzler gizli, çizimsiz) rafın “dolu” hâli olarak kaydedilir. Motor her gözün dolu görünümünü bu kareden alır. Raf eksiksiz doluyken kaydedin.', { tamam: 'Rafı dolu olarak kaydet' })) return;
    const r = await api('/api/ayar/referans', { kod: D.kod });
    D.ayar.referans = r.referans;
    bildir('Referans kare kaydedildi.'); await durumAl(); yanPanelCiz();
  },
  'd-motor': async e => {
    const ad = e.dataset.v;
    if (S.durum.gelistirme) return bildir('Analiz motoru bu kipte kullanılamıyor (geliştirme kipi). Gözleri elle çizin ya da “Gözlere böl”ü kullanın.', true);
    if (!await kaydetGerekirse()) return;
    if (ad === 'gozler') {
      const b = seciliBolge();
      const sonuc = await motorIsi('gozler', { kod: D.kod, bolge: b && ['raf', 'dolap'].includes(b.tur) ? b.kimlik : undefined });
      if (!sonuc) return;
      if (!sonuc.gozler.length) return bildir('Motor bu bölgede göz önermedi.');
      D.oneriler = { tur: 'gozler', gozler: sonuc.gozler, metin: `Motor ${sonuc.gozler.length} göz önerdi (yeşil kesik çizgili).` };
      duzenleyiciCiz();
    } else if (ad === 'urun_tani') {
      const liste = D.ayar.bolgeler.flatMap((b, i) => (b.gozler || []).map((g, j) => ({ i, j, g })));
      const sonuc = await motorIsi('urun_tani', { kod: D.kod, kutular: liste.map(x => x.g.kutu) });
      if (!sonuc) return;
      const eslesen = sonuc.urunler.map((u, n) => ({ ...u, hedef: liste[n] })).filter(u => u.hedef && u.urun && (u.benzerlik ?? 0) >= 0.6 && !u.hedef.g.urun);
      if (!eslesen.length) return bildir('Ürünü seçilmemiş gözler için güvenilir eşleşme bulunamadı.');
      D.oneriler = { tur: 'urun', eslesen, metin: `${eslesen.length} göz için ürün önerildi (benzerlik ≥ 0,6). Boş gözlere atansın mı?` };
      duzenleyiciCiz();
    } else {
      const liste = D.ayar.bolgeler.flatMap(b => (b.gozler || []).filter(g => g.etiket));
      const sonuc = await motorIsi('etiketler', { kod: D.kod, kutular: liste.map(g => g.etiket) });
      if (!sonuc) return;
      const okunan = sonuc.etiketler.map((x, n) => ({ ...x, g: liste[n] })).filter(x => x.g && x.fiyat != null);
      if (!okunan.length) return bildir('Etiketlerden fiyat okunamadı.');
      D.oneriler = { tur: 'fiyat', okunan, metin: `${okunan.length} etiketten fiyat okundu. Raf fiyatı boş olan gözlere yazılsın mı?` };
      duzenleyiciCiz();
    }
  },
  'd-oneri-ekle': () => {
    const o = D.oneriler;
    geriKaydet();
    if (o.tur === 'gozler') {
      for (const x of o.gozler) {
        const b = D.ayar.bolgeler.find(z => z.kimlik === x.bolge) || seciliBolge();
        if (!b) continue;
        (b.gozler = b.gozler || []).push({ kutu: x.kutu, urun: null, adet: 1, etiket: x.etiket || null, fiyat: null });
      }
    } else if (o.tur === 'urun') o.eslesen.forEach(u => { u.hedef.g.urun = u.urun; });
    else o.okunan.forEach(x => { if (x.g.fiyat == null) x.g.fiyat = x.fiyat; });
    D.oneriler = null; degisti(); duzenleyiciCiz();
  },
  'd-oneri-vazgec': () => { D.oneriler = null; duzenleyiciCiz(); },
});
Object.assign(DEGIS, {
  'kamera-tur': () => kameraTuruGoster(),
  'd-btur': e => { geriKaydet(); const b = seciliBolge(); b.tur = e.value; if (!['raf', 'dolap'].includes(b.tur)) delete b.gozler; else b.gozler = b.gozler || []; if (b.tur !== 'kasa') delete b.esik; degisti(); duzenleyiciCiz(); },
  'd-urun': e => {
    geriKaydet(); const g = seciliGoz(); g.urun = e.value || null; degisti(); cizimCiz();
    // sıradaki ürünü seçilmemiş göze geç: hızlı planogram girişi
    const b = seciliBolge(), sonraki = b.gozler.findIndex((x, j) => j > D.sg && !x.urun);
    if (g.urun && sonraki >= 0) { D.sg = sonraki; duzenleyiciCiz(); $('#d-urun')?.focus(); }
  },
});
document.addEventListener('change', ev => {
  const e = ev.target;
  const alan = e.dataset?.dAlan;
  if (alan) {
    const b = seciliBolge(), g = seciliGoz();
    geriKaydet();
    if (alan === 'bolge-ad') b.ad = e.value.trim().slice(0, 60) || b.ad;
    else if (alan === 'esik') { if (e.value === '') delete b.esik; else b.esik = Math.max(1, Math.min(50, Math.round(+e.value))); }
    else if (alan === 'adet') g.adet = Math.max(1, Math.min(99, Math.round(+e.value) || 1));
    else if (alan === 'fiyat') { const v = e.value.trim().replace(',', '.'); if (v === '') g.fiyat = null; else if (isNaN(+v) || +v < 0) { bildir('Fiyat bir sayı olmalı.', true); e.value = g.fiyat ?? ''; D.geri.pop(); return; } else g.fiyat = Math.round(+v * 100) / 100; }
    degisti(); duzenleyiciCiz();
    return;
  }
  if (e.id === 'd-tur') D.tur = e.value;
  if (e.id === 'kare-dosya' && e.files[0]) { const o = new FileReader(); o.onload = () => { D.kare = o.result; D.yerelKod = D.kod; D.yerelKare = o.result; cizimCiz(); bildir('Görüntü yalnızca çizim için kullanılır; kaydedilmez.'); }; o.readAsDataURL(e.files[0]); }
  if (e.dataset?.ozellik || e.dataset?.ozAyar || ['k-kisi-fps', 'k-raf-araligi', 'k-ad'].includes(e.id) || e.closest?.('#k-baglanti')) degisti();
});

/* Kayıt cihazının kanalları: formdaki bağlantı, her kanal için ayrı bir kamera olarak kaydedilir (bölgeler sonradan çizilir). */
async function kanallariEkle(kanallar, profiller) {
  const taban = { ...kameraFormu(), ozellikler: ozellikleriOku(), bolgeler: [] };
  if (!taban.kod) return bildir('Önce kısa kodu yazın (ör. nvr1): kanallar nvr1-k1, nvr1-k2… olarak eklenir.', true);
  if (!taban.kamera.ip) return bildir('Önce kayıt cihazının IP adresini yazın.', true);
  if (!kanallar.length || kanallar.length > 64) return bildir('Kanal sayısı 2 ile 64 arasında olmalı.', true);
  const kodlar = kanallar.map(n => `${taban.kod}-k${n}`);
  const varolan = kodlar.filter(k => (S.durum.kameralar || []).some(c => c.kod === k));
  if (varolan.length) return bildir(`Bu kodlarla kamera zaten var: ${varolan.join(', ')}. Üstlerine yazılmaz; başka bir kısa kod yazın.`, true);
  if (!await onayla(`${kanallar.length} kanal eklensin mi?`, `${kodlar[0]} … ${kodlar[kodlar.length - 1]} ayrı kameralar olarak eklenecek. Bölgeler her kamerada ayrıca çizilir.`, { tamam: 'Ekle' })) return;
  try { const r = await api('/api/ayar/kanallar', { taban, kanallar, ...(profiller ? { profiller } : {}) }); bildir(`${r.kodlar.length} kanal eklendi.`); } catch (x) { await durumAl(); return bildir(x.message, true); }
  D.degisti = false; await durumAl(); git('kameralar');
}
Object.assign(IS, {
  'nvr-kanallari-ekle': () => { const n = +$('#k-kanal-sayisi').value; return kanallariEkle(n >= 2 && n <= 64 ? Array.from({ length: n }, (_, i) => i + 1) : []); },
  'onvif-kesfet': async () => {
    $('#o-sonuc').innerHTML = '<div class="not">Ağda ONVIF cihazı aranıyor (yaklaşık 3 saniye)…</div>';
    const d = await api('/api/onvif/kesfet', {}).catch(x => ({ hata: x.message }));
    $('#o-sonuc').innerHTML = d.hata ? `<div class="not">${h(d.hata)}</div>` : d.cihazlar.length
      ? `<table>${d.cihazlar.map(c => `<tr><td><b>${h(c.ip)}</b>:${c.port}<div class="not">${h([c.ad, c.model].filter(Boolean).join(' · ') || 'ONVIF cihazı')}</div></td><td style="text-align:right"><button class="dug kucuk" data-is="onvif-cihaz-sec" data-ip="${h(c.ip)}" data-port="${c.port}">Seç</button></td></tr>`).join('')}</table>`
      : '<div class="not">Bu ağda yanıt veren ONVIF cihazı bulunamadı. IP adresini elle yazın.</div>';
  },
  'onvif-cihaz-sec': e => { $('#o-ip').value = e.dataset.ip; $('#o-port').value = e.dataset.port; $('#o-sonuc').innerHTML = '<div class="not">Cihaz seçildi. Kullanıcı adını ve şifreyi yazıp kanalları listeleyin.</div>'; degisti(); },
  'onvif-profiller': async () => {
    $('#o-sonuc').innerHTML = '<div class="not">Cihaza bağlanılıyor…</div>';
    const d = await api('/api/onvif/profiller', { ip: $('#o-ip').value.trim(), port: +$('#o-port').value || 80, kullanici: $('#o-kullanici').value.trim() || 'admin', sifre: $('#o-sifre').value }).catch(x => ({ hata: x.message }));
    if (d.hata) { $('#o-sonuc').innerHTML = `<div class="uyari-seridi" style="margin:0">${h(d.hata)}</div>`; return; }
    S.onvifProfiller = d.profiller;
    const kanallar = [...new Set(d.profiller.map(p => p.kanal))];
    const cihaz = [d.cihaz?.uretici, d.cihaz?.model].filter(Boolean).join(' ');
    $('#o-sonuc').innerHTML = `<div class="not" style="margin-bottom:4px">${h(cihaz || 'Cihaz')} · ${kanallar.length} kanal · ${d.profiller.length} profil</div>
      <table>${d.profiller.map(p => `<tr><td>Kanal ${p.kanal}</td><td><b>${h(p.ad || p.belirtec)}</b><div class="not">${h(p.kodlama)} ${p.en}×${p.boy}</div></td>
        <td style="text-align:right"><button class="dug kucuk" data-is="onvif-profil-sec" data-belirtec="${h(p.belirtec)}" data-kanal="${p.kanal}" data-kaynak="${h(p.kaynak)}" data-ad="${h(`Kanal ${p.kanal} · ${p.ad || p.belirtec} · ${p.kodlama} ${p.en}×${p.boy}`)}">Seç</button></td></tr>`).join('')}</table>
      ${kanallar.length > 1 ? `<p style="margin:8px 0 0"><button class="dug kucuk" data-is="onvif-kanallari-ekle" data-kanallar="${kanallar.join(',')}">${kanallar.length} kanalı ayrı kameralar olarak ekle</button></p>` : ''}`;
  },
  'onvif-profil-sec': e => {
    const s = $('#o-profil');
    [...s.options].filter(o => o.value).forEach(o => o.remove());
    const o = new Option(e.dataset.ad, e.dataset.belirtec, true, true);
    o.dataset.ad = e.dataset.ad; o.dataset.kaynak = e.dataset.kaynak || '';
    s.add(o);
    $('#o-kanal').value = e.dataset.kanal;
    degisti();
    bildir('Profil seçildi. Kaydet\'e basınca kamera bu profille bağlanır.');
  },
  'onvif-kanallari-ekle': e => kanallariEkle(e.dataset.kanallar.split(',').map(Number), S.onvifProfiller || []),
});
