//! Contrast arithmetic for text laid over an image, shared by the build
//! script (which measures the sky images) and the app (which tests it).
//!
//! WCAG 2 relative luminance and contrast ratio. Pure functions over sRGB
//! hex colours and luminances, so the same numbers decide at build time and
//! are checked in `cargo test`.

/// One sRGB channel to linear light.
pub fn channel(c: u8) -> f32 {
    let c = c as f32 / 255.0;
    if c <= 0.040_45 {
        c / 12.92
    } else {
        ((c + 0.055) / 1.055).powf(2.4)
    }
}

/// Relative luminance of `0xRRGGBB`.
pub fn luminance(rgb: u32) -> f32 {
    let r = channel((rgb >> 16) as u8);
    let g = channel((rgb >> 8) as u8);
    let b = channel(rgb as u8);
    0.2126 * r + 0.7152 * g + 0.0722 * b
}

/// Contrast ratio between two luminances, 1.0 to 21.0.
pub fn ratio(a: f32, b: f32) -> f32 {
    let (hi, lo) = if a > b { (a, b) } else { (b, a) };
    (hi + 0.05) / (lo + 0.05)
}

/// How the words go on one background: which ink, which shade behind it and
/// how dense, the contrast that buys, and whether the accent still reads.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Plan {
    pub ink: u32,
    pub shade: u32,
    pub shade_alpha: f32,
    pub contrast: f32,
    pub accent_reads: bool,
}

/// The ink with the better contrast against `bg` (the background's
/// luminance, taken at its brightest likely point), then the least shade of
/// the other colour that lifts it to `target`. A background that already
/// clears the target gets no shade at all; the shade never passes `cap`, so
/// the image always shows through.
pub fn plan(bg: f32, light: u32, dark: u32, accent: u32, target: f32, cap: f32) -> Plan {
    let (ink, shade) = if ratio(luminance(light), bg) >= ratio(luminance(dark), bg) {
        (light, dark)
    } else {
        (dark, light)
    };
    let (ink_l, shade_l) = (luminance(ink), luminance(shade));
    let behind = |a: f32| (1.0 - a) * bg + a * shade_l;
    let mut alpha = 0.0;
    while ratio(ink_l, behind(alpha)) < target && alpha < cap {
        alpha = (alpha + 0.01).min(cap);
    }
    let under = behind(alpha);
    Plan {
        ink,
        shade,
        shade_alpha: alpha,
        contrast: ratio(ink_l, under),
        accent_reads: ratio(luminance(accent), under) >= 4.5,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const LIGHT: u32 = 0xf2f5ff;
    const DARK: u32 = 0x05070f;
    const ACCENT: u32 = 0x86a3ff;

    #[test]
    fn white_and_black_are_twenty_one_to_one() {
        assert!((ratio(luminance(0xffffff), luminance(0x000000)) - 21.0).abs() < 0.01);
    }

    #[test]
    fn a_dark_sky_gets_light_words_and_a_bright_one_dark_words() {
        // the reader: "if background on the black text becomes white"
        assert_eq!(plan(0.02, LIGHT, DARK, ACCENT, 7.0, 0.9).ink, LIGHT);
        assert_eq!(plan(0.85, LIGHT, DARK, ACCENT, 7.0, 0.9).ink, DARK);
    }

    #[test]
    fn the_shade_is_only_as_dense_as_the_target_needs() {
        let clear = plan(0.0, LIGHT, DARK, ACCENT, 7.0, 0.9);
        assert_eq!(clear.shade_alpha, 0.0);
        // the shipped skies' brightest likely speck: light words, some shade
        let sky = plan(0.131, LIGHT, DARK, ACCENT, 7.0, 0.9);
        assert_eq!(sky.ink, LIGHT);
        assert!(sky.shade_alpha > 0.0 && sky.shade_alpha < 0.9);
        assert!(sky.contrast >= 7.0);
        // brighter still: dark words clear the target with no shade at all
        let bright = plan(0.38, LIGHT, DARK, ACCENT, 7.0, 0.9);
        assert_eq!((bright.ink, bright.shade_alpha), (DARK, 0.0));
    }

    #[test]
    fn a_mid_grey_still_reaches_the_target_from_either_side() {
        for bg in [0.18, 0.2, 0.25, 0.3] {
            assert!(plan(bg, LIGHT, DARK, ACCENT, 7.0, 0.9).contrast >= 7.0, "{bg}");
        }
    }
}
