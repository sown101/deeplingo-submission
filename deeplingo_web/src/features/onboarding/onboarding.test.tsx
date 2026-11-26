import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { languages, learnerInitialization, languageProfile } from "../../contracts/backendV1Fixtures";
import { OnboardingApi } from "./onboardingApi";
import { OnboardingScreen } from "./OnboardingScreen";

vi.mock("../../app/AuthProvider", () => ({ useAuth: () => ({ publicQueryClient: undefined }) }));

function mount() {
  const saveProfile = vi.fn(async () => languageProfile);
  const onboarding = { loadProfile: async () => ({ learning_language: null, support_language: null, is_complete: false }),
    loadLanguages: async () => languages, saveProfile };
  render(<MemoryRouter initialEntries={["/onboarding"]}><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ContainerProvider container={{ onboarding } as unknown as AppContainer}><Routes>
      <Route path="/onboarding" element={<OnboardingScreen />} /><Route path="/home" element={<h1>Home</h1>} />
    </Routes></ContainerProvider></QueryClientProvider></MemoryRouter>);
  return saveProfile;
}

describe("Optional declared level", () => {
  it.each(["", "B1"])("allows onboarding with the optional level %s", async level => {
    const save = mount();
    await screen.findByRole("heading", { name: "Choose your languages" });
    await userEvent.click(within(screen.getByRole("group", { name: "Learning language" })).getByRole("radio", { name: /English/ }));
    await userEvent.click(within(screen.getByRole("group", { name: "Support language" })).getByRole("radio", { name: /Vietnamese/ }));
    expect(screen.getByLabelText("My level (optional)")).toHaveValue("");
    if (level) await userEvent.selectOptions(screen.getByLabelText("My level (optional)"), level);
    await userEvent.click(screen.getByRole("button", { name: "Start learning" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith({ learningLanguageCode: "en", supportLanguageCode: "vi", ...(level ? { declaredLevel: level } : {}) }));
    expect(await screen.findByRole("heading", { name: "Home" })).toBeVisible();
  });

  it.each([undefined, "", "B1"])("serializes a level only when supplied: %s", async declaredLevel => {
    const put = vi.fn(async () => languageProfile);
    const api = new OnboardingApi({ post: vi.fn(async () => learnerInitialization), put } as never);
    await api.saveProfile({ learningLanguageCode: "en", supportLanguageCode: "vi", ...(declaredLevel !== undefined ? { declaredLevel } : {}) });
    expect(put).toHaveBeenCalledWith("/learner/me/language-profile", { learning_language: "en", support_language: "vi", ...(declaredLevel !== undefined ? { declared_level: declaredLevel } : {}) });
  });
});
