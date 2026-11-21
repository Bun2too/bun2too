// next/server for rendering tests (tests/render.tsx): the real module, except that
// connection() resolves, since there is no request scope outside a Next.js server.
export * from "next/server.js";
export async function connection() {}
