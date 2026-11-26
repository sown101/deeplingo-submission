import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { useModalDialog } from "./modalA11y";

// Mirrors the real usage pattern: a dialog COMPONENT that mounts together
// with the dialog (ConceptSheet, ImportDialog), so the hook's mount-time
// focus capture sees the opener.
function TestDialog({ onClose }: { onClose: () => void }): React.ReactElement {
  const dialogRef = useModalDialog(onClose);
  return (
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="Test dialog" tabIndex={-1}>
      <input aria-label="Field" />
      <button type="button" onClick={onClose}>
        Inside
      </button>
    </div>
  );
}

function Harness({ onClose }: { onClose: () => void }): React.ReactElement {
  return (
    <div>
      <button type="button" onClick={onClose}>
        Opener
      </button>
      <TestDialog onClose={onClose} />
    </div>
  );
}

function ToggleHarness({ onClose }: { onClose: () => void }): React.ReactElement {
  const [open, setOpen] = useState(true);
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>
        Opener
      </button>
      {open ? (
        <TestDialog
          onClose={() => {
            setOpen(false);
            onClose();
          }}
        />
      ) : null}
    </div>
  );
}

describe("useModalDialog", () => {
  it("moves focus into the dialog on open", () => {
    render(<Harness onClose={vi.fn()} />);
    expect(screen.getByRole("dialog", { name: "Test dialog" })).toHaveFocus();
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Escape still closes after onClose identity changes", () => {
    const onClose = vi.fn();
    const { rerender } = render(<Harness onClose={onClose} />);
    const latest = vi.fn();
    rerender(<Harness onClose={latest} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(latest).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("keeps Tab cycling inside the dialog", async () => {
    const user = userEvent.setup();
    render(<Harness onClose={vi.fn()} />);
    const field = screen.getByLabelText("Field");
    const inside = screen.getByRole("button", { name: "Inside" });
    field.focus();
    await user.tab(); // field -> inside (last focusable)
    expect(document.activeElement).toBe(inside);
    await user.tab(); // wraps: last -> first
    expect(document.activeElement).toBe(field);
    await user.tab({ shift: true }); // wraps: first -> last
    expect(document.activeElement).toBe(inside);
  });

  it("restores focus to the opener when the dialog closes", async () => {
    const onClose = vi.fn();
    render(<ToggleHarness onClose={onClose} />);
    const opener = screen.getByRole("button", { name: "Opener" });
    opener.focus();
    fireEvent.click(opener); // mounts the dialog; opener had focus
    await screen.findByRole("dialog", { name: "Test dialog" });
    fireEvent.click(screen.getByRole("button", { name: "Inside" }));
    await vi.waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(opener);
  });
});
