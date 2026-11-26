import { ComponentProps } from "react";
import { Icon as BaseIcon, IconGlyph } from "./Icon";

// Icons only the notebook screens use; they load with those screens, not with the app shell.
const notebookPaths = {
  filter: "M4 7h16M7 12h10M10 17h4",
  donut: "M21 12a9 9 0 1 1-9-9v9z",
  dots: "M12 5h.01M12 12h.01M12 19h.01",
  edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  move: "M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3",
  sound: "M4 10v4h3l4 4V6L7 10zM15 9a4 4 0 0 1 0 6M18 7a7 7 0 0 1 0 10",
  note: "M5 4h14v12l-4 4H5zM15 20v-4h4M8 9h8M8 13h5",
  image: "M4 5h16v14H4zM4 16l5-5 4 4 2-2 5 5M15 9h.01",
  list: "M5 7h14M5 12h14M5 17h14",
  heart: "M12 20s-7-4.6-9-9a5 5 0 0 1 9-3 5 5 0 0 1 9 3c-2 4.4-9 9-9 9z",
  stop: "M7 7h10v10H7z",
  hint: "M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10c1 1 1 2 1 3h6c0-1 0-2 1-3a6 6 0 0 0-4-10z",
  folder: "M3 7h6l2 2h10v10H3z",
  cards: "M8 4h11v13M5 7h11v13H5z",
  pen: "M4 20l1-4L16 5l3 3L8 19zM14 7l3 3",
  paste: "M9 4h6v3H9zM6 5h3M15 5h3v15H6V5M9 12h6M9 16h6",
  undo: "M9 7L4 12l5 5M4 12h11a5 5 0 0 1 0 10h-3",
  question: "M9 9a3 3 0 1 1 4.5 2.6c-1 .6-1.5 1.2-1.5 2.4M12 18h.01",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  erase: "M8 20l-5-5L14 4l7 7-9 9zM8 20h13",
  turtle: "M4 15a6 6 0 0 1 12 0zM16 13h3a2 2 0 0 0 0-4h-2M6 15v3M14 15v3",
} as const;

type NotebookIconName = keyof typeof notebookPaths;

export function Icon({ name }: { name: ComponentProps<typeof BaseIcon>["name"] | NotebookIconName }) {
  return name in notebookPaths ? <IconGlyph d={notebookPaths[name as NotebookIconName]} /> : <BaseIcon name={name as ComponentProps<typeof BaseIcon>["name"]} />;
}
