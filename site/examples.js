'use strict';

// Fictional teaching scenarios, never allegations or research about a real brand.
(() => {
  const common = {
    en: {
      mode: 'Illustrative example', status: 'Fictional product', caption: 'Fictional product · Demonstration only',
      overview: 'Start with the exact version in the listing. Compare the details with the evidence, then ask the question that could change your decision.',
      matchTitle: 'A specific detail to investigate', matchSummary: 'An observation, an open question and a practical next step.', matchStatus: 'Example',
      type: 'Illustrative scenario', sourceCount: '2 fictional evidence notes',
      disclaimer: 'Fictional products and sample evidence, created to explain the workflow. No real brand is being assessed; no live research is running.',
      caution: 'These notes are fictional teaching material, not real owner reports, test results or claims about any manufacturer. In Kriko, actual research links to the original sources.',
      sellerNote: 'Illustrative listing. Brand and model are fictional.',
    },
    tr: {
      mode: 'Temsili örnek', status: 'Kurgusal ürün', caption: 'Kurgusal ürün · Yalnızca tanıtım amaçlı',
      overview: 'İlandaki ürünün tam sürümünü belirle. Ayrıntıları bulgularla karşılaştır; ardından kararını değiştirebilecek soruyu sor.',
      matchTitle: 'Araştırılacak somut bir ayrıntı', matchSummary: 'Bir gözlem, açık bir soru ve uygulanabilir bir sonraki adım.', matchStatus: 'Örnek',
      type: 'Temsili senaryo', sourceCount: '2 kurgusal kanıt notu',
      disclaimer: 'Bu akış, kurgusal ürünler ve örnek kanıtlarla anlatılır. Gerçek bir marka değerlendirilmez; canlı araştırma yapılmaz.',
      caution: 'Bu notlar kurgusal eğitim içeriğidir; gerçek kullanıcı bildirimi, test sonucu veya bir üretici hakkında iddia değildir. Kriko, gerçek araştırmalarda özgün kaynaklara bağlantı verir.',
      sellerNote: 'Temsili ilan. Marka ve model kurgusaldır.',
    },
  };
  const examples = {
    en: {
      cars: {
        fields: { name: 'Hatchback D · 2017', address: 'example-listing / hatchback-d', breadcrumb: 'Cars / Brand hidden / Hatchback D', quote: '“Clean interior. No water damage.”',
          category: 'Boot floor · Inspection clue', topic: 'Water ingress', title: 'Dry carpet. Damp underneath?', summary: 'The carpet looks clean, but the spare-wheel well has a water mark. Lift the boot floor before deciding.',
          finding: 'A water mark under the boot floor changes the inspection.', explanation: 'In this fictional viewing, the upper carpet is dry. Lifting the boot floor reveals a damp patch and a tide mark beside the spare wheel. That is a reason to investigate, not a diagnosis of a failed seal.',
          supported: 'The sample inspection note records moisture below the carpet and a visible water mark.', unresolved: 'The entry point is unknown. A spill, condensation and an external leak have not been distinguished.',
          question: '“Can we test where the water enters before I buy?”', inspection: 'Ask for a controlled water test and an inspection of the rear-light seals, vents and drain paths. Compare the results with any repair invoice.',
        }, specs: ['2017', 'Petrol', 'Manual', 'Buying used'],
        sources: [{ initial: '1', label: 'Sample inspection note', detail: 'Fictional observation · Boot floor lifted', excerpt: '“Upper carpet dry; damp patch and a water mark in the spare-wheel well.”' }, { initial: '2', label: 'Sample service note', detail: 'Fictional record · Cause not confirmed', excerpt: '“No leak test or repair invoice supplied. Water entry point still to be checked.”' }],
      },
      laptop: {
        fields: { name: 'Laptop A · 256 GB', address: 'example-listing / laptop-a-256', breadcrumb: 'Laptops / Brand hidden / Laptop A', quote: '“Up to 3,000 MB/s storage.”',
          category: 'Storage version · Review mismatch', topic: 'Configuration differences', title: 'Same laptop. Different SSD?', summary: 'The review tests 1 TB. Your basket says 256 GB. Check the exact version before relying on the headline speed.',
          finding: 'The review’s 1 TB result does not establish the 256 GB speed.', explanation: 'The fictional listing advertises “up to 3,000 MB/s”. Its linked review measures the 1 TB version, but the selected item is 256 GB. A matching product name is not enough to carry that result across capacities.',
          supported: 'The sample review specifies 1 TB; the sample basket specifies 256 GB.', unresolved: 'The 256 GB version’s sustained speed, storage layout and behaviour when nearly full are not measured here.',
          question: '“Where is the test of the 256 GB configuration?”', inspection: 'Compare the exact capacity and part number. Look for a sustained file-copy test of that configuration, including temperature and free-space conditions.',
        }, specs: ['14-inch', '16 GB RAM', '256 GB SSD', 'Buying new'],
        sources: [{ initial: '1', label: 'Sample listing snapshot', detail: 'Fictional listing · Selected configuration', excerpt: '“14-inch · 16 GB RAM · 256 GB SSD. Storage: up to 3,000 MB/s.”' }, { initial: '2', label: 'Sample review test sheet', detail: 'Fictional test · Different capacity', excerpt: '“Unit tested: 1 TB SSD. The 256 GB configuration was not tested.”' }],
      },
      headphones: {
        fields: { name: 'Headphones B · Wireless', address: 'example-listing / headphones-b', breadcrumb: 'Audio / Brand hidden / Headphones B', quote: '“Made for the daily commute.”',
          category: 'Hinge · A closer inspection', topic: 'Hinge inspection', title: 'A great review. A hidden weak point?', summary: 'A sample account describes a crack near the swivel after eight months. Check the location, revision and repair options.',
          finding: 'One hinge account raises a question; it does not establish a failure rate.', explanation: 'A fictional owner note describes a crack near the right swivel after eight months of commuting. A sample repair note asks for photos and a revision number before recommending a part. Neither tells us how common the issue is.',
          supported: 'The sample account identifies the right swivel, eight months of use and a visible crack.', unresolved: 'Cause, handling, affected revisions and the failure rate remain unknown.',
          question: '“Is this the same revision, and can the hinge be replaced?”', inspection: 'Compare the crack location and revision in independent accounts. Check the repair process, part availability and warranty terms for the exact model.',
        }, specs: ['Over-ear', 'Wireless', 'Revision 02', 'Buying new'],
        sources: [{ initial: '1', label: 'Sample owner account', detail: 'Fictional account · Eight months in use', excerpt: '“Crack beside the right swivel. Used on weekdays; no cause confirmed.”' }, { initial: '2', label: 'Sample repair intake note', detail: 'Fictional repair note · Assessment pending', excerpt: '“Send close-up photos and the revision number. Replacement suitability not yet assessed.”' }],
      },
      coffee: {
        fields: { name: 'Espresso machine C', address: 'example-listing / espresso-c', breadcrumb: 'Kitchen / Brand hidden / Machine C', quote: '“Café-style coffee at home.”',
          category: 'Buzzing · Timing matters', topic: 'Noise and pressure', title: 'A buzz is a symptom. Not a diagnosis.', summary: 'A brief buzz during brewing and a buzz that continues after water stops are different clues. Ask when it happens.',
          finding: 'The timing of the noise changes what needs checking.', explanation: 'In one fictional account, buzzing stops as soon as extraction ends and pressure is stable. In another, it continues after water flow stops and the gauge fluctuates. Calling both “a noisy pump” would hide useful differences.',
          supported: 'The two sample notes describe different timing and pressure behaviour.', unresolved: 'The notes do not diagnose a failed pump or valve, or establish whether either sound is abnormal.',
          question: '“Does the noise stop with water flow, and is pressure stable?”', inspection: 'Record the brewing stage, sound duration and pressure behaviour. Compare them with the exact model’s instructions and seek a qualified diagnosis before replacing parts.',
        }, specs: ['Espresso', 'Built-in grinder', 'Manual controls', 'Buying new'],
        sources: [{ initial: '1', label: 'Sample observation A', detail: 'Fictional note · During extraction', excerpt: '“Buzz lasts 25 seconds, stops with extraction; pressure remains stable.”' }, { initial: '2', label: 'Sample observation B', detail: 'Fictional note · After water flow', excerpt: '“Buzz continues after water stops; the pressure gauge fluctuates. Cause unknown.”' }],
      },
    },
    tr: {
      cars: {
        fields: { name: 'Hatchback D · 2017', address: 'ornek-ilan / hatchback-d', breadcrumb: 'Otomobil / Marka gizli / Hatchback D', quote: '“İçi temiz. Su hasarı yok.”',
          category: 'Bagaj tabanı · Kontrol ipucu', topic: 'Su girişi', title: 'Halı kuru. Peki ya altı?', summary: 'Halı temiz görünüyor ama stepne havuzunda su izi var. Karar vermeden bagaj tabanını kaldır.',
          finding: 'Bagaj tabanının altındaki su izi, ekspertizde sorulacak soruyu değiştirir.', explanation: 'Bu kurgusal incelemede üstteki halı kuru. Bagaj tabanı kaldırılınca stepnenin yanında nemli bir bölge ve su izi görülüyor. Bu, araştırma gerekçesidir; bir contanın arızalı olduğuna dair teşhis değildir.',
          supported: 'Örnek inceleme notunda halının altında nem ve görünür bir su izi kayıtlı.', unresolved: 'Suyun nereden geldiği bilinmiyor. Dökülen sıvı, yoğuşma ve dışarıdan sızıntı henüz ayırt edilmedi.',
          question: '“Almadan önce suyun nereden girdiğini test edebilir miyiz?”', inspection: 'Kontrollü su testi ile arka stop contalarının, havalandırmaların ve tahliye yollarının kontrolünü iste. Sonuçları varsa onarım faturasıyla karşılaştır.',
        }, specs: ['2017', 'Benzinli', 'Manuel', 'İkinci el'],
        sources: [{ initial: '1', label: 'Örnek inceleme notu', detail: 'Kurgusal gözlem · Bagaj tabanı kaldırıldı', excerpt: '“Üst halı kuru; stepne havuzunda nemli bölge ve su izi var.”' }, { initial: '2', label: 'Örnek servis notu', detail: 'Kurgusal kayıt · Neden doğrulanmadı', excerpt: '“Sızıntı testi veya onarım faturası sunulmadı. Suyun giriş noktası kontrol edilmeli.”' }],
      },
      laptop: {
        fields: { name: 'Dizüstü A · 256 GB', address: 'ornek-ilan / dizustu-a-256', breadcrumb: 'Bilgisayar / Marka gizli / Dizüstü A', quote: '“3.000 MB/sn’ye kadar depolama hızı.”',
          category: 'Depolama sürümü · İnceleme farkı', topic: 'Yapılandırma farkları', title: 'Aynı bilgisayar. Farklı SSD?', summary: 'İnceleme 1 TB sürümü test ediyor. Sepetinde ise 256 GB var. Hız iddiasına güvenmeden tam sürümü kontrol et.',
          finding: '1 TB sürümün test sonucu, 256 GB sürümün hızını kanıtlamaz.', explanation: 'Kurgusal ilanda “3.000 MB/sn’ye kadar” yazıyor. Bağlantı verilen inceleme 1 TB sürümü ölçüyor; seçili ürün ise 256 GB. Ürün adının aynı olması, sonucu tüm kapasitelere genellemek için yeterli değil.',
          supported: 'Örnek incelemede 1 TB, örnek sepette ise 256 GB belirtiliyor.', unresolved: '256 GB sürümün uzun süreli hızı, depolama düzeni ve disk doluyken davranışı burada ölçülmedi.',
          question: '“256 GB sürümün testi nerede?”', inspection: 'Kapasiteyi ve parça numarasını karşılaştır. Aynı yapılandırmada yapılmış uzun dosya kopyalama testini; sıcaklık ve boş alan koşullarıyla birlikte ara.',
        }, specs: ['14 inç', '16 GB RAM', '256 GB SSD', 'Sıfır ürün'],
        sources: [{ initial: '1', label: 'Örnek ilan görüntüsü', detail: 'Kurgusal ilan · Seçili yapılandırma', excerpt: '“14 inç · 16 GB RAM · 256 GB SSD. Depolama hızı: 3.000 MB/sn’ye kadar.”' }, { initial: '2', label: 'Örnek inceleme test notu', detail: 'Kurgusal test · Farklı kapasite', excerpt: '“Test edilen cihaz: 1 TB SSD. 256 GB yapılandırma test edilmedi.”' }],
      },
      headphones: {
        fields: { name: 'Kulaklık B · Kablosuz', address: 'ornek-ilan / kulaklik-b', breadcrumb: 'Ses / Marka gizli / Kulaklık B', quote: '“Her gün yolda yanında.”',
          category: 'Menteşe · Yakından kontrol', topic: 'Menteşe kontrolü', title: 'İyi bir inceleme. Gözden kaçan bir ayrıntı?', summary: 'Örnek bir kullanıcı notu, sekiz ay sonra döner bağlantı yanında çatlak tarif ediyor. Konumu, revizyonu ve onarım seçeneğini kontrol et.',
          finding: 'Tek bir menteşe bildirimi soru doğurur; arıza oranını göstermez.', explanation: 'Kurgusal kullanıcı notunda sekiz aylık günlük kullanımdan sonra sağ döner bağlantı yanında çatlak anlatılıyor. Örnek onarım notu ise parça önermeden önce fotoğraf ve revizyon numarası istiyor. Bunlar sorunun ne kadar yaygın olduğunu göstermiyor.',
          supported: 'Örnek notta sağ döner bağlantı, sekiz aylık kullanım ve görünür çatlak belirtiliyor.', unresolved: 'Neden, kullanım koşulları, etkilenen revizyonlar ve arıza oranı bilinmiyor.',
          question: '“Bu aynı revizyon mu, menteşe değiştirilebiliyor mu?”', inspection: 'Bağımsız bildirimlerde çatlağın konumunu ve revizyonu karşılaştır. Tam model için onarım sürecini, yedek parçayı ve garanti koşullarını kontrol et.',
        }, specs: ['Kulak çevreleyen', 'Kablosuz', 'Revizyon 02', 'Sıfır ürün'],
        sources: [{ initial: '1', label: 'Örnek kullanıcı notu', detail: 'Kurgusal bildirim · Sekiz aylık kullanım', excerpt: '“Sağ döner bağlantının yanında çatlak. Hafta içi kullanıldı; neden doğrulanmadı.”' }, { initial: '2', label: 'Örnek onarım kabul notu', detail: 'Kurgusal onarım notu · İnceleme bekliyor', excerpt: '“Yakın çekim fotoğraf ve revizyon numarası gönderin. Parça uygunluğu henüz değerlendirilmedi.”' }],
      },
      coffee: {
        fields: { name: 'Espresso makinesi C', address: 'ornek-ilan / espresso-c', breadcrumb: 'Mutfak / Marka gizli / Makine C', quote: '“Evde kafe keyfi.”',
          category: 'Vızıltı · Zamanlama önemli', topic: 'Ses ve basınç', title: 'Vızıltı bir belirti. Teşhis değil.', summary: 'Demleme sırasında duyulan kısa ses ile su durduktan sonra süren ses farklı ipuçlarıdır. Ne zaman olduğunu sor.',
          finding: 'Sesin ne zaman duyulduğu, kontrol edilecek noktayı değiştirir.', explanation: 'Bir kurgusal notta vızıltı demleme bitince kesiliyor ve basınç sabit. Diğerinde su akışı durduktan sonra ses sürüyor ve gösterge dalgalanıyor. İkisine de “gürültülü pompa” demek, yararlı farkları gizler.',
          supported: 'İki örnek notta sesin zamanlaması ve basıncın davranışı farklı.', unresolved: 'Notlar pompa veya valf arızasını teşhis etmiyor; seslerin normal dışı olup olmadığını da kanıtlamıyor.',
          question: '“Su akışıyla ses de kesiliyor mu, basınç sabit mi?”', inspection: 'Demleme aşamasını, sesin süresini ve basıncın davranışını kaydet. Tam modelin kılavuzuyla karşılaştır; parça değiştirmeden önce yetkin bir servisten teşhis iste.',
        }, specs: ['Espresso', 'Dahili öğütücü', 'Manuel kontrol', 'Sıfır ürün'],
        sources: [{ initial: '1', label: 'Örnek gözlem A', detail: 'Kurgusal not · Demleme sırasında', excerpt: '“Ses 25 saniye sürüyor, demleme bitince kesiliyor; basınç sabit.”' }, { initial: '2', label: 'Örnek gözlem B', detail: 'Kurgusal not · Su akışından sonra', excerpt: '“Su durduktan sonra ses sürüyor; basınç göstergesi dalgalanıyor. Neden bilinmiyor.”' }],
      },
    },
  };
  for (const [lang, products] of Object.entries(examples)) {
    for (const product of Object.values(products)) product.fields = { ...common[lang], ...product.fields };
  }
  window.KRIKO_EXAMPLES = examples;
})();
