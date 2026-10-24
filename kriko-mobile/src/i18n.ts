/**
 * English/Turkish at runtime, with no dependency and no build step.
 *
 * The English string is the key. `translations` maps the exact text a screen
 * renders to its Turkish counterpart, and `tr` falls back to anchored patterns
 * for the runs that carry a value ("4 min ago", "3 of 10 free", "Sources · 6").
 * `Txt` reads the language through `useLanguage`, so switching it re-renders
 * every run in place, without a reload.
 *
 * Setting it: `setLanguage('tr')`. Reading it outside a component:
 * `getLanguage()`. Reading it in one: `useLanguage()`.
 *
 * A key is the string as it reaches React, so JSX whitespace is already
 * collapsed to single spaces. Add the exact English and the Turkish beside it;
 * never reword the English to fit a translation.
 */

import { useSyncExternalStore } from 'react';

export type Language = 'en' | 'tr';

let current: Language = 'en';

const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function snapshot(): Language {
  return current;
}

/** The language the UI renders in right now. */
export function getLanguage(): Language {
  return current;
}

/** Switch the UI language. Every mounted `Txt` re-renders on the change. */
export function setLanguage(lang: Language): void {
  if (lang !== 'en' && lang !== 'tr') return;
  if (lang === current) return;
  current = lang;
  for (const listener of [...listeners]) {
    try {
      listener();
    } catch {
      // One broken subscriber must not keep the rest of the UI in the old language.
    }
  }
}

/** The current language, as a value React re-renders on. */
export function useLanguage(): Language {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

/**
 * Static copy, keyed by its exact English. Every string here is one a screen
 * renders through `Txt`; names, URLs, prices and key shapes are left alone.
 */
export const translations: Record<string, string> = {


  /* ------------------------------------------------ agent settings -- */
  Answer: 'Yanıt',
  'How much the agent writes back.': 'Aracının ne kadar yazacağı.',
  Short: 'Kısa',
  Standard: 'Standart',
  'Product only': 'Yalnızca ürün',
  Thoroughness: 'Derinlik',
  'Sets the maximum search budget. Kriko may stop earlier when it has enough evidence or needs time to write the answer.':
    'En fazla arama bütçesini belirler. Yeterli kanıt bulduğunda veya yanıtı yazmak için zamana ihtiyaç duyduğunda Kriko daha erken durabilir.',
  'Share my screen': 'Ekranımı paylaş',
  'Close screen sharing': 'Ekran paylaşımını kapat',
  'Open any product page. Tap the floating Kriko button whenever you want to scan it. Read the findings over the page, or queue another product while research continues.':
    'İstediğin ürün sayfasını aç. Taramak istediğinde yüzen Kriko düğmesine dokun. Bulguları sayfanın üzerinde gör veya araştırma sürerken başka ürünleri sıraya ekle.',
  '1. Allow Kriko to display over other apps.': '1. Kriko’nun diğer uygulamaların üzerinde görünmesine izin ver.',
  '2. Approve Android’s screen sharing prompt.': '2. Android’in ekran paylaşımı isteğini onayla.',
  '3. Browse at your pace. Tap Kriko to scan.': '3. İstediğin gibi gezin. Taramak için Kriko’ya dokun.',
  'Only the frames you request are sent for reading. Stop sharing from the floating panel or Android notification.':
    'Yalnızca istediğin kareler okunmak üzere gönderilir. Paylaşımı yüzen panelden veya Android bildiriminden durdur.',
  'The floating scanner needs the updated Android build. You can still upload a screenshot here.':
    'Yüzen tarayıcı için güncel Android derlemesi gerekir. Buradan ekran görüntüsü yüklemeye devam edebilirsin.',
  'Screen sharing could not start. Try again.': 'Ekran paylaşımı başlatılamadı. Yeniden dene.',
  'Stop screen sharing': 'Ekran paylaşımını durdur',
  'Starting…': 'Başlatılıyor…',
  'Start floating scanner': 'Yüzen tarayıcıyı başlat',
  'Choose a screenshot': 'Ekran görüntüsü seç',
  'Scan queue': 'Tarama sırası',
  'Close queue': 'Taramaları kapat',
  'Cancel scan': 'Taramayı iptal et',
  'Scanned products will appear here.': 'Taranan ürünler burada görünür.',
  'Start a scan from Kriko’s floating button.': 'Taramayı Kriko’nun yüzen düğmesinden başlat.',
  'Complete': 'Tamamlandı',
  'Product scan': 'Ürün taraması',
  'New product scan': 'Yeni ürün taraması',
  'Researching this product…': 'Bu ürün araştırılıyor…',
  Cancel: 'İptal',
  Done: 'Bitti',
  queued: 'Sırada',
  running: 'Araştırılıyor',
  error: 'Hata',
  cancelled: 'İptal edildi',
  Low: 'Düşük',
  Default: 'Varsayılan',
  High: 'Yüksek',
  Language: 'Dil',
  'The interface. Answers follow the language you ask in.':
    'Arayüz. Yanıtlar sorduğunuz dilde gelir.',
  English: 'İngilizce',
  'Kriko is still working': 'Kriko hâlâ çalışıyor',
  'Stop the answer first, then start a new chat.':
    'Önce yanıtı durdurun, sonra yeni bir sohbet başlatın.',
  'Photo access is off': 'Fotoğraf erişimi kapalı',
  'That image could not be opened': 'Bu görsel açılamadı',
  'The photo picker did not open': 'Fotoğraf seçici açılmadı',

  /* ------------------------------------------------ chrome and titles -- */
  History: 'Geçmiş',
  Settings: 'Ayarlar',
  About: 'Hakkında',
  Sources: 'Kaynaklar',
  Conversation: 'Konuşma',
  'kriko / about': 'kriko / hakkında',
  'kriko / history': 'kriko / geçmiş',
  'kriko / settings': 'kriko / ayarlar',
  'kriko / sources': 'kriko / kaynaklar',

  /* --------------------------------------------------------- welcome -- */
  'What do you want to check?': 'Neyi kontrol etmek istiyorsun?',
  'A careful researcher for the product in front of you. It searches the web, reads the pages, and answers with what it found — or says what it could not.':
    'Önündeki ürün için dikkatli bir araştırmacı. Web’de arar, sayfaları okur ve bulduklarıyla yanıtlar — bulamadığını da söyler.',
  'No keys on this phone yet': 'Bu telefonda henüz anahtar yok',
  'access is the owner’s': 'erişim sahibinin',
  'Kriko Agent runs on the keys of the person who shared this build. They send an access code and a password in two separate messages; the code opens only inside Kriko.':
    'Kriko Agent, bu derlemeyi paylaşan kişinin anahtarlarıyla çalışır. Erişim kodunu ve parolayı iki ayrı mesajda gönderirler; kod yalnızca Kriko içinde açılır.',
  'Paste an access code': 'Erişim kodu yapıştır',
  'Or use my own keys': 'Ya da kendi anahtarlarımı kullan',
  'There is no Kriko account and no Kriko server. The keys are sent only to Inception and DeepSeek when you ask a question, and a screenshot is read by DeepSeek’s vision model.':
    'Kriko hesabı ve Kriko sunucusu yok. Anahtarlar yalnızca soru sorduğunda Inception ve DeepSeek’e gönderilir; ekran görüntüsünü DeepSeek’in görüntü modeli okur.',

  /* ----------------------------------------------------- access sheet -- */
  'Start with Kriko Agent': 'Kriko Agent ile başla',
  'Use Kriko Agent': 'Kriko Agent’ı kullan',
  'keys · on this phone': 'anahtarlar · bu telefonda',
  'Kriko Agent researches with Mercury and reads the web with DeepSeek. The person who shared access sends a code and a password, in two messages.':
    'Kriko Agent, Mercury ile araştırır ve Web’i DeepSeek ile okur. Erişimi paylaşan kişi kodu ve parolayı iki mesajda gönderir.',
  'Access code': 'Erişim kodu',
  'My own keys': 'Kendi anahtarlarım',
  Password: 'Parola',
  'Label (optional)': 'Etiket (isteğe bağlı)',
  'The long line that starts with S1NB…': 'S1NB… ile başlayan uzun satır',
  'The password that came separately': 'Ayrı gelen parola',
  'Who this access is from': 'Bu erişim kimden',
  'Mercury key': 'Mercury anahtarı',
  'DeepSeek key': 'DeepSeek anahtarı',
  Paste: 'Yapıştır',
  'Both are needed: Mercury writes the answer, DeepSeek searches and reads pages.':
    'İkisi de gerekli: yanıtı Mercury yazar, DeepSeek arar ve sayfaları okur.',
  'Opening…': 'Açılıyor…',
  'Use these keys': 'Bu anahtarları kullan',
  'Save the keys': 'Anahtarları kaydet',
  'The code is the owner’s keys, sealed. It opens only inside a Kriko build, and this phone keeps what it opens in the system’s secure storage.':
    'Kod, sahibinin mühürlenmiş anahtarlarıdır. Yalnızca bir Kriko derlemesinde açılır; bu telefon açtığını sistemin güvenli deposunda saklar.',
  'That did not open.': 'Bu açılmadı.',
  'Shared access': 'Paylaşılan erişim',

  /* -------------------------------------------------- screenshot sheet -- */
  'Read from the screenshot': 'Ekran görüntüsünden okundu',
  'reading the image': 'görüntü okunuyor',
  'not read': 'okunamadı',
  'check it, then ask': 'kontrol et, sonra sor',
  Reading: 'Okunuyor',
  'The image could not be read. Type what the listing says instead.':
    'Görüntü okunamadı. Bunun yerine ilanın ne dediğini yaz.',
  'Fill in the product by hand; the question still works.':
    'Ürünü elle doldur; soru yine de çalışır.',
  Brand: 'Marka',
  Product: 'Ürün',
  Model: 'Model',
  Price: 'Fiyat',
  Condition: 'Durum',
  unknown: 'bilinmiyor',
  new: 'yeni',
  used: 'kullanılmış',
  refurbished: 'yenilenmiş',
  'What the image says': 'Görüntünün söyledikleri',
  'Title, variant, specs, seller claims…': 'Başlık, varyant, özellikler, satıcı iddiaları…',
  'Your question (optional)': 'Sorun (isteğe bağlı)',
  'What should I check before buying it?': 'Satın almadan önce neyi kontrol etmeliyim?',
  'Ask about this': 'Bunu sor',
  'Reading…': 'Okunuyor…',
  'The image is sent to DeepSeek to read it. Kriko keeps only the text above and the thumbnail in your message.':
    'Görüntü, okunması için DeepSeek’e gönderilir. Kriko yalnızca yukarıdaki metni ve mesajındaki küçük resmi saklar.',

  /* -------------------------------------------------- reading a screen -- */
  'Read my screen': 'Ekranımı oku',
  'android screen access · once per read': 'android ekran erişimi · okuma başına bir kez',
  'Switch to the listing now': 'Şimdi ilana geç',
  'Kriko reads the screen when the count reaches zero. Stay on the listing until then.':
    'Sayaç sıfıra indiğinde Kriko ekranı okur. O ana kadar ilanda kal.',
  'Reading the screen…': 'Ekran okunuyor…',
  'Waiting for Android…': 'Android bekleniyor…',
  'Android will ask for screen access. Choose Entire screen, then switch to the product listing while Kriko counts four seconds.':
    'Android ekran erişimi isteyecek. Tüm ekranı seç, sonra Kriko dört saniye sayarken ürün ilanına geç.',
  'Allow screen access.': 'Ekran erişimine izin ver.',
  'Switch to the listing; Kriko reads it four seconds later.':
    'İlana geç; Kriko dört saniye sonra onu okur.',
  'The listing opens here for a check before you ask.':
    'İlan, sormadan önce kontrol için burada açılır.',
  'Try again': 'Yeniden dene',
  'Use a screenshot': 'Ekran görüntüsü kullan',
  'Screen access can be cancelled in the Android dialog at any time.':
    'Ekran erişimi Android iletişim kutusundan istediğin an iptal edilebilir.',
  'The screen could not be read. Try again, or use a screenshot.':
    'Ekran okunamadı. Yeniden dene ya da ekran görüntüsü kullan.',
  'Screen access was not granted.': 'Ekran erişimi verilmedi.',
  'Reading the screen is Android-only in this build.':
    'Ekran okuma bu derlemede yalnızca Android’de çalışır.',
  'No frame was captured. Keep Kriko in the background for a moment after you switch, then try again.':
    'Kare yakalanamadı. İlana geçtikten sonra Kriko’yu bir an arka planda tutup yeniden dene.',

  /* --------------------------------------------------- composer, chat -- */
  'Read screen': 'Ekranı oku',
  Screenshot: 'Ekran görüntüsü',
  'Ask about a product': 'Bir ürün hakkında sor',
  'Read the answer, or stop it…': 'Yanıtı oku ya da durdur…',
  'Ask about a product, or read the screen in front of you.':
    'Bir ürün hakkında sor ya da önündeki ekranı oku.',
  'Searched, read and cited. It says what it could not find instead of filling the gap.':
    'Arandı, okundu, kaynak gösterildi. Boşluğu doldurmak yerine bulamadığını söyler.',
  'What goes wrong with a Bosch GSB 600 drill?': 'Bosch GSB 600 matkapta ne ters gidebilir?',
  'Are used Galaxy Buds2 Pro worth $90?': 'Kullanılmış Galaxy Buds2 Pro 90$ eder mi?',
  'Trial used': 'Deneme bitti',
  Shared: 'Paylaşılan',
  'Own keys': 'Kendi anahtarlarım',
  'No keys': 'Anahtar yok',
  'The free questions on this phone are used up.': 'Bu telefondaki ücretsiz sorular bitti.',
  'Free questions used up · add an access code': 'Ücretsiz sorular bitti · erişim kodu ekle',
  'your own keys · this phone': 'kendi anahtarların · bu telefon',
  'no keys on this phone yet': 'bu telefonda henüz anahtar yok',
  'The turn did not start.': 'Yanıt başlamadı.',

  /* ------------------------------------------------ answers and steps -- */
  Working: 'Çalışıyor',
  Research: 'Araştırma',
  'Titles only': 'Yalnızca başlıklar',
  'Show fewer': 'Daha az göster',
  Copy: 'Kopyala',
  Copied: 'Kopyalandı',
  Stopped: 'Durduruldu',
  'No page text': 'Sayfa metni yok',
  live: 'canlı',
  'Looking for evidence…': 'Kanıt aranıyor…',
  All: 'Tümü',
  'Stopped.': 'Durduruldu.',

  /* --------------------------------------------------------- history -- */
  'Every conversation stays on this phone.': 'Her konuşma bu telefonda kalır.',
  'New chat': 'Yeni sohbet',
  Open: 'Açık',
  'Nothing asked yet': 'Henüz bir şey sorulmadı',
  'A question searches the web, reads the pages, and answers with the sources behind it. It stays here until you clear it.':
    'Bir soru Web’de arar, sayfaları okur ve arkasındaki kaynaklarla yanıtlar. Sen temizleyene kadar burada kalır.',
  'Ask the first one': 'İlkini sor',
  'Nothing asked yet. A question searches the web, reads the pages, and answers with the sources behind it.':
    'Henüz bir şey sorulmadı. Bir soru Web’de arar, sayfaları okur ve arkasındaki kaynaklarla yanıtlar.',

  /* -------------------------------------------------------- settings -- */
  'Free trial': 'Ücretsiz deneme',
  'keys shared by the owner': 'anahtarlar sahibinden',
  'The owner’s Mercury and DeepSeek keys, opened on this phone.':
    'Sahibinin Mercury ve DeepSeek anahtarları bu telefonda açık.',
  'Your own keys': 'Kendi anahtarların',
  'No access yet': 'Henüz erişim yok',
  'Mercury and DeepSeek keys stored in this phone’s secure storage.':
    'Mercury ve DeepSeek anahtarları bu telefonun güvenli deposunda saklanıyor.',
  'Paste an access code, or add your own Mercury and DeepSeek keys.':
    'Bir erişim kodu yapıştır ya da kendi Mercury ve DeepSeek anahtarlarını ekle.',
  'kriko agent · access': 'kriko agent · erişim',
  Unlocked: 'Erişim açık',
  Locked: 'Kilitli',
  'Add access': 'Erişim ekle',
  'Replace access': 'Erişimi değiştir',
  'Forget these keys': 'Bu anahtarları unut',
  'How one answer is made': 'Bir yanıt nasıl oluşur',
  'Writes the answer': 'Yanıtı yazar',
  'Searches and reads': 'Arar ve okur',
  'Reads screenshots': 'Ekran görüntülerini okur',
  'Kriko server': 'Kriko sunucusu',
  none: 'yok',
  'What leaves this phone': 'Bu telefondan ne çıkıyor',
  'Your question and the listing text read from a screenshot go to Inception, which writes the answer. Search queries and the URLs it chooses go to DeepSeek, which returns the pages. A screenshot is uploaded once to DeepSeek to be read; the image is kept only as a thumbnail in your chat. There is no analytics and no Kriko account.':
    'Sorun ve ekran görüntüsünden okunan ilan metni, yanıtı yazan Inception’a gider. Arama sorguları ve seçtiği adresler, sayfaları getiren DeepSeek’e gider. Bir ekran görüntüsü okunmak için bir kez DeepSeek’e yüklenir; görüntü sohbetinde yalnızca küçük resim olarak kalır. Analitik ve Kriko hesabı yok.',
  Conversations: 'Konuşmalar',
  'Clear every chat': 'Tüm sohbetleri temizle',
  'Nothing saved yet.': 'Henüz bir şey kaydedilmedi.',
  'Every chat, as a page instead of a sheet.':
    'Her sohbet, kayan panel değil, bir sayfa olarak.',
  'What this build is, what changed, what leaves the phone.':
    'Bu derleme ne, ne değişti, telefondan ne çıkıyor.',
  'This phone holds everything.': 'Her şey bu telefonda.',
  'Built for the friends test. Mercury and DeepSeek are third-party services.':
    'Arkadaş testi için yapıldı. Mercury ve DeepSeek üçüncü taraf hizmetlerdir.',

  /* ----------------------------------------------------------- about -- */
  'A small, local-first reader with a researcher inside.':
    'İçinde bir araştırmacı olan küçük, yerel öncelikli bir okuyucu.',
  'Kriko Agent for mobile': 'Mobil için Kriko Agent',
  'Ask what is known to go wrong with a product, or read the screen in front of you. The answer is researched on the open web, cites the pages it read, and keeps the work where you can see it.':
    'Bir üründe bilinen sorunları sor ya da önündeki ekranı oku. Yanıt açık Web’de araştırılır, okuduğu sayfaları kaynak gösterir ve çalışmayı görebileceğin yerde tutar.',
  'New in this build': 'Bu derlemede yeni',
  'A four-second capture of the listing you are already looking at. No screenshot, no photo library.':
    'Zaten baktığın ilanın dört saniyelik kaydı. Ekran görüntüsü yok, fotoğraf arşivi yok.',
  'New chat, one press': 'Yeni sohbet, tek basış',
  'The plus in the top bar starts a clean conversation without losing the old one.':
    'Üst çubuktaki artı, eskisini kaybetmeden temiz bir konuşma başlatır.',
  'Short answers': 'Kısa yanıtlar',
  'A verdict, the checks that matter, and the gap. Bullets, not paragraphs.':
    'Bir hüküm, önemli kontroller ve eksik kalan. Paragraf değil, maddeler.',
  'History and sources as pages': 'Geçmiş ve kaynaklar sayfa olarak',
  'The full record is a screen you can read, not a sheet that disappears.':
    'Tam kayıt, kaybolan bir kayan panel değil, okuyabileceğin bir ekran.',
  'Your question and the listing text go to Inception to write the answer. Search queries and chosen URLs go to DeepSeek. A screenshot or a screen read is uploaded once to DeepSeek vision. There is no Kriko account, no Kriko server and no analytics.':
    'Sorun ve ilan metni, yanıtı yazması için Inception’a gider. Arama sorguları ve seçilen adresler DeepSeek’e gider. Bir ekran görüntüsü ya da ekran okuması bir kez DeepSeek vision’a yüklenir. Kriko hesabı, Kriko sunucusu ve analitik yok.',
  'The stack': 'Yığın',
  'Plans the research and writes the answer.': 'Araştırmayı planlar ve yanıtı yazar.',
  'Finds the pages and returns their text.': 'Sayfaları bulur ve metinlerini getirir.',
  'Reads a listing screenshot or a screen capture.':
    'İlan ekran görüntüsünü ya da ekran yakalamasını okur.',
  'Built for friends to test. Mercury and DeepSeek are third-party services with their own availability and prices.':
    'Arkadaşların test etmesi için yapıldı. Mercury ve DeepSeek, kendi kullanılabilirliği ve fiyatları olan üçüncü taraf hizmetlerdir.',

  /* --------------------------------------------------------- sources -- */
  'Every page Kriko read for this chat.': 'Kriko’nun bu sohbet için okuduğu her sayfa.',
  'This chat has no sources yet. Ask a question and the pages Kriko reads will be listed here.':
    'Bu sohbetin henüz kaynağı yok. Bir soru sor; Kriko’nun okuduğu sayfalar burada listelenir.',

  /* ---------------------- engine copy that reaches a screen verbatim -- */
  'No keys on this phone yet. Paste an access code, or add your own keys.':
    'Bu telefonda henüz anahtar yok. Bir erişim kodu yapıştır ya da kendi anahtarlarını ekle.',
  'The free questions on this phone are used up. Paste an access code to keep going.':
    'Bu telefondaki ücretsiz sorular bitti. Devam etmek için erişim kodu yapıştır.',
  'The free questions on this phone are used up. Paste an access code to keep reading screenshots.':
    'Bu telefondaki ücretsiz sorular bitti. Ekran görüntülerini okumaya devam etmek için erişim kodu yapıştır.',
  'The turn failed.': 'Yanıt oluşmadı.',
  'The turn failed before it could answer.': 'Yanıt veremeden bir hata oluştu.',
  'Both keys are needed: Mercury runs the agent, DeepSeek runs the search.':
    'İki anahtar da gerekli: ajanı Mercury, aramayı DeepSeek çalıştırır.',
  'What should I know about this product?': 'Bu ürün hakkında ne bilmeliyim?',
  'What should I know before buying this?': 'Bunu satın almadan önce ne bilmeliyim?',
  'That does not look like an access code. Copy the whole line.':
    'Bu bir erişim koduna benzemiyor. Satırın tamamını kopyala.',
  'Could not open it: the password is not the one this code was made with, or the code was changed on the way.':
    'Açılamadı: parola bu kodun oluşturulduğu parola değil ya da kod yolda değişmiş.',
  'The code opened, but carried nothing readable.':
    'Kod açıldı ama okunacak bir şey taşımıyor.',
  'This build cannot open access codes: it was made without its share pepper.':
    'Bu derleme erişim kodlarını açamıyor: paylaşım pepper’ı olmadan derlenmiş.',
  'Paste the password that came with the code as well.':
    'Kodla gelen parolayı da yapıştır.',
  'That code carries no keys.': 'Bu kod anahtar taşımıyor.',
  'The provider refused this key. The access code may have been replaced, or the key is no longer valid.':
    'Sağlayıcı bu anahtarı reddetti. Erişim kodu değiştirilmiş olabilir ya da anahtar artık geçerli değil.',
  'The provider account behind this access has no credit left. Ask the person who shared it.':
    'Bu erişimin arkasındaki sağlayıcı hesabında kredi kalmadı. Paylaşan kişiye sor.',
  'The provider is rate-limiting this key. Wait a minute and ask again.':
    'Sağlayıcı bu anahtarı hız sınırına takmış. Bir dakika bekleyip yeniden sor.',
  'The search had no words in it.': 'Aramanın içinde kelime yoktu.',
  'That is not a readable page address.': 'Bu, okunabilir bir sayfa adresi değil.',
  'No results': 'Sonuç yok',
  'No search was run, so this answer is not verified against a page.':
    'Arama yapılmadı; bu yanıt bir sayfayla doğrulanmadı.',
  'No page text was readable — this answer rests on titles and snippets.':
    'Okunabilir sayfa metni yoktu — bu yanıt başlıklara ve alıntılara dayanıyor.',
  'The agent used its research budget without writing an answer. Ask again, or narrow the question.':
    'Ajan, yanıt yazmadan araştırma bütçesini tüketti. Yeniden sor ya da soruyu daralt.',
  'The agent asked for more web access after its retrieval budget ended. Ask again, or narrow the question.':
    'Ajan, arama bütçesi bittikten sonra daha fazla Web erişimi istedi. Yeniden sor ya da soruyu daralt.',
  'The image reader did not answer in the expected shape.':
    'Görüntü okuyucu beklenen biçimde yanıt vermedi.',
  'Fetch only accepts a URL returned by search':
    'Getirme yalnızca aramadan dönen bir adresi kabul eder',
  'Unsupported tool': 'Desteklenmeyen araç',
  'Refused a fetch that search did not return': 'Aramadan dönmeyen bir getirme reddedildi',
};

/**
 * The runs a dictionary cannot hold because a value moves inside them. Each
 * pattern is anchored, so it can only rewrite a whole run, never a fragment of
 * a sentence that happens to contain one of these words.
 */
const patterns: readonly (readonly [RegExp, string])[] = [
  [/^(\d+) products? in progress$/, '$1 ürün işleniyor'],
  [/^Reviews · (.+)$/, 'Yorumlar · $1'],
  [/^Source (\d+): (.+)$/, 'Kaynak $1: $2'],
  /* "2 min ago", "3 days ago" — the history timestamps. */
  [/^just now$/, 'az önce'],
  [/^(\d+) min ago$/, '$1 dk önce'],
  [/^(\d+) h ago$/, '$1 sa önce'],
  [/^yesterday$/, 'dün'],
  [/^(\d+) days ago$/, '$1 gün önce'],

  /* Counts. Turkish takes the bare noun after a number. */
  [/^(\d+) questions?$/, '$1 soru'],
  [/^(\d+) conversations?$/, '$1 konuşma'],
  [/^(\d+) chats?$/, '$1 sohbet'],
  [/^(\d+) messages$/, '$1 mesaj'],
  [/^(\d+) steps?$/, '$1 adım'],
  [/^(\d+) searches?$/, '$1 arama'],
  [/^(\d+) pages? read$/, '$1 sayfa okundu'],
  [/^(\d+) searches? · (\d+) pages? read$/, '$1 arama · $2 sayfa okundu'],
  [/^(\d+) chats? · (\d+) messages$/, '$1 sohbet · $2 mesaj'],
  [/^(\d+) left$/, '$1 kaldı'],
  [/^(\d+) of (\d+) free$/, '$1 / $2 ücretsiz'],

  /* Trial and access copy that carries the allowance. */
  [
    /^(\d+) of (\d+) questions left on this phone, on the owner’s keys\.$/,
    'Sahibinin anahtarlarıyla bu telefonda $1 / $2 soru kaldı.',
  ],
  [
    /^(\d+) free questions? left · owner’s keys$/,
    '$1 ücretsiz soru kaldı · sahibinin anahtarları',
  ],
  [
    /^The (\d+) free questions on this phone are used up\. Paste an access code to keep going\.$/,
    'Bu telefondaki $1 ücretsiz soru bitti. Devam etmek için erişim kodu yapıştır.',
  ],
  [
    /^keys shared by (.+)$/,
    'anahtarları paylaşan: $1',
  ],
  [
    /^(.+)’s Mercury and DeepSeek keys, opened on this phone\.$/,
    '$1 kullanıcısının Mercury ve DeepSeek anahtarları bu telefonda açık.',
  ],

  /* Lists, counters and build lines. */
  [/^Sources · (\d+)$/, 'Kaynaklar · $1'],
  [/^Show all (\d+)$/, 'Tümünü göster ($1)'],
  [/^Answer (\d+) · (.+)$/, 'Yanıt $1 · $2'],
  [/^Latest answer · (.+)$/, 'Son yanıt · $1'],
  [/^version (.+) · friends test$/, 'sürüm $1 · arkadaş testi'],
  [/^Kriko Agent for mobile · (.+)$/, 'Mobil için Kriko Agent · $1'],
];

function lookup(text: string): string | undefined {
  if (!Object.prototype.hasOwnProperty.call(translations, text)) return undefined;
  return translations[text];
}

/**
 * `text` in Turkish, or `text` itself when there is nothing to say differently.
 * Exact dictionary match first, then the anchored patterns, then the original.
 * It never throws and never returns `undefined`.
 */
export function tr(text: string, lang?: Language): string {
  try {
    if (!text) return text;
    const target = lang ?? current;
    if (target !== 'tr') return text;

    const exact = lookup(text);
    if (exact !== undefined) return exact;

    // JSX has already collapsed whitespace, but a caller can hand over a string
    // from a template literal with a newline in it; try that shape too.
    const collapsed = text.replace(/\s+/g, ' ').trim();
    if (collapsed !== text) {
      const found = lookup(collapsed);
      if (found !== undefined) return found;
    }
    if (!collapsed) return text;

    for (const [pattern, replacement] of patterns) {
      if (pattern.test(collapsed)) return collapsed.replace(pattern, replacement);
    }
    return text;
  } catch {
    return text;
  }
}
