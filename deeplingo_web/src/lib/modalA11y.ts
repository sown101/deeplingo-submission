import { useEffect, useRef } from "react";

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// Shared modal dialog semantics (W06 pattern): focus moves into the dialog on
// open (unless the dialog already focused something, e.g. an autoFocus input),
// Tab cycles inside, Escape closes, and focus returns to the opener on close.
// The dialog must render role="dialog" aria-modal="true" on the element this
// ref is attached to.
export function useModalDialog<T extends HTMLElement = HTMLDivElement>(
  onClose: () => void,
): React.RefObject<T> {
  const dialogRef = useRef<T | null>(null);
  // Captured during FIRST RENDER — before React commits the DOM and applies
  // autoFocus — so it always holds the element focused before the dialog
  // opened, never an element inside the dialog itself.
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  if (restoreFocusRef.current === null) {
    restoreFocusRef.current =
      (document.activeElement as HTMLElement | null) ?? null;
  }

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.contains(document.activeElement)) {
      dialog.focus();
    }
    return () => {
      restoreFocusRef.current?.focus();
    };
    // Runs once per mounted dialog instance.
  }, []);

  useEffect(() => {
    function handleKeydown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      );
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !dialog.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !dialog.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", handleKeydown, true);
    return () => document.removeEventListener("keydown", handleKeydown, true);
  }, [onClose]);

  return dialogRef as React.RefObject<T>;
}
