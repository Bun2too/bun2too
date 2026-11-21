/** @jsxRuntime automatic */
/** @jsxImportSource react */
// Render React server and client components to HTML in node:test, with no browser or
// Next.js server. Async server components are awaited first (React's static renderer
// cannot), and the server-only marker module is stubbed out.
import { registerHooks } from "node:module";
import {
  Children,
  cloneElement,
  isValidElement,
  type ReactElement,
  type ReactNode,
} from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import {
  PathnameContext,
  SearchParamsContext,
} from "next/dist/shared/lib/hooks-client-context.shared-runtime";

const stubs: Record<string, string> = {
  "server-only": new URL("./fixtures/empty-module.mjs", import.meta.url).href,
  "next/server": new URL("./fixtures/next-server.mjs", import.meta.url).href,
};
registerHooks({
  resolve(specifier, context, next) {
    const url = stubs[specifier];
    return url ? { url, shortCircuit: true } : next(specifier, context);
  },
  // Stylesheets are Next.js's to bundle; here they are empty modules.
  load(url, context, next) {
    if (url.endsWith(".css"))
      return { format: "module", source: "", shortCircuit: true };
    return next(url, context);
  },
});

type Component = (props: unknown) => ReactNode | Promise<ReactNode>;

// Calls each function component it can: async ones always, sync ones unless they need
// React's render (hooks), which throw outside it; those stay for renderToStaticMarkup.
export async function resolveTree(node: ReactNode): Promise<ReactNode> {
  if (Array.isArray(node)) return Promise.all(node.map(resolveTree));
  if (!isValidElement(node)) return node;
  const element = node as ReactElement<{ children?: ReactNode }>;
  if (typeof element.type === "function") {
    const type = element.type as Component;
    let output: ReactNode | Promise<ReactNode>;
    try {
      output = type(element.props);
    } catch (error) {
      if (type.constructor.name === "AsyncFunction") throw error;
      return withResolvedChildren(element);
    }
    return resolveTree(await output);
  }
  return withResolvedChildren(element);
}

async function withResolvedChildren(
  element: ReactElement<{ children?: ReactNode }>,
) {
  const { children } = element.props;
  if (children === undefined) return element;
  const resolved = await resolveTree(Children.toArray(children));
  return cloneElement(element, undefined, ...(resolved as ReactNode[]));
}

// The app router's contexts, so client components that read the route render as they
// would on that page. Navigation calls are recorded, not performed.
export const navigations: string[] = [];
const router = {
  push: (href: string) => void navigations.push(href),
  replace: (href: string) => void navigations.push(href),
  refresh: () => {},
  prefetch: () => {},
  back: () => {},
  forward: () => {},
};

export async function render(
  node: ReactNode,
  pathname = "/",
  search = "",
): Promise<string> {
  const tree = await resolveTree(node);
  return renderToStaticMarkup(
    <AppRouterContext.Provider value={router as never}>
      <PathnameContext.Provider value={pathname}>
        <SearchParamsContext.Provider
          value={new URLSearchParams(search) as never}
        >
          {tree}
        </SearchParamsContext.Provider>
      </PathnameContext.Provider>
    </AppRouterContext.Provider>,
  );
}
