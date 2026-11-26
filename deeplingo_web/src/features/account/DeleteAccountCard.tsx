import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useContainer } from "../../app/container";
import { useAuth } from "../../app/AuthProvider";
import { T, useT } from "../../i18n/i18n";
import { ProfileRow } from "./ProfileParts";

// FR-6.1: delete the account and everything that belongs to it, after a typed confirmation. The server
// deletes only the signed-in learner's own account; shared content such as videos stays.
const CONFIRMATION = "DELETE";

export function DeleteAccountRow() {
  const t = useT();
  const { client } = useContainer();
  const { signOut } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function remove() {
    setBusy(true);
    setFailed(false);
    try {
      await client.post("/learner/me/account/delete", { confirm: CONFIRMATION });
    } catch {
      setFailed(true);
      setBusy(false);
      return;
    }
    await signOut().catch(() => undefined);
    navigate("/signin", { replace: true });
  }
  function close() { setOpen(false); setTyped(""); setFailed(false); }

  return (
    <ProfileRow icon="🗑" tone="danger" title={t("Delete my account")} subtitle={t("Words, notebooks, progress and what Tata knows. Cannot be undone.")}
      open={open} onToggle={next => (next ? setOpen(true) : close())}>
      <p className="pf-hint">
        <T>Deletes your account and everything that belongs to it: your words, notebooks, progress and what the agent knows about you. This cannot be undone. Videos shared by everyone stay.</T>
      </p>
      <label className="pf-confirm"><T word={CONFIRMATION}>{"Type {word} to confirm"}</T>
        <input value={typed} autoComplete="off" disabled={busy} onChange={(event) => setTyped(event.target.value)} />
      </label>
      <div className="pf-row__actions">
        <button type="button" className="dl-btn dl-btn--danger" disabled={typed !== CONFIRMATION || busy} onClick={() => void remove()}>
          <T>Delete my account and data</T>
        </button>
        <button type="button" className="pf-link-btn" disabled={busy} onClick={close}><T>Cancel</T></button>
      </div>
      {failed ? <p className="pf-error" role="alert"><T>Your account could not be deleted. Nothing was removed. Please try again.</T></p> : null}
    </ProfileRow>
  );
}
