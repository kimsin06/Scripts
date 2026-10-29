# ParçaBul — Oto yedek parça fiyat karşılaştırma

Cimri mantığı, oto yedek parça için: kullanıcı **parça kodunu** (OEM / üretici kodu) yazar,
sistem bütün satıcılardaki fiyatları gösterir ve **en ucuzunu** öne çıkarır. Aracına göre
(marka → model → uyumlu parçalar) da arama yapılabilir. Fiyatları ve satıcı linklerini
görmek **aylık abonelik** ister.

## Ne yapıyor

- **Kod eşleştirme:** `8200 768 913`, `8200-768-913`, `8200.768.913` aynı parça sayılır.
- **Muadil parçalar:** OEM kodu ile yan sanayi kodu eşleştirilir; aramada ikisi birlikte listelenir.
- **En ucuz:** stokta olanlar önce, ucuzdan pahalıya. Stokta olmayan en ucuz sayılmaz.
  7 günden eski fiyatlar gösterilmez.
- **Fiyat geçmişi:** her fiyat değişikliği kaydedilir.
- **Tüm araçlar:** araç–parça uyumluluğu CSV ile yüklenir.
- **Abonelik:** misafir sadece en ucuz fiyatı görür; abone satıcıyı, tüm fiyatları ve linkleri görür.

## Fiyatlar nereden geliyor

`kaynaklar.json` dosyasına her satıcı için bir kaynak eklenir (örnek: `ornek/kaynaklar.json`):

1. **`feed` (önerilen):** Satıcının XML / JSON / CSV ürün listesi. Cimri ve Akakçe de
   fiyatların çoğunu böyle alır. Satıcıyla anlaşıp feed linkini istersiniz; `fields`
   kısmında satıcının alan adlarını bizimkilere eşlersiniz.
2. **`html_search`:** Feed'i olmayan satıcıların sitesinde kodu aratır ve sonuç sayfasını
   CSS seçicilerle okur. `robots.txt`'ye uyar, istekler arasında bekler (`delay`).
   Her site için seçicileri o sitenin HTML'ine göre yazmak gerekir.

> **Hukuki not:** Sitelerden izinsiz veri toplamak kullanım şartlarına aykırı olabilir.
> Satıcılarla anlaşıp feed almak hem daha güvenilir hem de risksizdir; satıcılar
> genelde trafik geldiği için feed vermeye isteklidir.

## Kurulum ve deneme

```bash
cd oto-parca-fiyat
pip install -r requirements.txt

python -m parcabul demo                  # örnek veriyi yükler
python -m parcabul ara "demo yf 100"     # terminalde en ucuzu listeler
python -m parcabul sunucu                # http://127.0.0.1:5000
```

## Günlük kullanım

```bash
python -m parcabul topla kaynaklar.json          # tüm satıcılardan fiyatları çek
python -m parcabul uyumluluk araclar.csv         # code,make,model,year_from,year_to,engine
python -m parcabul muadil muadiller.csv          # code,equivalent
python -m parcabul abonelik-ver ali@mail.com --ay 1 --ref DEKONT123
```

`topla` komutunu cron ile her gece (veya birkaç saatte bir) çalıştırın.

## Abonelik ve ödeme

- Aylık ücret: `PARCABUL_AYLIK_UCRET_TL` (varsayılan 199).
- Şu an ödeme **havale/EFT + elle onay** ile: kullanıcı kayıt olur, ödeme yapar,
  siz `abonelik-ver` ile aboneliğini açarsınız. Ödeme talimatı metni:
  `PARCABUL_ODEME_BILGISI`.
- Kartla otomatik aylık çekim için iyzico veya PayTR üye işyeri hesabı gerekir; başvuru
  onaylanınca `subscription.extend(...)` fonksiyonu ödeme bildirimi (webhook) içinden çağrılır.

## Canlıya alma

- `PARCABUL_SECRET_KEY` mutlaka sabit ve gizli bir değer olsun (yoksa her yeniden başlatmada
  kullanıcılar çıkış yapar).
- `PARCABUL_DB` veritabanı yolu.
- Geliştirme sunucusu yerine `gunicorn "parcabul.web:create_app()"` kullanın, önüne HTTPS koyun.

## Testler

```bash
python -m pytest tests
```
