import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { server } from "./src/mocks/server.js";

// jsdom has no ResizeObserver; antd's Table (rc-component) observes its size.
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// jsdom's CSS engine (nwsapi) can't evaluate antd's `:has(.ant-checkbox-input:focus-visible)`
// rule when an element in scope carries a Tailwind arbitrary-value class (e.g.
// `min-w-[240px]`): it rebuilds the relative selector without escaping the `[`/`]`
// and throws "is not a valid selector", aborting getComputedStyle. antd calls
// getComputedStyle while measuring scrollbars/wave ripples after clicks, so any
// interaction inside such a subtree would crash the test. Fall back to a safe,
// rule-free declaration when nwsapi throws so the real call's failure is contained.
const realGetComputedStyle = window.getComputedStyle.bind(window);
const gcsFallbackEl = document.createElement("div");
window.getComputedStyle = (element, pseudoElt) => {
  try {
    return realGetComputedStyle(element, pseudoElt);
  } catch {
    return realGetComputedStyle(gcsFallbackEl);
  }
};

// jsdom has no matchMedia; antd's responsive components (Table, Grid) call it.
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  });
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
