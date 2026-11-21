/** @jsxRuntime automatic */
/** @jsxImportSource react */
import "./render";
import assert from "node:assert/strict";
import { test } from "node:test";
import { render } from "./render";

const pages: [string, string][] = [
  ["/", "../src/app/page"],
  ["/services", "../src/app/services/page"],
  ["/process", "../src/app/process/page"],
  ["/usecases", "../src/app/usecases/page"],
  ["/contact", "../src/app/contact/page"],
  ["/support", "../src/app/support/page"],
  ["/privacy", "../src/app/privacy/page"],
  ["/terms", "../src/app/terms/page"],
  ["/cookies", "../src/app/cookies/page"],
  ["/insights", "../src/app/insights/page"],
  ["/articles", "../src/app/articles/page"],
  ["/hero", "../src/app/hero/page"],
  ["/cta", "../src/app/cta/page"],
];

const previews = new Set(["/hero", "/cta", "/articles"]);

for (const [path, module] of pages) {
  test(`${path} renders from the local CMS content`, async () => {
    const { default: Page } = await import(module);
    const html = await render(<Page />, path);
    assert.ok(html.length > 200, `${path} rendered ${html.length} characters`);
    // Content pages carry structured data for search engines; the section previews
    // (/hero, /cta, /articles) show one block each and do not.
    if (!previews.has(path))
      assert.match(html, /<script type="application\/ld\+json">/, path);
    assert.doesNotMatch(html, /undefined|\[object Object\]/, path);
  });
}
