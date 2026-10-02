//! Embed the Kriko icon and the Windows resource manifest into the exe, so
//! the taskbar and the installer carry the brand mark.

fn main() {
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        let mut res = winresource::WindowsResource::new();
        res.set_icon("assets/kriko.ico");
        res.set("FileDescription", "Kriko — local product knowledge");
        res.set("ProductName", "Kriko");
        res.set("LegalCopyright", "");
        res.compile().expect("windows resource");
    }
}
