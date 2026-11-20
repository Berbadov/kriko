/* The offline catalog: a real `.kpack`, read in a browser-shaped sandbox.
 *
 * The fixture is a SQLite file built by the pack schema, not a JSON stand-in.
 * It carries a claim body longer than a page, so the overflow path is walked
 * rather than assumed. The matching tests use invented products and invented
 * claims: passing must not depend on which packs ship.
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.join(__dirname, "..");
const PACK = fs.readFileSync(path.join(__dirname, "fixtures", "sample.kpack"));

function load() {
  const context = vm.createContext({
    console,
    TextDecoder,
    DataView,
    Uint8Array,
    Array,
    Object,
    String,
    Number,
    Boolean,
    Math,
    JSON,
    Date,
    Promise,
    Error,
    Map,
    Set,
    crypto: globalThis.crypto,
  });
  for (const file of ["offline/sqlite.js", "offline/catalog.js"]) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, file), "utf8"), context, { filename: file });
  }
  return context;
}

const TABLES = ["packs", "subjects", "attributes", "relations", "claims", "claim_text", "sources", "evidence"];

test("a real pack file is read as SQLite, table by table", () => {
  const { KrikoSqlite } = load();
  const tables = KrikoSqlite.read(PACK, TABLES);
  assert.equal(tables.subjects.length, 2);
  assert.equal(tables.claims.length, 2);
  assert.equal(tables.subjects[0][3], "Northstar Kettle X200");
  assert.ok(tables.claim_text[1][4].length > 4096, "the long body did not cross an overflow page");
});

test("a file that is not SQLite is refused with a sentence", () => {
  const { KrikoSqlite } = load();
  assert.throws(() => KrikoSqlite.read(new Uint8Array(2048), TABLES), /not a SQLite file/);
  const text = new TextEncoder().encode("PK\u0003\u0004" + "x".repeat(2048));
  assert.throws(() => KrikoSqlite.read(text, TABLES), /not a SQLite file/);
});

test("a pack becomes the small catalog the lookup needs", () => {
  const { KrikoSqlite, KrikoOffline } = load();
  const catalog = KrikoOffline.buildCatalog(KrikoSqlite.read(PACK, TABLES), {
    pack_id: "org.example.kettles", version: "1.0.0", sha256: "abc",
  });
  assert.equal(catalog.pack_id, "org.example.kettles");
  assert.equal(catalog.version, "1.0.0");
  assert.equal(catalog.subjects.length, 2);
  assert.equal(catalog.claims.length, 2);
  const text = catalog.texts["c-2\u0000org.example.kettles"];
  assert.equal(text.title, "Lid seal wears");
  assert.equal(text.body.length, 1200, "a claim body is capped before storage");
  assert.equal(catalog.texts["c-1\u0000org.example.kettles"].title, "Element cuts out before boiling");
});

test("a page naming the product gets that product's claims, with sources", () => {
  const { KrikoSqlite, KrikoOffline } = load();
  const catalog = KrikoOffline.buildCatalog(KrikoSqlite.read(PACK, TABLES), { pack_id: "org.example.kettles" });
  const result = KrikoOffline.match([catalog], {
    url: "https://shop.example/p/kettle",
    title: "Northstar Kettle X200 | Shop",
    fields: { brand: "Northstar", model: "X200" },
  });
  assert.equal(result.readable, true);
  assert.equal(result.offline, true);
  assert.equal(result.coverage, "RISKS_FOUND");
  assert.equal(result.identity.model, "x200");
  assert.equal(result.claims.length, 2);
  assert.equal(result.claims[0].severity, "high", "the severe claim leads");
  assert.equal(result.claims[0].sources[0].domain, "repair.example");
  assert.equal(result.packs[0].pack_id, "org.example.kettles");
});

test("a subject the page only partly names is a probable match, not an exact one", () => {
  const { KrikoSqlite, KrikoOffline } = load();
  const catalog = KrikoOffline.buildCatalog(KrikoSqlite.read(PACK, TABLES), { pack_id: "org.example.kettles" });
  const result = KrikoOffline.match([catalog], { title: "Northstar kettle for sale", fields: { brand: "Northstar" } });
  assert.equal(result.readable, true);
  assert.equal(result.verdict, "probably");
});

test("a page nothing in the catalog names is unknown, never an empty answer", () => {
  const { KrikoSqlite, KrikoOffline } = load();
  const catalog = KrikoOffline.buildCatalog(KrikoSqlite.read(PACK, TABLES), { pack_id: "org.example.kettles" });
  const result = KrikoOffline.match([catalog], { title: "Garden hose 20 m", fields: { brand: "Other" } });
  assert.equal(result.readable, false);
  assert.equal(result.coverage, "UNKNOWN_PRODUCT");
  assert.deepEqual(JSON.parse(JSON.stringify(result.claims)), []);
});

test("no catalogs stored is no answer at all, so the engine's error is shown", async () => {
  const { KrikoOffline } = load();
  const api = { storage: { local: { get: async () => ({}) } } };
  assert.equal(await KrikoOffline.lookup(api, { title: "anything" }), null);
});

test("sha256 is the one the release index names", async () => {
  const { KrikoOffline } = load();
  const digest = await KrikoOffline.sha256Hex(new TextEncoder().encode("abc"));
  assert.equal(digest, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
});

test("the fold makes a Turkish title match an ASCII catalogue value", () => {
  const { KrikoOffline } = load();
  assert.equal(KrikoOffline.fold("Yıkama Makinesi"), "yikama makinesi");
  assert.equal(KrikoOffline.fold("MOTOR"), "motor");
});
