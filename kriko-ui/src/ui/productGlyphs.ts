/** The closed vocabulary from a product's name to one sprite in the pixel
 *  library. Presentation only: no sprite for a name means no glyph, and this
 *  decides nothing about the product. */
export const GLYPHS: [RegExp, string][] = [
  [/e-?bike|bisiklet|\bbike\b/, 'ebike'],
  [/hoverboard/, 'hoverboard'],
  [/scooter|scoot/i, 'scooter'],
  [/robot ?vac|robot süpürge/, 'robotvac'],
  [/vacuum|süpürge|supurge/, 'vacuum'],
  [/dishwash|bulaşık|bulasik/, 'dishwasher'],
  [/wash(er|ing)|çamaşır|camasir/, 'washer'],
  [/dryer|kurutma/, 'dryer'],
  [/fridge|refriger|buzdolab/, 'fridge'],
  [/freezer|dondurucu/, 'fridge'],
  [/microwave|mikrodalga/, 'microwave'],
  [/oven|fırın|firin/, 'oven'],
  [/air ?fryer|fritöz|fritoz/, 'airfryer'],
  [/pressure ?cooker|düdüklü|duduklu/, 'pressurecooker'],
  [/espresso|coffee|kahve/, 'espresso'],
  [/kettle|su ısıtıcı|su isitici/, 'kettle'],
  [/toaster|tost/, 'toaster'],
  [/blender|blendır|blendir/, 'blender'],
  [/air ?purif|hava temizle/, 'airpurifier'],
  [/air ?con|klima/, 'aircon'],
  [/heater|ısıtıcı|isitici|radiator|radyatör|radiator/, 'heater'],
  [/boiler|kombi|şofben|sofben/, 'boiler'],
  [/fan\b|vantilatör|vantilator/, 'fan'],
  [/headphone|kulaklık|kulaklik/, 'headphones'],
  [/earbud|kulak içi/, 'earbuds'],
  [/phone|telefon|smartphone/, 'phone'],
  [/tablet/, 'tablet'],
  [/laptop|notebook|dizüstü|dizustu/, 'laptop'],
  [/monitor|ekran/, 'monitor'],
  [/\btv\b|television|televizyon/, 'tv'],
  [/console|playstation|xbox|nintendo/, 'gameconsole'],
  [/gpu|graphics card|ekran kart/, 'gpu'],
  [/power ?bank|taşınabilir şarj/, 'powerbank'],
  [/power ?strip|priz/, 'powerstrip'],
  [/car seat|oto koltu|çocuk koltu|cocuk koltuk/, 'carseat'],
  [/drone/, 'drone'],
  [/3d ?print/, '3dprinter'],
  [/\bdrill\b|matkap|darbeli/, 'drill'],
  [/watch|saat/, 'watch'],
  [/car\b|araba|otomobil|araç|arac/, 'car'],
]

export function glyphFor(name: string): string | null {
  const text = String(name || '').toLowerCase()
  for (const [pattern, sprite] of GLYPHS) {
    if (pattern.test(text)) return `px-${sprite}`
  }
  return null
}

/** The product's sprite, leading a row or a column.
 *
 *  Decorative: the name beside it already says what it is, so the picture is
 *  hidden from assistive tech. No symbol for a name means no space is spent.
 */
