// Ishga tushirish: npm test   (Node 22.18+ — TypeScript turlarini o'zi olib tashlaydi)
import assert from "node:assert/strict";
import { test } from "node:test";
import { detectCommandLanguage, isLang, LANGS, MESSAGES, translate } from "../i18n.ts";

test("all three languages define exactly the same keys", () => {
  const keys = (l) => Object.keys(MESSAGES[l]).sort();
  assert.deepEqual(keys("ru"), keys("uz"));
  assert.deepEqual(keys("en"), keys("uz"));
});

test("no translation is empty and placeholders match across languages", () => {
  const ph = (s) => (s.match(/\{\w+\}/g) ?? []).sort().join(",");
  for (const key of Object.keys(MESSAGES.uz)) {
    for (const l of LANGS) {
      assert.ok(MESSAGES[l][key].trim().length > 0, `${l}.${key} bo'sh`);
      assert.equal(ph(MESSAGES[l][key]), ph(MESSAGES.uz[key]), `${l}.${key} placeholder`);
    }
  }
});

test("switching language changes the text", () => {
  assert.equal(translate("uz", "nav.settings"), "Sozlamalar");
  assert.equal(translate("ru", "nav.settings"), "Настройки");
  assert.equal(translate("en", "nav.settings"), "Settings");
  assert.equal(translate("en", "confirm.expiresIn", { s: 7 }), "Automatically declined in 7 s");
  assert.equal(translate("ru", "dash.tasksOf", { a: 1, b: 2 }), "1 / 2 задач");
});

test("isLang guards stored values", () => {
  assert.ok(isLang("ru"));
  assert.ok(!isLang("tr"));
  assert.ok(!isLang(null));
});

test("Russian Cyrillic is detected as ru", () => {
  assert.equal(detectCommandLanguage("Открой Notes", "uz"), "ru");
  assert.equal(detectCommandLanguage("Найди погоду в Ташкенте", "en"), "ru");
});

test("Uzbek Cyrillic is detected as uz, not ru", () => {
  assert.equal(detectCommandLanguage("Ҳисобот папкасини яратинг", "ru"), "uz");   // ҳ
  assert.equal(detectCommandLanguage("Сафари ни оч", "uz"), "uz");                // maxsus harfsiz
  assert.equal(detectCommandLanguage("Телеграмни оч", "uz"), "uz");
  assert.equal(detectCommandLanguage("Қидир: об-ҳаво", "en"), "uz");
});

test("Latin text keeps the selected language", () => {
  assert.equal(detectCommandLanguage("Safari ni och", "uz"), "uz");
  assert.equal(detectCommandLanguage("Open Calculator", "en"), "en");
  assert.equal(detectCommandLanguage("Open Calculator", "ru"), "ru");
});
