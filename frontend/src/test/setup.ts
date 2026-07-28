import "@testing-library/jest-dom/vitest";

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (!("ResizeObserver" in globalThis)) {
  // jsdom does not implement ResizeObserver, required by recharts' ResponsiveContainer
  (globalThis as unknown as { ResizeObserver: typeof ResizeObserverMock }).ResizeObserver =
    ResizeObserverMock;
}
