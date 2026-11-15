import test from "node:test";
import assert from "node:assert/strict";

globalThis.location = { search: "" };
const { fromFields, fromValue } = await import("../public/js/data.js");

test("conversão do formato tipado do Firestore", () => {
  const doc = {
    name: { stringValue: "Flamengo" },
    n: { integerValue: "12" },
    sd: { doubleValue: 7.5 },
    ok: { booleanValue: true },
    nada: { nullValue: null },
    at: { timestampValue: "2026-11-15T10:00:00Z" },
    games: { arrayValue: { values: [{ mapValue: { fields: { pts: { arrayValue: { values: [{ integerValue: "20" }, { integerValue: "22" }] } } } } }] } },
    vazio: { arrayValue: {} },
    mapa: { mapValue: {} },
  };
  assert.deepEqual(fromFields(doc), {
    name: "Flamengo", n: 12, sd: 7.5, ok: true, nada: null, at: "2026-11-15T10:00:00Z",
    games: [{ pts: [20, 22] }], vazio: [], mapa: {},
  });
  assert.equal(fromValue(null), null);
});
