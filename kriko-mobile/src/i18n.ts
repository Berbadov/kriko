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
 * Upper-case a run the way the reader's language does it.
 *
 * Turkish has two letters I: `i` capitalises to `İ` and `ı` to `I`. A native
 * `textTransform: 'uppercase'` follows the phone's locale, not the app's, so an
 * English-locale phone showing Turkish drew "GEÇMIŞ" for "geçmiş". The mapping
 * is done here, once, before the string reaches the native text view.
 */
export function upper(text: string, lang: Language = current): string {
  if (lang !== 'tr') return text.toUpperCase();
  return text.replace(/i/g, 'İ').replace(/ı/g, 'I').toUpperCase();
}

/**
 * Static copy, keyed by its exact English. Every string here is one a screen
 * renders through `Txt`; names, URLs, prices and key shapes are left alone.
 */
export const translations: Record<string, string> = {
  /* -------------------------------------------------- chat scroll rail -- */
  'Scroll the conversation': 'Sohbeti kaydır',
  'Scroll down': 'Aşağı kaydır',
  'Scroll up': 'Yukarı kaydır',


  /* ------------------------------------------------ agent settings -- */
  Answer: 'Yanıt',
  'How much the agent writes back.': 'Ajanın ne kadar yazacağı.',
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
  '3. Browse at your pace. Tap Kriko to scan.': '3. İstediğin gibi gez. Taramak için Kriko’ya dokun.',
  'Only the frames you request are sent for reading. Stop sharing from the floating panel or Android notification.':
    'Yalnızca istediğin kareler okunmak üzere gönderilir. Paylaşımı yüzen panelden veya Android bildiriminden durdur.',
  'The floating scanner needs the updated Android build. You can still upload a screenshot here.':
    'Yüzen tarayıcı için güncel Android derlemesi gerekir. Buradan ekran görüntüsü yüklemeye devam edebilirsin.',
  'Screen sharing could not start. Try again.': 'Ekran paylaşımı başlatılamadı. Yeniden dene.',
  'Stop screen sharing': 'Ekran paylaşımını durdur',
  'Floating screen scan': 'Yüzen ekran taraması',
  "Shows when Kriko's user-started floating scan session is active.":
    'Kriko’nun senin başlattığın yüzen tarama oturumu açıkken görünür.',
  'Starting…': 'Başlatılıyor…',
  'Start floating scanner': 'Yüzen tarayıcıyı başlat',
  'Choose a screenshot': 'Ekran görüntüsü seç',
  'Scan queue': 'Tarama sırası',
  'Close queue': 'Sırayı kapat',
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
    'Arayüz. Yanıtlar sorduğun dilde gelir.',
  English: 'İngilizce',
  'Kriko is still working': 'Kriko hâlâ çalışıyor',
  'Stop the answer first, then start a new chat.':
    'Önce yanıtı durdur, sonra yeni bir sohbet başlat.',
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
  settings: 'ayarlar',
  about: 'hakkında',
  history: 'geçmiş',
  sources: 'kaynaklar',
  'your scans': 'taramaların',
  'your shelf': 'rafın',

  /* --------------------------------------------------------- welcome -- */
  'What do you want to check?': 'Neyi kontrol etmek istiyorsun?',
  'A careful researcher for the product in front of you. It searches the web, reads the pages, and answers with what it found — or says what it could not.':
    'Önündeki ürün için dikkatli bir araştırmacı. Webde arar, sayfaları okur ve bulduklarıyla yanıtlar — bulamadığını da söyler.',
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
    'Kriko Agent, Mercury ile araştırır ve webi DeepSeek ile okur. Erişimi paylaşan kişi kodu ve parolayı iki mesajda gönderir.',
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
  'What the image says': 'Görüntüde yazanlar',
  'Title, variant, specs, seller claims…': 'Başlık, varyant, özellikler, satıcı iddiaları…',
  'Your question (optional)': 'Sorduğun soru (isteğe bağlı)',
  'What should I check before buying it?': 'Satın almadan önce neyi kontrol etmeliyim?',
  'Ask about this': 'Bunu sor',
  'Reading…': 'Okunuyor…',
  'The image is sent to DeepSeek to read it. Kriko keeps only the text above and the thumbnail in your message.':
    'Görüntü, okunması için DeepSeek’e gönderilir. Kriko yalnızca yukarıdaki metni ve mesajındaki küçük resmi saklar.',

  /* -------------------------------------------------- reading a screen -- */
  'Read my screen': 'Ekranımı oku',
  'android screen access · once per read': 'Android ekran erişimi · okuma başına bir kez',
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
    'Bir soru webde arar, sayfaları okur ve arkasındaki kaynaklarla yanıtlar. Sen temizleyene kadar burada kalır.',
  'Ask the first one': 'İlkini sor',
  'Nothing asked yet. A question searches the web, reads the pages, and answers with the sources behind it.':
    'Henüz bir şey sorulmadı. Bir soru webde arar, sayfaları okur ve arkasındaki kaynaklarla yanıtlar.',

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
    'Sorduğun soru ve ekran görüntüsünden okunan ilan metni, yanıtı yazan Inception’a gider. Arama sorguları ve seçtiği adresler, sayfaları getiren DeepSeek’e gider. Bir ekran görüntüsü okunmak için bir kez DeepSeek’e yüklenir; görüntü sohbetinde yalnızca küçük resim olarak kalır. Analitik ve Kriko hesabı yok.',
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
    'Bir üründe bilinen sorunları sor ya da önündeki ekranı oku. Yanıt açık webde araştırılır, okuduğu sayfaları kaynak gösterir ve çalışmayı görebileceğin yerde tutar.',
  'New in this build': 'Bu derlemede yeni',
  'A four-second capture of the listing you are already looking at. No screenshot, no photo library.':
    'Zaten baktığın ilanın dört saniyelik kaydı. Ekran görüntüsü yok, fotoğraf arşivi yok.',
  'New chat, one press': 'Yeni sohbet, tek basış',
  'The plus in the top bar starts a clean conversation without losing the old one.':
    'Üst çubuktaki artı, eskisini kaybetmeden temiz bir konuşma başlatır.',
  'Short answers': 'Kısa yanıtlar',
  'A verdict, the checks that matter, and the gap. Bullets, not paragraphs.':
    'Bir karar, önemli kontroller ve eksik kalan. Paragraf değil, maddeler.',
  'History and sources as pages': 'Geçmiş ve kaynaklar sayfa olarak',
  'The full record is a screen you can read, not a sheet that disappears.':
    'Tam kayıt, kaybolan bir kayan panel değil, okuyabileceğin bir ekran.',
  'Your question and the listing text go to Inception to write the answer. Search queries and chosen URLs go to DeepSeek. A screenshot or a screen read is uploaded once to DeepSeek vision. There is no Kriko account, no Kriko server and no analytics.':
    'Sorduğun soru ve ilan metni, yanıtı yazması için Inception’a gider. Arama sorguları ve seçilen adresler DeepSeek’e gider. Bir ekran görüntüsü ya da ekran okuması bir kez DeepSeek vision’a yüklenir. Kriko hesabı, Kriko sunucusu ve analitik yok.',
  'The stack': 'Altyapı',
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
    'Bu derleme erişim kodlarını açamıyor: paylaşım için gereken gizli değer olmadan derlenmiş.',
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
    'Ajan, arama bütçesi bittikten sonra daha fazla web erişimi istedi. Yeniden sor ya da soruyu daralt.',
  'The image reader did not answer in the expected shape.':
    'Görüntü okuyucu beklenen biçimde yanıt vermedi.',
  'Fetch only accepts a URL returned by search':
    'Sayfa okuma yalnızca aramadan dönen bir adresi kabul eder',
  'Unsupported tool': 'Desteklenmeyen araç',
  'Refused a fetch that search did not return': 'Aramadan dönmeyen bir sayfa okuma isteği reddedildi',

  /* ------------------------------------------------ about this build -- */
  Back: 'Geri',
  'A local-first reader, with a researcher inside.':
    'İçinde bir araştırmacı olan, yerel öncelikli bir okuyucu.',
  'Know what you’re buying.': 'Ne aldığını bil.',
  'Ask what is known to go wrong, or read a product listing in front of you. Kriko researches the open web, cites the pages it read, and keeps the work where you can see it.':
    'Neyin ters gidebildiğini sor ya da önündeki ürün ilanını oku. Kriko açık webde araştırır, okuduğu sayfaları kaynak gösterir ve çalışmayı görebileceğin yerde tutar.',
  'Made to stay clear': 'Anlaşılır kalmak için tasarlandı',
  'Scan as you browse': 'Gezinirken tara',
  'Tap the floating Kriko button to capture the listing and read findings over the product page.':
    'İlanı yakalamak için yüzen Kriko düğmesine dokun ve bulguları ürün sayfasının üzerinde oku.',
  'Keep several products moving': 'Birden çok ürünü ilerlet',
  'Queue another scan while research continues. Each result keeps its own sources and conversation.':
    'Araştırma sürerken başka bir taramayı sıraya ekle. Her sonuç kendi kaynaklarını ve konuşmasını korur.',
  'Check the exact store': 'Tam mağazayı kontrol et',
  'Read comments from the selected site, with an optional product URL and no review substitution.':
    'Seçilen sitedeki yorumları oku; ürün adresi isteğe bağlıdır ve başka sitenin yorumu kullanılmaz.',
  'See the work': 'Çalışmayı gör',
  'Searches stop when evidence is enough or stops improving, leaving time to write the answer.':
    'Kanıt yeterli olduğunda veya yenisi gelmediğinde aramalar durur; yanıtı yazmaya zaman kalır.',
  'Your question and listing text go to Inception to write the answer. Search queries and chosen URLs go to DeepSeek. Screenshots are uploaded once to DeepSeek vision for reading, then kept only as a thumbnail in the conversation. There is no Kriko account, server, or analytics.':
    'Sorduğun soru ve ilan metni, yanıtı yazması için Inception’a gider. Arama sorguları ve seçilen adresler DeepSeek’e gider. Ekran görüntüleri okunmak üzere bir kez DeepSeek vision’a yüklenir, sonra konuşmada yalnızca küçük resim olarak kalır. Kriko hesabı, sunucusu ve analitik yoktur.',
  Answers: 'Yanıtlar',
  'Search and pages': 'Arama ve sayfalar',
  'Image reading': 'Görüntü okuma',
  'UIArc license': 'UIArc lisansı',
  'Motion by UIArc': 'Hareket: UIArc',
  'Native adaptation · MIT license': 'Yerel uyarlama · MIT lisansı',
  'Kriko on GitHub': 'Kriko, GitHub’da',
  'Open source': 'Açık kaynak',
  Visit: 'Aç',
  'Mercury and DeepSeek are independent services with their own availability and prices.':
    'Mercury ve DeepSeek, kendi kullanılabilirliği ve fiyatları olan bağımsız hizmetlerdir.',

  /* ------------------------------------------------------ history -- */
  'Delete this chat?': 'Bu sohbet silinsin mi?',
  Keep: 'Vazgeç',
  Delete: 'Sil',
  'The questions you asked, and what the scans found.':
    'Sorduğun sorular ve taramaların buldukları.',
  'New conversation': 'Yeni konuşma',
  'A clear page.': 'Temiz bir sayfa.',
  'Your conversations and product scans will appear here as you use Kriko.':
    'Kriko’yu kullandıkça konuşmaların ve ürün taramaların burada görünür.',
  'Scanned products': 'Taranan ürünler',
  Queue: 'Sıra',
  'No sources yet.': 'Henüz kaynak yok.',
  'Ask a question and the pages Kriko reads will appear here.':
    'Bir soru sor; Kriko’nun okuduğu sayfalar burada görünür.',

  /* ----------------------------------------------------- settings -- */
  'Forget these keys?': 'Bu anahtarlar unutulsun mu?',
  'The opened keys are removed from this phone. Your conversations stay.':
    'Açılan anahtarlar bu telefondan kaldırılır. Konuşmaların kalır.',
  Forget: 'Unut',
  'Clear every chat?': 'Tüm sohbetler temizlensin mi?',
  Clear: 'Temizle',
  'Reset preferences?': 'Tercihler sıfırlansın mı?',
  'Every appearance, text-size, motion and answer choice goes back to its default. Keys, conversations and scans stay.':
    'Görünüm, yazı boyutu, hareket ve yanıt seçimlerinin tümü varsayılanına döner. Anahtarlar, konuşmalar ve taramalar kalır.',
  Reset: 'Sıfırla',
  'A few choices. Everything stays on this phone.':
    'Birkaç seçim. Her şey bu telefonda kalır.',
  Access: 'Erişim',
  Appearance: 'Görünüm',
  Theme: 'Tema',
  'System follows your phone. White is brightest.':
    'Sistem telefonunu izler. En parlak seçenek beyazdır.',
  'Text size': 'Yazı boyutu',
  'How large every answer and label is drawn.':
    'Her yanıtın ve etiketin ne kadar büyük çizileceği.',
  Small: 'Küçük',
  Large: 'Büyük',
  Motion: 'Hareket',
  'Transitions and reveals. System follows your phone’s setting.':
    'Geçişler ve açılışlar. Sistem, telefonunun ayarını izler.',
  System: 'Sistem',
  Reduced: 'Azaltılmış',
  Full: 'Tam',
  Haptics: 'Dokunsal geri bildirim',
  'A small tap when you choose or act.':
    'Seçtiğinde veya bir işlem yaptığında küçük bir dokunuş.',
  'Interface language': 'Arayüz dili',
  'Answers follow the language you ask in.': 'Yanıtlar sorduğun dilde gelir.',
  'How Kriko answers': 'Kriko nasıl yanıtlar',
  'Answer length': 'Yanıt uzunluğu',
  'Choose how much the agent writes.': 'Ajanın ne kadar yazacağını seç.',
  'Research depth': 'Araştırma derinliği',
  'Sets the maximum search budget. Kriko may stop early when the evidence is enough.':
    'En yüksek arama bütçesini belirler. Kanıt yeterli olduğunda Kriko erken durabilir.',
  Light: 'Hafif',
  Deep: 'Derin',
  'What happens to your data': 'Verilerine ne olur',
  'Writes answers': 'Yanıtı yazar',
  'Your question and listing text go to Inception. Search queries and chosen pages go to DeepSeek. A screenshot is uploaded once for reading and kept only as a chat thumbnail. No Kriko account, server, or analytics.':
    'Sorduğun soru ve ilan metni Inception’a gider. Arama sorguları ve seçilen sayfalar DeepSeek’e gider. Bir ekran görüntüsü okunmak üzere bir kez yüklenir ve yalnızca sohbet küçük resmi olarak saklanır. Kriko hesabı, sunucusu veya analitik yok.',
  'Saved conversations': 'Kaydedilen konuşmalar',
  'Clear chats and scan results': 'Sohbetleri ve tarama sonuçlarını temizle',
  More: 'Daha fazla',
  'Chats, scans, and the pages behind them.':
    'Sohbetler, taramalar ve arkalarındaki sayfalar.',
  'About Kriko': 'Kriko hakkında',
  'How this build works and what it sends.':
    'Bu derlemenin nasıl çalıştığı ve ne gönderdiği.',
  'Reset preferences': 'Tercihleri sıfırla',
  'Put every choice on this screen back to its default.':
    'Bu ekrandaki her seçimi varsayılanına döndür.',
  Dark: 'Koyu',
  Paper: 'Kâğıt',
  White: 'Beyaz',

  /* ------------------------------------------------- access sheet -- */
  'Keys stay on this phone.': 'Anahtarlar bu telefonda kalır.',
  Close: 'Kapat',
  'The person who shares access sends a code and password separately. Or add your own provider keys.':
    'Erişimi paylaşan kişi kodu ve parolayı ayrı ayrı gönderir. Ya da kendi sağlayıcı anahtarlarını ekle.',
  'Paste the access code': 'Erişim kodunu yapıştır',
  'Sent separately': 'Ayrı gönderildi',
  'Label · optional': 'Etiket · isteğe bağlı',
  'Mercury writes the answer. DeepSeek searches and reads the web.':
    'Yanıtı Mercury yazar. DeepSeek arar ve webi okur.',
  'Opening access on this phone…': 'Erişim bu telefonda açılıyor…',
  'Access codes are checked on this phone. Opened keys are stored in the system’s secure storage and are never shown again.':
    'Erişim kodları bu telefonda denetlenir. Açılan anahtarlar sistemin güvenli deposunda saklanır ve bir daha gösterilmez.',

  /* ------------------------------------------------------ chrome -- */
  'a closer look': 'daha yakından',
  Home: 'Ana sayfa',
  'Your question': 'Sorduğun soru',
  Stop: 'Durdur',
  'Scan a product': 'Bir ürün tara',
  'Scan page': 'Sayfayı tara',
  Image: 'Görsel',
  'Your chats and product scans.': 'Sohbetlerin ve ürün taramaların.',
  'Close history': 'Geçmişi kapat',
  'Your chats and scans will stay here.': 'Sohbetlerin ve taramaların burada kalır.',
  'Close sheet': 'Paneli kapat',
  Beta: 'Beta',
  'Checking the product': 'Ürün kontrol ediliyor',
  'Research notes': 'Araştırma notları',
  'Open all sources': 'Tüm kaynakları aç',
  'Copy the answer': 'Yanıtı kopyala',
  'Show the research steps': 'Araştırma adımlarını göster',
  'Hide the research steps': 'Araştırma adımlarını gizle',

  /* --------------------------------------------- floating scanner -- */
  Scan: 'Tara',
  Now: 'Şimdi',
  'Read site comments': 'Site yorumlarını oku',
  'Review site (optional)': 'İnceleme sitesi (isteğe bağlı)',
  Queued: 'Sırada',
  Running: 'Çalışıyor',
  Error: 'Hata',
  Cancelled: 'İptal edildi',
  'Queue is full': 'Sıra dolu',
  'Tap Kriko to scan this page. Press and hold for more.':
    'Bu sayfayı taramak için Kriko’ya dokun. Daha fazlası için basılı tut.',
  'Drop here to stop sharing': 'Paylaşımı durdurmak için buraya bırak',
  'Kriko keeps reading. The answer will be in History.':
    'Kriko okumaya devam ediyor. Yanıt Geçmiş’te olacak.',
  'Kriko screen scan is active': 'Kriko ekran taraması açık',
  'Tap the floating K to scan one screen when you choose.':
    'İstediğinde tek bir ekranı taramak için yüzen K’ye dokun.',
  'Scan a product page. Each scan joins the queue here.':
    'Bir ürün sayfası tara. Her tarama burada sıraya girer.',
  'Scan a product page to see its answer and sources here.':
    'Yanıtını ve kaynaklarını burada görmek için bir ürün sayfası tara.',
  'Could not read that screen. Try scanning again.':
    'Ekran okunamadı. Yeniden taramayı dene.',
  'Could not open that source.': 'O kaynak açılamadı.',
  'Identifying appearance and product details…': 'Görünüm ve ürün ayrıntıları tanınıyor…',
  'The page could not be read.': 'Sayfa okunamadı.',
  'Wait for a product to finish, or cancel a queued scan.':
    'Bir ürünün bitmesini bekle ya da sıradaki taramayı iptal et.',
  'site comments': 'site yorumları',
  'One at a time is fine.': 'Tek seferde bir tane yeterli.',
  'Products you scan while browsing will gather here, with their findings and sources.':
    'Gezinirken taradığın ürünler, bulguları ve kaynaklarıyla birlikte burada toplanır.',
  'Gathering useful evidence…': 'İşe yarar kanıt toplanıyor…',
  'Scan products while you browse.': 'Gezinirken ürünleri tara.',
  'Allow Kriko over other apps.': 'Kriko’nun diğer uygulamaların üzerinde görünmesine izin ver.',
  'Approve Android’s screen sharing prompt.': 'Android’in ekran paylaşımı isteğini onayla.',
  'Open the page you want, then tap the K to scan it. Press and hold for more.':
    'İstediğin sayfayı aç, sonra taramak için K’ye dokun. Daha fazlası için basılı tut.',
  'Only screens you scan are sent for reading. Stop by dropping the K on the ×, from its menu, or from the Android notification.':
    'Yalnızca taradığın ekranlar okunmak üzere gönderilir. K’yi ×’in üzerine bırakarak, menüsünden ya da Android bildiriminden durdur.',
  'Scan this page': 'Bu sayfayı tara',
  'Scan again': 'Yeniden tara',
  'Results': 'Sonuçlar',
  'Site comments': 'Site yorumları',

  /* ------------------------------------------------ screenshot read -- */
  'Identify the product': 'Ürünü tanımla',
  'Full screenshot being read': 'Tam ekran görüntüsü okunuyor',
  'Recognising the product': 'Ürün tanınıyor',
  'Try reading again': 'Okumayı yeniden dene',
  'Possible:': 'Olası:',
  'confidence · visual match': 'güven · görsel eşleşme',
  'Similar models may look alike. These matches guide research; they do not confirm the exact model.':
    'Benzer modeller birbirine benzeyebilir. Bu eşleşmeler araştırmaya yön verir; tam modeli doğrulamaz.',
  'Listing details': 'İlan ayrıntıları',
  'Adjust anything that looks off.': 'Yanlış görünen her şeyi düzelt.',
  'Visible listing text': 'Görünen ilan metni',
  'Your question · optional': 'Sorduğun soru · isteğe bağlı',
  'The image is sent to DeepSeek to read it. Kriko keeps the observations above and the thumbnail in your message.':
    'Görüntü okunması için DeepSeek’e gönderilir. Kriko yalnızca yukarıdaki gözlemleri ve mesajındaki küçük resmi saklar.',

  /* --------------------------------------------- engine errors and copy -- */
  'The Android floating scan bubble is unavailable in this build.':
    'Android’in yüzen tarama balonu bu derlemede yok.',
  'Screen reading stopped.': 'Ekran okuma durdu.',
  'No screen frame was captured. Keep Kriko in the background until the countdown ends, then try again.':
    'Ekran karesi yakalanamadı. Geri sayım bitene kadar Kriko’yu arka planda tut, sonra yeniden dene.',
  'The captured screen image is incomplete. Try again with the listing fully loaded.':
    'Yakalanan ekran görüntüsü eksik. İlan tam yüklendikten sonra yeniden dene.',
  'The captured screen image could not be read. Try again.':
    'Yakalanan ekran görüntüsü okunamadı. Yeniden dene.',
  'Kriko needs to see the screenshot you choose. Turn on Photos access in Android settings, then try again.':
    'Kriko’nun seçtiğin ekran görüntüsünü görmesi gerekir. Android ayarlarından Fotoğraflar erişimini aç, sonra yeniden dene.',
  'Try another screenshot from Photos.': 'Fotoğraflar’dan başka bir ekran görüntüsü dene.',
  'Try again, or type the product instead.': 'Yeniden dene ya da ürünü elle yaz.',
  'Screen sharing is on': 'Ekran paylaşımı açık',
  'Floating scanner ready · requested scans only':
    'Yüzen tarayıcı hazır · yalnızca istediğin taramalar',
  'Could not stop screen sharing.': 'Ekran paylaşımı durdurulamadı.',

  /* -------------------------------------------------------- landing -- */
  'BUY WITH A CLEARER PICTURE': 'DAHA NET BİR BAKIŞLA AL',
  'Take a closer look.': 'Daha yakından bak.',
  'Scan a listing or ask a question. Kriko checks the details against independent sources.':
    'Bir ilanı tara ya da soru sor. Kriko ayrıntıları bağımsız kaynaklarla karşılaştırır.',
  'Read the page open on your phone': 'Telefonunda açık olan sayfayı oku',
  'Choose a screenshot instead': 'Bunun yerine ekran görüntüsü seç',
  'Recently scanned': 'Son tarananlar',
  'Open the saved scan': 'Kaydedilen taramayı aç',
  'Your recent product scans': 'Son ürün taramaların',
  'Evidence first. Clear about what is missing.': 'Önce kanıt. Eksik olan açıkça söylenir.',

  /* -------------------------------------------------------- welcome -- */
  'A MORE INFORMED PURCHASE': 'DAHA BİLGİLİ BİR ALIŞVERİŞ',
  'Look beyond the listing.': 'İlanın ötesine bak.',
  'Kriko checks product details against independent sources, then gives you a clear account of what it found.':
    'Kriko ürün ayrıntılarını bağımsız kaynaklarla karşılaştırır, sonra bulduklarını açıkça anlatır.',
  'Choose how to connect': 'Nasıl bağlanacağını seç',
  'No Kriko account is needed.': 'Kriko hesabı gerekmez.',
  'Use the shared access': 'Paylaşılan erişimi kullan',
  'Enter the access code and password from the person who shared this build. They arrive separately for your security.':
    'Bu derlemeyi paylaşan kişiden erişim kodunu ve parolayı gir. Güvenliğin için ayrı ayrı gelirler.',
  'Enter access code': 'Erişim kodunu gir',
  'I have my own provider keys': 'Kendi sağlayıcı anahtarlarım var',
  'Set up keys': 'Anahtarları ayarla',
  'Your question and the product details go to the research providers. Kriko keeps your chats on this phone.':
    'Sorduğun soru ve ürün ayrıntıları araştırma sağlayıcılarına gider. Kriko sohbetlerini bu telefonda tutar.',

  /* ------------------------------------------- vision errors and notes -- */
  'the image reader ran out of room before it could answer':
    'görüntü okuyucunun yanıt için yeri kalmadı',
  'the image reader was cut off before it returned usable product details':
    'görüntü okuyucu kullanılabilir ürün ayrıntıları vermeden kesildi',
  'The image reader replied in prose, so these details are observations, not a confirmed identity.':
    'Görüntü okuyucu düz metin yanıt verdi; bu ayrıntılar gözlemdir, doğrulanmış bir kimlik değildir.',

  /* ------------------------------------------------- the scanned picture -- */
  'Scanned page': 'Taranan sayfa',
  'Open the scanned picture': 'Taranan resmi aç',
  'Close the picture': 'Resmi kapat',
  'Checking this page': 'Bu sayfa kontrol ediliyor',

  /* ------------------------------------- the floating K and the assistant -- */
  'Screen capture paused': 'Ekran yakalama duraklatıldı',
  'Screen capture stopped. Tap Scan on the floating K to start it again.':
    'Ekran yakalama durdu. Yeniden başlatmak için yüzen K’deki Tara’ya dokun.',
  'Open Kriko and start the scanner again.': 'Kriko’yu açıp tarayıcıyı yeniden başlat.',
  'Opening Kriko…': 'Kriko açılıyor…',
  'Scanning this screen': 'Bu ekran taranıyor',
  'Kriko could not see your screen. In your phone’s assistant settings, turn on “Use screenshot”.':
    'Kriko ekranını göremedi. Telefonunun asistan ayarlarında “Ekran görüntüsünü kullan” seçeneğini aç.',
  'Floating scanner': 'Yüzen tarayıcı',
  Transparency: 'Saydamlık',
  'How see-through the floating K and its glass panels are. Faint shows the most of your page; Solid shows none.':
    'Yüzen K ve cam panellerin ne kadar şeffaf olacağı. Silik sayfanı en çok gösterir; Tam hiç göstermez.',
  'Answer over your page': 'Yanıt sayfanın üstünde',
  'The answer opens over the page you scanned, so you never leave it.':
    'Yanıt taradığın sayfanın üstünde açılır, o sayfadan hiç çıkmazsın.',
  'Allow Kriko over other apps and the answer opens over the page you scanned, instead of taking you into Kriko.':
    'Kriko’nun diğer uygulamaların üzerinde görünmesine izin ver; yanıt seni Kriko’ya götürmek yerine taradığın sayfanın üstünde açılır.',
  Allowed: 'İzinli',
  Off: 'Kapalı',
  'Over-other-apps settings': 'Üstte gösterme ayarları',
  'Allow over other apps': 'Diğer uygulamaların üzerinde göster',
  Faint: 'Silik',
  Soft: 'Yumuşak',
  Strong: 'Güçlü',
  Solid: 'Tam',
  'Phone assistant': 'Telefon asistanı',
  'Kriko is your phone’s assistant. Hold the power or home button to scan the screen at once.':
    'Kriko telefonunun asistanı. Ekranı hemen taramak için güç veya ana ekran düğmesini basılı tut.',
  'Make Kriko your phone’s assistant, then hold the power or home button to scan the screen at once.':
    'Kriko’yu telefonunun asistanı yap, sonra ekranı hemen taramak için güç veya ana ekran düğmesini basılı tut.',
  'Reading your screen': 'Ekranın okunuyor',
  'Kriko could not finish': 'Kriko bitiremedi',
  'Kriko is checking the page you were on. The answer opens in a new chat.':
    'Kriko bulunduğun sayfayı kontrol ediyor. Yanıt yeni bir sohbette açılır.',
  'Back to chat': 'Sohbete dön',
  'Scan with a long press': 'Uzun basarak tara',
  'Set as assistant': 'Asistan olarak ayarla',
  'Assistant settings': 'Asistan ayarları',
  'Active': 'Açık',
  'Not set': 'Ayarlı değil',
  'In the list, choose Kriko under Digital assistant app, and keep “Use screenshot” on.':
    'Listede Dijital asistan uygulaması altında Kriko’yu seç ve “Ekran görüntüsünü kullan” seçeneğini açık tut.',
  'Kriko could not read the screenshot your phone sent. Try again.':
    'Kriko telefonunun gönderdiği ekran görüntüsünü okuyamadı. Tekrar dene.',
  'Kriko did not receive a screenshot. In your phone’s assistant settings, turn on “Use screenshot”.':
    'Kriko bir ekran görüntüsü almadı. Telefonunun asistan ayarlarında “Ekran görüntüsünü kullan” seçeneğini aç.',
};

/**
 * The runs a dictionary cannot hold because a value moves inside them. Each
 * pattern is anchored, so it can only rewrite a whole run, never a fragment of
 * a sentence that happens to contain one of these words.
 */
const patterns: readonly (readonly [RegExp, string])[] = [
  [/^Version (.+) · Friends test$/, 'Sürüm $1 · Arkadaş testi'],
  [
    /^Kriko Agent for mobile · (.+) · Mercury and DeepSeek are third-party services\.$/,
    'Mobil için Kriko Agent · $1 · Mercury ve DeepSeek üçüncü taraf hizmetlerdir.',
  ],
  [/^Open scan result for (.+)$/, '$1 için tarama sonucunu aç'],
  [/^(.+) · site comments$/, '$1 · site yorumları'],
  [/^(\d+) products? in progress$/, '$1 ürün işleniyor'],
  [/^(\d+) products? (?:is|are) moving$/, '$1 ürün ilerliyor'],
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
    '$1 · Mercury ve DeepSeek anahtarları bu telefonda açık.',
  ],
  [
    /^The owner’s Mercury and DeepSeek keys, opened on this phone\.$/,
    'Sahibinin Mercury ve DeepSeek anahtarları bu telefonda açık.',
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
 * Whether `text` would render in Turkish. Used by the coverage test: a new
 * screen string must not reach the phone in English because nobody remembered
 * the dictionary.
 */
export function hasTranslation(text: string, lang: Language = 'tr'): boolean {
  if (!text || lang !== 'tr') return true;
  const collapsed = text.replace(/\s+/g, ' ').trim();
  if (!collapsed) return true;
  if (lookup(collapsed) !== undefined) return true;
  return patterns.some(([pattern]) => pattern.test(collapsed));
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
