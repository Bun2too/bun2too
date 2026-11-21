import assert from "node:assert/strict";
import { test } from "node:test";
import { act, createElement } from "react";
import Newsletter from "../src/components/Newsletter";
import {
  componentDom,
  button,
  click,
  deferred,
  flush,
  input,
  json,
  publicEnv,
  submit,
} from "./helpers/component-dom";

test("newsletter sends only the selected topics and explicit consent, then describes pending verification", async (t) => {
  const dom = componentDom(t);
  publicEnv(t, { NEXT_PUBLIC_TURNSTILE_SITE_KEY: undefined });
  const requests: RequestInit[] = [];
  const response = deferred<Response>();
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/subscriptions");
    requests.push(options);
    return response.promise;
  });
  const { container } = await dom.mount(
    createElement(Newsletter, { insights: true }),
  );
  const consent =
    container.querySelector<HTMLInputElement>('[name="consent"]')!;
  assert.equal(consent.checked, false);
  assert.deepEqual(
    [
      ...container.querySelectorAll<HTMLInputElement>(
        '[name="topics"]:checked',
      ),
    ].map((x) => x.value),
    ["ai-automation"],
  );
  await input(container, '[name="email"]', "reader@example.com");
  await click(consent);
  await click(
    container.querySelector<HTMLInputElement>(
      '[name="topics"][value="fintech"]',
    )!,
  );
  await submit(container.querySelector("form")!);
  assert.equal(button(container, /Saving/).disabled, true);
  assert.equal(
    container.querySelector<HTMLInputElement>('[name="email"]')!.disabled,
    true,
  );
  assert.deepEqual(JSON.parse(requests[0].body as string), {
    email: "reader@example.com",
    consent: true,
    topics: ["ai-automation", "fintech"],
    website: "",
    captchaToken: "",
  });
  assert.equal(requests[0].method, "POST");
  await act(async () => response.resolve(json({ accepted: true })));
  assert.match(
    container.querySelector('[role="status"]')!.textContent!,
    /verify your address/,
  );
  assert.equal(
    container.querySelector('[role="status"] a')!.getAttribute("href"),
    "/account",
  );
  assert.equal(container.querySelector('[role="alert"]'), null);
});

test("newsletter preserves the form on provider, malformed JSON and network failures", async (t) => {
  const dom = componentDom(t);
  publicEnv(t, { NEXT_PUBLIC_TURNSTILE_SITE_KEY: undefined });
  let attempt = 0;
  t.mock.method(globalThis, "fetch", async () => {
    attempt++;
    if (attempt === 1) return json({ error: "Try again later" }, 503);
    if (attempt === 2) return json({}, 503);
    if (attempt === 3) return new Response("gateway error", { status: 502 });
    throw new Error("Offline fixture");
  });
  const { container } = await dom.mount(createElement(Newsletter));
  await input(container, '[name="email"]', "retry@example.com");
  const form = container.querySelector("form")!;
  for (let index = 0; index < 4; index++) {
    await submit(form);
    assert.ok(container.querySelector('[role="alert"]'));
    assert.equal(button(container, /^Subscribe/).disabled, false);
    assert.equal(
      container.querySelector<HTMLInputElement>('[name="email"]')!.value,
      "retry@example.com",
    );
    assert.equal(container.querySelector('[role="status"]'), null);
  }
  assert.equal(attempt, 4);
});

test("newsletter CAPTCHA gates submit, expires tokens, resets after a request and removes its widget", async (t) => {
  const dom = componentDom(t);
  publicEnv(t, { NEXT_PUBLIC_TURNSTILE_SITE_KEY: "fixture-site-key" });
  let options: Record<string, Function>;
  const reset = t.mock.fn();
  const remove = t.mock.fn();
  dom.window.turnstile = {
    render: t.mock.fn((_element, value) => {
      options = value;
      return "newsletter-widget";
    }),
    reset,
    remove,
  };
  let sent: Record<string, unknown>;
  t.mock.method(globalThis, "fetch", async (_url, init) => {
    sent = JSON.parse(init.body as string);
    return json({ accepted: true });
  });
  const mounted = await dom.mount(createElement(Newsletter));
  assert.equal(button(mounted.container, /^Subscribe/).disabled, true);
  await act(async () => options.callback("fixture-captcha"));
  assert.equal(button(mounted.container, /^Subscribe/).disabled, false);
  await act(async () => options["expired-callback"]());
  assert.equal(button(mounted.container, /^Subscribe/).disabled, true);
  await act(async () => options["error-callback"]());
  assert.ok(mounted.container.querySelector('[role="alert"]'));
  await act(async () => options.callback("fresh-captcha"));
  await submit(mounted.container.querySelector("form")!);
  assert.equal(sent!.captchaToken, "fresh-captcha");
  assert.deepEqual(reset.mock.calls[0].arguments, ["newsletter-widget"]);
  await mounted.unmount();
  assert.deepEqual(remove.mock.calls[0].arguments, ["newsletter-widget"]);
  await flush();
});
