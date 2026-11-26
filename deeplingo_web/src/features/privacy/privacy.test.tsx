import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { PrivacyScreen } from "./PrivacyScreen";
import { YourDataCard } from "./YourDataCard";

describe("privacy", () => {
  it("states what is kept, what is not, where data goes and how to exercise rights", () => {
    render(<MemoryRouter><PrivacyScreen /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Quyền riêng tư" })).toBeInTheDocument();
    expect(screen.getByText("Không lưu ghi âm giọng nói.")).toBeInTheDocument();
    for (const provider of ["Supabase", "Google Gemini (AI)", "Microsoft Azure Speech"]) {
      expect(screen.getByText(provider)).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: "trang Profile" })).toHaveAttribute("href", "/account");
  });

  it("downloads the learner's own export as a JSON file", async () => {
    const user = userEvent.setup();
    const get = vi.fn().mockResolvedValue({ format: "deeplingo-learner-export-v1" });
    const createObjectURL = vi.fn(() => "blob:export");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(
      <ContainerProvider container={{ client: { get } } as unknown as AppContainer}>
        <MemoryRouter><YourDataCard /></MemoryRouter>
      </ContainerProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Download my data" }));
    expect(get).toHaveBeenCalledWith("/learner/me/export", { timeoutMs: 60_000 });
    expect(click).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:export");
    click.mockRestore();
  });

  it("reports a failed download", async () => {
    const user = userEvent.setup();
    render(
      <ContainerProvider container={{ client: { get: vi.fn().mockRejectedValue(new Error("x")) } } as unknown as AppContainer}>
        <MemoryRouter><YourDataCard /></MemoryRouter>
      </ContainerProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Download my data" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The download failed");
  });
});
