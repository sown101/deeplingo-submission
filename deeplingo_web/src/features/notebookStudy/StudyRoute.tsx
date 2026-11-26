import { lazy } from "react";
import { Navigate, useParams } from "react-router-dom";

// One app route for the notebook's Flashcard and Writing screens keeps their loaders out of the first download.
const FlashcardScreen = lazy(() => import("./FlashcardScreen").then((m) => ({ default: m.FlashcardScreen })));
const WritingScreen = lazy(() => import("./WritingScreen").then((m) => ({ default: m.WritingScreen })));

export function StudyRoute() {
  const { mode } = useParams();
  if (mode === "flashcards") return <FlashcardScreen />;
  if (mode === "writing") return <WritingScreen />;
  return <Navigate to="/words/lists" replace />;
}
