import { LABEL_TEXT, percent, type CoverageLabel } from "./coverageModels";
import { T, useT } from "../../i18n/i18n";

// A short mark for the Library list: "Comfortable · about 96% known". Shown only when the server
// has a number; never blocks the card.
export function CoverageBadge({ label, coverage, languageCode }: { label: CoverageLabel; coverage: number; languageCode?: string | null }) {
  const t = useT();
  return (
    <>
      <span className={`badge coverage-${label}`}
            title={t("An estimate from the video's transcript, the dictionary and the words you know")}>
        <T v1={t(LABEL_TEXT[label])} v2={percent(coverage)}>{"{v1} · about {v2} known"}</T>
      </span>
      {languageCode === "zh" ? <span className="small"> ước tính tiếng Trung chưa được hiệu chuẩn</span> : null}
    </>
  );
}
