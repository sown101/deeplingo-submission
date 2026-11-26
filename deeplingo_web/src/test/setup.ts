import "@testing-library/jest-dom/vitest";

// jsdom does not implement element scrolling; the watch transcript auto-follows playback.
if (!Element.prototype.scrollTo) Element.prototype.scrollTo = () => {};
