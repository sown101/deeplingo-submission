import { SelectField } from "../../design/Controls";
import { T } from "../../i18n/i18n";
import type { RoleplayScenario } from "./companionModels";

export function RoleplaySetup({ scenarios, value, swapped, onScenario, onSwap }: {
  scenarios: RoleplayScenario[]; value: string; swapped: boolean;
  onScenario: (id: string) => void; onSwap: (value: boolean) => void;
}) {
  const scene = scenarios.find(item => item.id === value);
  const role = swapped ? 1 : 0;
  return <section className="dl-card stack agent-roleplay-setup">
    <div className="agent-roleplay-fields">
    <SelectField id="roleplay-situation" label={<T>Situation</T>} value={value} onChange={event => onScenario(event.target.value)}>
      {scenarios.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
    </SelectField>
    {scene ? <SelectField id="roleplay-learner-role" label={<T>Your role</T>} value={String(role)} onChange={event => onSwap(event.target.value === "1")}>
        {scene.roles.map((label, index) => <option key={index} value={String(index)}>{label}</option>)}
      </SelectField> : null}
    </div>
    {scene ? <>
      <p className="subhead">{scene.context}</p>
      <p className="subhead"><T>Tata's role</T>: <strong>{scene.roles[1 - role]}</strong></p>
      <p className="subhead"><T>Your goal</T>: {scene.goals[role]}</p>
    </> : null}
  </section>;
}
