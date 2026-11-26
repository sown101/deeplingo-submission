import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { ContainerProvider, type AppContainer } from "../../app/container";
import { AgentStudyRequests } from "./AgentStudyRequests";
import { parseAgentStudyRequests, type AgentStudyRequest } from "./companionModels";

const GRAMMAR: AgentStudyRequest = { id: "r1", kind: "grammar_redo", title: "Past simple", reason: "was/were" };
const WORD: AgentStudyRequest = { id: "r2", kind: "word_review", title: "airport", reason: null };

function mount(items: AgentStudyRequest[], profile: unknown = { learning_language: "en", support_language: "vi" }) {
  const state = { items: [...items] };
  const companion = {
    getStudyRequests: vi.fn(async () => [...state.items]),
    dismissStudyRequest: vi.fn(async (id: string) => { state.items = state.items.filter(item => item.id !== id); }),
  };
  const client = new QueryClient();
  if (profile) client.setQueryData(["language-profile"], profile);
  render(<MemoryRouter><QueryClientProvider client={client}>
    <ContainerProvider container={{ companion } as unknown as AppContainer}><AgentStudyRequests /></ContainerProvider>
  </QueryClientProvider></MemoryRouter>);
  return companion;
}

it("shows nothing when Tata asked for nothing", async () => {
  const companion = mount([]);
  await waitFor(() => expect(companion.getStudyRequests).toHaveBeenCalledWith("en", "vi"));
  expect(screen.queryByRole("button", { name: /To practise again/ })).toBeNull();
});

it("lists what to practise again behind one button; grammar links to its exercise; an item can be set aside", async () => {
  const user = userEvent.setup();
  const companion = mount([GRAMMAR, WORD]);
  const toggle = await screen.findByRole("button", { name: "To practise again (2)" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  await user.click(toggle);
  const list = screen.getByRole("list", { name: "To practise again" });
  expect(within(list).getByText("Past simple")).toBeInTheDocument();
  expect(within(list).getByText("airport")).toBeInTheDocument();
  expect(within(list).getAllByRole("link")).toHaveLength(1); // grammar only: a word closes when it is reviewed
  expect(within(list).getByRole("link", { name: "Practise" })).toHaveAttribute("href", "/words/lists?tab=grammar");
  await user.click(within(list).getByRole("button", { name: "Set aside: airport" }));
  expect(companion.dismissStudyRequest).toHaveBeenCalledWith("r2");
  expect(await screen.findByRole("button", { name: "To practise again (1)" })).toBeInTheDocument();
});

it("waits for the learning language before asking", () => {
  const companion = mount([GRAMMAR], null);
  expect(companion.getStudyRequests).not.toHaveBeenCalled();
});

it("drops a row it cannot show and refuses a response without items", () => {
  expect(parseAgentStudyRequests({ items: [
    { id: "a", kind: "grammar_redo", title: "Past simple", reason: null, created_at: "2026-11-18T00:00:00Z" },
    { id: "b", kind: "region_practice", title: null, reason: null },
    { id: "c", kind: "word_review", title: null, reason: null },
  ] }).map(item => item.id)).toEqual(["a", "c"]);
  expect(() => parseAgentStudyRequests({})).toThrow();
});
