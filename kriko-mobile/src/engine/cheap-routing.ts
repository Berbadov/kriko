/** Deliberately narrow routing for answers that need no current facts. */
export type CheapRoute = 'ministral-3b-2512' | 'ministral-8b-2512';

const EXCLUDED = /\b(?:today|current(?:ly)?|latest|recent|news|price|cost|available|availability|release|version|update|202[4-9]|203\d|buy|buying|best|recommend(?:ation)?|compare|versus|vs\.?|review|reviews|seller|merchant|product|model number|compatib(?:le|ility)|recall|safety|dose|dosage|symptom|diagnos(?:e|is)|treat(?:ment)?|medicine|medical|doctor|lawyer|legal|lawsuit|law|tax|invest(?:ment|ing)|stock|crypto|financial|finance|interest rate|mortgage|insurance|warranty|company|president|ceo|exchange rate|currency|bleeding|aspirin|headache|migraine|kanama|ilaç|doz|tedavi|baş ağrısı|hukuk|dava|vergi|yatırım|kur)\b/i;
const URL = /(?:https?:\/\/|\bwww\.)|\b[\w-]+\.(?:com|org|net|io|ai|gov|edu)\b/i;
const PERSONAL = /\b(?:my|mine|me|i am|i'm|we|our|you|your|this (?:page|site|screen|image|photo|screenshot|document|file)|attached|uploaded|above|below|in the picture|in the screenshot)\b/i;
const STATIC_TOPICS = /\b(?:photosynthesis|fotosentez|gravity|yerçekimi|evaporation|buharlaşma|condensation|yoğunlaşma|fractions?|kesir|metaphor|metafor|simile|benzetme|grammar|dil bilgisi|prime number|asal sayı|multiplication|çarpma|division|bölme|addition|toplama|subtraction|çıkarma|solar system|güneş sistemi|water cycle|su döngüsü|noun|isim|verb|fiil|adjective|sıfat|adverb|zarf|punctuation|noktalama|alliteration|hyperbole|abartma|ecosystem|ekosistem|food chain|besin zinciri|molecule|molekül|atom|cell|hücre|evolution|evrim|natural selection|magnetism|manyetizma|electricity|elektrik|geometry|geometri|algebra|cebir|perimeter|area|alan|volume|hacim|democracy|demokrasi|federalism|plate tectonics|levha tektoniği|osmosis|osmoz|newton's laws|mitosis|mitoz|refraction|kırılma|convection|conduction|taşınım|iletim)\b/i;

export function classifyCheapQuestion(question: string, language: 'en' | 'tr' = 'en'): CheapRoute | null {
  const q = question.replace(/\s+/g, ' ').trim();
  if (!q || URL.test(q) || PERSONAL.test(q) || EXCLUDED.test(q)) return null;
  const translation = /^(?:translate|how do you say|çevir|çevirisi nedir)\b/i.test(q);
  const rewrite = /^(?:rewrite|rephrase|paraphrase|proofread|correct the grammar of|yeniden yaz|başka türlü ifade et|dilbilgisini düzelt)\b/i.test(q);
  if (translation) return q.length <= 2000 ? 'ministral-8b-2512' : null;
  if (rewrite) {
    if (q.length > 2000) return null;
    const turkishRewrite = language === 'tr' || /[çğıöşüİı]/i.test(q) || /\b(?:to|into) turkish\b|\btürkçe(?:ye|ye)?\b/i.test(q);
    return turkishRewrite ? 'ministral-8b-2512' : 'ministral-3b-2512';
  }

  const define = /^(?:define|what does .{1,100} mean\??|what is the meaning of|tanımla|.{1,100} ne demek\??|.{1,100} nedir\??)\b/i.test(q);
  const explain = /^(?:explain|what is|what are|how does|how do|why does|why do|açıkla|nasıl çalışır|nedir)\b/i.test(q);
  if (q.length <= 280 && (define || explain) && STATIC_TOPICS.test(q)) return define ? 'ministral-3b-2512' : 'ministral-8b-2512';
  return null;
}

export function isTransformRequest(question: string): boolean {
  return /^(?:translate|how do you say|çevir|çevirisi nedir|rewrite|rephrase|paraphrase|proofread|correct the grammar of|yeniden yaz|başka türlü ifade et|dilbilgisini düzelt)\b/i.test(question.trim());
}
