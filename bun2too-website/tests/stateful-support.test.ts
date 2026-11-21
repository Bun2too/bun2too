import assert from "node:assert/strict";
import { test } from "node:test";
import { act, createElement } from "react";
import SupportPanel from "../src/components/support/SupportPanel";
import SupportChat from "../src/components/support/SupportChat";
import SupportCaptcha from "../src/components/support/SupportCaptcha";
import SupportOpenButton from "../src/components/support/SupportOpenButton";
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

test("support only checks availability when opened and aborts a closed session request", async (t) => {
  const dom = componentDom(t);
  publicEnv(t, { NEXT_PUBLIC_TURNSTILE_SITE_KEY: undefined });
  const pending = deferred<Response>();
  const calls: { url: string; options: RequestInit }[] = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, options });
    return calls.length === 1
      ? pending.promise
      : json({ inquiries: false, chat: true });
  });
  const close = t.mock.fn();
  const mounted = await dom.mount(
    createElement(SupportPanel, { open: false, onClose: close }),
  );
  assert.equal(calls.length, 0);
  await mounted.render(
    createElement(SupportPanel, { open: true, onClose: close }),
  );
  assert.equal(mounted.container.querySelector("dialog")!.open, true);
  assert.equal(
    button(mounted.container, /Send private inquiry/).disabled,
    true,
  );
  await submit(mounted.container.querySelector("form")!);
  assert.equal(calls.length, 1, "an unavailable form must not submit");
  await mounted.render(
    createElement(SupportPanel, { open: false, onClose: close }),
  );
  assert.equal(calls[0].options.signal!.aborted, true);
  await act(async () =>
    pending.resolve(json({ inquiries: true, chat: false })),
  );
  await mounted.render(
    createElement(SupportPanel, { open: true, onClose: close }),
  );
  assert.equal(calls.length, 2);
  assert.ok(
    mounted.container.querySelector(".support-chat"),
    "chat availability is independent from inquiries",
  );
  await click(mounted.container.querySelector('[aria-label="Close support"]')!);
  await act(async () => {
    const cancel = new Event("cancel", { cancelable: true });
    mounted.container.querySelector("dialog")!.dispatchEvent(cancel);
    assert.equal(cancel.defaultPrevented, true);
  });
  assert.equal(close.mock.callCount(), 2);
  assert.ok(calls.every((call) => call.url === "/api/support/session"));
});

test("manual availability retry reports its result and preserves the inquiry draft", async (t) => {
  const dom = componentDom(t);
  publicEnv(t, { NEXT_PUBLIC_TURNSTILE_SITE_KEY: undefined });
  let checks = 0;
  t.mock.method(globalThis, "fetch", async (url) => {
    assert.equal(url, "/api/support/session");
    checks++;
    return json({ inquiries: checks === 3, chat: false });
  });
  const { container } = await dom.mount(
    createElement(SupportPanel, { open: true, onClose() {} }),
  );
  await input(
    container,
    '[name="message"]',
    "Keep this unsent project description.",
  );
  await click(button(container, /Check availability again/));
  assert.match(
    container.querySelector('[role="status"]')!.textContent!,
    /still unavailable/,
  );
  await click(button(container, /Check availability again/));
  assert.match(
    container.querySelector('[role="status"]')!.textContent!,
    /form is ready/,
  );
  assert.equal(
    container.querySelector<HTMLTextAreaElement>('[name="message"]')!.value,
    "Keep this unsent project description.",
  );
  assert.equal(button(container, /Send private inquiry/).disabled, false);
  assert.equal(checks, 3);
});

test("session HTTP, schema and network failures keep support unavailable with an explicit recovery path", async (t) => {
  const dom = componentDom(t);
  publicEnv(t, { NEXT_PUBLIC_TURNSTILE_SITE_KEY: undefined });
  const fixtures = [
    () => json({}, 503),
    () => json({ inquiries: "true", chat: false }),
    () => {
      throw new TypeError("network fixture");
    },
  ];
  for (const fixture of fixtures) {
    const request = t.mock.method(globalThis, "fetch", async () => fixture());
    const mounted = await dom.mount(
      createElement(SupportPanel, { open: true, onClose() {} }),
    );
    assert.match(
      mounted.container.querySelector('[role="alert"]')!.textContent!,
      /couldn’t check support availability/,
    );
    assert.equal(
      button(mounted.container, /Send private inquiry/).disabled,
      true,
    );
    assert.ok(button(mounted.container, /Check availability again/));
    await mounted.unmount();
    request.mock.restore();
  }
});

test("inquiry retry keeps its request ID and a busy form cannot duplicate its POST", async (t) => {
  const dom = componentDom(t);
  publicEnv(t, { NEXT_PUBLIC_TURNSTILE_SITE_KEY: undefined });
  const pending = deferred<Response>();
  const payloads: Record<string, unknown>[] = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    if (url === "/api/support/session")
      return json({ inquiries: true, chat: false });
    assert.equal(url, "/api/support/inquiries");
    assert.equal(options.method, "POST");
    payloads.push(JSON.parse(options.body));
    return payloads.length === 1
      ? pending.promise
      : json(
          {
            reference: "B2T-FIXTURE",
            notification: "accepted",
            acknowledgment: "accepted",
          },
          201,
        );
  });
  const { container } = await dom.mount(
    createElement(SupportPanel, { open: true, onClose() {} }),
  );
  await input(container, '[name="name"]', "Fixture Requester");
  await input(container, '[name="email"]', "requester@example.com");
  await input(
    container,
    '[name="message"]',
    "Please help integrate a customer service workflow.",
  );
  await input(container, '[name="topic"]', "application");
  await click(container.querySelector('[name="consent"]')!);
  const form = container.querySelector("form")!;
  await submit(form);
  await submit(form);
  assert.equal(payloads.length, 1);
  assert.equal(button(container, /Saving your inquiry/).disabled, true);
  await act(async () =>
    pending.resolve(json({ error: "Please retry this saved request." }, 503)),
  );
  assert.match(
    container.querySelector('[role="alert"]')!.textContent!,
    /Please retry/,
  );
  await submit(form);
  assert.equal(payloads.length, 2);
  assert.equal(payloads[0].requestId, payloads[1].requestId);
  assert.match(payloads[0].requestId as string, /^[a-f\d-]{36}$/);
  assert.deepEqual(
    { ...payloads[0], requestId: "id" },
    {
      name: "Fixture Requester",
      email: "requester@example.com",
      topic: "application",
      message: "Please help integrate a customer service workflow.",
      consent: true,
      website: "",
      requestId: "id",
      captchaToken: "",
    },
  );
  assert.match(
    container.querySelector(".support-confirmation")!.textContent!,
    /B2T-FIXTURE/,
  );
  assert.match(
    container.querySelector(".support-confirmation")!.textContent!,
    /not been subscribed/,
  );
  assert.equal(container.querySelector('[role="alert"]'), null);
  assert.equal(container.querySelector("form"), null);
});

test("saved inquiry warnings distinguish management notification from requester acknowledgment", async (t) => {
  const dom = componentDom(t);
  publicEnv(t, { NEXT_PUBLIC_TURNSTILE_SITE_KEY: undefined });
  for (const [notification, acknowledgment, warningCount] of [
    ["unconfirmed", "unconfirmed", 2],
    ["accepted", "unconfirmed", 1],
    ["unconfirmed", "accepted", 1],
  ] as const) {
    const request = t.mock.method(globalThis, "fetch", async (url) =>
      url === "/api/support/session"
        ? json({ inquiries: true, chat: false })
        : json({ reference: "B2T-SAVED", notification, acknowledgment }, 202),
    );
    const mounted = await dom.mount(
      createElement(SupportPanel, { open: true, onClose() {} }),
    );
    await submit(mounted.container.querySelector("form")!);
    assert.equal(
      mounted.container.querySelectorAll('[role="alert"]').length,
      warningCount,
    );
    assert.match(
      mounted.container.querySelector(".support-confirmation")!.textContent!,
      /B2T-SAVED/,
    );
    assert.equal(
      mounted.container.querySelectorAll("a[href^='mailto:']").length,
      0,
    );
    await mounted.unmount();
    request.mock.restore();
  }
});

test("inquiry malformed responses and network failures never produce a saved receipt", async (t) => {
  const dom = componentDom(t);
  publicEnv(t, { NEXT_PUBLIC_TURNSTILE_SITE_KEY: undefined });
  for (const fixture of [
    () => json({ reference: "B2T-INVALID", notification: "sending" }),
    () => new Response("gateway", { status: 504 }),
    () => {
      throw "offline fixture";
    },
  ]) {
    const request = t.mock.method(globalThis, "fetch", async (url) =>
      url === "/api/support/session"
        ? json({ inquiries: true, chat: false })
        : fixture(),
    );
    const mounted = await dom.mount(
      createElement(SupportPanel, { open: true, onClose() {} }),
    );
    await submit(mounted.container.querySelector("form")!);
    assert.ok(mounted.container.querySelector('[role="alert"]'));
    assert.equal(
      mounted.container.querySelector(".support-confirmation"),
      null,
    );
    assert.equal(
      button(mounted.container, /Send private inquiry/).disabled,
      false,
    );
    await mounted.unmount();
    request.mock.restore();
  }
});

test("AI questions require separate opt-in, suppress duplicate sends and render answers as plain text", async (t) => {
  const dom = componentDom(t);
  publicEnv(t, { NEXT_PUBLIC_TURNSTILE_SITE_KEY: undefined });
  const pending = deferred<Response>();
  const calls: RequestInit[] = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/support/chat");
    calls.push(options);
    return pending.promise;
  });
  const { container } = await dom.mount(
    createElement(SupportChat, { available: true }),
  );
  assert.equal(calls.length, 0);
  await input(container, "textarea", "Which AI services do you offer?");
  await submit(container.querySelector("form")!);
  assert.equal(calls.length, 0);
  await click(container.querySelector("input[type=checkbox]")!);
  assert.equal(calls.length, 0);
  await submit(container.querySelector("form")!);
  await submit(container.querySelector("form")!);
  assert.equal(calls.length, 1);
  assert.deepEqual(JSON.parse(calls[0].body as string), {
    question: "Which AI services do you offer?",
    consent: true,
    captchaToken: "",
  });
  assert.equal(container.querySelector("textarea")!.disabled, true);
  await act(async () =>
    pending.resolve(
      json({
        answer:
          '<script>alert("unsafe")</script> Public AI engineering services.',
      }),
    ),
  );
  assert.match(
    container.querySelector(".support-answer")!.textContent!,
    /<script>/,
  );
  assert.equal(container.querySelector(".support-answer script"), null);
  assert.equal(
    container.querySelector("textarea")!.value,
    "Which AI services do you offer?",
  );
  assert.equal(button(container, /^Ask AI/).disabled, false);
});

test("AI provider errors, gateway HTML and transport failures preserve the question without automatic replay", async (t) => {
  const dom = componentDom(t);
  publicEnv(t, { NEXT_PUBLIC_TURNSTILE_SITE_KEY: undefined });
  for (const fixture of [
    () => json({ error: "Public answer unavailable" }, 503),
    () => json({}),
    () => new Response("gateway HTML", { status: 504 }),
    () => {
      throw new TypeError("private provider details");
    },
    () => {
      throw new DOMException("private timeout details", "TimeoutError");
    },
  ]) {
    const request = t.mock.method(globalThis, "fetch", async () => fixture());
    const mounted = await dom.mount(
      createElement(SupportChat, { available: true }),
    );
    await input(
      mounted.container,
      "textarea",
      "Keep this question for a manual retry.",
    );
    await click(mounted.container.querySelector("input[type=checkbox]")!);
    await submit(mounted.container.querySelector("form")!);
    const alert =
      mounted.container.querySelector('[role="alert"]')!.textContent!;
    assert.doesNotMatch(
      alert,
      /private (?:provider|timeout) details|gateway HTML/,
    );
    assert.equal(request.mock.callCount(), 1);
    assert.equal(
      mounted.container.querySelector("textarea")!.value,
      "Keep this question for a manual retry.",
    );
    assert.equal(mounted.container.querySelector(".support-answer"), null);
    await mounted.unmount();
    request.mock.restore();
  }
});

test("AI checking and unavailable states cannot send questions", async (t) => {
  const dom = componentDom(t);
  const mounted = await dom.mount(
    createElement(SupportChat, { available: true, checking: true }),
  );
  assert.equal(mounted.container.textContent, "");
  await mounted.render(createElement(SupportChat, { available: false }));
  assert.equal(mounted.container.querySelector("form"), null);
  assert.equal(
    mounted.container.querySelector("a")!.getAttribute("href"),
    "/support",
  );
});

test("support CAPTCHA handles expiry/error/reset and removes the widget on unmount", async (t) => {
  const dom = componentDom(t);
  publicEnv(t, { NEXT_PUBLIC_TURNSTILE_SITE_KEY: "fixture-support-key" });
  let options: Record<string, Function>;
  const onToken = t.mock.fn();
  dom.window.turnstile = {
    render: t.mock.fn((_element, value) => {
      options = value;
      return "support-widget";
    }),
    reset: t.mock.fn(),
    remove: t.mock.fn(),
  };
  const mounted = await dom.mount(
    createElement(SupportCaptcha, { action: "support-chat", onToken }),
  );
  assert.equal(
    dom.window.turnstile.render.mock.calls[0].arguments[1].action,
    "support-chat",
  );
  await act(async () => options["error-callback"]());
  assert.ok(mounted.container.querySelector('[role="alert"]'));
  await act(async () => options.callback("fixture-token"));
  assert.equal(mounted.container.querySelector('[role="alert"]'), null);
  assert.equal(onToken.mock.calls.at(-1)!.arguments[0], "fixture-token");
  await act(async () => options["expired-callback"]());
  assert.equal(onToken.mock.calls.at(-1)!.arguments[0], "");
  await mounted.render(
    createElement(SupportCaptcha, {
      action: "support-chat",
      onToken,
      resetKey: 1,
    }),
  );
  assert.deepEqual(dom.window.turnstile.reset.mock.calls[0].arguments, [
    "support-widget",
  ]);
  await mounted.unmount();
  assert.deepEqual(dom.window.turnstile.remove.mock.calls[0].arguments, [
    "support-widget",
  ]);
});

test("support launcher stays absent on signup embeds and open buttons send only an intent event", async (t) => {
  const dom = componentDom(t, "https://website.example.com/insights/signup");
  const { default: SupportLauncher } =
    await import("../src/components/support/SupportLauncher");
  const launcher = await dom.mount(createElement(SupportLauncher));
  assert.equal(launcher.container.textContent, "");
  await launcher.unmount();
  const listener = t.mock.fn();
  dom.window.addEventListener("bun2too:open-support", listener);
  const mounted = await dom.mount(
    createElement(
      SupportOpenButton,
      { className: "fixture-contact" },
      "Send a private inquiry",
    ),
  );
  const opener = button(mounted.container, /Send a private inquiry/);
  assert.equal(opener.getAttribute("aria-controls"), "bun2too-support");
  assert.equal(opener.className, "fixture-contact");
  await click(opener);
  assert.equal(listener.mock.callCount(), 1);
  const defaultButton = await dom.mount(createElement(SupportOpenButton));
  assert.ok(button(defaultButton.container, /Contact Bun2Too/));
});

test("launcher loads the panel on a click or intent event and its close control updates the launcher", async (t) => {
  const dom = componentDom(t);
  const { default: SupportLauncher } =
    await import("../src/components/support/SupportLauncher");
  publicEnv(t, { NEXT_PUBLIC_TURNSTILE_SITE_KEY: undefined });
  const request = t.mock.method(globalThis, "fetch", async (url) => {
    assert.equal(url, "/api/support/session");
    return json({ inquiries: false, chat: false });
  });
  const mounted = await dom.mount(createElement(SupportLauncher));
  assert.equal(request.mock.callCount(), 0);
  assert.equal(mounted.container.querySelector("dialog"), null);
  await click(button(mounted.container, /Contact Bun2Too/));
  for (
    let attempt = 0;
    attempt < 20 && !mounted.container.querySelector("dialog");
    attempt++
  )
    await flush();
  assert.ok(mounted.container.querySelector("dialog"));
  assert.equal(
    button(mounted.container, /Contact Bun2Too/).getAttribute("aria-expanded"),
    "true",
  );
  await click(mounted.container.querySelector('[aria-label="Close support"]')!);
  assert.equal(
    button(mounted.container, /Contact Bun2Too/).getAttribute("aria-expanded"),
    "false",
  );
  await act(async () =>
    dom.window.dispatchEvent(new Event("bun2too:open-support")),
  );
  assert.equal(
    button(mounted.container, /Contact Bun2Too/).getAttribute("aria-expanded"),
    "true",
  );
  assert.equal(request.mock.callCount(), 2);
  await mounted.unmount();
  await act(async () =>
    dom.window.dispatchEvent(new Event("bun2too:open-support")),
  );
  assert.equal(
    request.mock.callCount(),
    2,
    "unmount removes the intent listener",
  );
});
