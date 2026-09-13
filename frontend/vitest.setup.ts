import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement scrollIntoView (a real, well-known gap -- not a
// production code guard). components/chat/ConversationThread.tsx calls it
// to keep the latest message in view.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
