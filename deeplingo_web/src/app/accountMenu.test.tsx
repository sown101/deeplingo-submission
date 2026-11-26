import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";

const { signOut } = vi.hoisted(() => ({ signOut: vi.fn() }));
vi.mock("./AuthProvider", () => ({ useAuth: () => ({ signOut }) }));
beforeEach(() => { vi.stubGlobal("scrollTo", vi.fn()); signOut.mockReset().mockResolvedValue(undefined); });
afterEach(() => vi.unstubAllGlobals());
function mount() {
  render(<MemoryRouter initialEntries={["/words"]}><Routes>
    <Route element={<AppShell />}><Route path="/words" element={<h1>Saved words</h1>} /></Route>
    <Route path="/signin" element={<h1>Sign in</h1>} />
  </Routes></MemoryRouter>);
}
describe("account menu", () => {
  it("keeps account actions inside the menu and restores focus after Escape", async () => {
    mount();
    expect(screen.queryByRole("menuitem", { name: "Sign out" })).not.toBeInTheDocument();
    const trigger = screen.getByRole("button", { name: "Account menu" });
    await userEvent.click(trigger);
    const menu = screen.getByRole("menu", { name: "Account menu" });
    expect(within(menu).getByRole("menuitem", { name: "Profile" })).toHaveAttribute("href", "/account");
    expect(within(menu).getByRole("menuitem", { name: "Settings" })).toHaveAttribute("href", "/account#learning-preferences");
    fireEvent.keyDown(document, { key: "ArrowDown" });
    expect(within(menu).getByRole("menuitem", { name: "Profile" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument(); expect(trigger).toHaveFocus();
    expect(signOut).not.toHaveBeenCalled();
  });
  it("closes on outside pointer and signs out only on explicit selection", async () => {
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Account menu" }));
    fireEvent.pointerDown(screen.getByRole("heading", { name: "Saved words" }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument(); expect(signOut).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Account menu" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    await waitFor(() => expect(signOut).toHaveBeenCalledOnce());
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  });
});
