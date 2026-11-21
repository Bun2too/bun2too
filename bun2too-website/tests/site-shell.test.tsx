/** @jsxRuntime automatic */
/** @jsxImportSource react */
import "./render";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, test } from "node:test";
import { render } from "./render";

process.env.INSIGHTS_API_ORIGIN = "https://editorial.example.invalid";
const fixture = JSON.parse(
  readFileSync(new URL("./fixtures/insights.json", import.meta.url), "utf8"),
);
const article = fixture.articles[0];
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});
function serveInsights() {
  globalThis.fetch = (async (input: string | URL) => {
    const url = String(input);
    const match = url.match(/\/articles\/([^/?]+)$/);
    if (match) {
      const found = fixture.articles.find(
        (a: { id: string }) => a.id === match[1],
      );
      return found ? Response.json(found) : new Response("{}", { status: 404 });
    }
    return Response.json(fixture);
  }) as typeof fetch;
}
// notFound() throws an error whose digest names the HTTP status.
const isNotFound = (error: unknown) =>
  String((error as { digest?: string }).digest).startsWith(
    "NEXT_HTTP_ERROR_FALLBACK;404",
  );

test("the root layout wraps a page in the navigation, footer, consent and support shell", async () => {
  const { default: RootLayout, metadata } = await import("../src/app/layout");
  const html = await render(
    <RootLayout>
      <p id="page-body">Page body</p>
    </RootLayout>,
  );
  assert.match(html, /^<html lang="en">/);
  assert.match(html, /<p id="page-body">Page body<\/p>/);
  assert.match(html, /<nav/);
  assert.match(html, /<footer/);
  assert.match(html, /application\/ld\+json/);
  assert.equal(metadata.applicationName, "Bun2Too");
});

test("a CMS path renders through the catch-all route, and anything else is not found", async () => {
  const { default: Page, generateMetadata } =
    await import("../src/app/[...slug]/page");
  const html = await render(
    await Page({ params: Promise.resolve({ slug: ["services"] }) }),
  );
  assert.match(html, /<main id="main-content"/);
  const metadata = await generateMetadata({
    params: Promise.resolve({ slug: ["services"] }),
  });
  assert.ok(metadata.title);
  for (const slug of [["no-such-page"], ["..", "etc"]])
    await assert.rejects(
      Page({ params: Promise.resolve({ slug }) }),
      isNotFound,
    );
});

test("an insight article renders with its metadata, and a missing one is not found", async () => {
  serveInsights();
  const { default: Page, generateMetadata } =
    await import("../src/app/insights/[id]/page");
  const params = Promise.resolve({ id: article.id });
  const html = await render(await Page({ params }));
  assert.ok(html.includes(article.title), "the article title is on the page");
  const metadata = await generateMetadata({
    params: Promise.resolve({ id: article.id }),
  });
  assert.equal((metadata.openGraph as { type?: string }).type, "article");
  await assert.rejects(
    Page({ params: Promise.resolve({ id: "missing" }) }),
    isNotFound,
  );
});

test("the insights index and sign-up pages render", async () => {
  serveInsights();
  for (const module of [
    "../src/app/insights/page",
    "../src/app/insights/signup/page",
  ]) {
    const { default: Page } = await import(module);
    assert.ok((await render(<Page />)).length > 100, module);
  }
});

test("robots, sitemap and llms.txt describe the public site", async () => {
  const { default: robots } = await import("../src/app/robots");
  const rules = robots();
  assert.match(String(rules.sitemap), /\/sitemap\.xml$/);
  const { default: sitemap } = await import("../src/app/sitemap");
  const entries = await sitemap();
  assert.ok(entries.some((entry) => entry.url.endsWith("/services")));
  assert.ok(entries.every((entry) => !entry.url.includes("/api/")));
  const { GET } = await import("../src/app/llms.txt/route");
  const response = await GET();
  assert.equal(response.status, 200);
  assert.match(await response.text(), /Bun2Too/i);
});

test("the shared static components render from the local CMS content", async () => {
  const modules = [
    "Services",
    "Process",
    "UseCases",
    "BrandLogo",
    "Hero",
    "CTA",
    "Articles",
  ];
  for (const name of modules) {
    const { default: Component } = await import(`../src/components/${name}`);
    assert.ok((await render(<Component />)).length > 50, name);
  }
});
