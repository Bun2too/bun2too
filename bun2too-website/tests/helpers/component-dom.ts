import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { setImmediate } from "node:timers/promises";
import type { TestContext } from "node:test";
import { act, createElement, type ReactNode } from "react";
import { JSDOM, VirtualConsole } from "jsdom";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime.js";
import {
  PathnameContext,
  SearchParamsContext,
} from "next/dist/shared/lib/hooks-client-context.shared-runtime.js";

export function componentDom(
  t: TestContext,
  url = "https://website.example.com/",
) {
  const errors: Error[] = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (error: Error) => errors.push(error));
  // Resource loading and script execution stay disabled: providers are fixtures.
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url,
    pretendToBeVisual: true,
    virtualConsole,
  });
  const previous = new Map<string, PropertyDescriptor | undefined>();
  function global(name: string, value: unknown) {
    previous.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
    Object.defineProperty(globalThis, name, {
      configurable: true,
      writable: true,
      value,
    });
  }
  for (const name of [
    "window",
    "self",
    "document",
    "navigator",
    "location",
    "localStorage",
    "sessionStorage",
    "HTMLElement",
    "HTMLInputElement",
    "HTMLFormElement",
    "HTMLTextAreaElement",
    "HTMLSelectElement",
    "Event",
    "CustomEvent",
    "MouseEvent",
    "KeyboardEvent",
    "FormData",
    "MutationObserver",
  ])
    global(
      name,
      name === "window" || name === "self" ? dom.window : dom.window[name],
    );
  global("IS_REACT_ACT_ENVIRONMENT", true);
  global("fetch", async () => {
    throw new Error("Unexpected network request in a component test");
  });
  Object.defineProperty(dom.window, "crypto", { value: webcrypto });
  dom.window.HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  dom.window.HTMLDialogElement.prototype.close = function () {
    this.open = false;
    this.dispatchEvent(new dom.window.Event("close"));
  };
  const roots: import("react-dom/client").Root[] = [];
  const replacements: string[] = [];
  const router = {
    back() {},
    forward() {},
    refresh() {},
    hmrRefresh() {},
    prefetch() {},
    push() {},
    replace(path: string) {
      replacements.push(path);
    },
  };
  function routed(node: ReactNode) {
    return createElement(
      AppRouterContext.Provider,
      { value: router },
      createElement(
        PathnameContext.Provider,
        { value: dom.window.location.pathname },
        createElement(
          SearchParamsContext.Provider,
          {
            value: new URLSearchParams(dom.window.location.search),
          },
          node,
        ),
      ),
    );
  }
  async function mount(node: ReactNode) {
    // React's event system must initialize after the browser globals exist.
    const { createRoot } = await import("react-dom/client");
    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    roots.push(root);
    const render = async (value: ReactNode) => {
      await act(async () => {
        root.render(routed(value));
      });
    };
    await render(node);
    return {
      container,
      render,
      async unmount() {
        await act(async () => root.unmount());
        roots.splice(roots.indexOf(root), 1);
      },
    };
  }
  t.after(async () => {
    await act(async () => {
      for (const root of roots) root.unmount();
    });
    await setImmediate();
    dom.window.close();
    for (const [name, descriptor] of previous) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else Reflect.deleteProperty(globalThis, name);
    }
    assert.deepEqual(errors, [], "browser APIs should not fail silently");
  });
  return {
    window: dom.window,
    document: dom.window.document,
    mount,
    replacements,
  };
}

export async function flush() {
  await act(async () => {
    await setImmediate();
  });
}

export function button(root: ParentNode, label: RegExp) {
  const result = [...root.querySelectorAll<HTMLButtonElement>("button")].find(
    (element) => label.test(element.textContent || ""),
  );
  assert.ok(result, `Expected button ${label}`);
  return result;
}

export async function click(element: HTMLElement) {
  await act(async () => element.click());
}

export async function input(root: ParentNode, selector: string, value: string) {
  const element = root.querySelector<
    HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
  >(selector);
  assert.ok(element, `Expected input ${selector}`);
  const prototype =
    element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : element instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(
      element,
      value,
    );
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

export async function submit(form: HTMLFormElement) {
  await act(async () => {
    form.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
  });
}

export function json(body: unknown, status = 200) {
  return Response.json(body, { status });
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

export function publicEnv(
  t: TestContext,
  values: Record<string, string | undefined>,
) {
  for (const [key, value] of Object.entries(values)) {
    const previous = process.env[key];
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
    t.after(() => {
      if (previous === undefined) delete process.env[key];
      else process.env[key] = previous;
    });
  }
}
